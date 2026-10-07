from labelforge.models import Annotation, Image


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_project_crud(client):
    r = client.post("/api/projects", json={"name": "  Gudang A ", "description": "CCTV"})
    assert r.status_code == 201
    p = r.json()
    assert p["name"] == "Gudang A"
    assert p["task_type"] == "object_detection"
    assert p["image_count"] == 0

    assert [x["id"] for x in client.get("/api/projects").json()] == [p["id"]]

    r = client.patch(f"/api/projects/{p['id']}", json={"description": "baru"})
    assert r.json()["description"] == "baru" and r.json()["name"] == "Gudang A"

    assert client.delete(f"/api/projects/{p['id']}").status_code == 204
    assert client.get(f"/api/projects/{p['id']}").status_code == 404


def test_project_validation(client):
    assert client.post("/api/projects", json={"name": "   "}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "task_type": "foo"}).status_code == 422


def test_delete_project_removes_files(client, project, storage):
    key = f"projects/{project['id']}/images/a.jpg"
    storage.save_bytes(key, b"x")
    client.delete(f"/api/projects/{project['id']}")
    assert not storage.exists(key)


def test_class_crud_and_prompt(client, project):
    pid = project["id"]
    r = client.post(f"/api/projects/{pid}/classes", json={"name": " Pallet "})
    assert r.status_code == 201
    pallet = r.json()
    assert pallet["name"] == "Pallet"
    assert pallet["effective_prompt"] == "Pallet"
    assert pallet["color"].startswith("#") and pallet["order_index"] == 0

    r = client.patch(f"/api/classes/{pallet['id']}", json={"text_prompt": "wooden  pallet"})
    assert r.json()["effective_prompt"] == "wooden pallet"

    # null mengembalikan prompt ke default nama class
    r = client.patch(f"/api/classes/{pallet['id']}", json={"text_prompt": None})
    assert r.json()["text_prompt"] is None and r.json()["effective_prompt"] == "Pallet"

    assert client.patch(f"/api/classes/{pallet['id']}", json={"color": "red"}).status_code == 422


def test_class_name_unique_case_insensitive(client, project):
    pid = project["id"]
    client.post(f"/api/projects/{pid}/classes", json={"name": "person"})
    assert client.post(f"/api/projects/{pid}/classes", json={"name": "Person"}).status_code == 409
    other = client.post(f"/api/projects/{pid}/classes", json={"name": "forklift"}).json()
    r = client.patch(f"/api/classes/{other['id']}", json={"name": "PERSON"})
    assert r.status_code == 409


def test_class_order_and_reindex_on_delete(client, project):
    pid = project["id"]
    ids = [
        client.post(f"/api/projects/{pid}/classes", json={"name": n}).json()["id"]
        for n in ("pallet", "person", "forklift")
    ]
    r = client.put(f"/api/projects/{pid}/classes/order", json={"class_ids": ids[::-1]})
    assert [(c["id"], c["order_index"]) for c in r.json()] == [(ids[2], 0), (ids[1], 1), (ids[0], 2)]

    bad = client.put(f"/api/projects/{pid}/classes/order", json={"class_ids": ids[:2]})
    assert bad.status_code == 422

    client.delete(f"/api/classes/{ids[1]}")
    remaining = client.get(f"/api/projects/{pid}/classes").json()
    assert [(c["id"], c["order_index"]) for c in remaining] == [(ids[2], 0), (ids[0], 1)]


def test_delete_class_cascades_annotations_and_stats(client, project, db):
    pid = project["id"]
    pallet = client.post(f"/api/projects/{pid}/classes", json={"name": "pallet"}).json()
    person = client.post(f"/api/projects/{pid}/classes", json={"name": "person"}).json()

    img = Image(
        project_id=pid, original_filename="a.jpg", storage_key="k", thumb_key="t",
        width=100, height=100, sha256="abc", status="auto_labeled",
    )  # fmt: skip
    db.add(img)
    db.flush()
    db.add_all(
        [
            Annotation(image_id=img.id, class_id=pallet["id"], x_min=0, y_min=0, x_max=0.5,
                       y_max=0.5, source="ai:grounding_dino", confidence=0.8),
            Annotation(image_id=img.id, class_id=person["id"], x_min=0, y_min=0, x_max=0.2,
                       y_max=0.2, source="manual", is_approved=True),
        ]
    )  # fmt: skip
    db.commit()

    stats = client.get(f"/api/projects/{pid}/stats").json()
    assert stats["total_images"] == 1
    assert stats["images_by_status"] == {"unlabeled": 0, "auto_labeled": 1, "reviewed": 0}
    assert stats["annotations_by_source"] == {"ai:grounding_dino": 1, "manual": 1}
    assert stats["unapproved_annotations"] == 1
    assert {c["name"]: c["annotations"] for c in stats["annotations_by_class"]} == {
        "pallet": 1,
        "person": 1,
    }
    classes = client.get(f"/api/projects/{pid}/classes").json()
    assert classes[0]["annotation_count"] == 1

    client.delete(f"/api/classes/{pallet['id']}")
    stats = client.get(f"/api/projects/{pid}/stats").json()
    assert stats["total_annotations"] == 1
    assert stats["annotations_by_source"] == {"manual": 1}
