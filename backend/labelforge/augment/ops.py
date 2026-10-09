"""Operasi augmentasi yang sadar box (numpy + OpenCV, tanpa library augmentasi pihak ketiga).

Konvensi: gambar `np.ndarray` HxWx3 uint8 (RGB); box `np.ndarray` Nx5 float
[class_index, x_min, y_min, x_max, y_max] ternormalisasi terhadap gambar.

Operasi geometrik memakai satu matriks affine untuk gambar DAN box, sehingga keduanya
tidak mungkin berbeda. Box hasil transformasi = bounding box dari 4 sudut yang
ditransformasi (untuk rotasi, box membesar seperti umumnya pada augmentasi bbox).
"""

import cv2
import numpy as np

PAD_COLOR = (114, 114, 114)


def empty_boxes() -> np.ndarray:
    return np.zeros((0, 5), dtype=np.float64)


def filter_boxes(
    boxes_unclipped: np.ndarray, width: int, height: int, min_visibility: float, min_px: float = 2.0
) -> np.ndarray:
    """Potong box ke batas gambar; buang yang sisa luasnya < min_visibility atau terlalu kecil."""
    if len(boxes_unclipped) == 0:
        return empty_boxes()
    b = boxes_unclipped.copy()
    full_area = (b[:, 3] - b[:, 1]) * (b[:, 4] - b[:, 2])
    b[:, 1:5] = np.clip(b[:, 1:5], 0.0, 1.0)
    clipped_area = (b[:, 3] - b[:, 1]) * (b[:, 4] - b[:, 2])
    with np.errstate(divide="ignore", invalid="ignore"):
        visible = np.where(full_area > 0, clipped_area / full_area, 0.0)
    keep = (
        (visible >= min_visibility)
        & ((b[:, 3] - b[:, 1]) * width >= min_px)
        & ((b[:, 4] - b[:, 2]) * height >= min_px)
    )
    return b[keep]


def affine_boxes(boxes: np.ndarray, matrix: np.ndarray, src_wh: tuple[int, int],
                 dst_wh: tuple[int, int]) -> np.ndarray:  # fmt: skip
    """Transformasi box (ternormalisasi src) dengan matriks affine pixel → box ternormalisasi dst (tanpa clip)."""
    if len(boxes) == 0:
        return empty_boxes()
    sw, sh = src_wh
    dw, dh = dst_wh
    x1, y1, x2, y2 = boxes[:, 1] * sw, boxes[:, 2] * sh, boxes[:, 3] * sw, boxes[:, 4] * sh
    corners = np.stack([
        np.stack([x1, y1], 1), np.stack([x2, y1], 1), np.stack([x1, y2], 1), np.stack([x2, y2], 1),
    ], 1)  # N x 4 x 2  # fmt: skip
    ones = np.ones((*corners.shape[:2], 1))
    moved = np.concatenate([corners, ones], 2) @ matrix.T  # N x 4 x 2
    out = boxes.copy()
    out[:, 1] = moved[:, :, 0].min(1) / dw
    out[:, 2] = moved[:, :, 1].min(1) / dh
    out[:, 3] = moved[:, :, 0].max(1) / dw
    out[:, 4] = moved[:, :, 1].max(1) / dh
    return out


def warp(img: np.ndarray, boxes: np.ndarray, matrix: np.ndarray, min_visibility: float,
         out_wh: tuple[int, int] | None = None) -> tuple[np.ndarray, np.ndarray]:  # fmt: skip
    h, w = img.shape[:2]
    ow, oh = out_wh or (w, h)
    out = cv2.warpAffine(img, matrix, (ow, oh), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=PAD_COLOR)  # fmt: skip
    return out, filter_boxes(affine_boxes(boxes, matrix, (w, h), (ow, oh)), ow, oh, min_visibility)


# --- geometrik ---------------------------------------------------------------


