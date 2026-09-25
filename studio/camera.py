"""Local GelSight camera access. Never open a default or unrelated webcam."""
from __future__ import annotations

import hashlib
import threading
import time

import cv2


def devices():
    from cv2_enumerate_cameras import enumerate_cameras
    import sys
    backend = cv2.CAP_DSHOW if sys.platform == 'win32' else cv2.CAP_ANY
    result = []
    for camera in enumerate_cameras(backend):
        # Names are supplied by the driver. USB bridge IDs alone are not unique
        # to GelSight: do not use them to select an ordinary webcam.
        if 'gelsight' not in camera.name.lower():
            continue
        key = hashlib.sha256(str(camera.path or camera.name).encode()).hexdigest()[:20]
        result.append(dict(id=key, name=camera.name, index=camera.index, backend=camera.backend))
    return result


class MiniCamera:
    def __init__(self):
        self.lock = threading.RLock()
        self.lifecycle = threading.Lock()
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.thread = None
        self.frame = None
        self.frame_time = 0.
        self.last_access = 0.
        self.device = None
        self.error = None
        self.count = 0

    def status(self):
        with self.lock:
            age = time.monotonic()-self.frame_time if self.frame_time else None
            return dict(connected=bool(self.thread and self.thread.is_alive() and self.frame is not None and age < 3),
                        device=self.device, width=self.frame.shape[1] if self.frame is not None else None,
                        height=self.frame.shape[0] if self.frame is not None else None,
                        frames_received=self.count, frame_age_seconds=age, error=self.error)

    def connect(self, device_id=None):
        with self.lifecycle:
            if self.thread and self.thread.is_alive():
                if device_id and self.device['id'] != device_id:
                    raise ValueError('Disconnect the current Mini before selecting another device.')
                self.last_access = time.monotonic()
                return self.status()
            found = devices()
            matches = [d for d in found if d['id']==device_id] if device_id else found
            if not matches:
                raise ValueError('No matching GelSight camera detected. Check USB and close other camera applications.')
            if len(matches) != 1:
                raise ValueError('Several GelSight cameras are connected. Choose one by name.')
            self.device = matches[0]
            self.frame = None
            self.frame_time = 0.
            self.count = 0
            self.error = None
            self.last_access = time.monotonic()
            self.stop_event.clear()
            self.ready.clear()
            self.thread = threading.Thread(target=self._read, daemon=True, name='gelsight-mini')
            self.thread.start()
            if not self.ready.wait(12):
                self.stop_event.set()
                raise ValueError('GelSight did not deliver a frame within 12 seconds. Close other camera applications and reconnect.')
            if self.error:
                raise ValueError(self.error)
            return self.status()

    def _read(self):
        capture = None
        try:
            capture = cv2.VideoCapture(self.device['index'], self.device['backend'])
            if not capture.isOpened() and self.device['backend']==cv2.CAP_DSHOW:
                from cv2_enumerate_cameras import enumerate_cameras
                alternatives = [d for d in enumerate_cameras(cv2.CAP_MSMF) if d.name==self.device['name']]
                if len(alternatives)==1:
                    capture.release()
                    chosen = alternatives[0]
                    capture = cv2.VideoCapture(chosen.index, chosen.backend)
                    self.device = {**self.device, 'index': chosen.index, 'backend': chosen.backend}
            if not capture.isOpened():
                raise ValueError('GelSight could not open. Another application may be using it, or Windows camera access is disabled.')
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            capture.set(cv2.CAP_PROP_FPS, 30)
            failures = 0
            while not self.stop_event.is_set() and time.monotonic()-self.last_access < 90:
                ok, frame = capture.read()
                if not ok:
                    failures += 1
                    if failures > 5:
                        raise ValueError('GelSight stopped delivering frames. Check the USB connection and reconnect.')
                    time.sleep(.1)
                    continue
                failures = 0
                if frame.ndim != 3 or frame.shape[2] != 3 or frame.shape[0]*frame.shape[1] > 4_000_000:
                    raise ValueError('Unsupported camera format or frame exceeds four megapixels.')
                with self.lock:
                    self.frame = frame
                    self.frame_time = time.monotonic()
                    self.count += 1
                self.ready.set()
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
            self.ready.set()
        finally:
            if capture is not None:
                capture.release()
            with self.lock:
                self.frame = None

    def snapshot(self, extension='.png'):
        with self.lock:
            if not self.status()['connected']:
                raise ValueError(self.error or 'Connect the GelSight Mini first; no fresh frame is available.')
            self.last_access = time.monotonic()
            frame = self.frame.copy()
        ok, encoded = cv2.imencode(extension, frame)
        if not ok:
            raise ValueError('Camera image encoding failed.')
        return encoded.tobytes()

    def close(self):
        with self.lifecycle:
            self.stop_event.set()
            if self.thread:
                self.thread.join(timeout=3)
                if self.thread.is_alive():
                    raise ValueError('Camera driver is still releasing the device. Wait a moment before reconnecting.')
            self.frame = None
            return self.status()


def capture_frame(store, camera, name='', session_id=None, baseline=False):
    return save_capture(store,camera.snapshot(),camera.status()['device'],name,session_id,baseline)


def save_capture(store, png, device, name='', session_id=None, baseline=False):
    from .inputs import import_bytes
    from .records import CaptureSession, now
    if 'gelsight' not in device.get('name','').lower():
        raise ValueError('Select the named GelSight Mini before saving tactile captures.')
    if session_id:
        session = CaptureSession(**store.get('sessions', session_id))
        if session.synthetic or session.sensor_id != device['name']:
            raise ValueError('Use a session captured with this Mini, or start a new session.')
    else:
        session = CaptureSession(name='Mini collection '+now()[:19].replace('T', ' '), sensor_id=device['name'])
        store.save('sessions', session)
    title = name.strip()[:120] or ('No-contact baseline' if baseline else 'Tactile sample '+str(len(session.frame_ids)+1).zfill(3))
    # Label is metadata only; stored raw filenames remain hashes.
    result = import_bytes(store, title+'.png', png, 'rgb', session.id,
                          settings=dict(capture_device=device['name'], capture_device_id=device['id'],
                                        capture_role='baseline' if baseline else 'sample', capture_time=now(),sample_crop=[.1,.1,.8,.8]))
    if baseline:
        updated = store.get('sessions', session.id)
        updated['baseline_id'] = result['frame']['id']
        store.save('sessions', updated)
        result['session'] = updated
    return result
