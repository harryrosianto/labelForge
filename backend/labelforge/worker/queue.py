"""Antarmuka antrian yang dipakai proses web. Diganti di test dengan eksekusi langsung."""

from typing import Protocol

from labelforge.services.job_runner import queue_for


class JobQueue(Protocol):
    def enqueue(self, job_type: str, job_id: int) -> str | None: ...

    def revoke(self, task_id: str) -> None: ...

    def ping_workers(self, timeout: float = 1.0) -> list[dict]: ...


class CeleryJobQueue:
    def enqueue(self, job_type: str, job_id: int) -> str | None:
        from labelforge.worker.celery_app import celery_app

        # send_task: proses web tidak perlu meng-import modul task (dan dependency ML-nya).
        result = celery_app.send_task("labelforge.run_job", args=[job_id], queue=queue_for(job_type))
        return result.id

    def revoke(self, task_id: str) -> None:
        from labelforge.worker.celery_app import celery_app

        celery_app.control.revoke(task_id)

    def ping_workers(self, timeout: float = 1.0) -> list[dict]:
        """Worker aktif berdasarkan heartbeat di Redis (bukan broadcast ping Celery)."""
        from labelforge.config import get_settings
        from labelforge.worker.heartbeat import list_workers

        try:
            return list_workers(get_settings().redis_url)
        except Exception:
            return []


_queue: JobQueue = CeleryJobQueue()


def get_job_queue() -> JobQueue:
    """FastAPI dependency."""
    return _queue
