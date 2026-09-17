# Dependencies and redistribution notes

The original repository states an intention to distribute under GPL-3.0-or-later
in its README. The new Studio code follows that project context. This work does
not change ownership or grant new rights in users' scans, stories or generated assets.
Specimen publication defaults to “All rights reserved”; the owner controls its credit
and license fields. No stock or generative surface imagery was added.

The existing bundled GelSight Mini weights/code originate from the repository's
GelSight integration. The [upstream SDK license](https://github.com/gelsightinc/gsrobotics/blob/main/LICENSE)
is GPL-3.0. Preserve upstream notices and inspect `technical_information_js.md`
before redistributing the complete application. GelSLAM code and skin-paper weights
are not bundled. Research references do not grant rights to unreleased implementations.

Direct dependencies are pinned in `requirements-studio.txt` and `package-lock.json`.
Installed distribution metadata provides the definitive texts/attributions for the
version being redistributed. Transitive compiled wheels can include further notices.

| Dependency | Upstream license family / purpose |
| --- | --- |
| NumPy, SciPy | BSD; numerical arrays/integration/optimization |
| OpenCV Python headless | Apache-2.0 for OpenCV; wheel includes third-party notices |
| Pillow | MIT-CMU / HPND historical notices; image processing |
| scikit-image | BSD; morphology/skeletonization |
| FastAPI, Uvicorn, Pydantic, httpx, python-multipart, pytest | MIT/BSD family; API, validation and tests (see installed texts) |
| trimesh | MIT; geometry import/export and inspection |
| lib3mf | BSD-2-Clause; actual unit-aware 3MF writing/reloading |
| manifold3d | Apache-2.0; solid booleans and bounded simplification |
| Three.js | MIT; interactive material/mesh rendering |
| Playwright | Apache-2.0; browser validation only |
| Optional PyTorch | BSD-style, additional dependency notices; supplied TorchScript models only |

`npm run setup:web` copies Three.js and its LICENSE locally so gallery/dictionary
exports work without a CDN. Python processing packages and Playwright are not
included in public static builds. Keep relevant license files with redistributed
dependencies. The static site source is included in the Sites source repository;
its data assets retain each specimen's owner-selected license.
