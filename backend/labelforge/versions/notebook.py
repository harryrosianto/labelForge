"""Template notebook Google Colab untuk training Ultralytics YOLO dari satu versi dataset.

Isi notebook: cek GPU, mount Drive, unzip ZIP export versi, perbaiki `path:` di data.yaml,
training, evaluasi, lalu export ONNX. Hasil training disimpan di Drive agar tidak hilang
saat runtime Colab terputus.
"""

import json

from labelforge.exporters.naming import slug, version_zip_name
from labelforge.models import DatasetVersion, Project

DRIVE_DIR = "/content/drive/MyDrive/labelforge"
DEFAULT_MODEL = "yolo11n.pt"


def _source(text: str) -> list[str]:
    lines = text.strip("\n").split("\n")
    return [line + "\n" for line in lines[:-1]] + [lines[-1]]


def _md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _source(text)}


def _code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": _source(text)}  # fmt: skip


def image_size(config: dict) -> int:
    """Ukuran training: sisi terpanjang hasil preprocessing, atau 640 bila ukuran asli."""
    prep = config.get("preprocessing") or {}
    if prep.get("resize", "none") != "none":
        return max(prep.get("width") or 640, prep.get("height") or 640)
    return 640


SETUP = """
from google.colab import drive
drive.mount('/content/drive')

ZIP_PATH = '{drive}/{zip_name}'
DATA_DIR = '/content/dataset'
!rm -rf {{DATA_DIR}} && mkdir -p {{DATA_DIR}} && unzip -q "{{ZIP_PATH}}" -d {{DATA_DIR}}

# data.yaml dari LabelForge memakai path relatif; Ultralytics butuh path absolut.
import pathlib, re
yaml_path = pathlib.Path(DATA_DIR) / 'data.yaml'
yaml_path.write_text(re.sub(r'^path:.*$', f'path: {{DATA_DIR}}', yaml_path.read_text(), flags=re.M))
print(yaml_path.read_text())
"""

TRAIN = """
!pip install -q ultralytics
from ultralytics import YOLO

MODEL = '{model}'   # n = paling ringan; coba yolo11s.pt / yolo11m.pt bila GPU cukup
EPOCHS = 100
IMGSZ = {imgsz}
PROJECT = '{drive}/runs'
NAME = '{run_name}'

model = YOLO(MODEL)
model.train(data=str(yaml_path), epochs=EPOCHS, imgsz=IMGSZ, batch=-1,
            project=PROJECT, name=NAME, exist_ok=True, patience=30)
"""

RESUME = """
# Hapus tanda # di bawah lalu jalankan untuk melanjutkan training yang terputus.
# YOLO(f'{PROJECT}/{NAME}/weights/last.pt').train(resume=True)
"""

EVALUATE = """
best = YOLO(f'{PROJECT}/{NAME}/weights/best.pt')
metrics = best.val(data=str(yaml_path), imgsz=IMGSZ, split='val')
print(f'mAP50-95: {metrics.box.map:.3f}   mAP50: {metrics.box.map50:.3f}')
for i, name in best.names.items():
    print(f'  {name:20s} mAP50-95 {metrics.box.maps[i]:.3f}')

from IPython.display import Image, display
for f in ('results.png', 'confusion_matrix_normalized.png'):
    p = pathlib.Path(f'{PROJECT}/{NAME}/{f}')
    if p.exists():
        display(Image(filename=str(p), width=900))
"""

EVALUATE_TEST = """
# Split test tidak dipakai selama training (val dipakai memilih checkpoint terbaik),
# jadi angka ini perkiraan paling jujur untuk gambar baru.
test = best.val(data=str(yaml_path), imgsz=IMGSZ, split='test')
print(f'TEST mAP50-95: {test.box.map:.3f}   mAP50: {test.box.map50:.3f}')
"""

EXPORT = """
onnx_path = best.export(format='onnx', imgsz=IMGSZ)
print('ONNX tersimpan di', onnx_path)
"""


def colab_notebook(project: Project, version: DatasetVersion) -> dict:
    config = version.config or {}
    splits = (version.summary or {}).get("splits", {})
    classes = [c["name"] for c in config.get("classes", [])]
    zip_name = version_zip_name(project.name, version.name, "yolo")
    run_name = f"{slug(project.name)}-{slug(version.name)}"
    imgsz = image_size(config)
    if config.get("split_mode") == "segment":
        split_note = f"per segmen {config.get('segment_size')} frame per sumber"
    else:
        split_note = "acak per gambar"
    augmented = (config.get("augmentation") or {}).get("enabled")

    intro = f"""
# Training YOLO: {project.name} / {version.name}

Dataset LabelForge versi **{version.name}**: {version.image_count} gambar (train
{splits.get("train", 0)}, val {splits.get("val", 0)}, test {splits.get("test", 0)}), split
{split_note}. Class: {", ".join(classes) or "-"}.

**Sebelum mulai**
1. Di LabelForge, buka versi ini, klik **Export YOLO**, lalu unduh `{zip_name}`.
2. Unggah file itu ke Google Drive di folder `MyDrive/labelforge/`.
3. Di Colab pilih *Runtime > Change runtime type > GPU*, lalu jalankan sel dari atas ke bawah.

Hasil training (bobot, grafik, ONNX) disimpan di `MyDrive/labelforge/runs/{run_name}`.

Ultralytics berlisensi AGPL-3.0. Untuk eksperimen internal umumnya tidak masalah; bila model
atau kodenya dipakai di produk, periksa ketentuan lisensinya.
"""
    if augmented:
        intro += """
Versi ini sudah berisi gambar augmentasi dari LabelForge. Ultralytics juga mengaugmentasi
saat training, jadi training akan lebih lama; untuk versi berikutnya augmentasi di LabelForge
bisa dimatikan.
"""

    cells = [
        _md(intro),
        _code("!nvidia-smi -L || echo 'GPU tidak aktif: Runtime > Change runtime type > GPU'"),
        _md("## 1. Siapkan dataset"),
        _code(SETUP.format(drive=DRIVE_DIR, zip_name=zip_name)),
        _md("## 2. Training"),
        _code(TRAIN.format(model=DEFAULT_MODEL, imgsz=imgsz, drive=DRIVE_DIR, run_name=run_name)),
        _md("Bila runtime terputus, jalankan ulang sel *Siapkan dataset*, lalu sel ini."),
        _code(RESUME),
        _md("## 3. Evaluasi"),
        _code(EVALUATE),
        *([_code(EVALUATE_TEST)] if splits.get("test") else []),
        _md("## 4. Export ONNX"),
        _code(EXPORT),
        _md(f"""
Selesai. `best.pt` dan `best.onnx` ada di `MyDrive/labelforge/runs/{run_name}/weights/`.
Unduh `best.onnx`, lalu di LabelForge buka tab **Model** dan upload file itu beserta mAP di
atas. Model langsung bisa dipakai untuk auto-label dan tercatat berasal dari versi
**{version.name}**.
"""),
    ]
    return {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


def notebook_bytes(project: Project, version: DatasetVersion) -> bytes:
    return json.dumps(colab_notebook(project, version), indent=1, ensure_ascii=False).encode("utf-8")
