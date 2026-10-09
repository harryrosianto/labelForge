"""Struktur netral hasil parsing dataset (YOLO/COCO) dan sumber file (ZIP atau folder)."""

import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
SPLIT_ALIASES = {"train": "train", "training": "train", "val": "val", "valid": "val",
                 "validation": "val", "test": "test", "testing": "test"}  # fmt: skip
MAX_PROBLEMS_STORED = 200


class DatasetReadError(ValueError):
    """Dataset tidak bisa dibaca (pesan aman untuk user)."""


class Source(Protocol):
    def names(self) -> list[str]:
        """Semua path file (posix, relatif), tanpa folder & file sistem (__MACOSX, .DS_Store)."""

    def read(self, name: str) -> bytes: ...


def _visible(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return bool(parts) and parts[0] != "__MACOSX" and not any(p.startswith(".") for p in parts)


class ZipSource:
    def __init__(self, path: str | Path):
        try:
            self._zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile as e:
            raise DatasetReadError("File bukan ZIP yang valid") from e
        self._names = sorted(
            i.filename for i in self._zf.infolist() if not i.is_dir() and _visible(i.filename)
        )

    def names(self) -> list[str]:
        return self._names

    def read(self, name: str) -> bytes:
        return self._zf.read(name)

    def close(self) -> None:
        self._zf.close()


class DirSource:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        if not self.root.is_dir():
            raise DatasetReadError(f"Folder tidak ditemukan: {root}")
        self._names = sorted(
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file() and _visible(p.relative_to(self.root).as_posix())
        )

    def names(self) -> list[str]:
        return self._names

    def read(self, name: str) -> bytes:
        return (self.root / name).read_bytes()

    def close(self) -> None:
        pass


def open_source(path: str | Path) -> ZipSource | DirSource:
    return DirSource(path) if Path(path).is_dir() else ZipSource(path)


def is_image(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() in IMAGE_EXTS


def split_from_path(name: str) -> str | None:
    """Split dari segmen path (images/train/x.jpg, train/images/x.jpg, instances_val.json)."""
    for part in PurePosixPath(name.lower()).parts[:-1]:
        if part in SPLIT_ALIASES:
            return SPLIT_ALIASES[part]
    stem = PurePosixPath(name.lower()).stem
    for token in stem.replace("-", "_").split("_"):
        if token in SPLIT_ALIASES:
            return SPLIT_ALIASES[token]
    return None


@dataclass
class ImportBox:
    class_name: str
    box: tuple[float, float, float, float]  # xyxy ternormalisasi


@dataclass
class ImportImage:
    path: str
    split: str | None
    boxes: list[ImportBox] = field(default_factory=list)
    has_label: bool = True


@dataclass
class ImportProblem:
    kind: str
    path: str
    detail: str


# Penjelasan tiap jenis masalah untuk UI.
PROBLEM_LABELS = {
    "image_without_label": "Gambar tanpa label (diimpor sebagai gambar tanpa objek)",
    "label_without_image": "Label tanpa gambar (dilewati)",
    "invalid_line": "Baris label tidak valid (dilewati)",
    "unknown_class": "Class tidak dikenal (box dilewati)",
    "box_clipped": "Box keluar batas gambar (dipotong)",
    "box_invalid": "Box berukuran nol/negatif (dilewati)",
    "image_not_found": "Gambar yang dirujuk anotasi tidak ada di ZIP (dilewati)",
    "ambiguous_image": "Nama gambar ganda di ZIP (dipakai yang pertama)",
}


@dataclass
class ParsedDataset:
    format: str
    class_names: list[str]
    images: list[ImportImage]
    problems: list[ImportProblem] = field(default_factory=list)

    def problem(self, kind: str, path: str, detail: str = "") -> None:
        self.problems.append(ImportProblem(kind, path, detail))

    def analysis(self) -> dict:
        boxes = Counter(b.class_name for img in self.images for b in img.boxes)
        imgs = Counter(n for img in self.images for n in {b.class_name for b in img.boxes})
        problem_counts = Counter(p.kind for p in self.problems)
        return {
            "format": self.format,
            "images": len(self.images),
            "images_with_boxes": sum(1 for i in self.images if i.boxes),
            "boxes": sum(boxes.values()),
            "splits": dict(Counter(i.split or "none" for i in self.images)),
            "classes": [
                {"name": n, "boxes": boxes.get(n, 0), "images": imgs.get(n, 0)}
                for n in self.class_names
            ],
            "problem_counts": {
                k: {"count": v, "label": PROBLEM_LABELS.get(k, k)} for k, v in problem_counts.items()
            },
            "problems": [
                {"kind": p.kind, "path": p.path, "detail": p.detail}
                for p in self.problems[:MAX_PROBLEMS_STORED]
            ],
        }


def clip_box(
    box: tuple[float, float, float, float], ds: ParsedDataset, path: str
) -> tuple[float, float, float, float] | None:
    """Rapikan box ternormalisasi: urutkan, potong ke 0..1, buang yang tidak valid."""
    x1, y1, x2, y2 = box
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    clipped = (max(0.0, x1), max(0.0, y1), min(1.0, x2), min(1.0, y2))
    if clipped[2] - clipped[0] <= 1e-6 or clipped[3] - clipped[1] <= 1e-6:
        ds.problem("box_invalid", path, f"{box}")
        return None
    tol = 1e-4  # pembulatan wajar dari tool lain tidak dianggap masalah
    if any(abs(a - b) > tol for a, b in zip(clipped, (x1, y1, x2, y2))):
        ds.problem("box_clipped", path, f"{box}")
    return clipped
