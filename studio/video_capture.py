"""Private recorded Mini video -> FFmpeg stills -> linked relative surfaces."""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from .inputs import import_bytes, image_array, MAX_UPLOAD
from .records import CaptureSession, uid, now
from .samples import crop_box, export_capture_surface
from .reconstruction import reconstruct

CROP=[.1,.1,.8,.8]


def ffmpeg_path():
    executable=shutil.which('ffmpeg')
    if not executable:raise ValueError('FFmpeg is missing. Install FFmpeg, add its bin folder to PATH, and restart Studio.')
    return executable


def save_recording(store,data,name,device,baseline=None,synthetic=False):
    ffmpeg_path()
    if not data or len(data)>MAX_UPLOAD:raise ValueError('Video must be nonempty and at most 128 MiB.')
    if not synthetic and 'gelsight' not in device.lower():raise ValueError('Select a named GelSight camera.')
    suffix=Path(name).suffix.lower()
    if suffix not in ('.webm','.mp4','.mov','.mkv','.avi'):raise ValueError('Use WebM, MP4, MOV, MKV or AVI video.')
    if baseline is not None:
        if len(baseline)>16*1024*1024:raise ValueError('Reference image exceeds 16 MiB.')
        image_array(baseline)
    raw,digest=store.raw(data,suffix);record_id=uid()
    record=dict(id=record_id,created_at=now(),name=Path(name).stem[:120],device=device[:200],
        raw_file=raw,source_sha256=digest,synthetic=bool(synthetic),crop=CROP,
        baseline_file=store.raw(baseline,'.png')[0] if baseline else None)
    store.save('recordings',record)
    return record


def extract_recording(store,recording_id,stride=10,max_frames=60,progress=None,job_id=None):
    run_id=uid()
    try:return _extract_recording(store,recording_id,stride,max_frames,progress,run_id,job_id)
    except Exception as exc:
        try:run=store.get('video_runs',run_id)
        except ValueError:pass
        else:
            run.update(status='failed',error=str(exc));store.save('video_runs',run)
            (store.path(run['directory'])/'manifest.json').write_text(json.dumps(run,indent=2),encoding='utf-8')
        raise


