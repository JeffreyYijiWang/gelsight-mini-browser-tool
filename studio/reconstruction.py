"""Pluggable normal prediction reusing the repository's exact Mini MLP weights."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .inputs import image_array, quality
from .records import CalibrationProfile, SurfacePatch
from .surface import check, integrate_normals

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_MODEL = ROOT / "gelsight_p5/models/nnmini_mlp_weights.bin"


class NormalPredictor(Protocol):
    def predict(self, rgb: np.ndarray, baseline: np.ndarray | None) -> np.ndarray: ...


class MiniMLP:
    def __init__(self, path=BUNDLED_MODEL):
        if not Path(path).is_file():
            raise ValueError(f"Configured Mini weights are missing: {Path(path).name}. Restore weights or select another calibration.")
        packed=np.fromfile(path,dtype="<f4")
        if packed.size!=8834 or not np.isfinite(packed).all():
            raise ValueError("Mini weight file is malformed: expected 8834 finite little-endian float32 values.")
        self.layers=[]; offset=0
        for n_in,n_out in ((5,64),(64,64),(64,64),(64,2)):
            weight=packed[offset:offset+n_in*n_out].reshape(n_out,n_in);offset+=n_in*n_out
            bias=packed[offset:offset+n_out];offset+=n_out
            self.layers.append((weight,bias))

    def predict(self,rgb,baseline=None):
        h,w=rgb.shape[:2]
        y,x=np.indices((h,w),dtype=np.float32)
        # Match gelsight-core.js: B,G,R,y/height,x/width. Never RGB order.
        features=np.concatenate((rgb[...,::-1].astype(np.float32)/255,(y/h)[...,None],(x/w)[...,None]),axis=-1).reshape(-1,5)
        result=[]
        for batch in np.array_split(features,max(1,len(features)//8192)):
            v=batch
            for i,(weight,bias) in enumerate(self.layers):
                v=v@weight.T+bias
                if i<3: v=np.maximum(v,0)
            result.append(v)
        xy=np.concatenate(result).reshape(h,w,2)
        length=np.linalg.norm(xy,axis=-1,keepdims=True)
        xy*=np.minimum(1.,.995/np.maximum(length,1e-12))
        # Network's Y normal is in image-down coordinates; convert to surface Y-up.
        return np.stack((xy[...,0],-xy[...,1],np.sqrt(1-np.sum(xy*xy,axis=-1))),axis=-1)


def polynomial_features(rgb,baseline):
    if baseline is None:
        raise ValueError("Polynomial normal prediction requires a baseline image.")
    color=(rgb.astype(float)-baseline.astype(float))/255
    y,x=np.indices(rgb.shape[:2],dtype=float)
    a=np.concatenate((color, (x/rgb.shape[1])[...,None],(y/rgb.shape[0])[...,None]),axis=-1)
    return np.concatenate((np.ones((*a.shape[:2],1)),a,a*a,a[...,0:1]*a[...,1:2],a[...,1:2]*a[...,2:3],a[...,0:1]*a[...,2:3]),axis=-1)


class PolynomialNormals:
    def __init__(self,path):
        try:
            with np.load(path,allow_pickle=False) as z: self.coefficients=z["coefficients"]
        except Exception as exc:
            raise ValueError("Configured polynomial normal calibration failed to load.") from exc
        if self.coefficients.shape!=(14,3) or not np.isfinite(self.coefficients).all():
            raise ValueError("Calibration coefficients must be finite 14×3 values.")

    def predict(self,rgb,baseline):
        n=polynomial_features(rgb,baseline)@self.coefficients
        return n/np.maximum(np.linalg.norm(n,axis=-1,keepdims=True),1e-9)


class TorchScriptNormals:
    def __init__(self,path):
        if not Path(path).is_file(): raise ValueError("Configured learned normal model is missing. Supply locally trained TorchScript weights.")
        try:
            import torch
            self.torch=torch
            self.model=torch.jit.load(str(path),map_location="cpu").eval()
        except ImportError as exc:
            raise ValueError("TorchScript adapter needs optional PyTorch. Install torch in the Studio environment.") from exc
        except Exception as exc:
            raise ValueError("Configured TorchScript model failed to load; no relative fallback was used.") from exc

    def predict(self,rgb,baseline):
        if baseline is None: raise ValueError("Learned 8-channel model needs a baseline image.")
        y,x=np.indices(rgb.shape[:2],dtype=np.float32)
        tensor=np.concatenate((rgb/255.,baseline/255.,(x/rgb.shape[1])[...,None],(y/rgb.shape[0])[...,None]),axis=-1)
        with self.torch.no_grad():
            n=self.model(self.torch.from_numpy(tensor.transpose(2,0,1)[None].astype(np.float32))).detach().cpu().numpy()
        if n.shape!=(1,3,*rgb.shape[:2]): raise ValueError("TorchScript output must be N×3×H×W surface-coordinate normals.")
        n=n[0].transpose(1,2,0)
        return n/np.maximum(np.linalg.norm(n,axis=-1,keepdims=True),1e-9)


def reconstruct(store,frame_id,settings=None,progress=None):
    settings=settings or {}
    frame=store.get("frames",frame_id)
    if frame["kind"]!="rgb": raise ValueError("Reconstruction expects a tactile RGB frame.")
    session=store.get("sessions",frame["session_id"])
    rgb=image_array(store.path(frame["raw_file"]).read_bytes())
    baseline_id=settings.get("baseline_id") or session.get("baseline_id")
    baseline=None
    if baseline_id:
        baseline_frame=store.get("frames",baseline_id)
        if baseline_frame["session_id"]!=frame["session_id"]: raise ValueError("Baseline must belong to the same session.")
        baseline=image_array(store.path(baseline_frame["raw_file"]).read_bytes())
    calibration=None
    crop=frame['settings'].get('sample_crop')
    if crop:
        from .samples import crop_box
        if baseline is not None and (baseline.shape!=rgb.shape or baseline_frame['settings'].get('sample_crop')!=crop):
            raise ValueError('Baseline resolution and crop must match this sample. Capture a new baseline.')
        x0,y0,x1,y1=crop_box((rgb.shape[1],rgb.shape[0]),crop)
        rgb=rgb[y0:y1,x0:x1]
        if baseline is not None:baseline=baseline[y0:y1,x0:x1]
        settings={**settings,'source_crop':crop}
    model_path=BUNDLED_MODEL
    adapter="mini_mlp"
    if settings.get("calibration_id"):
        calibration=CalibrationProfile(**store.get("calibrations",settings["calibration_id"]))
        if (session.get("sensor_id"),session.get("gel_id"))!=(calibration.sensor_id,calibration.gel_id):
            raise ValueError("Calibration sensor/gel IDs do not match this session. Set verified session IDs first.")
        if (rgb.shape[1],rgb.shape[0])!=(calibration.width,calibration.height):
            raise ValueError("Calibration dimensions do not match the input image; use its original crop/resolution.")
        model_path=BUNDLED_MODEL if calibration.weights=="bundled_mini" else store.path(calibration.weights)
        adapter=calibration.adapter
        if calibration.camera_matrix is not None:
            matrix=np.asarray(calibration.camera_matrix,float); distortion=np.asarray(calibration.distortion or [],float)
            rgb=cv2.undistort(rgb,matrix,distortion)
            if baseline is not None: baseline=cv2.undistort(baseline,matrix,distortion)
    elif max(rgb.shape[:2])>320:
        scale=320/max(rgb.shape[:2]); size=(round(rgb.shape[1]*scale),round(rgb.shape[0]*scale))
        rgb=cv2.resize(rgb,size,interpolation=cv2.INTER_AREA)
        if baseline is not None: baseline=cv2.resize(baseline,size,interpolation=cv2.INTER_AREA)
    if rgb.shape[0]*rgb.shape[1]>1_000_000: raise ValueError("Reconstruction exceeds the one-million-pixel budget.")
    mask,q=quality(rgb,baseline,border=int(settings.get("border",4)),marker_high=int(settings.get("marker_high",45)),contact_threshold=float(settings.get("contact_threshold",8)))
    roi=settings.get("roi")
    if roi:
        x0,y0,x1,y1=[float(v) for v in roi]
        if not (0<=x0<x1<=1 and 0<=y0<y1<=1): raise ValueError("ROI must be normalized x0,y0,x1,y1 inside [0,1].")
        selection=np.zeros(mask.shape,bool);selection[int(y0*mask.shape[0]):int(y1*mask.shape[0]),int(x0*mask.shape[1]):int(x1*mask.shape[1])]=True
        mask &= selection
    if q["rejected"] or mask.sum()<16: raise ValueError("Frame rejected: insufficient sharp valid contact. Check baseline, markers, lighting and ROI.")
    check(progress,.1,"Predicting normals")
    predictor={"mini_mlp":MiniMLP,"polynomial":PolynomialNormals,"torchscript":TorchScriptNormals}[adapter](model_path)
    normals=predictor.predict(rgb,baseline)
    metric=bool(calibration and calibration.validated)
    spacing=calibration.pixel_spacing_mm if metric else (1.,1.)
    if calibration and adapter!="mini_mlp" and calibration.normal_convention=="image_y_down": normals[...,1]*=-1
    if baseline is not None:
        bnormals=predictor.predict(baseline,baseline)
        if calibration and adapter!="mini_mlp" and calibration.normal_convention=="image_y_down": bnormals[...,1]*=-1
        # Remove untouched slope bias before integration, maintaining masks.
        nx=normals[...,0]/np.maximum(normals[...,2],.05)-bnormals[...,0]/np.maximum(bnormals[...,2],.05)
        ny=normals[...,1]/np.maximum(normals[...,2],.05)-bnormals[...,1]/np.maximum(bnormals[...,2],.05)
        normals=np.stack((nx,ny,np.ones_like(nx)),axis=-1)
        normals/=np.linalg.norm(normals,axis=-1,keepdims=True)
    if calibration: normals[...,:2]*=calibration.object_sign
    height,mask=integrate_normals(normals,mask,spacing,progress=progress)
    patch=SurfacePatch(name=Path(frame["source_name"]).stem+" relief",region=session["region"],source_ids=[frame_id],session_id=session["id"],
                       state="calibrated" if metric else "uncalibrated",units="mm" if metric else "relative",pixel_spacing=spacing if metric else None,
                       calibration_id=calibration.id if calibration else None,validation_notes=calibration.validation_notes if metric else "",
                       synthetic=session.get("synthetic",False),width=rgb.shape[1],height=rgb.shape[0],settings=settings,quality=q,
                       height_reference="valid connected components individually mean-zero; positive object relief",
                       provenance=[{"operation":"normal prediction and masked Poisson integration","adapter":adapter,
                                    "model_sha256":hashlib.sha256(Path(model_path).read_bytes()).hexdigest(),"baseline_id":baseline_id,"metric_validated":metric}])
    return store.put_patch(patch,height,mask,rgb=rgb,normals=normals)
