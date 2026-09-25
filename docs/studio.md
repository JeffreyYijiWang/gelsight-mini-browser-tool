# GelSight Material Studio

Material Studio adds a local owner workspace to the original GelSight Mini viewer.
Its modes are Surface Capture, Tactile Atlas, Brush & Material Lab, Print
Studio, Material Gallery, Texture Dictionary, Live Typology and p5 Live Capture,
plus the separate Texture Unfolding program. The [README mode guide](../README.md)
explains controls, resolutions, background subtraction and coordinated 3D/depth/normal
typology exports. The original camera viewer is
preserved under `/gelsight_p5/` and linked from the sidebar.

## Start on Windows

Python 3.11 and Node.js 20+ are required. From the repository root:

```powershell
py -3.11 -m venv .venv-studio
.\.venv-studio\Scripts\python.exe -m pip install -r requirements-studio.txt
npm ci
npm run setup:web
.\.venv-studio\Scripts\python.exe -m studio serve --port 8090
```

Open http://127.0.0.1:8090. On systems with a managed certificate authority,
configure Python/Node to trust the system certificate store; never disable TLS
verification. The preview currently runs on that address. `start-studio.ps1`
restarts it after closing the current server. On Linux/macOS use `python3 -m venv`
and `.venv-studio/bin/python` instead of the Windows executable.

All storage is in ignored `studio-data/`. Back up that directory to retain original
uploads, source hashes, versions, calibration records, specimens and settings.
`--data PATH` selects a separate store. Do not serve that folder with a generic
HTTP server or publish the whole repository. The owner service binds only to
loopback. Its per-run token, same-site cookie, mutation token and origin checks
protect private APIs; it is not a remotely accessible multi-user admin server.

## First complete workflow

1. Load the synthetic sample project, or import a capture. Synthetic examples are
   explicitly labeled; they are analytic surfaces, not measurements of human skin.
2. In Capture, import RGB sequences, a folder, video, a GelSight export ZIP,
   height/normal map, or an STL/OBJ/PLY/GLB mesh. Live UVC acquisition uses the
   browser camera adapter when hardware and browser permission are available.
3. Select a baseline and reconstruction profile for tactile RGB. The bundled Mini
   network yields **relative relief**. RGB brightness is never a height import.
   The separate “Collect RGB as art” action creates an explicitly image-based
   artistic specimen without claiming source geometry.
4. Inspect masks/normals/height, set an ROI, and analyze a cross-section. Metric
   wrinkle summaries require a validated original patch; edits and invented pixels
   are excluded. Capture conditions store only supplied force/posture information.
5. Build an atlas from overlapping frames, inspecting links, footprints, independent
   islands and optional artistic warp. Reconstruct frames first for height fusion;
   appearance-only atlases have no invented height. Open an island in Material Lab
   to crop it as a separate derived patch.
6. Generate maps and brushes in Material Lab. Original data stays separate from
   seamless conversion, gap fills, inversion and gain. Inspect sphere/flat views,
   compare actual displacement with bump/normal shading, and draw/replay strokes.
7. In Print Studio, choose a source, scale, substrate and error budget. Inspect actual
   mesh geometry, cross-section, dimensions and validation before downloading a
   package. A printer profile uses your documented/tested process limits.
8. Collect the surface in Texture Dictionary, write a title/story, move virtual
   pressure, and save impression variants. Link existing materials/prints, choose
   public views/downloads, then preview the exact entry. Approval freezes a revision
   for a future website build; a separate deployment updates the hosted website.

