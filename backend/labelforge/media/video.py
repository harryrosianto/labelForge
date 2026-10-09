"""Baca metadata video dan ambil frame pada interval tertentu (OpenCV)."""

from collections.abc import Iterator
from dataclasses import dataclass

import cv2
import numpy as np
from pydantic import BaseModel, Field, model_validator

VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".m4v", ".webm", ".mpg", ".mpeg"}


class VideoReadError(ValueError):
    pass


@dataclass
class VideoInfo:
    duration_s: float
    fps: float
    frame_count: int
    width: int
    height: int


def probe(path: str) -> VideoInfo:
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise VideoReadError("Video tidak bisa dibuka (format/codec tidak didukung)")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if fps <= 0 or width <= 0 or height <= 0:
            raise VideoReadError("Metadata video tidak valid (fps/resolusi tidak terbaca)")
        return VideoInfo(round(frames / fps, 3), round(fps, 3), frames, width, height)
    finally:
        cap.release()


class ExtractOptions(BaseModel):
    """Ambil satu frame tiap `every_s` detik, atau `fps` frame per detik (pilih salah satu)."""

    every_s: float | None = Field(default=1.0, gt=0, le=3600)
    fps: float | None = Field(default=None, gt=0, le=60)
    start_s: float = Field(0.0, ge=0)
    end_s: float | None = Field(default=None, gt=0)
    max_frames: int = Field(500, ge=1, le=100_000)
    dedup_threshold: int = Field(6, ge=0, le=32, description="Jarak dHash maks. dianggap mirip (0 = nonaktif)")

    @model_validator(mode="after")
    def _one_rate(self):
        if self.fps is not None:
            self.every_s = None
        if self.every_s is None and self.fps is None:
            raise ValueError("Isi every_s atau fps")
        if self.end_s is not None and self.end_s <= self.start_s:
            raise ValueError("end_s harus lebih besar dari start_s")
        return self

    @property
    def step_s(self) -> float:
        return self.every_s if self.every_s is not None else 1.0 / self.fps


def sample_times(info: VideoInfo, opts: ExtractOptions) -> list[float]:
    end = min(info.duration_s, opts.end_s) if opts.end_s is not None else info.duration_s
    times, t = [], opts.start_s
    while t < end and len(times) < opts.max_frames:
        times.append(round(t, 3))
        t += opts.step_s
    return times


def iter_frames(path: str, times: list[float], fps: float) -> Iterator[tuple[float, np.ndarray | None]]:
    """(waktu, frame RGB atau None bila gagal dibaca). Dibaca berurutan (grab) lalu decode
    hanya frame yang dibutuhkan; lebih akurat daripada seek pada banyak codec."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise VideoReadError("Video tidak bisa dibuka")
    try:
        targets = [(round(t * fps), t) for t in times]
        index = -1
        for target, t in targets:
            ok = True
            while index < target and ok:
                ok = cap.grab()
                index += 1
            if not ok:
                yield t, None
                continue
            ok, frame = cap.retrieve()
            yield t, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if ok else None
    finally:
        cap.release()
