"""Explicit permanent-gel exclusions. Never infer that a puncture is measured surface."""
import numpy as np
from scipy.ndimage import binary_dilation


def validate_regions(regions):
    values = np.asarray(regions, dtype=float)
    if values.ndim != 2 or values.shape[1] != 4 or not 1 <= len(values) <= 64:
        raise ValueError('Damage regions must contain 1–64 normalized ellipses [x,y,rx,ry].')
    if not np.isfinite(values).all() or np.any(values[:, :2] < 0) or np.any(values[:, :2] > 1) or np.any(values[:, 2:] <= 0) or np.any(values[:, 2:] > .5):
        raise ValueError('Damage regions must have finite centers in [0,1] and radii in (0,0.5].')
    return values.tolist()


def damage_mask(shape, regions, crop=(0, 0, 1, 1)):
    """Regions use full-source normalized coordinates; return invalid target pixels."""
    regions = validate_regions(regions)
    h, w = shape
    y, x = np.indices(shape, dtype=float)
    x = crop[0]+(x+.5)/w*crop[2]; y = crop[1]+(y+.5)/h*crop[3]
    invalid = np.zeros(shape, bool)
    for cx, cy, rx, ry in regions:
        invalid |= ((x-cx)/rx)**2+((y-cy)/ry)**2 <= 1
    invalid = binary_dilation(invalid, iterations=2)  # documented processing-grid safety margin
    if invalid.mean() > .5:
        raise ValueError('Damage excludes more than half the sensing area. Reduce the mask or replace the damaged gel.')
    return invalid
