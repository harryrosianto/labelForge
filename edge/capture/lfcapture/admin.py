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
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lfcapture.config import DEFAULT_SITE, SITE_RE, check_site, check_usb_uuid, lfcapture_home

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
    usb_uuid: str | None = None  # CAPTURE_USB_UUID: CAPTURE_DIR adalah titik mount flashdisk

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
    return Paths(lfcapture_home(env), Path(root), site, check_usb_uuid(env.get("CAPTURE_USB_UUID", "")))


# --- ringkasan data -----------------------------------------------------------
def site_dirs(root: Path) -> list[Path]:
    """Folder site di CAPTURE_DIR. Folder lain (mis. "System Volume Information" buatan Windows
    di flashdisk) diabaikan."""
    if not root.is_dir():
        return []
    return sorted(x for x in root.iterdir() if x.is_dir() and SITE_RE.match(x.name))


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
    if p.usb_uuid:
        state = "terpasang" if os.path.ismount(p.root) else (
            "TIDAK terpasang (tercolok, jalankan: lfc usb pasang)" if usb_device(p.usb_uuid).exists()
            else "TIDAK terpasang (tidak tercolok)")
        print(f"flashdisk : {p.usb_uuid} {state}")
    try:
        lan = lan_summary(p.home)
    except (OSError, ValueError) as e:
        lan = f"pengaturan lan.env tidak terbaca ({e})"
    if lan:
        print(f"LAN       : {lan}")

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
        if disk.get("used_pct") is not None:
            print(f"disk      : {disk.get('used_pct')}% terpakai, sisa {human((disk.get('free_mb') or 0) * 2**20)}")
        if st.get("disk_full"):
            print(f"PERHATIAN : perekaman BERHENTI, {st.get('storage_problem') or 'disk penuh'}")
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
    if not p.usb_uuid or os.path.ismount(p.root):  # tanpa flashdisk: jangan isi memori internal
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
    for site_dir in site_dirs(p.root):
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


# --- tarik dataset (dipakai deploy/tarik-dataset.ps1 lewat SSH) ------------------------------
def complete_stems(day_dir: Path) -> dict[str, int]:
    """Frame lengkap (gambar + label) di satu folder harian -> ukuran gambar+label (byte).

    Gambar ditulis setelah labelnya (lihat writer), jadi frame yang sedang ditulis belum ikut.
    """
    images, labels = day_dir / "images", day_dir / "labels"
    out = {}
    for img in images.glob("*.jpg") if images.is_dir() else []:
        label = labels / f"{img.stem}.txt"
        if label.exists():
            out[img.stem] = img.stat().st_size + label.stat().st_size
    return out


def cmd_inventory(p: Paths, out=None) -> int:
    """Satu baris JSON per folder harian: site, day, frames, bytes."""
    out = out or sys.stdout
    for site_dir in site_dirs(p.root):
        for _, day in day_folders(site_dir):
            stems = complete_stems(day)
            out.write(json.dumps({"site": site_dir.name, "day": day.name, "frames": len(stems),
                                  "bytes": sum(stems.values())}) + "\n")  # fmt: skip
    return 0


def parse_export_request(lines, root: Path) -> dict[tuple[str, str], set[str]]:
    """Baris 'DAY <site> <folder>' dan 'HAVE <site> <folder> <stem>' -> {(site, folder): stem yang sudah ada}.

    Nama site & folder divalidasi supaya permintaan tidak bisa keluar dari CAPTURE_DIR.
    """
    want: dict[tuple[str, str], set[str]] = {}
    for raw in lines:
        parts = raw.strip().split()
        if not parts:
            continue
        if parts[0] not in ("DAY", "HAVE") or len(parts) != (3 if parts[0] == "DAY" else 4):
            raise ValueError(f"baris permintaan tidak dikenal: {raw.strip()[:80]!r}")
        site, folder = check_site(parts[1]), parts[2]
        if not DAY_RE.match(folder) or not _inside(root, root / site / folder):
            raise ValueError(f"folder harian tidak valid: {folder!r}")
        have = want.setdefault((site, folder), set())
        if parts[0] == "HAVE":
            have.add(parts[3])
    return want


