import io
import json
import zipfile

import pytest

from labelforge.importers.base import DatasetReadError, DirSource, ZipSource, split_from_path
from labelforge.importers.detect import detect_format, parse_dataset
from labelforge.importers.yolo import parse_line
from tests.test_images_service import make_jpeg

JPG = make_jpeg((100, 50))


def zip_source(tmp_path, files: dict[str, bytes | str], name="ds.zip") -> ZipSource:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for n, data in files.items():
            zf.writestr(n, data)
    return ZipSource(path)


def boxes_of(ds, path):
    img = next(i for i in ds.images if i.path == path)
    return [(b.class_name, tuple(round(v, 6) for v in b.box)) for b in img.boxes]


def kinds(ds):
    return sorted(p.kind for p in ds.problems)


# --- YOLO ---------------------------------------------------------------------


def test_yolo_standard_structure(tmp_path):
    src = zip_source(tmp_path, {
        "ds/data.yaml": "names: ['pallet', 'person']\nnc: 2\n",
        "ds/images/train/a.jpg": JPG,
        "ds/labels/train/a.txt": "0 0.5 0.5 0.2 0.4\n1 0.1 0.1 0.2 0.2\n",
        "ds/images/val/b.jpg": JPG,
        "ds/labels/val/b.txt": "",
        "__MACOSX/ds/._a.jpg": "junk",
    })  # fmt: skip
    assert detect_format(src) == "yolo"
    ds = parse_dataset(src)
    assert ds.class_names == ["pallet", "person"]
    assert boxes_of(ds, "ds/images/train/a.jpg") == [
        ("pallet", (0.4, 0.3, 0.6, 0.7)), ("person", (0.0, 0.0, 0.2, 0.2)),
    ]  # fmt: skip
    assert {i.path: i.split for i in ds.images} == {"ds/images/train/a.jpg": "train", "ds/images/val/b.jpg": "val"}
    assert ds.problems == []  # label kosong = gambar tanpa objek yang sah
    a = ds.analysis()
    assert a["boxes"] == 2 and a["images_with_boxes"] == 1 and a["splits"] == {"train": 1, "val": 1}
    assert a["classes"] == [{"name": "pallet", "boxes": 1, "images": 1}, {"name": "person", "boxes": 1, "images": 1}]


def test_yolo_names_dict_split_first_and_valid_alias(tmp_path):
    src = zip_source(tmp_path, {
        "data.yaml": "names:\n  1: person\n  0: pallet\n",
        "valid/images/c.jpg": JPG,
        "valid/labels/c.txt": "1 0.5 0.5 0.5 0.5",
    })  # fmt: skip
    ds = parse_dataset(src)
    assert ds.class_names == ["pallet", "person"]
    assert boxes_of(ds, "valid/images/c.jpg") == [("person", (0.25, 0.25, 0.75, 0.75))]
    assert ds.images[0].split == "val"


def test_yolo_flat_folder_without_yaml_and_darknet_names(tmp_path):
    flat = zip_source(tmp_path, {"x.jpg": JPG, "x.txt": "2 0.5 0.5 0.1 0.1"}, "flat.zip")
    ds = parse_dataset(flat)
    assert ds.class_names == ["class_0", "class_1", "class_2"]
    assert boxes_of(ds, "x.jpg")[0][0] == "class_2"

    darknet = zip_source(tmp_path, {"obj.names": "forklift\npallet\n", "y.jpg": JPG,
                                    "y.txt": "1 0.5 0.5 0.2 0.2"}, "dk.zip")  # fmt: skip
    ds = parse_dataset(darknet)
    assert ds.class_names == ["forklift", "pallet"] and ds.problems == []


def test_yolo_segmentation_polygon_becomes_bbox():
    assert parse_line("0 0.1 0.2 0.5 0.2 0.3 0.6") == (0, (0.1, 0.2, 0.5, 0.6))
    assert parse_line("0 0.1 0.2") is None
    assert parse_line("x 0.5 0.5 0.1 0.1") is None


