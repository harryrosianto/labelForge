"""Provider auto-label dari model hasil training sendiri (ONNX), satu provider per model.

Nama provider `model:<id>` (id baris tabel `models`). Kelas provider dibuat dari baris DB
oleh `registry.get_provider_class`, termasuk pemetaan index class model ke class project.
"""

from pathlib import Path
from typing import Any, ClassVar

from PIL import Image

from labelforge.providers.base import ClassDef, Detection, LabelingProvider, ParamSpec, ProviderError

PREFIX = "model:"


def model_id_of(provider_name: str) -> int | None:
    if not provider_name.startswith(PREFIX):
        return None
    try:
        return int(provider_name.removeprefix(PREFIX))
    except ValueError:
        raise ProviderError(f"Nama provider model tidak valid: {provider_name}")


class CustomModelProvider(LabelingProvider):
    """Dasar provider model kustom; atribut kelas diisi oleh `make_provider_class`."""

    name: ClassVar[str] = "model"
    modes = ("detect",)
    per_class_nms_param = "nms_iou"
    model_id: ClassVar[int]
    project_id: ClassVar[int]
    weights_path: ClassVar[Path | None]
    class_map: ClassVar[dict[int, int | None]]  # index class model → id class project

    @classmethod
    def param_specs(cls, mode: str) -> list[ParamSpec]:
        return [
            ParamSpec("score_threshold", "float", 0.25, "Confidence minimum",
                      "Box dengan skor di bawah ini dibuang", min=0.01, max=1.0, step=0.01),
            ParamSpec("nms_iou", "float", 0.7, "IoU NMS per class", min=0.05, max=1.0, step=0.05),
            ParamSpec("max_det", "int", 300, "Box maksimum per gambar", min=1, max=3000, step=1),
        ]  # fmt: skip

    @classmethod
    def is_available(cls) -> tuple[bool, str | None]:
        if cls.weights_path is None or not Path(cls.weights_path).is_file():
            return False, "file model tidak ditemukan di storage"
        if not any(v is not None for v in cls.class_map.values()):
            return False, "belum ada class model yang dipetakan ke class project"
        return True, None

    @classmethod
    def source_tag(cls, mode: str) -> str:
        return f"ai:model:{cls.model_id}"

    @classmethod
    def class_warnings(cls, mode: str, classes: list[ClassDef]) -> list[str]:
        mapped = {v for v in cls.class_map.values() if v is not None}
        return [f"Class '{c.name}' tidak dikenali model ini" for c in classes if c.id not in mapped]

    def _load(self) -> None:
        from labelforge.providers.onnx_yolo import OnnxDetector

        self.detector = OnnxDetector(self.weights_path)

    def _detect(self, image: Image.Image, classes: list[ClassDef], params: dict[str, Any]) -> list[Detection]:
        out = []
        for index, x1, y1, x2, y2, score in self.detector.detect(image, params["score_threshold"],
                                                                 params["max_det"]):  # fmt: skip
            class_id = self.class_map.get(index)
            if class_id is not None:
                out.append(Detection(class_id, (x1, y1, x2, y2), score))
        return out

    def _postprocess(self, dets, width, height, class_ids, p):
        return super()._postprocess(dets, width, height, class_ids, p)[: p["max_det"]]


def make_provider_class(
    model_id: int, project_id: int, label: str, weights_path: Path | None, class_map: dict
) -> type[CustomModelProvider]:
    attrs = {
        "name": f"{PREFIX}{model_id}",
        "label": label,
        "model_id": model_id,
        "project_id": project_id,
        "weights_path": weights_path,
        "class_map": {int(k): v for k, v in class_map.items()},
    }
    return type(f"CustomModel{model_id}", (CustomModelProvider,), attrs)
