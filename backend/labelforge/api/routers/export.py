import os
import re
import tempfile
import zipfile
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from starlette.background import BackgroundTask

from labelforge.api.deps import DbSession, Storage, get_project_or_404
from labelforge.exporters.base import ExportOptions, collect_dataset
from labelforge.exporters.coco import write_coco
from labelforge.exporters.yolo import write_yolo

router = APIRouter(tags=["export"])
WRITERS = {"yolo": write_yolo, "coco": write_coco}


class SplitRatio(BaseModel):
    train: float = Field(0.8, ge=0, le=1)
    val: float = Field(0.2, ge=0, le=1)
    test: float = Field(0.0, ge=0, le=1)

    @model_validator(mode="after")
    def _positive(self):
        if self.train + self.val + self.test <= 0:
            raise ValueError("Total rasio split harus > 0")
        if self.train <= 0:
            raise ValueError("Split train harus > 0")
        return self


class ExportRequest(BaseModel):
    format: Literal["yolo", "coco"] = "yolo"
    reviewed_only: bool = True
    split: SplitRatio = SplitRatio()
    seed: int = 42

    def options(self) -> ExportOptions:
        return ExportOptions(self.format, self.reviewed_only, self.split.model_dump(), self.seed)


@router.post("/projects/{project_id}/export/preview")
def preview_export(project_id: int, body: ExportRequest, db: DbSession):
    """Ringkasan isi export (jumlah gambar per split, box per class) tanpa membuat file."""
    get_project_or_404(db, project_id)
    return collect_dataset(db, project_id, body.options()).summary()


@router.post("/projects/{project_id}/export")
def export_dataset(project_id: int, body: ExportRequest, db: DbSession, storage: Storage):
    """Buat ZIP dataset (YOLO atau COCO) dan kirim sebagai download."""
    get_project_or_404(db, project_id)
    dataset = collect_dataset(db, project_id, body.options())
    if dataset.num_images == 0:
        msg = "Belum ada gambar reviewed" if body.reviewed_only else "Belum ada gambar berlabel"
        raise HTTPException(422, f"{msg} untuk diekspor")

    fd, tmp_path = tempfile.mkstemp(prefix="labelforge-export-", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w") as zf:
            WRITERS[body.format](dataset, storage, zf)
    except Exception:
        os.unlink(tmp_path)
        raise

    slug = re.sub(r"[^a-z0-9]+", "-", dataset.project.name.lower()).strip("-") or "dataset"
    filename = f"{slug}_{body.format}_{datetime.now():%Y%m%d-%H%M}.zip"
    return FileResponse(tmp_path, media_type="application/zip", filename=filename,
                        background=BackgroundTask(os.unlink, tmp_path))  # fmt: skip
