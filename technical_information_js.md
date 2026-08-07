# GelSight-Mini Tool: JS Implementation

This document summarizes the JavaScript implementation of the p5-based
GelSight-Mini View/Export Tool. It is intended for developers who need to
understand, maintain, or extend the browser implementation.

The user-facing document should be `README.md`. This file is the technical
companion.

## 1. Overview

The p5 project implements a browser-based depth reconstruction and export tool
for the GelSight Mini tactile sensor. The GelSight Mini appears to the computer
as a UVC webcam. Its elastomer surface is lit by colored raking illumination,
so each camera frame encodes local surface orientation through red, green, and
blue intensity patterns.

The browser pipeline is:

1. Capture a live camera frame or load a demo ZIP frame.
2. Crop the GelSight image to the useful sensor region.
3. Resize the crop to the reconstruction size.
4. Convert pixels into neural-network features.
5. Run a tiny per-pixel MLP to estimate surface gradients.
6. Integrate gradients into a scalar depth field using a Poisson solver.
7. Subtract a calibration baseline.
8. Display a grayscale depth preview and a 3D mesh.
9. Export PNG depth images, OBJ mesh, source capture, baseline, and metadata.

The implementation uses:

- p5.js for UI, drawing, interaction, and app structure.
- WebGL for fast crop-resize preprocessing and accelerated mesh rendering.
- WebAssembly for custom MLP inference.
- OpenCV.js for DCT/IDCT operations used by the Poisson solver.
- JavaScript for orchestration, export, metadata, and fallback paths.

The project began by examining the GelSight Robotics Python code. That code
uses a small learned neural model to estimate gradients, then integrates those
gradients into a height/depth field. The browser implementation follows the
same conceptual model, but replaces the Python/PyTorch runtime with browser
runtimes.

## 2. How The GelSight Solver Works

The GelSight Mini is not a depth camera in the usual sense. It is a camera
looking at the back side of a soft, reflective gel surface. When an object
presses into the gel, the camera sees the deformation of that surface.

Colored LEDs illuminate the surface from different directions. The red, green,
and blue pixel values therefore carry information about local surface slope.
In an ideal photometric-stereo setup, one could derive normals from known light
directions. The GelSight Robotics approach instead uses a learned calibration
model: a small neural network maps each pixel's color and position to local
surface gradient estimates.

The current model feature order is:

1. `B / 255`
2. `G / 255`
3. `R / 255`
4. `y / height`
5. `x / width`

The model outputs two gradient fields, approximately corresponding to `gx` and
`gy`. These gradients describe local surface slope, not depth directly.

To obtain a depth/height field, the system solves a Poisson integration
problem. In practical terms, it finds a scalar depth image whose derivatives
best match the predicted gradient fields. The result is then baseline-subtracted
using a calibration capture of the untouched gel.

The neural network is "AI" only in a narrow technical sense. It is a tiny MLP
used as a calibrated nonlinear color-to-gradient function. It is not a large
vision model, transformer, classifier, or generative model.

## 3. Application Structure

Important files:

- `p5/index.html`: browser entry point and script loading.
- `p5/sketch.js`: main p5 application, UI, camera handling, processing loop,
  mesh rendering setup, export orchestration, and metadata generation.
- `p5/gelsight-core.js`: image-processing and reconstruction primitives.
- `p5/export-utils.js`: ZIP, PNG, OBJ, and metadata export helpers.
- `p5/vendor/opencv.js`: custom OpenCV.js build with DCT/IDCT support.
- `p5/models/`: ONNX and custom MLP weight assets.
- `p5/wasm/`: custom WASM MLP implementation and compiled artifacts.
- `p5/captures/gelsight_demo.zip`: demo capture used by the Demo button.
- `tools/verify_gelsight_p5.js`: Playwright smoke test for the p5 app.

The main application state lives in a large `state` object in `p5/sketch.js`.
It tracks camera state, selected resolution, crop rectangle, calibration
baseline, smoothing buffers, inference mode, profiling data, mesh renderer
state, and export-specific state.

