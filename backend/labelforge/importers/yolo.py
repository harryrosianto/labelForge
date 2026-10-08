"""Parser dataset YOLO (format Ultralytics/Darknet).

Struktur yang dikenali:
- images/{split}/x.jpg + labels/{split}/x.txt (juga {split}/images/x.jpg + {split}/labels/x.txt)
- folder datar: x.jpg + x.txt di folder yang sama
Nama class dari data.yaml (`names` list atau dict); tanpa data.yaml → class_0, class_1, ...
Baris label: "cls cx cy w h" atau polygon YOLO-seg "cls x1 y1 x2 y2 ..." (diubah ke bbox).
"""

from pathlib import PurePosixPath

import yaml

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


def find_yaml(names: list[str]) -> str | None:
    yamls = [n for n in names if PurePosixPath(n).suffix.lower() in (".yaml", ".yml")]
    # data.yaml paling dekat ke root lebih diutamakan
    yamls.sort(key=lambda n: (PurePosixPath(n).name.lower() != "data.yaml", n.count("/"), n))
    return yamls[0] if yamls else None


def read_class_names(source: Source, yaml_name: str | None) -> list[str] | None:
    if yaml_name is None:
        return None
    try:
        data = yaml.safe_load(source.read(yaml_name)) or {}
    except yaml.YAMLError as e:
        raise DatasetReadError(f"{yaml_name} tidak bisa dibaca: {e}") from e
    names = data.get("names") if isinstance(data, dict) else None
    if isinstance(names, dict):
        try:
            return [str(names[k]) for k in sorted(names, key=int)]
        except (TypeError, ValueError) as e:
            raise DatasetReadError(f"Format 'names' di {yaml_name} tidak dikenali") from e
    if isinstance(names, list):
        return [str(n) for n in names]
    if isinstance(data, dict) and isinstance(data.get("nc"), int):
        return [f"class_{i}" for i in range(data["nc"])]
    return None


def read_names_file(source: Source, names: list[str]) -> list[str] | None:
    """Format Darknet: classes.txt / obj.names berisi satu nama class per baris."""
    for n in sorted(names, key=lambda x: x.count("/")):
        if PurePosixPath(n).name.lower() in ("classes.txt", "obj.names"):
            lines = source.read(n).decode("utf-8", errors="replace").splitlines()
            return [line.strip() for line in lines if line.strip()] or None
    return None


def label_candidates(image_path: str) -> list[str]:
    p = PurePosixPath(image_path)
    parts = list(p.parts)
    out = []
    # ganti segmen 'images' terakhir dengan 'labels'
    for i in range(len(parts) - 2, -1, -1):
        if parts[i].lower() == "images":
            swapped = parts[:i] + ["labels"] + parts[i + 1 :]
            out.append(str(PurePosixPath(*swapped).with_suffix(".txt")))
            break
    out.append(str(p.with_suffix(".txt")))
    return out


def parse_line(line: str) -> tuple[int, tuple[float, float, float, float]] | None:
    values = line.split()
    if len(values) < 5:
        return None
    try:
        cls = int(float(values[0]))
        coords = [float(v) for v in values[1:]]
    except ValueError:
        return None
    if len(coords) == 4:
        # Koordinat mentah (tanpa clip) supaya box di luar gambar bisa dilaporkan.
        cx, cy, w, h = coords
        if w < 0 or h < 0:
            return None
        return cls, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    if len(coords) >= 6 and len(coords) % 2 == 0:  # polygon YOLO-seg
        xs, ys = coords[0::2], coords[1::2]
        return cls, (min(xs), min(ys), max(xs), max(ys))
    return None


def parse_yolo(source: Source) -> ParsedDataset:
    names = source.names()
    name_set = set(names)
    class_names = read_class_names(source, find_yaml(names)) or read_names_file(source, names)
    ds = ParsedDataset("yolo", list(class_names or []), [])
    max_seen = -1
    used_labels: set[str] = set()

    for image_path in (n for n in names if is_image(n)):
        label_path = next((c for c in label_candidates(image_path) if c in name_set), None)
        img = ImportImage(image_path, split_from_path(image_path), has_label=label_path is not None)
        if label_path is None:
            ds.problem("image_without_label", image_path)
        else:
            used_labels.add(label_path)
            text = source.read(label_path).decode("utf-8", errors="replace")
            for n, raw in enumerate(text.splitlines(), 1):
                if not raw.strip():
                    continue
                parsed = parse_line(raw)
                if parsed is None:
                    ds.problem("invalid_line", label_path, f"baris {n}: {raw.strip()[:80]}")
                    continue
                cls, box = parsed
                if cls < 0 or (class_names is not None and cls >= len(class_names)):
                    ds.problem("unknown_class", label_path, f"baris {n}: class {cls}")
                    continue
                max_seen = max(max_seen, cls)
                box = clip_box(box, ds, label_path)
                if box is not None:
                    name = class_names[cls] if class_names is not None else f"class_{cls}"
                    img.boxes.append(ImportBox(name, box))
        ds.images.append(img)

    if class_names is None:
        ds.class_names = [f"class_{i}" for i in range(max_seen + 1)]

    yaml_and_txt = {n for n in names if PurePosixPath(n).suffix.lower() == ".txt"}
    for orphan in sorted(yaml_and_txt - used_labels):
        if PurePosixPath(orphan).name.lower() in ("classes.txt", "readme.txt", "notes.txt", "obj.names"):
            continue
        ds.problem("label_without_image", orphan)

    if not ds.images:
        raise DatasetReadError("Tidak ada gambar di dataset")
    return ds
