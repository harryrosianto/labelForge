from labelforge.db import get_session_factory
from labelforge.services.jobs import run_autolabel_job
from labelforge.storage import get_storage
from labelforge.worker.celery_app import celery_app


@celery_app.task(name="labelforge.autolabel")
def autolabel(job_id: int) -> str:
    return run_autolabel_job(job_id, get_session_factory(), get_storage())