The UI is built dynamically in `createToolbar()`. Processing starts after
runtime initialization succeeds. Live frames are processed from the p5 `draw()`
loop, but processing is gated so duplicate draw frames do not repeatedly process
the same camera frame.

## 4. Camera Capture

The live GelSight Mini camera is accessed through `navigator.mediaDevices` and
`getUserMedia()`. The app exposes a camera chooser and a capture-resolution
menu.

Current capture resolution choices are:

- `640x480`
- `958x720`
- `1640x1232`
- `3280x2464`

The browser treats camera constraints as requests. The app records both the
requested resolution and the actual camera settings returned by the browser.

There are two source modes:

- `live`: frames come from the selected camera.
- `demo`: frames and baseline come from `p5/captures/gelsight_demo.zip`.

Demo ZIP metadata restores important state:

- crop rectangle
- baseline depth image
- baseline frame count
- selected camera resolution
- inference quality
- alpha smoothing
- lambda regularization

During export, `capture.png` is depth-synchronous: it is the frame used to
compute the exported depth and OBJ files. A separate high-resolution capture may
also be included in live mode, but that capture can be one frame stale relative
to the depth result.

If the selected live capture resolution is already `3280x2464`, the app skips
the separate high-resolution export because `capture.png` is already the large
capture.

## 5. Crop And Preprocessing

The crop rectangle is stored as normalized source coordinates:

```text
{ x, y, w, h }
```

The crop is constrained to a 4:3 aspect ratio. The top-left handle moves the
rectangle; the bottom-right handle scales it.

The minimum crop size is based on the reconstruction dimensions. The crop cannot
be made smaller than the fraction of the source image required to map to
`320x240`.

The main preprocessing path uses WebGL:

1. Upload the source camera/demo frame as a texture.
2. Draw the selected crop into a fixed-size offscreen target.
3. Read back the resulting `320x240` RGBA buffer.

This replaced a slower 2D-canvas crop-resize path. The 2D-canvas path was
measured at roughly 15-25 ms per frame on the tested machine, while WebGL
reduced crop-resize/readback to a few milliseconds.

### BGR vs RGB

Browser image data arrives as RGBA. The model, inherited from the GelSight
pipeline, expects feature columns in BGR order:

```text
B/255, G/255, R/255, y/height, x/width
```

This matters. Accidentally feeding RGB instead of BGR produces plausible-looking
but wrong gradient/depth estimates. The code comments in the preprocessing path
call this out directly.

## 6. Neural Network Inference

The original browser approach used ONNX Runtime Web with the neural model:

- default WASM execution provider
- WebGPU execution provider
- quantized ONNX model

In practice, ONNX Runtime Web was too slow for this particular workload. The MLP
is tiny, but it is evaluated for every pixel. The overhead of feeding many rows
through ONNX dominated performance.

The current fast path is a custom WASM MLP:

- model weights are stored in `p5/models/nnmini_mlp_weights.bin`
- JavaScript copies feature data into WASM memory
- WASM runs the MLP over all inference pixels
- JavaScript views the output gradient buffers

The custom MLP was then hand-vectorized with `wasm_simd128.h`. This is WASM
SIMD, not a shader. The implementation uses SIMD instructions inside the WASM
MLP inner loops to accelerate arithmetic on CPU vector lanes.

An FP16-weights experiment was also implemented. The idea was to store weights
more compactly while still doing FP32 math. On the tested system, this did not
produce a meaningful improvement, so the normal FP32-weight WASM model remains
the useful path.

## 7. Live Inference Resolution

The app has two live inference quality modes:

- `Fast (160x120)`: run the MLP on a half-resolution grid.
- `Full (320x240)`: run the MLP on the full reconstruction grid.

The exported depth images and OBJ mesh remain `320x240`. In Fast mode, gradient
fields are estimated at `160x120` and then bilinearly upsampled to `320x240`
before marker handling and Poisson integration.

