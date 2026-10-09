import pytest

from labelforge.models import LabelingJob, LabelingJobItem
from labelforge.services import job_runner
from labelforge.services.job_runner import (
    create_job,
    queue_for,
    register_job_handler,
    run_job,
)

TEST_TYPE = "test_job"


@pytest.fixture
def behaviour():
    """Handler uji: perilakunya diatur per test lewat dict ini."""
    state = {"items": ["a", "b", "c"], "fail": set(), "raise": None, "cancel_after": None}

    def handler(ctx):
        ctx.set_total(len(state["items"]))
        for i, name in enumerate(state["items"]):
            if state["cancel_after"] is not None and i == state["cancel_after"]:
                with ctx.session_factory() as db:
                    db.get(LabelingJob, ctx.job_id).cancel_requested = True
                    db.commit()
            ctx.check_cancel()
            if state["raise"]:
                raise state["raise"]
            ctx.record(label=name, error="rusak" if name in state["fail"] else None, count=1)
        ctx.warn("catatan")
        return {"imported": len(state["items"]) - len(state["fail"]), "payload": ctx.payload}

    register_job_handler(TEST_TYPE)(handler)
    yield state
    job_runner._HANDLERS.pop(TEST_TYPE, None)


@pytest.fixture
def job_id(db, project):
    job = create_job(db, project["id"], TEST_TYPE, {"x": 1})
    db.commit()
    return job.id


def _job(db, job_id):
    db.expire_all()
    return db.get(LabelingJob, job_id)


def test_completed_with_result_items_and_warnings(db, session_factory, storage, behaviour, job_id):
    assert run_job(job_id, session_factory, storage) == "completed"
    job = _job(db, job_id)
    assert (job.total, job.processed, job.failed_count) == (3, 3, 0)
    assert job.result["imported"] == 3 and job.result["payload"] == {"x": 1}
    assert "duration_s" in job.result and job.warnings == ["catatan"]
    items = db.query(LabelingJobItem).filter_by(job_id=job_id).all()
    assert [(i.label, i.image_id, i.status) for i in items] == [
        ("a", None, "done"), ("b", None, "done"), ("c", None, "done")
    ]
    assert job.provider is None and job.started_at and job.finished_at


def test_item_errors_and_all_failed(db, session_factory, storage, behaviour, job_id, project):
    behaviour["fail"] = {"b"}
    assert run_job(job_id, session_factory, storage) == "completed"
    assert _job(db, job_id).failed_count == 1

    behaviour["fail"] = {"a", "b", "c"}
    job2 = create_job(db, project["id"], TEST_TYPE)
    db.commit()
    assert run_job(job2.id, session_factory, storage) == "failed"
    assert "Semua item gagal" in _job(db, job2.id).error


def test_exception_marks_failed(db, session_factory, storage, behaviour, job_id):
    behaviour["raise"] = ValueError("ZIP rusak")
    assert run_job(job_id, session_factory, storage) == "failed"
    assert _job(db, job_id).error == "ValueError: ZIP rusak"


def test_cancel_mid_run_and_before_start(db, session_factory, storage, behaviour, job_id, project):
    behaviour["cancel_after"] = 1
    assert run_job(job_id, session_factory, storage) == "cancelled"
    assert _job(db, job_id).processed == 1

    job2 = create_job(db, project["id"], TEST_TYPE)
    job2.cancel_requested = True
    db.commit()
    assert run_job(job2.id, session_factory, storage) == "cancelled"
    # job yang sudah selesai tidak dijalankan ulang
    assert run_job(job_id, session_factory, storage) == "cancelled"


def test_unknown_type_and_missing_job(db, session_factory, storage, project):
    job = create_job(db, project["id"], "tidak_ada")
    db.commit()
    with pytest.raises(ValueError):
        run_job(job.id, session_factory, storage)
    assert run_job(99999, session_factory, storage) == "missing"


def test_queue_routing():
    assert queue_for("autolabel") == "inference"
    for t in ("import", "version_build", "video_extract", "rtsp_capture"):
        assert queue_for(t) == "io"


def test_generic_job_visible_and_cancellable_via_api(client, db, project, behaviour):
    job = create_job(db, project["id"], TEST_TYPE, {"x": 1})
    db.commit()
    listed = client.get(f"/api/projects/{project['id']}/jobs").json()
    assert listed[0]["job_type"] == TEST_TYPE and listed[0]["provider"] is None
    assert listed[0]["payload"] == {"x": 1}
    r = client.post(f"/api/jobs/{job.id}/cancel").json()
    assert r["status"] == "cancelled"

