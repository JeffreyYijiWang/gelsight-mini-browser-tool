# Codex implementation prompt: GelSight Material Studio

Build this application end to end in the current repository. Inspect the repository and AGENTS.md first, preserve existing functionality, and reuse its stack and GelSight acquisition/calibration code where available. Do not stop at an architecture proposal or a UI mockup. Implement runnable processing, previews, exports, documentation, and meaningful validation. Make reasonable reversible decisions autonomously. If hardware, calibration, model weights, or hosting credentials are unavailable, complete everything that can run with imported data and clearly labeled synthetic fixtures; identify only the remaining dependencies.

## Product goal

Create a tool that turns GelSight tactile captures into reusable digital art assets and interactive material spheres for an online gallery. I want to capture fine wrinkles and grain from different skin regions, stitch overlapping tactile observations into a larger flat texture, and produce Photoshop brushes and PBR texture packs.

Provide four workspace modes plus a shared material-sphere viewer:

1. Skin / Surface Capture: reconstruct local relief and inspect wrinkle structure.
2. Tactile Atlas: stitch overlapping tactile images into a planar texture atlas.
3. Brush & Material Lab: derive, edit, preview, and export brushes and maps.
4. Print Studio: convert reconstructed meshes or height fields into detailed, watertight raised-relief models for 3D printing.
5. Shared Material Gallery: compare and display resulting textures on spheres online.

The spheres display sampled surface texture, not anatomical models. Include editable region labels: ankle, finger, fingertip, palm, nipple/areola, inner elbow, outer elbow, wrist, and custom. These are organizational labels, not claims that every region was evaluated by a paper. Default to neutral gray materials so relief is easy to compare. Allow artist-selected colors.

## Research and evidence boundaries

Read the methods and check official code, availability, and licenses before implementation or reuse:

- Padmanabha et al., In-Vivo Skin 3-D Surface Reconstruction and Wrinkle Depth Estimation using Handheld High Resolution Tactile Sensing (2025): https://arxiv.org/abs/2509.11385 ; methods: https://arxiv.org/html/2509.11385v1
- Huang et al., GelSLAM: A Real-time, High-Fidelity, and Robust 3D Tactile SLAM System (2025): https://arxiv.org/abs/2508.15990 ; https://github.com/rpl-cmu/gelslam
- GelSight robotics SDK: https://github.com/gelsightinc/gsrobotics
- Microfacet roughness background: https://www.pbr-book.org/4ed/Reflection_Models/Roughness_Using_Microfacet_Theory
- Photoshop image-to-brush workflow: https://helpx.adobe.com/photoshop/desktop/apply-painting-techniques/brushes-presets/create-brush-tip-image.html

The skin paper uses a custom soft gel and force-controlled capture, a CNN predicting normals, Poisson height integration, and detrending. Its wrinkle analysis detects valleys in angled profiles, skeletonizes candidates, and estimates depths using nearby peaks, reporting a percentile summary. Use it as a reference, document deviations, and do not inherit its reported accuracy without independent validation. Do not invent released weights or training data.

GelSLAM estimates object pose and reconstructs geometry using tactile observations, normals, curvature, and loop closure. Our atlas mode borrows registration ideas but is a 2D/2.5D mosaic, not a claimed reproduction of full 3D GelSLAM.

Treat the following as engineering requirements for this application, not claims that the papers already implement this product.

## Architecture and input contract

Reuse the existing stack. If starting empty, use a Python processing service with NumPy, OpenCV, SciPy, and optional PyTorch, and a React/TypeScript frontend with Three.js for visualization. Keep processing callable without the UI through a CLI or API. Heavy reconstruction and stitching must run as cancellable jobs with progress and useful error messages. GPU acceleration is optional; basic import, stitching, and export must work on CPU.

Accept image folders, ordered image sequences, video, existing height/normal maps, and a live camera adapter when supported. A sequence is needed for stitching; one image can produce one local patch only. Keep raw inputs immutable.

Define explicit records for CaptureSession, Frame, CalibrationProfile, SurfacePatch, Atlas, MaterialAsset, and ExportManifest. Store source IDs, timestamps/order, sensor and gel IDs, pixel dimensions, pixel spacing if known, processing settings, masks, confidence, transforms, and provenance. Record capture force and pose notes only when supplied; image-only input must not silently invent them.

Two explicit reconstruction states:

