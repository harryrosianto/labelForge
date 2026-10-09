import io
import zipfile

import pytest
from sqlalchemy import select

from labelforge.models import DatasetImport, Image, LabelClass
from tests.test_exporters import W, H, ds  # noqa: F401  (fixture dataset 400x200)
from tests.test_images_service import make_jpeg



def make_zip(files: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, d in files.items():
            zf.writestr(n, d)
    return buf.getvalue()


def upload(client, pid, data: bytes, name="dataset.zip"):
    return client.post(f"/api/projects/{pid}/imports", files={"file": (name, data, "application/zip")})


YOLO_ZIP = make_zip({
    "data.yaml": "names: [Pallet, forklift, box]",
    "images/train/a.jpg": make_jpeg((100, 50), "red"),
    "labels/train/a.txt": "0 0.5 0.5 0.2 0.4\n1 0.2 0.2 0.2 0.2\n2 0.8 0.8 0.1 0.1\n",
    "images/val/b.jpg": make_jpeg((100, 50), "blue"),
    "labels/val/b.txt": "",
})  # fmt: skip


@pytest.fixture
def pallet_project(client, project):
    pid = project["id"]
    pallet = client.post(f"/api/projects/{pid}/classes", json={"name": "pallet"}).json()["id"]
    return pid, pallet


def test_analysis_suggests_mapping_without_touching_project(client, pallet_project, db):
    pid, pallet = pallet_project
    r = upload(client, pid, YOLO_ZIP)
    assert r.status_code == 201, r.text
    imp = r.json()
    assert imp["status"] == "analyzed" and imp["format"] == "yolo"
    a = imp["analysis"]
    assert a["images"] == 2 and a["boxes"] == 3
    # "Pallet" dipetakan ke class "pallet" yang sudah ada (tanpa membedakan huruf besar/kecil)
    assert a["suggested_mapping"] == {
        "Pallet": {"action": "map", "class_id": pallet},
        "forklift": {"action": "create", "name": "forklift"},
        "box": {"action": "create", "name": "box"},
    }
    assert db.query(Image).count() == 0  # analisis tidak mengubah project


def test_import_flow_create_map_ignore(client, pallet_project, db, storage):
    pid, pallet = pallet_project
    imp = upload(client, pid, YOLO_ZIP).json()
    r = client.post(f"/api/imports/{imp['id']}/start", json={"mapping": {
        "Pallet": {"action": "map", "class_id": pallet},
        "forklift": {"action": "create", "name": "Forklift  Listrik"},
        "box": {"action": "ignore"},
    }})  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"  # InlineQueue: job langsung dijalankan

    job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
    assert job["job_type"] == "import" and job["status"] == "completed"
    assert (job["total"], job["processed"], job["failed_count"]) == (2, 2, 0)
    assert job["result"]["imported"] == 2 and job["result"]["boxes"] == 2
    assert job["result"]["boxes_ignored"] == 1

    classes = [c["name"] for c in client.get(f"/api/projects/{pid}/classes").json()]
    assert classes == ["pallet", "Forklift Listrik"]
    images = client.get(f"/api/projects/{pid}/images", params={"source_type": "import"}).json()
    assert images["total"] == 2
    for img in images["items"]:
        assert img["status"] == "reviewed" and img["source_label"] == "dataset.zip"
        assert all(a["is_approved"] and a["source"] == "import:yolo" for a in img["annotations"])
    assert client.get(f"/api/projects/{pid}/images", params={"source_type": "upload"}).json()["total"] == 0
    # ZIP dihapus setelah berhasil
    assert not storage.exists(db.get(DatasetImport, imp["id"]).storage_key)


def test_mark_for_review_and_duplicates(client, pallet_project, db):
    pid, pallet = pallet_project
    mapping = {"Pallet": {"action": "map", "class_id": pallet}, "forklift": {"action": "ignore"},
               "box": {"action": "ignore"}}  # fmt: skip
    first = upload(client, pid, YOLO_ZIP).json()
    client.post(f"/api/imports/{first['id']}/start", json={"mapping": mapping, "mark_for_review": True})
    imgs = client.get(f"/api/projects/{pid}/images").json()["items"]
    assert {i["status"] for i in imgs} == {"auto_labeled"}
    assert not any(a["is_approved"] for i in imgs for a in i["annotations"])

    second = upload(client, pid, YOLO_ZIP).json()
    r = client.post(f"/api/imports/{second['id']}/start", json={"mapping": mapping}).json()
    job = client.get(f"/api/jobs/{r['job_id']}").json()
    assert job["result"]["duplicates"] == 2 and job["result"]["imported"] == 0
    assert db.query(Image).count() == 2


def test_start_validation_and_discard(client, pallet_project, storage, db):
    pid, _ = pallet_project
    imp = upload(client, pid, YOLO_ZIP).json()
    r = client.post(f"/api/imports/{imp['id']}/start", json={"mapping": {"Pallet": {"action": "ignore"}}})
    assert r.status_code == 422 and "belum lengkap" in r.json()["detail"]
    r = client.post(f"/api/imports/{imp['id']}/start", json={"mapping": {
        "Pallet": {"action": "map", "class_id": 9999}, "forklift": {"action": "ignore"}, "box": {"action": "ignore"},
    }})  # fmt: skip
    assert r.status_code == 422 and "bukan milik" in r.json()["detail"]
    assert db.query(LabelClass).count() == 1  # validasi gagal tidak membuat class

    key = db.get(DatasetImport, imp["id"]).storage_key
    assert client.delete(f"/api/imports/{imp['id']}").status_code == 204
    assert not storage.exists(key)
    assert client.get(f"/api/imports/{imp['id']}").status_code == 404


def test_upload_errors(client, project, storage):
    pid = project["id"]
    assert upload(client, pid, b"x", "a.rar").status_code == 422
    r = upload(client, pid, b"bukan zip")
    assert r.status_code == 422 and "ZIP" in r.json()["detail"]
    r = upload(client, pid, make_zip({"readme.md": "x"}))
    assert r.status_code == 422 and "gambar" in r.json()["detail"]
    assert client.get(f"/api/projects/{pid}/imports").json() == []


def _snapshot(db, project_id):
    """{sha256 gambar: [(nama class, box)]}: identitas gambar & box, lepas dari id."""
    out = {}
    for img in db.scalars(select(Image).where(Image.project_id == project_id)):
        out[img.sha256] = sorted(
            (a.label_class.name, (a.x_min, a.y_min, a.x_max, a.y_max)) for a in img.annotations
        )
    return out


@pytest.mark.parametrize("fmt,tol", [("yolo", 1e-6), ("coco", 0.01 / 200)])
def test_round_trip_export_then_import(client, ds, db, fmt, tol):  # noqa: F811
    """Export Fase 1 lalu import ke project kosong → gambar & box identik."""
    zip_bytes = client.post(f"/api/projects/{ds['pid']}/export",
                            json={"format": fmt, "split": {"train": 0.5, "val": 0.5}}).content  # fmt: skip
    target = client.post("/api/projects", json={"name": "tujuan"}).json()["id"]
    imp = upload(client, target, zip_bytes).json()
    assert imp["format"] == fmt and imp["analysis"]["problem_counts"] == {}
    mapping = {c["name"]: {"action": "create"} for c in imp["analysis"]["classes"]}
    client.post(f"/api/imports/{imp['id']}/start", json={"mapping": mapping})

    db.expire_all()
    src_reviewed = {
        sha: boxes for sha, boxes in _snapshot(db, ds["pid"]).items()
        if db.scalar(select(Image.status).where(Image.sha256 == sha, Image.project_id == ds["pid"])) == "reviewed"
    }  # fmt: skip
    dst = _snapshot(db, target)
    assert set(dst) == set(src_reviewed)  # gambar sama persis (hash file)
    for sha, boxes in src_reviewed.items():
        got = dst[sha]
        assert [n for n, _ in got] == [n for n, _ in boxes]
        for (_, a), (_, b) in zip(got, boxes):
            assert a == pytest.approx(b, abs=tol)
    names = [c["name"] for c in client.get(f"/api/projects/{target}/classes").json()]
    assert names == ["pallet", "person"]  # urutan class ikut terbawa


def test_gallery_source_filter_validation(client, project):
    r = client.get(f"/api/projects/{project['id']}/images", params={"source_type": "kamera"})
    assert r.status_code == 422

