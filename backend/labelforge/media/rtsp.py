"""Capture frame berkala dari kamera RTSP (OpenCV + FFmpeg).

Stream dibaca terus (grab) agar buffer tidak menumpuk; frame terbaru di-decode tiap
`interval_s`. Koneksi putus → coba sambung ulang beberapa kali dengan jeda bertambah.
`open_capture`, `clock`, dan `sleep` bisa diganti untuk test tanpa kamera.
"""

import time
from collections.abc import Callable, Iterator
from typing import Protocol

import cv2
import numpy as np
from pydantic import BaseModel, Field, model_validator


class CaptureLike(Protocol):
    def isOpened(self) -> bool: ...  # noqa: N802 (nama API OpenCV)
    def grab(self) -> bool: ...
    def retrieve(self) -> tuple[bool, np.ndarray | None]: ...
    def release(self) -> None: ...


class CameraError(RuntimeError):
    pass


# Jam & jeda sebagai fungsi modul (dicari saat dipanggil) agar bisa diganti di test.
def _now() -> float:
    return time.monotonic()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def open_capture(url: str, timeout_s: float = 10.0) -> CaptureLike:
    params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(timeout_s * 1000),
              cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(timeout_s * 1000)]  # fmt: skip
    return cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)


class CaptureOptions(BaseModel):
    interval_s: float = Field(5.0, ge=0.2, le=3600, description="Jeda antar frame yang disimpan")
    duration_s: float | None = Field(default=600, gt=0, le=7 * 24 * 3600)
    max_frames: int | None = Field(default=None, ge=1, le=100_000)
    dedup_threshold: int = Field(6, ge=0, le=32)
    reconnect_attempts: int = Field(5, ge=0, le=50)

    @model_validator(mode="after")
    def _has_limit(self):
        if self.duration_s is None and self.max_frames is None:
            raise ValueError("Isi duration_s atau max_frames agar capture punya batas")
        return self


def grab_one(url: str, timeout_s: float = 10.0, opener: Callable[..., CaptureLike] | None = None) -> np.ndarray:
    """Ambil satu frame (untuk tes koneksi). Frame RGB."""
    cap = (opener or open_capture)(url, timeout_s)
    try:
        if not cap.isOpened():
            raise CameraError("Kamera tidak bisa dihubungi (cek alamat, port, kredensial, jaringan)")
        for _ in range(30):  # beberapa frame awal stream bisa kosong
            if cap.grab():
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        raise CameraError("Terhubung tetapi tidak ada frame yang terbaca")
    finally:
        cap.release()


def capture_frames(
    url: str,
    opts: CaptureOptions,
    *,
    should_stop: Callable[[], bool] = lambda: False,
    on_reconnect: Callable[[int], None] = lambda n: None,
    opener: Callable[..., CaptureLike] | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> Iterator[np.ndarray]:
    """Hasilkan frame RGB tiap `interval_s` sampai durasi/jumlah tercapai atau `should_stop()`."""
    opener = opener or open_capture  # dicari saat dipanggil agar bisa diganti di test
    clock = clock or _now
    sleep = sleep or _sleep
    start = clock()
    next_at = start
    produced = 0
    failures = 0
    cap = opener(url)
    try:
        while True:
            if should_stop():
                return
            if opts.duration_s is not None and clock() - start >= opts.duration_s:
                return
            if opts.max_frames is not None and produced >= opts.max_frames:
                return
            if not cap.isOpened() or not cap.grab():
                cap.release()
                failures += 1
                if failures > opts.reconnect_attempts:
                    raise CameraError(f"Koneksi kamera terputus; gagal tersambung lagi setelah {failures - 1} percobaan")
                on_reconnect(failures)
                sleep(min(30.0, 2.0 ** failures))
                cap = opener(url)
                continue
            failures = 0
            if clock() >= next_at:
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    produced += 1
                    next_at = clock() + opts.interval_s
                    yield cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    finally:
        cap.release()
