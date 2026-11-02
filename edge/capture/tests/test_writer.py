import json
import shutil
from collections import namedtuple

import pytest

from lfcapture.select import Detections
from lfcapture.writer import DatasetWriter, DiskFull, yolo_lines
from tests.helpers import JPEG, det_msg, item, make_config, track

TS = 1762156712.345  # 2025-11-03 08:38:32 UTC


def det(**kw):
    return Detections.from_message(det_msg(**kw))


def test_yolo_lines_with_confidence_and_ignored(tmp_path):
    cfg = make_config(tmp_path)
    d = det(tracks=[track(box=(0.4, 0.2, 0.5, 0.8), score=0.91)],
            items=[item("Helmet", (0.42, -0.05, 0.48, 0.05), 0.42), item("fire", (0, 0, 1, 1), 0.9),
                   item("Mask", (0.3, 0.3, 0.3, 0.4), 0.7)])  # fmt: skip
    lines, ignored = yolo_lines(d, cfg)
    assert lines == ["0 0.45000 0.50000 0.10000 0.60000 0.910",
                     "1 0.45000 0.02500 0.06000 0.05000 0.420"]  # box dipotong ke dalam gambar
    assert ignored == 2  # class di luar daftar + box berlebar nol


def test_without_person_class(tmp_path):
    cfg = make_config(tmp_path, CAPTURE_CLASSES="Helmet,Mask", CAPTURE_PERSON_CLASS="")
    lines, _ = yolo_lines(det(tracks=[track()], items=[item("Mask")]), cfg)
    assert [ln.split()[0] for ln in lines] == ["1"]


def test_save_layout_meta_and_unique_names(tmp_path):
    cfg = make_config(tmp_path / "out", CAPTURE_PREFIX="mdlz")
    w = DatasetWriter(cfg)
    d = det(ts=TS - 0.08, tracks=[track(missing=["Helmet"])], items=[item()])
    first = w.save(d, JPEG, TS, "violation", "Line 3")
    second = w.save(d, JPEG, TS, "violation", "Line 3")
    day = tmp_path / "out" / "mdlz-20251103"
    assert first.image == day / "images" / "cam3_1762156712345.jpg"
    assert second.image.name == "cam3_1762156712346.jpg"
    assert first.image.read_bytes() == JPEG
    assert (day / "labels" / "cam3_1762156712345.txt").read_text().count("\n") == 2
    assert (day / "data.yaml").read_text().startswith('names: ["person", "Helmet", "Mask", "Safety Vest"')
    meta = [json.loads(x) for x in (day / "meta" / "20251103.jsonl").read_text().splitlines()]
    assert meta[0]["reason"] == "violation" and meta[0]["lag_ms"] == 80
    assert meta[0]["tracks"][0]["ppe_missing"] == ["Helmet"]
    assert "Budi" not in json.dumps(meta)  # nama hasil pengenalan wajah tidak disimpan
    assert not list(day.rglob("*.tmp"))


def test_empty_frame_has_empty_label(tmp_path):
    w = DatasetWriter(make_config(tmp_path))
    saved = w.save(det(), JPEG, TS, "empty")
    assert saved.boxes == 0
    assert saved.image.parent.parent.joinpath("labels", saved.image.stem + ".txt").read_text() == ""


def test_disk_guard(tmp_path, monkeypatch):
    w = DatasetWriter(make_config(tmp_path, CAPTURE_DISK_MAX_USED_PCT=85, CAPTURE_DISK_MIN_FREE_MB=1024))
    usage = namedtuple("usage", "total used free")
    gb = 1024**3
    monkeypatch.setattr(shutil, "disk_usage", lambda _: usage(100 * gb, 90 * gb, 10 * gb))
    with pytest.raises(DiskFull, match="90.0%"):
        w.save(det(), JPEG, TS, "empty")
    monkeypatch.setattr(shutil, "disk_usage", lambda _: usage(100 * gb, 50 * gb, gb // 2))
    with pytest.raises(DiskFull, match="512 MB"):
        w.check_disk()
    assert not list(tmp_path.rglob("*.jpg"))


def test_output_imports_into_labelforge(tmp_path):
    """Folder hasil perekam terbaca importer YOLO LabelForge apa adanya, termasuk confidence."""
    importers = pytest.importorskip("labelforge.importers.detect")
    from labelforge.importers.base import DirSource

    w = DatasetWriter(make_config(tmp_path))
    w.save(det(tracks=[track(score=0.91)], items=[item(score=0.42)]), JPEG, TS, "uncertain")
    w.save(det(), JPEG, TS + 10, "empty")
    ds = importers.parse_dataset(DirSource(tmp_path / "ppe-20251103"))
    assert ds.format == "yolo" and ds.class_names[:2] == ["person", "Helmet"]
    assert ds.problems == []
    boxes = sorted((b.class_name, b.confidence) for i in ds.images for b in i.boxes)
    assert boxes == [("Helmet", 0.42), ("person", 0.91)]