- Calibrated: use a compatible sensor-specific model/calibration and known scale; expose dimensions and heights in physical units where validated.
- Uncalibrated: allow appearance mosaics and a clearly labeled artistic relative-relief preview. Do not report micrometers, quantitative wrinkle depths, or metric displacement. Offer height-map import as an alternative.

Do not equate tactile RGB brightness with height. Handle background subtraction, camera distortion, contact segmentation, borders, saturated pixels, gel marker masks, and bad-frame rejection. The sensor's stationary markers and illumination are not object features. Distinguish absent calibration from a calibrated model failing to load. A failed load must surface an error, not silently downgrade scientific output.

## Mode 1: Skin / Surface Capture

Build import/capture, session labeling, ROI selection, baseline selection, frame-quality inspection, and a reconstruction action. Provide synchronized panels for tactile RGB, valid contact, normals, height, wrinkle overlay, and a rotatable relief patch.

Implement a pluggable reconstruction interface. Use compatible existing calibration first. Add an adapter for learned normal prediction and a documented calibration/training entry point if weights must be trained. Preserve masks through normal-to-gradient conversion and Poisson integration. Anchor the arbitrary height offset and record the convention. Keep original reconstruction, detrended relief, and artist-edited output as separate versions.

Provide adjustable detrending scale, smoothing, valley sensitivity, physical neighborhood radius when calibrated, and a region-of-interest selector. Implement wrinkle detection and depth summaries with a documented relationship to the reference method. Show cross-section profiles and median/80th-percentile depth only when valid calibration exists. Estimate from valid observed regions; exclude masked pixels and synthetic fills. Label confidence as a quality score unless it is statistically calibrated.

Skin deformation changes with pressure and posture. Let users compare repeated captures and record posture/force metadata; do not claim to recover unloaded skin from an imprint. This is an art and surface-analysis application, not a diagnostic system.

## Mode 2: Tactile Atlas — image-only stitching

The runtime input is overlapping tactile images or video, plus optional sensor calibration. Do not require external RGB cameras, robot poses, IMU, depth cameras, or a pre-existing object mesh.

Build a robust baseline before advanced warping:

1. Choose sharp, stable keyframes with useful contact and sufficient overlap; reject duplicates and contact loss.
2. Construct matching descriptors from object texture and, when available, reconstructed gradients, normals, or curvature. Exclude sensor-fixed artifacts.
3. Estimate candidate correspondences with OpenCV features and/or dense alignment. Use robust outlier rejection and overlap, residual, and spatial-coverage checks.
4. Default to translation/rotation, with bounded affine correction where needed. Avoid unrestricted projective warps that absorb contact deformation while corrupting geometry.
5. Build a frame graph and optimize relative transforms globally. Add loop closures only after geometric verification. Show disconnected components as separate islands.
6. Offer bounded local deformation refinement for artistic mosaics, with a distortion visualization and a toggle back to the rigid baseline.
7. Fuse valid overlap with confidence and border weighting. Produce coverage, source-frame index, seam, and quality maps as well as the atlas.

Tactile illumination changes with slope and contact, so raw RGB stitching is only an appearance mode. Calibrated geometry is the preferred basis for relief fusion. Align heights by solving overlap offsets with an anchored reference; do not normalize each patch independently. Resample heights consistently, derive atlas-space normals from the fused height field, and handle transforms and coordinate conventions explicitly. Warp vectors correctly if directly transforming normal fields.

Provide live atlas preview, frame footprints, accepted/rejected links, overlap score, undo/exclude frame, manual correspondence correction, crop, and export. Repetitive grain, uniform surfaces, non-overlap, and changed pressure must fail visibly rather than create confident false joins. Do not join disconnected islands simply because they are near each other on screen. Manual layouts must be labeled manual.

Call this a planar tactile atlas. A curved surface generally cannot be flattened without distortion. Track where calibration remains meaningful; arbitrary nonrigid warps invalidate original metric distances unless a local metric is propagated. Quantitative measurements should remain on calibrated source patches by default.

## Mode 3: Brush & Material Lab

Accept a source patch or atlas. Provide non-destructive controls, before/after comparison, tiling preview, and distinct source-versus-edited views. Keep processing in floating point until export.

Implement these outputs:

