"""Menulis frame terpilih sebagai dataset YOLO per hari yang bisa langsung diimport LabelForge.

    <out_dir>/<prefix>-YYYYMMDD/
      data.yaml                       names sesuai CAPTURE_CLASSES
      images/cam3_1762156712345.jpg   frame mentah dari SysGuard, tidak di-encode ulang
      labels/cam3_1762156712345.txt   "cls cx cy w h conf" per box
      meta/YYYYMMDD.jsonl             alasan simpan, PPE yang kurang, selisih waktu, dst.

Nama file `cam<id>_<epoch ms>` dipakai LabelForge untuk split per segmen waktu per kamera
(sumber = kata sebelum '_' pertama, urutan = angka terakhir). Tanggal folder memakai UTC.
Nama orang hasil pengenalan wajah sengaja tidak disimpan.
"""

import io
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lfcapture.config import Config
from lfcapture.select import Detections


log = logging.getLogger("lfcapture")
ASPECT_TOLERANCE = 0.02  # selisih rasio di bawah 2% dianggap sudah sesuai
JPEG_QUALITY = 92
_pillow_warned = False


def fix_aspect(jpeg: bytes, aspect: tuple[int, int] | None) -> tuple[bytes, tuple[int, int] | None]:
    """Sesuaikan rasio frame ke rasio kamera (tinggi tetap, lebar disesuaikan).

    Kamera bisa mengirim substream 4:3 (mis. 640x480) dari sensor 16:9; tampilan SysGuard
    meregangkannya kembali, tetapi frame mentah terlihat tergencet. Koordinat YOLO
    ternormalisasi, jadi label tetap pas setelah gambar diregangkan per sumbu.
    Hasil: (jpeg, ukuran baru) atau (jpeg asli, None) bila tidak perlu/tidak bisa diubah.
    """
    global _pillow_warned
    if aspect is None:
        return jpeg, None
    try:
        from PIL import Image
    except ImportError:
        if not _pillow_warned:
            log.warning("Pillow tidak terpasang: rasio gambar tidak disesuaikan (CAPTURE_ASPECT)")
            _pillow_warned = True
        return jpeg, None
    try:
        with Image.open(io.BytesIO(jpeg)) as img:
            w, h = img.size
            target_w = round(h * aspect[0] / aspect[1])
            if abs(target_w - w) / w < ASPECT_TOLERANCE:
                return jpeg, None
            out = io.BytesIO()
            img.convert("RGB").resize((target_w, h), Image.Resampling.LANCZOS).save(
                out, "JPEG", quality=JPEG_QUALITY)
    except (OSError, ValueError) as e:  # JPEG rusak: lebih baik simpan apa adanya daripada hilang
        log.warning("rasio gambar tidak bisa disesuaikan: %s", e)
        return jpeg, None
    return out.getvalue(), (target_w, h)


class DiskFull(Exception):
    """Batas disk tercapai; perekaman berhenti sementara, deteksi SysGuard tidak terganggu."""


@dataclass
class Saved:
    image: Path
    boxes: int
    ignored: int


def _clip(v: float) -> float:
    return min(1.0, max(0.0, float(v)))


def yolo_lines(det: Detections, cfg: Config) -> tuple[list[str], int]:
    """Baris label YOLO + jumlah box yang dilewati (class di luar CAPTURE_CLASSES)."""
    index = {name: i for i, name in enumerate(cfg.classes)}
    rows: list[tuple[int, list, float]] = []
    if cfg.person_class is not None:
        rows += [(index[cfg.person_class], t["box"], t.get("score")) for t in det.tracks]
    ignored = 0
    for item in det.items:
        cls = index.get(str(item.get("cls")))
        if cls is None:
            ignored += 1
            continue
        rows.append((cls, item["box"], item.get("score")))
    lines = []
    for cls, box, score in rows:
        x1, y1, x2, y2 = (_clip(v) for v in box)
        w, h = x2 - x1, y2 - y1
        if w <= 0 or h <= 0:
            ignored += 1
            continue
        conf = _clip(score if isinstance(score, (int, float)) else 1.0)
        lines.append(f"{cls} {x1 + w / 2:.5f} {y1 + h / 2:.5f} {w:.5f} {h:.5f} {conf:.3f}")
    return lines, ignored


def _data_yaml(classes: tuple[str, ...]) -> str:
    # Daftar JSON adalah YAML yang sah, dan aman untuk nama berspasi seperti "Safety Vest".
    return f"names: {json.dumps(list(classes))}\nnc: {len(classes)}\n"


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class DatasetWriter:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.out_dir.mkdir(parents=True, exist_ok=True)

    def disk_status(self) -> dict:
        usage = shutil.disk_usage(self.cfg.out_dir)
        used_pct = 100.0 * (usage.total - usage.free) / usage.total if usage.total else 100.0
        return {"used_pct": round(used_pct, 1), "free_mb": usage.free // (1024 * 1024)}

    def check_disk(self) -> None:
        s = self.disk_status()
        if s["used_pct"] >= self.cfg.disk_max_used_pct or s["free_mb"] < self.cfg.disk_min_free_mb:
            raise DiskFull(f"disk {s['used_pct']}% terpakai, sisa {s['free_mb']} MB")

    def day_dir(self, when: datetime) -> Path:
        day = self.cfg.out_dir / f"{self.cfg.prefix}-{when:%Y%m%d}"
        if not (day / "data.yaml").exists():
            for sub in ("images", "labels", "meta"):
                (day / sub).mkdir(parents=True, exist_ok=True)
            _write_atomic(day / "data.yaml", _data_yaml(self.cfg.classes).encode())
        return day

    def save(self, det: Detections, jpeg: bytes, snap_ts: float, reason: str,
             camera_name: str | None = None, aspect: tuple[int, int] | None = None) -> Saved:
        self.check_disk()
        jpeg, saved_size = fix_aspect(jpeg, aspect)
        when = datetime.fromtimestamp(snap_ts, UTC)
        day = self.day_dir(when)
        ms = int(snap_ts * 1000)
        while (day / "images" / f"cam{det.camera_id}_{ms}.jpg").exists():
            ms += 1  # dua frame pada milidetik yang sama
        stem = f"cam{det.camera_id}_{ms}"
        lines, ignored = yolo_lines(det, self.cfg)
        # Label ditulis dulu: gambar tanpa label akan terbaca sebagai contoh negatif.
        _write_atomic(day / "labels" / f"{stem}.txt", ("\n".join(lines) + "\n" if lines else "").encode())
        _write_atomic(day / "images" / f"{stem}.jpg", jpeg)
        meta = {
            "file": f"images/{stem}.jpg",
            "camera_id": det.camera_id,
            "camera_name": camera_name,
            "reason": reason,
            "det_ts": det.ts,
            "snap_ts": round(snap_ts, 3),
            "lag_ms": round((snap_ts - det.ts) * 1000) if det.ts else None,
            "frame_size": list(det.frame_size) if det.frame_size else None,
            "saved_size": list(saved_size) if saved_size else None,  # None = ukuran asli
            "tracks": [{"id": t.get("id"), "box": t["box"], "score": t.get("score"),
                        "ppe_missing": t.get("ppe_missing") or [], "safety": t.get("safety") or []}
                       for t in det.tracks],  # fmt: skip
            "boxes": len(lines),
            "ignored_boxes": ignored,
        }
        with open(day / "meta" / f"{when:%Y%m%d}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        return Saved(day / "images" / f"{stem}.jpg", len(lines), ignored)
