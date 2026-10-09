import io
import json
import zipfile

import pytest

from PIL import Image as PILImage

from labelforge.models import Annotation, Image
from tests.test_exporters import ds  # noqa: F401  (4 gambar 400x200: 2 reviewed, 1 auto, 1 unlabeled)

ALL_TRAIN = {"train": 1, "val": 0, "test": 0}


def create(client, pid, **body):
    body = {"name": "v1", "split": ALL_TRAIN} | body
    return client.post(f"/api/projects/{pid}/versions", json=body)


def export(client, vid, fmt="yolo") -> bytes:
    r = client.post(f"/api/versions/{vid}/export", json={"format": fmt})
    assert r.status_code == 200, r.text
    return r.content


def test_preview_then_create_ready_without_job(client, ds, queue):  # noqa: F811
    pid = ds["pid"]
    p = client.post(f"/api/projects/{pid}/versions/preview", json={"reviewed_only": False}).json()
    assert p["images"] == 3 and p["annotations"] == 3 and p["empty_images"] == 1
    assert [c["name"] for c in p["per_class"]] == ["pallet", "person"]

    r = create(client, pid, name="  v1  awal ", notes="baseline")
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["name"] == "v1 awal" and v["status"] == "ready" and v["job_id"] is None
    assert v["image_count"] == 2 and v["summary"]["splits"] == {"train": 2, "val": 0, "test": 0}
    assert v["config"]["classes"] == [{"name": "pallet", "color": v["config"]["classes"][0]["color"]},
                                      {"name": "person", "color": v["config"]["classes"][1]["color"]}]  # fmt: skip
    assert queue.enqueued == []  # tanpa preprocessing tidak perlu job


def test_export_identical_bytes_and_immutable(client, ds, db):  # noqa: F811
    pid = ds["pid"]
    vid = create(client, pid).json()["id"]
    first = export(client, vid)
    assert export(client, vid) == first  # ZIP identik byte-per-byte

    # Ubah project setelah versi dibuat: anotasi digeser, dihapus, class diganti nama.
    r1 = ds["ids"][0]
    anns = db.query(Annotation).filter_by(image_id=r1).all()
    anns[0].x_min = 0.01
    db.delete(anns[1])
    db.commit()
    client.patch(f"/api/classes/{ds['pallet']}", json={"name": "palet"})
    client.post(f"/api/images/{ds['ids'][2]}/approve")  # gambar auto → reviewed

    assert export(client, vid) == first  # versi tidak terpengaruh

    v2 = create(client, pid, name="v2").json()
    assert export(client, v2["id"]) != first
    assert v2["image_count"] == 3


def test_version_zip_content(client, ds):  # noqa: F811
    vid = create(client, ds["pid"], split={"train": 0.5, "val": 0.5}).json()["id"]
    zf = zipfile.ZipFile(io.BytesIO(export(client, vid)))
    names = zf.namelist()
    assert "data.yaml" in names and any(n.startswith("images/val/") for n in names)
    info = json.loads(zf.read("export_info.json"))
    assert info["version"]["name"] == "v1" and info["images"] == 2
    assert all(i.date_time == (2020, 1, 1, 0, 0, 0) for i in zf.infolist())


def test_image_protection(client, ds, db):  # noqa: F811
    pid, ids = ds["pid"], ds["ids"]
    vid = create(client, pid, name="rilis-1").json()["id"]
    r = client.delete(f"/api/images/{ids[0]}")
    assert r.status_code == 409 and "rilis-1" in r.json()["detail"]
    # gambar yang tidak dipakai versi tetap bisa dihapus massal; yang dipakai dilewati
    r = client.post(f"/api/projects/{pid}/images/bulk-delete", json={"image_ids": [ids[0], ids[3]]})
    assert r.json() == {"deleted": 1, "protected": [ids[0]]}

    assert client.delete(f"/api/versions/{vid}").status_code == 204
    assert client.delete(f"/api/images/{ids[0]}").status_code == 204


