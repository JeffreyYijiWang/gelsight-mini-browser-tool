#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import onnx
from onnx import numpy_helper


ROOT = Path(__file__).resolve().parents[1]
LAYER_ORDER = (
    "fc1.weight",
    "fc1.bias",
    "fc2.weight",
    "fc2.bias",
    "fc3.weight",
    "fc3.bias",
    "fc4.weight",
    "fc4.bias",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export GelSight RGB2NormNet MLP weights as packed float32 and float16.",
    )
    parser.add_argument(
        "--onnx",
        type=Path,
        default=ROOT / "p5" / "models" / "nnmini.onnx",
        help="Input fp32 ONNX model.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "p5" / "models" / "nnmini_mlp_weights.bin",
        help="Output raw little-endian float32 weights.",
    )
    parser.add_argument(
        "--output-fp16",
        type=Path,
        default=ROOT / "p5" / "models" / "nnmini_mlp_weights_fp16.bin",
        help="Output raw little-endian float16 weights.",
    )
    args = parser.parse_args()

    model = onnx.load(args.onnx)
    initializers = {
        tensor.name: numpy_helper.to_array(tensor) for tensor in model.graph.initializer
    }
    missing = [name for name in LAYER_ORDER if name not in initializers]
    if missing:
        raise RuntimeError(f"Missing ONNX initializers: {', '.join(missing)}")

    packed = np.concatenate(
        [
            np.ascontiguousarray(initializers[name], dtype="<f4").reshape(-1)
            for name in LAYER_ORDER
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    packed.tofile(args.output)
    packed_fp16 = np.ascontiguousarray(packed, dtype="<f2")
    args.output_fp16.parent.mkdir(parents=True, exist_ok=True)
    packed_fp16.tofile(args.output_fp16)

    print(f"wrote {args.output}")
    print(f"float_count={packed.size}")
    print(f"byte_count={args.output.stat().st_size}")
    print(f"wrote {args.output_fp16}")
    print(f"float16_count={packed_fp16.size}")
    print(f"float16_byte_count={args.output_fp16.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