def cmd_export(p: Paths, request, out) -> int:
    """Tulis tar (stream) berisi frame lengkap yang belum dimiliki peminta, plus data.yaml & meta.

    Path di dalam tar: <site>/<folder>/..., jadi bisa dibuka langsung di folder tujuan laptop.
    """
    import tarfile

    want = parse_export_request(request, p.root)
    with tarfile.open(fileobj=out, mode="w|") as tar:
        for (site, folder), have in sorted(want.items()):
            day = p.root / site / folder
            if not day.is_dir():
                continue
            base = f"{site}/{folder}"
            extras = [day / "data.yaml", *sorted((day / "meta").glob("*.jsonl"))]
            for f in extras:
                if f.exists():
                    tar.add(f, arcname=f"{base}/{f.relative_to(day).as_posix()}")
            for stem in sorted(set(complete_stems(day)) - have):
                tar.add(day / "labels" / f"{stem}.txt", arcname=f"{base}/labels/{stem}.txt")
                tar.add(day / "images" / f"{stem}.jpg", arcname=f"{base}/images/{stem}.jpg")
    return 0


# --- flashdisk (CAPTURE_USB_UUID) ------------------------------------------------------------
# /etc di perangkat read-only (tanpa fstab/unit sistem), jadi mount dilakukan lewat `sudo -n`
# oleh `lfc usb pasang`, yang juga dijalankan saat boot oleh deploy/lfcapture-usb.service.
USB_FS = ("vfat", "exfat")  # bisa langsung dibaca laptop Windows
STATUS_FILES = {"status.json", "status.json.tmp"}


def usb_device(uuid: str) -> Path:
    return Path("/dev/disk/by-uuid") / uuid


def sudo(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["sudo", "-n", *args], capture_output=True, text=True, timeout=60)


def usb_fstype(dev: Path) -> str:
    try:
        return subprocess.run(["lsblk", "-no", "FSTYPE", str(dev)], capture_output=True,
                              text=True, timeout=10).stdout.strip()  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return ""


def usb_mount_options(fstype: str) -> str:
    uid = os.getuid() if hasattr(os, "getuid") else 0
    gid = os.getgid() if hasattr(os, "getgid") else 0
    # FAT tanpa izin per file: semua milik user perekam, tertutup untuk user lain. `flush`
    # menulis ke flashdisk lebih cepat sehingga lebih sedikit data hilang bila listrik padam.
    opts = f"rw,noatime,nosuid,nodev,noexec,uid={uid},gid={gid},fmask=0177,dmask=0077"
    return opts + (",flush" if fstype == "vfat" else "")


def _need_usb(p: Paths) -> str:
    if not p.usb_uuid:
        raise SystemExit("CAPTURE_USB_UUID belum diisi di capture.env (lihat README, bagian Flashdisk)")
    return p.usb_uuid


def cmd_usb_status(p: Paths, fstype: Callable[[Path], str] = usb_fstype) -> int:
    uuid = _need_usb(p)
    dev = usb_device(uuid)
    mounted = os.path.ismount(p.root)
    print(f"flashdisk : {uuid}  {'tercolok' if dev.exists() else 'TIDAK tercolok'}"
          f"{f' ({fstype(dev)})' if dev.exists() else ''}")  # fmt: skip
    print(f"mount     : {p.root}  {'terpasang' if mounted else 'TIDAK terpasang'}")
    if mounted:
        usage = shutil.disk_usage(p.root)
        print(f"isi       : {human(usage.total - usage.free)} terpakai dari {human(usage.total)}, "
              f"sisa {human(usage.free)}")  # fmt: skip
    elif dev.exists():
        print("pasang dengan: lfc usb pasang")
    return 0 if mounted else 1


