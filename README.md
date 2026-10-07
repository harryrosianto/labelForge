# LabelForge

Web platform untuk membuat dataset object detection dengan auto-labeling AI — mirip Roboflow,
difokuskan untuk kamera CCTV gudang (pallet, kardus, orang, forklift).

Alur: **project → class (text prompt / contoh visual) → upload gambar → auto-label AI →
review & koreksi di editor → export YOLO / COCO.**

Roadmap fase berikutnya ada di [ROADMAP.md](ROADMAP.md); spesifikasi Fase 1 di
[docs/SPEC_FASE1.md](docs/SPEC_FASE1.md).

## Arsitektur

```
browser ──► frontend (React + Vite, nginx di Docker)
               │  /api
               ▼
            web (FastAPI) ──► SQLite/PostgreSQL + storage gambar (/data)
               │  Celery task
               ▼
            redis ──► worker (Celery, model AI di-load sekali) ──► /data
                         │ (opsional)
                         └─► RemoteApiProvider ──HTTP──► inference server di mesin GPU lain
```

| Komponen | Teknologi |
|---|---|
| API | FastAPI, SQLAlchemy 2.0, Alembic, SQLite (siap PostgreSQL via `DATABASE_URL`) |
| Worker | Celery + Redis, `--pool=solo` (satu proses, model tetap di memori) |
| Model | PyTorch + HuggingFace `transformers` (tanpa library AGPL) |
| Frontend | React, TypeScript, Tailwind, TanStack Query, react-konva |

**Kenapa Celery + Redis:** proses web tetap ringan & responsif (tidak memuat torch), model
cukup di-load sekali di worker, job tidak hilang saat web restart (`acks_late`), dan queue
per jenis pekerjaan (`inference`, nanti `training`) bisa diarahkan ke mesin berbeda.

### Provider auto-label

| Provider | Mode | Sumber anotasi | Catatan |
|---|---|---|---|
| **OWLv2** (default) | `text` | `ai:owlv2_text` | Paling akurat & cepat pada uji CCTV gudang (~9 dtk/gambar di CPU) |
| OWLv2 | `image_guided` | `ai:owlv2_image` | Mencari objek yang mirip **contoh visual** (crop) per class |
| Grounding DINO | `text` | `ai:grounding_dino` | `grounding-dino-base`; ~24 dtk/gambar di CPU |
| Remote | `<provider>:<mode>` | sama dengan model di server | Memanggil inference server LabelForge di mesin lain |

> Spesifikasi awal menetapkan Grounding DINO sebagai default. Setelah diuji pada foto CCTV
> gudang, OWLv2 teks mendeteksi pallet lebih baik dan ~2,5× lebih cepat, sehingga dijadikan
> default. Ubah dengan `DEFAULT_PROVIDER` / `DEFAULT_MODE` di `.env`.

Tips prompt: tulis sinonim dipisah koma, mis. class `pallet` → `wooden pallet, plastic pallet`.
Setiap frasa menjadi query tersendiri yang dipetakan ke class yang sama.

## Menjalankan dengan Docker (disarankan)

Butuh Docker Desktop (Windows/macOS) atau Docker Engine + Compose v2.24+.

```bash
cp .env.example .env            # opsional, untuk mengubah threshold/model
docker compose up -d --build    # CPU
```

Buka **http://localhost:8080**. Build pertama mengunduh PyTorch (beberapa ratus MB) dan job
pertama mengunduh bobot model (~600 MB OWLv2, ~900 MB Grounding DINO) ke volume `hf_cache`.

Sudah punya cache model HuggingFace di host? Pakai ulang agar tidak download lagi:

```bash
HF_CACHE_DIR=$HOME/.cache/huggingface docker compose up -d          # Linux/macOS
$env:HF_CACHE_DIR="$env:USERPROFILE\.cache\huggingface"; docker compose up -d   # PowerShell
```

### GPU (NVIDIA)

Butuh driver NVIDIA + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/)
(di Windows: Docker Desktop dengan backend WSL2 sudah menyertakan dukungan GPU).

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

