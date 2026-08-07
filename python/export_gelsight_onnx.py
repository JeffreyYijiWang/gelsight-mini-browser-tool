#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch


ROOT = Path(__file__).resolve().parents[1]
GSROBOTICS = ROOT / "gsrobotics"
sys.path.insert(0, str(GSROBOTICS))

from utilities.reconstruction import RGB2NormNet


def load_model(model_path: Path) -> RGB2NormNet:
    model = RGB2NormNet().float()
    state = torch.load(model_path, map_location="cpu")
    model.load_state_dict(state["state_dict"])
    model.eval()
    return model


def export_onnx(model: RGB2NormNet, output_path: Path, opset: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    example = torch.zeros((16, 5), dtype=torch.float32)
    torch.onnx.export(
        model,
        example,
        str(output_path),
        input_names=["features"],
        output_names=["normal_xy"],
        dynamic_axes={
            "features": {0: "num_pixels"},
            "normal_xy": {0: "num_pixels"},
        },
        opset_version=opset,
    )


def verify_export(model: RGB2NormNet, output_path: Path) -> float:
    rng = np.random.default_rng(20260806)
    samples = rng.random((2048, 5), dtype=np.float32)
    with torch.no_grad():
        torch_out = model(torch.from_numpy(samples)).numpy()

    session = ort.InferenceSession(str(output_path), providers=["CPUExecutionProvider"])
    onnx_out = session.run(None, {"features": samples})[0]
    return float(np.max(np.abs(torch_out - onnx_out)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export GelSight Mini normal model to ONNX.")
    parser.add_argument(
        "--model",
        type=Path,
        default=GSROBOTICS / "models" / "nnmini.pt",
        help="Input PyTorch checkpoint from gsrobotics.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "p5" / "models" / "nnmini.onnx",
        help="Output ONNX model path served by the p5 sketch.",
    )
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--max-error", type=float, default=1e-5)
    args = parser.parse_args()

    model = load_model(args.model)
    export_onnx(model, args.output, args.opset)
    max_abs_error = verify_export(model, args.output)
    print(f"wrote {args.output}")
    print(f"torch-vs-onnx max_abs_error={max_abs_error:.8g}")
    if max_abs_error > args.max_error:
        raise RuntimeError(
            f"ONNX verification failed: max_abs_error {max_abs_error} > {args.max_error}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
