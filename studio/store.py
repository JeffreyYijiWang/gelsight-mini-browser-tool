from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import numpy as np

from .records import Record, SurfacePatch, uid


class Store:
    """Append-only source/derived objects; atomic JSON index records."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        for name in ("records", "raw", "arrays", "materials", "prints", "exports", "jobs", "atlases"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Path is outside the project store.")
        return path

    def save(self, kind: str, record: Record | dict) -> dict:
        data = record.model_dump(mode="json") if isinstance(record, Record) else record
        self._id(data["id"])
        folder = self.path("records/" + kind)
        folder.mkdir(exist_ok=True)
        target = folder / (data["id"] + ".json")
        temp = target.with_suffix("." + uid() + ".tmp")
        temp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temp, target)
        return data

    @staticmethod
    def _id(value: str):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value):
            raise ValueError("Invalid record ID.")

    def get(self, kind: str, record_id: str) -> dict:
        self._id(record_id)
        file = self.path(f"records/{kind}/{record_id}.json")
        if not file.exists():
            raise ValueError(f"{kind} record {record_id} was not found.")
        return json.loads(file.read_text(encoding="utf-8"))

    def list(self, kind: str) -> list[dict]:
        records=[json.loads(p.read_text(encoding="utf-8")) for p in self.path("records/" + kind).glob("*.json")]
        return sorted(records,key=lambda record:(record.get('created_at',''),record['id']))

    def raw(self, data: bytes, suffix: str) -> tuple[str, str]:
        digest = hashlib.sha256(data).hexdigest()
        suffix = re.sub(r"[^a-z0-9.]", "", suffix.lower())[:16]
        relative = f"raw/{digest}{suffix}"
        path = self.path(relative)
        if not path.exists():
            with path.open("xb") as out:
                out.write(data)
        return relative, digest

    def put_patch(self, patch: SurfacePatch, height: np.ndarray, mask: np.ndarray | None = None,
                  synthetic_mask: np.ndarray | None = None, **extras) -> dict:
        height = np.asarray(height, dtype=np.float32)
        if height.ndim != 2 or min(height.shape) < 2 or height.size > 4_000_000:
            raise ValueError("Height must be a 2D array, at least 2×2 and at most 4 million samples.")
        mask = np.isfinite(height) if mask is None else np.asarray(mask, bool) & np.isfinite(height)
        if mask.shape != height.shape or mask.sum() < 4:
            raise ValueError("Height mask must match the height field and contain at least four valid samples.")
        invented = np.zeros_like(mask) if synthetic_mask is None else np.asarray(synthetic_mask, bool)
        if invented.shape != height.shape:
            raise ValueError("Synthetic mask shape mismatch.")
        patch.width, patch.height = height.shape[1], height.shape[0]
        patch.arrays = f"arrays/{patch.id}.npz"
        np.savez_compressed(self.path(patch.arrays), height=np.where(mask, height, 0), mask=mask,
                            synthetic_mask=invented, **extras)
        return self.save("patches", patch)

    def patch(self, patch_id: str) -> tuple[SurfacePatch, dict[str, np.ndarray]]:
        patch = SurfacePatch(**self.get("patches", patch_id))
        with np.load(self.path(patch.arrays), allow_pickle=False) as data:
            arrays = {key: data[key] for key in data.files}
        return patch, arrays