def cmd_usb_pasang(p: Paths, start: bool = True, wait_s: float = 0,
                   run_sudo: Callable[..., subprocess.CompletedProcess] = sudo,
                   run: Systemctl = systemctl, fstype: Callable[[Path], str] = usb_fstype,
                   sleep: Callable[[float], None] = time.sleep) -> int:  # fmt: skip
    uuid = _need_usb(p)
    if os.path.ismount(p.root):
        print(f"flashdisk sudah terpasang di {p.root}")
    else:
        dev = usb_device(uuid)
        waited = 0.0
        while not dev.exists() and waited < wait_s:  # saat boot USB bisa terdeteksi belakangan
            sleep(1)
            waited += 1
        if not dev.exists():
            print(f"flashdisk {uuid} tidak tercolok; perekam tidak menyimpan sampai dipasang")
            return 1
        fs = fstype(dev)
        if fs not in USB_FS:
            print(f"format flashdisk {fs or '?'} tidak didukung; format ulang sebagai FAT32/exFAT di laptop")
            return 1
        p.root.mkdir(parents=True, exist_ok=True)
        hidden = [x.name for x in p.root.iterdir() if x.name not in STATUS_FILES]
        if hidden:
            print(f"PERHATIAN: {p.root} di memori internal berisi {', '.join(sorted(hidden)[:5])}; "
                  "isinya tertutup selama flashdisk terpasang")  # fmt: skip
        r = run_sudo("mount", "-t", fs, "-o", usb_mount_options(fs), str(dev), str(p.root))
        if r.returncode != 0:
            print(f"mount gagal: {(r.stderr or r.stdout).strip()}", file=sys.stderr)
            return 1
        print(f"flashdisk {uuid} terpasang di {p.root}")
    if start and run("is-active", SERVICE).stdout.strip() != "active":
        return cmd_service("start", run)
    return 0


def cmd_usb_lepas(p: Paths, run_sudo: Callable[..., subprocess.CompletedProcess] = sudo,
                  run: Systemctl = systemctl) -> int:
    _need_usb(p)
    if not os.path.ismount(p.root):
        print(f"flashdisk tidak terpasang di {p.root}; aman dicabut")
        return 0
    was_active = run("is-active", SERVICE).stdout.strip() == "active"
    if was_active:
        cmd_service("stop", run)
    if hasattr(os, "sync"):
        os.sync()
    r = run_sudo("umount", str(p.root))
    if r.returncode != 0:
        print(f"umount gagal: {(r.stderr or r.stdout).strip()}\n"
              f"Pastikan tidak ada terminal yang sedang berada di {p.root} (cd ~), lalu ulangi.",
              file=sys.stderr)  # fmt: skip
        return 1
    print(f"flashdisk AMAN DICABUT.{' Perekam dihentikan.' if was_active else ''}\n"
          "Setelah dicolok lagi: lfc usb pasang  (perekam ikut dimulai)")
    return 0


# --- IP port LAN (lan.env) -------------------------------------------------------------------
# Firmware memasang alamat recovery 192.168.100.1/24 di eth0 dan tidak mengizinkan alamat lain
# di subnet itu (aturan R57). Di site yang jaringan CCTV-nya juga 192.168.100.0/24 dan .1 sudah
# dipakai (biasanya gateway), alamat itu bentrok. `lfc lan terapkan` (dijalankan saat boot dan
# tiap menit oleh deploy/lfcapture-lan.timer) melepas alamat itu dan memasang alamat dari IT.
# Ini tambalan per site sampai firmware bisa memindah recovery subnet.
LAN_ENV = "lan.env"
IFACE_RE = re.compile(r"^[a-z0-9]{1,15}$")


@dataclass
class LanConfig:
    iface: str
    addr: str  # alamat yang dipasang, mis. 192.168.100.245/24
    drop: str  # alamat yang dilepas, mis. 192.168.100.1/24


def load_lan(home: Path) -> LanConfig | None:
    import ipaddress

    from lfcapture.config import ConfigError, read_env_file

    path = home / LAN_ENV
    if not path.exists():
        return None
    env = read_env_file(path)
    iface = env.get("LAN_IFACE", "eth0").strip()
    if not IFACE_RE.match(iface):
        raise ConfigError(f"LAN_IFACE {iface!r} tidak valid")
    out = {}
    for key, default in (("LAN_ADDR", ""), ("LAN_DROP", "192.168.100.1/24")):
        raw = env.get(key, default).strip()
        try:
            if "/" not in raw:
                raise ValueError
            out[key] = str(ipaddress.IPv4Interface(raw))
        except ValueError:
            raise ConfigError(f"{key} di {path} harus alamat IPv4 dengan prefix, mis. 192.168.100.245/24") from None
    if out["LAN_ADDR"] == out["LAN_DROP"]:
        raise ConfigError("LAN_ADDR dan LAN_DROP tidak boleh sama")
    return LanConfig(iface, out["LAN_ADDR"], out["LAN_DROP"])


