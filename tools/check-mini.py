"""Read a live frame from a named GelSight, then release it. No default webcam."""
from pathlib import Path
import json
import sys
import time
import cv2
from cv2_enumerate_cameras import enumerate_cameras
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.camera import MiniCamera, devices

camera = MiniCamera()
try:
    if '--diagnose' in sys.argv:
        for backend in (cv2.CAP_DSHOW,cv2.CAP_MSMF):
            found=enumerate_cameras(backend)
            print(json.dumps({'backend':backend,'devices':[{'index':d.index,'name':d.name} for d in found]}),flush=True)
            for device in found:
                if 'gelsight' not in device.name.lower():continue
                cap=cv2.VideoCapture(device.index,device.backend)
                print(json.dumps({'main_thread_open':cap.isOpened(),'backend':backend}),flush=True)
                if cap.isOpened():
                    ok,frame=cap.read();print(json.dumps({'read':bool(ok),'shape':list(frame.shape) if ok else None}),flush=True)
                cap.release()
    print(json.dumps({'devices': devices()}), flush=True)
    camera.connect()
    time.sleep(.4)
    output = Path('test-artifacts/mini-connection.png')
    output.parent.mkdir(exist_ok=True)
    output.write_bytes(camera.snapshot())
    result = {**camera.status(), 'preview': str(output), 'saved_as_specimen': False}
    Path('test-artifacts/mini-connection.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)
finally:
    camera.close()
