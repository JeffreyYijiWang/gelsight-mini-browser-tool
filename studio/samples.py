"""Synchronized p5 sample bundles; source RGB and solver arrays remain immutable."""
import io
import json

import numpy as np
from PIL import Image

from .inputs import image_array, import_bytes
from .records import CaptureSession, SurfacePatch, uid, now


def export_capture_surface(directory, depth, mask=None):
    """Full solver grid, without screenshot Z exaggeration or per-image scaling."""
    from .surface import normals_from_height
    valid=np.isfinite(depth) if mask is None else np.asarray(mask,bool)&np.isfinite(depth)
    normals,normal_mask=normals_from_height(depth,mask=valid)
    encoded=np.rint((normals*.5+.5)*255).astype(np.uint8)
    Image.fromarray(encoded).save(directory/'normal.png')
    dx=encoded.copy();dx[...,1]=255-dx[...,1]
    dx[~normal_mask]=(128,128,255)
    Image.fromarray(dx).save(directory/'normal-directx.png')
    np.save(directory/'normals.npy',normals,allow_pickle=False)
    Image.fromarray((valid*255).astype(np.uint8)).save(directory/'mask.png')
    Image.fromarray((normal_mask*255).astype(np.uint8)).save(directory/'normal-mask.png')
    h,w=depth.shape
    indices=np.zeros(depth.shape,int);indices[valid]=np.arange(1,int(valid.sum())+1);triangles=0
    with (directory/'mesh.obj').open('w',encoding='utf-8') as out:
        out.write('# Relative p5 relief. XY: model pixels; Z: solver values. Not millimeters.\n')
        for y in range(h):
            for x in range(w):
                if valid[y,x]:out.write(f'v {x-(w-1)/2:g} {(h-1)/2-y:g} {float(depth[y,x]):.9g}\n')
        for y in range(h-1):
            for x in range(w-1):
                if valid[y:y+2,x:x+2].all():
                    a,b,c,d=indices[y,x],indices[y,x+1],indices[y+1,x],indices[y+1,x+1]
                    out.write(f'f {a} {c} {b}\nf {b} {c} {d}\n');triangles+=2
    return dict(depth='depth.npy',depth_preview='depth.png',rgb='raw.png',
        normal_opengl='normal.png',normal_directx='normal-directx.png',normals='normals.npy',
        mesh='mesh.obj',mesh_view='mesh.png',mask='mask.png',normal_mask='normal-mask.png',
        geometry=dict(width=w,height=h,vertices=int(valid.sum()),triangles=triangles,
            xy_spacing=[1,1],xy_units='model pixels',z_units='relative solver values',
            axes='X right, Y up, Z out; array rows down',
            normal_convention='OpenGL +Y; DirectX PNG flips green',
            normal_method='Finite differences of the saved depth at unit model-pixel spacing',
            display_exaggeration_applied=False,metric_validated=False))


def crop_box(size, rect=(.1, .1, .8, .8)):
    x, y, w, h = map(float, rect)
    if not all(np.isfinite([x,y,w,h])) or not (0<=x<1 and 0<=y<1 and w>0 and h>0 and x+w<=1.000001 and y+h<=1.000001):
        raise ValueError('Crop must be a normalized rectangle inside the source.')
    width, height = size
    left, top = round(x*width), round(y*height)
    return left, top, min(width,left+round(w*width)), min(height,top+round(h*height))


