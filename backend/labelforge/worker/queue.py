"""Antarmuka antrian yang dipakai proses web. Diganti di test dengan eksekusi langsung."""

from typing import Protocol

from labelforge.services.job_runner import queue_for


class JobQueue(Protocol):
    def enqueue(self, job_type: str, job_id: int) -> str | None: ...

    def revoke(self, task_id: str) -> None: ...

    def ping_workers(self, timeout: float = 1.0) -> list[str]: ...


class CeleryJobQueue:
    def enqueue(self, job_type: str, job_id: int) -> str | None:
        from labelforge.worker.celery_app import celery_app

        # send_task: proses web tidak perlu meng-import modul task (dan dependency ML-nya).
        result = celery_app.send_task("labelforge.run_job", args=[job_id], queue=queue_for(job_type))
        return result.id

    def revoke(self, task_id: str) -> None:
        from labelforge.worker.celery_app import celery_app

        celery_app.control.revoke(task_id)

    def ping_workers(self, timeout: float = 1.0) -> list[str]:
        from labelforge.worker.celery_app import celery_app

        try:
            replies = celery_app.control.ping(timeout=timeout) or []
        except Exception:
            return []
        return [name for reply in replies for name in reply]


_queue: JobQueue = CeleryJobQueue()


def get_job_queue() -> JobQueue:
    """FastAPI dependency."""
    return _queue
