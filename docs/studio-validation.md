# Verification — updated 2026-10-01

## Native matrix application — 2026-10-01

- Dedicated Live GelSight tab follow-up: native synthetic UI smoke passed again
  (`test-artifacts/native-4c1d47ac/smoke-report.json`). Checks confirm a fresh live
  frame updates the independent preview without changing the selected capture or
  its saved normal-map image; disconnect clears the preview. The existing baseline,
  ragged-row capture, panorama, 3D and STL flow still passed. Compilation and diff
  whitespace checks passed. This follow-up did not repeat hardware acquisition.

- Added a separate Qt Widgets/OpenGL Python application. No WebEngine, HTML,
  web server, cloud publication or edits to `gelsight_p5/` are part of this addition.
- Full numerical suite passed **63 tests** (one existing Starlette/AnyIO
  deprecation warning). A subsequent focused desktop run passed **5 tests**,
  including one newly added positive registration test. Tests exercise unchanged
  JavaScript marker-fill/DCT parity, crop geometry, the real Mini weight inference,
  normal orientation, PLY point/surface reload, normal-textured GLB, full-grid solid
  STL reload, ragged-row adjacency, missing-cell masks, rejected repetitive matches,
  accepted distinctive normal-map translation, source tamper rejection, calibration
  averaging, baseline/device compatibility, cancellation and revision persistence.
- Native Qt smoke test passed with explicitly synthetic camera frames: 50-frame
  baseline, three synchronized captures arranged `[2,1]`, 560×420 continuous
  panorama, native mesh/point/normal-lighting modes, and a 940,796-triangle closed
  STL with correct authored dimensions and successful reload. No GUI errors.
  Final workflow report: `test-artifacts/native-39f7c428/smoke-report.json`.
  Native window screenshots were visually inspected; scrolling, brighter lighting
  and a Fit Surface control were added after that inspection.
- Actual hardware preview was verified: Windows sees **GelSight Mini R0B
  65Y7-RDNB**, but Qt video enumeration returns empty on this host. FFmpeg DirectShow
  advertises only 3280×2464 MJPEG at 25 fps; requesting 640×480 input fails. Opening
  the advertised mode succeeded (50 frames in the command-line stream check).
  The native window then received **11 real frames**, delivered as 640×480 RGB,
  and released the device cleanly. Evidence:
  `test-artifacts/native-182785df/smoke-report.json` and `hardware-preview.png`.
  **No physical untouched baseline, real capture matrix, measured reconstruction
  accuracy, hardware stitching, slicer run or physical print is claimed.**
- Synthetic example generation passed again: tile maximum source error
  0.04991385 mm within 0.05 mm; coupon 0.05998882 mm within 0.06 mm; atlas one island
  with ten accepted links. Local synthetic publication preview remains a draft.
- Existing `tools/verify-studio.mjs` passed against an isolated owner server on
  port 8091: material geometry, STL/3MF reload, private specimen editing, static
  export, mobile layout and no page errors. Public entry count remained zero.
- Original `tools/verify_gelsight_p5.js` could not launch its expected Playwright
  headless-shell executable. Retrying with installed Chrome through an ignored
  test wrapper reached the original app but timed out waiting for startup state
  (`cv` and `session`, 30 seconds). No fresh standalone-p5 pass is claimed.
  Original p5 assets are unchanged. Diff whitespace checks passed.

Scientific/functional limits: Mini depth remains relative. The desktop port uses
the upstream DCT recipe but full-resolution inference and no temporal mixing;
CPU preprocessing is not asserted browser-pixel-identical. Matrix matching uses
normal-map features and near-translation gates. Unmatched regions use recorded
grid priors. Relative-height leveling, overlap blending and filling missing ragged
cells produce an explicitly artistic continuous surface; final normals derive from
that field. Source/coverage/synthetic masks and failed-match reports remain available.
The normal-material GLB is a separate flat inspection plane. Print geometry uses
actual height samples, authored mm scale and a closed backing, with physical
manufacturing readiness explicitly unverified.

## Video Capture — 2026-09-29

- Full numerical regression suite: **59 passed**, with one existing non-failing
  Starlette/AnyIO deprecation warning. JavaScript syntax and diff whitespace checks passed.