def iface_addrs(iface: str) -> list[str]:
    """Alamat IPv4 di interface, mis. ['192.168.100.245/24']."""
    r = subprocess.run(["ip", "-j", "-4", "addr", "show", "dev", iface], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or f"interface {iface} tidak ada")
    return [f"{a['local']}/{a['prefixlen']}" for link in json.loads(r.stdout or "[]") for a in link.get("addr_info", [])]


def link_up(iface: str) -> bool:
    try:
        return Path(f"/sys/class/net/{iface}/carrier").read_text().strip() == "1"
    except OSError:  # interface turun: membaca carrier gagal dengan EINVAL
        return False


def arp_probe(iface: str, addr: str) -> str | None:
    """MAC perangkat lain yang memakai `addr` (tanpa prefix), None bila bebas."""
    script = Path(__file__).with_name("arpprobe.py")
    r = sudo(sys.executable, "-I", str(script), iface, addr, "3")
    out = (r.stdout or "").strip()
    if r.returncode == 0 and out == "BEBAS":
        return None
    if r.returncode == 1 and out.startswith("DIPAKAI"):
        return out.split()[-1]
    raise OSError(f"ARP probe gagal: {(r.stderr or out).strip()}")


def cmd_lan_terapkan(home: Path, run_sudo: Callable[..., subprocess.CompletedProcess] = sudo,
                     addrs: Callable[[str], list[str]] = iface_addrs,
                     is_up: Callable[[str], bool] = link_up,
                     probe: Callable[[str, str], str | None] = arp_probe) -> int:  # fmt: skip
    cfg = load_lan(home)
    if cfg is None:
        return 0  # site tanpa lan.env: tidak ada yang diubah
    current = addrs(cfg.iface)
    rc = 0
    if cfg.drop in current:
        r = run_sudo("ip", "addr", "del", cfg.drop, "dev", cfg.iface)
        if r.returncode != 0:
            print(f"gagal melepas {cfg.drop} dari {cfg.iface}: {(r.stderr or r.stdout).strip()}", file=sys.stderr)
            rc = 1
        else:
            print(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S} {cfg.drop} dilepas dari {cfg.iface}")
    if cfg.addr in current:
        return rc
    if not is_up(cfg.iface):
        # Tanpa kabel tidak bisa dicek bentrok; dipasang setelah kabel tercolok (timer tiap menit).
        return rc
    ip = cfg.addr.split("/")[0]
    used_by = probe(cfg.iface, ip)
    if used_by:
        print(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S} PERINGATAN: {ip} sudah dipakai perangkat {used_by}; tidak dipasang. "
              f"Minta IP lain ke IT lalu ubah LAN_ADDR di {home / LAN_ENV}", file=sys.stderr)  # fmt: skip
        return 1
    r = run_sudo("ip", "addr", "add", cfg.addr, "dev", cfg.iface)
    if r.returncode != 0:
        print(f"gagal memasang {cfg.addr} di {cfg.iface}: {(r.stderr or r.stdout).strip()}", file=sys.stderr)
        return 1
    print(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S} {cfg.addr} dipasang di {cfg.iface}")
    return rc


def lan_summary(home: Path, addrs: Callable[[str], list[str]] = iface_addrs,
                is_up: Callable[[str], bool] = link_up) -> str | None:  # fmt: skip
    cfg = load_lan(home)
    if cfg is None:
        return None
    try:
        current = addrs(cfg.iface)
    except OSError as e:
        return f"{cfg.iface} tidak terbaca ({e})"
    state = "OK" if cfg.addr in current and cfg.drop not in current else "BELUM SESUAI"
    if cfg.drop in current:
        state += f", {cfg.drop} masih terpasang"
    if cfg.addr not in current:
        state += f", {cfg.addr} belum dipasang" + ("" if is_up(cfg.iface) else " (kabel tidak tercolok)")
    return f"{cfg.iface} {cfg.addr} [{state}]"