def save_p5_sample(store, raw, mesh, depth_preview, payload, name='', session_id=None, color_baseline=None, model_rgb=None):
    if len(json.dumps(payload))>5_000_000:
        raise ValueError('Capture metadata exceeds the five-megabyte budget.')
    depth = np.asarray(payload.get('depth'), dtype=np.float32)
    if depth.shape != (240,320) or not np.isfinite(depth).all():
        raise ValueError('p5 depth must contain 320 × 240 finite solver samples.')
    baseline = payload.get('baseline')
    if baseline is not None:
        baseline=np.asarray(baseline,dtype=np.float32)
        if baseline.shape!=depth.shape or not np.isfinite(baseline).all():
            raise ValueError('Baseline must match the p5 depth grid.')
    metadata=payload.get('metadata',{})
    if metadata.get('calibration',{}).get('dirty') or payload.get('calibrating'):
        raise ValueError('Finish a fresh no-contact calibration before saving this sample.')
    rgb=image_array(raw)
    # Never accept arbitrarily large screenshot uploads as derived previews.
    previews=[image_array(data) for data in (mesh,depth_preview)]
    threshold=float(payload.get('background_threshold',12))
    if not np.isfinite(threshold) or not 1<=threshold<=100:raise ValueError('Background threshold must be between 1 and 100 RGB code units.')
    reference=image_array(color_baseline) if color_baseline else None
    model_image=image_array(model_rgb) if model_rgb else None
    if reference is not None and (model_image is None or reference.shape!=(240,320,3) or model_image.shape!=reference.shape):
        raise ValueError('RGB background and model image must both be 320 × 240 RGB.')
    damage=payload.get('sensor_damage');invalid=np.zeros(depth.shape,bool)
    if damage:
        import hashlib
        from .sensor_damage import validate_regions,damage_mask
        if baseline is None or reference is None: raise ValueError('Permanent damage requires a matching untouched depth and RGB baseline.')
        damage=dict(version=1,regions=validate_regions(damage.get('regions')),reference_sha256=hashlib.sha256(color_baseline).hexdigest(),margin_pixels=2)
    if any(max(image.shape[:2])>2048 for image in previews):
        raise ValueError('Preview images must be at most 2048 pixels per side.')
    synthetic=bool(payload.get('demo'))
    device=str(payload.get('device',''))[:200]
    if not synthetic and 'gelsight' not in device.lower():
        raise ValueError('Select the named GelSight Mini before saving a live sample.')
    rect=payload.get('crop',[.1,.1,.8,.8])
    box=crop_box((rgb.shape[1],rgb.shape[0]),rect)
    if min(box[2]-box[0],box[3]-box[1])<2:
        raise ValueError('Crop is too small.')
    if damage:
        invalid=damage_mask(depth.shape,damage['regions'],[box[0]/rgb.shape[1],box[1]/rgb.shape[0],(box[2]-box[0])/rgb.shape[1],(box[3]-box[1])/rgb.shape[0]])
        damage['mesh_screenshot']='Original unmasked diagnostic view; use masked mesh.obj for geometry.'
    if session_id:
        session=CaptureSession(**store.get('sessions',session_id))
        if session.synthetic!=synthetic or session.sensor_id!=device:
            raise ValueError('Start a new collection for this sensor or demo source.')
    else:
        session=CaptureSession(name=('Demo' if synthetic else 'Mini')+' p5 collection '+now()[:19],sensor_id=device,synthetic=synthetic)
        store.save('sessions',session)
    title=str(name).strip()[:120] or 'Tactile sample '+str(len(session.frame_ids)+1).zfill(3)
    result=import_bytes(store,title+'.png',raw,'rgb',session.id,settings={'capture_role':'sample','sample_crop':rect,'capture_engine':'p5','capture_time':now()})
    frame=result['frame']
    patch=SurfacePatch(name=title+' depth',source_ids=[frame['id']],session_id=session.id,
        width=320,height=240,synthetic=synthetic,settings={'p5':metadata,'crop':rect,**({'sensor_damage':damage} if damage else {})},
        height_reference='p5 solver relief; baseline subtraction when supplied; not metric',
        quality={'contact_status':'not independently verified','baseline_present':baseline is not None},
        provenance=[{'operation':'synchronized p5 capture','source_sha256':frame['sha256'],'metric_validated':False}])
    cropped=Image.fromarray(rgb).crop(box)
    extras={'rgb':np.asarray(cropped.resize((320,240),Image.Resampling.BILINEAR))}
    if baseline is not None:extras['baseline']=baseline
    saved=store.put_patch(patch,depth,mask=~invalid,**extras)
    record_id=uid();directory=store.path('samples/'+record_id);directory.mkdir(parents=True)
    cropped.save(directory/'raw.png')
    for data,filename in zip(previews,('mesh.png','depth.png')):Image.fromarray(data).save(directory/filename)
    np.save(directory/'depth.npy',depth,allow_pickle=False)
    assets=export_capture_surface(directory,depth,~invalid)
    if damage:
        import cv2
        Image.fromarray((invalid*255).astype(np.uint8)).save(directory/'damage-mask.png')
        alpha=(1-cv2.resize(invalid.astype(np.uint8),(previews[1].shape[1],previews[1].shape[0]),interpolation=cv2.INTER_NEAREST))*255
        Image.fromarray(np.dstack((previews[1],alpha))).save(directory/'depth.png')
        # Original solver values stay in depth.npy; validity is always a separate mask.
    if baseline is not None:np.save(directory/'baseline.npy',baseline,allow_pickle=False)
    if reference is not None:
        import cv2
        delta=np.abs(model_image.astype(np.float32)-reference.astype(np.float32))
        contact=np.linalg.norm(delta,axis=-1)>threshold
        # Small sensor noise islands are suppressed; this is an authored visual
        # contact mask, not a force/geometry measurement or reconstructed photograph.
        contact=cv2.morphologyEx(contact.astype(np.uint8),cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        contact[invalid]=0
        Image.fromarray(reference).save(directory/'color-baseline.png')
        Image.fromarray(model_image).save(directory/'model-rgb.png')
        Image.fromarray(np.rint(np.clip(delta*3,0,255)).astype(np.uint8)).save(directory/'difference.png')
        Image.fromarray(np.dstack((model_image,contact*255))).save(directory/'clean.png')
    if baseline is not None:np.save(directory/'depth-before-background.npy',depth+baseline,allow_pickle=False)
    record=dict(id=record_id,created_at=now(),name=title,directory='samples/'+record_id,
        frame_id=frame['id'],patch_id=patch.id,session_id=session.id,synthetic=synthetic,
        source_sha256=frame['sha256'],crop=rect,crop_pixels=list(box),metadata=metadata,
        assets=assets,sensor_damage=damage,
        background=dict(available=reference is not None,threshold=threshold,difference_gain=3,
            method='Absolute RGB delta from averaged no-contact model input; clean image uses a thresholded contact alpha mask.',
            depth='p5 depth already subtracts its depth baseline; never subtract it twice'),
        interpretation='Synchronized p5 RGB and relative solver depth; normal maps and actual OBJ derived from that frozen depth, plus current camera mesh screenshot. No metric calibration.')
    (directory/'sample.json').write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    store.save('samples',record)
    frame['settings']['sample_id']=record_id;store.save('frames',frame)
    if damage:
        frame['settings']['sensor_damage']=damage;store.save('frames',frame)
    return {'sample':record,'frame':frame,'patch':saved,'session':store.get('sessions',session.id)}
