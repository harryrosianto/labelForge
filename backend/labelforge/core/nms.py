"""Non-maximum suppression (numpy) untuk membuang box ganda."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from labelforge.providers.base import Detection


def iou_one_to_many(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = (box[2] - box[0]) * (box[3] - box[1])
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    union = area + areas - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-12), 0.0)


def nms(boxes: Sequence[Sequence[float]], scores: Sequence[float], iou_threshold: float) -> list[int]:
    """Indeks box yang dipertahankan, urut skor menurun. Box dengan IoU > threshold dibuang."""
    if len(boxes) == 0:
        return []
    b = np.asarray(boxes, dtype=np.float64).reshape(-1, 4)
    s = np.asarray(scores, dtype=np.float64)
    order = np.argsort(-s, kind="stable")
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        rest = order[1:]
        if rest.size == 0:
            break
        order = rest[iou_one_to_many(b[i], b[rest]) <= iou_threshold]
    return keep


def batched_nms(
    boxes: Sequence[Sequence[float]],
    scores: Sequence[float],
    groups: Sequence[int],
    iou_threshold: float,
) -> list[int]:
    """NMS terpisah per grup (class). Hasil diurutkan skor menurun."""
    by_group: dict[int, list[int]] = {}
    for i, g in enumerate(groups):
        by_group.setdefault(g, []).append(i)
    keep: list[int] = []
    for idxs in by_group.values():
        kept = nms([boxes[i] for i in idxs], [scores[i] for i in idxs], iou_threshold)
        keep.extend(idxs[k] for k in kept)
    return sorted(keep, key=lambda i: -scores[i])


def apply_nms(
    detections: list["Detection"],
    per_class_iou: float | None,
    class_agnostic_iou: float | None = None,
) -> list["Detection"]:
    """NMS per class (jika per_class_iou diisi) lalu opsional antar-class (class_agnostic_iou)."""
    dets = list(detections)
    if per_class_iou is not None and dets:
        keep = batched_nms([d.bbox for d in dets], [d.confidence for d in dets],
                           [d.class_id for d in dets], per_class_iou)  # fmt: skip
        dets = [dets[i] for i in keep]
    if class_agnostic_iou is not None and dets:
        keep = nms([d.bbox for d in dets], [d.confidence for d in dets], class_agnostic_iou)
        dets = [dets[i] for i in keep]
    return sorted(dets, key=lambda d: -d.confidence)
