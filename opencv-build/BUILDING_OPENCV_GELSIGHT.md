# Building Patched OpenCV.js for GelSight

This project needs OpenCV.js with `cv.dct` and `cv.idct` exported so the browser can run the same DCT-based Poisson integration used by the Python GelSight reconstruction code.

The stock OpenCV.js builds expose `cv.dft`, but not `cv.dct` or `cv.idct`.

## Local Layout

The build uses these local paths:

```text
opencv-build/
  emsdk/                 Emscripten SDK
  opencv-4.12.0/         OpenCV source
  build-opencv-js/       OpenCV.js build output
  build-opencv-gelsight.sh
  test-opencv-gelsight-dct.js

p5/vendor/
  opencv-gelsight.js
  opencv-gelsight-loader.js
  opencv_js.wasm
```

## One-Time Setup

Clone Emscripten:

```sh
git clone https://github.com/emscripten-core/emsdk.git opencv-build/emsdk
```

Install and activate the pinned Emscripten version:

```sh
opencv-build/emsdk/emsdk install 3.1.64
opencv-build/emsdk/emsdk activate 3.1.64
```

Clone OpenCV:

```sh
git clone --depth 1 --branch 4.12.0 https://github.com/opencv/opencv.git opencv-build/opencv-4.12.0
```

## Patch DCT Exports

Patch the module-level JavaScript whitelist:

```diff
--- a/modules/core/misc/js/gen_dict.json
+++ b/modules/core/misc/js/gen_dict.json
@@
- "determinant", "dft", "divide", "eigen",
+ "determinant", "dct", "idct", "dft", "divide", "eigen",
```

Also patch the legacy/platform config for clarity:

```diff
--- a/platforms/js/opencv_js.config.py
+++ b/platforms/js/opencv_js.config.py
@@
- 'determinant', 'dft', 'divide', 'eigen',
+ 'determinant', 'dct', 'idct', 'dft', 'divide', 'eigen',
```

Important: for OpenCV 4.12, `modules/core/misc/js/gen_dict.json` is the patch that actually affects the default JS build. `platforms/js/opencv_js.config.py` alone is not enough unless the build is run with an explicit `--config`.

## Build

Use the checked-in build wrapper:

```sh
opencv-build/build-opencv-gelsight.sh
```

The wrapper:

1. Sources `opencv-build/emsdk/emsdk_env.sh`.
2. Runs OpenCV's `platforms/js/build_js.py`.
3. Builds non-threaded WASM with SIMD.
4. Copies the output into `p5/vendor/`.

The current build intentionally does not enable threads. Threaded WASM would require cross-origin isolation headers in the browser.

## Output Files

After a successful build:

```text
p5/vendor/opencv-gelsight.js
p5/vendor/opencv-gelsight-loader.js
p5/vendor/opencv_js.wasm
```

`opencv-gelsight.js` is a small loader/wrapper. The OpenCV implementation is in `opencv_js.wasm`.

## Verify

Run the smoke test:

```sh
node opencv-build/test-opencv-gelsight-dct.js
```

Expected output:

```text
OpenCV.js DCT smoke test passed
dct=function idct=function dft=function
```

The test checks that:

1. `cv.dct` exists.
2. `cv.idct` exists.
3. `cv.dft` still exists.
4. `idct(dct([[1, 2], [3, 4]]))` round-trips back to the original matrix.

## Notes

- The first attempt at patching only `platforms/js/opencv_js.config.py` built successfully but did not export `dct` or `idct`.
- The effective OpenCV 4.12 whitelist is generated from module-level `misc/js/gen_dict.json` files.
- The generated build currently includes the stock OpenCV.js module set, which is larger than we need. If size becomes a problem, the next step is a smaller custom build containing only `core`, selected `imgproc` utilities, and the DCT/IDCT exports.
