import pytest

from labelforge.models import Annotation, Image, ReviewAuditItem
from tests.test_api_images import upload
from tests.test_images_service import make_jpeg


@pytest.fixture
def pool(client, project, db):
    """10 gambar import auto-label (1 box), 1 auto-label tanpa box, 1 reviewed, 1 unlabeled."""
    pid = project["id"]
    cid = client.post(f"/api/projects/{pid}/classes", json={"name": "pallet"}).json()["id"]
    files = [(f"f{i}.jpg", make_jpeg((64, 48), (i * 15, 80, 120))) for i in range(13)]
    ids = sorted(i["id"] for i in upload(client, pid, *files).json()["uploaded"])
    imported, empty, reviewed, unlabeled = ids[:10], ids[10], ids[11], ids[12]
    for iid in imported + [reviewed]:
        db.add(Annotation(image_id=iid, class_id=cid, x_min=0.1, y_min=0.1, x_max=0.5, y_max=0.5,
                          source="import:yolo", is_approved=iid == reviewed))  # fmt: skip
        db.get(Image, iid).status = "reviewed" if iid == reviewed else "auto_labeled"
    db.get(Image, empty).status = "auto_labeled"
    db.commit()
    return {"pid": pid, "cid": cid, "imported": imported, "empty": empty, "reviewed": reviewed,
            "unlabeled": unlabeled}  # fmt: skip


def bulk(client, pid, **body):
    r = client.post(f"/api/projects/{pid}/images/bulk-status", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def statuses(client, pid, **filters) -> dict[str, int]:
    out: dict[str, int] = {}
    for img in client.get(f"/api/projects/{pid}/images", params={"page_size": 100, **filters}).json()["items"]:
        out[img["status"]] = out.get(img["status"], 0) + 1
    return out


def test_bulk_approve_by_filter_dry_run_then_apply(client, pool, db):
    pid = pool["pid"]
    dry = bulk(client, pid, status="reviewed", dry_run=True)
    assert dry == {"matched": 13, "changed": 11, "without_boxes": 1, "skipped_unlabeled": 1}
    assert statuses(client, pid)["auto_labeled"] == 11  # dry run tidak mengubah apa pun

    # Hanya hasil filter sumber import: gambar tanpa box (bukan import) tidak ikut.
    r = bulk(client, pid, status="reviewed", filters={"source": "import:yolo", "status": "auto_labeled"})
    assert r == {"matched": 10, "changed": 10, "without_boxes": 0, "skipped_unlabeled": 0}
    assert statuses(client, pid) == {"reviewed": 11, "auto_labeled": 1, "unlabeled": 1}
    db.expire_all()
    assert all(a.is_approved for a in db.query(Annotation).all())


def test_bulk_unapprove_and_selected_ids(client, pool, db):
    pid = pool["pid"]
    picked = pool["imported"][:3] + [pool["reviewed"], pool["unlabeled"]]
    r = bulk(client, pid, status="reviewed", image_ids=picked)
    assert (r["matched"], r["changed"], r["skipped_unlabeled"]) == (5, 3, 1)

    r = bulk(client, pid, status="auto_labeled", image_ids=picked)
    assert (r["matched"], r["changed"]) == (5, 4)  # 3 tadi + 1 yang memang reviewed
    assert statuses(client, pid) == {"auto_labeled": 12, "unlabeled": 1}
    db.expire_all()
    assert not any(a.is_approved for a in db.query(Annotation).all())


def test_bulk_status_validation(client, pool):
    url = f"/api/projects/{pool['pid']}/images/bulk-status"
    assert client.post(url, json={"status": "unlabeled"}).status_code == 422
    assert client.post("/api/projects/999/images/bulk-status", json={"status": "reviewed"}).status_code == 404


def test_audit_sample_navigation_and_summary(client, pool, db):
    pid = pool["pid"]
    r = client.post(f"/api/projects/{pid}/audits",
                    json={"filters": {"source": "import:yolo"}, "size": 4, "seed": 1})  # fmt: skip
    assert r.status_code == 201, r.text
    audit = r.json()
    assert (audit["population"], audit["sample_size"]) == (10, 4)
    assert audit["filters"] == {"source": "import:yolo"}
    assert audit["summary"] == {"checked": 0, "approved_unchanged": 0, "corrected": 0, "pending": 4,
                                "removed": 0, "error_rate": None}  # fmt: skip

    sample = [i["id"] for i in client.get(f"/api/projects/{pid}/images",
                                          params={"audit_id": audit["id"]}).json()["items"]]  # fmt: skip
    assert len(sample) == 4 and set(sample) <= set(pool["imported"])
    detail = client.get(f"/api/images/{sample[0]}", params={"audit_id": audit["id"]}).json()
    assert (detail["position"], detail["filtered_total"], detail["next_id"]) == (1, 4, sample[1])

    # Gambar 1: approve tanpa ubah. Gambar 2: box digeser lalu approve. Gambar 3: dikoreksi, belum approve.
    assert client.post(f"/api/images/{sample[0]}/approve").status_code == 200
    for iid, approve in ((sample[1], True), (sample[2], False)):
        box = client.get(f"/api/images/{iid}").json()["annotations"][0]
        box["x_max"] = 0.7
        r = client.put(f"/api/images/{iid}/annotations", json={"annotations": [box], "approve": approve})
        assert r.status_code == 200, r.text

    s = client.get(f"/api/audits/{audit['id']}").json()["summary"]
    assert s == {"checked": 3, "approved_unchanged": 1, "corrected": 2, "pending": 1,
                 "removed": 0, "error_rate": round(2 / 3, 4)}  # fmt: skip

    # Daftar audit: terbaru di atas.
    again = client.post(f"/api/projects/{pid}/audits",
                        json={"filters": {"source": "import:yolo"}, "size": 4, "seed": 1}).json()  # fmt: skip
    assert again["population"] == 8  # 2 gambar yang sudah di-approve tidak termasuk populasi
    assert [a["id"] for a in client.get(f"/api/projects/{pid}/audits").json()] == [again["id"], audit["id"]]


def test_audit_only_samples_auto_labeled(client, pool):
    pid = pool["pid"]
    audit = client.post(f"/api/projects/{pid}/audits", json={"size": 500}).json()
    assert audit["population"] == audit["sample_size"] == 11  # reviewed & unlabeled tidak diambil
    r = client.post(f"/api/projects/{pid}/audits", json={"filters": {"status": "reviewed"}})
    assert r.status_code == 422


def test_delete_audit_and_image(client, pool, db):
    pid = pool["pid"]
    audit = client.post(f"/api/projects/{pid}/audits", json={"size": 3, "seed": 5}).json()
    first = client.get(f"/api/projects/{pid}/images", params={"audit_id": audit["id"]}).json()["items"][0]
    assert client.delete(f"/api/images/{first['id']}").status_code == 204
    s = client.get(f"/api/audits/{audit['id']}").json()["summary"]
    assert (s["pending"], s["removed"]) == (2, 1)

    assert client.delete(f"/api/audits/{audit['id']}").status_code == 204
    assert client.get(f"/api/audits/{audit['id']}").status_code == 404
    db.expire_all()
    assert db.query(ReviewAuditItem).count() == 0
    assert statuses(client, pid)["auto_labeled"] == 10  # gambar & label tidak ikut terhapus
