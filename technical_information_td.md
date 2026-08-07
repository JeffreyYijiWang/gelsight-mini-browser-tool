# Technical Information: TouchDesigner Roadmap

This document outlines a possible roadmap for turning the GelSight-Mini
View/Export Tool into a TouchDesigner TOP workflow.

The goal would be a TouchDesigner operator that captures or receives a GelSight
Mini camera image and produces both a regular video image and a reconstructed
depth image.

## 1. Recommended Architecture

The most practical first version should not capture the camera directly.
Instead, it should consume an existing TouchDesigner video TOP:

```text
Video Device In TOP -> GelSight Depth TOP
```

TouchDesigner already has robust camera selection, camera resolution selection,
device reconnect behavior, and video texture handling. Reusing `Video Device In
TOP` keeps the custom GelSight operator focused on reconstruction rather than
camera plumbing.

The custom node would be a C++ TOP plugin that accepts the GelSight RGB camera
image as input and outputs a reconstructed image.

## 2. Possible Operator Designs

### Single Custom TOP With Output Mode

One `GelSight Depth TOP` could expose an `Output Mode` menu:

- `Camera RGB`
- `Depth Preview`
- `Depth Float`
- `Gradient X`
- `Gradient Y`
- `Normals`

This is simple and fits TouchDesigner's TOP model, but only one image output is
visible per node instance. Users could create multiple instances with different
output modes if they need several outputs at once.

### Multiple Companion TOPs

Another design would use a small family of operators:

- `GelSight Capture TOP`
- `GelSight Depth TOP`
- `GelSight Normal TOP`

This may feel more TouchDesigner-native for complex networks, but it increases
implementation and maintenance cost.

### Multi-Output Operator

A multi-output operator would be ideal if TouchDesigner plugin support makes it
straightforward:

- output 0: RGB camera image
- output 1: depth image
- output 2: normals or gradients

This should be verified against the TouchDesigner C++ TOP plugin API before
committing to it.

## 3. Processing Pipeline

The TouchDesigner implementation can use the same conceptual pipeline as the
JavaScript app:

```text
GelSight frame
  -> crop/resize
  -> BGR feature extraction
  -> tiny MLP gradient inference
  -> gradient sanitization
  -> Poisson integration
  -> baseline subtraction
  -> output TOP image
```

The target reconstruction size would initially remain `320x240`, matching the
current browser implementation.

## 4. Camera Capture

Preferred first version:

- Use TouchDesigner's `Video Device In TOP`.
- Feed its output into the custom GelSight TOP.
- Let TouchDesigner handle UVC device selection and capture resolution.

Possible later version:

- Capture the GelSight Mini directly inside the plugin.
- Use platform APIs such as AVFoundation on macOS or Media Foundation on
  Windows.
- Or use OpenCV camera capture.

Direct capture would make the plugin more self-contained, but it would also
duplicate functionality TouchDesigner already provides.

## 5. Preprocessing

The plugin needs to crop the incoming camera image and resize it to the solver
input size.

Initial implementation:

- CPU/OpenCV crop and resize.
- Convert incoming RGB/RGBA pixels into BGR model feature order.
- Add normalized pixel coordinates `y/height` and `x/width`.

Later optimization:

- GPU shader crop-resize.
- Direct texture-to-compute path if the plugin architecture makes that practical.

The BGR/RGB issue remains important. The model expects:

```text
B/255, G/255, R/255, y/height, x/width
```

Supplying RGB instead of BGR produces incorrect reconstruction.

## 6. MLP Inference

The tiny GelSight neural network should be ported from the browser WASM path to
plain native C++.

Recommended path:

- Reuse the packed weight format from `p5/models/nnmini_mlp_weights.bin`.
- Port the current `p5/wasm/gelsight_mlp.c` implementation to C++.
- Run dense layers/ReLU directly in native code.

This avoids embedding PyTorch or ONNX Runtime in the TouchDesigner plugin.

The MLP is small:

- 5 input features
- hidden layers with ReLU
- 2 output gradient values

Native C++ should be substantially faster than browser ONNX or browser WASM.
SIMD can be added with compiler auto-vectorization, platform intrinsics, Eigen,
xsimd, or another small vector math helper.

## 7. Poisson Integration

The depth solver should use OpenCV C++:

- `cv::dct`
- `cv::idct`

This is simpler than the browser version, where a custom OpenCV.js build was
required to expose DCT/IDCT.

The solver would use the same DCT Neumann Poisson formulation:

```text
depthDct = -divergenceDct / (laplacianEigenvalue + lambda)
```

The plugin should expose `Lambda` as a TouchDesigner parameter.

## 8. Calibration

Calibration should follow the browser implementation:

