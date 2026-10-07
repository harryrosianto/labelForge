from typing import Any

from PIL import Image

from labelforge.providers.base import ClassDef, Detection, LabelingProvider, ParamSpec


class FakeProvider(LabelingProvider):
    """Mengembalikan box tetap; menyimpan argumen terakhir untuk diperiksa.

    Gambar berukuran `fail_size` (w, h) menimbulkan error (uji error per gambar).
    """

    name = "fake"
    modes = ("text", "image_guided")
    per_class_nms_param = "nms_iou"
    last_call: dict = {}
    calls: int = 0
    fail_size: tuple[int, int] | None = None

    @classmethod
    def param_specs(cls, mode: str) -> list[ParamSpec]:
        return [ParamSpec("nms_iou", "float", 0.5, min=0.0, max=1.0)]

    @classmethod
    def class_warnings(cls, mode: str, classes: list[ClassDef]) -> list[str]:
        if mode != "image_guided":
            return []
        return [f"Class '{c.name}' tanpa exemplar" for c in classes if not c.exemplar_paths]

    def _detect(self, image: Image.Image, classes: list[ClassDef], params: dict[str, Any]):
        FakeProvider.calls += 1
        if image.size == FakeProvider.fail_size:
            raise RuntimeError("gagal sengaja")
        FakeProvider.last_call = {
            "size": image.size,
            "classes": classes,
            "params": params,
            "exemplar_bytes": [p.read_bytes() for c in classes for p in c.exemplar_paths],
        }
        first = classes[0].id
        return [
            Detection(first, (10, 10, 50, 50), 0.9),
            Detection(first, (12, 12, 50, 50), 0.6),     # duplikat → NMS
            Detection(first, (-20, 90, 30, 500), 0.8),   # keluar gambar → di-clip
            Detection(first, (5, 5, 6, 6), 0.95),        # terlalu kecil → dibuang
            Detection(999, (0, 0, 10, 10), 0.99),        # class tidak diminta → dibuang
        ]  # fmt: skip
