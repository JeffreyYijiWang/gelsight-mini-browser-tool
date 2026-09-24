from __future__ import annotations

from contextlib import asynccontextmanager
import io
import json
from pathlib import Path
import secrets
import threading

import numpy as np
from PIL import Image
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .records import CaptureSession, CalibrationProfile, PrinterProfile
from .store import Store
from .jobs import Jobs

ROOT=Path(__file__).resolve().parents[1]


def create_app(data_dir=None):
    store=Store(data_dir or ROOT/'studio-data');token=secrets.token_urlsafe(32);jobs=Jobs(store)
    ink_slots=threading.BoundedSemaphore(2)
    from .camera import MiniCamera
    camera=MiniCamera()
    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.close()
        try:camera.close()
        except ValueError:pass
    app=FastAPI(title="Material Studio local owner API",docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.store=store;app.state.token=token;app.state.jobs=jobs
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])
    @app.middleware('http')
    async def protect(request,call_next):
        if request.url.path.startswith('/api/'):
            supplied=request.headers.get('x-studio-token') or request.cookies.get('studio_owner')
            if not supplied or not secrets.compare_digest(supplied,token):return JSONResponse({"detail":"Owner session required. Open Material Studio on this computer."},status_code=401)
            if request.method not in ('GET','HEAD'):
                if request.headers.get('x-studio-token')!=token:return JSONResponse({"detail":"Missing owner request token."},status_code=403)
                origin=request.headers.get('origin')
                if origin and origin!=str(request.base_url).rstrip('/'):return JSONResponse({"detail":"Cross-origin editing is not allowed."},status_code=403)
        response=await call_next(request)
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        return response
    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse({"detail":str(exc)},status_code=422)
    @app.get('/')
    async def index():
        page=(ROOT/'studio/web/index.html').read_text(encoding='utf-8').replace('__OWNER_TOKEN__',token)
        response=HTMLResponse(page);response.set_cookie('studio_owner',token,httponly=True,samesite='strict',secure=False)
        response.headers['Cache-Control']='no-store';return response
    @app.get('/api/state')
    async def state():
        return {kind:store.list(kind) for kind in ('sessions','frames','patches','materials','atlases','prints','calibrations','printers','specimens','impressions','typologies','jobs','exports')}
    @app.get('/api/camera/devices')
    def camera_devices():
        from .camera import devices
        return devices()
    @app.get('/api/camera/status')
    def camera_status():return camera.status()
    @app.post('/api/camera/connect')
    def camera_connect(options:dict):return camera.connect(options.get('device_id'))
    @app.post('/api/camera/disconnect')
    def camera_disconnect():return camera.close()
    @app.get('/api/camera/frame.jpg')
    def camera_frame():return Response(camera.snapshot('.jpg'),media_type='image/jpeg')
    @app.post('/api/camera/capture')
    def camera_capture(options:dict):
        from .camera import capture_frame
        return capture_frame(store,camera,name=options.get('name',''),session_id=options.get('session_id'),baseline=bool(options.get('baseline',False)))
    @app.post('/api/camera/browser-capture')
    async def browser_capture(file:UploadFile=File(...),device_name:str=Form(...),device_id:str=Form(''),name:str=Form(''),session_id:str=Form(''),baseline:bool=Form(False)):
        from .camera import save_capture
        from .inputs import MAX_UPLOAD
        data=await file.read(MAX_UPLOAD+1)
        return save_capture(store,data,dict(name=device_name,id=device_id),name,session_id or None,baseline)
    @app.get('/api/typology/items')
    def typology_items():
        from .typology import catalog
        return catalog(store)
    @app.get('/api/typology/thumbnail/{kind}/{record_id}')
    def typology_thumbnail(kind:str,record_id:str):
        from .typology import source_image
        picture,_=source_image(store,kind,record_id);picture.thumbnail((256,256));out=io.BytesIO();picture.save(out,format='WEBP',quality=82)
        return Response(out.getvalue(),media_type='image/webp')
    @app.get('/favicon.ico')
    async def favicon():return Response(status_code=204)
    @app.get('/api/health')
    async def health():return {"status":"ok","owner_only":True,"local_storage":True}
    @app.post('/api/import')
    async def upload(files:list[UploadFile]=File(...),kind:str=Form('rgb'),session_id:str=Form(''),settings:str=Form('{}')):
        from .inputs import import_bytes,MAX_UPLOAD
        options=json.loads(settings);results=[]
        if len(files)>120:raise ValueError('Import at most 120 files per batch.')
        for file in files:
            data=await file.read(MAX_UPLOAD+1)
            if len(data)>MAX_UPLOAD:raise ValueError('File exceeds 128 MiB.')
            if Path(file.filename or '').suffix.lower() in ('.mp4','.mov','.avi','.mkv','.webm'):
                raw,_=store.raw(data,Path(file.filename).suffix)
                results.append(jobs.start('video',{"name":file.filename,"raw_file":raw,"settings":options}));continue
            result=import_bytes(store,file.filename or 'upload.png',data,kind,session_id or None,options)
            session_id=result['session']['id'];results.append(result)
        return results
    @app.post('/api/sessions')
    async def save_session(request:Request):
        values=await request.json()
        if values.get('id'):
            old=store.get('sessions',values['id']);values={**old,**values}
        session=CaptureSession(**values)
        if session.baseline_id and session.baseline_id not in session.frame_ids:raise ValueError('Baseline must be a frame in this session.')
        return store.save('sessions',session)
    @app.post('/api/calibrations')
    async def save_calibration(request:Request):
        profile=CalibrationProfile(**(await request.json()))
        if profile.weights!='bundled_mini' and not profile.weights.startswith('raw/'):raise ValueError('Upload a model into the local store first; arbitrary server paths are not accepted.')
        return store.save('calibrations',profile)
    @app.post('/api/weights')
    async def weights(file:UploadFile):
        from .inputs import MAX_UPLOAD
        data=await file.read(MAX_UPLOAD+1)
        if len(data)>MAX_UPLOAD:raise ValueError('Model exceeds 128 MiB.')
        suffix=Path(file.filename or '').suffix
        if suffix not in ('.bin','.npz','.pt','.pth'):raise ValueError('Supported model formats: .bin, .npz or trusted local TorchScript .pt/.pth.')
        path,digest=store.raw(data,suffix);return {'weights':path,'sha256':digest}
    @app.post('/api/printers')
    async def printer(request:Request):return store.save('printers',PrinterProfile(**(await request.json())))
    @app.post('/api/jobs')
    async def start(request:Request):
        data=await request.json();return jobs.start(data['kind'],data.get('params',{}))
    @app.get('/api/jobs/{job_id}')
    async def job(job_id:str):return store.get('jobs',job_id)
    @app.post('/api/jobs/{job_id}/cancel')
    async def cancel(job_id:str):return jobs.cancel(job_id)
    @app.get('/api/patches/{patch_id}/surface')
    async def patch_surface(patch_id:str):
        from .surface import smooth_valid
        patch,a=store.patch(patch_id);step=max(1,int(np.ceil(max(a['height'].shape)/192)))
        return {"patch":patch.model_dump(mode='json'),"height":a['height'][::step,::step].tolist(),"mask":a['mask'][::step,::step].astype(int).tolist(),
                "coarse":smooth_valid(a['height'],a['mask'],3)[::step,::step].tolist(),
                "source_units":patch.units,"source_spacing":patch.pixel_spacing or (1,1),
                "width":a['height'][::step,::step].shape[1],"height_px":a['height'][::step,::step].shape[0],"preview_stride":step}
    @app.get('/api/patches/{patch_id}/image/{kind}')
    async def patch_image(patch_id:str,kind:str):
        from .materials import gray8
        from .surface import normals_from_height
        patch,a=store.patch(patch_id)
        if kind=='height':data=gray8(a['height'],a['mask'])
        elif kind=='mask':data=a['mask'].astype(np.uint8)*255
        elif kind=='synthetic':data=a['synthetic_mask'].astype(np.uint8)*255
        elif kind=='rgb':data=a.get('rgb',np.repeat(gray8(a['height'],a['mask'])[...,None],3,axis=-1))
        elif kind=='normal':data=np.rint((normals_from_height(a['height'],patch.pixel_spacing or (1,1),a['mask'])[0]*.5+.5)*255).astype(np.uint8)
        else:raise HTTPException(404)
        out=io.BytesIO();Image.fromarray(data).save(out,format='PNG');return Response(out.getvalue(),media_type='image/png')
    @app.get('/api/frames/{frame_id}/image')
    async def frame_image(frame_id:str):
        frame=store.get('frames',frame_id)
        if frame['kind']!='rgb':raise ValueError('Only RGB frames have a tactile image preview.')
        return FileResponse(store.path(frame['raw_file']))
    @app.get('/api/files/{kind}/{record_id}/{filename:path}')
    async def derived_file(kind:str,record_id:str,filename:str):
        if kind not in ('materials','prints','impressions','atlases','typologies'):raise HTTPException(404)
        record=store.get(kind,record_id)
        directory=store.path(f'atlases/{record_id}' if kind=='atlases' else record['directory'])
        path=(directory/filename).resolve()
        if not path.is_relative_to(directory) or not path.is_file():raise HTTPException(404)
        return FileResponse(path)
    @app.get('/api/downloads/{export_id}')
    async def download(export_id:str):
        record=store.get('exports',export_id);return FileResponse(store.path(record['file']),filename=Path(record['file']).name,media_type='application/zip')
    @app.post('/api/specimens')
    async def specimen(request:Request):
        from .dictionary import create_specimen
        return create_specimen(store,**(await request.json()))
    @app.patch('/api/specimens/{specimen_id}')
    async def edit(specimen_id:str,request:Request):
        from .dictionary import edit_specimen
        return edit_specimen(store,specimen_id,await request.json())
    @app.get('/api/ink-settings')
    def ink_settings():
        from .ink import DEFAULTS, LEGACY_DEFAULTS, PRESETS
        return dict(defaults=DEFAULTS, legacy_defaults=LEGACY_DEFAULTS, presets=PRESETS)
    @app.post('/api/specimens/{specimen_id}/pressure-proof')
    def ink_proof(specimen_id:str,settings:dict):
        from .ink import pressure_proof
        with ink_slots:
            picture=pressure_proof(store,specimen_id,settings);out=io.BytesIO();picture.save(out,format='PNG',dpi=(152.4,152.4))
        return Response(out.getvalue(),media_type='image/png',headers={'Content-Disposition':'attachment; filename="pressure-proof.png"'})
    @app.post('/api/specimens/{specimen_id}/ink-preview')
    def ink_preview(specimen_id:str,settings:dict):
        from .ink import preview_ink
        with ink_slots:
            picture=preview_ink(store,specimen_id,settings);out=io.BytesIO();picture.save(out,format='PNG')
        return Response(out.getvalue(),media_type='image/png')
    @app.post('/api/specimens/{specimen_id}/publish')
    async def publish(specimen_id:str):
        from .dictionary import publish_specimen
        return publish_specimen(store,specimen_id)
    @app.post('/api/specimens/{specimen_id}/unpublish')
    async def unpublish(specimen_id:str,request:Request):
        from .dictionary import unpublish_specimen
        return unpublish_specimen(store,specimen_id,(await request.json()).get('archive',False))
    @app.get('/api/previews/{preview_id}/{filename:path}')
    async def preview(preview_id:str,filename:str=''):
        store._id(preview_id);directory=store.path('previews/'+preview_id);path=(directory/filename).resolve()
        if path.is_dir():path/= 'index.html'
        if not path.is_relative_to(directory) or not path.is_file():raise HTTPException(404)
        return FileResponse(path)
    app.mount('/web',StaticFiles(directory=ROOT/'studio/web'),name='web')
    app.mount('/gelsight_p5',StaticFiles(directory=ROOT/'gelsight_p5',html=True),name='legacy')
    return app