1. User presses a `Calibrate` pulse parameter.
2. Plugin accumulates 50 distinct input frames.
3. It reconstructs raw depth for each frame.
4. It averages the raw depth into a baseline.
5. Future outputs subtract that baseline:

```text
depth = rawDepth - baselineDepth
```

The plugin should mark calibration stale when parameters that affect baseline
compatibility change:

- crop rectangle
- lambda
- inference mode
- input resolution or solver resolution

Useful calibration features:

- save baseline to disk
- load baseline from disk
- expose calibration frame count
- expose calibrated/uncalibrated/stale status

## 9. Output Formats

The plugin should support at least two depth output modes.

### Depth Preview

An 8-bit or 16-bit visual image suitable for monitoring:

- normalized for display
- uses p01/p99 percentile range
- uses display headroom
- uses temporal smoothing of display min/max

This is useful for visual feedback but should not be treated as measurement
data.

### Depth Float

A true data output:

- preferably 32-bit float
- single-channel if TouchDesigner supports it cleanly
- otherwise RGBA float with depth in the red channel
- values in solver units

This output is better for downstream measurement, compositing, geometry
generation, or stitching workflows.

Optional outputs:

- gradient X
- gradient Y
- normals
- confidence or validity mask
- baseline depth

## 10. TouchDesigner Parameters

Suggested parameters:

- `Output Mode`: camera, preview depth, float depth, gradient X, gradient Y,
  normals
- `Crop X`
- `Crop Y`
- `Crop Width`
- `Crop Height`
- `Inference Quality`: fast/full
- `Alpha`: temporal input smoothing
- `Lambda`: Poisson regularization
- `Calibrate`: pulse
- `Reset Baseline`
- `Save Baseline`
- `Load Baseline`
- `Display Percentile Low`
- `Display Percentile High`
- `Display Headroom`
- `Display Range Smoothing`

The crop controls should preserve the desired 4:3 aspect ratio unless an
advanced mode disables that constraint.

## 11. Temporal And Display Smoothing

The TouchDesigner implementation should keep the browser app's smoothing
strategy:

- input alpha smoothing before inference
- histogram percentile display normalization
- p01/p99 display bounds
- headroom around the percentile range
- minimum-span protection
- flat idle locking to a wider zero-centered range
- asymmetric temporal smoothing for display min/max

This reduces flicker in both the depth preview and any downstream visualization.

The float depth output should not be display-normalized. It should preserve
solver units.

## 12. Performance Expectations

A native C++ TouchDesigner plugin should be significantly faster than the
browser prototype.

Reasons:

- native C++ MLP inference avoids browser runtime overhead
- OpenCV C++ DCT/IDCT avoids OpenCV.js overhead
- TouchDesigner already manages GPU textures efficiently
- p5 mesh rendering bottlenecks do not apply

Estimated effort:

- prototype TOP consuming input TOP and outputting depth preview: 2-4 days
- native C++ MLP, OpenCV Poisson, and calibration parameters: 1-2 weeks
- polished distributable plugin with docs, macOS/Windows builds, saved
  calibration, and robust error handling: 2-4 weeks

## 13. Implementation Phases

### Phase 1: CPU Prototype

- Create a C++ TOP plugin.
- Accept one input TOP.
- Read pixels to CPU.
- Crop/resize with OpenCV.
- Run native C++ MLP.
- Solve depth with OpenCV DCT/IDCT.
- Output normalized depth preview.

### Phase 2: Calibration And Parameters

- Add crop parameters.
- Add alpha and lambda parameters.
- Add calibrate pulse.
- Accumulate 50-frame baseline.
- Add stale calibration status.

### Phase 3: Data Outputs

- Add float depth output mode.
- Add gradient/normal output modes.
- Add optional baseline output.
- Add save/load baseline.

### Phase 4: Optimization

- Avoid unnecessary CPU/GPU transfers where possible.
- Add SIMD to MLP if profiling says it matters.
- Consider GPU crop-resize.
- Consider GPU display normalization.

### Phase 5: Packaging

- Build for target TouchDesigner platforms.
- Document installation.
- Include license and notices.
- Provide example `.toe` network.

## 14. Licensing

The TouchDesigner plugin should use the same conservative license as the
browser project:

```text
GPL-3.0-or-later
```

The reason is the same: the reconstruction approach and model assets are
GelSight-derived, and the local GelSight Robotics reference code is GPLv3.

If a permissive or closed-source TouchDesigner plugin were desired later, the
project would need one of:

- explicit licensing permission from GelSight
- a permissively licensed replacement model
- a freshly trained clean model with clear redistribution rights
- no redistribution of GelSight-derived model weights

This is an engineering summary, not legal advice.
