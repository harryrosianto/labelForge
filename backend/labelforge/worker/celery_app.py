"""Aplikasi Celery.

Jalankan worker (satu proses, model di-load sekali & tetap di memori):
    celery -A labelforge.worker.celery_app worker --pool=solo --concurrency=1 -Q inference

Queue per jenis pekerjaan (`inference`, nanti `training` di Fase 3) supaya bisa
dijalankan di mesin berbeda.
"""

import logging
import os

from celery import Celery
from celery.signals import worker_ready

from labelforge.config import get_settings

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


@worker_ready.connect
def _preload_models(**_kwargs):
    """Load model provider di awal agar job pertama tidak menunggu lama.
    WORKER_PRELOAD=owlv2,grounding_dino (default: provider default di config; kosong = lazy)."""
    from labelforge.providers.registry import get_provider

    names = os.environ.get("WORKER_PRELOAD", settings.default_provider)
    for name in filter(None, (n.strip() for n in names.split(","))):
        try:
            log.info("Preload model provider %s ...", name)
            get_provider(name).load()
            log.info("Provider %s siap di %s", name, get_provider(name).device)
        except Exception:
            log.exception("Preload provider %s gagal (akan dicoba lagi saat job)", name)