This is a speed/quality tradeoff:

- Fast mode gives better interaction rate.
- Full mode preserves more spatial detail.
- Fast-mode depth is not truly native `320x240`; it is reconstructed from
  upsampled gradients.

## 8. Gradient Postprocessing

The gradient fields can become unstable if the gel is pressed hard or the model
sees values outside its comfortable training distribution. Earlier testing
found repeatable cases where the depth solver went blank because NaNs entered
the gradient/depth pipeline.

The app now sanitizes gradients before Poisson integration:

- non-finite values are detected
- bad values are replaced
- extreme gradients are clamped
- invalid/clamped counts are reported in profiling/debug output

This protects the downstream DCT/IDCT Poisson solver and mesh renderer from
NaN poisoning.

## 9. Poisson Integration

The neural network estimates local gradients. To turn gradients into a scalar
depth image, the app solves a Poisson equation.

The browser implementation uses OpenCV.js DCT and IDCT:

- `cv.dct`
- `cv.idct`

This required a custom OpenCV.js build. The small OpenCV build originally used
by the project did not expose the DCT functions needed by the solver.

Important terminology note: the current implementation uses DCT/IDCT for a
Neumann-boundary Poisson solve. It does not use DST. If the documentation or
conversation mentions "DST", read that as a solver-family concern; the actual
current OpenCV requirement is DCT/IDCT.

The OpenCV.js build process involved patching OpenCV's JavaScript config so the
DCT functions are included in the generated JS bindings. The build is documented
separately in the OpenCV build notes.

### Lambda Regularization

The Poisson solve includes a small regularization lambda:

```text
depthDct = -divergenceDct / (laplacianEigenvalue + lambda)
```

Lambda damps unstable low-frequency behavior in the integration. The UI exposes
it as a slider with a small range. Changing lambda changes the baseline-compatible
math, so live calibration is marked stale when lambda changes.

## 10. Calibration

Calibration captures the untouched gel and uses it as a baseline depth field.
The app collects 50 distinct camera frames. This is important: calibration should
not average 50 animation frames if the camera has not produced 50 new images.

The frame identity is tracked using browser video frame information when
available, with a fallback based on video time.

During calibration:

1. Raw depth is reconstructed without baseline subtraction.
2. The raw depth is accumulated.
3. After 50 distinct frames, the average becomes `state.baseline`.
4. Future depth frames use:

```text
depth = rawDepth - baselineDepth
```

The live Calibrate button pulses when calibration is missing or stale. It stops
pulsing after a completed calibration.

Changes that make calibration stale include:

- changing lambda
- moving/scaling the crop rectangle
- changing inference quality
- changing capture resolution

Inference-quality and capture-resolution changes discard the baseline entirely.
Lambda and crop changes mark the baseline stale while preserving the old
baseline until the user recalibrates.

## 11. Temporal And Display Smoothing

Several smoothing strategies were added to improve visual stability.

### Input Alpha Smoothing

Input smoothing runs before solving:

```text
runningAvg = alpha * runningAvg + (1 - alpha) * input
```

The default alpha is currently `0.6`. Higher values reduce flicker but increase
latency. The smoothing is applied to the preprocessed `320x240` RGBA frame
before BGR feature extraction.

### Display Range Smoothing

The grayscale depth preview originally normalized each frame using the raw
minimum and maximum depth. That caused flicker because min/max values are noisy.
It also caused gradual blooming/high-contrast feedback-like behavior in some
conditions.

The current display normalization uses:

- histogram percentiles
- p01/p99 bounds
- 5% headroom
- minimum span protection
- flat idle locking to a wider zero-centered range
- asymmetric temporal smoothing

The display range is used for:

- grayscale depth preview normalization
- mesh shader color depth range

The display range is only for visualization. It does not change the exported
absolute solver-units depth image.

## 12. Depth Images And Units

