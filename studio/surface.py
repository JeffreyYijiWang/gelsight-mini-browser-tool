"""Mask-aware numerical surface operations; all arrays use row-down coordinates."""
from __future__ import annotations

import numpy as np
from scipy import ndimage, sparse
from scipy.sparse.linalg import cg
from skimage.morphology import skeletonize


def check(progress, value: float, message: str):
    if progress:
        progress(value, message)


def smooth_valid(height, mask, sigma):
    if sigma <= 0:
        return np.asarray(height, float).copy()
    weight = ndimage.gaussian_filter(np.asarray(mask, float), sigma)
    return ndimage.gaussian_filter(np.where(mask, height, 0.), sigma) / np.maximum(weight, 1e-12)


def fill_nearest(height, mask):
    if not np.any(mask):
        raise ValueError("No valid surface samples.")
    indices = ndimage.distance_transform_edt(~mask, return_distances=False, return_indices=True)
    return np.asarray(height)[tuple(indices)]


def normals_from_height(height, spacing=(1., 1.), mask=None, convention="opengl"):
    """X right, Y up, Z out; rows down. Heights and spacing use the same unit."""
    height = np.asarray(height, float)
    mask = np.isfinite(height) if mask is None else np.asarray(mask, bool)
    if min(spacing) <= 0 or convention not in ("opengl", "directx"):
        raise ValueError("Positive XY spacing and opengl/directx convention required.")
    gy, gx = np.gradient(fill_nearest(height, mask), spacing[1], spacing[0])
    normals = np.stack((-gx, gy, np.ones_like(gx)), axis=-1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
    if convention == "directx":
        normals[..., 1] *= -1
    valid = ndimage.binary_erosion(mask, border_value=1)
    normals[~valid] = (0, 0, 1)
    return normals.astype(np.float32), valid


def integrate_normals(normals, mask, spacing=(1., 1.), convention="opengl", progress=None):
    """Sparse least-squares Poisson integration over valid edges, one anchor/island.

    No equations cross holes. Connected islands have independent zero offsets.
    This is deliberately different from the skin paper's periodic FFT integration.
    """
    normals = np.asarray(normals, float)
    mask = np.asarray(mask, bool) & np.isfinite(normals).all(axis=-1) & (normals[..., 2] > .05)
    if mask.sum() < 4:
        raise ValueError("Too few valid upward normals for integration.")
    if mask.size > 1_000_000:
        raise ValueError("Normal integration budget is 1 million pixels. Crop or downsample first.")
    gx = -normals[..., 0] / np.maximum(normals[..., 2], .05)
    gy = normals[..., 1] / np.maximum(normals[..., 2], .05)
    if convention == "directx":
        gy *= -1
    ids = np.full(mask.shape, -1, int)
    ids[mask] = np.arange(mask.sum())
    hgood = mask[:, 1:] & mask[:, :-1]
    vgood = mask[1:] & mask[:-1]
    a = np.concatenate((ids[:, :-1][hgood], ids[:-1][vgood]))
    b = np.concatenate((ids[:, 1:][hgood], ids[1:][vgood]))
    delta = np.concatenate((((gx[:, 1:] + gx[:, :-1]) * spacing[0] / 2)[hgood],
                            (((gy[1:] + gy[:-1]) * spacing[1] / 2))[vgood]))
    count = int(mask.sum())
    lap = sparse.coo_matrix((np.concatenate((np.ones(len(a)*2), -np.ones(len(a)*2))),
                            (np.concatenate((a,b,a,b)), np.concatenate((a,b,b,a)))), shape=(count,count)).tocsr()
    rhs = np.bincount(b, weights=delta, minlength=count) - np.bincount(a, weights=delta, minlength=count)
    labels, components = ndimage.label(mask)
    anchors = [ids[np.argwhere(labels == i)[0][0], np.argwhere(labels == i)[0][1]] for i in range(1, components+1)]
    diag = np.zeros(count)
    diag[anchors] = 1
    lap = lap + sparse.diags(diag)
    iteration = [0]
    def callback(_):
        iteration[0] += 1
        if iteration[0] % 25 == 0:
            check(progress, min(.85, .15 + iteration[0]/5000), "Integrating valid normal components")
    values, status = cg(lap, rhs, rtol=1e-7, atol=1e-9, maxiter=5000, callback=callback,
                        M=sparse.diags(1 / np.maximum(lap.diagonal(), 1)))
    if status != 0:
        raise ValueError("Normal integration did not converge; reduce the ROI or inspect normal quality.")
    out = np.zeros(mask.shape, np.float32)
    out[mask] = values
    for i in range(1, components+1):
        out[labels == i] -= np.mean(out[labels == i])
    return out, mask


def detrend(height, mask, sigma=12., smoothing=0.):
    filtered = smooth_valid(height, mask, smoothing)
    trend = smooth_valid(filtered, mask, sigma) if sigma > 0 else np.zeros_like(filtered)
    relief = filtered - trend
    relief[mask] -= np.mean(relief[mask])
    relief[~mask] = 0
    return relief.astype(np.float32), trend.astype(np.float32)


def wrinkles(height, mask, radius=8, sensitivity=.015, metric=False, synthetic_mask=None):
    """Six angled local valley profiles, skeletonization, nearby peak-depth summary.

    Local profile comparisons replace whole-line peak detection. Deterministic;
    radius is pixels here, converted from user mm by the caller where calibrated.
    """
    radius = int(np.clip(radius, 2, 100))
    valid = np.asarray(mask, bool).copy()
    if synthetic_mask is not None:
        valid &= ~synthetic_mask
    safe = ndimage.binary_erosion(valid, iterations=radius, border_value=0)
    h = smooth_valid(height, valid, .7)
    y, x = np.indices(h.shape, dtype=float)
    candidates = np.zeros(h.shape, bool)
    local_depth = np.zeros(h.shape)
    for angle in (-60, -30, 0, 30, 60, 90):
        dx, dy = np.cos(np.deg2rad(angle)), np.sin(np.deg2rad(angle))
        left = np.stack([ndimage.map_coordinates(h, [y-dy*r, x-dx*r], order=1, mode="nearest") for r in range(1, radius+1)])
        right = np.stack([ndimage.map_coordinates(h, [y+dy*r, x+dx*r], order=1, mode="nearest") for r in range(1, radius+1)])
        depth = np.minimum(left.max(axis=0), right.max(axis=0)) - h
        # A central trough must be below its immediate neighbors on both sides.
        candidates |= (h <= left[0]) & (h < right[0]) & (depth > sensitivity)
        local_depth = np.maximum(local_depth, depth)
    valleys = skeletonize(candidates & safe)
    yy, xx = np.ogrid[-radius:radius+1, -radius:radius+1]
    peak = ndimage.maximum_filter(h, footprint=xx*xx+yy*yy <= radius*radius)
    depths = (peak-h)[valleys]
    summary = {"method": "six-angle local valleys; skeleton; highest peak in disk", "count": int(valleys.sum()),
               "quality_score_is_probability": False, "neighborhood_radius_px": radius,
               "metric_depths_available": bool(metric), "excluded_synthetic_pixels": True}
    if metric and len(depths):
        summary.update(median_depth_mm=float(np.median(depths)), p80_depth_mm=float(np.percentile(depths,80)))
    return valleys, summary


def seamless(height, mask, band=12):
    """Blend opposing edge strips; original stays untouched, changed pixels marked."""
    out = fill_nearest(height, mask).astype(float).copy()
    changed = ~mask.copy()
    band = min(max(1, int(band)), min(out.shape)//3)
    for a in range(band):
        weight = .5 * (1 - a / band)
        left, right = out[:, a].copy(), out[:, -1-a].copy()
        out[:, a] = left*(1-weight)+right*weight
        out[:, -1-a] = right*(1-weight)+left*weight
        top, bottom = out[a].copy(), out[-1-a].copy()
        out[a] = top*(1-weight)+bottom*weight
        out[-1-a] = bottom*(1-weight)+top*weight
        changed[:, [a, -1-a]] = True
        changed[[a, -1-a], :] = True
    # Corner blending can perturb endpoint equality; enforce exact periodic values.
    out[:, -1] = out[:, 0]
    out[-1] = out[0]
    return out.astype(np.float32), changed


def encode_height(height, mask):
    lo, hi = float(np.min(height[mask])), float(np.max(height[mask]))
    scale = (hi-lo)/65535 if hi > lo else 1/65535
    encoded = np.rint(np.clip((height-lo)/scale, 0, 65535)).astype(np.uint16)
    encoded[~mask] = 0
    return encoded, {"bias": lo, "scale_per_code": scale, "decode": "height = code * scale_per_code + bias",
                     "max_quantization_error": scale/2, "invalid": "consult valid_mask.png; code 0 is also valid minimum"}
