"""Pengelompokan gambar per segmen waktu per sumber, untuk split tanpa kebocoran.

Frame CCTV/video yang berdekatan hampir identik. Bila frame 757 masuk train dan 758 masuk
val, metrik validasi terlihat lebih baik dari kenyataan. Di sini gambar dikelompokkan:

1. Sumber: video/kamera RTSP memakai id-nya; gambar lain memakai awalan nama file
   (`kamera3_757.jpg` -> `kamera3`).
2. Urutan: waktu frame video, waktu capture kamera, atau nomor terakhir di nama file.
3. Salinan frame yang sama (`kamera3_758_jpg.rf.<hash>.jpg` beberapa kali) menjadi satu frame.
4. Frame per sumber diurutkan lalu dipotong per `segment_size` frame berturut-turut.
"""

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from labelforge.models.enums import ImageSource

# Akhiran salinan dari tool labeling lain: `<nama>_jpg.rf.<hash>.jpg`.
_COPY_SUFFIX = re.compile(r"[._](jpe?g|png|bmp|webp|tiff?)\.rf\.[0-9a-f]+$", re.IGNORECASE)
_EXT = re.compile(r"\.[A-Za-z0-9]{2,5}$")
_TOKEN = re.compile(r"[_\-. ]+")
_LAST_NUMBER = re.compile(r"(\d+)(?!.*\d)")


@dataclass(frozen=True)
class ImageMeta:
    id: int
    source_type: str
    source_id: int | None
    filename: str
    frame_time_s: float | None
    captured_at: datetime | None


def frame_key(meta: ImageMeta) -> tuple[str, float, str]:
    """(sumber, posisi urut, identitas frame). Salinan frame yang sama punya identitas sama."""
    if meta.source_type in (ImageSource.VIDEO, ImageSource.RTSP) and meta.source_id is not None:
        source = f"{meta.source_type}:{meta.source_id}"
        if meta.frame_time_s is not None:
            return source, meta.frame_time_s, f"{source}@{meta.frame_time_s}"
        if meta.captured_at is not None:
            ts = meta.captured_at.timestamp()
            return source, ts, f"{source}@{ts}"
    base = _COPY_SUFFIX.sub("", _EXT.sub("", meta.filename))
    source = _TOKEN.split(base, maxsplit=1)[0].lower() or "lain"
    number = _LAST_NUMBER.search(base)
    if number is None:
        return source, float(meta.id), f"id:{meta.id}"
    return source, float(number.group(1)), f"{source}#{base.lower()}"


def segment_groups(metas: Iterable[ImageMeta], segment_size: int) -> tuple[list[list[int]], list[str]]:
    """Kelompokkan gambar menjadi segmen. Hasil: (daftar grup id gambar, sumber tiap grup)."""
    frames: dict[str, dict[str, tuple[float, list[int]]]] = defaultdict(dict)
    for meta in metas:
        source, position, identity = frame_key(meta)
        entry = frames[source].setdefault(identity, (position, []))
        entry[1].append(meta.id)

    groups: list[list[int]] = []
    strata: list[str] = []
    for source in sorted(frames):
        ordered = sorted(frames[source].values(), key=lambda e: (e[0], min(e[1])))
        for start in range(0, len(ordered), segment_size):
            groups.append([i for _, ids in ordered[start : start + segment_size] for i in ids])
            strata.append(source)
    return groups, strata