Internal depth values are in solver units. They should not be assumed to be
millimeters. A physical calibration procedure would be needed to convert solver
units to metric displacement.

The ZIP export includes two depth PNGs.

### `depth_16bit.png`

This is a normalized 16-bit grayscale depth image:

```text
uint16 = round((depth - DepthMin) / (DepthMax - DepthMin) * 65535)
```

Its min/max values are recorded in `metadata.json`. This image is convenient for
visualization, but different captures can have different normalization ranges.

### `depth_solver_units_16bit.png`

This is a fixed-range solver-units image:

```text
uint16 = clamp(round(depth * 1000 + 32768), 0, 65535)
depth = (uint16 - 32768) / 1000
```

The intended range is:

```text
[-32.768, 32.767]
```

This image is better for stitching or comparing multiple captures because the
encoding is consistent across exports.

### `baseline_16bit.png`

If calibration is available, the baseline is exported too. The demo ZIP loader
uses this baseline when loading a saved project/demo capture.

## 13. 3D Mesh Rendering

The original mesh renderer used p5 line drawing. Profiling showed that drawing
a low-resolution wireframe mesh this way could cost more than 100 ms per frame.
That was the main frame-rate bottleneck for a period of the project.

The current renderer uses WebGL:

- depth is uploaded to a texture or buffer
- the GPU renders a filled shaded heightfield
- sparse wire overlay is drawn on top
- smooth normals are computed for the shaded surface

The old wireframe code is retained as a fallback path, but the accelerated
renderer is the normal path.

The mesh uses 16-bit indices. Full-resolution line meshes can exceed 16-bit
index limits on systems without `uint32` element index support, so the minimum
mesh step is constrained accordingly.

The 3D view also has a bilinear interpolation checkbox. When enabled, the shader
samples depth bilinearly and computes smoother normals from neighboring depth
texels. When disabled, the view falls back to the previous, more discrete mesh
look.

The Z slider controls preview scale only. It does not affect OBJ export.

## 14. Export Format

Exports are ZIP files named:

```text
gelsight_YYYYMMDD_HHMMSS.zip
```

Typical contents:

- `capture.png`
- optional `capture_highres.jpg` or `capture_highres.png`
- `depth_16bit.png`
- `depth_solver_units_16bit.png`
- `baseline_16bit.png`
- `mesh.obj`
- `metadata.json`

`capture.png`, depth PNGs, and OBJ are synchronized to the same processed frame.
The optional high-resolution capture is a live-camera convenience image and can
be one frame stale relative to the depth.

The high-resolution file defaults to JPEG to save space. PNG remains supported
in code.

## 15. Metadata

`metadata.json` is intentionally verbose. It records enough context to interpret
an export later and to diagnose processing differences between captures.

Important metadata sections include:

- `schema`
- `version`
- `app`
- `source`
- `files`
- `camera`
- `exportProcess`
- `crop`
- `preprocessing`
- `inference`
- `poissonIntegration`
- `calibration`
- `liveDisplay`
- `controls`
- `meshPreview`
- `computerVision`

The app version policy is:

```text
Increment APP_VERSION by 0.001 for every app change.
```

The version is displayed in the UI and written into export metadata.

## 16. Performance History And Current Bottlenecks

Major bottlenecks found during development:

- ONNX Runtime Web inference overhead
- 2D-canvas crop-resize
- p5 wireframe mesh drawing
- per-frame depth image min/max normalization

Major optimizations:

- custom WASM MLP
- hand-vectorized WASM SIMD inner loops
- WebGL crop-resize
- histogram-based depth preview generation
- WebGL mesh renderer
- optional `160x120` live inference mode

The `p` key prints profiling data to the browser console. Useful fields include:

- `frameMs`
- `inferencePixels`
- `wasmMlpUsPerPixel`
- `cropResize`
- `webglReadback`
- `poisson`
- `depthImage`
- mesh draw/profile fields