- Numerical coverage adds a real FFmpeg lossless video fixture. Checks cover
  extraction intervals and timestamps, frame limits, immutable video hashes,
  aligned central-80% RGB/depth/normal/mesh fields, OBJ Z reload and winding,
  invalid-mask holes, separate extraction revisions, baseline rejection and
  decoder failures recorded as failed runs. The synthetic example generator
  passed again with the existing tile/coupon fidelity bounds and atlas checks.
- `node tools/verify-video-capture.mjs` passed with Chrome's explicitly synthetic
  file-backed camera: Start/Stop MediaRecorder, video review, stream release on
  navigation, retained stopped video, FFmpeg extraction of frames 0 and 5, linked
  RGB/depth/normal/OBJ delivery, saved-video access, reload, mobile layout and
  cancellation. No page errors. Screenshot and JSON report are in the ignored
  `test-artifacts/video-capture*` files. This is not a hardware-camera test.
- Early harness runs exposed unreliable detached-canvas recording and premature
  reads of older results. The harness now generates a file-backed camera fixture,
  waits for actual MediaRecorder data and the exact new collection. Recording
  duration uses monotonic time; empty recordings produce an actionable message.
- FFmpeg is installed here at `C:\FFmpeg\bin\ffmpeg.exe` (7.1 essentials build).
  Each run freezes its tool version, source hash, frame indices, presentation times
  and limits. Failed/rejected frames never acquire fabricated depth. Offline
  reconstruction remains relative and is distinct from the live p5 solver.
- The original `gelsight_p5/` files remain unchanged. No new physical calibration,
  manufacturing or public dictionary deployment is claimed.

## Complete per-capture assets — 2026-09-29

- All **57 numerical tests passed**. Capture checks now reload the actual OBJ
  (76,800 vertices / 152,482 triangles), compare its Z values with saved float
  depth, verify upward triangle winding, compare float normals with depth
  gradients, check PNG quantization/green inversion, and verify sample asset links.
  Coordinated sheet tests now cover per-capture normals as well as RGB/depth/mesh.
- The synthetic example generator completed successfully again. No new hardware
  capture or physical calibration is claimed; tests use labeled synthetic inputs.
- Per-capture meshes preserve solver Z and use model-pixel XY spacing. They are
  open surfaces, not manufacturing solids. Existing samples are not migrated.
- The expanded p5/typology/unfolding browser smoke passed with no page errors:
  complete capture asset metadata, RGB/depth/normal/OBJ links, authenticated
  nonempty asset responses, download events, saved-board sample links and eight
  coordinated sheets. Existing assembly/unfolding views and mobile checks passed.
  One initial run stalled awaiting Chrome download completion; the harness now
  checks response bytes and UI download events, then cancels the test download.
  That verifies delivery and wiring, not completion of Chrome's local save step.
- JavaScript syntax checks and `git diff --check` passed. The unchanged standalone
  p5 regression was attempted but stopped after it stalled without a result;
  no fresh standalone-regression pass is claimed for this update. The complete
  embedded p5 capture browser workflow above passed. Prior standalone evidence
  below remains dated to its earlier run.


## Implemented and checked

`python -m pytest -q`: **59 passed**. One non-failing deprecation warning originates
from Starlette's use of an AnyIO alias. Checks cover:

- Flat/ramp normal orientation, DirectX sign, physical spacing, masked integration
  and independent height anchors; float-to-16-bit scale/bias precision.
- Calibration gates, missing weights, finite Mini model output, contact loss and
  marker exclusion; source-preserving seamless edits and metric wrinkle exclusion.
- Known overlapping crops within 1 pixel, unrelated/repetitive-pair rejection and
  global loop constraints reducing controlled drift.
- Narrow-valley solids, masked holes/walls, welded sphere seams/poles, intersecting
  solids failing validation, explicit mesh units, open mesh projection to closed solid,
  rounded exterior borders, shared-vertex intersection detection, and paired depth
  ratio preservation.
- Real STL/3MF round trips, finite geometry/manifoldness/orientation, material GLB
  meter units with baked relief, and selected export contents.
