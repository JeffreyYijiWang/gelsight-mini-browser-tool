#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
GSROBOTICS = ROOT / "gsrobotics"
sys.path.insert(0, str(GSROBOTICS))

from utilities.image_processing import (
    apply_cmap,
    color_map_from_txt,
    crop_and_resize,
    normalize_array,
    trim_outliers,
)
from utilities.reconstruction import Reconstruction3D


def write_obj(path: Path, depth: np.ndarray, scale_z: float) -> None:
    height, width = depth.shape
    with path.open("w", encoding="utf-8") as f:
        f.write("# GelSight depth grid\n")
        for y in range(height):
            for x in range(width):
                f.write(f"v {x} {-y} {depth[y, x] * scale_z:.8f}\n")
        for y in range(height - 1):
            for x in range(width - 1):
                a = y * width + x + 1
                b = a + 1
                c = a + width
                d = c + 1
                f.write(f"f {a} {c} {b}\n")
                f.write(f"f {b} {c} {d}\n")


def reconstruct_image(
    image_bgr: np.ndarray,
    model_path: Path,
    width: int,
    height: int,
    border_fraction: float,
    marker_range: tuple[int, int] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # CRITICAL: pass OpenCV BGR into Reconstruction3D, not RGB.
    # Swapping to RGB causes large false normal/depth artifacts near the image top.
    frame = crop_and_resize(
        image=image_bgr,
        target_size=(width, height),
        border_fraction=border_fraction,
    )
    reconstruction = Reconstruction3D(
        image_width=width,
        image_height=height,
        use_gpu=False,
    )
    if reconstruction.load_nn(str(model_path)) is None:
        raise RuntimeError(f"Could not load model: {model_path}")

    reconstruction.depth_map_zero_counter = 51
    depth, contact_mask, grad_x, grad_y = reconstruction.get_depthmap(
        image=frame,
        markers_threshold=marker_range,
    )
    return frame, depth, contact_mask, grad_x, grad_y


def save_outputs(
    output_prefix: Path,
    frame_bgr: np.ndarray,
    depth: np.ndarray,
    contact_mask: np.ndarray,
    grad_x: np.ndarray,
    grad_y: np.ndarray,
    cmap_path: Path,
    obj_scale_z: float,
) -> None:
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_prefix.with_suffix(".frame.png")), frame_bgr)
    np.save(str(output_prefix.with_suffix(".depth.npy")), depth)
    np.save(str(output_prefix.with_suffix(".grad_x.npy")), grad_x)
    np.save(str(output_prefix.with_suffix(".grad_y.npy")), grad_y)
    cv2.imwrite(
        str(output_prefix.with_suffix(".mask.png")),
        (contact_mask * 255).astype(np.uint8),
    )

    depth_trimmed = trim_outliers(depth, 1, 99)
    depth_vis = normalize_array(depth_trimmed, min_divider=10)
    cmap = color_map_from_txt(str(cmap_path), is_bgr=True)
    cv2.imwrite(
        str(output_prefix.with_suffix(".depth.png")),
        cv2.cvtColor(apply_cmap(depth_vis, cmap).astype(np.uint8), cv2.COLOR_RGB2BGR),
    )
    write_obj(output_prefix.with_suffix(".obj"), depth, obj_scale_z)


def parse_marker_range(value: str) -> tuple[int, int] | None:
    if value.lower() in {"none", "off", "false"}:
        return None
    low, high = value.split(",", 1)
    return int(low), int(high)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run GelSight Mini neural depth reconstruction on a still image."
    )
    parser.add_argument("image", type=Path, help="Input GelSight image.")
    parser.add_argument("--output-prefix", type=Path, default=Path("python/out/reconstruction"))
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=240)
    parser.add_argument("--border-fraction", type=float, default=0.15)
    parser.add_argument("--model", type=Path, default=GSROBOTICS / "models" / "nnmini.pt")
    parser.add_argument("--cmap", type=Path, default=GSROBOTICS / "cmap.txt")
    parser.add_argument(
        "--marker-range",
        type=parse_marker_range,
        default=(0, 70),
        help="'low,high' grayscale range or 'none'.",
    )
    parser.add_argument("--obj-scale-z", type=float, default=1.0)
    args = parser.parse_args()

    # CRITICAL: cv2.imread returns BGR, and that is what the GelSight NN expects.
    # Do not convert this image to RGB before reconstruction.
    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read image: {args.image}")

    frame, depth, contact_mask, grad_x, grad_y = reconstruct_image(
        image_bgr=image,
        model_path=args.model,
        width=args.width,
        height=args.height,
        border_fraction=args.border_fraction,
        marker_range=args.marker_range,
    )
    save_outputs(
        args.output_prefix,
        frame,
        depth,
        contact_mask,
        grad_x,
        grad_y,
        args.cmap,
        args.obj_scale_z,
    )
    print(f"wrote {args.output_prefix}.depth.npy")
    print(
        f"depth min={float(np.nanmin(depth)):.6f} "
        f"max={float(np.nanmax(depth)):.6f} "
        f"mean={float(np.nanmean(depth)):.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
