import io
import zipfile

import pytest

from labelforge.models import Annotation, Image
from tests.test_images_service import make_jpeg


def upload(client, pid, *files):
    return client.post(f"/api/projects/{pid}/images", files=[("files", f) for f in files])


def make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_upload_multi_and_zip(client, project, storage):
    pid = project["id"]
    zip_bytes = make_zip({
        "cam/a.jpg": make_jpeg(color="blue"),
        "cam/readme.txt": b"x",
        "__MACOSX/cam/._a.jpg": b"junk",
        "cam/dup.jpg": make_jpeg(color="red"),   # duplikat file pertama
        "cam/broken.png": b"not an image",
    })  # fmt: skip
    r = upload(
        client, pid,
        ("one.jpg", make_jpeg(color="red"), "image/jpeg"),
        ("notes.pdf", b"%PDF", "application/pdf"),
        ("batch.zip", zip_bytes, "application/zip"),
    )  # fmt: skip
    assert r.status_code == 201, r.text
    res = r.json()
    assert sorted(i["original_filename"] for i in res["uploaded"]) == ["a.jpg", "one.jpg"]
    assert [d["filename"] for d in res["duplicates"]] == ["batch.zip/cam/dup.jpg"]
    assert sorted(s["filename"] for s in res["skipped"]) == ["batch.zip/cam/readme.txt", "notes.pdf"]
    assert [e["filename"] for e in res["errors"]] == ["batch.zip/cam/broken.png"]

    img = res["uploaded"][0]
    assert client.get(f"/api/images/{img['id']}/file").content.startswith(b"\xff\xd8")
    thumb = client.get(f"/api/images/{img['id']}/thumb")
    assert thumb.headers["content-type"] == "image/jpeg" and "immutable" in thumb.headers["cache-control"]


def test_upload_bad_zip(client, project):
    res = upload(client, project["id"], ("x.zip", b"not zip", "application/zip")).json()
    assert res["errors"][0]["detail"].startswith("ZIP rusak")


@pytest.fixture
def gallery(client, project, db):
    """5 gambar dengan kombinasi status/anotasi berbeda."""
    pid = project["id"]
    pallet = client.post(f"/api/projects/{pid}/classes", json={"name": "pallet"}).json()["id"]
    person = client.post(f"/api/projects/{pid}/classes", json={"name": "person"}).json()["id"]
    colors = ["red", "green", "blue", "yellow", "white"]
    ids = [i["id"] for i in upload(client, pid, *[(f"{c}.jpg", make_jpeg(color=c)) for c in colors]).json()["uploaded"]]
    ids.sort()

    def ann(iid, cid, source, conf=None, approved=False):
        db.add(Annotation(image_id=iid, class_id=cid, x_min=0.1, y_min=0.1, x_max=0.5,
                          y_max=0.5, source=source, confidence=conf, is_approved=approved))  # fmt: skip

    ann(ids[0], pallet, "ai:owlv2_text", 0.9)
    ann(ids[1], pallet, "ai:owlv2_text", 0.2)                 # confidence rendah
    ann(ids[2], person, "manual", approved=True)
    ann(ids[3], person, "ai:grounding_dino", 0.1, approved=True)  # rendah tapi sudah approved
    for iid, status in zip(ids, ["auto_labeled", "auto_labeled", "reviewed", "reviewed"]):
        db.get(Image, iid).status = status
    db.commit()
    return {"pid": pid, "ids": ids, "pallet": pallet, "person": person}


def ids_for(client, pid, **params):
    r = client.get(f"/api/projects/{pid}/images", params=params)
    assert r.status_code == 200, r.text
    return [i["id"] for i in r.json()["items"]]


def test_gallery_filters(client, gallery):
    pid, ids = gallery["pid"], gallery["ids"]
    assert ids_for(client, pid) == ids
    assert ids_for(client, pid, status="unlabeled") == [ids[4]]
    assert ids_for(client, pid, status="reviewed") == [ids[2], ids[3]]
    assert ids_for(client, pid, class_id=gallery["pallet"]) == [ids[0], ids[1]]
    assert ids_for(client, pid, source="manual") == [ids[2]]
    assert ids_for(client, pid, source="ai") == [ids[0], ids[1], ids[3]]
    assert ids_for(client, pid, source="ai:grounding_dino") == [ids[3]]
    assert ids_for(client, pid, max_conf=0.5) == [ids[1]]
    assert ids_for(client, pid, status="auto_labeled", max_conf=0.95) == [ids[0], ids[1]]


def test_gallery_pagination_and_annotations(client, gallery):
    r = client.get(f"/api/projects/{gallery['pid']}/images", params={"page": 2, "page_size": 2}).json()
    assert r["total"] == 5 and [i["id"] for i in r["items"]] == gallery["ids"][2:4]
    assert r["items"][0]["annotations"][0]["source"] == "manual"


def test_image_detail_neighbours_follow_filter(client, gallery):
    ids = gallery["ids"]
    d = client.get(f"/api/images/{ids[2]}").json()
    assert (d["prev_id"], d["next_id"], d["position"], d["filtered_total"]) == (ids[1], ids[3], 3, 5)

    d = client.get(f"/api/images/{ids[1]}", params={"source": "ai"}).json()
    assert (d["prev_id"], d["next_id"], d["position"], d["filtered_total"]) == (ids[0], ids[3], 2, 3)

    # gambar di luar filter (mis. baru di-approve) tetap bisa navigasi ke tetangga terdekat
    d = client.get(f"/api/images/{ids[2]}", params={"status": "auto_labeled"}).json()
    assert (d["prev_id"], d["next_id"], d["position"]) == (ids[1], None, None)
    assert d["annotations"][0]["class_id"] == gallery["person"]


def test_delete_images(client, gallery, storage, db):
    pid, ids = gallery["pid"], gallery["ids"]
    key = db.get(Image, ids[0]).storage_key
    assert client.delete(f"/api/images/{ids[0]}").status_code == 204
    assert not storage.exists(key)
    assert client.get(f"/api/images/{ids[0]}").status_code == 404

    r = client.post(f"/api/projects/{pid}/images/bulk-delete", json={"image_ids": ids[1:3] + [9999]})
    assert r.json() == {"deleted": 2}
    assert ids_for(client, pid) == ids[3:]
    db.expire_all()
    assert db.query(Annotation).count() == 1  # anotasi ikut terhapus
