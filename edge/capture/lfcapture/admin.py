"""Perintah pengelolaan perekam lewat SSH (`lfc ...`): status, start/stop, site, log, clean, reset.

Perintah ini tidak butuh password akun SysGuard: hanya membaca CAPTURE_DIR/CAPTURE_SITE dari
file env, status.json dan meta yang ditulis perekam, serta mengendalikan service user systemd.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lfcapture.config import DEFAULT_SITE, check_site, lfcapture_home

SERVICE = "lfcapture.service"
DAY_RE = re.compile(r"^(?P<prefix>.+)-(?P<day>\d{8})$")
STATUS_STALE_S = 180  # status.json ditulis tiap 60 detik; lebih tua dari ini = perekam macet

Systemctl = Callable[..., subprocess.CompletedProcess]


def systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


@dataclass
class Paths:
    home: Path  # ~/lfcapture
    root: Path  # CAPTURE_DIR
    site: str

    @property
    def site_dir(self) -> Path:
        return self.root / self.site

    @property
    def site_env(self) -> Path:
        return self.home / "site.env"

    @property
    def log_file(self) -> Path:
        return self.home / "logs" / "lfcapture.log"


def load_paths(env: Mapping[str, str]) -> Paths:
    root = env.get("CAPTURE_DIR", "").strip()
    if not root:
        raise SystemExit("CAPTURE_DIR belum diisi di capture.env")
    site = check_site(env.get("CAPTURE_SITE", "").strip() or DEFAULT_SITE)
    return Paths(lfcapture_home(env), Path(root), site)


# --- ringkasan data -----------------------------------------------------------
def day_folders(site_dir: Path) -> list[tuple[date, Path]]:
    out = []
    for p in site_dir.iterdir() if site_dir.is_dir() else []:
        m = DAY_RE.match(p.name)
        if p.is_dir() and m:
            try:
                out.append((datetime.strptime(m["day"], "%Y%m%d").date(), p))
            except ValueError:
                continue
    return sorted(out)


def folder_size(path: Path) -> tuple[int, int]:
    """(jumlah gambar, total byte)."""
    images = size = 0
    for p in path.rglob("*"):
        if p.is_file():
            size += p.stat().st_size
            images += p.suffix == ".jpg" and p.parent.name == "images"
    return images, size


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def today_meta(site_dir: Path, today: date) -> tuple[Counter, float | None]:
    """Jumlah frame hari ini per alasan dan waktu frame terakhir, dari meta/*.jsonl."""
    reasons: Counter = Counter()
    last = None
    for _, day in day_folders(site_dir):
        meta = day / "meta" / f"{today:%Y%m%d}.jsonl"
        if not meta.exists():
            continue
        for line in meta.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            reasons[row.get("reason", "?")] += 1
            last = max(last or 0.0, float(row.get("snap_ts") or 0))
    return reasons, last


def ago(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds} detik lalu"
    if seconds < 5400:
        return f"{seconds // 60} menit lalu"
    return f"{seconds // 3600} jam lalu"


# --- perintah -----------------------------------------------------------------
def cmd_status(p: Paths, run: Systemctl = systemctl, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    props = dict(line.split("=", 1) for line in run(
        "show", SERVICE, "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts",
        "-p", "UnitFileState", "-p", "ActiveEnterTimestamp").stdout.splitlines() if "=" in line)  # fmt: skip
    active = props.get("ActiveState") == "active"
    state = "BERJALAN" if active else f"BERHENTI ({props.get('ActiveState', '?')})"
    since = f", sejak {props['ActiveEnterTimestamp']}" if active and props.get("ActiveEnterTimestamp") else ""
    restarts = f", restart {props['NRestarts']}x" if props.get("NRestarts", "0") not in ("", "0") else ""
    print(f"perekam   : {state}{since}{restarts}")
    print(f"autostart : {'on' if props.get('UnitFileState') == 'enabled' else 'off'}"
          f" (linger: {linger_state()})")  # fmt: skip
    print(f"site      : {p.site}  ({p.site_dir})")

    status_file = p.root / "status.json"
    if status_file.exists():
        st = json.loads(status_file.read_text(encoding="utf-8"))
        age = (now - datetime.fromisoformat(st["time"])).total_seconds()
        conn = "terhubung" if st.get("connected") else "TIDAK terhubung"
        stale = "" if age < STATUS_STALE_S or not active else "  (status lama: perekam macet?)"
        print(f"SysGuard  : {conn}, kamera {st.get('cameras')}, diperbarui {ago(age)}{stale}")
        if st.get("site") not in (None, p.site) and active:
            print(f"            perekam masih memakai site {st['site']!r}; jalankan: lfc start")
        disk = st.get("disk") or {}
        full = "  PENUH, perekaman berhenti" if st.get("disk_full") else ""
        print(f"disk      : {disk.get('used_pct')}% terpakai, sisa {human((disk.get('free_mb') or 0) * 2**20)}{full}")
    else:
        print("SysGuard  : belum ada status.json (perekam belum pernah berjalan)")

    reasons, last = today_meta(p.site_dir, now.date())
    detail = ", ".join(f"{k} {v}" for k, v in reasons.most_common())
    print(f"hari ini  : {sum(reasons.values())} frame{f' ({detail})' if detail else ''}  [tanggal UTC]")
    if last:
        stamp = datetime.fromtimestamp(last, UTC)
        print(f"terakhir  : {stamp:%Y-%m-%d %H:%M:%S} UTC ({ago((now - stamp).total_seconds())})")
    return 0 if active else 3


def linger_state() -> str:
    try:
        out = subprocess.run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger",
                              "--value"], capture_output=True, text=True).stdout.strip()  # fmt: skip
    except OSError:
        return "?"
    return out or "?"


def cmd_service(action: str, run: Systemctl = systemctl) -> int:
    r = run(action, SERVICE)
    if r.returncode != 0:
        print(r.stderr.strip() or f"systemctl {action} gagal", file=sys.stderr)
        return 1
    print({"start": "perekam dimulai", "stop": "perekam dihentikan",
           "restart": "perekam dimulai ulang"}[action])  # fmt: skip
    return 0


def cmd_autostart(on: bool, run: Systemctl = systemctl) -> int:
    r = run("enable" if on else "disable", SERVICE)
    if r.returncode != 0:
        print(r.stderr.strip(), file=sys.stderr)
        return 1
    print(f"autostart {'on' if on else 'off'}")
    if on and linger_state() != "yes":
        print("PERHATIAN: linger belum aktif, service tidak jalan saat boot tanpa login.\n"
              f"Aktifkan sekali: sudo loginctl enable-linger {os.environ.get('USER', '<user>')}")  # fmt: skip
    return 0


def cmd_site(p: Paths, new: str | None, run: Systemctl = systemctl) -> int:
    if new is None:
        print(p.site)
        return 0
    check_site(new)
    old = os.umask(0o077)
    try:
        p.home.mkdir(parents=True, exist_ok=True)
        p.site_env.write_text(f"CAPTURE_SITE={new}\n", encoding="utf-8")
    finally:
        os.umask(old)
    (p.root / new).mkdir(parents=True, exist_ok=True)
    print(f"site aktif: {new}  ({p.root / new})")
    if run("is-active", SERVICE).stdout.strip() == "active":
        return cmd_service("restart", run)
    print("perekam tidak berjalan; mulai dengan: lfc start")
    return 0


def cmd_sites(p: Paths) -> int:
    if not p.root.is_dir():
        print("belum ada data")
        return 0
    rows = []
    for site_dir in sorted(x for x in p.root.iterdir() if x.is_dir()):
        days = day_folders(site_dir)
        images, size = folder_size(site_dir)
        span = f"{days[0][0]:%Y-%m-%d} s/d {days[-1][0]:%Y-%m-%d}" if days else "-"
        mark = "*" if site_dir.name == p.site else " "
        rows.append(f"{mark} {site_dir.name:<28} {len(days):>4} hari {images:>7} frame {human(size):>9}   {span}")
    print("  site                          hari     frame    ukuran   rentang")
    print("\n".join(rows) if rows else "  (kosong)")
    print("* = site aktif")
    return 0


def _confirm(prompt: str, expected: str, given: str | None) -> bool:
    if given is not None:
        return given == expected
    if not sys.stdin.isatty():
        print("butuh konfirmasi interaktif (ssh -t), atau sertakan --konfirmasi", file=sys.stderr)
        return False
    try:
        return input(prompt).strip() == expected
    except EOFError:
        return False


def _inside(root: Path, target: Path) -> bool:
    root, target = root.resolve(), target.resolve()
    return target != root and root in target.parents


def old_days(days: list[tuple[date, Path]], today: date, older_than: int) -> list[Path]:
    """Folder harian yang lebih tua dari `older_than` hari. Folder hari ini tidak pernah ikut."""
    limit = today - timedelta(days=older_than)
    return [path for day, path in days if day < limit and day < today]


def cmd_clean(p: Paths, site: str, older_than: int, given: str | None,
              today: date | None = None) -> int:
    check_site(site)
    if older_than < 1:
        raise SystemExit("--older-than minimal 1 hari")
    site_dir = p.root / site
    targets = old_days(day_folders(site_dir), today or datetime.now(UTC).date(), older_than)
    if not targets:
        print(f"tidak ada folder lebih tua dari {older_than} hari di site {site}")
        return 0
    total = 0
    for t in targets:
        n, size = folder_size(t)
        total += size
        print(f"  {t.name}  {n} frame  {human(size)}")
    print(f"total {len(targets)} folder, {human(total)}. Pastikan sudah ditarik ke laptop.")
    if not _confirm("ketik 'hapus' untuk menghapus: ", "hapus", given):
        print("dibatalkan")
        return 1
    for t in targets:
        if _inside(p.root, t):
            shutil.rmtree(t)
    print(f"{len(targets)} folder dihapus")
    return 0


def cmd_reset(p: Paths, site: str, given: str | None, run: Systemctl = systemctl) -> int:
    check_site(site)
    site_dir = p.root / site
    if not site_dir.is_dir():
        print(f"site {site} tidak ada")
        return 1
    if site == p.site and run("is-active", SERVICE).stdout.strip() == "active":
        print(f"site {site} sedang direkam. Hentikan dulu (lfc stop) atau pindah site (lfc site <lain>).")
        return 1
    n, size = folder_size(site_dir)
    print(f"AKAN MENGHAPUS SELURUH site {site}: {len(day_folders(site_dir))} hari, {n} frame, {human(size)}")
    if not _confirm(f"ketik nama site ({site}) untuk konfirmasi: ", site, given):
        print("dibatalkan")
        return 1
    if not _inside(p.root, site_dir):
        raise SystemExit("lokasi site di luar CAPTURE_DIR, dibatalkan")
    shutil.rmtree(site_dir)
    print(f"site {site} dihapus")
    return 0


def cmd_log(p: Paths, lines: int, follow: bool) -> int:
    if not p.log_file.exists():
        print(f"belum ada log di {p.log_file}")
        return 1
    args = ["tail", "-n", str(lines)] + (["-F"] if follow else []) + [str(p.log_file)]
    try:
        return subprocess.call(args)
    except KeyboardInterrupt:
        return 0