Default memakai PyTorch CUDA 12.6 (`cu126`). Untuk driver terbaru (CUDA 13):
`TORCH_INDEX_URL=https://download.pytorch.org/whl/cu130`. Mode GPU mengaktifkan fp16
(`USE_FP16=true`); matikan jika hasil deteksi berbeda dari CPU.

### Data

SQLite dan gambar disimpan di named volume `labelforge_data` (bukan bind mount, karena SQLite
mode WAL yang dipakai bersama web & worker tidak andal di bind mount Docker Desktop).
Backup:

```bash
docker run --rm -v labelforge_data:/data -v "$PWD":/backup alpine tar czf /backup/labelforge-data.tgz -C /data .
```

## Menjalankan untuk development (tanpa Docker)

Prasyarat: Python 3.11+, Node 20.19+/22+, Redis (mis. `docker run -d -p 6379:6379 redis:7-alpine`).

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/activate                      # Linux/macOS: source .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # atau cu126 untuk GPU
pip install -e ".[ml,dev]"
alembic upgrade head

uvicorn labelforge.api.main:app --reload --port 8000                     # terminal 1
celery -A labelforge.worker.celery_app worker --pool=solo -Q inference --loglevel=INFO   # terminal 2

# Frontend (terminal 3)
cd frontend
npm install
npm run dev          # http://localhost:5173, /api diteruskan ke :8000
```

Swagger API: http://localhost:8000/docs

Test:

```bash
cd backend && pytest          # konversi format, NMS, mapping label, exporter, API, job
cd frontend && npm test       # logika editor
```

## CLI uji model

Uji kualitas model di foto asli tanpa web/DB/Redis:

```bash
cd backend
python -m labelforge.cli providers                         # daftar provider & parameter

# OWLv2 teks (default)
python -m labelforge.cli detect --classes "pallet,box" \
    --prompt "pallet=wooden pallet, plastic pallet" --prompt "box=cardboard box" \
    --input ./samples --output ./out/owl

# Grounding DINO, threshold lebih rendah
python -m labelforge.cli detect --provider grounding_dino --classes "pallet,person,forklift" \
    --box-threshold 0.25 --input ./samples --output ./out/gdino

# OWLv2 dengan contoh visual: exemplars/<nama_class>/*.png
python -m labelforge.cli detect --provider owlv2 --mode image_guided \
    --exemplar-dir ./exemplars --input ./samples --output ./out/owl_img

