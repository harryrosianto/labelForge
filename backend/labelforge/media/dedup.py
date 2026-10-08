"""Hash perseptual (dHash 64-bit) untuk mendeteksi frame/gambar yang hampir sama.

CCTV gudang sering statis berjam-jam; frame yang praktis identik tidak menambah informasi
untuk training. Dua gambar dianggap mirip bila jarak Hamming dHash-nya <= ambang.
"""

import cv2
import numpy as np
from PIL import Image


def dhash(image: Image.Image | np.ndarray, size: int = 8) -> str:
    """dHash: bandingkan piksel bersebelahan pada versi abu-abu (size+1)x size. Hasil hex 16 karakter."""
    arr = np.asarray(image.convert("L")) if isinstance(image, Image.Image) else image
    if arr.ndim == 3:
        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(arr, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


class SimilarFilter:
    """Lewati frame yang mirip dengan frame terakhir yang disimpan (threshold 0 = nonaktif)."""

    def __init__(self, threshold: int):
        self.threshold = threshold
        self.last: str | None = None
        self.skipped = 0

    def accept(self, frame_hash: str) -> bool:
        if self.threshold > 0 and self.last is not None and hamming(frame_hash, self.last) <= self.threshold:
            self.skipped += 1
            return False
        self.last = frame_hash
        return True
