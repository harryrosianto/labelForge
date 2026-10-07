"""Pembuatan & eksekusi job auto-label. Eksekusi tidak bergantung Celery supaya bisa dites."""

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from labelforge.config import get_settings
from labelforge.models import ClassExemplar, Image, LabelClass, LabelingJob, LabelingJobItem
from labelforge.models.enums import ImageStatus, JobItemStatus, JobStatus, JobTarget, JobType
from labelforge.providers.base import ClassDef, ProviderError
from labelforge.providers.registry import get_provider, get_provider_class
from labelforge.services.annotations import apply_ai_detections
from labelforge.storage import StorageBackend

log = logging.getLogger(__name__)


class JobRequestError(ValueError):
    """Permintaan job tidak valid (pesan aman untuk ditampilkan ke user)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def build_class_defs(db: Session, storage: StorageBackend, project_id: int) -> list[ClassDef]:
    classes = db.scalars(
        select(LabelClass).where(LabelClass.project_id == project_id).order_by(LabelClass.order_index)
    ).all()
    exemplars: dict[int, list[Path]] = {}
    for ex in db.scalars(
        select(ClassExemplar)
        .where(ClassExemplar.class_id.in_([c.id for c in classes]))
        .order_by(ClassExemplar.id)
    ):
        path = storage.local_file_for_response(ex.crop_storage_key)
        if path is not None:
            exemplars.setdefault(ex.class_id, []).append(path)
    return [ClassDef(c.id, c.name, c.text_prompt, tuple(exemplars.get(c.id, ()))) for c in classes]


def select_target_images(
    db: Session, project_id: int, target: str, image_ids: list[int] | None, include_reviewed: bool
) -> list[int]:
    query = select(Image.id).where(Image.project_id == project_id).order_by(Image.id)
    if target == JobTarget.UNLABELED:
        query = query.where(Image.status == ImageStatus.UNLABELED)
    elif target == JobTarget.SELECTED:
        if not image_ids:
            raise JobRequestError("Pilih minimal satu gambar")
        # Gambar terpilih diproses apa pun statusnya karena user memilihnya secara eksplisit.
        query = query.where(Image.id.in_(image_ids))
    elif not include_reviewed:
        query = query.where(Image.status != ImageStatus.REVIEWED)
    return list(db.scalars(query))


def create_autolabel_job(
    db: Session,
    storage: StorageBackend,
    project_id: int,
    *,
    provider: str | None,
    params: dict,
    target: str,
    image_ids: list[int] | None = None,
    include_reviewed: bool = False,
) -> LabelingJob:
    """Validasi permintaan dan buat job + item (status queued). Caller yang enqueue & commit."""
    settings = get_settings()
    provider = provider or settings.default_provider
    params = dict(params or {})
    if provider == settings.default_provider and not params.get("mode"):
        params["mode"] = settings.default_mode
    try:
        provider_cls = get_provider_class(provider)
        available, reason = provider_cls.is_available()
        if not available:
            raise JobRequestError(f"Provider '{provider}' tidak tersedia: {reason}")
        resolved = provider_cls.resolve_params(params)
    except ProviderError as e:
        raise JobRequestError(str(e)) from e

    classes = build_class_defs(db, storage, project_id)
    if not classes:
        raise JobRequestError("Project belum punya class")
    warnings = provider_cls.class_warnings(resolved["mode"], classes)
    if len(warnings) == len(classes) and warnings:
        raise JobRequestError("Tidak ada class yang bisa diproses: " + "; ".join(warnings))

    ids = select_target_images(db, project_id, target, image_ids, include_reviewed)
    if not ids:
        raise JobRequestError("Tidak ada gambar yang cocok dengan target job")

    job = LabelingJob(
        project_id=project_id,
        job_type=JobType.AUTOLABEL,
        provider=provider,
        mode=resolved.pop("mode"),
        params=resolved,
        target=target,
        image_ids=image_ids if target == JobTarget.SELECTED else None,
        include_reviewed=include_reviewed,
        status=JobStatus.QUEUED,
        total=len(ids),
        warnings=warnings,
    )
    db.add(job)
    db.flush()
    db.add_all(LabelingJobItem(job_id=job.id, image_id=i) for i in ids)
    db.flush()
    return job


def run_autolabel_job(
    job_id: int,
    session_factory: sessionmaker[Session],
    storage: StorageBackend,
    on_progress: Callable[[LabelingJob], None] | None = None,
) -> str:
    """Proses semua item `pending` dari job. Aman dijalankan ulang (mis. setelah worker restart):
    item yang sudah selesai dilewati. Error satu gambar tidak menghentikan job."""
    with session_factory() as db:
        job = db.get(LabelingJob, job_id)
        if job is None:
            log.warning("Job %s tidak ditemukan", job_id)
            return "missing"
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return job.status
        if job.cancel_requested:
            job.status, job.finished_at = JobStatus.CANCELLED, _now()
            db.commit()
            return job.status

        job.status = JobStatus.RUNNING
        job.started_at = job.started_at or _now()
        db.commit()

        try:
            provider = get_provider(job.provider)
            provider.load()
        except Exception as e:  # konfigurasi/dependency/model gagal → seluruh job gagal
            log.exception("Gagal memuat provider %s", job.provider)
            job.status, job.error, job.finished_at = JobStatus.FAILED, str(e), _now()
            db.commit()
            return job.status

        classes = build_class_defs(db, storage, job.project_id)
        params = {**job.params, "mode": job.mode}
        source = provider.source_tag(job.mode)
        item_ids = list(
            db.scalars(
                select(LabelingJobItem.id)
                .where(LabelingJobItem.job_id == job_id,
                       LabelingJobItem.status == JobItemStatus.PENDING)
                .order_by(LabelingJobItem.id)
            )
        )  # fmt: skip

    for item_id in item_ids:
        with session_factory() as db:
            job = db.get(LabelingJob, job_id)
            if job.cancel_requested:
                job.status, job.finished_at = JobStatus.CANCELLED, _now()
                db.commit()
                return job.status

            item = db.get(LabelingJobItem, item_id)
            image = db.get(Image, item.image_id)
            start = time.perf_counter()
            try:
                if image is None:
                    raise FileNotFoundError("Gambar sudah dihapus")
                with storage.local_path(image.storage_key) as path:
                    result = provider.detect_with_info(path, classes, params)
                item.num_detections = apply_ai_detections(
                    db, image, result.detections, source, job_id
                )
                item.status = JobItemStatus.DONE
            except Exception as e:
                db.rollback()
                item = db.get(LabelingJobItem, item_id)
                item.status, item.error = JobItemStatus.ERROR, f"{type(e).__name__}: {e}"
                log.warning("Job %s gambar %s gagal: %s", job_id, item.image_id, item.error)
            item.duration_ms = int((time.perf_counter() - start) * 1000)

            # Update counter secara atomik (API bisa membaca job bersamaan).
            failed = int(item.status == JobItemStatus.ERROR)
            db.execute(
                update(LabelingJob)
                .where(LabelingJob.id == job_id)
                .values(processed=LabelingJob.processed + 1,
                        failed_count=LabelingJob.failed_count + failed)
            )  # fmt: skip
            db.commit()
            if on_progress:
                on_progress(db.get(LabelingJob, job_id))

    with session_factory() as db:
        job = db.get(LabelingJob, job_id)
        job.status = JobStatus.COMPLETED
        job.finished_at = _now()
        if job.total and job.failed_count == job.total:
            job.status, job.error = JobStatus.FAILED, "Semua gambar gagal diproses"
        db.commit()
        return job.status
