"""Kontrak provider auto-labeling.

Menambah provider baru: buat subclass `LabelingProvider`, isi `name`, `modes`,
`param_specs()` dan `_detect()`, lalu beri decorator `@register_provider`.
Import library berat (torch, transformers) di dalam `_load()` / `_detect()`,
bukan di level modul, supaya proses web tetap ringan.
"""

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image, ImageOps

from labelforge.core.formats import clip_xyxy, is_valid_box
from labelforge.core.nms import apply_nms


class ProviderError(Exception):
    """Error yang pesannya aman ditampilkan ke user (konfigurasi/parameter salah)."""


@dataclass(frozen=True)
class ClassDef:
    id: int
    name: str
    text_prompt: str | None = None
    exemplar_paths: tuple[Path, ...] = ()

    @property
    def prompt(self) -> str:
        return " ".join((self.text_prompt or self.name).split())

    @property
    def prompts(self) -> list[str]:
        """Frasa sinonim dari text_prompt (dipisah koma/titik koma), mis.
        "wooden pallet, plastic pallet" → ["wooden pallet", "plastic pallet"]."""
        parts = [" ".join(p.split()) for p in self.prompt.replace(";", ",").split(",")]
        return [p for p in parts if p] or [self.name]


@dataclass
class Detection:
    class_id: int
    bbox: tuple[float, float, float, float]  # pixel xyxy
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {"class_id": self.class_id, "bbox": list(self.bbox), "confidence": self.confidence}


@dataclass
class ParamSpec:
    name: str
    type: str  # "float" | "int" | "bool"
    default: Any
    label: str = ""
    description: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def coerce(self, value: Any) -> Any:
        if value is None:
            return self.default
        try:
            if self.type == "bool":
                if isinstance(value, str):
                    return value.strip().lower() in ("1", "true", "yes", "on")
                return bool(value)
            v = int(value) if self.type == "int" else float(value)
        except (TypeError, ValueError) as e:
            raise ProviderError(f"Parameter '{self.name}' harus bertipe {self.type}") from e
        if (self.min is not None and v < self.min) or (self.max is not None and v > self.max):
            raise ProviderError(f"Parameter '{self.name}' harus di antara {self.min} dan {self.max}")
        return v


# Parameter pasca-proses yang berlaku untuk semua provider.
COMMON_PARAMS = [
    ParamSpec("class_agnostic_nms", "bool", False, "NMS antar-class",
              "Buang box tumpang-tindih walaupun class-nya berbeda"),
    ParamSpec("class_agnostic_iou", "float", 0.7, "IoU NMS antar-class", min=0.05, max=1.0,
              step=0.05),
    ParamSpec("min_box_size", "float", 4.0, "Ukuran box minimum (px)", min=0, max=10000, step=1),
]  # fmt: skip


@dataclass
class DetectResult:
    detections: list[Detection]
    duration_ms: int
    warnings: list[str] = field(default_factory=list)


class LabelingProvider(ABC):
    name: ClassVar[str]
    label: ClassVar[str] = ""
    modes: ClassVar[tuple[str, ...]] = ("text",)
    # Nama parameter IoU untuk NMS per class; None = provider tidak memakai NMS per class.
    per_class_nms_param: ClassVar[str | None] = None

    def __init__(self) -> None:
        self._loaded = False
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self.device: str = "cpu"

    # --- metadata ------------------------------------------------------------

    @classmethod
    @abstractmethod
    def param_specs(cls, mode: str) -> list[ParamSpec]: ...

    @classmethod
    def all_param_specs(cls, mode: str) -> list[ParamSpec]:
        return cls.param_specs(mode) + COMMON_PARAMS

    @classmethod
    def is_available(cls) -> tuple[bool, str | None]:
        """(tersedia, alasan jika tidak). Hanya cek konfigurasi, karena proses web tidak memasang
        torch, jadi dependency ML dicek saat `load()` di worker (lihat `require_ml_deps`)."""
        return True, None

    @classmethod
    def source_tag(cls, mode: str) -> str:
        return f"ai:{cls.name}"

    @classmethod
    def class_warnings(cls, mode: str, classes: list[ClassDef]) -> list[str]:
        """Peringatan sebelum job jalan (mis. class tanpa exemplar)."""
        return []

    @classmethod
    def resolve_params(cls, params: dict[str, Any] | None) -> dict[str, Any]:
        params = dict(params or {})
        mode = params.pop("mode", None) or cls.modes[0]
        if mode not in cls.modes:
            raise ProviderError(f"Mode '{mode}' tidak didukung {cls.name} (pilihan: {cls.modes})")
        resolved: dict[str, Any] = {"mode": mode}
        for spec in cls.all_param_specs(mode):
            resolved[spec.name] = spec.coerce(params.get(spec.name))
        return resolved

    # --- lifecycle -------------------------------------------------------------

    def load(self) -> None:
        """Load model sekali per proses (thread-safe, idempotent)."""
        if self._loaded:
            return
        with self._load_lock:
            if not self._loaded:
                self._load()
                self._loaded = True

    def _load(self) -> None:  # noqa: B027 - opsional untuk provider tanpa model lokal
        pass

    # --- inference -------------------------------------------------------------

    def detect(
        self, image_path: str | Path, classes: list[ClassDef], params: dict[str, Any] | None = None
    ) -> list[Detection]:
        return self.detect_with_info(image_path, classes, params).detections

    def detect_with_info(
        self, image_path: str | Path, classes: list[ClassDef], params: dict[str, Any] | None = None
    ) -> DetectResult:
        p = self.resolve_params(params)
        warnings = self.class_warnings(p["mode"], classes)
        if not classes:
            return DetectResult([], 0, warnings)
        image = load_image(image_path)
        self.load()
        start = time.perf_counter()
        with self._infer_lock:
            raw = self._detect(image, classes, p)
        dets = self._postprocess(raw, image.width, image.height, {c.id for c in classes}, p)
        return DetectResult(dets, int((time.perf_counter() - start) * 1000), warnings)

    @abstractmethod
    def _detect(
        self, image: Image.Image, classes: list[ClassDef], params: dict[str, Any]
    ) -> list[Detection]: ...

    def _postprocess(
        self, dets: list[Detection], width: int, height: int, class_ids: set[int], p: dict
    ) -> list[Detection]:
        cleaned = []
        for d in dets:
            if d.class_id not in class_ids:
                continue
            box = clip_xyxy(d.bbox, width, height)
            if is_valid_box(box, p["min_box_size"]):
                cleaned.append(Detection(d.class_id, box, float(d.confidence)))
        per_class = p.get(self.per_class_nms_param) if self.per_class_nms_param else None
        agnostic = p["class_agnostic_iou"] if p["class_agnostic_nms"] else None
        return apply_nms(cleaned, per_class, agnostic)


def require_ml_deps(*modules: str) -> None:
    """Pastikan library ML terpasang; pesan error jelas jika dijalankan di proses tanpa torch."""
    import importlib

    for module in modules:
        try:
            importlib.import_module(module)
        except ImportError as e:
            raise ProviderError(
                f"Dependency ML '{module}' belum terpasang di proses ini. "
                "Jalankan di worker, atau pip install -e .[ml]"
            ) from e


def load_image(path: str | Path) -> Image.Image:
    """Buka gambar dengan orientasi EXIF diterapkan, mode RGB."""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")
