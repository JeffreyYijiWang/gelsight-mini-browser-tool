#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
GSROBOTICS = ROOT / "gsrobotics"
sys.path.insert(0, str(GSROBOTICS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reconstruct_gelsight import save_outputs
from utilities.gelsightmini import GelSightMini
from utilities.reconstruction import Reconstruction3D


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe a GelSight Mini UVC camera and optionally reconstruct depth."
    )
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=240)
    parser.add_argument("--border-fraction", type=float, default=0.15)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--output-prefix", type=Path, default=Path("python/out/camera_probe"))
    parser.add_argument("--model", type=Path, default=GSROBOTICS / "models" / "nnmini.pt")
    parser.add_argument("--cmap", type=Path, default=GSROBOTICS / "cmap.txt")
    parser.add_argument("--no-depth", action="store_true")
    args = parser.parse_args()

    stream = GelSightMini(
        target_width=args.width,
        target_height=args.height,
        border_fraction=args.border_fraction,
    )
    devices = stream.get_device_list()
    print(f"available cameras: {devices}")
    stream.select_device(args.camera_index)
    stream.start()

    reconstruction = None
    if not args.no_depth:
        reconstruction = Reconstruction3D(
            image_width=args.width,
            image_height=args.height,
            use_gpu=False,
        )
        if reconstruction.load_nn(str(args.model)) is None:
            raise RuntimeError(f"Could not load model: {args.model}")

    last_frame_bgr = None
    last_depth = None
    last_mask = None
    last_grad_x = None
    last_grad_y = None
    try:
        for idx in range(args.frames):
            frame = stream.update(dt=0)
            if frame is None:
                time.sleep(0.02)
                continue
            # CRITICAL: GelSightMini.update() returns RGB, but the GelSight NN
            # expects OpenCV BGR. Feeding RGB creates false noisy depth patches.
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            last_frame_bgr = frame_bgr
            if reconstruction is not None:
                (
                    last_depth,
                    last_mask,
                    last_grad_x,
                    last_grad_y,
                ) = reconstruction.get_depthmap(
                    image=frame_bgr,
                    markers_threshold=(0, 70),
                )
            print(f"frame {idx + 1}/{args.frames} fps={stream.fps:.1f}", flush=True)
    finally:
        if stream.camera is not None:
            stream.camera.release()

    if last_frame_bgr is None:
        raise RuntimeError("No frames captured.")

    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    if reconstruction is None:
        cv2.imwrite(
            str(args.output_prefix.with_suffix(".frame.png")),
            last_frame_bgr,
        )
        print(f"wrote {args.output_prefix}.frame.png")
    else:
        assert (
            last_depth is not None
            and last_mask is not None
            and last_grad_x is not None
            and last_grad_y is not None
        )
        save_outputs(
            output_prefix=args.output_prefix,
            frame_bgr=last_frame_bgr,
            depth=last_depth,
            contact_mask=last_mask,
            grad_x=last_grad_x,
            grad_y=last_grad_y,
            cmap_path=args.cmap,
            obj_scale_z=1.0,
        )
        print(f"wrote {args.output_prefix}.depth.npy")
        print(
            f"depth min={float(np.nanmin(last_depth)):.6f} "
            f"max={float(np.nanmax(last_depth)):.6f} "
            f"mean={float(np.nanmean(last_depth)):.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