def _extract_recording(store,recording_id,stride,max_frames,progress,run_id,job_id):
    if not isinstance(stride,int) or not 1<=stride<=300:raise ValueError('Frame interval must be 1–300 frames.')
    if not isinstance(max_frames,int) or not 1<=max_frames<=120:raise ValueError('Extract 1–120 photos per job.')
    recording=store.get('recordings',recording_id)
    folder=store.path('video_runs/'+run_id);folder.mkdir(parents=True)
    session=CaptureSession(name=recording['name']+' frames',sensor_id=recording['device'],synthetic=recording['synthetic'])
    store.save('sessions',session)
    run=dict(id=run_id,created_at=now(),directory='video_runs/'+run_id,recording_id=recording_id,
        name=session.name,session_id=session.id,source_sha256=recording['source_sha256'],
        stride=stride,max_frames=max_frames,crop=CROP,status='extracting',items=[],job_id=job_id,
        interpretation='FFmpeg-decoded photos; offline bundled Mini MLP + masked Poisson relative reconstruction. Not live p5 solver output or metric calibration.',
        limits=dict(duration_seconds=600,decoded_width=1280,decoded_height=960))
    run['ffmpeg_version']=subprocess.run([ffmpeg_path(),'-version'],capture_output=True,text=True,timeout=10).stdout.splitlines()[0]
    def save():
        store.save('video_runs',run)
        (folder/'manifest.json').write_text(json.dumps(run,indent=2),encoding='utf-8')
    save()
    # FFmpeg reads one immutable local file and cannot resolve network protocols.
    with tempfile.TemporaryDirectory(prefix='frames-',dir=folder) as temporary:
        output=Path(temporary)
        filters=f"select=not(mod(n\\,{stride})),scale=w=min(1280\\,iw):h=min(960\\,ih):force_original_aspect_ratio=decrease,showinfo"
        command=[ffmpeg_path(),'-hide_banner','-nostdin','-max_alloc','134217728','-threads','2','-filter_threads','1',
            '-protocol_whitelist','file,pipe','-i',str(store.path(recording['raw_file'])),
            '-t','600','-an','-vf',filters,'-fps_mode','vfr','-frames:v',str(max_frames+1),
            '-threads','2',str(output/'frame-%05d.png')]
        if progress:progress(.02,'FFmpeg: extracting video frames')
        try:decoded=subprocess.run(command,capture_output=True,text=True,timeout=180)
        except subprocess.TimeoutExpired as exc:raise ValueError('FFmpeg exceeded three minutes. Use a shorter recording.') from exc
        if decoded.returncode:raise ValueError('FFmpeg could not decode this recording: '+decoded.stderr[-1500:])
        paths=sorted(output.glob('frame-*.png'))
        if not paths:raise ValueError('Recording contains no decodable video frames.')
        times=[float(v) for v in re.findall(r'\bn:\s*\d+.*?pts_time:([\d.eE+\-]+)',decoded.stderr)]
        run['frame_limit_reached']=len(paths)>max_frames
        paths=paths[:max_frames];run['status']='processing'
        if recording.get('baseline_file'):
            baseline=image_array(store.path(recording['baseline_file']).read_bytes())
            # Apply exactly the same extraction resize to the reference frame.
            from PIL import ImageOps
            baseline_image=ImageOps.contain(Image.fromarray(baseline),(1280,960)) if baseline.shape[1]>1280 or baseline.shape[0]>960 else Image.fromarray(baseline)
            import io
            b=io.BytesIO();baseline_image.save(b,format='PNG')
            ref=import_bytes(store,'No-contact baseline.png',b.getvalue(),session_id=session.id,settings={'sample_crop':CROP,'capture_role':'baseline'})['frame']
            saved_session=store.get('sessions',session.id);saved_session['baseline_id']=ref['id'];store.save('sessions',saved_session)
        for i,path in enumerate(paths):
            if progress:progress(.1+.85*i/len(paths),f'Reconstructing photo {i+1} / {len(paths)}')
            frame=import_bytes(store,f'{recording["name"]}-{i*stride:06d}.png',path.read_bytes(),session_id=session.id,
                settings={'sample_crop':CROP,'capture_role':'sample','recording_id':recording_id,'video_run_id':run_id,'original_frame':i*stride})['frame']
            frame['timestamp_seconds']=times[i] if i<len(times) else None;store.save('frames',frame)
            item=dict(frame_id=frame['id'],original_frame=i*stride,timestamp_seconds=frame['timestamp_seconds'])
            try:
                patch=reconstruct(store,frame['id'],{'border':0})
                _,arrays=store.patch(patch['id']);height=arrays['height'];mask=arrays['mask']
                sample_id=uid();directory=store.path('samples/'+sample_id);directory.mkdir(parents=True)
                rgb=image_array(path.read_bytes());box=crop_box((rgb.shape[1],rgb.shape[0]),CROP)
                Image.fromarray(rgb).crop(box).save(directory/'raw.png')
                np.save(directory/'depth.npy',height,allow_pickle=False)
                low,high=float(height[mask].min()),float(height[mask].max())
                gray=np.rint(np.clip((height-low)/max(high-low,1e-9),0,1)*255).astype(np.uint8);gray[~mask]=0
                Image.fromarray(gray).save(directory/'depth.png')
                assets=export_capture_surface(directory,height,mask);assets.pop('mesh_view')
                sample=dict(id=sample_id,created_at=now(),name=Path(frame['source_name']).stem,directory='samples/'+sample_id,
                    frame_id=frame['id'],patch_id=patch['id'],session_id=session.id,synthetic=recording['synthetic'],
                    source_sha256=frame['sha256'],crop=CROP,crop_pixels=list(box),assets=assets,
                    metadata=dict(recording_id=recording_id,video_run_id=run_id,original_frame=i*stride,
                        timestamp_seconds=frame['timestamp_seconds'],crop_applied='Once to RGB before inference; depth, normals and mesh cover that exact cropped field.'),
                    interpretation=run['interpretation'])
                (directory/'sample.json').write_text(json.dumps(sample,indent=2),encoding='utf-8');store.save('samples',sample)
                frame['settings']['sample_id']=sample_id;store.save('frames',frame)
                item.update(sample_id=sample_id,patch_id=patch['id'],status='ready')
            except ValueError as exc:
                item.update(status='rejected',error=str(exc))
            run['items'].append(item);save()
    run['status']='completed';run['ready']=sum(i['status']=='ready' for i in run['items']);run['rejected']=len(run['items'])-run['ready'];save()
    return run
