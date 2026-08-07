#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EMSDK="$ROOT/opencv-build/emsdk"
OPENCV="$ROOT/opencv-build/opencv-4.12.0"
BUILD="$ROOT/opencv-build/build-opencv-js"

# The required DCT exports are enabled in:
#   opencv-4.12.0/modules/core/misc/js/gen_dict.json
#   opencv-4.12.0/platforms/js/opencv_js.config.py
# The module-level gen_dict.json is the one OpenCV 4.12's default JS build uses.
EMSDK_QUIET=1 source "$EMSDK/emsdk_env.sh"

python3 "$OPENCV/platforms/js/build_js.py" "$BUILD" \
  --opencv_dir "$OPENCV" \
  --build_wasm \
  --disable_single_file \
  --simd \
  --build_loader

cp "$BUILD/bin/opencv.js" "$ROOT/p5/vendor/opencv-gelsight.js"
cp "$BUILD/bin/opencv_js.wasm" "$ROOT/p5/vendor/opencv_js.wasm"
cp "$BUILD/bin/loader.js" "$ROOT/p5/vendor/opencv-gelsight-loader.js"
