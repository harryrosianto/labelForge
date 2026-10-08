import pytest
from sqlalchemy import select

from labelforge.models import Annotation, ClassExemplar, Image
from labelforge.providers import registry
from labelforge.services.images import ingest_image
from tests.fakes import FakeProvider
from tests.test_images_service import make_jpeg


@pytest.fixture(autouse=True)
def fake_provider():
    registry.register_provider(FakeProvider)
    FakeProvider.calls, FakeProvider.fail_size = 0, None
    yield
    registry._CLASSES.pop("fake", None)
    registry._INSTANCES.pop("fake", None)


@pytest.fixture
def setup(client, project, db, storage):
    """Project dengan 2 class dan 3 gambar 200x100."""
    pid = project["id"]
    pallet = client.post(f"/api/projects/{pid}/classes", json={"name": "pallet"}).json()
    client.post(f"/api/projects/{pid}/classes", json={"name": "person"})
    ids = [
        ingest_image(db, storage, pid, f"{c}.jpg", make_jpeg((200, 100), c)).image.id
        for c in ("red", "green", "blue")
    ]
    db.commit()
    return {"pid": pid, "pallet": pallet["id"], "images": ids}


def start(client, pid, **body):
    return client.post(f"/api/projects/{pid}/jobs/autolabel", json={"provider": "fake", **body})


def annotations(db, image_id):
    db.expire_all()
    return db.scalars(select(Annotation).where(Annotation.image_id == image_id)).all()


def test_providers_endpoint(client):
    names = [p["name"] for p in client.get("/api/providers").json()]
    assert names[0] == "owlv2" and "fake" in names


def test_job_runs_and_writes_annotations(client, setup, db):
    r = start(client, setup["pid"], params={"nms_iou": 0.5})
    assert r.status_code == 201, r.text
    job = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed"
    assert (job["total"], job["processed"], job["failed_count"]) == (3, 3, 0)
    assert job["progress"] == 1.0
    assert job["mode"] == "text" and job["params"]["nms_iou"] == 0.5

    anns = annotations(db, setup["images"][0])
    # FakeProvider: 5 box → 2 tersisa setelah filter class, ukuran minimum, clip & NMS
    assert len(anns) == 2
    a = max(anns, key=lambda a: a.confidence)
    assert (a.x_min, a.y_min, a.x_max, a.y_max) == pytest.approx((0.05, 0.1, 0.25, 0.5))
    assert a.source == "ai:fake" and not a.is_approved and a.job_id == job["id"]
    assert a.class_id == setup["pallet"]
    assert db.get(Image, setup["images"][0]).status == "auto_labeled"

    items = client.get(f"/api/jobs/{job['id']}/items").json()
    assert {i["status"] for i in items} == {"done"} and items[0]["num_detections"] == 2


def test_rerun_replaces_only_unapproved_ai(client, setup, db):
    iid = setup["images"][0]
    db.add_all([
        Annotation(image_id=iid, class_id=setup["pallet"], x_min=0.5, y_min=0.5, x_max=0.6,
                   y_max=0.6, source="manual", is_approved=True),
        Annotation(image_id=iid, class_id=setup["pallet"], x_min=0.7, y_min=0.7, x_max=0.8,
                   y_max=0.8, source="ai:fake", confidence=0.5, is_approved=True),
        Annotation(image_id=iid, class_id=setup["pallet"], x_min=0.1, y_min=0.1, x_max=0.2,
                   y_max=0.2, source="ai:owlv2_text", confidence=0.3),
    ])  # fmt: skip
    db.commit()
    start(client, setup["pid"], target="all")
    anns = annotations(db, iid)
    assert sorted((a.source, a.is_approved) for a in anns) == [
        ("ai:fake", False), ("ai:fake", False), ("ai:fake", True), ("manual", True),
    ]  # fmt: skip


def test_targets(client, setup, db):
    pid, ids = setup["pid"], setup["images"]
    db.get(Image, ids[0]).status = "reviewed"
    db.get(Image, ids[1]).status = "auto_labeled"
    db.commit()

    assert start(client, pid, target="unlabeled").json()["total"] == 1
    assert start(client, pid, target="all").json()["total"] == 2
    assert start(client, pid, target="all", include_reviewed=True).json()["total"] == 3
    # gambar terpilih diproses apa pun statusnya
    assert start(client, pid, target="selected", image_ids=[ids[0]]).json()["total"] == 1
    db.expire_all()
    assert db.get(Image, ids[0]).status == "reviewed"  # reviewed tidak turun status


