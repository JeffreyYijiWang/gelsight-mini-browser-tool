# GelSight-Mini View/Export Tool

This is a browser-based tool for viewing, reconstructing, and exporting data
from a GelSight Mini tactile sensor.

![gelsight_demo_screenshot.png](images/gelsight_demo_screenshot.png)

---

## Overview

The GelSight family of tactile sensors are vision-based touch sensors that transform physical contact into high-resolution 3D measurements of surface geometry. Rather than relying on arrays of pressure sensors, a GelSight device contains a soft, transparent elastomer coated with a reflective membrane; when pressed against an object, the gel conforms to its microscopic topography, and an internal camera with colored LED illumination images the resulting deformation. Using photometric stereo, the system reconstructs a micron-scale 3D height map. Because the sensing process depends on geometry rather than optical appearance, GelSight can accurately inspect opaque, reflective, transparent, or textured materials with sub-micron depth sensitivity.

The GelSight Mini presents to the computer as a standard UVC webcam. The browser
captures its live video stream, estimates a depth map from the colored tactile
image, displays a 3D mesh preview, and exports captures as ZIP files containing
images, depth maps, OBJ meshes, calibration data, and metadata.

## What You Need

- A GelSight Mini tactile sensor connected by USB.
- A recent desktop browser. Chrome is recommended.
- A local web server. The browser camera API works from `localhost`.

## First-Time Setup

Download or clone this repository, then start a local web server from the
top-level project folder:

```sh
python3 -m http.server 8002
```

Open this URL in Chrome:

```text
http://127.0.0.1:8002/gelsight_p5/
```

You do not need Node.js or npm for normal use of the tool. The app ships with
the browser assets it needs for the default custom-WASM reconstruction path.

Do not open `index.html` by double-clicking it. Browser camera access and local
WASM/model loading are more reliable from `http://localhost` than from a
`file://` URL.

## How To Use The Tool

1. Plug in the GelSight Mini.

2. Open the tool in the browser:

   ```text
   http://127.0.0.1:8002/gelsight_p5/
   ```

3. Choose the GelSight Mini from the camera menu.

4. Choose a capture resolution. The default is intended to balance quality and
   speed.

5. Click `Enable Camera` and allow browser camera access if prompted.

6. Adjust the crop rectangle over the useful part of the GelSight image.

7. With nothing touching the gel surface, click `Calibrate`.

8. Wait for calibration to finish. Do not touch the sensor while it says
   `CALIBRATING`.

9. Press an object into the GelSight surface. The tool will show:

   - the live GelSight camera image
   - an estimated depth image
   - a 3D mesh preview

10. Use the controls as needed:

    - `Fast (160x120)` / `Full (320x240)` changes inference quality.
    - `Lambda` adjusts Poisson integration regularization.
    - `Alpha` adjusts temporal smoothing.
    - The vertical `Z` slider changes only the 3D preview scale.

11. If the `Calibrate` button pulses, recalibrate before trusting measurements.
    Changes such as crop or lambda can make the current calibration stale.

12. Click `Export` to save a ZIP file.

## Exported Files

Exports are named like:

```text
gelsight_YYYYMMDD_HHMMSS.zip
```

The ZIP can include:

- `capture.png`: the image used to compute the depth map and mesh.
- `capture_highres.jpg`: optional high-resolution camera grab.
- `depth_16bit.png`: normalized 16-bit depth image.
- `depth_solver_units_16bit.png`: fixed-range solver-unit depth image.
- `baseline_16bit.png`: calibration baseline, when available.
- `mesh.obj`: exported 3D mesh.
- `metadata.json`: capture, calibration, processing, and export metadata.

## Demo Mode

The `Demo` button loads a sample export from `gelsight_p5/captures/`. This is
useful for trying the interface without a connected sensor. When Demo mode is
active, the button changes to `Live`; click it to return to the camera.

## Notes

- The depth values are solver units, not calibrated millimeters.
- For best results, recalibrate after changing crop, lambda, inference quality,
  capture resolution, or sensor lighting/contact conditions.
- The 3D preview scale does not affect the exported OBJ.
- Technical implementation notes are in `technical_information_js.md`.
- A possible TouchDesigner roadmap is in `technical_information_td.md`.

## License

This project is intended to be distributed under GPL-3.0-or-later.

See the technical documentation for notes about redistributed GelSight-derived
model assets and third-party browser/runtime components.
