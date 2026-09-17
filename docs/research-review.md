# Research review and implementation choices

Reviewed against the official sources on 2026-09-17. The product brief is a set of
engineering requirements, not evidence that research code or accuracy transfers
to this hardware or application.

| Source | What is used | Boundaries and deviations |
| --- | --- | --- |
| [Padmanabha et al., 2025 methods](https://arxiv.org/html/2509.11385v1) | Normal prediction, integration, detrending, directional valley profiles, nearby peaks and an 80th-percentile summary inform the independent pipeline. | The paper uses a custom soft gel and controlled force. No released compatible weights/training set was identified. Studio uses its existing Mini network or supplied calibration, a sparse masked least-squares integrator with independent component anchors, and six local directional valley comparisons. It does not reproduce the paper's periodic FFT solver or claim its accuracy. |
| [GelSLAM official repository](https://github.com/rpl-cmu/gelslam) / [paper](https://arxiv.org/abs/2508.15990) | Verified relative registration, global graph adjustment and loop closure inform the planar atlas design. | No GelSLAM source was copied because redistribution permission was not established during this review. This independently implemented SIFT/RANSAC and least-squares mosaic is 2D/2.5D, not full 3D GelSLAM. |
| [GelSight robotics SDK](https://github.com/gelsightinc/gsrobotics) | Compatibility with the Mini model already bundled in this repository; reviewed feature order, output convention and source license. | The packed 5→64→64→64→2 model is reused locally. Camera baseline subtraction removes slope bias; it does not establish metric calibration. Upstream code is GPL-3.0. |
| [PBRT microfacet theory](https://www.pbr-book.org/4ed/Reflection_Models/Roughness_Using_Microfacet_Theory) | Editable dielectric GGX-style material, with roughness controlling the shader distribution. | Geometric height variation does not measure BRDF/albedo/gloss. Constant roughness is authored; the optional slope-statistic texture is an artistic estimate. |
| [Adobe brush-tip workflow](https://helpx.adobe.com/photoshop/desktop/apply-painting-techniques/brushes-presets/create-brush-tip-image.html) | Export actual grayscale image brush tips plus pattern grain and setup instructions. | No native ABR is fabricated. Photoshop import remains untested. |

Metric wrinkle analysis runs only on a calibrated original patch with a compatible
model/import provenance and valid observed pixels. It excludes synthetic fills and
edited versions. The six-angle valley skeleton/depth estimate is a reference-inspired
engineering method, not a clinically validated endpoint. Small digital error against
an analytic source says nothing about sensor error on living skin.

The atlas rejects ambiguous/repetitive matches and weak coverage. Adjacent duplicate
frames are excluded from fusion. Loop links need the same geometric checks as local
links. Heights are fused only when reconstructed patches exist, with overlap offsets
solved jointly; there is no per-frame relief-range normalization. Artistic local
warps are bounded, visualized and marked; measurements stay on source patches.

Gyotaku is an artistic reference for preserving an impression from a encountered
surface. Texture Dictionary is a digital interpretation of that idea, not traditional
fish printing. Its sigmoid coverage, virtual pressure, breakup and paper grain are
reproducible artistic layers. They do not model actual capture force, replace the
observed surface, modify wrinkle metrics or enter manufacturing geometry.

Geometry validation distinguishes topology from self-intersection. Generated
height solids use positive-thickness, injective construction checks. Imported shapes
use an explicit triangle-intersection search with a candidate budget; exceeding the
budget is unresolved, not success. Manifold booleans join labels/bases/borders. Mesh
simplification is accepted only after sampled bidirectional surface-error checks.
These finite checks are engineering verification, not formal sensor/process accuracy.