There are also browser-console helpers exposed through `window.__gelsightState`
and related diagnostic functions.

## 17. Browser And Platform Requirements

The app expects:

- browser support for camera capture through `getUserMedia`
- local host or another secure context for camera permissions
- WebGL support
- WASM support
- preferably WASM SIMD support
- OpenCV.js with DCT/IDCT support

Browser camera resolution negotiation is not exact. The app records actual
stream settings so exports document what the browser really delivered.

## 18. Development And Build Notes

JavaScript dependencies are recorded by:

- `p5/package.json`
- `p5/package-lock.json`

`p5/node_modules/` should not be committed. It is recreated with `npm install`
inside the `p5/` directory.

The custom OpenCV.js build workspace should also not be committed. The useful
runtime artifact is the generated OpenCV.js file in `p5/vendor/`.

The custom WASM MLP artifacts live under `p5/wasm/` and are loaded by the p5
app. Rebuilding them requires the local WASM toolchain used during development.

The main smoke test is:

```sh
node tools/verify_gelsight_p5.js http://127.0.0.1:8002/p5/
```

Syntax checks commonly used during development:

```sh
node --check p5/sketch.js
node --check tools/verify_gelsight_p5.js
```

## 19. Known Limitations

- Solver units are not calibrated millimeters.
- The MLP is specific to the GelSight Mini image statistics and training setup.
- Sensor edges can be noisy; crop placement matters.
- Extreme pressure can still produce unstable inputs.
- Browser camera resolution selection is best-effort.
- Fast mode sacrifices spatial detail.
- The display normalization is for visualization, not measurement.
- The optional high-resolution capture can be one frame stale.

## 20. Future Work

Possible future improvements:

- physical calibration from solver units to millimeters
- retraining or improving the MLP
- revisiting WebGPU inference if browser runtimes improve
- noisy-region masking or paintable zero-displacement regions
- multi-capture stitching support
- formal metadata schema documentation
- additional mesh export formats
- confidence or validity mask export
- more robust camera-resolution probing

## 21. License And Redistributed Components

This project should be distributed under the GNU General Public License,
version 3 or later (GPLv3+):

```text
GPL-3.0-or-later
```

This is the conservative licensing choice because the JavaScript tool is based
on the GelSight Robotics reconstruction approach, and the local GelSight
Robotics reference code is distributed under GPLv3. The app also redistributes
model artifacts derived from the GelSight Mini model checkpoint.

Redistributed or derived GelSight components include:

- `p5/models/nnmini.onnx`
- `p5/models/nnmini_quant_int8.onnx`
- `p5/models/nnmini_mlp_weights.bin`
- `p5/models/nnmini_mlp_weights_fp16.bin`

These are converted, packed, or quantized forms of the GelSight Mini neural
network used to map per-pixel color/position features to surface-gradient
estimates. Treat them as GelSight-derived model assets.

The browser app also redistributes third-party runtime assets with their own
licenses, including:

- `p5/p5.js`: p5.js and bundled p5 dependencies.
- `p5/vendor/opencv-gelsight.js` and `p5/vendor/opencv_js.wasm`: custom
  OpenCV.js build artifacts.
- `p5/wasm/gelsight_mlp.js` and `p5/wasm/gelsight_mlp.wasm`: project-specific
  WASM MLP runtime generated from this repository's C source.
- `p5/package.json` and `p5/package-lock.json`: npm dependency declarations,
  currently including `onnxruntime-web`.

`p5/node_modules/` should not be committed. It is recreated from
`p5/package-lock.json`.

The repository should include a top-level `LICENSE` file containing the GPLv3
license text, plus any third-party notices required by redistributed browser
assets. The project README should state the license in SPDX form:

```text
SPDX-License-Identifier: GPL-3.0-or-later
```

This section is a practical engineering summary, not legal advice. If the
project is used commercially or redistributed broadly, confirm the licensing of
the GelSight model weights and any bundled third-party binaries.
