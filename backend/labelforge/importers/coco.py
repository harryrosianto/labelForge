"""Parser dataset COCO (object detection).

Membaca semua file JSON yang berisi `images`, `annotations`, dan `categories`. Split diambil
dari nama file JSON (instances_train.json → train). `file_name` dicocokkan ke file di ZIP
berdasarkan path lengkap, lalu path relatif terhadap folder images/, lalu nama file saja.
Hanya bbox yang dipakai; segmentation diabaikan.
"""

import json
from collections import defaultdict
from pathlib import PurePosixPath

from labelforge.importers.base import (
    DatasetReadError,
    ImportBox,
    ImportImage,
    ParsedDataset,
    Source,
    clip_box,
    is_image,
    split_from_path,
)


def coco_json_files(source: Source) -> list[tuple[str, dict]]:
    out = []
    for name in source.names():
        if PurePosixPath(name).suffix.lower() != ".json":
            continue
        try:
            data = json.loads(source.read(name))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and {"images", "annotations", "categories"} <= data.keys():
            out.append((name, data))
    return out


class _ImageIndex:
    def __init__(self, names: list[str]):
        self.exact = {n for n in names if is_image(n)}
        self.by_base: dict[str, list[str]] = defaultdict(list)
        for n in sorted(self.exact):
            self.by_base[PurePosixPath(n).name].append(n)

    def find(self, file_name: str, json_dir: PurePosixPath, split: str | None) -> tuple[str | None, bool]:
        """(path di sumber, ambigu?)"""
        file_name = file_name.replace("\\", "/").removeprefix("./")
        for candidate in (file_name, str(json_dir / file_name), str(json_dir.parent / file_name),
                          str(json_dir.parent / "images" / file_name),
                          str(json_dir.parent / "images" / (split or "") / file_name)):  # fmt: skip
            if candidate in self.exact:
                return candidate, False
        matches = self.by_base.get(PurePosixPath(file_name).name, [])
        if split and len(matches) > 1:
            in_split = [m for m in matches if split_from_path(m) == split]
            if len(in_split) == 1:
                return in_split[0], False
        return (matches[0], len(matches) > 1) if matches else (None, False)


def parse_coco(source: Source) -> ParsedDataset:
    files = coco_json_files(source)
    if not files:
        raise DatasetReadError("Tidak ditemukan file anotasi COCO (JSON berisi images/annotations/categories)")

    index = _ImageIndex(source.names())
    ds = ParsedDataset("coco", [], [])
    seen_paths: set[str] = set()

    for json_name, data in files:
        split = split_from_path(json_name)
        json_dir = PurePosixPath(json_name).parent
        categories = {c["id"]: str(c["name"]) for c in data["categories"]}
        for cid in sorted(categories):  # urutan class mengikuti id kategori
            if categories[cid] not in ds.class_names:
                ds.class_names.append(categories[cid])

        anns_by_image: dict[int, list[dict]] = defaultdict(list)
        for ann in data["annotations"]:
            anns_by_image[ann.get("image_id")].append(ann)

        for info in data["images"]:
            path, ambiguous = index.find(str(info.get("file_name", "")), json_dir, split)
            if path is None:
                ds.problem("image_not_found", str(info.get("file_name")), json_name)
                continue
            if ambiguous:
                ds.problem("ambiguous_image", str(info.get("file_name")), path)
            if path in seen_paths:
                continue
            seen_paths.add(path)
            width, height = float(info.get("width") or 0), float(info.get("height") or 0)
            img = ImportImage(path, split or split_from_path(path))
            for ann in anns_by_image.get(info["id"], []):
                name = categories.get(ann.get("category_id"))
                if name is None:
                    ds.problem("unknown_class", path, f"category_id {ann.get('category_id')}")
                    continue
                bbox = ann.get("bbox")
                if not bbox or len(bbox) != 4 or width <= 0 or height <= 0:
                    ds.problem("box_invalid", path, f"bbox {bbox}")
                    continue
                x, y, w, h = (float(v) for v in bbox)
                box = clip_box((x / width, y / height, (x + w) / width, (y + h) / height), ds, path)
                if box is not None:
                    img.boxes.append(ImportBox(name, box))
            ds.images.append(img)

        known_ids = {i["id"] for i in data["images"]}
        for image_id in set(anns_by_image) - known_ids:
            ds.problem("image_not_found", f"image_id {image_id}", json_name)

    if not ds.images:
        raise DatasetReadError("Tidak ada gambar COCO yang ditemukan di dalam ZIP")
    return ds
