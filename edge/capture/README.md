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
~/dataset/                         CAPTURE_DIR
  status.json                      ringkasan berkala (site, terhubung, jumlah, disk)
  mondelez-cikarang/               satu folder per site (lokasi), lihat `lfc site`
    ppe-20261103/
      data.yaml                      names = CAPTURE_CLASSES
      images/cam3_1762156712345.jpg  JPEG dari SysGuard, tidak di-encode ulang
      labels/cam3_1762156712345.txt  "cls cx cy w h conf"
      meta/20261103.jsonl            alasan, track, PPE yang kurang, selisih waktu
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
```

Akun SysGuard dibuat di Edge Gateway (`https://<ip>/system`, kartu Users) dengan role viewer
dan tanpa TOTP. Password pabrik gateway ditolak SysGuard; pakai password sendiri, disimpan di
file `chmod 600` (`SG_PASSWORD_FILE`) tanpa diketik di riwayat shell:

```bash
umask 077; read -rsp "Password: " P; printf '%s' "$P" > ~/lfcapture/password; unset P; echo
```

### Sebagai service (jalan saat boot)

`/etc` di perangkat SysGuard adalah image read-only yang diganti saat update OS, jadi perekam
dipasang sebagai service milik user di `~/.config/systemd/user` (di `/home`, persisten):

```bash
sudo loginctl enable-linger sysedge     # sekali; ulangi setelah update OS (slot berganti)
cd ~/lfcapture/src && sh deploy/install-service.sh
```

Skrip memasang perintah `lfc` ke `~/.local/bin`, menjalankan `lfc check`, lalu memasang,
mengaktifkan, dan me-restart service. Service berprioritas rendah (`Nice=10`, I/O idle) dan
restart sendiri bila mati. Koneksi putus, SysGuard restart, atau sesi berakhir ditangani
perekam dengan login dan sambung ulang otomatis.

### Perintah `lfc` (lewat SSH)

```
lfc status                     perekam, autostart, site, koneksi SysGuard, frame hari ini, disk
lfc start | stop               mulai / hentikan perekaman
lfc autostart on | off         ikut jalan saat perangkat menyala
lfc site                       site aktif
lfc site mondelez-cikarang     pindah site (perekam di-restart, data masuk folder site itu)
lfc sites                      daftar site: jumlah hari, frame, ukuran, rentang tanggal
lfc log [-f] [-n 50]           log perekam (file berotasi, maks ~3 MB, tanpa sudo)
lfc clean <site> --older-than 7   hapus folder harian lebih tua dari 7 hari (bukan hari ini)
lfc reset <site>               hapus seluruh data satu site
lfc check                      uji login, kamera, snapshot, disk
lfc vpn [up]                   status akses jarak jauh / daftarkan perangkat ke Tailscale
```

- Nama site: huruf kecil, angka, dan `-`. Site aktif disimpan di `~/lfcapture/site.env`.
- `clean` dan `reset` menampilkan apa yang akan dihapus lalu meminta konfirmasi (`hapus` atau
  nama site). Di sesi non-interaktif tambahkan `--konfirmasi <teks>`. `reset` menolak site
  yang sedang direkam: `lfc stop` atau pindah site dulu.
- Saat batas disk tercapai perekaman berhenti (`lfc status` menandai PENUH); deteksi SysGuard
  tidak terpengaruh, dan perekaman lanjut sendiri setelah ruang dikosongkan.
- Sesi SSH biasa sudah punya `lfc` di PATH. Untuk perintah satu baris dari laptop pakai path
  lengkap: `ssh sysedge@<ip> .local/bin/lfc status`.

### Akses jarak jauh (Tailscale)

Perangkat di jaringan klien diakses lewat Tailscale yang berjalan sebagai service user dalam mode
userspace (tanpa root, tanpa antarmuka jaringan baru). Koneksi hanya keluar dari perangkat, jadi
tidak ada port yang dibuka di jaringan klien; SSH yang masuk lewat Tailscale diteruskan ke sshd
lokal. Pasang sebelum perangkat dibawa ke lokasi, dan minta persetujuan IT klien.

1. Di laptop: unduh paket resmi arm64 dari `https://pkgs.tailscale.com/stable/`
   (`tailscale_<versi>_arm64.tgz` dan `.sha256`-nya), cocokkan checksum, lalu salin
   `tailscale` dan `tailscaled` ke `~/tailscale/bin/` di perangkat (`chmod 755`).
2. Di perangkat: `cd ~/lfcapture/src && sh deploy/install-tailscale.sh`
3. Di konsol admin Tailscale (tailnet perusahaan): buat auth key sekali pakai. Bila memakai tag,
   izinkan dulu di ACL (`tagOwners`) dan batasi akses tag itu ke port 22 untuk engineer saja.
4. Di perangkat, simpan kunci tanpa tercetak di layar atau riwayat, lalu daftarkan:

   ```bash
   umask 077; read -rsp "Auth key: " K; printf '%s' "$K" > ~/tailscale/authkey; unset K; echo
   lfc vpn up --tags tag:edge      # tanpa --tags bila ACL belum disiapkan
   ```

   File kunci dihapus otomatis setelah berhasil.
5. Di konsol admin: matikan *key expiry* untuk perangkat ini, kalau tidak koneksi putus sendiri
   setelah masa berlaku kunci habis.

`lfc vpn` menampilkan status, IP Tailscale (100.x.x.x), dan tailnet. Dari laptop yang ikut
tailnet yang sama: `ssh sysedge@<ip-tailscale> .local/bin/lfc status`, dan skrip tarik dengan
`-Device sysedge@<ip-tailscale>`. Setelah update OS yang berpindah slot, jalankan ulang
`sudo loginctl enable-linger sysedge` agar kedua service kembali jalan saat boot.

### Menarik dataset ke laptop

```powershell
.\edge\capture\deploy\tarik-dataset.ps1 -Device sysedge@<ip> -Tujuan D:\dataset-edge [-Site mondelez-cikarang]
```

Tiap folder harian dikirim sebagai satu aliran tar lalu di-ZIP per site
(`<Tujuan>\<site>\<site>-ppe-YYYYMMDD.zip`), siap diimport. Folder yang sudah ditarik dilewati
kecuali folder hari ini; frame yang sedang ditulis saat ditarik dilewati dan ikut di tarikan
berikutnya. Data di perangkat tidak dihapus: setelah ZIP diperiksa, `lfc clean`.

## Test

```bash
pip install -e ".[dev]"
pytest
```

Test memakai SysGuard palsu (HTTP + WebSocket lokal). Bila paket `labelforge` terpasang di
environment yang sama, test juga memastikan hasil perekam terbaca importer LabelForge.