def cmd_lan_status(home: Path) -> int:
    cfg = load_lan(home)
    if cfg is None:
        print(f"tidak dipakai (tidak ada {home / LAN_ENV})")
        return 0
    print(f"pengaturan: {cfg.iface} pasang {cfg.addr}, lepas {cfg.drop}")
    print(f"link      : {'tercolok' if link_up(cfg.iface) else 'tidak tercolok'}")
    print(f"alamat    : {', '.join(iface_addrs(cfg.iface)) or '-'}")
    summary = lan_summary(home) or ""
    print(f"status    : {summary.split('[', 1)[-1].rstrip(']')}")
    return 0 if summary.endswith("[OK]") else 1


# --- akses jarak jauh (Tailscale userspace, lihat deploy/install-tailscale.sh) -----------------
def tailscale_home() -> Path:
    return Path(os.environ.get("TAILSCALE_HOME") or Path.home() / "tailscale")


def _tailscale(*args: str) -> subprocess.CompletedProcess:
    ts = tailscale_home()
    return subprocess.run([str(ts / "bin" / "tailscale"), f"--socket={ts / 'tailscaled.sock'}", *args],
                          capture_output=True, text=True, timeout=60)  # fmt: skip


def _too_open(path: Path) -> bool:
    return os.name != "nt" and bool(path.stat().st_mode & 0o077)


def cmd_vpn_status(run_ts: Callable[..., subprocess.CompletedProcess] = _tailscale,
                   run: Systemctl = systemctl) -> int:
    try:
        svc = run("is-active", "tailscaled.service").stdout.strip() or "?"
    except OSError:
        svc = "?"
    print(f"tailscaled: {svc}")
    try:
        r = run_ts("status", "--json")
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"tailscale tidak bisa dijalankan: {e}")
        return 1
    if r.returncode != 0 or not r.stdout.strip().startswith("{"):
        print((r.stdout + r.stderr).strip() or "status tidak tersedia")
        return 1
    st = json.loads(r.stdout)
    me = st.get("Self") or {}
    print(f"status    : {st.get('BackendState')}")
    if st.get("BackendState") == "NeedsLogin":
        print("belum terdaftar: simpan auth key di ~/tailscale/authkey lalu jalankan: lfc vpn up")
        return 1
    ips = ", ".join(me.get("TailscaleIPs") or [])
    print(f"perangkat : {me.get('HostName')}  {ips}")
    print(f"tailnet   : {(st.get('CurrentTailnet') or {}).get('Name', '?')}")
    peers = (st.get("Peer") or {}).values()
    online = [p for p in peers if p.get("Online")]
    print(f"peer      : {len(online)} online dari {len(list((st.get('Peer') or {}).values()))}")
    if me.get("KeyExpiry"):
        print(f"kunci kedaluwarsa: {me['KeyExpiry']}  (matikan expiry perangkat ini di konsol admin)")
    return 0 if st.get("BackendState") == "Running" else 1


def cmd_vpn_up(hostname: str, tags: str | None,
               run_ts: Callable[..., subprocess.CompletedProcess] = _tailscale,
               run: Systemctl = systemctl) -> int:
    """Daftarkan perangkat memakai auth key di ~/tailscale/authkey, lalu hapus file kuncinya."""
    key = tailscale_home() / "authkey"
    if not key.exists():
        print(f"belum ada {key}. Simpan auth key dari konsol admin Tailscale ke file itu "
              "(chmod 600), lalu jalankan lagi.")  # fmt: skip
        return 1
    if _too_open(key):
        print(f"{key} harus chmod 600")
        return 1
    args = ["up", f"--auth-key=file:{key}", f"--hostname={hostname}"]
    if tags:
        args.append(f"--advertise-tags={tags}")
    r = run_ts(*args)
    print((r.stdout + r.stderr).strip())
    if r.returncode != 0:
        return 1
    key.unlink()  # kunci hanya untuk pendaftaran; jangan tertinggal di perangkat
    print("terdaftar; file auth key dihapus")
    return cmd_vpn_status(run_ts, run)


def cmd_log(p: Paths, lines: int, follow: bool) -> int:
    if not p.log_file.exists():
        print(f"belum ada log di {p.log_file}")
        return 1
    args = ["tail", "-n", str(lines)] + (["-F"] if follow else []) + [str(p.log_file)]
    try:
        return subprocess.call(args)
    except KeyboardInterrupt:
        return 0
