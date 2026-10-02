"""CPU adaptation of the bundled Golan core. Relative relief only.

Uses its full 320x240 model, marker fill order and shifted DCT denominator.
Temporal smoothing is intentionally disabled for synchronized still captures.
"""
from collections import deque
import hashlib
import cv2
import numpy as np
from scipy.fft import dctn, idctn
from studio.reconstruction import MiniMLP, BUNDLED_MODEL

CONFIG = dict(engine='desktop-golan-cpu-v1', model_size=[320, 240],
              crop_each_edge=.1, poisson_lambda=.0005, baseline_frames=50,
              marker_threshold=70, max_gradient=50, temporal_smoothing=False,
              metric_validated=False, units='relative solver values',
              differences='CPU bilinear resize; full inference; no temporal mixing. Not browser pixel parity or physical calibration.')


def crop_rgb(rgb):
    h, w = rgb.shape[:2]
    x, y = int(w*.1), int(h*.1)
    return rgb[y:h-y, x:w-x].copy(), [x, y, w-x, h-y]


def fill_markers(values, mask):
    """Match core's ordered neighbor averaging then breadth-first propagation."""
    h, w = mask.shape
    out = values.astype(np.float32).copy().ravel()
    filled = (~mask).ravel().copy()
    queue = deque()
    def neighbors(i):
        x, y = i % w, i // w
        return ([i-1] if x else []) + ([i+1] if x+1<w else []) + ([i-w] if y else []) + ([i+w] if y+1<h else [])
    for i in np.flatnonzero(mask.ravel()):
        good = [n for n in neighbors(int(i)) if filled[n]]
        if good:
            out[i] = sum(float(out[n]) for n in good)/len(good)
            filled[i] = True
            queue.append(int(i))
    while queue:
        parent = queue.popleft()
        for n in neighbors(parent):
            if not filled[n]:
                out[n] = out[parent]
                filled[n] = True
                queue.append(n)
    return out.reshape(h, w)


def poisson(gx, gy, regularization=.0005):
    """Exact discrete boundary and frequency recipe in gelsight-core.js."""
    h, w = gx.shape
    xp = np.minimum(np.arange(w)+1, w-1); xm = np.maximum(np.arange(w)-1, 0)
    yp = np.minimum(np.arange(h)+1, h-1); ym = np.maximum(np.arange(h)-1, 0)
    div = (gx[:, xp]-gx[:, xm]+gy[yp]-gy[ym]).astype(np.float32)
    div[0, 1:-1] += gy[0, 1:-1]; div[-1, 1:-1] -= gy[-1, 1:-1]
    div[1:-1, 0] += gx[1:-1, 0]; div[1:-1, -1] -= gx[1:-1, -1]
    div[0, 0] += gy[0, 0]+gx[0, 0]
    div[0, -1] += gy[0, -1]-gx[0, -1]
    div[-1, 0] += -gy[-1, 0]+gx[-1, 0]
    div[-1, -1] -= gy[-1, -1]+gx[-1, -1]
    y, x = np.indices((h, w))
    denom = 4*(np.sin(.5*np.pi*(x+1)/w)**2+np.sin(.5*np.pi*(y+1)/h)**2)
    z = idctn((-dctn(div, norm='ortho')/(denom+regularization)).astype(np.float32), norm='ortho')
    return (z-z.mean(dtype=np.float64)).astype(np.float32)


class Reconstructor:
    def __init__(self):
        self.model = MiniMLP()
        self.config = {**CONFIG, 'model_sha256': hashlib.sha256(BUNDLED_MODEL.read_bytes()).hexdigest()}

    def raw_depth(self, rgb):
        crop, box = crop_rgb(rgb)
        image = cv2.resize(crop, (320, 240), interpolation=cv2.INTER_LINEAR)
        h, w = image.shape[:2]; y, x = np.indices((h, w), dtype=np.float32)
        features = np.concatenate((image[..., ::-1].astype(np.float32)/255,
                                   (y/h)[..., None], (x/w)[..., None]), axis=-1).reshape(-1, 5)
        predictions = []
        for batch in np.array_split(features, 10):
            for i, (weight, bias) in enumerate(self.model.layers):
                batch = batch@weight.T+bias
                if i<3: batch = np.maximum(batch, 0)
            predictions.append(batch)
        xy = np.concatenate(predictions).reshape(h, w, 2)
        with np.errstate(invalid='ignore', divide='ignore'):
            nz = np.sqrt(1-np.sum(xy*xy, axis=-1))
            nz = np.where(np.isfinite(nz), nz, np.nanmean(nz) if np.isfinite(nz).any() else 1)
            gx, gy = -xy[..., 0]/nz, -xy[..., 1]/nz
        marker = (image[..., ::-1]@np.array([.299, .587, .114])) <= 70
        if marker.mean()>.65:
            raise ValueError('Image is mostly dark markers/black. Check Mini lighting and camera exposure.')
        gx, gy = fill_markers(gx, marker), fill_markers(gy, marker)
        invalid = ~np.isfinite(gx) | ~np.isfinite(gy)
        gx[invalid] = 0; gy[invalid] = 0
        gx, gy = fill_markers(gx, invalid), fill_markers(gy, invalid)
        z = poisson(np.clip(gx, -50, 50), np.clip(gy, -50, 50))
        return dict(depth=z, rgb=image, crop=crop, crop_box=box, marker=marker)
