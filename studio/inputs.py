from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

import cv2
import numpy as np
from PIL import Image

from .records import CaptureSession, Frame, SurfacePatch
from .surface import integrate_normals, normals_from_height

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
MESH_EXTENSIONS = {".stl", ".obj", ".ply", ".glb", ".3mf"}
MAX_UPLOAD = 128 * 1024 * 1024


def image_array(data, color=True):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width*image.height > 24_000_000:
                raise ValueError("Image exceeds 24 megapixels. Crop before import.")
            return np.array(image.convert("RGB") if color else image)
    except (OSError,Image.DecompressionBombError) as exc:
        raise ValueError("Image could not be decoded. Use PNG, TIFF, JPEG or a float NPY height field.") from exc


def safe_numpy(data):
    if data[:2]==b'PK':
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(i.file_size for i in archive.infolist())>MAX_UPLOAD*2:
                raise ValueError("Expanded array archive exceeds 256 MiB.")
    else:
        buffer=io.BytesIO(data)
        version=np.lib.format.read_magic(buffer)
        shape,_,_=np.lib.format._read_array_header(buffer,version)
        if np.prod(shape,dtype=object)>12_000_000:
            raise ValueError("Array exceeds the 12-million-value import budget.")
    return np.load(io.BytesIO(data),allow_pickle=False)


def quality(rgb, baseline=None, border=4, marker_high=45, contact_threshold=8.):
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    mask = np.ones(gray.shape, bool)
    border = int(np.clip(border, 0, min(gray.shape)//4))
    if border:
        mask[:border] = mask[-border:] = False
        mask[:, :border] = mask[:, -border:] = False
    markers = cv2.dilate((gray <= marker_high).astype(np.uint8), np.ones((5,5), np.uint8)) > 0
    saturated = np.any(rgb >= 253, axis=-1)
    mask &= ~markers & ~saturated
    if baseline is not None:
        if baseline.shape != rgb.shape:
            raise ValueError("Baseline and frame dimensions must match.")
        diff = np.linalg.norm(rgb.astype(float)-baseline.astype(float), axis=-1)
        contact = cv2.morphologyEx((diff > contact_threshold).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7,7), np.uint8)) > 0
        # Sensor-fixed dark spots are excluded in either the baseline or frame.
        fixed = cv2.cvtColor(baseline, cv2.COLOR_RGB2GRAY) <= marker_high
        mask &= contact & ~(cv2.dilate(fixed.astype(np.uint8), np.ones((5,5),np.uint8))>0)
    sharpness = float(np.var(cv2.Laplacian(gray, cv2.CV_32F)[mask])) if mask.any() else 0.
    score = float(np.clip(mask.mean()*min(1.,sharpness/100),0,1))
    return mask, {"valid_fraction": float(mask.mean()), "sharpness": sharpness,
                  "quality_score": score, "quality_score_is_probability": False,
                  "contact_status": "baseline difference" if baseline is not None else "unverified; no baseline",
                  "marker_fraction": float(markers.mean()), "saturated_fraction": float(saturated.mean()),
                  "rejected": bool(mask.mean()<.08 or sharpness<1.)}


