"""Job export dataset (queue `io`): ZIP ditulis worker lalu diunduh lewat link biasa.

Export besar (ribuan gambar, gigabyte) tidak lagi berjalan di dalam satu request HTTP dan
tidak ditampung di memori browser.
"""

import os
import re
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from labelforge.exporters.base import ExportOptions, collect_dataset
from labelforge.exporters.coco import write_coco
from labelforge.exporters.yolo import write_yolo
from labelforge.models import DatasetVersion, LabelingJob, Project
from labelforge.models.enums import JobStatus, JobType, VersionStatus
from labelforge.services.job_runner import JobContext, register_job_handler
from labelforge.storage import StorageBackend, project_prefix
from labelforge.versions.export import version_dataset

WRITERS = {"yolo": write_yolo, "coco": write_coco}
RETENTION = timedelta(days=7)
PROGRESS_EVERY = 25  # gambar per update progress (hemat tulis DB)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "dataset"


def cleanup_old_exports(session_factory, storage: StorageBackend, project_id: int) -> int:
    """Hapus file export project yang lebih tua dari RETENTION. Mengembalikan jumlah file."""
    cutoff = datetime.now(timezone.utc) - RETENTION
    removed = 0
    with session_factory() as db:
        jobs = db.scalars(select(LabelingJob).where(
            LabelingJob.project_id == project_id, LabelingJob.job_type == JobType.EXPORT,
            LabelingJob.status == JobStatus.COMPLETED,
        ))  # fmt: skip
        for job in jobs:
            result = dict(job.result or {})
            finished = job.finished_at
            if finished is not None and finished.tzinfo is None:
                finished = finished.replace(tzinfo=timezone.utc)
            if result.get("file") and not result.get("expired") and finished and finished < cutoff:
                storage.delete(result["file"])
                job.result = {**result, "expired": True}
                removed += 1
        db.commit()
    return removed


@register_job_handler(JobType.EXPORT)
def run_export(ctx: JobContext) -> dict:
    payload = ctx.payload
    fmt = payload["format"]
    cleanup_old_exports(ctx.session_factory, ctx.storage, ctx.project_id)

    with ctx.session_factory() as db:
        if payload.get("version_id"):
            version = db.get(DatasetVersion, int(payload["version_id"]))
            if version is None or version.status != VersionStatus.READY:
                raise ValueError("Versi tidak ada atau belum siap")
            dataset = version_dataset(db, version, fmt)
            name = f"{_slug(dataset.project.name)}-{_slug(version.name)}_{fmt}.zip"
        else:
            options = ExportOptions(format=fmt, reviewed_only=payload["reviewed_only"],
                                    split=payload["split"], seed=payload["seed"])  # fmt: skip
            dataset = collect_dataset(db, ctx.project_id, options)
            project = db.get(Project, ctx.project_id)
            name = f"{_slug(project.name)}_{fmt}_{datetime.now():%Y%m%d-%H%M}.zip"
    if dataset.num_images == 0:
        raise ValueError("Tidak ada gambar untuk diekspor")
    ctx.set_total(dataset.num_images)

    done = [0]

    def on_image() -> None:
        done[0] += 1
        if done[0] % PROGRESS_EVERY == 0:
            ctx.check_cancel()
            ctx.advance(PROGRESS_EVERY)

    fd, tmp_path = tempfile.mkstemp(prefix="labelforge-export-", suffix=".zip")
    os.close(fd)
    key = f"{project_prefix(ctx.project_id)}/exports/{ctx.job_id}_{name}"
    try:
        with zipfile.ZipFile(tmp_path, "w") as zf:
            WRITERS[fmt](dataset, ctx.storage, zf, on_image)
        with open(tmp_path, "rb") as f:
            size = ctx.storage.save_file(key, f)
    finally:
        os.unlink(tmp_path)
    ctx.advance(done[0] % PROGRESS_EVERY)
    return {"file": key, "filename": name, "size_bytes": size, "images": dataset.num_images,
            "format": fmt}  # fmt: skip
