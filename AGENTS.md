# GelSight Material Studio — decisions and working rules

This is the repository's agent guide and decision log. Update it when a significant
architecture, scientific, file-format, or validation decision changes. Detailed
status and evidence belong in `docs/studio-validation.md`, not in completion claims.

## Accepted decisions — 2026-09-17

1. Preserve `gelsight_p5/` and its acquisition, bundled Mini model, WASM, and exports.
   Build the new application in `studio/`, with a Python CPU processing package,
   local FastAPI service and CLI, and a vanilla ES-module/Three.js UI. The existing
   app is vanilla JavaScript/p5; introducing React would add an unnecessary stack.
2. The user's specification is `docs/material-studio-spec.md`. It is an engineering
   target, not evidence of scientific accuracy. Record omissions candidly.
3. Keep source uploads immutable and hash them. Save derived versions separately.
   Never serve the data directory wholesale. Exports select derived assets by ID.
4. Metric measurements require explicit source units, spacing and validation
   provenance. The bundled Mini network supplies relative relief only. Baseline
   subtraction is not a metric calibration. Failed configured models must error.
5. Coordinates: array rows point down, surface X points right, surface Y points up,
   object relief Z points out. Store height units and XY spacing explicitly.
   OpenGL normals use Y up; DirectX flips the green channel. STL output is mm.
6. Research algorithms guide independent implementations. Do not copy GelSLAM
   source without a verified redistribution license. Do not invent skin-paper
   weights, sensor resolution, force data, measured reflectance or physical tests.
7. Atlas transforms map source pixel coordinates to island coordinates. Verified
   rigid registration is the baseline. Islands are never silently joined. Artistic
   deformation and fills carry synthetic masks and invalidate atlas measurements.
8. Prints bake real height into geometry. Preserve source and scaled-source error.
   Failed or incomplete validation cannot produce a print-ready label. Printer
   limits are authored values, and slicer/physical verification is reported separately.
9. Use actual image brush exports and actual STL/3MF files. Do not disguise formats.
   Gallery exports run without a backend and omit unselected captures and metadata.
10. CPU jobs have input/memory budgets, progress, cancellation and actionable errors.
    Bind the service to loopback by default. The later dictionary authorization and
    specimen limits are recorded in decisions 11–16 below.

## Texture Dictionary extension — 2026-09-17

11. The user subsequently requested online publication through Sites. That request
    authorizes the website deployment; each specimen still requires explicit public
    selection. Preserve private/draft records and never infer approval of captures.
12. Keep owner editing in the loopback Studio service. Publish a separate static,
    allowlisted build in `texture-dictionary/`; no admin API, source captures or draft
    data goes to the host. Stable specimen slugs survive revisions/unpublish/republish;
    public asset paths include the revision. Read `docs/texture-dictionary-spec.md`.
13. A specimen is the collected source, with multiple reproducible ImpressionVariant
    records. Ink effects are deterministic artistic layers and never alter geometry.
    Physical scan force and virtual printing pressure are different metadata.
14. Warm paper and dark ink follow the user's requested collection design. Gyotaku
    informs the idea of recording an impression; no fish illustration or generated
    replacement surface is needed. Synthetic fixtures are labeled and excluded from
    production until explicitly selected. Public fields and downloads are allowlisted.
15. The user explicitly selected **“Keep the public collection empty for now.”**
    Deploy an empty public dictionary. Keep the bundled coin and both synthetic
    examples as local drafts. Do not publish samples without new explicit approval.
16. Texture Dictionary uses frozen public snapshots and revision-specific asset paths.
    Local approval and hosted deployment are distinct; unpublish needs a new build
    and deployment to remove an entry already online. Exhibition exports reuse only
    approved snapshots. Display images remain saveable even with downloads disabled.
17. Manufacturing STL/3MF uses millimeters; GLB uses meters. Material GLB bakes full
    relief and omits extra normal relief to avoid double-counting. Interactive split
    mode uses coarse displacement and fine normals. Rounded borders affect exterior
    corners in plan and preserve the observed top surface.
18. Owner ink previews are bounded, read-only computations. Full variants keep source
    hashes, seeds and settings. All action buttons inside forms must use type=button
    unless they intentionally submit the form; browser tests cover the complete flow.
19. Sites confirmed the empty public deployment on 2026-09-17 at
    https://texture-dictionary-gelsight-studio.jeffrey-yiji-wang.chatgpt.site .
    Reuse `texture-dictionary/.openai/hosting.json` and its separate source repository.
    Do not confuse the initially estimated hostname with the confirmed live URL.