def import_bytes(store, name, data, kind="rgb", session_id=None, settings=None):
    settings = settings or {}
    if not data or len(data)>MAX_UPLOAD:
        raise ValueError("Input must be nonempty and at most 128 MiB.")
    name = Path(name).name
    suffix = Path(name).suffix.lower()
    if suffix == ".zip":
        return import_legacy_zip(store, name, data, settings)
    session = CaptureSession(**store.get("sessions", session_id)) if session_id else CaptureSession(name=Path(name).stem, region=settings.get("region","custom"))
    if not session_id:
        store.save("sessions", session)
    raw, digest = store.raw(data, suffix)
    if suffix in MESH_EXTENSIONS:
        from .printing import load_mesh
        mesh, inspection = load_mesh(store.path(raw), settings.get("mesh_units"))
        frame = Frame(session_id=session.id, source_name=name, sha256=digest, order=len(session.frame_ids),
                      width=0, height=0, raw_file=raw, kind="mesh", settings={**settings,"inspection":inspection})
    elif kind == "rgb":
        rgb = image_array(data)
        if max(rgb.shape[:2]) > 4096:
            raise ValueError("RGB processing accepts at most 4096 pixels per side; use a crop.")
        _, q = quality(rgb)
        frame = Frame(session_id=session.id, source_name=name, sha256=digest, order=len(session.frame_ids),
                      width=rgb.shape[1], height=rgb.shape[0], raw_file=raw, quality=q, settings=settings)
    else:
        if suffix == ".npy":
            height = safe_numpy(data)
            mask = None
        elif suffix == ".npz":
            with safe_numpy(data) as z:
                height = z["normals" if kind=="normal" else "height"]
                mask = z["mask"] if "mask" in z else None
        else:
            image = Image.open(io.BytesIO(data))
            height = image_array(data, color=kind=="normal")
            mask = None
            if kind == "height" and height.ndim == 2:
                if "DepthMin" in image.info and "DepthMax" in image.info:
                    low, high = float(image.info["DepthMin"]),float(image.info["DepthMax"])
                    height = height.astype(float)/65535*(high-low)+low
                else:
                    height = height.astype(float)*float(settings.get("scale_per_code",1.))+float(settings.get("bias",0.))
        metric = settings.get("units") == "mm"
        spacing = settings.get("pixel_spacing") if metric else None
        if metric and (not spacing or not settings.get("validation_notes")):
            raise ValueError("Metric import needs mm XY pixel spacing and validation notes. Otherwise import as relative.")
        if kind == "normal":
            if height.ndim != 3 or height.shape[-1] != 3:
                raise ValueError("Normal map must have 3 channels.")
            normals = height.astype(float)/127.5-1 if height.dtype == np.uint8 else height.astype(float)
            height, mask = integrate_normals(normals, np.ones(normals.shape[:2],bool) if mask is None else mask,
                                             spacing=spacing or (1.,1.), convention=settings.get("convention","opengl"))
        elif height.ndim != 2:
            raise ValueError("Height input must be a single-channel map; RGB tactile brightness is not height.")
        frame = Frame(session_id=session.id, source_name=name, sha256=digest, order=len(session.frame_ids),
                      width=height.shape[1], height=height.shape[0], raw_file=raw, kind=kind, settings=settings)
        patch = SurfacePatch(name=Path(name).stem, region=session.region, source_ids=[frame.id], session_id=session.id,
                             state="calibrated" if metric else "uncalibrated", units="mm" if metric else "relative",
                             pixel_spacing=spacing, validation_notes=settings.get("validation_notes",""),
                             width=frame.width, height=frame.height, settings=settings,
                             provenance=[{"operation":"normal integration" if kind=="normal" else "height import", "sha256":digest}])
        patch_record = store.put_patch(patch, height, mask)
    store.save("frames", frame)
    session.frame_ids.append(frame.id)
    store.save("sessions", session)
    return {"session": session.model_dump(mode="json"), "frame": frame.model_dump(mode="json"),
            "patch": patch_record if kind in ("height","normal") and suffix not in MESH_EXTENSIONS else None}