| Asset | Required behavior |
| --- | --- |
| Height / displacement | Export float master data plus 16-bit PNG/TIFF where supported; preserve scale, bias, units, sign, valid mask, and pixel spacing in JSON. Uncalibrated data remains relative. |
| Normal map | Derive from height gradients using correct horizontal and vertical scales. Support tangent-space OpenGL and DirectX conventions, with an explicit green-channel flip. |
| Bump | Export a scalar relief map and shader-strength metadata. |
| Roughness | Provide constant roughness and an optional geometry-derived artistic estimate using local slope statistics at a chosen scale. Label the latter estimated, with tunable range and no claim of measured reflectance. |
| Brush tip | Grayscale opacity mask with inversion, levels, curve, threshold, edge falloff, rotation, and crop controls. Use black as full paint and white as no paint in Photoshop brush-tip export. |
| Brush grain | A separately generated seamless grayscale texture with tiling scale and contrast controls. |
| Wrinkle mask | Export detected or artist-edited valleys with clear provenance. |

Distinguish physical surface-height roughness from shader roughness. Height alone does not recover albedo, gloss, subsurface scattering, or a measured BRDF. Supply an editable dielectric PBR/BRDF model with authored parameters. Never label GelSight RGB as skin base color or claim a complete measured skin material.

Prevent double-counting the same relief through full-strength displacement, normal, and roughness. Provide frequency-band separation: coarse relief for displacement, finer resolved detail for normals, and explicitly estimated residual variation for roughness. Allow an artistic override with an understandable control.

Seamless conversion must preserve the original and produce a derived asset. Mark synthesized/inpainted pixels and exclude them from measurement. Fill gaps only as an explicit artistic operation. Preserve directional texture orientation rather than automatically rotating every sample.

Add a drawing canvas with pointer/stylus pressure, brush size, spacing, opacity, grain scale, and stroke replay. Implement an optional height-based pickup model: light pressure selects peaks and increasing pressure includes lower levels. Label it an artistic model. Support mouse input with a manual pressure slider.

Export PNG brush tips and grain plus Photoshop setup instructions. Do not rename a PNG to .abr. Add native ABR only if a compatible writer is available, licensed, and validated by an actual importer; otherwise the image import workflow is the supported deliverable.

## Mode 4: Print Studio — scan / mesh to high-fidelity raised 3D print

Implement a real geometry-processing pipeline, not just an STL download button. I want to hold enlarged physical versions of captured skin wrinkles and other surface textures: raised relief tiles, plaques, curved swatches, and textured spheres. Accept reconstructed SurfacePatch/Atlas height data and existing meshes (STL, OBJ, PLY, or GLB using supported importers). Add PrintProject, PrinterProfile, and MeshValidationReport records. Keep this mode accessible directly from every scan, atlas, and material asset.

### 1. Inspect and preserve the source

Keep the untouched scan/mesh as the reference. Inspect units, transforms, dimensions, topology, valid coverage, confidence, and estimated sampling density. Apply scene transforms on import; STL units must be explicitly assigned if unknown. Prefer the original floating-point height field over an already decimated preview mesh. Do not bake noise, marker holes, atlas seams, or lighting artifacts into raised geometry.

An existing dense mesh is valid input without its source images. Offer local plane fitting and projection for a relief patch, with an interactive orientation/crop tool. Reject or partition multi-valued surfaces and overhangs instead of silently flattening them into one height per pixel. Keep arbitrary 3D meshes in a separate mesh-preserving branch when a faithful height-field representation is impossible.

High fidelity means preserving measured shape within a documented error tolerance. Subdivision and upsampling add vertices, not new measured detail. Do not invent pores, sharpen sensor noise into wrinkles, or claim resolution beyond the scan. Any optional artistic enhancement must be a separate version.

### 2. Set physical size and relief strength

Expose final width, height, base thickness, relief range, XY enlargement, Z exaggeration, and an aspect-ratio lock. Use millimeters for the output model. Separate true-scale, uniformly enlarged, and artistically exaggerated modes. Uncalibrated input requires an authored output size and relief range, labeled as such.

For a calibrated planar patch, use explicit transforms such as x_out = s_xy*x_source, y_out = s_xy*y_source, and z_top = base_thickness + s_z*(h-h_min), after converting source coordinates to millimeters. Compute h_min over valid selected data. Record the original height reference and every transform. A physically similar enlargement has s_z = s_xy; independent values intentionally alter proportions. Recompute the model bounds after every change.

