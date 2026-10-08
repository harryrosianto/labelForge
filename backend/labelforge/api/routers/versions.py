import os
import re
import tempfile
import zipfile
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from starlette.background import BackgroundTask

from labelforge.api.deps import DbSession, Storage, get_project_or_404
from labelforge.api.routers.export import WRITERS
from labelforge.api.routers.jobs import Queue
from labelforge.models import DatasetVersion
from labelforge.models.enums import JobStatus, JobType, VersionStatus
from labelforge.services.job_runner import create_job
from labelforge.storage import project_prefix
from labelforge.versions.builder import VersionCreate, VersionSettings, create_version, plan_items, summarize
from labelforge.versions.export import compare_versions, version_dataset

router = APIRouter(tags=["versions"])


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    notes: str | None
    status: str
    config: dict[str, Any]
    summary: dict[str, Any] | None
    image_count: int
    job_id: int | None
    created_at: datetime
    updated_at: datetime


class VersionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)


class VersionExport(BaseModel):
    format: Literal["yolo", "coco"] = "yolo"


def _get_version(db: DbSession, version_id: int) -> DatasetVersion:
    version = db.get(DatasetVersion, version_id)
    if version is None:
        raise HTTPException(404, f"Versi {version_id} tidak ditemukan")
    return version


@router.get("/projects/{project_id}/versions", response_model=list[VersionOut])
def list_versions(project_id: int, db: DbSession):
    get_project_or_404(db, project_id)
    return db.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.project_id == project_id)
        .order_by(DatasetVersion.id.desc())
    ).all()


@router.post("/projects/{project_id}/versions/preview")
def preview_version(project_id: int, body: VersionSettings, db: DbSession):
    """Ringkasan isi versi dengan pengaturan ini, tanpa membuat apa pun."""
    get_project_or_404(db, project_id)
    classes, items = plan_items(db, project_id, body)
    return summarize([c.name for c in classes], items)


@router.post(
    "/projects/{project_id}/versions", response_model=VersionOut, status_code=status.HTTP_201_CREATED
)
def create_version_endpoint(project_id: int, body: VersionCreate, db: DbSession, queue: Queue):
    get_project_or_404(db, project_id)
    try:
        version, needs_job = create_version(db, project_id, body)
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    if needs_job:
        job = create_job(db, project_id, JobType.VERSION_BUILD, {"version_id": version.id})
        version.job_id = job.id
    db.commit()
    if needs_job:
        try:
            job.celery_task_id = queue.enqueue(JobType.VERSION_BUILD, job.id)
        except Exception as e:
            job.status, job.error = JobStatus.FAILED, f"Gagal mengirim job ke antrian: {e}"
            version.status = VersionStatus.FAILED
        db.commit()
    db.refresh(version)
    return version


@router.get("/versions/compare")
def compare(db: DbSession, a: int = Query(...), b: int = Query(...)):
    va, vb = _get_version(db, a), _get_version(db, b)
    if va.project_id != vb.project_id:
        raise HTTPException(422, "Kedua versi harus dari project yang sama")
    return compare_versions(db, va, vb)


@router.get("/versions/{version_id}", response_model=VersionOut)
def get_version(version_id: int, db: DbSession):
    return _get_version(db, version_id)


@router.patch("/versions/{version_id}", response_model=VersionOut)
def update_version(version_id: int, body: VersionUpdate, db: DbSession):
    """Hanya nama & catatan yang bisa diubah; isi versi tidak bisa diubah."""
    version = _get_version(db, version_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        name = " ".join(data["name"].split())
        if not name:
            raise HTTPException(422, "Nama versi tidak boleh kosong")
        version.name = name
    if "notes" in data:
        version.notes = data["notes"]
    db.commit()
    return version


@router.delete("/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_version(version_id: int, db: DbSession, storage: Storage):
    version = _get_version(db, version_id)
    if version.status == VersionStatus.BUILDING:
        raise HTTPException(409, "Versi sedang dibuat; batalkan job-nya dulu")
    prefix = f"{project_prefix(version.project_id)}/versions/{version.id}"
    db.delete(version)
    db.commit()
    storage.delete_prefix(prefix)


@router.post("/versions/{version_id}/export")
def export_version(version_id: int, body: VersionExport, db: DbSession, storage: Storage):
    """ZIP dataset dari versi. Isi & byte ZIP sama setiap kali diunduh."""
    version = _get_version(db, version_id)
    if version.status != VersionStatus.READY:
        raise HTTPException(409, f"Versi berstatus {version.status}, belum bisa diekspor")
    dataset = version_dataset(db, version, body.format)

    fd, tmp_path = tempfile.mkstemp(prefix="labelforge-version-", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w") as zf:
            WRITERS[body.format](dataset, storage, zf)
    except Exception:
        os.unlink(tmp_path)
        raise
    slug = re.sub(r"[^a-z0-9]+", "-", f"{dataset.project.name}-{version.name}".lower()).strip("-")
    return FileResponse(tmp_path, media_type="application/zip", filename=f"{slug}_{body.format}.zip",
                        background=BackgroundTask(os.unlink, tmp_path))  # fmt: skip