**Publication decision:** the owner requested an empty public collection on
2026-09-17. All bundled coin and synthetic specimens remain local drafts.
The [public Texture Dictionary](https://texture-dictionary-gelsight-studio.jeffrey-yiji-wang.chatgpt.site)
is deployed with zero specimens.

## Developing gyotaku-inspired prints

For live Mini acquisition and ShuffleSnap comparison boards, see
[Mini capture and typologies](mini-typology.md). Double-click
`Start-Material-Studio.cmd` to open the dedicated local camera window.

In Texture Dictionary, select a specimen and use **Develop your impression**.
Choose soot ink, indigo, iron oxide, or a clean specimen starting point. Move
virtual printing pressure to bring lower parts of the recorded relief into the
impression. **Make pressure proof** compares 0.25, 0.55 and 0.85 with the same
source, crop, palette and seed; its PNG download saves no variants and publishes
nothing. Relief-shaded presentation has no pressure proof because lighting, rather
than contact coverage, produces that view.

**Restore a saved recipe** restores every control, including palette, crop,
rotation, page size, seed and engine version, without changing the specimen cover.
**Save new impression variant** records the working recipe and selects the new
variant as the local cover. Changing the local cover does not update an approved
public snapshot. Source and saved-image buttons cancel pending live previews.
Original RGB comparison is available when the patch explicitly links an RGB frame.

Engine 2 computes coverage and artistic effects on the cropped source grid, then
uses that same result for preview and export. The preview caps its display at
640 pixels; downsampling can hide fine grain. Source grids are never upsampled to
invent detail. RGB-only artistic inputs are capped at 2048 pixels per side in both
paths. Clean presentation removes dry brush, spread, edge blur and paper grain;
switch back to ink to use their retained settings. Inversion also changes relief
lighting. Missing samples stay outside the ink mask.

All new recipes store explicit defaults and `engine_version: 2`. Earlier records
without a version restore through engine 1, which retains the original rendering
and layout behavior. Select a palette to move an old recipe to engine 2. To replay
an old settings object through the CLI, explicitly include `engine_version: 1`.

Master PNG, transparent contact ink and grayscale coverage exports have matching
page dimensions and DPI. The transparent export contains pigment/contact coverage,
not relief shading, paper or a scale bar. `artistic_layers.npz` contains base and
final coverage, dry brush, paper grain and valid mask in cropped source coordinates,
before rotation/page layout. `variant.json` is the full recipe; `process.json`
records crop sample bounds and layout. These owner downloads remain private.

Calibrated layouts preserve anisotropic X/Y spacing and account for rotation when
reporting reproduction magnification. Source dimensions span the sample centers.
The millimeter page size is an authored print size and remains separate from source
calibration. Relative sources have no measured magnification or physical scale bar.
Master pages are limited to 6000 pixels wide, 8000 high and 32 megapixels; owner
preview/proof computation allows two concurrent renders.

Local examples are at `examples/generated/gyotaku/index.html`: three 2400-pixel
coin impressions, pressure proofs, transparent ink, coverage, layers and recipes.
The provided coin has relative scale, so its 180 mm page is an authored size.
Regenerate from an existing specimen (matching recipes are reused):

```powershell
.\.venv-studio\Scripts\python.exe tools/develop-gyotaku.py --specimen SPECIMEN_ID --data studio-data
node tools/verify-ink-workbench.mjs
```

To open a particular local specimen, use
`http://127.0.0.1:8090/?specimen=SPECIMEN_ID#dictionary`.

## Inputs, units and scientific scope

Height imports support float NPY/NPZ (`height`, optional `mask`), grayscale PNG or
TIFF. For integer maps, provide `scale_per_code` and `bias`. Metric import also
requires `units: "mm"`, positive `[x,y]` pixel spacing in mm and validation notes.
Missing scale stays relative. Normal maps support OpenGL and DirectX conventions;
normal integration is explicitly estimated unless metric calibration is supplied.
Mesh transforms are applied; assign STL units explicitly. Mesh projection fits a
local plane or uses supplied Euler orientation and normalized crop. It rejects
overhangs/multiple heights; arbitrary geometry uses the mesh-preserving branch.

Array rows run down, surface Y runs up, and positive Z is object relief outward.
Connected regions in normal integration each have an arbitrary mean-zero anchor.
Force and posture affect the imprint. Nothing reconstructs unloaded skin, infers
hydration/health, or inherits a research paper's accuracy. Quality is an engineering
score, not a calibrated probability. See [research-review.md](research-review.md).

## Exports

Texture packs include float height, 16-bit PNG/TIFF encoding metadata, masks,
coarse displacement, fine/full normal maps, bump, authored/estimated roughness,
wrinkle mask, brush tip, seamless grain, previews and checksummed manifest. Data
maps are linear; authored color is sRGB. Split-frequency mode uses coarse geometry
plus fine normals. An explicit artistic override allows full relief in all channels.

Photoshop: open `brush_tip.png`, select it, then **Edit → Define Brush Preset**.
Black means full paint. Define `brush_grain.png` as a Pattern and choose it under
Brush Settings → Texture. Native ABR is not produced. Actual Photoshop importer
testing has not been performed.

GLB bakes full relief into vertices and uses meters; its normal map is omitted to
avoid counting baked relief twice. The 25 mm sphere and 1 mm relief range are authored
display dimensions. OBJ uses mm. A flat patch displayed on a sphere is a material
presentation, not an anatomical reconstruction.

Print packages include STL and real lib3mf-written 3MF only after geometry passes,
editing PLY/OBJ/GLB, source/scaling/repair records, filter error map, cross-section,
overview, validation and export-reload results. STL/3MF use mm; GLB uses meters.
Adaptive meshing tests original samples and seven interior locations per triangle.
Error is processing fidelity against the scaled digital source, not sensor accuracy.
Rounded borders mean rounded exterior corners in plan; the scanned top is intact.
Large imported meshes retain geometry by default; error-verified simplification is
bounded to 12,000 source faces. A failed project and its editing files remain local.
Use slicer supports away from the featured surface. No G-code is generated.

Standalone gallery ZIPs contain selected derived materials and local JS dependencies.
Dictionary exhibition ZIPs contain only selected published snapshots, approved
images/downloads, captions/credits and a self-contained site. Publicly displayed
images remain saveable even if high-resolution download links are disabled.

## CLI, configuration and schemas

```powershell
.\.venv-studio\Scripts\python.exe -m studio demo
.\.venv-studio\Scripts\python.exe -m studio import --input captures --kind rgb
.\.venv-studio\Scripts\python.exe -m studio import --input surface.npy --kind height --config examples/height-import.json
.\.venv-studio\Scripts\python.exe -m studio run --kind material --config examples/material-job.json
.\.venv-studio\Scripts\python.exe -m studio build-dictionary --output texture-dictionary/dist
.\.venv-studio\Scripts\python.exe -m studio examples --data test-artifacts/example-data --output examples/generated
.\.venv-studio\Scripts\python.exe -m pytest -q
npm run test:browser
node tools/verify-static-exports.mjs
node tools/verify-dictionary-flow.mjs
```

Replace the example source ID with an actual imported patch ID. Every processing
job can be invoked with `studio run --kind KIND --config FILE.json`; configuration
is the same `params` object accepted by `POST /api/jobs`. Available kinds and argument
dispatch are in `studio/jobs.py`. Web jobs run in cancellable subprocesses: two jobs
at once, 2 GiB observed working memory per job, and 30 minutes per job. Uploads are
limited to 128 MiB each; patch storage to four million samples; print processing to
500,000 height samples; atlas input to 60 frames and output to four million pixels.
The synchronous CLI assumes a trusted local operator and does not add a subprocess
watchdog. Progress and failures are recorded; cancellation terminates computation.

Persisted Pydantic records are in `studio/records.py`; generated JSON Schemas are in
`docs/records.schema.json`. Store layout is documented by `studio/store.py`. The
owner API uses JSON for records/jobs and multipart files for `/api/import`.

## Calibration and training

There are three normal predictors: the bundled Mini MLP, an independently trained
polynomial calibration, and optional trusted TorchScript. Mini input is precisely
B,G,R,y/height,x/width. Models must match sensor ID, gel ID and source dimensions.
A configured model failing to load causes an error, never a silent fallback.

`studio train-calibration --input calibration.npz --output model.npz` trains a CPU
ridge model and reports held-out **frame** normal errors. The NPZ needs `rgb` and
`normals` arrays N×H×W×3, `mask` N×H×W, and `baseline` H×W×3 or N×H×W×3; at least
three distinct frames are required. Normals use surface Y up and +Z out. Train on
independently known geometry, then independently validate reconstructed dimensions,
height polarity and error for the exact sensor, gel, spacing and capture conditions.
The training report deliberately remains `validated: false`.

The optional PyTorch adapter accepts trusted TorchScript with input N×8×H×W
(RGB, baseline RGB, x, y in [0,1]) and output N×3×H×W normals. Install PyTorch only
if using that adapter. No pretrained skin-paper model or training data is bundled.

## Texture Dictionary hosting

The separate site project is `texture-dictionary/`. See its README for build,
branding, allowlists, revision lifecycle and Sites deployment. Owner APIs, raw
images, source identifiers and capture-condition metadata are never copied into
that build automatically. Deleting/unpublishing locally requires rebuilding and
deploying to remove an entry from an already hosted site.

See [studio-validation.md](studio-validation.md) for observed test results and
[licenses.md](licenses.md) for dependencies and redistribution notes.
