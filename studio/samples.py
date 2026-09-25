"""Synchronized p5 sample bundles; source RGB and solver arrays remain immutable."""
import io
import json

import numpy as np
from PIL import Image

from .inputs import image_array, import_bytes
from .records import CaptureSession, SurfacePatch, uid, now


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
        width=320,height=240,synthetic=synthetic,settings={'p5':metadata,'crop':rect},
        height_reference='p5 solver relief; baseline subtraction when supplied; not metric',
        quality={'contact_status':'not independently verified','baseline_present':baseline is not None},
        provenance=[{'operation':'synchronized p5 capture','source_sha256':frame['sha256'],'metric_validated':False}])
    cropped=Image.fromarray(rgb).crop(box)
    extras={'rgb':np.asarray(cropped.resize((320,240),Image.Resampling.BILINEAR))}
    if baseline is not None:extras['baseline']=baseline
    saved=store.put_patch(patch,depth,**extras)
    record_id=uid();directory=store.path('samples/'+record_id);directory.mkdir(parents=True)
    cropped.save(directory/'raw.png')
    for data,filename in zip(previews,('mesh.png','depth.png')):Image.fromarray(data).save(directory/filename)
    np.save(directory/'depth.npy',depth,allow_pickle=False)
    if baseline is not None:np.save(directory/'baseline.npy',baseline,allow_pickle=False)
    if reference is not None:
        import cv2
        delta=np.abs(model_image.astype(np.float32)-reference.astype(np.float32))
        contact=np.linalg.norm(delta,axis=-1)>threshold
        # Small sensor noise islands are suppressed; this is an authored visual
        # contact mask, not a force/geometry measurement or reconstructed photograph.
        contact=cv2.morphologyEx(contact.astype(np.uint8),cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        Image.fromarray(reference).save(directory/'color-baseline.png')
        Image.fromarray(model_image).save(directory/'model-rgb.png')
        Image.fromarray(np.rint(np.clip(delta*3,0,255)).astype(np.uint8)).save(directory/'difference.png')
        Image.fromarray(np.dstack((model_image,contact*255))).save(directory/'clean.png')
    if baseline is not None:np.save(directory/'depth-before-background.npy',depth+baseline,allow_pickle=False)
    record=dict(id=record_id,created_at=now(),name=title,directory='samples/'+record_id,
        frame_id=frame['id'],patch_id=patch.id,session_id=session.id,synthetic=synthetic,
        source_sha256=frame['sha256'],crop=rect,crop_pixels=list(box),metadata=metadata,
        background=dict(available=reference is not None,threshold=threshold,difference_gain=3,
            method='Absolute RGB delta from averaged no-contact model input; clean image uses a thresholded contact alpha mask.',
            depth='p5 depth already subtracts its depth baseline; never subtract it twice'),
        interpretation='Synchronized p5 RGB, relative solver depth, and current camera mesh view. No metric calibration.')
    (directory/'sample.json').write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    store.save('samples',record)
    frame['settings']['sample_id']=record_id;store.save('frames',frame)
    return {'sample':record,'frame':frame,'patch':saved,'session':store.get('sessions',session.id)}
