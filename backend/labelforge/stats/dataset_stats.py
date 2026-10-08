"""Statistik dataset: keseimbangan class, ukuran & bentuk box, posisi box, ukuran gambar.

Fungsi `compute_stats` murni (tanpa DB) agar mudah dites; pemanggil menyiapkan daftar gambar
berupa `StatImage` dari anotasi project maupun manifest versi.
"""

import math
from collections import Counter
from dataclasses import dataclass, field

# Batas ukuran box mengikuti COCO (luas dalam pixel).
SMALL_AREA = 32 * 32
MEDIUM_AREA = 96 * 96
HEATMAP_GRID = 20
MAX_BOXES_PER_IMAGE_BIN = 10  # bin terakhir = "10+"
ASPECT_BINS = [(0, 0.25, "< 1:4"), (0.25, 0.5, "1:4 - 1:2"), (0.5, 1, "1:2 - 1:1"),
               (1, 2, "1:1 - 2:1"), (2, 4, "2:1 - 4:1"), (4, math.inf, "> 4:1")]  # fmt: skip
SIZE_BINS = 20  # histogram sisi relatif box = sqrt(luas box / luas gambar), 0..1

# Ambang peringatan
FEW_BOXES = 50
IMBALANCE_RATIO = 10
SMALL_SHARE = 0.5


@dataclass
class StatImage:
    width: int
    height: int
    # (class_index, x_min, y_min, x_max, y_max) ternormalisasi
    boxes: list[tuple[int, float, float, float, float]] = field(default_factory=list)


def compute_stats(class_names: list[str], images: list[StatImage]) -> dict:
    n_cls = len(class_names)
    boxes_per_class = [0] * n_cls
    images_per_class = [0] * n_cls
    size_buckets = {"small": [0] * n_cls, "medium": [0] * n_cls, "large": [0] * n_cls}
    size_hist = [0] * SIZE_BINS
    aspect = [0] * len(ASPECT_BINS)
    heat = [[0] * HEATMAP_GRID for _ in range(HEATMAP_GRID)]
    per_image = [0] * (MAX_BOXES_PER_IMAGE_BIN + 1)
    image_sizes: Counter = Counter()

    for img in images:
        image_sizes[(img.width, img.height)] += 1
        per_image[min(len(img.boxes), MAX_BOXES_PER_IMAGE_BIN)] += 1
        seen = set()
        for cls, x1, y1, x2, y2 in img.boxes:
            if not 0 <= cls < n_cls:
                continue
            boxes_per_class[cls] += 1
            seen.add(cls)
            w_px, h_px = (x2 - x1) * img.width, (y2 - y1) * img.height
            area = w_px * h_px
            bucket = "small" if area < SMALL_AREA else "medium" if area < MEDIUM_AREA else "large"
            size_buckets[bucket][cls] += 1
            rel_side = math.sqrt(max(0.0, (x2 - x1) * (y2 - y1)))
            size_hist[min(SIZE_BINS - 1, int(rel_side * SIZE_BINS))] += 1
            if h_px > 0:
                ratio = w_px / h_px
                aspect[next(i for i, (lo, hi, _) in enumerate(ASPECT_BINS) if lo <= ratio < hi)] += 1
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            heat[min(HEATMAP_GRID - 1, int(cy * HEATMAP_GRID))][min(HEATMAP_GRID - 1, int(cx * HEATMAP_GRID))] += 1
        for cls in seen:
            images_per_class[cls] += 1

    total_boxes = sum(boxes_per_class)
    small_total = sum(size_buckets["small"])
    return {
        "images": len(images),
        "boxes": total_boxes,
        "empty_images": per_image[0],
        "classes": [
            {"name": name, "boxes": boxes_per_class[i], "images": images_per_class[i],
             "small": size_buckets["small"][i], "medium": size_buckets["medium"][i],
             "large": size_buckets["large"][i]}
            for i, name in enumerate(class_names)
        ],  # fmt: skip
        "box_size": {
            "small": small_total,
            "medium": sum(size_buckets["medium"]),
            "large": sum(size_buckets["large"]),
            "relative_side_hist": [
                {"from": i / SIZE_BINS, "to": (i + 1) / SIZE_BINS, "count": c}
                for i, c in enumerate(size_hist)
            ],
        },
        "boxes_per_image": [
            {"label": f"{i}+" if i == MAX_BOXES_PER_IMAGE_BIN else str(i), "count": c}
            for i, c in enumerate(per_image)
        ],
        "aspect_ratio": [{"label": label, "count": aspect[i]} for i, (_, _, label) in enumerate(ASPECT_BINS)],
        "heatmap": {"grid": HEATMAP_GRID, "counts": heat},
        "image_sizes": [
            {"width": w, "height": h, "count": c} for (w, h), c in image_sizes.most_common(10)
        ],
        "warnings": _warnings(class_names, boxes_per_class, total_boxes, small_total),
    }


def _warnings(names: list[str], boxes: list[int], total: int, small: int) -> list[dict]:
    out = []
    empty = [n for n, b in zip(names, boxes) if b == 0]
    if empty:
        out.append({"kind": "class_without_boxes", "classes": empty,
                    "message": f"Class tanpa box: {', '.join(empty)}. Model tidak bisa belajar mengenalinya."})  # fmt: skip
    few = [n for n, b in zip(names, boxes) if 0 < b < FEW_BOXES]
    if few:
        out.append({"kind": "few_boxes", "classes": few,
                    "message": f"Contoh sedikit (< {FEW_BOXES} box): {', '.join(few)}."})  # fmt: skip
    nonzero = [b for b in boxes if b > 0]
    if len(nonzero) >= 2 and max(nonzero) / min(nonzero) >= IMBALANCE_RATIO:
        top = names[boxes.index(max(nonzero))]
        low = names[boxes.index(min(nonzero))]
        out.append({"kind": "imbalance", "classes": [top, low],
                    "message": f"Tidak seimbang: '{top}' punya {max(nonzero)} box, '{low}' hanya {min(nonzero)} "
                               f"({max(nonzero) // min(nonzero)}x)."})  # fmt: skip
    if total and small / total >= SMALL_SHARE:
        out.append({"kind": "many_small", "classes": [],
                    "message": f"{round(small / total * 100)}% box berukuran kecil (< 32x32 px). "
                               "Pertimbangkan resolusi input lebih besar saat training."})  # fmt: skip
    return out
