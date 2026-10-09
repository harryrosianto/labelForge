"""Format COCO detection:

images/{split}/<nama>.jpg
annotations/instances_{split}.json   bbox = [x, y, w, h] pixel, category_id mulai 1
"""

import json
import zipfile
from collections.abc import Callable

from labelforge.core.formats import box_area, norm_to_xyxy_px, xyxy_px_to_coco
from labelforge.exporters.base import ExportDataset, export_info, write_bytes, write_text
from labelforge.storage import StorageBackend


def coco_json(dataset: ExportDataset, split: str) -> dict:
    images, annotations = [], []
    ann_id = 1
    for img in dataset.splits[split]:
        images.append({"id": img.id, "file_name": img.file_name, "width": img.width, "height": img.height})
        for b in img.boxes:
            px = norm_to_xyxy_px(b.box, img.width, img.height)
            x, y, w, h = xyxy_px_to_coco(px)
            annotations.append(
                {
                    "id": ann_id,
                    "image_id": img.id,
                    "category_id": b.class_index + 1,
                    "bbox": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
                    "area": round(box_area(px), 2),
                    "iscrowd": 0,
                    "segmentation": [],
                }
            )
            ann_id += 1
    return {
        "info": {"description": f"{dataset.project.name} ({split})", "version": "1.0",
                 "contributor": "LabelForge"},
        "licenses": [],
        "images": images,
        "annotations": annotations,
        "categories": [
            {"id": i + 1, "name": name, "supercategory": "none"}
            for i, name in enumerate(dataset.class_names)
        ],
    }  # fmt: skip


def write_coco(dataset: ExportDataset, storage: StorageBackend, zf: zipfile.ZipFile,
               on_image: Callable[[], None] | None = None) -> None:  # fmt: skip
    for split, imgs in dataset.splits.items():
        if not imgs:
            continue
        for img in imgs:
            write_bytes(zf, f"images/{split}/{img.file_name}", storage.read_bytes(img.storage_key))
            if on_image:
                on_image()
        write_text(zf, f"annotations/instances_{split}.json", json.dumps(coco_json(dataset, split)))
    write_text(zf, "export_info.json", json.dumps(export_info(dataset), indent=2))
