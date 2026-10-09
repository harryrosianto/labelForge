import uuid
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from labelforge.api.deps import DbSession, Storage, get_project_or_404
from labelforge.api.routers.jobs import Queue
from labelforge.importers.apply import ClassMapping, MappingError, resolve_mapping, suggest_mapping
from labelforge.importers.base import DatasetReadError, ZipSource
from labelforge.importers.detect import parse_dataset
from labelforge.models import DatasetImport, LabelClass
from labelforge.models.enums import ImportStatus, JobStatus, JobType
from labelforge.services.job_runner import create_job
from labelforge.storage import project_prefix

router = APIRouter(tags=["imports"])


class ImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    original_filename: str
    format: str | None
    status: str
    error: str | None
    analysis: dict[str, Any] | None
    job_id: int | None
    created_at: datetime


class ImportStart(BaseModel):
    mapping: dict[str, ClassMapping]
    mark_for_review: bool = False


def _get_import(db: DbSession, import_id: int) -> DatasetImport:
    imp = db.get(DatasetImport, import_id)
    if imp is None:
        raise HTTPException(404, f"Import {import_id} tidak ditemukan")
    return imp


@router.post(
    "/projects/{project_id}/imports", response_model=ImportOut, status_code=status.HTTP_201_CREATED
)
def upload_import(
    project_id: int, db: DbSession, storage: Storage, file: Annotated[UploadFile, File()]
):
    """Unggah ZIP dataset YOLO/COCO lalu analisis (tanpa mengubah project)."""
    get_project_or_404(db, project_id)
    name = PurePosixPath(file.filename or "dataset.zip").name
    if not name.lower().endswith(".zip"):
        raise HTTPException(422, "Dataset harus berupa file ZIP")
    key = f"{project_prefix(project_id)}/imports/{uuid.uuid4().hex}.zip"
    storage.save_file(key, file.file)

    try:
        with storage.local_path(key) as path:
            source = ZipSource(path)
            try:
                parsed = parse_dataset(source)
            finally:
                source.close()
    except DatasetReadError as e:
        storage.delete(key)
        raise HTTPException(422, str(e))

    existing = list(db.scalars(select(LabelClass).where(LabelClass.project_id == project_id)))
    analysis = parsed.analysis()
    analysis["suggested_mapping"] = suggest_mapping(parsed.class_names, existing)
    imp = DatasetImport(project_id=project_id, original_filename=name, storage_key=key,
                        format=parsed.format, analysis=analysis, status=ImportStatus.ANALYZED)  # fmt: skip
    db.add(imp)
    db.commit()
    return imp


@router.get("/projects/{project_id}/imports", response_model=list[ImportOut])
def list_imports(project_id: int, db: DbSession):
    get_project_or_404(db, project_id)
    return db.scalars(
        select(DatasetImport)
        .where(DatasetImport.project_id == project_id)
        .order_by(DatasetImport.id.desc())
    ).all()


@router.get("/imports/{import_id}", response_model=ImportOut)
def get_import(import_id: int, db: DbSession):
    return _get_import(db, import_id)


@router.post("/imports/{import_id}/start", response_model=ImportOut)
def start_import(import_id: int, body: ImportStart, db: DbSession, queue: Queue):
    """Terapkan pemetaan class (class baru langsung dibuat) lalu jalankan job import."""
    imp = _get_import(db, import_id)
    if imp.status != ImportStatus.ANALYZED:
        raise HTTPException(409, f"Import berstatus {imp.status}, tidak bisa dimulai")
    class_names = [c["name"] for c in (imp.analysis or {}).get("classes", [])]
    try:
        class_ids, created = resolve_mapping(db, imp.project_id, class_names, body.mapping)
    except MappingError as e:
        db.rollback()
        raise HTTPException(422, str(e))

    job = create_job(db, imp.project_id, JobType.IMPORT, {
        "import_id": imp.id, "class_ids": class_ids,
        "mark_for_review": body.mark_for_review, "classes_created": created,
    })  # fmt: skip
    imp.status, imp.job_id, imp.error = ImportStatus.IMPORTING, job.id, None
    db.commit()
    try:
        job.celery_task_id = queue.enqueue(JobType.IMPORT, job.id)
    except Exception as e:
        job.status, job.error = JobStatus.FAILED, f"Gagal mengirim job ke antrian: {e}"
        imp.status = ImportStatus.ANALYZED
    db.commit()
    db.refresh(imp)
    return imp


@router.delete("/imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_import(import_id: int, db: DbSession, storage: Storage):
    """Buang import yang belum/selesai diproses beserta file ZIP-nya."""
    imp = _get_import(db, import_id)
    if imp.status == ImportStatus.IMPORTING:
        raise HTTPException(409, "Import sedang berjalan; batalkan job-nya dulu")
    key = imp.storage_key
    db.delete(imp)
    db.commit()
    storage.delete(key)
