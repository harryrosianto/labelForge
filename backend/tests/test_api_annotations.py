import io

import pytest
from PIL import Image as PILImage

from labelforge.models import Annotation, ClassExemplar, Image
from tests.test_api_images import upload
from tests.test_images_service import make_jpeg


@pytest.fixture
def img(client, project, db):
    pid = project["id"]
    pallet = client.post(f"/api/projects/{pid}/classes", json={"name": "pallet"}).json()["id"]
    person = client.post(f"/api/projects/{pid}/classes", json={"name": "person"}).json()["id"]
    image = upload(client, pid, ("a.jpg", make_jpeg((400, 200)))).json()["uploaded"][0]
    ai = Annotation(image_id=image["id"], class_id=pallet, x_min=0.1, y_min=0.1, x_max=0.5,
                    y_max=0.5, source="ai:owlv2_text", confidence=0.42)  # fmt: skip
    ai2 = Annotation(image_id=image["id"], class_id=pallet, x_min=0.6, y_min=0.6, x_max=0.7,
                     y_max=0.7, source="ai:owlv2_text", confidence=0.2)  # fmt: skip
    db.add_all([ai, ai2])
    db.get(Image, image["id"]).status = "auto_labeled"
    db.commit()
    return {"pid": pid, "id": image["id"], "pallet": pallet, "person": person, "ai": ai.id, "ai2": ai2.id}


def put(client, image_id, annotations, approve=False):
    return client.put(f"/api/images/{image_id}/annotations",
                      json={"annotations": annotations, "approve": approve})  # fmt: skip


def box(**kw):
    return {"x_min": 0.2, "y_min": 0.2, "x_max": 0.4, "y_max": 0.4, "is_approved": True} | kw


def test_save_set_updates_adds_and_deletes(client, img):
    r = put(client, img["id"], [
        # AI box dipindah & ganti class → sumber & confidence tetap, kini approved
        box(id=img["ai"], class_id=img["person"], x_min=0.15),
        # box baru manual (sudut terbalik dirapikan)
        box(class_id=img["pallet"], x_min=0.9, x_max=0.8, y_min=0.3, y_max=0.1),
        # ai2 tidak dikirim → dihapus
    ])  # fmt: skip
    assert r.status_code == 200, r.text
    anns = sorted(r.json()["annotations"], key=lambda a: a["source"])
    assert len(anns) == 2
    ai, manual = anns
    assert (manual["source"], manual["is_approved"]) == ("manual", True)
    assert (manual["x_min"], manual["x_max"], manual["y_min"], manual["y_max"]) == pytest.approx((0.8, 0.9, 0.1, 0.3))
    assert ai["id"] == img["ai"] and ai["class_id"] == img["person"]
    assert (ai["source"], ai["confidence"], ai["x_min"]) == ("ai:owlv2_text", 0.42, pytest.approx(0.15))
    assert r.json()["status"] == "auto_labeled"  # simpan saja tidak mengubah status


def test_save_keeps_unapproved_ai_when_requested(client, img):
    r = put(client, img["id"], [box(id=img["ai"], class_id=img["pallet"], is_approved=False)])
    assert r.json()["annotations"][0]["is_approved"] is False


def test_approve_via_save_and_endpoint(client, img):
    r = put(client, img["id"], [box(id=img["ai"], class_id=img["pallet"], is_approved=False)], approve=True)
    assert r.json()["status"] == "reviewed"
    assert all(a["is_approved"] for a in r.json()["annotations"])

    r = client.post(f"/api/images/{img['id']}/approve").json()
    assert r["status"] == "reviewed"


def test_approve_empty_image_is_reviewed_negative(client, img):
    # Gambar tanpa objek tetap bisa di-review (berguna sebagai contoh negatif)
    r = put(client, img["id"], [], approve=True)
    assert r.json()["status"] == "reviewed" and r.json()["annotations"] == []


@pytest.mark.parametrize(
    "annotations,message",
    [
        ([box(class_id=9999)], "bukan milik project"),
        ([box(id=123456, class_id=0)], "bukan milik"),
        ([box(class_id=0, x_min=0.3, x_max=0.3)], "terlalu kecil"),
        ([box(class_id=0, x_min=1.5, x_max=2.0)], "terlalu kecil"),
    ],
)
def test_save_validation(client, img, annotations, message):
    for a in annotations:
        if a["class_id"] == 0:
            a["class_id"] = img["pallet"]
    r = put(client, img["id"], annotations)
    assert r.status_code == 422 and message in r.json()["detail"]
    # transaksi dibatalkan: anotasi lama utuh
    assert len(client.get(f"/api/images/{img['id']}").json()["annotations"]) == 2


def test_duplicate_id_rejected(client, img):
    a = box(id=img["ai"], class_id=img["pallet"])
    assert put(client, img["id"], [a, a]).status_code == 422


def test_exemplar_lifecycle(client, img, storage, db):
    r = client.post(f"/api/annotations/{img['ai']}/exemplar")
    assert r.status_code == 201, r.text
    ex = r.json()
    # box 0.1..0.5 pada gambar 400x200 → crop 160x80
    assert (ex["class_id"], ex["width"], ex["height"]) == (img["pallet"], 160, 80)
    assert ex["source_image_id"] == img["id"]

    png = client.get(f"/api/exemplars/{ex['id']}/image")
    assert PILImage.open(io.BytesIO(png.content)).size == (160, 80)
    assert [e["id"] for e in client.get(f"/api/classes/{img['pallet']}/exemplars").json()] == [ex["id"]]
    assert client.get(f"/api/projects/{img['pid']}/classes").json()[0]["exemplar_count"] == 1

    # menghapus anotasi/gambar asal tidak menghapus exemplar
    put(client, img["id"], [])
    db.expire_all()
    assert db.get(ClassExemplar, ex["id"]).source_annotation_id is None

    key = db.get(ClassExemplar, ex["id"]).crop_storage_key
    assert client.delete(f"/api/exemplars/{ex['id']}").status_code == 204
    assert not storage.exists(key)


def test_exemplar_too_small(client, img, db):
    tiny = Annotation(image_id=img["id"], class_id=img["pallet"], x_min=0.1, y_min=0.1,
                      x_max=0.11, y_max=0.11, source="manual", is_approved=True)  # fmt: skip
    db.add(tiny)
    db.commit()
    r = client.post(f"/api/annotations/{tiny.id}/exemplar")
    assert r.status_code == 422 and "terlalu kecil" in r.json()["detail"]
