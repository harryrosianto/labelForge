import io
import json
import zipfile

import pytest
from PIL import Image as PILImage

from labelforge.core.formats import yolo_to_norm_xyxy
from labelforge.models import Annotation, Image
from tests.test_api_images import upload
from tests.test_images_service import make_jpeg

W, H = 400, 200  # non-persegi agar tertukarnya w/h ketahuan


@pytest.fixture
def ds(client, project, db):
    """4 gambar: 2 reviewed (salah satunya tanpa objek), 1 auto_labeled, 1 unlabeled."""
    pid = project["id"]
    # urutan class sengaja dibalik dari urutan pembuatan untuk menguji index YOLO
    person = client.post(f"/api/projects/{pid}/classes", json={"name": "person"}).json()["id"]
    pallet = client.post(f"/api/projects/{pid}/classes", json={"name": "pallet"}).json()["id"]
    client.put(f"/api/projects/{pid}/classes/order", json={"class_ids": [pallet, person]})

    files = [(f"cam {c}.jpg", make_jpeg((W, H), c)) for c in ("red", "green", "blue", "white")]
    ids = sorted(i["id"] for i in upload(client, pid, *files).json()["uploaded"])
    r1, r_empty, auto, unl = ids

    def ann(iid, cid, box, approved=True, source="manual"):
        db.add(Annotation(image_id=iid, class_id=cid, x_min=box[0], y_min=box[1], x_max=box[2],
                          y_max=box[3], source=source, is_approved=approved,
                          confidence=None if approved else 0.4))  # fmt: skip

    ann(r1, pallet, (0.1, 0.2, 0.5, 0.6))
    ann(r1, person, (0.5, 0.5, 1.0, 1.0))
    ann(auto, pallet, (0.0, 0.0, 0.25, 0.5), approved=False, source="ai:owlv2_text")
    for iid, status in ((r1, "reviewed"), (r_empty, "reviewed"), (auto, "auto_labeled")):
        db.get(Image, iid).status = status
    db.commit()
    return {"pid": pid, "ids": ids, "pallet": pallet, "person": person}


def export(client, pid, **body):
    body = {"split": {"train": 1, "val": 0, "test": 0}} | body
    r = client.post(f"/api/projects/{pid}/export", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(r.content))


def test_yolo_export_reviewed_only(client, ds):
    zf = export(client, ds["pid"], format="yolo")
    names = sorted(zf.namelist())
    r1, r_empty = ds["ids"][0], ds["ids"][1]
    assert names == sorted([
        "data.yaml", "export_info.json",
        f"images/train/{r1:06d}_cam_red.jpg", f"labels/train/{r1:06d}_cam_red.txt",
        f"images/train/{r_empty:06d}_cam_green.jpg", f"labels/train/{r_empty:06d}_cam_green.txt",
    ])  # fmt: skip

    lines = zf.read(f"labels/train/{r1:06d}_cam_red.txt").decode().splitlines()
    # pallet index 0 (urutan class), person index 1; koordinat cx cy w h ternormalisasi
    assert lines == ["0 0.300000 0.400000 0.400000 0.400000", "1 0.750000 0.750000 0.500000 0.500000"]
    for line in lines:
        cls, *yolo = line.split()
        assert all(0 <= v <= 1 for v in yolo_to_norm_xyxy([float(v) for v in yolo]))
    # gambar reviewed tanpa objek → file label kosong (contoh negatif)
    assert zf.read(f"labels/train/{r_empty:06d}_cam_green.txt") == b""
    # gambar di zip identik dengan aslinya
    img = PILImage.open(io.BytesIO(zf.read(f"images/train/{r1:06d}_cam_red.jpg")))
    assert img.size == (W, H)

    yaml = zf.read("data.yaml").decode()
    assert "train: images/train" in yaml and "val: images/train" in yaml
    assert 'nc: 2' in yaml and '  0: "pallet"' in yaml and '  1: "person"' in yaml
    info = json.loads(zf.read("export_info.json"))
    assert info["images"] == 2 and info["per_class"] == {"pallet": 1, "person": 1}


def test_unlabeled_never_exported_and_auto_labeled_optional(client, ds):
    unl = ds["ids"][3]
    zf = export(client, ds["pid"], format="yolo", reviewed_only=False)
    labels = [n for n in zf.namelist() if n.startswith("labels/")]
    assert len(labels) == 3
    assert not any(f"{unl:06d}_" in n for n in zf.namelist())
    auto = ds["ids"][2]
    assert zf.read(f"labels/train/{auto:06d}_cam_blue.txt").decode() == "0 0.125000 0.250000 0.250000 0.500000\n"


def test_yolo_split_dirs(client, ds):
    zf = export(client, ds["pid"], reviewed_only=False, split={"train": 0.6, "val": 0.4, "test": 0})
    imgs = [n for n in zf.namelist() if n.startswith("images/")]
    assert {n.split("/")[1] for n in imgs} == {"train", "val"}
    yaml = zf.read("data.yaml").decode()
    assert "val: images/val" in yaml and "test:" not in yaml
    for n in imgs:  # setiap gambar punya label di split yang sama
        stem = n.split("/")[-1].rsplit(".", 1)[0]
        assert f"labels/{n.split('/')[1]}/{stem}.txt" in zf.namelist()


def test_coco_export(client, ds):
    zf = export(client, ds["pid"], format="coco")
    coco = json.loads(zf.read("annotations/instances_train.json"))
    assert [c["name"] for c in coco["categories"]] == ["pallet", "person"]
    assert [c["id"] for c in coco["categories"]] == [1, 2]
    r1 = ds["ids"][0]
    img = next(i for i in coco["images"] if i["id"] == r1)
    assert (img["width"], img["height"], img["file_name"]) == (W, H, f"{r1:06d}_cam_red.jpg")
    anns = sorted(coco["annotations"], key=lambda a: a["category_id"])
    # pallet (0.1,0.2)-(0.5,0.6) pada 400x200 → x=40 y=40 w=160 h=80
    assert anns[0]["bbox"] == [40.0, 40.0, 160.0, 80.0] and anns[0]["area"] == 12800.0
    assert anns[0]["category_id"] == 1 and anns[1]["category_id"] == 2
    assert anns[1]["bbox"] == [200.0, 100.0, 200.0, 100.0]
    assert len({a["id"] for a in coco["annotations"]}) == len(coco["annotations"])
    assert f"images/train/{r1:06d}_cam_red.jpg" in zf.namelist()
    assert "annotations/instances_val.json" not in zf.namelist()


def test_preview_and_errors(client, ds, project):
    p = client.post(f"/api/projects/{ds['pid']}/export/preview",
                    json={"reviewed_only": False, "split": {"train": 0.5, "val": 0.5}}).json()  # fmt: skip
    assert p["images"] == 3 and p["annotations"] == 3 and p["empty_images"] == 1
    assert sum(p["splits"].values()) == 3

    bad = client.post(f"/api/projects/{ds['pid']}/export", json={"split": {"train": 0, "val": 1}})
    assert bad.status_code == 422

    empty = client.post("/api/projects", json={"name": "kosong"}).json()["id"]
    r = client.post(f"/api/projects/{empty}/export", json={})
    assert r.status_code == 422 and "reviewed" in r.json()["detail"]
