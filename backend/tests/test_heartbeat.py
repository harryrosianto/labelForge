import json

from labelforge.worker import heartbeat
from labelforge.worker.heartbeat import Heartbeat, list_workers


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    def set(self, key, value, ex=None):
        self.data[key] = value
        self.ttl[key] = ex

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)

    def scan_iter(self, match, count=None):
        prefix = match.rstrip("*")
        return [k for k in list(self.data) if k.startswith(prefix)]


def test_heartbeat_lifecycle():
    r = FakeRedis()
    hb = Heartbeat("redis://x", "celery@pc", ["io", "inference"], client=r).start()
    key = "labelforge:worker:celery@pc"
    info = json.loads(r.data[key])
    assert info["state"] == "starting" and info["queues"] == ["inference", "io"]
    assert r.ttl[key] == heartbeat.TTL_S

    hb.set_state("loading_model")
    assert list_workers("redis://x", client=r)[0]["state"] == "loading_model"
    hb.set_state("ready")
    assert [w["name"] for w in list_workers("redis://x", client=r)] == ["celery@pc"]

    hb.stop()
    assert list_workers("redis://x", client=r) == []


def test_list_workers_skips_garbage_and_sorts():
    r = FakeRedis()
    r.set("labelforge:worker:b", json.dumps({"name": "b"}))
    r.set("labelforge:worker:a", json.dumps({"name": "a"}))
    r.set("labelforge:worker:rusak", "bukan json")
    r.set("kunci:lain", json.dumps({"name": "z"}))
    assert [w["name"] for w in list_workers("redis://x", client=r)] == ["a", "b"]


def test_beat_survives_redis_error():
    class Broken(FakeRedis):
        def set(self, *a, **k):
            raise ConnectionError("redis mati")

    Heartbeat("redis://x", "w", ["io"], client=Broken()).beat()  # tidak melempar error


def test_health_reports_queues_without_worker(client, queue, monkeypatch):
    h = client.get("/api/health").json()
    assert h["workers"] == ["inline@test"] and h["queues_without_worker"] == []

    monkeypatch.setattr(queue, "ping_workers", lambda timeout=1.0: [
        {"name": "io@pc", "queues": ["io"], "state": "ready"},
        {"name": "gpu@pc", "queues": ["inference"], "state": "loading_model"},
    ])  # fmt: skip
    h = client.get("/api/health").json()
    assert h["workers"] == ["io@pc", "gpu@pc"]
    assert h["queues_without_worker"] == ["inference"]  # worker inference masih memuat model