20. Gyotaku print engine 2 stores every resolved setting, the engine version, seed,
    source hash and page layout. Render artistic layers on the cropped source grid
    before preview/export layout. Keep `studio/ink_v1.py` for reproducing older
    recipes; missing version fields on existing records mean engine 1. Palette
    selection starts engine 2. Do not silently rewrite historical variants.
21. Metric page layout uses the source's X/Y sample spacing and rotated physical
    extent. Source dimensions measure sample-center spans `(N-1)*spacing`.
    Magnification derives from the actual raster fit and authored page width;
    rotated calibrated prints may have a page-space source ruler. Uncalibrated
    prints never acquire a physical scale bar. Clean style suppresses all added
    ink artifacts. Relief shading is separate from transparent contact coverage.
22. Pressure proofs are read-only owner exports at virtual pressures 0.25/0.55/0.85.
    They do not create variants, select covers, modify geometry or publish entries.
    The local coin studies in `examples/generated/gyotaku/` come from the provided
    tactile scan and remain private. A proof's caption may use an installed Unicode
    font; the master print's metric labels use Pillow's bundled font.

## Live Mini typologies — 2026-09-24

23. The user requested their connected GelSight Mini and Kyle McDonald's ShuffleSnap
    for image typologies. Use the actual pinned `shufflesnap==0.3.0` solver, not an
    imitation or an unrelated sort. Local image descriptors and deterministic PCA
    provide its 2D input. Descriptor neighborhoods are visual comparisons, not
    calibrated geometry, material classification, force or health measurements.
24. Capture through named-device Chrome `getUserMedia` in Live Typology. Never
    silently open the default/integrated webcam. The dedicated launcher grants
    camera permission only to `http://127.0.0.1:8090` in its separate local Chrome
    profile. Real Mini video at 640×480 was verified on this host; native OpenCV
    could enumerate but could not open it. Keep diagnostic results distinct from
    the working browser capture path and from independent physical calibration.
25. Save explicit captures in a sensor-specific collection session. The user must
    deliberately save an untouched baseline; no contact state is inferred. Baselines
    and synthetic fixtures are excluded from typology selection by default. Raw
    images are immutable, and saving a typology does not publish its source images.
26. Typology records freeze selected source IDs/hashes, descriptors, PCA coordinates,
    grid cells and solver settings. Limit boards to 2–2000 selected images, run the
    solver to convergence inside cancellable bounded jobs, and pass `margin=0`
    explicitly for the released 0.3.0 API. Private PNG/HTML/ZIP exports contain only
    selected image previews and layout metadata. They are separate from public
    dictionary approvals. The public collection remains empty.

## p5 capture, surface typologies and unfolding — 2026-09-24

27. Studio embeds the unchanged p5 app through `/p5-studio`, injecting a same-origin
    bridge. Keep the original standalone assets unchanged. Studio camera entry
    points select a named GelSight only; leaving a camera mode releases its stream.
28. The user confirmed removing 10% from every edge: retain the central 80% in X/Y.
    Preserve full raw RGB plus an explicit derived crop. p5 retains interactive
    crop overrides and records the actual crop. Synchronized bundles freeze RGB,
    float relative depth, background, depth display, current mesh view and settings.
    Changing baseline geometry requires recalibration; baseline is not metric scale.
29. Typology raw/depth/mesh sheets share one frozen assignment and have named and
    image-only exports. Do not fabricate capture-time views for old RGB imports.
30. `/unfold` is a separate owner program using bounded jobs, appearance clustering,
    connected regions and rotated edge matching. Retain source hashes, region boxes,
    exclusions, coverage, rotations and inferred neighbor costs. Assemblies are
    synthetic display compositions, never measured patches or recovered topology.
    Sphere wrapping is a UV projection with visible seam/pole distortion. Normalize
    available depth per source only for display; missing depth remains flat.
31. Actual typology meshes reuse frozen ShuffleSnap cells and captured height patches.
    Older RGB boards may explicitly create a new surface-view revision using latest
    linked reconstructions. Record source IDs/hashes and preserve the old revision.
    Keep scan components separate: similarity is not physical registration. Export
    OBJ in authored display coordinates and float height/masks separately. Mixed
    metric/relative inputs require explicit per-source display normalization.
    An optional connected version may add explicitly named synthetic seam triangles
    without moving source vertices. Export connected geometry/depth separately and
    retain source/synthetic pixel masks and the synthetic face range. Default
    geometry remains disconnected at independent scan boundaries.