# Impor folder gambar ke project yang sudah ada
python -m labelforge.cli import-images --project-id 1 --input ./samples
```

Output per gambar: `<nama>.jpg` (box tergambar) dan `<nama>.json`, plus `summary.json`.
Opsi lain: `--param class_agnostic_nms=true`, `--device cpu|cuda`, `--fp16`, `--limit N`.

## Menggunakan aplikasi

1. **Classes** — tambah class; isi *text prompt* deskriptif (sinonim dipisah koma). Urutan
   class = index class di YOLO dan shortcut angka di editor.
2. **Upload** — drag & drop gambar atau ZIP. Duplikat (hash sama) otomatis dilewati;
   orientasi EXIF diterapkan.
3. **Auto-label** — pilih model, mode & threshold; target: belum berlabel / semua / terpilih
   dari galeri. Box AI yang belum di-approve diganti setiap job; box manual & yang sudah
   di-approve tidak disentuh.
4. **Galeri → editor** — filter status / class / sumber / confidence rendah, lalu review:

   | Tombol | Aksi |
   |---|---|
   | ← / → | gambar sebelumnya / berikutnya (otomatis simpan) |
   | drag di area kosong | gambar box dengan class aktif |
   | 1–9 | pilih class (atau ganti class box terpilih) |
   | Del | hapus box |
   | Enter | approve semua box → `reviewed`, lanjut |
   | Ctrl+Z / Ctrl+S | undo / simpan |
   | Spasi + drag, scroll | geser, zoom |

   Box AI bergaris putus-putus + confidence sampai di-approve atau diedit. **Jadikan contoh
   visual** menyimpan crop box terpilih untuk mode image-guided OWLv2.
5. **Export** — YOLO (`images/`, `labels/`, `data.yaml`) atau COCO JSON, split train/val/test
   dengan seed. Default hanya gambar `reviewed`; gambar `unlabeled` tidak pernah diekspor
   (tanpa label ia akan terbaca sebagai gambar tanpa objek). Gambar reviewed tanpa box
   diekspor dengan file label kosong sebagai contoh negatif.

## Menambah provider baru

Contoh: model YOLO hasil training sendiri (Fase 3) atau API lain.

1. Buat `backend/labelforge/providers/my_model.py`:

   ```python
   from labelforge.providers.base import ClassDef, Detection, LabelingProvider, ParamSpec, require_ml_deps
   from labelforge.providers.registry import register_provider


   @register_provider
   class MyModelProvider(LabelingProvider):
       name = "my_model"                 # id provider (dipakai API & source "ai:my_model")
       label = "Model saya"
       modes = ("text",)
       per_class_nms_param = "nms_iou"   # parameter IoU untuk NMS per class (opsional)

       @classmethod
       def param_specs(cls, mode):       # otomatis jadi form di UI
           return [
               ParamSpec("score_threshold", "float", 0.3, "Score threshold", min=0, max=1, step=0.01),
               ParamSpec("nms_iou", "float", 0.5, "IoU NMS", min=0.05, max=1, step=0.05),
           ]

       def _load(self):                  # dipanggil sekali per proses worker
           require_ml_deps("torch")
           import torch
           self.model = ...              # load bobot; set self.device

       def _detect(self, image, classes: list[ClassDef], params) -> list[Detection]:
           # image: PIL RGB (EXIF sudah diterapkan). Kembalikan box pixel xyxy.
           return [Detection(classes[0].id, (x1, y1, x2, y2), score) for ...]
   ```

2. Tambahkan modulnya ke `BUILTIN_MODULES` di `providers/registry.py`.
3. Selesai — provider muncul di dropdown Auto-label, CLI (`--provider my_model`) dan inference
   server. Clip ke batas gambar, filter ukuran minimum, dan NMS per class / antar-class
   ditangani otomatis oleh `LabelingProvider`.

Override opsional: `is_available()` (cek konfigurasi), `source_tag(mode)`,
`class_warnings(mode, classes)` (peringatan sebelum job, mis. class tanpa exemplar).
Import library berat di dalam `_load()`/`_detect()`, bukan di level modul — proses web tidak
memasang torch.

## Inference di mesin GPU lain

Jalankan inference server di mesin GPU (butuh kode backend + `pip install -e ".[ml]"`):

```bash
INFERENCE_SERVER_TOKEN=rahasia python -m labelforge.inference_server --port 8100 --preload owlv2
```

Lalu di `.env` server LabelForge:

```
REMOTE_INFERENCE_URL=http://gpu-server:8100
REMOTE_INFERENCE_TOKEN=rahasia
```

Pilih model **Remote inference server** di halaman Auto-label. Kontrak HTTP-nya
didokumentasikan di `backend/labelforge/providers/remote_api.py`.

## Konfigurasi

Semua opsi ada di [.env.example](.env.example): model id, device (`auto`/`cpu`/`cuda`),
fp16, threshold default, provider default, URL remote, ukuran thumbnail, batas upload.

## Struktur folder

```
backend/labelforge/
  api/            FastAPI app & router (projects, classes, images, annotations, jobs, export)
  core/           konversi format bbox, NMS, device, visualisasi
  providers/      LabelingProvider, registry, OWLv2, Grounding DINO, remote
  worker/         Celery app & task
  services/       logika bisnis (upload, job, editor, query galeri)
  exporters/      YOLO, COCO, split
  inference_server/  server HTTP untuk RemoteApiProvider
  cli/            CLI uji model & impor
  models/ schemas/ storage/
frontend/src/
  pages/          Projects, tab project, editor
  editor/         canvas react-konva & state editor
  api/ components/ lib/
```

Tabel `dataset_versions` dan `models` sudah ada di schema untuk Fase 2–3, fiturnya belum.