- Monotonic pressure, constant/masked/inverted fields, reproducible artistic layers
  without source changes, read-only live ink previews, private API protection,
  frozen public revisions, stable slugs, update/unpublish/republish and exhibition
  allowlists. Cancellation terminates an actual worker process.

`npm run test:browser`: **passed** using installed Chrome and software WebGL.
The test generates a material, draws/replays/downloads a PNG, confirms actual
displacement changes geometry (bounding radius 1.0000 → 1.1599; 9,024 triangles),
builds/validates a print, builds an atlas, creates/edits a draft, generates an ink
variant, prepares a private entry preview, reloads its direct address, changes/resets
ink, and lazy-loads Surface 3D. It checks a 390 px mobile layout without horizontal
overflow. **Zero browser page errors; zero published specimens.** Screenshots and
machine-readable results are in ignored `test-artifacts/`.

The original `tools/verify_gelsight_p5.js` also **passed**, using an installed-Chrome
launcher adapter without changing the original test or viewer. It exercised the
bundled coin demo, WASM reconstruction (76,800 finite samples), camera-gated controls,
orbit/pan, and ZIP export including the 152,482-triangle OBJ and original metadata.
The coin is real provided tactile imagery, not a newly acquired hardware capture.

Node syntax checks and `git diff --check` passed. The installed npm dependency audit
reported zero vulnerabilities after using Playwright 1.55.1.

`node tools/verify-static-exports.mjs`: **passed**. A separate temporary static
server rendered the exported material sphere without the processing service,
served the empty public collection under a subdirectory, and refreshed direct
About/Compare routes with zero page errors. The test server shut down afterward.

`node tools/verify-dictionary-flow.mjs`: **passed**. Browser file upload imported
a float height field as relative data, created a draft, exercised the live pressure
preview, saved an impression, filtered by tag/category, switched static sphere
thumbnails, compared two specimens with shared ink/scale/lighting, and downloaded
an explicitly enabled PNG. Zero page errors and zero public entries. Forms remain
inert until handlers are ready, preventing premature native submissions at startup.

## Gyotaku print continuation

The print workbench adds four palette/presentation starting points, restores all
saved recipe fields, exports three-pressure proof sheets, and exposes coverage,
source-space layers and recipe downloads to the owner. The 13 added checks cover
complete deterministic replay, retained engine-1 pixels, preview/master agreement
at the same raster size, consistent PNG DPI/alpha, anisotropic metric dimensions,
90°/45° rotated magnification, calibrated rulers, degenerate crops, read-only
proofs, private endpoints, effect removal and missing-data/inversion handling.

`node tools/verify-ink-workbench.mjs`: **passed** in installed Chrome. Checked
palette selection, edited recipe save/restore, downloadable proof, no extra variant
from proof generation, cancellation before switching back to source, style-specific
controls, and 390 px layout without overflow. Zero page errors and zero published
specimens. The complete Studio browser smoke test also passed after these changes.

Three actual local coin studies were generated at 2400 pixels wide in soot,
indigo and iron oxide palettes, with pressure proofs and complete recipes. They
use the existing relative relief from the provided capture. Visual inspection
confirmed distinct progressive contact, source detail and legible proof labels.
The public site was not changed or redeployed during this continuation.

## Live Mini and ShuffleSnap — 2026-09-24

Windows detected **GelSight Mini R0B 65Y7-RDNB** with device status OK. An
unrestricted installed-Chrome check opened that specifically named camera and
read an actual **640×480** frame, saved privately for inspection. A restricted
browser reported system permission denial; native Python/OpenCV enumerated the
Mini but did not open it. The supported launcher therefore uses browser capture.
`studio-data/logs/browser-status.json` confirmed the visible dedicated Chrome
window was on Live Typology with the named Mini live at 640×480. No hardware
baseline, known-depth calibration or physical surface classification was inferred.

The six new numerical/API tests exercise the installed native ShuffleSnap 0.3.0
solver, deterministic distinct-cell assignments, degenerate PCA inputs, immutable
raw source hashes, private selected-only ZIP export, safe text, sensor-specific
capture sessions, explicit baseline handling and protected endpoints. The full
suite passed: **49 tests**, with the existing non-failing AnyIO deprecation warning.