32. p5 Studio calibration averages RGB on the same distinct frames as depth.
    Only a matching RGB baseline produces a clean transparent contact view and
    absolute difference image. Store threshold, gain and originals. p5 depth is
    already background-subtracted; never subtract again. Missing backgrounds remain
    unavailable, and a contact alpha mask is not a physical contact/force measurement.
33. Bound BLAS/OpenMP thread defaults to two in the owner CLI/server as well as
    job workers, respecting explicit environment overrides. Browser + scientific
    runtime tests exposed Windows memory pressure; report allocation failures as
    actionable owner API errors and run heavy validation suites sequentially.
34. Typology normal maps derive from float depth at the exported mesh's authored
    XY/Z display scale. Mask-aware finite differences never cross independent
    source cells in the default version. Export OpenGL (+Y) and DirectX (green
    flipped) PNGs, validity masks and float OpenGL normals. Connected raster
    normals include artistic interpolation, not exact OBJ face normals; retain
    a synthetic-influence mask including affected source-edge pixels. Invalid
    PNG pixels are neutral blue. Freeze maps in new board revisions and do not
    add their relief again to the already displaced interactive mesh.

35. New p5 capture bundles automatically export full-resolution OBJ geometry,
    OpenGL/DirectX normal PNGs and float OpenGL normals from the same frozen depth.
    Per-capture XY uses unit model pixels and Z preserves solver values; no metric
    units or screenshot Z exaggeration are implied. Record asset links and scale
    in sample.json. The mesh screenshot remains a separate asset. Old samples are
    not rewritten. Label the older quick capture RGB-only and direct complete
    capture to p5; never imply a camera-only path ran depth inference.

36. Video Capture is an explicit named-device MediaRecorder Start/Stop workflow.
    Preserve and hash the uploaded RGB video. FFmpeg selects bounded frame intervals
    with original-frame indices and presentation times; freeze tool version, limits
    and source links per extraction run. Offline Mini MLP/masked Poisson produces
    relative surfaces, not live p5 depth or a claimed metric recording. Apply the
    central-80% crop once before inference; normals and mesh share that cropped
    field. Rejected frames retain RGB and reasons. Do not invent live mesh views.
    Optional untouched references are explicitly captured, never inferred. Stop
    streams when leaving the mode and terminate FFmpeg descendants on job cancellation.

## Native matrix application — 2026-10-01

37. The user explicitly requested a separate native Python Windows application.
    Use `desktop_studio/` with Qt Widgets and native OpenGL; no HTML, WebEngine or
    HTTP server. Preserve the existing Studio and original p5 app. Native projects
    are private, immutable-source, versioned folders under `desktop-data/` by default.
38. Compare configuration to the local Golan core, not an endorsement by its author.
    Native CPU reconstruction uses bundled FP32 weights, full 320×240 inference,
    original marker fill and DCT recipe (lambda 0.0005). Disable temporal mixing
    for frozen stills. Crop 10% per edge once before inference; record integer bounds.
    CPU/browser resampling can differ. A 50-distinct-frame untouched baseline is
    explicit and nonmetric; reconnect/resolution changes require recalibration.
39. Prefer named-device Qt capture; use native FFmpeg DirectShow when Qt enumerates
    no Mini. Probe advertised formats. This Mini exposes 3280×2464 MJPEG at 25 fps;
    guessing 640×480 input fails. Deliver bounded 640×480 or 1280×960 RGB, recording
    the input mode and resize. Immutable `source.png` is the delivered frame, not
    the original MJPEG packet. Never select an integrated/default webcam.
40. Matrix rows are left-aligned and may be ragged. Match only existing right/down
    normal-map neighbors; gate correspondences. Translation fitting retains explicit
    grid priors for unmatched regions. Level/blend relative depth and fill ragged gaps
    for an artistic rectangular continuous surface, never claimed physical topology.
    Retain observations, synthetic masks, rejected links, source hashes and placement
    reports. Derive final normals and geometry from the same fused depth field.
41. Per-cell and assembled outputs include float depth/normals, RGB/normal previews,
    binary surface PLY and point-cloud PLY. A separate flat UV GLB carries the normal
    material; never double-count relief on the displaced mesh. Native preview reduces
    geometry only for interaction. Full-resolution STL uses every depth sample plus
    a bottom and outer walls, with authored mm dimensions and explicit topology/reload
    validation. No physical print-ready label without printer/slicer/physical checks.