def test_delete_project_with_versions(client, ds, db):  # noqa: F811
    create(client, ds["pid"])
    assert client.delete(f"/api/projects/{ds['pid']}").status_code == 204
    assert db.query(Image).count() == 0


def test_preprocessing_fit_runs_job(client, ds, storage, queue):  # noqa: F811
    r = create(client, ds["pid"], name="640",
               preprocessing={"resize": "fit", "width": 640, "height": 640})  # fmt: skip
    v = r.json()
    assert v["status"] == "ready" and v["job_id"]  # InlineQueue: job langsung selesai
    job = client.get(f"/api/jobs/{v['job_id']}").json()
    assert job["job_type"] == "version_build" and (job["processed"], job["failed_count"]) == (2, 0)
    assert queue.enqueued == [("version_build", v["job_id"])]

    zf = zipfile.ZipFile(io.BytesIO(export(client, v["id"])))
    r1 = ds["ids"][0]
    img_name = next(n for n in zf.namelist() if n.startswith(f"images/train/{r1:06d}_"))
    assert PILImage.open(io.BytesIO(zf.read(img_name))).size == (640, 640)
    label = zf.read(img_name.replace("images/", "labels/").rsplit(".", 1)[0] + ".txt").decode()
    # pallet (0.1,0.2)-(0.5,0.6) pada 400x200 → letterbox 640x320 offset y 160 →
    # y: (160 + 0.2*320)/640 = 0.35 .. (160 + 0.6*320)/640 = 0.55
    assert label.splitlines()[0] == "0 0.300000 0.450000 0.400000 0.200000"

    assert client.delete(f"/api/versions/{v['id']}").status_code == 204
    assert not any(storage.exists(f"projects/{ds['pid']}/versions/{v['id']}/train/{i}_0.jpg") for i in ds["ids"])


def test_building_version_cannot_export_or_delete(client, ds, queue):  # noqa: F811
    queue.run = False
    v = create(client, ds["pid"], preprocessing={"resize": "stretch", "width": 64, "height": 64}).json()
    assert v["status"] == "building"
    assert client.post(f"/api/versions/{v['id']}/export", json={}).status_code == 409
    assert client.delete(f"/api/versions/{v['id']}").status_code == 409


def test_validation(client, ds, project):  # noqa: F811
    empty = client.post("/api/projects", json={"name": "kosong"}).json()["id"]
    r = create(client, empty)
    assert r.status_code == 422 and "reviewed" in r.json()["detail"]
    assert create(client, ds["pid"], name="  ").status_code == 422
    assert create(client, ds["pid"], split={"train": 0, "val": 1}).status_code == 422
    assert create(client, ds["pid"], preprocessing={"resize": "fit"}).status_code == 422


def test_rename_only(client, ds):  # noqa: F811
    v = create(client, ds["pid"]).json()
    r = client.patch(f"/api/versions/{v['id']}", json={"name": "v1-final", "notes": "untuk training",
                                                      "config": {"seed": 1}}).json()  # fmt: skip
    assert (r["name"], r["notes"]) == ("v1-final", "untuk training")
    assert r["config"] == v["config"]  # isi versi tidak bisa diubah


def test_compare(client, ds, db):  # noqa: F811
    pid = ds["pid"]
    a = create(client, pid, name="a").json()["id"]
    ann = db.query(Annotation).filter_by(image_id=ds["ids"][0]).first()
    ann.x_max = 0.9
    db.commit()
    client.post(f"/api/images/{ds['ids'][2]}/approve")
    b = create(client, pid, name="b", seed=7).json()["id"]

    c = client.get("/api/versions/compare", params={"a": a, "b": b}).json()
    assert (c["images_only_in_a"], c["images_only_in_b"], c["images_in_both"]) == (0, 1, 2)
    assert c["labels_changed"] == 1
    assert {p["name"]: (p["a"], p["b"]) for p in c["per_class"]} == {"pallet": (1, 2), "person": (1, 1)}
    assert c["settings_changed"] == {"seed": {"a": 42, "b": 7}}


