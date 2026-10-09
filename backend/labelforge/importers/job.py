"""Job worker untuk import dataset (queue `io`)."""

from labelforge.importers.apply import apply_import
from labelforge.importers.base import ZipSource
from labelforge.importers.detect import parse_dataset
from labelforge.models import DatasetImport
from labelforge.models.enums import ImportStatus, JobType
from labelforge.services.job_runner import JobCancelled, JobContext, register_job_handler


def _set_status(ctx: JobContext, import_id: int, status: str, error: str | None = None) -> None:
    with ctx.session_factory() as db:
        imp = db.get(DatasetImport, import_id)
        if imp is not None:
            imp.status, imp.error = status, error
            db.commit()


@register_job_handler(JobType.IMPORT)
def run_import(ctx: JobContext) -> dict:
    import_id = int(ctx.payload["import_id"])
    class_ids = {k: (int(v) if v is not None else None) for k, v in ctx.payload["class_ids"].items()}
    with ctx.session_factory() as db:
        imp = db.get(DatasetImport, import_id)
        if imp is None:
            raise ValueError(f"Import {import_id} tidak ditemukan")
        storage_key, fmt, label = imp.storage_key, imp.format, imp.original_filename

    try:
        with ctx.storage.local_path(storage_key) as path:
            source = ZipSource(path)
            try:
                parsed = parse_dataset(source, fmt)
                ctx.set_total(len(parsed.images))
                result = apply_import(
                    ctx.session_factory, ctx.storage, ctx.project_id, source, parsed, class_ids,
                    mark_for_review=bool(ctx.payload.get("mark_for_review")),
                    source_label=label, import_id=import_id,
                    on_item=ctx.record, check_cancel=ctx.check_cancel,
                )  # fmt: skip
            finally:
                source.close()
    except JobCancelled:
        # Gambar yang sudah masuk tetap ada; import bisa dimulai lagi (duplikat dilewati).
        _set_status(ctx, import_id, ImportStatus.ANALYZED)
        raise
    except Exception as e:
        _set_status(ctx, import_id, ImportStatus.FAILED, f"{type(e).__name__}: {e}")
        raise

    _set_status(ctx, import_id, ImportStatus.COMPLETED)
    ctx.storage.delete(storage_key)  # ZIP tidak dibutuhkan lagi setelah berhasil
    return result
