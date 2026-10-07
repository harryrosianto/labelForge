"""Antarmuka antrian yang dipakai proses web. Diganti di test dengan eksekusi langsung."""

from typing import Protocol


class JobQueue(Protocol):
    def enqueue_autolabel(self, job_id: int) -> str | None: ...

    def revoke(self, task_id: str) -> None: ...

    def ping_workers(self, timeout: float = 1.0) -> list[str]: ...


class CeleryJobQueue:
    def enqueue_autolabel(self, job_id: int) -> str | None:
        from labelforge.worker.celery_app import celery_app

        # send_task: proses web tidak perlu meng-import modul task (dan dependency ML-nya).
        return celery_app.send_task("labelforge.autolabel", args=[job_id]).id

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
