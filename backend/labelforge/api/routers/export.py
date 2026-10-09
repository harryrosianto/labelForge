import os
import re
import tempfile
import zipfile
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from starlette.background import BackgroundTask

from labelforge.api.deps import DbSession, Storage, get_project_or_404
from labelforge.api.routers.jobs import Queue
from labelforge.exporters.base import ExportOptions, collect_dataset
from labelforge.exporters.coco import write_coco
from labelforge.exporters.yolo import write_yolo
from labelforge.models import LabelingJob
from labelforge.models.enums import JobStatus, JobType
from labelforge.schemas.job import JobOut
from labelforge.services.job_runner import create_job

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


# --- export sebagai job (untuk dataset besar) -------------------------------------


def enqueue_export(db: DbSession, queue: Queue, project_id: int, payload: dict) -> LabelingJob:
    """Buat job export, commit, lalu kirim ke queue `io`. ZIP diunduh lewat /exports/{job_id}/download."""
    job = create_job(db, project_id, JobType.EXPORT, payload)
    db.commit()
    try:
        job.celery_task_id = queue.enqueue(JobType.EXPORT, job.id)
    except Exception as e:
        job.status, job.error = JobStatus.FAILED, f"Gagal mengirim job ke antrian: {e}"
    db.commit()
    db.refresh(job)
    return job


@router.post("/projects/{project_id}/export-jobs", response_model=JobOut,
             status_code=status.HTTP_201_CREATED)  # fmt: skip
def start_export_job(project_id: int, body: ExportRequest, db: DbSession, queue: Queue):
    get_project_or_404(db, project_id)
    return enqueue_export(db, queue, project_id, body.model_dump())


@router.get("/exports/{job_id}/download")
def download_export(job_id: int, db: DbSession, storage: Storage):
    """Unduh ZIP hasil job export (streaming dari disk, mendukung resume)."""
    job = db.get(LabelingJob, job_id)
    if job is None or job.job_type != JobType.EXPORT:
        raise HTTPException(404, "Export tidak ditemukan")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(409, f"Export berstatus {job.status}, belum bisa diunduh")
    result = job.result or {}
    key = result.get("file")
    if not key or result.get("expired") or not storage.exists(key):
        raise HTTPException(410, "File export sudah dihapus; buat export baru")
    path = storage.local_file_for_response(key)
    if path is None:
        raise HTTPException(501, "Storage ini tidak mendukung unduhan langsung")
    return FileResponse(path, media_type="application/zip", filename=result["filename"])