def import_legacy_zip(store, name, data, settings):
    """Read known entries only; never extract paths from untrusted archives."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if sum(i.file_size for i in z.infolist()) > MAX_UPLOAD*2:
            raise ValueError("Expanded archive exceeds the import budget.")
        candidates = [x for x in ("depth_solver_units_16bit.png","depth_16bit.png","height.npy") if x in z.namelist()]
        if not candidates:
            raise ValueError("Expected an original GelSight export ZIP with a depth map.")
        # Never promote legacy solver units to mm via user override.
        result = import_bytes(store, candidates[0], z.read(candidates[0]), "height", settings={**settings,"units":"relative"})
        if "capture.png" in z.namelist():
            import_bytes(store, "capture.png", z.read("capture.png"), session_id=result["session"]["id"])
        store.raw(data,".zip")
        return result


def import_video(store, name, data, settings=None, progress=None):
    settings = settings or {}
    raw, _ = store.raw(data, Path(name).suffix)
    cap = cv2.VideoCapture(str(store.path(raw)))
    if not cap.isOpened():
        raise ValueError("Video could not be decoded. Export an ordered PNG image sequence instead.")
    session = CaptureSession(name=Path(name).stem, region=settings.get("region","custom"))
    store.save("sessions",session)
    stride = max(1,int(settings.get("stride",10)))
    count, imported = 0, 0
    try:
        while imported < 120:
            ok, bgr = cap.read()
            if not ok:
                break
            if count % stride == 0:
                if progress:
                    progress(min(.9, imported/120), f"Importing video frame {count}")
                ok, png = cv2.imencode(".png",bgr)
                record = import_bytes(store,f"frame-{count:06d}.png",png.tobytes(),session_id=session.id)
                frame = record["frame"]
                frame["timestamp_seconds"] = float(cap.get(cv2.CAP_PROP_POS_MSEC)/1000)
                frame["settings"] = {"video_source":raw, "original_frame":count}
                store.save("frames",frame)
                imported+=1
            count+=1
    finally:
        cap.release()
    if not imported:
        raise ValueError("Video contained no decodable frames.")
    return {"session":store.get("sessions",session.id), "imported":imported, "limit":120}


def synthetic_demo(store, seed=7, size=160):
    """Analytic, deterministic artificial wrinkles. Never represents a human sample."""
    rng = np.random.default_rng(seed)
    y,x = np.mgrid[0:size,0:size]/(size-1)
    h = .015*np.sin(2*np.pi*x)*np.sin(2*np.pi*y)
    for center, depth, width in ((.23,.08,.013),(.53,.05,.022),(.78,.1,.009)):
        curve = center+.035*np.sin(2*np.pi*y+center*5)
        h -= depth*np.exp(-((x-curve)/width)**2)
    h += .003*np.sin(x*140+y*25)*np.sin(y*105)
    mask = np.ones(h.shape,bool)
    patch = SurfacePatch(name="Synthetic • narrow valleys",region="custom",state="calibrated",units="mm",
                         pixel_spacing=(10/(size-1),10/(size-1)),validation_notes="Analytic synthetic field, exact authored mm coordinates; not sensor validation.",
                         synthetic=True,width=size,height=size,provenance=[{"operation":"analytic fixture","seed":seed,"not_human_data":True}])
    out = store.put_patch(patch,h,mask)
    second = patch.model_copy(update={"id":__import__('uuid').uuid4().hex,"name":"Synthetic • paired shallower valleys","parent_id":patch.id})
    out2 = store.put_patch(second,h*.55,mask)
    # Nonperiodic texture crops provide a reproducible image-only atlas example.
    canvas = rng.uniform(55,210,(260,420,3)).astype(np.uint8)
    canvas = cv2.GaussianBlur(canvas,(3,3),.5)
    for _ in range(70):
        p = tuple(rng.integers([0,0],[420,260]).tolist())
        cv2.circle(canvas,p,int(rng.integers(2,10)),tuple(rng.integers(60,220,3).tolist()),-1)
    session = CaptureSession(name="Synthetic overlapping tactile-like crops",synthetic=True)
    store.save("sessions",session)
    for i,(cx,cy) in enumerate(((0,0),(90,0),(180,30),(90,60),(0,60))):
        image=canvas[cy:cy+180,cx:cx+220]
        buf=io.BytesIO();Image.fromarray(image).save(buf,format="PNG")
        import_bytes(store,f"synthetic-{i}.png",buf.getvalue(),session_id=session.id,settings={"known_translation":[cx,cy],"synthetic":True})
    return {"patches":[out,out2],"session":store.get("sessions",session.id)}
