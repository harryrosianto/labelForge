from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from labelforge.config import get_settings
from labelforge.providers import registry
from labelforge.providers.base import ClassDef, ProviderError
from labelforge.providers.remote_api import RemoteApiProvider
from tests.fakes import FakeProvider


@pytest.fixture(autouse=True)
def fake_registered():
    registry.register_provider(FakeProvider)
    yield
    registry._CLASSES.pop("fake", None)
    registry._INSTANCES.pop("fake", None)
    registry._INSTANCES.pop("remote", None)


@pytest.fixture
def image_path(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (200, 100), "gray").save(path)
    return path


CLASSES = [ClassDef(1, "pallet", "wooden pallet"), ClassDef(2, "person")]


def test_postprocess_clip_nms_filter(image_path):
    dets = registry.get_provider("fake").detect(image_path, CLASSES, {})
    assert [(d.class_id, d.bbox, d.confidence) for d in dets] == [
        (1, (10.0, 10.0, 50.0, 50.0), 0.9),
        (1, (0.0, 90.0, 30.0, 100.0), 0.8),
    ]


def test_exif_orientation_applied(tmp_path):
    path = tmp_path / "rot.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° CW
    Image.new("RGB", (200, 100)).save(path, exif=exif)
    registry.get_provider("fake").detect(path, CLASSES, {})
    assert FakeProvider.last_call["size"] == (100, 200)


def test_params_resolved_and_validated(image_path):
    provider = registry.get_provider("fake")
    provider.detect(image_path, CLASSES, {"nms_iou": "0.3", "class_agnostic_nms": "true"})
    p = FakeProvider.last_call["params"]
    assert p["mode"] == "text" and p["nms_iou"] == 0.3 and p["class_agnostic_nms"] is True
    with pytest.raises(ProviderError):
        provider.detect(image_path, CLASSES, {"nms_iou": 5})
    with pytest.raises(ProviderError):
        provider.detect(image_path, CLASSES, {"mode": "video"})


def test_unknown_provider():
    with pytest.raises(ProviderError):
        registry.get_provider("tidak_ada")


def test_describe_providers_lists_builtins():
    names = {p["name"] for p in registry.describe_providers()}
    assert {"grounding_dino", "owlv2", "remote", "fake"} <= names


def test_owlv2_warns_class_without_exemplar():
    owl = registry.get_provider_class("owlv2")
    with_ex = ClassDef(1, "pallet", exemplar_paths=(Path("x.jpg"),))
    warnings = owl.class_warnings("image_guided", [with_ex, ClassDef(2, "person")])
    assert len(warnings) == 1 and "person" in warnings[0]
    assert owl.class_warnings("text", [ClassDef(2, "person")]) == []
    assert owl.source_tag("image_guided") == "ai:owlv2_image"
    assert owl.source_tag("text") == "ai:owlv2_text"


def test_remote_roundtrip_through_inference_server(image_path, tmp_path, monkeypatch):
    """RemoteApiProvider → inference server (in-process) → FakeProvider."""
    from labelforge.inference_server.app import app

    settings = get_settings()
    monkeypatch.setattr(settings, "remote_inference_url", "http://inference")
    monkeypatch.setattr(settings, "remote_inference_token", "rahasia")
    monkeypatch.setattr(settings, "inference_server_token", "rahasia")
    monkeypatch.setattr("labelforge.providers.remote_api.REMOTE_MODES", ("fake:image_guided",))
    monkeypatch.setattr(RemoteApiProvider, "modes", ("fake:image_guided",))

    server = TestClient(app)
    remote = registry.get_provider("remote")
    remote.load()
    remote.client = httpx.Client(
        transport=server._transport, base_url="http://inference", headers=remote.client.headers
    )

    exemplar = tmp_path / "ex.png"
    exemplar.write_bytes(b"crop-bytes")
    classes = [ClassDef(7, "pallet", "wooden pallet", (exemplar,)), ClassDef(8, "person")]
    dets = remote.detect(image_path, classes, {"mode": "fake:image_guided", "nms_iou": 0.4})

    assert [(d.class_id, d.confidence) for d in dets] == [(7, 0.9), (7, 0.8)]
    call = FakeProvider.last_call
    assert call["params"]["mode"] == "image_guided" and call["params"]["nms_iou"] == 0.4
    assert [c.id for c in call["classes"]] == [7, 8]
    assert call["classes"][0].text_prompt == "wooden pallet"
    assert call["exemplar_bytes"] == [b"crop-bytes"]
    assert RemoteApiProvider.source_tag("fake:image_guided") == "ai:fake"


def test_inference_server_rejects_bad_token(image_path, monkeypatch):
    from labelforge.inference_server.app import app

    monkeypatch.setattr(get_settings(), "inference_server_token", "rahasia")
    client = TestClient(app)
    r = client.post("/v1/detect", data={"payload": "{}"},
                    files={"image": ("a.jpg", image_path.read_bytes())},
                    headers={"Authorization": "Bearer salah"})  # fmt: skip
    assert r.status_code == 401
    assert client.get("/v1/health").status_code == 200


def test_default_provider_listed_first(monkeypatch):
    monkeypatch.setattr(get_settings(), "default_provider", "owlv2")
    providers = registry.describe_providers()
    assert providers[0]["name"] == "owlv2" and providers[0]["is_default"]
    assert sum(p["is_default"] for p in providers) == 1
