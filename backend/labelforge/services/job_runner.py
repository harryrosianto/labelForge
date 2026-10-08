"""Kerangka eksekusi job generik (import, versi, video, RTSP, autolabel).

Setiap tipe job mendaftarkan handler dengan `@register_job_handler(JobType.X)`. Handler
menerima `JobContext` untuk melaporkan progress per item, memeriksa pembatalan, dan
mengembalikan ringkasan hasil (disimpan di `labeling_jobs.result`). Celery task maupun test
memanggil `run_job(job_id, ...)`, jadi logika job tidak bergantung pada Celery.
"""

import importlib
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from labelforge.models import LabelingJob, LabelingJobItem
from labelforge.models.enums import JobItemStatus, JobStatus, JobType
from labelforge.storage import StorageBackend

log = logging.getLogger(__name__)

# Queue Celery per tipe job: model AI di `inference`, pekerjaan I/O di `io`.
JOB_QUEUES: dict[str, str] = {JobType.AUTOLABEL: "inference"}
DEFAULT_QUEUE = "io"

# Modul yang mendaftarkan handler; ditambah seiring tipe job baru.
HANDLER_MODULES: list[str] = ["labelforge.services.jobs"]


def queue_for(job_type: str) -> str:
    return JOB_QUEUES.get(job_type, DEFAULT_QUEUE)


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, job_id: int, session_factory: sessionmaker[Session], storage: StorageBackend):
        self.job_id = job_id
        self.session_factory = session_factory
        self.storage = storage
        with session_factory() as db:
            job = db.get(LabelingJob, job_id)
            self.project_id = job.project_id
            self.payload: dict[str, Any] = dict(job.payload or {})

    def set_total(self, total: int) -> None:
        with self.session_factory() as db:
            db.execute(update(LabelingJob).where(LabelingJob.id == self.job_id).values(total=total))
            db.commit()

    def check_cancel(self) -> None:
        with self.session_factory() as db:
            if db.get(LabelingJob, self.job_id).cancel_requested:
                raise JobCancelled()

    def warn(self, message: str) -> None:
        with self.session_factory() as db:
            job = db.get(LabelingJob, self.job_id)
            job.warnings = [*(job.warnings or []), message]
            db.commit()

    def record(
        self,
        *,
        label: str | None = None,
        image_id: int | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
        count: int | None = None,
    ) -> None:
        """Catat satu item selesai (atau gagal bila `error` diisi) dan majukan progress."""
        with self.session_factory() as db:
            db.add(LabelingJobItem(
                job_id=self.job_id, image_id=image_id, label=label,
                status=JobItemStatus.ERROR if error else JobItemStatus.DONE,
                error=error, duration_ms=duration_ms, num_detections=count,
            ))  # fmt: skip
            db.execute(
                update(LabelingJob)
                .where(LabelingJob.id == self.job_id)
                .values(processed=LabelingJob.processed + 1,
                        failed_count=LabelingJob.failed_count + int(error is not None))
            )  # fmt: skip
            db.commit()


JobHandler = Callable[[JobContext], dict | None]
_HANDLERS: dict[str, JobHandler] = {}
_modules_loaded = False


def register_job_handler(job_type: str) -> Callable[[JobHandler], JobHandler]:
    def decorator(fn: JobHandler) -> JobHandler:
        _HANDLERS[job_type] = fn
        return fn

    return decorator


def get_job_handler(job_type: str) -> JobHandler:
    global _modules_loaded
    if not _modules_loaded:
        for module in HANDLER_MODULES:
            importlib.import_module(module)
        _modules_loaded = True
    try:
        return _HANDLERS[job_type]
    except KeyError:
        raise ValueError(f"Tidak ada handler untuk job tipe '{job_type}'")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _finish(session_factory, job_id: int, **values) -> str:
    with session_factory() as db:
        job = db.get(LabelingJob, job_id)
        for k, v in values.items():
            setattr(job, k, v)
        job.finished_at = _now()
        db.commit()
        return job.status


def run_job(job_id: int, session_factory: sessionmaker[Session], storage: StorageBackend) -> str:
    """Jalankan job sesuai tipenya. Error di handler menandai job `failed` (bukan crash worker)."""
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
        job_type = job.job_type
        job.status = JobStatus.RUNNING
        job.started_at = job.started_at or _now()
        db.commit()

    handler = get_job_handler(job_type)
    if getattr(handler, "manages_status", False):
        # Handler lama (autolabel) mengatur status job sendiri.
        return handler(job_id, session_factory, storage)

    start = time.perf_counter()
    try:
        result = handler(JobContext(job_id, session_factory, storage)) or {}
    except JobCancelled:
        return _finish(session_factory, job_id, status=JobStatus.CANCELLED)
    except Exception as e:
        log.exception("Job %s (%s) gagal", job_id, job_type)
        return _finish(session_factory, job_id, status=JobStatus.FAILED,
                       error=f"{type(e).__name__}: {e}")  # fmt: skip

    result.setdefault("duration_s", round(time.perf_counter() - start, 2))
    with session_factory() as db:
        job = db.get(LabelingJob, job_id)
        all_failed = job.total > 0 and job.failed_count == job.total
    return _finish(
        session_factory, job_id, result=result,
        status=JobStatus.FAILED if all_failed else JobStatus.COMPLETED,
        error="Semua item gagal diproses" if all_failed else None,
    )  # fmt: skip


def create_job(
    db: Session, project_id: int, job_type: str, payload: dict | None = None, total: int = 0
) -> LabelingJob:
    """Buat job non-autolabel berstatus queued. Caller yang commit lalu enqueue."""
    job = LabelingJob(project_id=project_id, job_type=job_type, payload=payload or {},
                      status=JobStatus.QUEUED, total=total, params={}, warnings=[])  # fmt: skip
    db.add(job)
    db.flush()
    return job
