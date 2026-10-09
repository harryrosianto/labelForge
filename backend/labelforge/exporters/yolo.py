"""Format YOLO (Ultralytics/Darknet):

images/{split}/<nama>.jpg
labels/{split}/<nama>.txt   satu baris per box: "<class> <cx> <cy> <w> <h>" (ternormalisasi)
data.yaml
"""

import json
import zipfile
from collections.abc import Callable

from labelforge.core.formats import format_yolo_line
from labelforge.exporters.base import ExportDataset, export_info, write_bytes, write_text
from labelforge.storage import StorageBackend


def data_yaml(dataset: ExportDataset) -> str:
    present = [s for s, imgs in dataset.splits.items() if imgs]
    lines = ["# Dibuat oleh LabelForge", "path: .  # ganti ke path absolut folder ini bila perlu"]
    lines.append("train: images/train")
    if "val" in present:
        lines.append("val: images/val")
    else:
        # Ultralytics mewajibkan 'val'; tanpa split val, pakai train agar file tetap valid.
        lines.append("val: images/train  # tidak ada split val")
    if "test" in present:
        lines.append("test: images/test")
    lines.append(f"nc: {len(dataset.class_names)}")
    lines.append("names:")
    # json.dumps menghasilkan string ber-kutip yang juga valid sebagai YAML.
    lines += [f"  {i}: {json.dumps(name)}" for i, name in enumerate(dataset.class_names)]
    return "\n".join(lines) + "\n"


def label_text(boxes) -> str:
    return "".join(format_yolo_line(b.class_index, b.box) + "\n" for b in boxes)


def write_yolo(dataset: ExportDataset, storage: StorageBackend, zf: zipfile.ZipFile,
               on_image: Callable[[], None] | None = None) -> None:  # fmt: skip
    for split, images in dataset.splits.items():
        for img in images:
            write_bytes(zf, f"images/{split}/{img.file_name}", storage.read_bytes(img.storage_key))
            stem = img.file_name.rsplit(".", 1)[0]
            # File label kosong = gambar tanpa objek (contoh negatif), tetap ditulis.
            write_text(zf, f"labels/{split}/{stem}.txt", label_text(img.boxes))
            if on_image:
                on_image()
    write_text(zf, "data.yaml", data_yaml(dataset))
    write_text(zf, "export_info.json", json.dumps(export_info(dataset), indent=2))
