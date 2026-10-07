"""Konversi koordinat bounding box.

Konvensi:
- xyxy pixel      : (x_min, y_min, x_max, y_max) dalam pixel, origin kiri-atas.
- xyxy normalized : sama, dibagi width/height gambar → 0..1. Format penyimpanan di DB.
- YOLO            : (cx, cy, w, h) ternormalisasi 0..1.
- COCO            : (x_min, y_min, w, h) dalam pixel.

Semua fungsi murni (tanpa I/O) agar mudah dites; bug di sini merusak seluruh dataset.
"""

from collections.abc import Sequence

Box = tuple[float, float, float, float]


def _check_size(width: float, height: float) -> None:
    if width <= 0 or height <= 0:
        raise ValueError(f"Ukuran gambar tidak valid: {width}x{height}")


def _ordered(box: Sequence[float]) -> Box:
    x1, y1, x2, y2 = (float(v) for v in box)
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def clip_xyxy(box: Sequence[float], width: float, height: float) -> Box:
    """Urutkan sudut dan potong box ke dalam batas [0, width] x [0, height]."""
    x1, y1, x2, y2 = _ordered(box)
    return (
        min(max(x1, 0.0), width),
        min(max(y1, 0.0), height),
        min(max(x2, 0.0), width),
        min(max(y2, 0.0), height),
    )


def clip_norm(box: Sequence[float]) -> Box:
    return clip_xyxy(box, 1.0, 1.0)


def box_area(box: Sequence[float]) -> float:
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def is_valid_box(box: Sequence[float], min_size: float = 0.0) -> bool:
    """True jika lebar dan tinggi > min_size (setelah box diurutkan)."""
    x1, y1, x2, y2 = _ordered(box)
    return (x2 - x1) > min_size and (y2 - y1) > min_size


# --- pixel <-> normalized ---------------------------------------------------


def xyxy_px_to_norm(box: Sequence[float], width: float, height: float) -> Box:
    _check_size(width, height)
    x1, y1, x2, y2 = clip_xyxy(box, width, height)
    return x1 / width, y1 / height, x2 / width, y2 / height


def norm_to_xyxy_px(box: Sequence[float], width: float, height: float) -> Box:
    _check_size(width, height)
    x1, y1, x2, y2 = clip_norm(box)
    return x1 * width, y1 * height, x2 * width, y2 * height


# --- normalized xyxy <-> YOLO -----------------------------------------------


def norm_xyxy_to_yolo(box: Sequence[float]) -> Box:
    x1, y1, x2, y2 = clip_norm(box)
    return (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1


def yolo_to_norm_xyxy(yolo: Sequence[float]) -> Box:
    cx, cy, w, h = (float(v) for v in yolo)
    if w < 0 or h < 0:
        raise ValueError(f"Lebar/tinggi YOLO negatif: {yolo}")
    return clip_norm((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))


def xyxy_px_to_yolo(box: Sequence[float], width: float, height: float) -> Box:
    return norm_xyxy_to_yolo(xyxy_px_to_norm(box, width, height))


def yolo_to_xyxy_px(yolo: Sequence[float], width: float, height: float) -> Box:
    return norm_to_xyxy_px(yolo_to_norm_xyxy(yolo), width, height)


# --- pixel xyxy <-> COCO ----------------------------------------------------


def xyxy_px_to_coco(box: Sequence[float]) -> Box:
    x1, y1, x2, y2 = _ordered(box)
    return x1, y1, x2 - x1, y2 - y1


def coco_to_xyxy_px(coco: Sequence[float]) -> Box:
    x, y, w, h = (float(v) for v in coco)
    if w < 0 or h < 0:
        raise ValueError(f"Lebar/tinggi COCO negatif: {coco}")
    return x, y, x + w, y + h


def norm_xyxy_to_coco(box: Sequence[float], width: float, height: float) -> Box:
    return xyxy_px_to_coco(norm_to_xyxy_px(box, width, height))


def coco_to_norm_xyxy(coco: Sequence[float], width: float, height: float) -> Box:
    return xyxy_px_to_norm(coco_to_xyxy_px(coco), width, height)


def format_yolo_line(class_index: int, box_norm: Sequence[float], precision: int = 6) -> str:
    cx, cy, w, h = norm_xyxy_to_yolo(box_norm)
    return f"{class_index} {cx:.{precision}f} {cy:.{precision}f} {w:.{precision}f} {h:.{precision}f}"
