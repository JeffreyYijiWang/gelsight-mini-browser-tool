# Mini capture and image typologies

Double-click **Start-Material-Studio.cmd** in the project folder. The launcher
starts the loopback Studio server when needed and opens a dedicated Chrome window
at `http://127.0.0.1:8090/#typology`. It selects only a camera whose driver label
contains GelSight. Your ordinary Chrome profile is not changed.

## Collect a series

1. Plug in the Mini. The Live Typology panel should name the device and show its
   live image. On this computer, **GelSight Mini R0B 65Y7-RDNB** was verified at
   **640 × 480**. Use Connect Mini if it has not connected automatically.
2. Choose **Start a new collection**. With the gel clear of any object, click
   **Save no-contact baseline**. This records a background for relative relief
   reconstruction; it does not establish millimeter calibration.
3. Place a surface against the gel, allow the image to settle, enter a sample name
   such as “linen 01”, then click **Capture sample**. Repeat for each surface.
4. Each saved sample is selected for the next typology. Captures from this Mini
   stay in the chosen session. A new-session selection takes effect on the next
   saved baseline or sample. No continuous recording or automatic specimen
   publication occurs.
5. To reconstruct a capture, use **Reconstruct last capture**, or inspect its tile
   in a board and choose **Reconstruct this capture**. The existing Surface Capture
   workflow uses this session's baseline. Its bundled model remains relative.
   Collect a reconstructed patch in Texture Dictionary to make gyotaku variants.

## Compare the images

Choose Tactile RGB captures, Reconstructed height previews, Gyotaku ink impressions,
or All image types. Filter by session/name. Baselines and synthetic demonstration
images are hidden by default; their inclusion requires their checkboxes.

Select the images you want, or click **Select visible images**. Selection is
retained across filters; **Clear selection** resets it. At least two selected
images are needed. Name the board, choose its columns (0 means automatic), and
click **Build with ShuffleSnap**. Processing has progress and cancellation.

Texture similarity uses normalized grayscale structure, spatial frequencies,
gradient direction and local contrast. Appearance similarity uses coarse RGB
appearance, preserving color differences. PCA reduces these descriptors to 2D;
ShuffleSnap maps the points into distinct grid cells without overlapping tiles.
The board shows how much descriptor variation the two PCA axes retain. No learned
semantic model or remote embedding service is involved.

Neighbors suggest visual resemblance. They do not establish identical materials,
physical roughness, skin health or differences caused by a treatment. Keep scan
orientation, crop, contact conditions and illumination consistent when comparing.
Tactile RGB includes the sensor's colored illumination; it is not measured material
color. Height previews are independently contrast-normalized and not a shared
millimeter scale. Ink palettes and page margins influence appearance comparisons.

Click a tile to inspect the original saved capture or derived image. The frozen
board's previews and source hashes retain what was used to build that layout.
Adding/removing images can change the layout; rebuild to incorporate new captures.
Earlier boards and original source files remain unchanged.

## Save and export

- **Contact sheet PNG:** a numbered grid, capped at 24 megapixels and 8000 pixels
  per dimension. Numbers map to names in the interactive board/JSON.
- **Open comparison board:** a separate, read-only local page with fixed grid order.
- **Export private board ZIP:** standalone `index.html`, selected previews, PNG,
  `typology.json`, `features.npz` and a checksummed export manifest. Extract it and
  open `index.html`; no server is needed for this exported grid.

The JSON stores source references/hashes, descriptor version, points, assignment,
grid dimensions, comparison mode, solver version and settings. A board selects
2–2000 images. The actual ShuffleSnap 0.3.0 solver runs to convergence with two
threads; its `margin=0` parameter is explicit. No N×N image-distance matrix is used.
Very elongated grids may need more columns to fit the contact-sheet size budget.

These are **private exports**: the previews and selected labels can contain personal
captures. Exporting does not publish them. The hosted Texture Dictionary remains
empty and still requires explicit specimen approval.

## Running and troubleshooting

The configured environment needs `.venv-studio`, installed Chrome, Node and
`npm ci` / `npm run setup:web`. The pinned Python dependencies include
`shufflesnap==0.3.0` and `cv2-enumerate-cameras==1.3.4`.

```powershell
# Visible local app, named Mini connection
.\start-studio.ps1 -OpenBrowser
# Server only (existing behavior)
.\start-studio.ps1
```

The dedicated browser profile is `studio-data/mini-browser-profile/`; camera
permission is scoped to the local Studio origin. Close its Chrome window when
finished to release the sensor. If the profile is already open, use that window
rather than launching a second copy. The server remains local in the background.
Logs are in `studio-data/logs/`.

If a normal browser or Codex panel cannot identify/open the Mini, use the launcher.
Camera permission may conceal device labels; Studio will not probe unrelated
webcams to discover the Mini. If Chrome reports system denial, check Windows camera
access yourself and ensure another application is not holding the device. On this
host, an unrestricted Chrome camera check succeeded while the restricted browser
and native OpenCV checks could not open the stream.

Validation commands:

```powershell
.\.venv-studio\Scripts\python.exe -m pytest -q tests/test_typology.py
node tools/verify-typology.mjs
# Hardware check only; closes the Mini after reading one frame
node tools/check-mini-browser.mjs
```

The automated browser comparison test imports clearly labeled synthetic fixtures;
it does not capture real surfaces. Hardware evidence is separately recorded in
`test-artifacts/mini-browser-check.json` and the launcher's local status log.

Algorithm/source: [Kyle McDonald's ShuffleSnap](https://github.com/kylemcdonald/shufflesnap).
