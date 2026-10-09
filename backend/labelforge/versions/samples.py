"""Muat/simpan gambar untuk pembuatan versi & pratinjau augmentasi."""

import io

import numpy as np
from PIL import Image as PILImage
from PIL import ImageOps

from labelforge.storage import StorageBackend
from labelforge.versions.preprocess import Preprocessing, apply_preprocessing


def load_base(storage: StorageBackend, key: str, preprocessing: Preprocessing | None = None) -> PILImage.Image:
    """Gambar RGB (orientasi EXIF diterapkan), opsional dengan preprocessing."""
    with storage.local_path(key) as path, PILImage.open(path) as src:
        img = ImageOps.exif_transpose(src).convert("RGB")
    return apply_preprocessing(img, preprocessing) if preprocessing else img


def to_boxes(annotations: list) -> np.ndarray:
    return np.array(annotations, dtype=np.float64).reshape(-1, 5)


def from_boxes(boxes: np.ndarray) -> list[list[float]]:
    return [[int(b[0]), *(round(float(v), 6) for v in b[1:])] for b in boxes]


def encode_jpeg(img: PILImage.Image | np.ndarray, quality: int = 95, max_side: int | None = None) -> bytes:
    pil = PILImage.fromarray(img) if isinstance(img, np.ndarray) else img
    if max_side and max(pil.size) > max_side:
        pil = pil.copy()
        pil.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
