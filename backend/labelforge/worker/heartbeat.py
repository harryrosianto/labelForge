"""Heartbeat worker di Redis: dasar indikator "worker aktif" di UI.

Setiap worker menulis key `labelforge:worker:<nama>` (berisi queue, status, pid) setiap
INTERVAL detik dengan masa berlaku TTL detik. Worker yang mati otomatis hilang dari daftar.
Tidak memakai broadcast ping Celery (pub/sub), yang pada kasus nyata bisa berhenti menjawab
walaupun worker tetap memproses job.
"""

import json
import os
import threading
import time
from typing import Any

KEY_PREFIX = "labelforge:worker:"
INTERVAL_S = 10
TTL_S = 30


def _client(redis_url: str):
    import redis

    return redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)


class Heartbeat:
    def __init__(self, redis_url: str, hostname: str, queues: list[str], client=None):
        self.client = client or _client(redis_url)
        self.key = KEY_PREFIX + hostname
        self.info: dict[str, Any] = {
            "name": hostname, "queues": sorted(queues), "pid": os.getpid(),
            "started_at": time.time(), "state": "starting",
        }  # fmt: skip
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def set_state(self, state: str) -> None:
        self.info["state"] = state
        self.beat()

    def beat(self) -> None:
        try:
            self.client.set(self.key, json.dumps({**self.info, "beat_at": time.time()}), ex=TTL_S)
        except Exception:
            pass  # Redis sesaat tidak terjangkau: coba lagi di detak berikutnya

    def start(self) -> "Heartbeat":
        self.beat()

        def loop() -> None:
            while not self._stop.wait(INTERVAL_S):
                self.beat()

        self._thread = threading.Thread(target=loop, name="labelforge-heartbeat", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        try:
            self.client.delete(self.key)
        except Exception:
            pass


def list_workers(redis_url: str, client=None) -> list[dict]:
    """Worker yang masih mengirim heartbeat, urut nama."""
    client = client or _client(redis_url)
    workers = []
    for key in client.scan_iter(match=KEY_PREFIX + "*", count=100):
        raw = client.get(key)
        if raw:
            try:
                workers.append(json.loads(raw))
            except ValueError:
                continue
    return sorted(workers, key=lambda w: w.get("name", ""))
