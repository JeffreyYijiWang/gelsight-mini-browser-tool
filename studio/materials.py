from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

from .records import ExportManifest, MaterialAsset, SurfacePatch
from .surface import check, detrend, encode_height, fill_nearest, normals_from_height, seamless, smooth_valid, wrinkles


def png(path, values):
    values=np.asarray(values)
    Image.fromarray(values).save(path)


def gray8(values, mask=None):
    valid=np.isfinite(values) if mask is None else mask
    lo,hi=float(values[valid].min()),float(values[valid].max())
    return np.rint(np.clip((values-lo)/max(hi-lo,1e-12),0,1)*255).astype(np.uint8)


def sphere_thumbnail(height, mask, color="#929795", size=480):
    """Deterministic orthographic material preview from the source, no invented grain."""
    source=fill_nearest(height,mask)
    y,x=np.mgrid[-1.13:1.13:complex(size),-1.13:1.13:complex(size)]
    inside=x*x+y*y<1
    z=np.sqrt(np.maximum(0,1-x*x-y*y))
    u=(np.arctan2(x,z)/(2*np.pi)+.5)%1
    v=np.arccos(np.clip(-y,-1,1))/np.pi
    # Tangent-space slopes perturb the sphere normal; the source remains unchanged.
    local,_=normals_from_height(source,mask=np.ones_like(mask))
    coordinates=[v*(source.shape[0]-1),u*(source.shape[1]-1)]
    nx=ndimage.map_coordinates(local[...,0],coordinates,order=1)
    ny=ndimage.map_coordinates(local[...,1],coordinates,order=1)
    normal=np.stack((x+nx*.65,-y+ny*.65,z),axis=-1)
    normal/=np.maximum(np.linalg.norm(normal,axis=-1,keepdims=True),1e-8)
    light=np.array([-.55,.65,.7]);light/=np.linalg.norm(light)
    shade=np.clip(.3+.7*np.maximum(normal@light,0),0,1)
    from PIL import ImageColor
    rgb=np.array(ImageColor.getrgb(color),float)
    result=np.empty((size,size,3),np.uint8);result[:]=[231,234,224]
    result[inside]=np.clip(rgb*shade[inside,None],0,255).astype(np.uint8)
    return result


def derive_patch(store,patch_id,settings):
    source,a=store.patch(patch_id)
    h,mask,invented=a["height"].copy(),a["mask"].copy(),a["synthetic_mask"].copy()
    roi=settings.get("roi")
    if roi:
        x0,y0,x1,y1=roi
        if not (0<=x0<x1<=1 and 0<=y0<y1<=1): raise ValueError("ROI must be normalized and have positive area.")
        ys,xs=slice(int(y0*len(h)),max(int(y1*len(h)),int(y0*len(h))+2)),slice(int(x0*h.shape[1]),max(int(x1*h.shape[1]),int(x0*h.shape[1])+2))
        h,mask,invented=h[ys,xs],mask[ys,xs],invented[ys,xs]
    if not mask.any(): raise ValueError("Selected ROI has no valid data.")
    if settings.get("fill_gaps"):
        h=fill_nearest(h,mask);invented|=~mask;mask[:]=True
    if settings.get("detrend",0)>0 or settings.get("smoothing",0)>0:
        h,_=detrend(h,mask,float(settings.get("detrend",0)),float(settings.get("smoothing",0)))
    if settings.get("seamless"):
        h,new=seamless(h,mask,settings.get("seam_band",12));invented|=new;mask[:]=True
    if settings.get("invert"): h=-h
    h*=float(settings.get("height_gain",1.))
    patch=SurfacePatch(**{**source.model_dump(),"id":__import__('uuid').uuid4().hex,
                          "name":source.name+" • edited","parent_id":source.id,"version":"artist-derived",
                          "settings":settings,"provenance":source.provenance+[{"operation":"non-destructive edit","source_id":source.id,"settings":settings}],
                          "quality":{**source.quality,"measurement_allowed":False}})
    # Retain the known unit transform, but all post-edit measurement is disabled.
    return store.put_patch(patch,h,mask,invented)