42. Bound native projects to 100 captures and assemblies to 600,000 pixels. Background
    jobs cancel at stage boundaries; lock projects against simultaneous windows.
    Calibration/capture/assembly manifests enter the project only after successful
    completion. Incomplete unindexed diagnostic folders can remain after cancellation.
43. Native Live GelSight is a dedicated tab, independent of Captured maps and the
    3D viewport. Captures and matrix selection never replace its current camera
    image. Switching tabs preserves streaming; disconnecting clears the live preview.
44. The user reported permanent puncture/damage in the Mini gel (2026-10-08).
    Browser Live Typology and p5 Live Capture provide an explicit untouched-reference
    damage editor. Store authored normalized full-source ellipses, reference identity/
    hash and a two-processing-pixel exclusion margin in each new capture. Crop mapping
    follows actual integer bounds. Never call excluded pixels repaired or measured.
    Quick-capture reconstruction freezes its raw baseline and excludes damage before
    masked integration. p5 keeps its original baseline-subtracted solver values and
    excludes damage from saved geometry/normals without subtracting depth twice.
    p5's live diagnostic screenshot remains unmasked and is omitted from corrected
    typology mesh sheets. Recomputed typology surfaces retain the source validity mask.
    Median replacement in RGB comparison previews/descriptors is display preprocessing,
    not recovered texture. Original RGB and historical captures remain unchanged.
    Require a fresh reference after reconnect/configuration changes; no automatic
    no-contact inference or persisted unverified damage profile.

45. High-resolution all-collection exports are a separate read-only batch command,
    `python -m studio.collection_export`. Snapshot indexed native captures and
    nonsynthetic sensor sessions; exclude untouched references and fixture imports.
    Preserve each stored depth grid and source hashes. RGB-only frames may receive
    explicitly labeled offline relative Mini inference; absent baselines remain
    absent. Use actual ShuffleSnap for multi-image boards and freeze its assignment.
    The user requested a continuous flat-filled composition: retain original heights,
    record an eight-pixel synthetic taper to zero and flat gaps, derive normals from
    the constructed field, and export a closed solid separately from source geometry.
    Authored mm dimensions are display/print design, never measured sensor units.
    This offline path permits up to 32 million height samples and 256 million RGB
    pixels, with streamed mesh writing and disk-backed topology validation. It does
    not raise the native interactive assembly budget. Verify every serialized edge,
    winding, Euler characteristic, positive volume and STL triangle round trip.
    Completed manifests are immutable; resume verifies sources and finished exports.

46. Explicit twelve-cell studies use a fixed 3-column by 4-row layout: scans 0–2,
    3–5, 6–8 and 9–11. Do not run similarity sorting on an authored order. The
    supplied GelSight archive has 124 captures in five collections / thirteen
    panel groups; preserve original folder and metadata labels, and leave absent
    scans as labeled empty slots. Preserve and hash the ZIP and extracted files.
    Source layers, supplied float depth and metadata remain unchanged. Archive
    depth declares mm and 0.0634 mm/pixel, with unverified physical calibration;
    preserve this distinction from relative solver units and authored board mm.
47. Archive force reports have zero tracked markers and null Newton values.
    Preserve supplied shear imagery and dense flow as unvalidated source outputs;
    do not equate nonzero dense flow with tracked markers or measured shear.
    Research-informed load arrows, waves and tearing are deterministic artistic
    animation, not force estimation, physical simulation, or material failure.
    Per-cell particle sorting uses relative height, never an invented force rank.
    Source-displaced models do not receive additional normal-map relief. Model
    preview decimation/exaggeration is separate from full-resolution geometry.

## Required validation (all applications)


Run the numerical tests in `tests/`, the synthetic example generator, and the
browser smoke test. Test masks, normal orientation/scaling, round-trip precision,
registration rejection, calibrated-state gating, mesh topology and export reloads.
Keep the original browser viewer's regression check working where its dependencies
are available. Do not claim hardware, Photoshop, slicer or physical printing tests
unless actually performed. Keep tests focused on substantive behavior.

## Development

See `docs/studio.md` for setup, API/CLI, formats and calibration. Runtime data is
local and ignored by Git; deterministic synthetic fixtures are explicitly labeled.
No sub-agent delegation is required by this file.