`node tools/verify-typology.mjs`: **passed**. Imported seven explicitly synthetic
image fixtures, verified default exclusion/session filters, built the actual
ShuffleSnap grid, inspected source images, downloaded the numbered PNG and private
ZIP, reloaded the standalone board and checked 390 px layout. **Zero page errors;
zero published entries.** A repeated test now waits for a unique newly generated
board instead of matching a previous board with the same title.

The complete Studio browser smoke test, original p5 viewer regression, synthetic
example generator, JavaScript syntax checks and `git diff --check` also passed.
The launcher was executed successfully and opens a separate Chrome profile without
changing the everyday browser profile. See `mini-typology.md` for the user workflow,
descriptor limitations, hardware troubleshooting and private export contents.

## Reproducible example artifacts

Run `studio examples --data test-artifacts/example-data --output examples/generated`.
The checked example set is in `examples/generated/` (ignored generated outputs):

| Example | Geometry / result |
| --- | --- |
| Relief tile | 40 × 40 × 2.793956 mm; 6,392 triangles; maximum processing error 0.049914 mm ≤ 0.05 mm; p95 0.018596 mm; p99 0.031817 mm. |
| Paired comparison coupon | 97 × 84.300000 × 3.593383 mm; 21,744 triangles; maximum per-variant processing error 0.059989 mm ≤ 0.06 mm; shared scaling retains the analytic 0.55 depth ratio. Coupon percentiles summarize per-variant maximum errors, not a pooled surface distribution. |
| Texture and standalone gallery ZIPs | Float/16-bit maps, masks, brush images, material geometry, local Three.js dependencies; no unselected capture uploads. |
| Analytic image sequence | One connected atlas; ten accepted verified links. Appearance-only until frame relief is reconstructed. |

Both manufacturing examples are closed, consistently oriented, single-component,
positive-volume, vertex-manifold solids, with construction lower bounds on base
thickness. Both STL and 3MF reloads passed. The browser-generated 50 mm tile had
maximum vertex round-trip errors of 0.00000256 mm (STL) and 0.00000556 mm (3MF).

## Privacy and publication

