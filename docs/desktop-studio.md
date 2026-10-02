# Native GelSight Matrix Studio

This is a separate Python Windows application using Qt Widgets and an OpenGL
viewport. It starts no web server and contains no HTML or embedded browser.
The existing browser Studio remains available separately.

## Open the window

Double-click **Start-Desktop-Studio.cmd** in the repository. Dependencies are
installed on the current computer. From PowerShell:

```powershell
cd "C:\Users\Jeffr\OneDrive\Documents\GitHub\gelsight-mini-browser-tool"
.\start-desktop.ps1
```

On a new computer, install Python 3.11 and run `.\start-desktop.ps1 -Setup` once.
Resume an existing collection with:

```powershell
.\start-desktop.ps1 -Project "C:\path\to\my-collection"
```

The default project is a new dated folder under `desktop-data/`. The **New / open
project folder** button also resumes a saved collection. A project lock prevents
two windows from writing the same collection. No captures are published.

## Configure and calibrate

1. Select the named GelSight Mini and delivered RGB resolution, then **Connect
   camera**. Other webcams are excluded. The default delivery is 640×480; 1280×960
   is also available with the DirectShow fallback. Higher delivery resolution
   preserves more RGB detail but does not increase the Mini network's depth grid.
2. Keep the gel completely untouched and press **Calibrate — gel must be
   untouched**. The application collects 50 distinct delivered frames, reconstructs
   each, and saves their mean RGB/depth baseline. It never infers a no-contact state.
3. Wait for **Untouched baseline saved** before touching the surface. Recalibrate
   after reconnecting, changing the camera resolution or gel, or opening a project.

**View configuration comparison** explains the relationship to the bundled Golan
code: identical Mini FP32 weights, B/G/R/y/x feature order, marker threshold 70,
gradient cap 50, DCT boundary/frequency recipe and lambda 0.0005. Numerical tests
compare marker fill and the DCT recipe with the unchanged JavaScript core.

Intentional differences: full 320×240 inference for each still; no temporal mixing
(p5 normally uses half-resolution inference and alpha 0.6); CPU bilinear resizing;
10% edge crop instead of upstream's 15% default. This is a configuration comparison,
not an endorsement by Golan Levin or a claim of pixel-identical browser output.
Baseline subtraction produces **relative relief**, not a metric sensor calibration.

On this host Qt lists no cameras, so the program falls back to native FFmpeg
DirectShow. The connected Mini advertises 3280×2464 MJPEG at 25 fps. FFmpeg opens
that advertised mode and resizes to the selected delivered RGB size. `source.png`
preserves that delivered frame, **not** the original high-resolution MJPEG packet.
The exact camera mode and backend are recorded. A 50-frame command-line stream and
11 frames in the native window were verified; no physical baseline was assumed.

If a stream fails, close any browser camera feed, check Windows Camera privacy
settings, reconnect USB, and refresh devices. FFmpeg must be on PATH for the
DirectShow fallback (`C:\FFmpeg\bin` on this computer). The launcher can also select
Qt's older native backend with `-CameraBackend windows`; DirectShow remains the
fallback if Qt cannot enumerate the sensor.

## Collect rows

**Capture cell →** freezes one camera frame and saves the whole bundle before
advancing the column. Move the sensor right with approximately 25% overlap between
the *cropped* fields. **Next row ↙** advances the row and resets the column to zero;
physically return to the left edge. This is left-aligned capture, not a zigzag scan.
Rows can have different lengths. Empty trailing rows are permitted; missing cells
are never mistaken for neighboring captures. Click any saved thumbnail to inspect it.

The crop removes `floor(0.1 × dimension)` pixels from each edge once, before
inference. The resulting field is resized to 320×240. All surface outputs correspond
to that cropped field; depth, normals, meshes and points are not cropped a second
time. Rounding for odd source dimensions is recorded in `capture.json`.

Each cell contains:

| Asset | Meaning |
|---|---|
| `source.png` | Immutable delivered RGB before the crop |
| `cropped-source.png` | Central crop at delivered RGB resolution |
| `rgb.png` | Cropped RGB on the 320×240 model grid |
| `depth.npy`, `depth.png` | Float relative depth and percentile-scaled display preview |
| `normals.npy`, `normal.png` | Float/OpenGL normals derived from the saved depth |
| `normal-directx.png` | Same normal map with its green channel flipped |
| `surface.ply` | Actual displaced, colored surface triangles |
| `points.ply` | Colored point cloud on the same vertices |
| `normal-material.glb` | Flat UV plane with RGB and normal textures for inspection |
| `interpolated-markers.png` | Pixels whose gradients were filled over sensor markers |
| `background-subtracted.png` | RGB with transparent pixels below a 12-code-unit RGB difference threshold |
| `capture.json` | Index, baseline reference, crop, configuration and asset SHA-256 hashes |