def test_yolo_problems(tmp_path):
    src = zip_source(tmp_path, {
        "data.yaml": "names: [pallet]",
        "images/a.jpg": JPG,
        "labels/a.txt": "0 0.5 0.5 0.2 0.2\nrusak\n5 0.5 0.5 0.1 0.1\n0 0.95 0.5 0.2 0.2\n0 0.5 0.5 0 0.1\n",
        "images/no_label.jpg": JPG,
        "labels/orphan.txt": "0 0.5 0.5 0.1 0.1",
    })  # fmt: skip
    ds = parse_dataset(src)
    assert kinds(ds) == ["box_clipped", "box_invalid", "image_without_label", "invalid_line",
                         "label_without_image", "unknown_class"]  # fmt: skip
    assert boxes_of(ds, "images/a.jpg") == [("pallet", (0.4, 0.4, 0.6, 0.6)), ("pallet", (0.85, 0.4, 1.0, 0.6))]
    no_label = next(i for i in ds.images if i.path == "images/no_label.jpg")
    assert no_label.boxes == [] and not no_label.has_label
    a = ds.analysis()
    assert a["problem_counts"]["invalid_line"]["count"] == 1 and "label" in a["problem_counts"]["invalid_line"]


# --- COCO ---------------------------------------------------------------------


def coco(images, annotations, categories=({"id": 1, "name": "pallet"},)):
    return json.dumps({"images": images, "annotations": annotations, "categories": list(categories)})


def test_coco_basic_and_file_lookup(tmp_path):
    src = zip_source(tmp_path, {
        "annotations/instances_train.json": coco(
            [{"id": 10, "file_name": "a.jpg", "width": 100, "height": 50},
             {"id": 11, "file_name": "sub/b.jpg", "width": 100, "height": 50}],
            [{"id": 1, "image_id": 10, "category_id": 1, "bbox": [10, 5, 40, 20]},
             {"id": 2, "image_id": 11, "category_id": 7, "bbox": [0, 0, 10, 10]},
             {"id": 3, "image_id": 99, "category_id": 1, "bbox": [0, 0, 10, 10]}],
        ),
        "images/train/a.jpg": JPG,
        "images/train/sub/b.jpg": JPG,
    })  # fmt: skip
    assert detect_format(src) == "coco"
    ds = parse_dataset(src)
    assert ds.class_names == ["pallet"]
    assert boxes_of(ds, "images/train/a.jpg") == [("pallet", (0.1, 0.1, 0.5, 0.5))]
    assert all(i.split == "train" for i in ds.images)
    assert kinds(ds) == ["image_not_found", "unknown_class"]


def test_coco_missing_image_and_ambiguous(tmp_path):
    src = zip_source(tmp_path, {
        "ann.json": coco([{"id": 1, "file_name": "x.jpg", "width": 10, "height": 10},
                          {"id": 2, "file_name": "dup.jpg", "width": 10, "height": 10}], []),
        "a/dup.jpg": JPG, "b/dup.jpg": JPG,
    })  # fmt: skip
    ds = parse_dataset(src)
    assert [i.path for i in ds.images] == ["a/dup.jpg"]
    assert kinds(ds) == ["ambiguous_image", "image_not_found"]


def test_coco_category_order_follows_id(tmp_path):
    src = zip_source(tmp_path, {
        "ann.json": coco([{"id": 1, "file_name": "a.jpg", "width": 10, "height": 10}], [],
                         [{"id": 3, "name": "person"}, {"id": 1, "name": "pallet"}]),
        "a.jpg": JPG,
    })  # fmt: skip
    assert parse_dataset(src).class_names == ["pallet", "person"]


# --- umum ---------------------------------------------------------------------


def test_errors(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"bukan zip")
    with pytest.raises(DatasetReadError, match="ZIP"):
        ZipSource(bad)
    with pytest.raises(DatasetReadError, match="gambar"):
        detect_format(zip_source(tmp_path, {"a.txt": "x"}, "nogambar.zip"))
    with pytest.raises(DatasetReadError, match="tidak dikenali"):
        detect_format(zip_source(tmp_path, {"a.jpg": JPG}, "unknown.zip"))


def test_dir_source(tmp_path):
    root = tmp_path / "folder"
    (root / "images").mkdir(parents=True)
    (root / "labels").mkdir()
    (root / "images" / "a.jpg").write_bytes(JPG)
    (root / "labels" / "a.txt").write_text("0 0.5 0.5 0.2 0.2")
    (root / ".DS_Store").write_text("x")
    src = DirSource(root)
    assert src.names() == ["images/a.jpg", "labels/a.txt"]
    assert len(parse_dataset(src).images[0].boxes) == 1


@pytest.mark.parametrize("path,split", [
    ("images/train/a.jpg", "train"), ("ds/valid/images/a.jpg", "val"),
    ("annotations/instances_val.json", "val"), ("test/a.jpg", "test"), ("a.jpg", None),
])  # fmt: skip
def test_split_from_path(path, split):
    assert split_from_path(path) == split


def test_zip_source_reads_bytes(tmp_path):
    src = zip_source(tmp_path, {"a.jpg": JPG})
    assert io.BytesIO(src.read("a.jpg")).read() == JPG
