"""Memanggil inference server LabelForge di mesin lain (mis. mesin GPU) via HTTP.

Server-nya adalah `python -m labelforge.inference_server`, yang memakai registry provider
yang sama. Kontrak:

POST {REMOTE_INFERENCE_URL}/v1/detect   (multipart/form-data)
  image            : file gambar (orientasi EXIF sudah diterapkan)
  payload          : JSON {"provider", "params", "classes": [{"id", "name", "text_prompt",
                     "exemplars": [nama field file]}]}
  exemplar_<n>     : file crop exemplar yang dirujuk di payload
  Authorization    : Bearer <REMOTE_INFERENCE_TOKEN> (opsional)
→ 200 {"detections": [{"class_id", "bbox": [x1,y1,x2,y2] pixel, "confidence"}],
       "source", "device", "duration_ms", "warnings"}
"""

import io
import json
import time
from typing import Any

from PIL import Image

from labelforge.config import get_settings
from labelforge.providers.base import (
    ClassDef,
    Detection,
    LabelingProvider,
    ParamSpec,
    ProviderError,
)
from labelforge.providers.registry import get_provider_class, register_provider

# Mode remote = "<provider>:<mode>" dari provider lokal yang dijalankan di server.
REMOTE_MODES = ("grounding_dino:text", "owlv2:text", "owlv2:image_guided")


def split_mode(mode: str) -> tuple[type[LabelingProvider], str]:
    provider_name, _, sub_mode = mode.partition(":")
    return get_provider_class(provider_name), sub_mode


@register_provider
class RemoteApiProvider(LabelingProvider):
    name = "remote"
    label = "Remote inference server"
    modes = REMOTE_MODES

    @classmethod
    def param_specs(cls, mode: str) -> list[ParamSpec]:
        provider_cls, sub_mode = split_mode(mode)
        return provider_cls.param_specs(sub_mode)

    @classmethod
    def is_available(cls) -> tuple[bool, str | None]:
        if not get_settings().remote_inference_url:
            return False, "REMOTE_INFERENCE_URL belum diatur di .env"
        return True, None

    @classmethod
    def source_tag(cls, mode: str) -> str:
        # Sumber anotasi mengikuti model yang dipakai, bukan lokasi eksekusinya.
        provider_cls, sub_mode = split_mode(mode)
        return provider_cls.source_tag(sub_mode)

    @classmethod
    def class_warnings(cls, mode: str, classes: list[ClassDef]) -> list[str]:
        provider_cls, sub_mode = split_mode(mode)
        return provider_cls.class_warnings(sub_mode, classes)

    def _load(self) -> None:
        import httpx

        s = get_settings()
        headers = {}
        if s.remote_inference_token:
            headers["Authorization"] = f"Bearer {s.remote_inference_token}"
        self.device = "remote"
        self.client = httpx.Client(
            base_url=s.remote_inference_url.rstrip("/"),
            headers=headers,
            timeout=s.remote_inference_timeout,
        )

    def _detect(
        self, image: Image.Image, classes: list[ClassDef], params: dict[str, Any]
    ) -> list[Detection]:
        import httpx

        provider_name, _, sub_mode = params["mode"].partition(":")
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=95)
        files: list[tuple[str, tuple[str, bytes, str]]] = [
            ("image", ("image.jpg", buf.getvalue(), "image/jpeg"))
        ]
        class_payload = []
        for cls in classes:
            fields = []
            for path in cls.exemplar_paths:
                field = f"exemplar_{len(files)}"
                files.append((field, (path.name, path.read_bytes(), "application/octet-stream")))
                fields.append(field)
            class_payload.append({"id": cls.id, "name": cls.name, "text_prompt": cls.text_prompt,
                                  "exemplars": fields})  # fmt: skip
        payload = {"provider": provider_name, "params": params | {"mode": sub_mode},
                   "classes": class_payload}  # fmt: skip

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.client.post(
                    "/v1/detect", data={"payload": json.dumps(payload)}, files=files
                )
            except httpx.TransportError as e:
                last_error = e
            else:
                if resp.status_code < 500:
                    break
                last_error = ProviderError(f"Server remote error {resp.status_code}: {resp.text}")
            time.sleep(2**attempt)
        else:
            raise ProviderError(f"Gagal menghubungi inference server: {last_error}")

        if resp.status_code != 200:
            raise ProviderError(f"Inference server menolak request ({resp.status_code}): {resp.text}")
        return [
            Detection(int(d["class_id"]), tuple(d["bbox"]), float(d["confidence"]))
            for d in resp.json()["detections"]
        ]
