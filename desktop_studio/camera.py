"""Native DirectShow fallback for Minis that Qt cannot enumerate.

No default camera selection. Probe advertised modes instead of guessing 640x480.
FFmpeg decodes a supported input mode and delivers bounded RGB frames to Qt.
"""
import os
import re
import shutil
import subprocess
import numpy as np
from PySide6.QtCore import QObject, QProcess, Signal


def probe(args):
    exe = shutil.which('ffmpeg')
    if not exe: return ''
    result = subprocess.run([exe, '-hide_banner', *args], capture_output=True, timeout=8,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return result.stderr.decode('utf-8', errors='replace')


def discover():
    if os.name!='nt': return []
    output = probe(['-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'])
    devices = []
    for name in re.findall(r'"([^"\r\n]+)" \(video\)', output):
        if 'gelsight' not in name.lower(): continue
        options = probe(['-list_options', 'true', '-f', 'dshow', '-i', 'video='+name])
        modes = []
        for codec, pixel, w, h, fps in re.findall(r'(?:vcodec=(\w+)|pixel_format=(\w+))\s+min s=(\d+)x(\d+) fps=([\d.]+)', options):
            mode = dict(codec=codec, pixel_format=pixel, width=int(w), height=int(h), fps=float(fps))
            if mode not in modes: modes.append(mode)
        if modes:
            # Prefer native 640x480 if advertised; some Minis expose only 3280x2464 MJPEG.
            modes.sort(key=lambda m:abs(m['width']-640)+abs(m['height']-480))
            devices.append(dict(name=name, mode=modes[0], backend='FFmpeg DirectShow'))
    return devices


class DirectShowCamera(QObject):
    frame = Signal(object)
    error = Signal(str)

    def __init__(self, device, size, parent=None):
        super().__init__(parent)
        self.process = QProcess(self); self.device = device; self.size = size
        self.buffer = bytearray(); self.errors = ''; self.stopping = False
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.readyReadStandardError.connect(self.read_error)
        self.process.errorOccurred.connect(lambda _:self.error.emit(self.process.errorString()) if not self.stopping else None)
        self.process.finished.connect(lambda *_:self.error.emit(self.errors[-1500:] or 'Camera stream stopped.') if not self.stopping else None)

    def start(self):
        mode = self.device['mode']; w, h = self.size
        args = ['-hide_banner', '-loglevel', 'error', '-nostdin', '-threads', '2', '-f', 'dshow', '-rtbufsize', '128M']
        if mode['codec']: args += ['-vcodec', mode['codec']]
        if mode['pixel_format']: args += ['-pixel_format', mode['pixel_format']]
        args += ['-video_size', f'{mode["width"]}x{mode["height"]}', '-framerate', str(mode['fps']),
                 '-i', 'video='+self.device['name'], '-an', '-threads', '2', '-filter_threads', '2',
                 '-vf', f'scale={w}:{h}', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
        self.process.start(shutil.which('ffmpeg'), args)

    def read_error(self):
        self.errors = (self.errors+bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace'))[-4000:]

    def read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        w, h = self.size; size = w*h*3; count = len(self.buffer)//size
        if count:
            # Retain the newest complete frame; never infer on stale queued video.
            raw = np.frombuffer(bytes(self.buffer[(count-1)*size:count*size]), np.uint8).reshape(h, w, 3).copy()
            del self.buffer[:count*size]
            self.frame.emit(raw)

    def stop(self):
        self.stopping = True
        self.process.kill(); self.process.waitForFinished(2000)
        self.buffer.clear()
