# Verification — 2026-09-17

## Implemented and checked

`python -m pytest -q`: **30 passed**. One non-failing deprecation warning originates
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

- No live GelSight hardware, independent metric sensor calibration, learned skin
  model, Photoshop importer, slicer or physical print was tested. Slicing and physical
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

See `research-review.md` for algorithm differences and `studio.md` for setup,
configuration, CPU budgets, calibration entry points and export interpretation.