The owner explicitly requested an empty public dictionary. `texture-dictionary/dist/`
contains **zero entries**, no asset/capture folder, and no unpublished specimen records.
Only the frontend, shared viewer/dependencies, empty manifest, About and Compare
pages are included. Sample captures and synthetic specimens remain local drafts.
Sites confirmed successful public deployment on 2026-09-17:
[Texture Dictionary](https://texture-dictionary-gelsight-studio.jeffrey-yiji-wang.chatgpt.site).
The deployed collection is empty, as requested. This confirmation comes from the
hosting service's terminal success response; the local build was tested separately.

## Practical limits

- Live GelSight Mini video was verified in Chrome on 2026-09-24. No independent
  metric sensor calibration, learned skin model, Photoshop importer, slicer or
  physical print was tested. Slicing and physical
  fabrication remain explicitly unverified. No universal printer profile or G-code
  is supplied.
- The atlas is a bounded planar mosaic, not a full GelSLAM reproduction. Artistic
  nonrigid warps/fills and pressure/posture changes are not valid quantitative skin
  comparisons. Viewer quality caps and shader maps do not invent sensor resolution.
- Mesh error tests sample source/interior points; they are processing checks rather
  than a formal continuous bound or a measurement of sensor truth. Large arbitrary
  imports may need cropping, an increased budget or independent repair. Their minimum
  wall thickness is unresolved unless the construction supplies a verified bound.
- Border rounding affects corners in plan, not a fillet across the measured top.
  Unsupported WebGL uses a static fallback. Live camera availability depends on the
  connected device and browser permissions.

## p5 bundles, stitched typologies and texture unfolding — 2026-09-24

- Full numerical suite: **56 passed**, including seven new tests for exact central
  80% crop and immutable originals; synchronized views; stale-baseline rejection;
  repeatable segmentation and region provenance; missing-depth behavior; RGB
  transparency without double depth subtraction; and immutable layout upgrades.
- Actual OBJ reload verifies triangle counts and finite vertices. Default quilts
  preserve separate source components. Optional artistic bridges reduce component
  count without changing source vertices; source and synthetic masks do not overlap.
- `tools/verify-p5-unfold.mjs` passed with installed Chrome and software WebGL on
  the isolated port-8091 test store. It checks all four resolution options, two
  captured demo bundles, coordinated named/image-only sheets, actual mesh/depth
  views, the artistic connection toggle, region/flat/sphere views, private export,
  saved reload and mobile overflow. No browser page errors were reported.
- `tools/verify-p5-background.mjs` passed: 50 synthetic processing frames produce
  an averaged RGB reference; a synthetic canvas video supplies synchronized model
  RGB and background blobs. It opens no hardware camera and saves no live specimen.
- Browser screenshots: `test-artifacts/p5-studio.png`, `p5-typology.png`,
  `typology-stitched-mesh.png`, `unfold-flat.png`, `unfold-ball.png`, and
  `unfold-regions.png`. Reports are `p5-unfold-report.json` and
  `p5-background-report.json` in that same ignored directory.
- The synthetic example generator passed again: tile maximum source error
  0.04991385 mm within 0.05 mm; paired coupon 0.05998882 mm within 0.06 mm;
  one atlas island with ten accepted links. Physical printing remains untested.
- Initial combined validation and repeated server runs exposed Windows allocation
  failures. Heavy suites were rerun sequentially; the owner CLI/server now uses
  the same two-thread BLAS/OpenMP defaults as workers, reducing the observed
  server private allocation from roughly 1.3 GB to 142 MB in the browser run.
  Allocation failures return an actionable owner error. No unrelated apps were closed.
- The original p5 source tree remains unmodified. Integration is a same-origin
  wrapper. New hardware resolution modes and physical calibration were not tested;
  prior 640×480 Mini verification is separate from these synthetic checks.
- The unchanged original p5 regression passed again: 76,800 finite depth values,
  152,482 OBJ triangles, baseline recovery and ZIP metadata/encoding checks.
  The broader existing Studio smoke reached valid STL/3MF round trips and atlas
  construction, but its ink job was blocked by Windows: `DLL load failed while
  importing cv2: The paging file is too small for this operation to complete.`
  This run is not claimed as a complete legacy workflow pass. The new p5/typology/
  unfolding browser suite and numerical suite passed separately as recorded above.
- Unfolding is an appearance-based proposed composition, not recovered object
  topology. Sphere wrapping has seam/pole distortion. Combined typology mesh units
  are authored display coordinates; float arrays and masks retain their described
  source/display encoding. Artistic seams cannot support physical measurements.
- All QA data stayed in the isolated test store. No specimen was publicly approved
  or deployed, and the user's public collection remains empty.

## Typology normal maps — 2026-09-24

- Full numerical suite: **57 passed**. The focused capture/typology/unfolding file
  has eight passing tests. An analytic ramp verifies XY spacing and Y-up normals,
  one-sided boundaries, holes, isolated-pixel exclusion and separation across a
  100-unit source-cell discontinuity. Export checks verify unit lengths, PNG
  quantization, exact valid-pixel green inversion, neutral missing pixels, masks,
  synthetic influence, standalone links and immutable board revisions.
- The synthetic example generator passed again with the previously recorded tile,
  coupon and atlas results. No physical or hardware validation was added.
- `tools/verify-p5-unfold.mjs` passed with no page errors: both normal conventions,
  separate/connected preview switching, all four normal PNG downloads, return to
  depth mode, capture bundles, six sheets, 3D assembly and unfolding still work.
  The normal preview was visually checked in `test-artifacts/typology-normal-map.png`.
  Its first run selected an older sample twice because it assumed the last
  timestamp-sorted record was the new capture; the harness now uses response IDs.
- Original p5 regression passed again: 76,800 finite depth samples, 152,482 OBJ
  triangles, baseline recovery and ZIP encoding/metadata. Its source tree has no
  changes. JavaScript syntax checks and `git diff --check` also passed.
- Normal PNGs use the assembly display scale and retain their normal-validity mask.
  Connected maps describe the interpolated raster; no exact OBJ-face equivalence
  or metric accuracy is claimed. Float exports retain OpenGL normals and masks.

See `research-review.md` for algorithm differences and `studio.md` for setup,
configuration, CPU budgets, calibration entry points and export interpretation.