def test_error_per_image_does_not_stop_job(client, setup, db, storage):
    bad = ingest_image(db, storage, setup["pid"], "bad.jpg", make_jpeg((123, 45))).image.id
    db.commit()
    FakeProvider.fail_size = (123, 45)
    job = start(client, setup["pid"]).json()
    assert job["status"] == "completed"
    assert (job["processed"], job["failed_count"]) == (4, 1)
    errors = client.get(f"/api/jobs/{job['id']}/items", params={"status": "error"}).json()
    assert [e["image_id"] for e in errors] == [bad] and "gagal sengaja" in errors[0]["error"]
    assert db.get(Image, bad).status == "unlabeled"


def test_all_images_failing_marks_job_failed(client, setup):
    FakeProvider.fail_size = (200, 100)
    job = start(client, setup["pid"]).json()
    assert job["status"] == "failed" and job["failed_count"] == 3


@pytest.mark.parametrize(
    "body,message",
    [
        ({"provider": "tidak_ada"}, "tidak dikenal"),
        ({"params": {"nms_iou": 9}}, "nms_iou"),
        ({"mode": "video"}, "Mode"),
        ({"target": "selected"}, "minimal satu gambar"),
    ],
)
def test_invalid_requests(client, setup, body, message):
    r = start(client, setup["pid"], **body)
    assert r.status_code == 422 and message in r.json()["detail"]


def test_requires_classes_and_images(client, project, db, storage):
    pid = project["id"]
    assert "class" in start(client, pid).json()["detail"]
    client.post(f"/api/projects/{pid}/classes", json={"name": "pallet"})
    assert "gambar" in start(client, pid).json()["detail"]


def test_image_guided_warnings_and_exemplars(client, setup, db, storage):
    key = "projects/x/exemplars/1.png"
    storage.save_bytes(key, b"crop")
    db.add(ClassExemplar(class_id=setup["pallet"], x_min=0, y_min=0, x_max=1, y_max=1,
                         crop_storage_key=key, width=1, height=1))  # fmt: skip
    db.commit()
    job = start(client, setup["pid"], mode="image_guided").json()
    assert job["warnings"] == ["Class 'person' tanpa exemplar"]
    assert FakeProvider.last_call["exemplar_bytes"] == [b"crop"]


def test_cancel_queued_job(client, setup, queue):
    queue.run = False
    job = start(client, setup["pid"]).json()
    assert job["status"] == "queued"
    r = client.post(f"/api/jobs/{job['id']}/cancel").json()
    assert r["status"] == "cancelled" and queue.revoked == [f"task-{job['id']}"]
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 409

    # worker yang terlambat mengambil task tidak memproses apa pun
    queue.run = True
    queue.enqueue("autolabel", job["id"])
    assert FakeProvider.calls == 0


def test_cancel_running_job_stops_at_next_image(client, setup, session_factory, storage):
    from labelforge.models import LabelingJob
    from labelforge.services import jobs as jobs_service

    job_id = start(client, setup["pid"]).json()["id"]  # selesai (inline)
    # Simulasikan job baru yang dibatalkan setelah gambar pertama
    with session_factory() as s:
        job = jobs_service.create_autolabel_job(s, storage, setup["pid"], provider="fake",
                                                params={}, target="all", include_reviewed=True)  # fmt: skip
        s.commit()
        new_id = job.id

    def cancel_after_first(job):
        with session_factory() as s:
            s.get(LabelingJob, job.id).cancel_requested = True
            s.commit()

    status = jobs_service.run_autolabel_job(new_id, session_factory, storage, cancel_after_first)
    assert status == "cancelled"
    final = client.get(f"/api/jobs/{new_id}").json()
    assert final["processed"] == 1 and job_id != new_id


def test_job_list_and_health(client, setup):
    start(client, setup["pid"])
    assert len(client.get(f"/api/projects/{setup['pid']}/jobs").json()) == 1
    assert client.get("/api/health").json()["workers"] == ["inline@test"]
