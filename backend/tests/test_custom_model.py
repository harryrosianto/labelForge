import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper, numpy_helper
from PIL import Image as PILImage

from labelforge.models import Annotation, Image
from labelforge.providers import registry
from labelforge.providers.onnx_yolo import OnnxModelError, decode, letterbox, read_model_info
from labelforge.services.images import ingest_image
from tests.test_images_service import make_jpeg

# Kandidat dalam koordinat letterbox 64x64 (cx, cy, w, h) dan skor per class [pallet, person].
CANDIDATES = [
    ((16, 24, 8, 8), (0.9, 0.1)),   # pallet
    ((48, 40, 16, 16), (0.2, 0.8)),  # person
    ((49, 40, 16, 16), (0.1, 0.7)),  # duplikat person, dibuang NMS
    ((30, 30, 4, 4), (0.05, 0.1)),   # di bawah threshold
]  # fmt: skip


def make_onnx(path, names=("pallet", "person"), task="detect", end2end=False, size=64):
    """Model ONNX kecil: output konstan [1, 4+nc, N] (atau [1, N, 6]) + metadata gaya Ultralytics."""
    if end2end:
        rows = [[cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, max(s), int(np.argmax(s))]
                for (cx, cy, w, h), s in CANDIDATES]  # fmt: skip
        value = np.array([rows], dtype=np.float32)
    else:
        value = np.array([[[*b, *s] for b, s in CANDIDATES]], dtype=np.float32).transpose(0, 2, 1)
    node = helper.make_node("Constant", [], ["output0"], value=numpy_helper.from_array(value))
    graph = helper.make_graph(
        [node], "tiny",
        [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, size, size])],
        [helper.make_tensor_value_info("output0", TensorProto.FLOAT, list(value.shape))],
    )  # fmt: skip
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    meta = {"task": task, "imgsz": f"[{size}, {size}]", "end2end": str(end2end),
            "names": str(dict(enumerate(names)))}  # fmt: skip
    for k, v in meta.items():
        model.metadata_props.add(key=k, value=v)
    onnx.save(model, str(path))
    return path


def test_letterbox_and_decode_back_to_original_coordinates():
    image = PILImage.new("RGB", (128, 64))  # skala 0,5 → 64x32, padding atas/bawah 16
    tensor, scale, pad = letterbox(image, (64, 64))
    assert tensor.shape == (1, 3, 64, 64) and scale == 0.5 and pad == (0, 16)
    out = np.array([[[*b, *s] for b, s in CANDIDATES]], dtype=np.float32).transpose(0, 2, 1)
    dets = decode(out, False, 0.25, scale, pad)
    assert [d[0] for d in dets] == [0, 1, 1]  # urut skor, kandidat lemah dibuang
    assert dets[0][1:5] == pytest.approx((24, 8, 40, 24))  # (16±4, 24±4) → ((x-0)/0,5, (y-16)/0,5)


def test_read_model_info(tmp_path):
    info = read_model_info(make_onnx(tmp_path / "m.onnx"))
    assert (info.names, info.input_size, info.end2end) == (["pallet", "person"], (64, 64), False)
    assert read_model_info(make_onnx(tmp_path / "e.onnx", end2end=True)).end2end
    with pytest.raises(OnnxModelError, match="bukan deteksi"):
        read_model_info(make_onnx(tmp_path / "seg.onnx", task="segment"))
    (tmp_path / "rusak.onnx").write_bytes(b"bukan onnx")
    with pytest.raises(OnnxModelError, match="bukan model ONNX"):
        read_model_info(tmp_path / "rusak.onnx")


@pytest.fixture
def proj(client, project, db, storage):
    pid = project["id"]
    pallet = client.post(f"/api/projects/{pid}/classes", json={"name": "Pallet"}).json()["id"]
    goods = client.post(f"/api/projects/{pid}/classes", json={"name": "goods"}).json()["id"]
    image = ingest_image(db, storage, pid, "cam.jpg", make_jpeg((128, 64), "gray")).image.id
    db.commit()
    yield {"pid": pid, "pallet": pallet, "goods": goods, "image": image}
    registry._CUSTOM.clear()
    for name in [n for n in registry._INSTANCES if n.startswith("model:")]:
        registry._INSTANCES.pop(name)


def upload_model(client, pid, path, **form):
    with open(path, "rb") as f:
        return client.post(f"/api/projects/{pid}/models", files={"file": (path.name, f)}, data=form)


