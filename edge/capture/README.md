# lfcapture: perekam dataset di perangkat edge SysGuard

Berjalan di perangkat edge (Raspberry Pi CM5 dengan SysGuard Vision) di samping deteksi PPE
yang sudah ada. Perekam tidak menjalankan model sendiri: ia membaca hasil deteksi SysGuard,
memilih frame yang berguna untuk training, lalu menyimpannya sebagai dataset YOLO yang
langsung bisa diimport ke LabelForge beserta prediksi model sebagai label awal.

```
SysGuard Vision (Hailo-8)
  ├─ /ws  pesan "detections" per frame: box orang + box PPE + skor + PPE yang kurang
  └─ GET /api/cameras/{id}/snapshot: frame mentah terbaru, tanpa box tergambar
          │
          ▼
lfcapture: pilih frame ─► ambil snapshot ─► <CAPTURE_DIR>/<prefix>-YYYYMMDD/
```

## Frame yang disimpan

Per kamera, urut prioritas:

| Alasan | Kapan | Jeda |
|---|---|---|
| `violation` | Ada orang dengan PPE kurang | `CAPTURE_VIOLATION_COOLDOWN_S` per track |
| `uncertain` | Ada box PPE dengan skor di antara `CAPTURE_UNCERTAIN_LOW` dan `_HIGH` | `CAPTURE_UNCERTAIN_COOLDOWN_S` |
| `interval` | Ada orang | `CAPTURE_INTERVAL_S` |
| `empty` | Tidak ada orang maupun box (contoh negatif) | `CAPTURE_EMPTY_INTERVAL_S` |

Semuanya dibatasi jeda minimum, kuota per jam, dan penyaring duplikat: frame dilewati bila
susunan box-nya hampir sama dengan frame terakhir yang disimpan (IoU `CAPTURE_DEDUP_IOU`).
Adegan yang diam lama tetap disimpan sekali tiap `CAPTURE_EMPTY_INTERVAL_S`.

Box dari SysGuard sudah melewati ambang confidence-nya, jadi deteksi yang nyaris lolos tidak
ikut terekam. Class yang tidak dikenal model (mis. hairnet) dilabeli manual di LabelForge.

## Hasil

```
ppe-20261103/
  data.yaml                      names = CAPTURE_CLASSES
  images/cam3_1762156712345.jpg  JPEG dari SysGuard, tidak di-encode ulang
  labels/cam3_1762156712345.txt  "cls cx cy w h conf"
  meta/20261103.jsonl            alasan, track, PPE yang kurang, selisih waktu deteksi ke frame
status.json                      ringkasan berkala (jumlah tersimpan/dilewati, disk)
```

- Nama `cam<id>_<epoch ms>` dipakai LabelForge untuk split per segmen waktu per kamera.
- Tanggal folder memakai UTC (jam perangkat).
- Nama orang dari pengenalan wajah tidak disimpan. Gambar tetap berisi wajah karyawan, jadi
  perlakukan folder dataset sebagai data pribadi (persetujuan klien, enkripsi, retensi).

Import di LabelForge: ZIP folder harian, lalu Upload → Import dataset dan centang tandai untuk
review, atau `python -m labelforge.cli import-dataset --project-id N --input <folder> --review`.
Box masuk sebagai label AI belum di-approve dengan confidence-nya, sehingga filter confidence
rendah dan audit sampel bisa dipakai.

## Menjalankan

Butuh Python 3.11+ dan paket `websockets`. Perangkat di lokasi klien biasanya tanpa internet,
jadi wheel diunduh di laptop lalu disalin:

```bash
# di laptop (Python apa saja), untuk Pi dengan Python 3.13 aarch64
pip download websockets --only-binary=:all: --platform manylinux2014_aarch64 \
    --python-version 3.13 -d wheels/
```

```bash
# di laptop, dari root repo: salin kode dan wheel ke perangkat
git archive --format=tar HEAD edge/capture | ssh sysedge@<ip> \
    'mkdir -p ~/lfcapture/src ~/lfcapture/wheels && tar -x -C ~/lfcapture/src --strip-components=2'
scp edge/capture/wheels/*.whl sysedge@<ip>:lfcapture/wheels/
```

```bash
# di perangkat. Paket tidak di-pip-install (build offline butuh setuptools); cukup PYTHONPATH.
cd ~/lfcapture
python3 -m venv venv
venv/bin/pip install --no-index --find-links wheels websockets
umask 077; cp src/capture.env.example capture.env    # lalu isi SG_USERNAME, password, dst.
PYTHONPATH=src venv/bin/python -m lfcapture check --env-file capture.env
PYTHONPATH=src venv/bin/python -m lfcapture run --env-file capture.env
```

Akun SysGuard dibuat di Edge Gateway (`https://<ip>/system`, kartu Users) dengan role viewer
dan tanpa TOTP. Password pabrik gateway ditolak SysGuard; pakai password sendiri, disimpan di
file `chmod 600` (`SG_PASSWORD_FILE`) tanpa diketik di riwayat shell:

```bash
umask 077; read -rsp "Password: " P; printf '%s' "$P" > ~/lfcapture/password; unset P; echo
```

`check` mencoba login, mendaftar kamera, mengambil satu snapshot per kamera, dan memeriksa
disk. `run` merekam sampai dihentikan (Ctrl+C atau SIGTERM). Koneksi putus, SysGuard restart,
atau sesi berakhir ditangani dengan login dan sambung ulang otomatis. Saat batas disk tercapai
perekaman berhenti; deteksi SysGuard tidak terpengaruh, dan perekaman lanjut sendiri setelah
ruang dikosongkan.

## Test

```bash
pip install -e ".[dev]"
pytest
```

Test memakai SysGuard palsu (HTTP + WebSocket lokal). Bila paket `labelforge` terpasang di
environment yang sama, test juga memastikan hasil perekam terbaca importer LabelForge.
