from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from labelforge.api.deps import DbSession, Storage, get_project_or_404
from labelforge.models import LabelingJob, LabelingJobItem
from labelforge.models.enums import JobItemStatus, JobStatus
from labelforge.providers.registry import describe_providers
from labelforge.schemas.job import AutolabelJobCreate, JobItemOut, JobOut
from labelforge.services.jobs import JobRequestError, create_autolabel_job
from labelforge.worker.queue import JobQueue, get_job_queue

router = APIRouter(tags=["jobs"])
Queue = Annotated[JobQueue, Depends(get_job_queue)]


def _get_job(db: DbSession, job_id: int) -> LabelingJob:
    job = db.get(LabelingJob, job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id} tidak ditemukan")
    return job


@router.get("/providers")
def list_providers():
    return describe_providers()


@router.post(
    "/projects/{project_id}/jobs/autolabel",
    response_model=JobOut,
    status_code=status.HTTP_201_CREATED,
)
def start_autolabel(
    project_id: int, body: AutolabelJobCreate, db: DbSession, storage: Storage, queue: Queue
):
    get_project_or_404(db, project_id)
    params = dict(body.params)
    if body.mode:
        params["mode"] = body.mode
    try:
        job = create_autolabel_job(
            db, storage, project_id,
            provider=body.provider, params=params, target=body.target,
            image_ids=body.image_ids, include_reviewed=body.include_reviewed,
        )  # fmt: skip
    except JobRequestError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    db.commit()  # job harus sudah tersimpan sebelum worker mengambilnya

    try:
        job.celery_task_id = queue.enqueue_autolabel(job.id)
    except Exception as e:
        job.status, job.error = JobStatus.FAILED, f"Gagal mengirim job ke antrian: {e}"
    db.commit()
    db.refresh(job)  # worker mungkin sudah memperbarui job di sesi lain
    return job


@router.get("/projects/{project_id}/jobs", response_model=list[JobOut])
def list_jobs(project_id: int, db: DbSession, limit: int = Query(50, ge=1, le=500)):
    get_project_or_404(db, project_id)
    return db.scalars(
        select(LabelingJob)
        .where(LabelingJob.project_id == project_id)
        .order_by(LabelingJob.id.desc())
        .limit(limit)
    ).all()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: DbSession):
    return _get_job(db, job_id)


@router.get("/jobs/{job_id}/items", response_model=list[JobItemOut])
def list_job_items(job_id: int, db: DbSession, status: JobItemStatus | None = None):
    _get_job(db, job_id)
    query = select(LabelingJobItem).where(LabelingJobItem.job_id == job_id)
    if status is not None:
        query = query.where(LabelingJobItem.status == status)
    return db.scalars(query.order_by(LabelingJobItem.id)).all()


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int, db: DbSession, queue: Queue):
    job = _get_job(db, job_id)
    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        raise HTTPException(409, f"Job sudah {job.status}")
    # Job yang sedang berjalan berhenti di gambar berikutnya (worker memeriksa flag ini).
    job.cancel_requested = True
    if job.status == JobStatus.QUEUED:
        # Belum diambil worker: tandai selesai sekarang. Jika worker kebetulan baru
        # mengambilnya, run_autolabel_job melihat status cancelled dan langsung berhenti.
        job.status, job.finished_at = JobStatus.CANCELLED, datetime.now(timezone.utc)
        if job.celery_task_id:
            queue.revoke(job.celery_task_id)
    db.commit()
    return job