@pytest.mark.parametrize("end2end", [False, True])
def test_upload_map_and_autolabel(client, proj, db, tmp_path, end2end):
    pid = proj["pid"]
    r = upload_model(client, pid, make_onnx(tmp_path / "best.onnx", end2end=end2end),
                     name="yolo v1", map50="0.947", map50_95="0.803")  # fmt: skip
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["provider"] == f"model:{m['id']}" and m["names"] == ["pallet", "person"]
    assert m["class_map"] == {"0": proj["pallet"], "1": None}  # nama sama (beda huruf) dipetakan
    assert m["metrics"] == {"map50": 0.947, "map50_95": 0.803}

    providers = client.get("/api/providers", params={"project_id": pid}).json()
    assert providers[0]["name"] == m["provider"] and providers[0]["custom"] and providers[0]["available"]
    assert not any(p["name"].startswith("model:") for p in client.get("/api/providers").json())

    job = client.post(f"/api/projects/{pid}/jobs/autolabel",
                      json={"provider": m["provider"], "target": "all"}).json()  # fmt: skip
    assert job["warnings"] == ["Class 'goods' tidak dikenali model ini"]
    job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "completed", job["error"]
    db.expire_all()
    anns = db.query(Annotation).filter_by(image_id=proj["image"]).all()
    assert [(a.class_id, a.source) for a in anns] == [(proj["pallet"], f"ai:model:{m['id']}")]
    a = anns[0]
    assert (a.x_min, a.y_min, a.x_max, a.y_max) == pytest.approx((24 / 128, 8 / 64, 40 / 128, 24 / 64))
    assert a.confidence == pytest.approx(0.9)
    assert db.get(Image, proj["image"]).status == "auto_labeled"
    assert client.get(f"/api/projects/{pid}/models").json()[0]["annotations"] == 1


def test_remap_classes_reloads_provider(client, proj, db, tmp_path):
    pid = proj["pid"]
    m = upload_model(client, pid, make_onnx(tmp_path / "best.onnx")).json()
    r = client.patch(f"/api/models/{m['id']}", json={"class_map": {"0": None, "1": proj["goods"]},
                                                      "notes": "person = goods"})  # fmt: skip
    assert r.status_code == 200 and r.json()["class_map"] == {"0": None, "1": proj["goods"]}
    client.post(f"/api/projects/{pid}/jobs/autolabel", json={"provider": m["provider"], "target": "all"})
    db.expire_all()
    anns = db.query(Annotation).filter_by(image_id=proj["image"]).all()
    assert [a.class_id for a in anns] == [proj["goods"]]  # duplikat person sudah dibuang NMS

    assert client.patch(f"/api/models/{m['id']}", json={"class_map": {"0": 999}}).status_code == 422
    r = client.patch(f"/api/models/{m['id']}", json={"class_map": {"0": None, "1": None}})
    providers = client.get("/api/providers", params={"project_id": pid}).json()
    assert providers[0]["available"] is False
    r = client.post(f"/api/projects/{pid}/jobs/autolabel", json={"provider": m["provider"], "target": "all"})
    assert r.status_code == 422 and "belum ada class" in r.json()["detail"]


def test_upload_validation_and_delete(client, proj, tmp_path, storage):
    pid = proj["pid"]
    (tmp_path / "x.pt").write_bytes(b"x")
    assert upload_model(client, pid, tmp_path / "x.pt").status_code == 422
    r = upload_model(client, pid, make_onnx(tmp_path / "s.onnx", task="segment"))
    assert r.status_code == 422 and "detect" in r.json()["detail"]
    assert upload_model(client, pid, make_onnx(tmp_path / "v.onnx"), dataset_version_id="999").status_code == 422

    m = upload_model(client, pid, make_onnx(tmp_path / "best.onnx")).json()
    key = next(storage.root.glob(f"projects/{pid}/models/*.onnx"))
    other = client.post("/api/projects", json={"name": "lain"}).json()["id"]
    r = client.post(f"/api/projects/{other}/jobs/autolabel", json={"provider": m["provider"], "target": "all"})
    assert r.status_code == 422

    assert client.delete(f"/api/models/{m['id']}").status_code == 204
    assert not key.exists() and client.get(f"/api/projects/{pid}/models").json() == []
    r = client.post(f"/api/projects/{pid}/jobs/autolabel", json={"provider": m["provider"], "target": "all"})
    assert r.status_code == 422 and "tidak ditemukan" in r.json()["detail"]