def hflip(img: np.ndarray, boxes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    out = boxes.copy()
    if len(out):
        out[:, 1], out[:, 3] = 1.0 - boxes[:, 3], 1.0 - boxes[:, 1]
    return np.ascontiguousarray(img[:, ::-1]), out


def rotate(img, boxes, angle_deg: float, min_visibility: float):
    h, w = img.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    return warp(img, boxes, matrix, min_visibility)


def scale_translate(img, boxes, scale: float, shift_x: float, shift_y: float, min_visibility: float):
    """Zoom (scale > 1 = memperbesar/crop, < 1 = memperkecil + padding) di sekitar pusat lalu geser.
    shift_x/shift_y dalam pecahan lebar/tinggi gambar."""
    h, w = img.shape[:2]
    matrix = np.array([[scale, 0, (1 - scale) * w / 2 + shift_x * w],
                       [0, scale, (1 - scale) * h / 2 + shift_y * h]], dtype=np.float64)  # fmt: skip
    return warp(img, boxes, matrix, min_visibility)


def mosaic(samples: list[tuple[np.ndarray, np.ndarray]], out_wh: tuple[int, int], center: tuple[float, float],
           min_visibility: float) -> tuple[np.ndarray, np.ndarray]:  # fmt: skip
    """Gabungkan 4 gambar dalam grid 2x2 dengan titik tengah `center` (pecahan 0..1).
    Tiap gambar di-scale agar menutupi kuadrannya (cover) lalu dipotong di tengah."""
    ow, oh = out_wh
    cx, cy = int(round(center[0] * ow)), int(round(center[1] * oh))
    canvas = np.full((oh, ow, 3), PAD_COLOR, dtype=np.uint8)
    regions = [(0, 0, cx, cy), (cx, 0, ow, cy), (0, cy, cx, oh), (cx, cy, ow, oh)]
    all_boxes = []
    for (img, boxes), (rx1, ry1, rx2, ry2) in zip(samples, regions):
        qw, qh = rx2 - rx1, ry2 - ry1
        if qw <= 0 or qh <= 0:
            continue
        h, w = img.shape[:2]
        s = max(qw / w, qh / h)
        # pusatkan gambar ter-scale pada kuadran (kelebihan terpotong)
        tx = rx1 + (qw - w * s) / 2
        ty = ry1 + (qh - h * s) / 2
        matrix = np.array([[s, 0, tx], [0, s, ty]], dtype=np.float64)
        warped = cv2.warpAffine(img, matrix, (ow, oh), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=PAD_COLOR)  # fmt: skip
        canvas[ry1:ry2, rx1:rx2] = warped[ry1:ry2, rx1:rx2]
        moved = affine_boxes(boxes, matrix, (w, h), (ow, oh))
        if len(moved):
            # potong ke kuadran (bukan ke seluruh kanvas) sebelum cek visibilitas
            q = np.array([rx1 / ow, ry1 / oh, rx2 / ow, ry2 / oh])
            full = (moved[:, 3] - moved[:, 1]) * (moved[:, 4] - moved[:, 2])
            moved[:, [1, 3]] = np.clip(moved[:, [1, 3]], q[0], q[2])
            moved[:, [2, 4]] = np.clip(moved[:, [2, 4]], q[1], q[3])
            area = (moved[:, 3] - moved[:, 1]) * (moved[:, 4] - moved[:, 2])
            with np.errstate(divide="ignore", invalid="ignore"):
                vis = np.where(full > 0, area / full, 0.0)
            all_boxes.append(moved[vis >= min_visibility])
    boxes = np.concatenate(all_boxes) if all_boxes else empty_boxes()
    return canvas, filter_boxes(boxes, ow, oh, 0.0)


# --- warna (box tidak berubah) ------------------------------------------------


def brightness_contrast(img: np.ndarray, brightness: float, contrast: float) -> np.ndarray:
    """brightness & contrast relatif, mis. 0.1 = +10%."""
    out = img.astype(np.float32) * (1.0 + contrast)
    out += (128.0 * -contrast) + 255.0 * brightness
    return np.clip(out, 0, 255).astype(np.uint8)


def hue_saturation(img: np.ndarray, hue_deg: float, saturation: float) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV).astype(np.float32)
    hsv[..., 0] = (hsv[..., 0] + hue_deg / 2.0) % 180.0  # OpenCV: hue 0..180
    hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + saturation), 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)


def blur(img: np.ndarray, kernel: int) -> np.ndarray:
    k = max(3, kernel | 1)  # ganjil
    return cv2.GaussianBlur(img, (k, k), 0)


def noise(img: np.ndarray, std: float, rng: np.random.Generator) -> np.ndarray:
    out = img.astype(np.float32) + rng.normal(0.0, std, img.shape).astype(np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)
