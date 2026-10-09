"""Aplikasi Celery.

Worker inference (satu proses, model AI di-load sekali & tetap di memori):
    celery -A labelforge.worker.celery_app worker --pool=solo --concurrency=1 -Q inference

Worker io (import, versi, video, RTSP; tanpa model AI):
    WORKER_PRELOAD= celery -A labelforge.worker.celery_app worker --pool=threads --concurrency=2 -Q io

Untuk development cukup satu worker yang mendengar keduanya: `-Q inference,io`.

Queue per jenis pekerjaan (mis. `inference`, `training`) supaya bisa
dijalankan di mesin berbeda.
"""

import logging
import os

from celery import Celery
from celery.signals import worker_ready, worker_shutdown

from labelforge.config import get_settings
from labelforge.worker.heartbeat import Heartbeat

log = logging.getLogger(__name__)
settings = get_settings()

celery_app = Celery("labelforge", broker=settings.redis_url, include=["labelforge.worker.tasks"])
celery_app.conf.update(
    task_ignore_result=True,  # status job disimpan di DB, bukan result backend
    task_acks_late=True,  # task dikirim ulang jika worker mati di tengah job
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_routes={"labelforge.autolabel": {"queue": "inference"}},
    task_default_queue="inference",
    broker_connection_retry_on_startup=True,
    # Job besar bisa berjam-jam di CPU; visibility timeout harus > durasi job terpanjang
    # agar Redis tidak mengirim ulang task yang masih berjalan.
    broker_transport_options={"visibility_timeout": 24 * 3600},
)


_heartbeat: Heartbeat | None = None


@worker_ready.connect
def _on_ready(sender=None, **_kwargs):
    """Mulai heartbeat (indikator worker di UI), lalu preload model.
    WORKER_PRELOAD=owlv2,grounding_dino (default: provider default di config; kosong = lazy)."""
    global _heartbeat
    queues = [q.name for q in sender.task_consumer.queues] if sender is not None else []
    _heartbeat = Heartbeat(settings.redis_url, sender.hostname if sender else "worker", queues).start()
    _preload_models()
    _heartbeat.set_state("ready")


@worker_shutdown.connect
def _on_shutdown(**_kwargs):
    if _heartbeat is not None:
        _heartbeat.stop()


def _preload_models() -> None:
    from labelforge.providers.registry import get_provider

    names = os.environ.get("WORKER_PRELOAD", settings.default_provider)
    if names.strip() and _heartbeat is not None:
        _heartbeat.set_state("loading_model")
    for name in filter(None, (n.strip() for n in names.split(","))):
        try:
            log.info("Preload model provider %s ...", name)
            get_provider(name).load()
            log.info("Provider %s siap di %s", name, get_provider(name).device)
        except Exception:
            log.exception("Preload provider %s gagal (akan dicoba lagi saat job)", name)
