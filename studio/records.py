"""Persisted, explicit records. Physical truth is never inferred from RGB brightness."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def uid() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(default_factory=uid)
    created_at: str = Field(default_factory=now)


class CaptureSession(Record):
    name: str = "Untitled session"
    region: str = "custom"
    sensor_id: str | None = None
    gel_id: str | None = None
    force_n: float | None = None
    posture_notes: str | None = None
    frame_ids: list[str] = Field(default_factory=list)
    baseline_id: str | None = None
    synthetic: bool = False


class Frame(Record):
    session_id: str
    source_name: str
    sha256: str
    order: int
    width: int
    height: int
    timestamp_seconds: float | None = None
    raw_file: str
    kind: Literal["rgb", "height", "normal", "mesh"] = "rgb"
    quality: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)


class CalibrationProfile(Record):
    name: str
    sensor_id: str
    gel_id: str
    width: int = Field(gt=1)
    height: int = Field(gt=1)
    pixel_spacing_mm: tuple[float, float]
    adapter: Literal["mini_mlp", "torchscript", "polynomial"] = "mini_mlp"
    weights: str
    validated: bool = False
    validation_notes: str = ""
    camera_matrix: list[list[float]] | None = None
    distortion: list[float] | None = None
    normal_convention: Literal["image_y_down", "surface_y_up"] = "image_y_down"
    object_sign: Literal[-1, 1] = 1

    @model_validator(mode="after")
    def check_scale(self):
        if min(self.pixel_spacing_mm) <= 0:
            raise ValueError("Calibration pixel spacing must be positive in mm.")
        if self.validated and not self.validation_notes.strip():
            raise ValueError("Validated calibration requires independent validation notes.")
        return self


class SurfacePatch(Record):
    name: str
    region: str = "custom"
    source_ids: list[str] = Field(default_factory=list)
    session_id: str | None = None
    parent_id: str | None = None
    state: Literal["calibrated", "uncalibrated"] = "uncalibrated"
    units: Literal["mm", "relative"] = "relative"
    pixel_spacing: tuple[float, float] | None = None
    calibration_id: str | None = None
    validation_notes: str = ""
    synthetic: bool = False
    version: str = "original"
    width: int
    height: int
    arrays: str = ""
    height_reference: str = "imported reference preserved; positive is object relief outwards"
    settings: dict = Field(default_factory=dict)
    provenance: list[dict] = Field(default_factory=list)
    quality: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_metric(self):
        if self.state == "calibrated":
            if self.units != "mm" or not self.pixel_spacing or min(self.pixel_spacing) <= 0 or not self.validation_notes:
                raise ValueError("Metric patches require mm heights, positive XY spacing, and validation provenance.")
        elif self.units != "relative" or self.pixel_spacing is not None:
            raise ValueError("Uncalibrated patches must remain relative; no metric pixel spacing.")
        return self


class Atlas(Record):
    name: str
    source_ids: list[str]
    islands: list[dict]
    links: list[dict]
    rejected_frames: list[dict] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)
    mode: str = "planar appearance atlas"
    measurement_scope: str = "calibrated source patches only"


class MaterialAsset(Record):
    name: str
    patch_id: str
    region: str = "custom"
    synthetic: bool = False
    state: str = "uncalibrated"
    directory: str = ""
    settings: dict = Field(default_factory=dict)
    maps: dict = Field(default_factory=dict)
    descriptor: dict = Field(default_factory=dict)
    provenance: list[dict] = Field(default_factory=list)


class PrinterProfile(Record):
    name: str
    process: Literal["FDM", "resin"]
    build_volume_mm: tuple[float, float, float]
    layer_height_mm: float = Field(gt=0)
    lateral_limit_mm: float = Field(gt=0)
    min_raised_line_mm: float = Field(gt=0)
    min_groove_mm: float = Field(gt=0)
    min_wall_mm: float = Field(gt=0)
    source_notes: str = Field(min_length=1)
    orientation_notes: str = "Texture facing upwards; keep supports off the texture where practical."
    support_settings: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def volume_positive(self):
        if min(self.build_volume_mm) <= 0:
            raise ValueError("Printer build dimensions must be positive.")
        return self


class MeshValidationReport(Record):
    checks: dict = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    dimensions_mm: list[float] = Field(default_factory=list)
    volume_mm3: float | None = None
    triangles: int = 0
    components: int = 0
    geometry_valid: bool = False
    print_ready: bool = False
    fidelity: dict = Field(default_factory=dict)
    printer_assessment: dict = Field(default_factory=dict)
    slicing: str = "unverified"
    physical_printing: str = "unverified"


class PrintProject(Record):
    name: str
    source_id: str
    source_kind: Literal["patch", "mesh"] = "patch"
    directory: str = ""
    settings: dict = Field(default_factory=dict)
    transforms: dict = Field(default_factory=dict)
    repairs: list[dict] = Field(default_factory=list)
    printer: PrinterProfile | None = None
    report: MeshValidationReport | None = None
    exports: dict = Field(default_factory=dict)


class ExportManifest(Record):
    schema_version: str = "material-studio/1"
    kind: str
    selected_ids: list[str]
    files: dict = Field(default_factory=dict)
    raw_captures_included: bool = False
    notes: list[str] = Field(default_factory=list)


class Specimen(Record):
    slug: str
    accession: str
    title: str
    category: str = "other"
    tags: list[str] = Field(default_factory=list)
    body_region: str | None = None
    common_name: str | None = None
    scientific_name: str | None = None
    collection_timestamp: str | None = None
    public_location: str | None = None
    notes: str = ""
    source_id: str
    source_kind: Literal["patch", "frame"] = "patch"
    atlas_id: str | None = None
    calibration_status: str = "uncalibrated"
    source_dimensions_mm: tuple[float, float] | None = None
    synthetic: bool = False
    state: Literal["draft", "published", "archived"] = "draft"
    impression_ids: list[str] = Field(default_factory=list)
    cover_id: str | None = None
    material_id: str | None = None
    print_project_id: str | None = None
    related_ids: list[str] = Field(default_factory=list)
    public_assets: list[str] = Field(default_factory=lambda: ["impression"])
    downloads: list[str] = Field(default_factory=list)
    license: str = "All rights reserved"
    attribution: str = ""
    fabrication_status: Literal["not recorded", "model only", "owner reports printed"] = "model only"
    published_revision: str | None = None
    updated_at: str = Field(default_factory=now)


class ImpressionVariant(Record):
    specimen_id: str
    source_id: str
    source_version: str
    source_sha256: str
    settings: dict
    seed: int = 7
    pixel_size: tuple[int, int]
    print_size_mm: tuple[float, float]
    reproduction_magnification: float | None = None
    source_dimensions_mm: tuple[float, float] | None = None
    palette: dict
    directory: str
    thumbnail: str = "thumbnail.webp"
    exports: dict = Field(default_factory=dict)
    interpretation: str = "height-based artistic ink coverage; not measured ink physics"
