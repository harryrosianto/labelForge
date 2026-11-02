"""Memilih frame yang layak disimpan dari aliran pesan `detections` SysGuard.

Pesan datang sekitar 15 kali per detik per kamera; menyimpan semuanya hanya menghasilkan
ribuan frame yang hampir sama. Aturan per kamera, urut prioritas:

1. violation: ada orang dengan PPE yang kurang (`ppe_missing`), jeda per track.
2. uncertain: ada box PPE dengan skor di zona ragu (contoh paling berharga untuk training).
3. interval: ada orang, satu frame tiap `interval_s`.
4. empty: tidak ada orang maupun box, satu frame tiap `empty_interval_s` (contoh negatif).

Semua alasan tunduk pada jeda minimum, kuota per jam, dan penyaring duplikat: frame dilewati
bila susunan box-nya hampir sama dengan frame terakhir yang disimpan (orang diam di tempat).
"""

from collections import deque
from dataclasses import dataclass, field

from lfcapture.config import Config

Box = tuple[float, float, float, float]

VIOLATION, UNCERTAIN, INTERVAL, EMPTY = "violation", "uncertain", "interval", "empty"


@dataclass
class Detections:
    """Bagian pesan `detections` yang dipakai; box xyxy ternormalisasi 0..1."""

    camera_id: int
    ts: float
    frame_size: tuple[int, int] | None
    tracks: list[dict]
    items: list[dict]

    @classmethod
    def from_message(cls, msg: dict) -> "Detections | None":
        if msg.get("type") != "detections" or not isinstance(msg.get("camera_id"), int):
            return None
        size = msg.get("frame_size")
        frame_size = (int(size[0]), int(size[1])) if isinstance(size, list) and len(size) == 2 else None
        tracks = [t for t in msg.get("tracks") or [] if _valid_box(t.get("box"))]
        items = [i for i in msg.get("items") or [] if _valid_box(i.get("box"))]
        ts = float(msg.get("ts") or 0.0)
        return cls(msg["camera_id"], ts, frame_size, tracks, items)

    def boxes(self) -> list[tuple[str, Box]]:
        out: list[tuple[str, Box]] = [("__person__", tuple(t["box"])) for t in self.tracks]
        out += [(str(i.get("cls")), tuple(i["box"])) for i in self.items]
        return out


def _valid_box(box) -> bool:
    return isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def similar(a: list[tuple[str, Box]], b: list[tuple[str, Box]], threshold: float) -> bool:
    """True bila kedua susunan box sama jumlah & class-nya dan tiap box punya pasangan IoU tinggi."""
    if len(a) != len(b) or sorted(c for c, _ in a) != sorted(c for c, _ in b):
        return False
    remaining = list(b)
    for cls, box in a:
        match = next((j for j, (c, other) in enumerate(remaining)
                      if c == cls and iou(box, other) >= threshold), None)  # fmt: skip
        if match is None:
            return False
        remaining.pop(match)
    return True


@dataclass
class _CameraState:
    last_save: float = float("-inf")
    last_by_reason: dict[str, float] = field(default_factory=dict)
    last_by_track: dict[int, float] = field(default_factory=dict)
    last_boxes: list[tuple[str, Box]] | None = None
    saves: deque = field(default_factory=deque)  # waktu simpan dalam satu jam terakhir


@dataclass
class Decision:
    reason: str | None
    skipped: str | None = None  # "dedup" | "quota" bila ada alasan tetapi tidak disimpan


class Selector:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._cams: dict[int, _CameraState] = {}

    def _state(self, camera_id: int) -> _CameraState:
        return self._cams.setdefault(camera_id, _CameraState())

    def _reason(self, det: Detections, st: _CameraState, now: float) -> str | None:
        cfg = self.cfg
        if now - st.last_save < cfg.min_gap_s:
            return None
        if any(t.get("ppe_missing") and now - st.last_by_track.get(t.get("id"), float("-inf"))
               >= cfg.violation_cooldown_s for t in det.tracks):  # fmt: skip
            return VIOLATION
        if any(cfg.uncertain_low <= float(i.get("score") or 0) <= cfg.uncertain_high
               for i in det.items) and \
                now - st.last_by_reason.get(UNCERTAIN, float("-inf")) >= cfg.uncertain_cooldown_s:  # fmt: skip
            return UNCERTAIN
        if det.tracks and now - st.last_by_reason.get(INTERVAL, float("-inf")) >= cfg.interval_s:
            return INTERVAL
        if not det.tracks and not det.items and \
                now - st.last_by_reason.get(EMPTY, float("-inf")) >= cfg.empty_interval_s:
            return EMPTY
        return None

    def decide(self, det: Detections, now: float) -> Decision:
        st = self._state(det.camera_id)
        reason = self._reason(det, st, now)
        if reason is None:
            return Decision(None)
        while st.saves and now - st.saves[0] >= 3600:
            st.saves.popleft()
        if len(st.saves) >= self.cfg.max_per_hour:
            return Decision(None, "quota")
        boxes = det.boxes()
        # Adegan diam berjam-jam tetap disimpan sesekali (cahaya berubah sepanjang hari).
        recent = now - st.last_save < self.cfg.empty_interval_s
        if boxes and recent and st.last_boxes is not None and \
                similar(boxes, st.last_boxes, self.cfg.dedup_iou):
            return Decision(None, "dedup")
        return Decision(reason)

    def mark_saved(self, det: Detections, reason: str, now: float) -> None:
        """Dipanggil setelah frame benar-benar tersimpan, supaya kegagalan tidak memakan jatah."""
        st = self._state(det.camera_id)
        st.last_save = now
        st.last_by_reason[reason] = now
        if det.tracks:  # frame apa pun yang berisi orang juga memenuhi interval
            st.last_by_reason[INTERVAL] = now
        for t in det.tracks:
            if t.get("ppe_missing"):
                st.last_by_track[t.get("id")] = now
        if len(st.last_by_track) > 1000:  # id track terus bertambah; buang yang sudah lama
            st.last_by_track = {k: v for k, v in st.last_by_track.items() if now - v < 3600}
        st.last_boxes = det.boxes()
        st.saves.append(now)
