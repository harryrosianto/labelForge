from labelforge.db import get_session_factory
from labelforge.services.job_runner import run_job
from labelforge.storage import get_storage
from labelforge.worker.celery_app import celery_app


@celery_app.task(name="labelforge.run_job")
def run_job_task(job_id: int) -> str:
    """Satu task untuk semua tipe job; queue (`inference`/`io`) dipilih saat enqueue."""
    return run_job(job_id, get_session_factory(), get_storage())


@celery_app.task(name="labelforge.autolabel")
def autolabel(job_id: int) -> str:
    # Nama lama, dipertahankan agar pesan yang masih antre dari versi sebelumnya tetap diproses.
    return run_job(job_id, get_session_factory(), get_storage())