Preserve natural valleys and ridges by default. Add an explicit inverse-relief option to turn grooves into raised lines for artistic displays, with a visible label. Do not accidentally export the negative impression of the gel instead of the reconstructed object surface. Provide cross-sections and a polarity toggle with an explanatory preview.

For before/after moisturizer samples, support a paired-print layout using identical XY/Z scaling, processing, and tile dimensions. Do not independently stretch both samples to the same relief range, which would erase meaningful differences.

### 3. Generate detail-preserving geometry

Implement controlled outlier removal and optional feature-preserving denoising with source-versus-result comparison. Preserve a physical-unit error map, and keep noise filtering distinct from decorative smoothing. Crop invalid borders. For interior missing regions, let users exclude the region, split the tile, or explicitly fill it as a derived repair; record any fill in provenance.

For height fields, generate a triangulated top surface, using adaptive tessellation or an equivalent approach whose deviation from the source is measured. Refine around high curvature and narrow wrinkle valleys. Let users set geometric tolerance in millimeters and a triangle/memory budget. If the budget cannot meet tolerance, report the achieved error rather than claiming success. Test dense samples across triangle interiors as well as vertices. Keep a high-resolution export mesh separate from a lighter UI preview.

For imported meshes, repair only justified defects and use error-bounded remeshing/decimation. Protect ridge/valley features and open boundaries. Avoid global smoothing that removes the texture the user wants to print. Show before/after triangle counts and distance/profile errors.

Convert displacement into vertex positions before export. Normal maps, bump shading, and PBR roughness alone do not create printable relief; if only those maps exist, request a height field or identify any integrated relative reconstruction as estimated. Do not translate a roughness map into height automatically.

### 4. Build a printable solid

Provide rectangular and circular relief tiles first, then curved swatches and textured spheres. For tiles, connect the top boundary to sidewalls and a flat bottom using shared vertices and consistent winding. Ensure the thinnest point retains the requested base thickness. Add optional borders, rounded exterior edges, a stand, and sample labels outside the scan area. Union additions into the solid rather than leaving overlapping shells.

For spheres, bake actual radial displacement, weld the seam/poles, and check self-intersections and minimum radius. Offer a flattened base or separate display stand. Curved substrates must retain valid wall thickness after displacement. Do not attempt to reconstruct the original anatomical shape from a local texture patch.

Validate finite coordinates, degenerate/duplicate faces, edge incidence, vertex manifoldness, consistent orientation, self-intersections, connected components, closed boundaries, positive volume, bounding dimensions, and minimum thickness. Watertightness alone is not sufficient. Flag unresolved defects, provide a repair preview, and prevent failed meshes from being labeled print-ready. Preserve the failed project for further editing.

### 5. Check detail against the intended printing process

Add editable FDM and resin printer profiles containing build volume, layer height, effective lateral feature limit, minimum raised-line width, minimum groove width, minimum wall/base thickness, and relevant orientation/support settings. Require user-entered or documented machine/material values; do not invent a universal high-detail profile. Nozzle diameter or pixel pitch alone is not proof of achievable feature resolution.

Visualize scan details likely to be lost at the selected output scale. Estimate how many layers span the relief height and whether narrow ridges/grooves exceed the profile's feature limits. Suggest XY enlargement and Z exaggeration separately. Label these as estimates until verified by a physical print.

Generate a small calibration coupon from the same scan with multiple labeled scale/exaggeration variants. Offer before/after coupons with matched scales. Keep labels on the underside or border. Provide orientation/support guidance that keeps supports away from the featured texture where practical. Leave printer-specific support generation to the slicer unless a real supported integration exists.

### 6. Preview, export, and round-trip verification

Create a Print Studio interface with source/print split view, wireframe, cross-section, measurement ruler, detail-loss overlay, dimensions, scale factors, triangle count, and validation state. Clearly distinguish rendered texture detail from actual triangles. Run large mesh jobs asynchronously with cancellation and memory limits.

Export binary STL with an explicit millimeter convention in the filename/manifest, and 3MF with explicit units using a validated library. Do not rename another format to .3mf. Include the high-resolution mesh, source metadata, scale/exaggeration settings, repair log, printer profile, validation report, and an overview image in a print package. Retain GLB/OBJ/PLY options for editing and web preview where useful.

