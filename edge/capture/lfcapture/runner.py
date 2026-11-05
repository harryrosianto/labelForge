"""Loop utama: login, subscribe /ws, pilih frame, ambil snapshot, tulis dataset.

Koneksi putus atau SysGuard restart tidak menghentikan perekam: login dan sambung ulang
dengan jeda bertahap (2 detik sampai 60 detik). Snapshot diambil di thread agar pembacaan
/ws tidak tertahan, dengan paling banyak `MAX_INFLIGHT` snapshot sekaligus.
"""

import asyncio
import json
import logging
import time
from collections import Counter
from datetime import UTC, datetime

from websockets.exceptions import ConnectionClosed, InvalidStatus

from lfcapture.client import (
    CLOSE_POLICY,
    CLOSE_SESSION_ENDED,
    ApiError,
    AuthError,
    SysGuardClient,
    subscribe,
)
from lfcapture.config import Config, parse_aspect
from lfcapture.select import Detections, Selector
from lfcapture.writer import DatasetWriter, DiskFull

log = logging.getLogger("lfcapture")
MAX_INFLIGHT = 2
BACKOFF_MIN, BACKOFF_MAX = 2.0, 60.0


class Recorder:
    def __init__(self, cfg: Config, client: SysGuardClient | None = None,
                 writer: DatasetWriter | None = None, clock=time.monotonic):
        self.cfg = cfg
        self.client = client or SysGuardClient(cfg)
        self.writer = writer or DatasetWriter(cfg)
        self.selector = Selector(cfg)
        self.clock = clock
        self.names: dict[int, str | None] = {}
        self.aspects: dict[int, tuple[int, int] | None] = {}
        self.stats: Counter = Counter()
        self.disk_full = False
        self._reauth = False
        self._inflight = asyncio.Semaphore(MAX_INFLIGHT)
        self._tasks: set[asyncio.Task] = set()

    # --- satu pesan ---------------------------------------------------------
    async def handle(self, msg: dict) -> None:
        det = Detections.from_message(msg)
        if det is None or det.camera_id not in self.names:
            return
        now = self.clock()
        decision = self.selector.decide(det, now)
        if decision.skipped:
            self.stats[f"skip_{decision.skipped}"] += 1
        if decision.reason is None:
            return
        if self.disk_full or self._inflight.locked():
            self.stats["skip_busy" if not self.disk_full else "skip_disk"] += 1
            return
        # Tandai tersimpan lebih dulu agar pesan berikutnya tidak memicu snapshot ganda;
        # jatah memang hangus bila snapshot gagal, dan itu jarang terjadi.
        self.selector.mark_saved(det, decision.reason, now)
        task = asyncio.create_task(self._save(det, decision.reason))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _save(self, det: Detections, reason: str) -> None:
        async with self._inflight:
            try:
                jpeg, received = await asyncio.to_thread(self.client.snapshot, det.camera_id)
                if det.ts and received - det.ts > self.cfg.max_snapshot_lag_s:
                    self.stats["skip_lag"] += 1  # frame sudah terlalu jauh dari deteksinya
                    return
                saved = await asyncio.to_thread(self.writer.save, det, jpeg, received, reason,
                                                self.names.get(det.camera_id),
                                                self.aspects.get(det.camera_id))  # fmt: skip
                self.stats[f"saved_{reason}"] += 1
                log.debug("tersimpan %s (%s, %d box)", saved.image.name, reason, saved.boxes)
            except DiskFull as e:
                if not self.disk_full:
                    log.warning("perekaman berhenti: %s", e)
                self.disk_full = True
                self.stats["skip_disk"] += 1
            except AuthError:
                self.stats["error_auth"] += 1
                self._reauth = True  # loop koneksi menutup /ws lalu login ulang
            except (ApiError, OSError) as e:
                self.stats["error_snapshot"] += 1
                log.warning("snapshot kamera %s gagal: %s", det.camera_id, e)

    # --- koneksi ------------------------------------------------------------
    async def _prepare(self) -> list[int]:
        if not self.client.session:
            await asyncio.to_thread(self.client.login)
            log.info("login SysGuard berhasil sebagai %s", self.cfg.username)
        cams = await asyncio.to_thread(self.client.cameras)
        if self.cfg.camera_ids:
            chosen = [c for c in cams if c["id"] in self.cfg.camera_ids]
            missing = set(self.cfg.camera_ids) - {c["id"] for c in chosen}
            if missing:
                log.warning("kamera tidak ditemukan: %s", sorted(missing))
        else:
            chosen = [c for c in cams if c["enabled"]]
        self.names = {c["id"]: c["name"] for c in chosen}
        self.aspects = {c["id"]: self._aspect(c) for c in chosen}
        return sorted(self.names)

    def _aspect(self, cam: dict) -> tuple[int, int] | None:
        if self.cfg.aspect == "off":
            return None
        if self.cfg.aspect == "auto":
            return parse_aspect(cam.get("resolution") or "")
        return parse_aspect(self.cfg.aspect)

    async def run_once(self, stop: asyncio.Event) -> None:
        ids = await self._prepare()
        if not ids:
            raise ApiError("tidak ada kamera untuk direkam (cek CAPTURE_CAMERAS / kamera aktif)")
        async with self.client.open_ws() as ws:
            await subscribe(ws, ids)
            log.info("merekam kamera %s ke %s", ids, self.cfg.out_dir)
            while not stop.is_set():
                if self._reauth:
                    self._reauth = False
                    raise AuthError("sesi berakhir saat mengambil snapshot")
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except TimeoutError:
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    await self.handle(msg)

    async def run(self, stop: asyncio.Event) -> None:
        backoff = BACKOFF_MIN
        reporter = asyncio.create_task(self._report(stop))
        try:
            while not stop.is_set():
                started = self.clock()
                try:
                    await self.run_once(stop)
                except AuthError as e:
                    self.client.session = None
                    log.warning("autentikasi: %s", e)
                except ConnectionClosed as e:
                    code = e.rcvd.code if e.rcvd else None
                    if code in (CLOSE_SESSION_ENDED, CLOSE_POLICY):
                        self.client.session = None
                    log.warning("koneksi /ws tertutup (kode %s)", code)
                except InvalidStatus as e:
                    if e.response.status_code in (401, 403):
                        self.client.session = None
                    log.warning("/ws ditolak: HTTP %s", e.response.status_code)
                except (ApiError, OSError, TimeoutError) as e:
                    log.warning("SysGuard tidak bisa dihubungi: %s", e)
                if stop.is_set():
                    break
                if self.clock() - started > BACKOFF_MAX:
                    backoff = BACKOFF_MIN  # sempat berjalan lama: mulai lagi dari jeda pendek
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except TimeoutError:
                    pass
                backoff = min(BACKOFF_MAX, backoff * 2)
        finally:
            reporter.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _report(self, stop: asyncio.Event) -> None:
        """Ringkasan berkala ke log dan status.json (untuk health check jarak jauh)."""
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.cfg.stats_interval_s)
            except TimeoutError:
                pass
            try:
                self._write_status()
            except OSError as e:  # mis. flashdisk dicabut tanpa `lfc usb lepas`
                log.warning("status.json tidak bisa ditulis: %s", e)

    def _write_status(self) -> None:
        # Berhenti karena disk penuh / flashdisk lepas: lanjut sendiri setelah masalahnya hilang.
        # Jeda 2% sebelum lanjut supaya tidak bolak-balik berhenti-jalan tepat di batas disk.
        problem = self.writer.storage_problem(margin_pct=2.0 if self.disk_full else 0.0)
        if self.disk_full and problem is None:
            self.disk_full = False
            log.info("penyimpanan siap lagi, perekaman dilanjutkan")
        elif problem and not self.disk_full:
            self.disk_full = True
            log.warning("perekaman berhenti: %s", problem)
        status = {"time": datetime.now(UTC).isoformat(timespec="seconds"),
                  "connected": self.client.session is not None, "site": self.cfg.site,
                  "cameras": sorted(self.names), "disk": self.writer.disk_status(),
                  "disk_full": self.disk_full, "storage_problem": problem,
                  "counts": dict(self.stats)}  # fmt: skip
        log.info("status %s", json.dumps(status["counts"], sort_keys=True))
        # Tanpa flashdisk, status ditulis ke folder titik mount di memori internal (kecil, dan
        # tertutup lagi saat flashdisk dipasang) supaya `lfc status` tetap menampilkan masalahnya.
        self.cfg.root_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.cfg.root_dir / "status.json.tmp"
        tmp.write_text(json.dumps(status, indent=2), encoding="utf-8")
        tmp.replace(self.cfg.root_dir / "status.json")