def analyze_patch(store,patch_id,settings=None):
    settings=settings or {}
    patch,a=store.patch(patch_id)
    h=a["height"];mask=a["mask"] & ~a["synthetic_mask"]
    working,_=detrend(h,mask,float(settings.get("detrend",12)),float(settings.get("smoothing",.5)))
    metric=patch.state=="calibrated" and patch.version=="original" and not patch.quality.get("measurement_allowed") is False
    radius=int(settings.get("radius_px",8))
    if settings.get("radius_mm") is not None:
        if not metric: raise ValueError("A physical neighborhood radius requires a calibrated original patch.")
        radius=int(round(float(settings["radius_mm"])/min(patch.pixel_spacing)))
    valleys,summary=wrinkles(working,mask,radius,float(settings.get("sensitivity",.01)),metric,a["synthetic_mask"])
    row=int(np.clip(settings.get("profile_row",h.shape[0]//2),0,h.shape[0]-1))
    distance=np.arange(h.shape[1])*(patch.pixel_spacing[0] if metric else 1.)
    values=[float(v) if ok else None for v,ok in zip(working[row],mask[row])]
    return {"patch_id":patch_id,"summary":summary,"profile":{"x":distance.tolist(),"height":values,"row":row,"units":"mm" if metric else "relative"},
            "width":h.shape[1],"height":h.shape[0],"valleys":valleys.astype(int).tolist(),"detrended":working.tolist(),"synthetic":patch.synthetic}


def brush_tip(height,mask,settings):
    tip=gray8(height,mask).astype(float)/255
    low,high=float(settings.get("black",0)),float(settings.get("white",1))
    if not 0<=low<high<=1: raise ValueError("Brush levels require 0 ≤ black < white ≤ 1.")
    tip=np.clip((tip-low)/(high-low),0,1)**float(np.clip(settings.get("gamma",1),.05,10))
    if settings.get("tip_invert"): tip=1-tip
    if settings.get("threshold") is not None: tip=(tip>=float(settings["threshold"])).astype(float)
    edge=float(np.clip(settings.get("edge_falloff",.15),0,1))
    if edge>0:
        y,x=np.indices(tip.shape,dtype=float);x=(x/(tip.shape[1]-1)-.5)*2;y=(y/(tip.shape[0]-1)-.5)*2
        fade=np.clip((1-np.maximum(abs(x),abs(y)))/edge,0,1)
        tip=1-(1-tip)*fade
    tip[~mask]=1
    angle=float(settings.get("rotation",0))
    if angle: tip=ndimage.rotate(tip,angle,reshape=False,order=1,mode="constant",cval=1)
    return np.rint(tip*255).astype(np.uint8)


def build_material(store,patch_id,settings=None,progress=None):
    settings=settings or {}
    patch,a=store.patch(patch_id)
    h,mask=a["height"],a["mask"]
    if max(h.shape)>2048:
        raise ValueError("Material textures are limited to 2048 pixels per side; crop or explicitly resample first.")
    asset=MaterialAsset(name=settings.get("name",patch.name),patch_id=patch.id,region=patch.region,
                        synthetic=patch.synthetic,state=patch.state,settings=settings,
                        provenance=[{"operation":"material derivation","patch_id":patch.id,"version":patch.version}])
    asset.directory=f"materials/{asset.id}"
    directory=store.path(asset.directory);directory.mkdir()
    spacing=patch.pixel_spacing or (1.,1.)
    check(progress,.1,"Separating displacement and normal detail")
    band=float(np.clip(settings.get("frequency_split",3.),.1,64))
    coarse=smooth_valid(h,mask,band)
    fine=h-coarse
    if settings.get("full_relief_override"):
        coarse=h.copy();fine=h.copy()
    encoded,encoding=encode_height(h,mask)
    coarse_encoded,coarse_encoding=encode_height(coarse,mask)
    np.save(directory/"height.npy",h)
    np.save(directory/"displacement.npy",coarse.astype(np.float32))
    png(directory/"height_16.png",encoded)
    Image.fromarray(encoded).save(directory/"height_16.tiff")
    png(directory/"displacement_16.png",coarse_encoded)
    png(directory/"valid_mask.png",mask.astype(np.uint8)*255)
    png(directory/"synthetic_mask.png",a["synthetic_mask"].astype(np.uint8)*255)
    normal,normal_valid=normals_from_height(fine,spacing,mask,"opengl")
    full_normal,_=normals_from_height(h,spacing,mask,"opengl")
    png(directory/"normal_opengl.png",np.rint((normal*.5+.5)*255).astype(np.uint8))
    normal[...,1]*=-1
    png(directory/"normal_directx.png",np.rint((normal*.5+.5)*255).astype(np.uint8))
    png(directory/"normal_full_opengl.png",np.rint((full_normal*.5+.5)*255).astype(np.uint8))
    png(directory/"normal_valid_mask.png",normal_valid.astype(np.uint8)*255)
    png(directory/"bump.png",gray8(fine,mask))
    roughness=float(np.clip(settings.get("roughness",.62),.02,1))
    rough=np.full(h.shape,roughness)
    estimated=settings.get("roughness_mode","constant")=="estimated"
    if estimated:
        residual=fine-smooth_valid(fine,mask,max(.5,band/3))
        dy,dx=np.gradient(residual,spacing[1],spacing[0])
        slopes=np.sqrt(ndimage.gaussian_filter(dx*dx+dy*dy,float(settings.get("roughness_scale",2))))
        lo=float(np.clip(settings.get("roughness_min",.3),0,1));hi=float(np.clip(settings.get("roughness_max",.9),lo,1))
        rough=lo+(hi-lo)*np.clip(slopes/max(float(np.percentile(slopes[mask],95)),1e-8),0,1)
    png(directory/"roughness.png",np.rint(rough*255).astype(np.uint8))
    png(directory/"brush_tip.png",brush_tip(h,mask,settings))
    grain,synth=seamless(h,mask,int(settings.get("seam_band",12)))
    grain=(gray8(grain)/255-.5)*float(settings.get("grain_contrast",1))+.5
    png(directory/"brush_grain.png",np.rint(np.clip(grain,0,1)*255).astype(np.uint8))
    png(directory/"grain_synthetic_mask.png",synth.astype(np.uint8)*255)
    valleys,summary=wrinkles(h,mask,int(settings.get("radius_px",8)),float(settings.get("sensitivity",.01)),False,a["synthetic_mask"])
    png(directory/"wrinkle_mask.png",valleys.astype(np.uint8)*255)
    light=np.array([-.5,.55,.67]);light/=np.linalg.norm(light)
    shade=np.clip(.25+.7*(full_normal@light),0,1)
    shade[~mask]=.12
    png(directory/"preview.png",(shade*255).astype(np.uint8))
    png(directory/"sphere-preview.png",sphere_thumbnail(h,mask,settings.get("color","#929795")))
    # Small floating point preview data, separate from full-precision master.
    step=max(1,int(np.ceil(max(h.shape)/192)))
    preview={"height":h[::step,::step].tolist(),"coarse":coarse[::step,::step].tolist(),"mask":mask[::step,::step].astype(int).tolist(),
             "width":h[::step,::step].shape[1],"height_px":h[::step,::step].shape[0],"source_spacing":spacing,
             "source_units":patch.units,"preview_stride":step}
    (directory/"surface.json").write_text(json.dumps(preview,allow_nan=False),encoding="utf-8")
    asset.maps={k:k for k in ("height.npy","height_16.png","height_16.tiff","displacement_16.png","normal_opengl.png","normal_directx.png","bump.png","roughness.png","brush_tip.png","brush_grain.png","wrinkle_mask.png","valid_mask.png","synthetic_mask.png","preview.png","surface.json")}
    asset.descriptor={"model":"authored dielectric GGX","base_color":settings.get("color","#929795"),"metalness":0,"roughness":roughness,
                      "ior":float(np.clip(settings.get("ior",1.45),1.01,2.5)),"roughness_source":"geometry-derived artistic estimate" if estimated else "authored constant",
                      "height_encoding":{**encoding,"units":patch.units,"pixel_spacing":patch.pixel_spacing,"sign":"positive outwards","reference":patch.height_reference},
                      "displacement_encoding":coarse_encoding,"frequency_split_sigma_px":band,"full_relief_override":bool(settings.get("full_relief_override")),
                      "bump_strength":float(settings.get("bump_strength",.3)),"normal_conventions":{"opengl":"+Y up","directx":"green flipped"},
                      "data_color_space":"linear","base_color_space":"sRGB","measurement_source":"original calibrated source patch only",
                      "not_measured":["albedo","BRDF","gloss","subsurface scattering"],"default_render_mode":"combined",
                      "synthetic":patch.synthetic,"source_status":patch.state,"brush_black_is_full_paint":True,
                      "grain_scale":float(settings.get("grain_scale",1.)),"wrinkle_method":summary["method"]}
    check(progress,.7,"Writing material descriptor and editing meshes")
    from .printing import sphere_mesh
    # Bake source height into a portable geometry preview, with authored display scale.
    span=max(float(np.ptp(h[mask])),1e-12)
    mesh,_=sphere_mesh(fill_nearest(h,mask),radius=25.,relief_scale=1./span,segments=96,rings=64)
    from trimesh.visual.material import PBRMaterial
    from trimesh.visual.texture import TextureVisuals
    color=asset.descriptor["base_color"].lstrip('#')
    try: rgba=[int(color[i:i+2],16) for i in (0,2,4)]+[255]
    except (ValueError,IndexError): rgba=[146,151,149,255]
    # Full relief is baked into this portable mesh; adding fine normals would
    # count that detail a second time. Interactive combined mode uses coarse+fine.
    mesh.visual=TextureVisuals(uv=mesh.metadata["uv"],material=PBRMaterial(baseColorFactor=rgba,metallicFactor=0,roughnessFactor=roughness))
    webmesh=mesh.copy();webmesh.apply_scale(.001);webmesh.export(directory/"material_baked.glb")
    mesh.export(directory/"material_baked.obj")
    asset.maps["sphere-preview.png"]="sphere-preview.png"
    asset.descriptor["baked_preview"]={"radius_mm":25,"authored_relief_mm":1.,"not_metric_reproduction":True,"gltf_units":"meters","obj_units":"mm","gltf_displacement":"full relief baked vertices; no additional normal map; source height kept separately"}
    (directory/"material.json").write_text(json.dumps(asset.model_dump(mode="json"),indent=2),encoding="utf-8")
    (directory/"README.md").write_text(MATERIAL_README,encoding="utf-8")
    return store.save("materials",asset)


MATERIAL_README="""# Material Studio texture pack

height.npy is the float32 master. Decode height_16.png/TIFF with the scale and bias
in material.json; consult valid_mask.png. Data maps are linear. Source dimensions
and relative/physical units are explicit. Invalid pixels are not measured zeros.
The normal maps contain the fine frequency band; displacement contains coarse
relief. Full-band normals are separate. Roughness is authored or an artistic
slope estimate, never a measured BRDF. Gray base color is authored, not skin color.

Photoshop: open brush_tip.png, select the image, choose Edit > Define Brush Preset.
Black means full paint, white no paint. Open brush_grain.png and use Edit > Define
Pattern; select it in Brush Settings > Texture. Adjust spacing, pressure/opacity
and scale. These PNG files are not ABR files. Photoshop importer testing has not
been performed. Reference: https://helpx.adobe.com/photoshop/desktop/apply-painting-techniques/brushes-presets/create-brush-tip-image.html

Seamless grain is an artistic derivative. grain_synthetic_mask marks changed
pixels. Source orientation is retained. Material spheres display a sampled
texture, not anatomical geometry. material_baked.glb has actual displaced vertices
at an authored display size. Standard glTF has no portable arbitrary displacement
shader. Height data remains available separately. Do not infer sensor accuracy
from export precision. No raw tactile images are included in this pack.
"""


def zip_directory(store,kind,selected_ids,directory,filename=None):
    manifest=ExportManifest(kind=kind,selected_ids=selected_ids)
    directory=Path(directory)
    entries=[p for p in directory.rglob('*') if p.is_file()]
    manifest.files={p.relative_to(directory).as_posix():{"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"bytes":p.stat().st_size} for p in entries}
    relative=f"exports/{filename or manifest.id}.zip"
    with zipfile.ZipFile(store.path(relative),'w',zipfile.ZIP_DEFLATED) as z:
        for p in entries: z.write(p,p.relative_to(directory).as_posix())
        z.writestr("export-manifest.json",json.dumps(manifest.model_dump(mode="json"),indent=2))
    store.save("exports",{**manifest.model_dump(mode="json"),"file":relative})
    return {"id":manifest.id,"file":relative,"manifest":manifest.model_dump(mode="json")}


def export_textures(store,material_id):
    asset=store.get("materials",material_id)
    return zip_directory(store,"texture-pack",[material_id],store.path(asset["directory"]))


def export_gallery(store,selected_ids):
    if not selected_ids: raise ValueError("Select at least one material to include in the gallery.")
    if len(selected_ids)>50: raise ValueError("Gallery limit is 50 selected materials.")
    import shutil
    from .records import uid
    root=store.path("exports/gallery-"+uid());root.mkdir()
    web=Path(__file__).parent/"web"
    if not (web/"vendor/three.module.js").exists(): raise ValueError("Run npm install and npm run setup:web before exporting a gallery.")
    for name in ("gallery.html","gallery.js","viewer.js","style.css"):
        shutil.copyfile(web/name,root/("index.html" if name=="gallery.html" else name))
    shutil.copytree(web/"vendor",root/"vendor")
    cards=[]
    for selected in dict.fromkeys(selected_ids):
        a=store.get("materials",selected)
        target=root/"assets"/selected;target.mkdir(parents=True)
        for name in ("surface.json","preview.png","normal_opengl.png","normal_full_opengl.png","roughness.png","bump.png","valid_mask.png"):
            shutil.copyfile(store.path(a["directory"])/name,target/name)
        # Intentionally omit source IDs, force/posture notes, raw files, sensor IDs.
        cards.append({"id":selected,"name":a["name"],"region":a["region"],"synthetic":a["synthetic"],"state":a["state"],
                      "descriptor":a["descriptor"],"base":f"assets/{selected}/"})
    (root/"gallery.json").write_text(json.dumps({"materials":cards,"raw_captures_included":False},indent=2),encoding="utf-8")
    (root/"README.md").write_text("# Standalone gallery\n\nNo processing server or build is needed. Preview: `python -m http.server 8080` in this folder, then open http://localhost:8080. Deploy this folder on ordinary static HTTPS hosting. All JS dependencies are included locally. Only selected derived maps and chosen labels are included; inspect those labels before publishing. No deployment has been performed.\n",encoding="utf-8")
    return zip_directory(store,"static-gallery",selected_ids,root)
