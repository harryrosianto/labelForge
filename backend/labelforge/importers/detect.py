from pathlib import PurePosixPath

from labelforge.importers.base import DatasetReadError, ParsedDataset, Source, is_image
from labelforge.importers.coco import coco_json_files, parse_coco
from labelforge.importers.yolo import parse_yolo


def detect_format(source: Source) -> str:
    names = source.names()
    if not any(is_image(n) for n in names):
        raise DatasetReadError("Tidak ada file gambar di dalam dataset")
    if coco_json_files(source):
        return "coco"
    has_txt = any(PurePosixPath(n).suffix.lower() == ".txt" for n in names)
    has_yaml = any(PurePosixPath(n).suffix.lower() in (".yaml", ".yml") for n in names)
    if has_txt or has_yaml:
        return "yolo"
    raise DatasetReadError(
        "Format dataset tidak dikenali. Didukung: YOLO (labels/*.txt, data.yaml) dan COCO (JSON)."
    )


def parse_dataset(source: Source, fmt: str | None = None) -> ParsedDataset:
    fmt = fmt or detect_format(source)
    if fmt == "coco":
        return parse_coco(source)
    if fmt == "yolo":
        return parse_yolo(source)
    raise DatasetReadError(f"Format tidak didukung: {fmt}")