def test_list_versions(client, ds):  # noqa: F811
    create(client, ds["pid"], name="satu")
    create(client, ds["pid"], name="dua")
    names = [v["name"] for v in client.get(f"/api/projects/{ds['pid']}/versions").json()]
    assert names == ["dua", "satu"]



AUG = {"enabled": True, "multiplier": 2, "hflip": 1.0, "brightness": 0, "contrast": 0}


def _zip_payload(content: bytes) -> dict[str, bytes]:
    """Isi ZIP tanpa export_info (yang memuat nama/tanggal versi)."""
    zf = zipfile.ZipFile(io.BytesIO(content))
    return {n: zf.read(n) for n in zf.namelist() if n != "export_info.json"}


def test_augmented_version(client, ds, queue):  # noqa: F811
    pid = ds["pid"]
    p = client.post(f"/api/projects/{pid}/versions/preview",
                    json={"split": ALL_TRAIN, "augmentation": AUG}).json()  # fmt: skip
    assert p["augmented"] == 4  # 2 gambar train x 2 salinan

    v = create(client, pid, name="aug", augmentation=AUG).json()
    assert v["status"] == "ready"
    assert v["image_count"] == 6 and v["summary"]["augmented"] == 4
    job = client.get(f"/api/jobs/{v['job_id']}").json()
    assert job["result"]["augmented"] == 4 and job["failed_count"] == 0

    zf = zipfile.ZipFile(io.BytesIO(export(client, v["id"])))
    r1 = ds["ids"][0]
    orig = zf.read(next(n for n in zf.namelist() if n.startswith(f"labels/train/{r1:06d}_"))).decode()
    flipped = zf.read(next(n for n in zf.namelist() if n.startswith(f"labels/train/{r1:06d}_aug1_"))).decode()
    # hflip pasti (p=1): cx menjadi 1 - cx, sisanya sama
    for a, b in zip(sorted(orig.splitlines()), sorted(flipped.splitlines(), key=lambda l: l.split()[0])):
        ca, xa, ya, wa, ha = a.split()
        cb, xb, yb, wb, hb = b.split()
        assert ca == cb and float(xb) == pytest.approx(1 - float(xa), abs=2e-6)
        assert (ya, wa, ha) == (yb, wb, hb)
    img = PILImage.open(io.BytesIO(zf.read(next(n for n in zf.namelist()
                                              if n.startswith(f"images/train/{r1:06d}_aug2_")))))  # fmt: skip
    assert img.size == (400, 200)


def test_augmentation_reproducible_across_versions(client, ds):  # noqa: F811
    cfg = {"enabled": True, "multiplier": 2, "rotate_deg": 10, "scale_min": 0.8, "scale_max": 1.2,
           "translate": 0.1, "hue_deg": 5, "noise": 0.5}  # fmt: skip
    a = create(client, ds["pid"], name="a", augmentation=cfg).json()["id"]
    b = create(client, ds["pid"], name="b", augmentation=cfg).json()["id"]
    c = create(client, ds["pid"], name="c", augmentation=cfg, seed=99).json()["id"]
    assert _zip_payload(export(client, a)) == _zip_payload(export(client, b))
    assert _zip_payload(export(client, a)) != _zip_payload(export(client, c))


def test_preview_augmentation(client, ds):  # noqa: F811
    r = client.post(f"/api/projects/{ds['pid']}/versions/preview-augmentation",
                    json={"count": 3, "augmentation": {"hflip": 1.0},
                          "preprocessing": {"resize": "fit", "width": 256, "height": 256}})  # fmt: skip
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["classes"] == ["pallet", "person"] and len(data["samples"]) == 2  # hanya 2 gambar reviewed
    s = data["samples"][0]
    assert s["data_url"].startswith("data:image/jpeg;base64,") and (s["width"], s["height"]) == (256, 256)
    assert all(len(b) == 5 for b in s["boxes"])
    bad = client.post(f"/api/projects/{ds['pid']}/versions/preview-augmentation",
                      json={"augmentation": {"scale_min": 0.9, "scale_max": 0.8}})  # fmt: skip
    assert bad.status_code == 422
