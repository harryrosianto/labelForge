"""Job worker pembuatan file versi (hasil preprocessing)."""

import io
import time

from PIL import Image as PILImage
from PIL import ImageOps

from labelforge.models import DatasetVersion, Image, LabelingJob
from labelforge.models.enums import JobType, VersionStatus
from labelforge.services.job_runner import JobCancelled, JobContext, register_job_handler
from labelforge.versions.builder import VersionSettings, version_items
from labelforge.versions.preprocess import apply_preprocessing


def _set_status(ctx: JobContext, version_id: int, status: str) -> None:
    with ctx.session_factory() as db:
        version = db.get(DatasetVersion, version_id)
        if version is not None:
            version.status = status
            db.commit()


@register_job_handler(JobType.VERSION_BUILD)
def build_version(ctx: JobContext) -> dict:
    version_id = int(ctx.payload["version_id"])
    with ctx.session_factory() as db:
        version = db.get(DatasetVersion, version_id)
        if version is None:
            raise ValueError(f"Versi {version_id} tidak ditemukan")
        settings = VersionSettings.model_validate(version.config)
        items = [(it.id, it.image_id, it.storage_key) for it in version_items(db, version_id)
                 if it.storage_key]  # fmt: skip
        sources = {i.id: i.storage_key for i in db.query(Image).filter(
            Image.id.in_({image_id for _, image_id, _ in items}))}  # fmt: skip
    ctx.set_total(len(items))

    written = 0
    try:
        for item_id, image_id, key in items:
            ctx.check_cancel()
            start = time.perf_counter()
            if ctx.storage.exists(key):  # job dijalankan ulang: lewati yang sudah ada
                ctx.record(label=key, image_id=image_id)
                continue
            try:
                with ctx.storage.local_path(sources[image_id]) as path, PILImage.open(path) as src:
                    out = apply_preprocessing(ImageOps.exif_transpose(src), settings.preprocessing)
                buf = io.BytesIO()
                out.save(buf, format="JPEG", quality=95)
                ctx.storage.save_bytes(key, buf.getvalue())
                written += 1
                ctx.record(label=key, image_id=image_id,
                           duration_ms=int((time.perf_counter() - start) * 1000))  # fmt: skip
            except Exception as e:
                ctx.record(label=key, image_id=image_id, error=f"{type(e).__name__}: {e}")
    except JobCancelled:
        _set_status(ctx, version_id, VersionStatus.FAILED)
        raise
    except Exception:
        _set_status(ctx, version_id, VersionStatus.FAILED)
        raise

    with ctx.session_factory() as db:
        failed = db.get(LabelingJob, ctx.job_id).failed_count
    # Versi hanya dianggap siap jika semua file berhasil dibuat; sebagian gagal = versi gagal.
    _set_status(ctx, version_id, VersionStatus.FAILED if failed else VersionStatus.READY)
    return {"written": written, "failed": failed}