X points right, Y up and Z out. Capture mesh XY uses model pixels; Z preserves
relative solver values. The transparent background is a display mask, not a force
or physical contact measurement. Baseline reference frames and derived hashes live
in `calibrations/`. Earlier captures are never rewritten by a later calibration.

## Assemble a continuous surface

Set the expected overlap and press **Build continuous panorama**. Only existing
right and down neighbors are matched. SIFT features in normal-map images are
matched mutually, then gated by robust geometry, overlap, coverage, repetition,
duplicate and direction checks. The current matrix assembler accepts near-translation
motion; it rejects significant rotation or deformation. It is not general 3D SLAM.

Accepted matches influence a joint translation fit. Indexed grid positions remain
explicit priors for rejected/missing links. Relative depth offsets are leveled over
overlaps, then depth and RGB are feather blended. Missing parts of the rectangular
extent (including short-row gaps) use nearest observed values, with local smoothing
at joins. The complete panorama is an **artistic continuous assembly**, not a verified
physical reconstruction. Rejected matches remain visible in the report; a plausible
looking seam is not evidence that the surfaces physically align.

The normal panorama is recomputed from the fused float depth so its geometry agrees
with the surface mesh. It is not an independent integration of blended normal maps.
`observed-mask.png` marks source coverage; `synthetic-mask.png` marks overlap blends,
fills and their neighborhood. `assembly.json` freezes all sources/hashes, accepted
and rejected neighbors, translations, relative height offsets and row lengths.
Every assembly creates a new revision. The combined point cloud and regular-grid
mesh share the same rectangular field and have no interior holes.

Limits: 100 captures per collection, 600,000 output pixels per assembly. If the
panorama exceeds the memory budget, use a smaller collection or greater actual
capture overlap. The program does not silently downsample source depth to fit.
Cancellation is cooperative at stage boundaries; mesh export/reload can take a
short while to finish the current stage. Interrupted unindexed output folders may
remain for diagnosis, but are never presented as completed captures or assemblies.

## Inspect and print

The **Live GelSight** tab shows the current camera image before cropping and opens
automatically when connecting. It keeps updating independently while you capture
cells or select saved images. Switching tabs does not disconnect the camera.
The **Captured maps** tab displays saved RGB, depth, normals, background subtraction
and assembly masks. New live frames never replace the selected saved map. Disconnecting
clears the live image so an old frame cannot be mistaken for a live feed.
The **Native 3D viewport** has:

- **Relief mesh:** displaced geometry with RGB colors.
- **Point cloud:** the same surface represented as colored points.
- **Baked normal lighting (flat plane):** a diffuse lighting preview calculated
  from the saved normal map; the exported GLB holds the actual UV normal texture.

Drag to orbit and use the wheel to zoom. The preview is reduced to at most 160×160
for interaction; export geometry retains every saved depth sample. **Relief range**
sets an authored peak-to-valley depth in millimeters; **print width** determines XY
size with the original sample aspect ratio; **backing** determines the base thickness.
These dimensions do not retrospectively calibrate the sensor. The flat normal-map
preview uses the captured normals and therefore does not respond to the relief slider.

**Export full-resolution STL solid** creates a full-grid top surface, bottom and
outer walls, then verifies watertightness, winding, volume and STL reload. Files go
to a new `prints/<revision>/` beneath the selected capture/assembly. `validation.json`
records dimensions, source hash, scaling and digital topology checks. STL units are
millimeters. The dense source samples are preserved; increasing dimensions cannot
recover detail the model did not measure. Normal texture appearance alone is not
printable, so the manufacturing export uses actual displaced geometry.

The mesh is not labeled print-ready: printer feature limits, slicer settings and a
physical print still need validation. Missing-cell fills and synthetic seams remain
part of the authored solid. Inspect the masks and source maps before manufacture.

To rebuild the normal-textured GLB with the separate Python script:

```powershell
.\.venv-studio\Scripts\python.exe -m desktop_studio.bake "C:\path\to\collection\assemblies\REVISION"
```

The GLB is an inspection plane with authored 1 mm/model-pixel display scale (stored
in meters), not a metric scan. Full displaced meshes do not receive an extra normal
texture, which would double-count their relief.

## Verification

```powershell
.\.venv-studio\Scripts\python.exe -m pytest tests/test_desktop_studio.py -q
.\.venv-studio\Scripts\python.exe tools/verify-desktop.py
.\.venv-studio\Scripts\python.exe tools/verify-desktop.py --hardware
```

The first native smoke run uses labeled synthetic camera frames and exercises
baseline, three synchronized captures, ragged rows, panorama, all 3D modes and STL.
The optional hardware run opens the named Mini for preview only and releases it;
it neither records an assumed untouched baseline nor adds physical samples.