Reload the exported files and verify dimensions, orientation, topology, and surface error. Use a supported slicer CLI for a smoke test when available; otherwise mark slicing as unverified. Provide slicer import instructions without claiming successful physical printing. Do not generate machine-ready G-code without a confirmed printer profile.

Acceptance fixtures must include a calibrated analytic height field with narrow valleys, an open scanned patch needing a base, an imported mesh with incorrect units, masked holes, a self-intersection failure, and a sphere seam. Verify that intended raised detail exists in exported geometry, dimensions survive round trips, and paired prints retain relative depth differences. Evaluate the final mesh against the appropriately scaled source, not against the unscaled scan. Include maximum and percentile errors and note that these measure processing fidelity, not original sensor accuracy.

## Shared material sphere pipeline and gallery

Create a reusable pipeline from patch/atlas to maps, material descriptor, sphere preview, and shareable web gallery bundle.

Use physically based lighting, orbit controls, exposure, directional grazing light, and an environment-light option. Include sphere and flat-patch views. Support bump-only, normal-only, displacement-only, and combined split-frequency views, with roughness-map inspection and wireframe.

Displacement must modify actual geometry when enabled and therefore change silhouettes; use adequate tessellation and selectable quality. Recompute or correctly evaluate displaced shading normals. For limited hardware, explicitly fall back to normal/bump rendering and identify that mode. Honor map color spaces: normals, height, masks, and roughness are linear data; authored base-color textures follow the renderer's color-management convention.

UV wrapping creates seams and pole distortion. Provide seam inspection, adjustable rotation/repeats, and a suitable mapping strategy. Make clear that applying a flat sample to a sphere is a material presentation, not recovery of the original body shape. Keep source sample dimensions separate from artistic sphere texture repeats and exaggeration. Show physical and artistic displacement strength separately.

Make gallery cards for body-region samples with thumbnail, source status, scale if known, and material controls. Seed empty/demo states with unmistakably synthetic wrinkle textures, never invented human measurements. Use lazy loading, bounded texture resolutions, and disposal of GPU resources when cards unmount. Include responsive layouts and keyboard-accessible controls.

Prepare a standalone static gallery export that runs on ordinary HTTPS hosting without the processing backend. Include assets, a manifest, a build/run command, and deployment instructions. Keep raw body captures out of gallery exports by default; publish only the assets the user selects. Prepare the preview and package without making this prompt an automatic authorization to publish private captures.

Export a texture ZIP containing maps, preview, README, and manifest. Offer GLB with base PBR and normal textures where supported, but document that standard glTF does not portably encode arbitrary displacement. For portable displaced shape, bake the displacement into mesh vertices and export that mesh with compatible material textures; retain the original height map separately.

## Validation and completion criteria

Use deterministic synthetic fixtures and real user data when available. Tests must cover substantive numerical behavior:

- A flat height field produces a flat normal map; a known ramp/bump has the correct orientation, scale, and sign.
- Height encoding/decoding preserves documented precision, bias, and scale without clipping.
- Known overlapping crops recover a connected atlas within declared pixel tolerances; unrelated and repetitive ambiguous pairs are rejected or marked uncertain.
- Invalid contacts and fixed gel markers cannot dominate alignment. Loop closure reduces drift on a controlled sequence.
- Calibration absence disables metric claims. Missing weights and malformed input produce actionable errors.
- Seamless edits preserve a separate measured source and mark invented pixels.
- The same exported material renders consistently after reload. Displacement visibly affects a silhouette; normal mapping alone does not.
- The static gallery works without the processing server, and export archives contain no unselected raw captures.

Implement a complete vertical slice first: imported data -> patch -> maps -> sphere -> export. Next complete the print path: patch or imported mesh -> scaled relief -> closed solid -> validation -> STL/3MF package. Then implement atlas stitching, skin analysis, brush drawing, curved print variants, and optional live input. This ordering is a development plan, not permission to leave later modes as stubs. Include a generated relief tile and a paired comparison coupon as verified export examples, with physical printing status stated separately.

Deliver working code, setup/run instructions, dependency and license notes, a sample project with synthetic provenance, texture and gallery export examples, processing configuration documentation, and a brief validation report. State what was implemented, what was actually tested, and any hardware/calibration limitations. Do not claim paper-level fidelity, live-hardware verification, Photoshop import validation, or online deployment unless performed. Continue through implementation and verification rather than returning only a plan.
