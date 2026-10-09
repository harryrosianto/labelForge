import io
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from labelforge.exporters import job as export_job
from labelforge.models import LabelingJob
from labelforge.services.job_runner import JobCancelled, JobContext
from tests.test_exporters import ds  # noqa: F401  (4 gambar 400x200: 2 reviewed, 1 auto, 1 unlabeled)
from tests.test_versions import create, export


def _entries(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def _download(client, job_id: int):
    return client.get(f"/api/exports/{job_id}/download")


def test_version_export_job_identical_to_direct_export(client, ds, queue):  # noqa: F811
    v = create(client, ds["pid"], name="v1").json()
    r = client.post(f"/api/versions/{v['id']}/export-jobs", json={"format": "yolo"})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["job_type"] == "export" and job["status"] == "completed"
    assert (job["processed"], job["total"]) == (2, 2)
    assert job["result"]["filename"].endswith("_yolo.zip") and job["result"]["images"] == 2
    assert queue.enqueued[-1] == ("export", job["id"])

    d = _download(client, job["id"])
    assert d.status_code == 200
    assert d.headers["content-type"] == "application/zip"
    assert job["result"]["filename"] in d.headers["content-disposition"]
    assert d.content == export(client, v["id"])  # byte identik dengan export langsung
    assert int(d.headers["content-length"]) == job["result"]["size_bytes"]


def test_project_export_job_same_content(client, ds):  # noqa: F811
    body = {"format": "coco", "reviewed_only": False, "split": {"train": 0.5, "val": 0.5, "test": 0}, "seed": 3}
    job = client.post(f"/api/projects/{ds['pid']}/export-jobs", json=body).json()
    assert job["status"] == "completed", job["error"]
    direct = client.post(f"/api/projects/{ds['pid']}/export", json=body).content
    assert _entries(_download(client, job["id"]).content) == _entries(direct)


def test_export_job_empty_fails(client, project):
    job = client.post(f"/api/projects/{project['id']}/export-jobs", json={}).json()
    assert job["status"] == "failed" and "Tidak ada gambar" in job["error"]
    assert _download(client, job["id"]).status_code == 409


def test_version_export_job_requires_ready(client, ds, queue):  # noqa: F811
    queue.run = False
    v = create(client, ds["pid"], preprocessing={"resize": "stretch", "width": 64, "height": 64}).json()
    assert client.post(f"/api/versions/{v['id']}/export-jobs", json={}).status_code == 409
    assert client.post("/api/versions/999/export-jobs", json={}).status_code == 404


def test_download_errors(client, ds, queue):  # noqa: F811
    assert _download(client, 999).status_code == 404
    queue.run = False
    job = client.post(f"/api/projects/{ds['pid']}/export-jobs", json={}).json()
    assert job["status"] == "queued"
    assert _download(client, job["id"]).status_code == 409
    v = create(client, ds["pid"], preprocessing={"resize": "stretch", "width": 64, "height": 64}).json()
    assert _download(client, v["job_id"]).status_code == 404  # job lain, bukan export


def test_old_exports_cleaned_up(client, ds, db, storage):  # noqa: F811
    old = client.post(f"/api/projects/{ds['pid']}/export-jobs", json={}).json()
    key = old["result"]["file"]
    assert storage.exists(key)
    row = db.get(LabelingJob, old["id"])
    row.finished_at = datetime.now(timezone.utc) - export_job.RETENTION - timedelta(hours=1)
    db.commit()

    new = client.post(f"/api/projects/{ds['pid']}/export-jobs", json={}).json()  # memicu pembersihan
    assert not storage.exists(key) and storage.exists(new["result"]["file"])
    assert client.get(f"/api/jobs/{old['id']}").json()["result"]["expired"] is True
    assert _download(client, old["id"]).status_code == 410
    assert _download(client, new["id"]).status_code == 200


def test_export_job_cancel_leaves_no_file(client, ds, storage, monkeypatch):  # noqa: F811
    monkeypatch.setattr(export_job, "PROGRESS_EVERY", 1)

    def cancel(self):
        raise JobCancelled()

    monkeypatch.setattr(JobContext, "check_cancel", cancel)
    job = client.post(f"/api/projects/{ds['pid']}/export-jobs", json={}).json()
    assert job["status"] == "cancelled" and job["result"] is None
    exports = storage.root / f"projects/{ds['pid']}/exports"
    assert not exports.exists() or not any(exports.iterdir())


@pytest.mark.parametrize("name,expected", [("Gudang A / Lantai 2", "gudang-a-lantai-2"), ("!!!", "dataset")])
def test_slug(name, expected):
    assert export_job._slug(name) == expected
