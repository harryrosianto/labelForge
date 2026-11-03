"""Konfigurasi dari environment (systemd EnvironmentFile) atau file .env."""

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_CLASSES = ("person", "Helmet", "Mask", "Safety Vest", "boots", "glove")
DEFAULT_SITE = "umum"
SITE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
# Folder kerja di perangkat; `lfc` dan service membaca capture.env lalu site.env dari sini.
HOME_ENV = "LFCAPTURE_HOME"
ENV_FILES = ("capture.env", "site.env")


class ConfigError(ValueError):
    """Konfigurasi tidak lengkap atau tidak valid (pesan aman ditampilkan)."""


def check_site(name: str) -> str:
    if not SITE_RE.match(name):
        raise ConfigError(f"Nama site {name!r} tidak valid: huruf kecil, angka, dan '-' "
                          "(maks 40 karakter), diawali huruf/angka")  # fmt: skip
    return name


def lfcapture_home(env: Mapping[str, str] | None = None) -> Path:
    e = os.environ if env is None else env
    return Path(e.get(HOME_ENV) or Path.home() / "lfcapture")


def default_env_files(env: Mapping[str, str] | None = None) -> list[Path]:
    home = lfcapture_home(env)
    return [home / name for name in ENV_FILES if (home / name).exists()]


@dataclass(frozen=True)
class Config:
    sg_url: str
    username: str
    password: str = field(repr=False)
    out_dir: Path  # folder site aktif: <root_dir>/<site>
    root_dir: Path  # CAPTURE_DIR; status.json ada di sini
    site: str = DEFAULT_SITE
    prefix: str = "ppe"
    camera_ids: tuple[int, ...] = ()  # kosong = semua kamera yang aktif
    classes: tuple[str, ...] = DEFAULT_CLASSES
    person_class: str | None = "person"  # box orang dari tracks; None = tidak disimpan
    ca_file: str | None = None
    insecure_tls: bool = False
    # Aturan pemilihan frame (detik / skor)
    interval_s: float = 10.0
    uncertain_low: float = 0.25
    uncertain_high: float = 0.6
    uncertain_cooldown_s: float = 3.0
    violation_cooldown_s: float = 5.0
    empty_interval_s: float = 300.0
    min_gap_s: float = 1.0
    dedup_iou: float = 0.85
    max_per_hour: int = 360
    # Penjaga disk
    disk_max_used_pct: float = 85.0
    disk_min_free_mb: int = 1024
    max_snapshot_lag_s: float = 1.0
    stats_interval_s: float = 60.0


def read_env_file(path: str | Path) -> dict[str, str]:
    """Format KEY=VALUE per baris; '#' komentar; tanda kutip di sekeliling nilai dibuang."""
    values: dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _is_loopback(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config(env: Mapping[str, str] | None = None) -> Config:
    e = dict(os.environ if env is None else env)

    def num(key: str, default: float, cast=float):
        raw = e.get(key, "")
        try:
            return cast(raw) if raw.strip() else default
        except ValueError:
            raise ConfigError(f"{key} harus berupa angka, bukan {raw!r}") from None

    url = e.get("SG_URL", "https://127.0.0.1:8080").rstrip("/")
    if urlsplit(url).scheme not in ("http", "https"):
        raise ConfigError("SG_URL harus diawali http:// atau https://")
    username = e.get("SG_USERNAME", "").strip()
    password = e.get("SG_PASSWORD", "")
    if not password and e.get("SG_PASSWORD_FILE"):
        password = Path(e["SG_PASSWORD_FILE"]).read_text(encoding="utf-8").strip()
    if not username or not password:
        raise ConfigError("SG_USERNAME dan SG_PASSWORD (atau SG_PASSWORD_FILE) wajib diisi")
    out_dir = e.get("CAPTURE_DIR", "").strip()
    if not out_dir:
        raise ConfigError("CAPTURE_DIR wajib diisi")
    ca_file = e.get("SG_CA_FILE", "").strip() or None
    # Sertifikat SysGuard self-signed. Tanpa CA, verifikasi hanya boleh dilewati untuk
    # alamat loopback (lalu lintas tidak keluar dari perangkat) atau bila diminta eksplisit.
    insecure = _bool(e.get("SG_INSECURE_TLS"), default=ca_file is None and _is_loopback(url))
    if urlsplit(url).scheme == "https" and not insecure and ca_file is None:
        raise ConfigError("SG_URL bukan loopback: isi SG_CA_FILE (sertifikat SysGuard) "
                          "atau SG_INSECURE_TLS=1 bila memang disengaja")
    cameras = tuple(int(x) for x in e.get("CAPTURE_CAMERAS", "").replace(" ", "").split(",") if x)
    classes = tuple(c.strip() for c in e.get("CAPTURE_CLASSES", ",".join(DEFAULT_CLASSES)).split(",")
                    if c.strip())  # fmt: skip
    person = e.get("CAPTURE_PERSON_CLASS", "person").strip() or None
    if person is not None and person not in classes:
        raise ConfigError(f"CAPTURE_PERSON_CLASS {person!r} tidak ada di CAPTURE_CLASSES")
    prefix = e.get("CAPTURE_PREFIX", "ppe").strip() or "ppe"
    site = check_site(e.get("CAPTURE_SITE", "").strip() or DEFAULT_SITE)
    cfg = Config(
        sg_url=url, username=username, password=password, out_dir=Path(out_dir) / site,
        root_dir=Path(out_dir), site=site, prefix=prefix,
        camera_ids=cameras, classes=classes, person_class=person, ca_file=ca_file,
        insecure_tls=insecure,
        interval_s=num("CAPTURE_INTERVAL_S", 10.0),
        uncertain_low=num("CAPTURE_UNCERTAIN_LOW", 0.25),
        uncertain_high=num("CAPTURE_UNCERTAIN_HIGH", 0.6),
        uncertain_cooldown_s=num("CAPTURE_UNCERTAIN_COOLDOWN_S", 3.0),
        violation_cooldown_s=num("CAPTURE_VIOLATION_COOLDOWN_S", 5.0),
        empty_interval_s=num("CAPTURE_EMPTY_INTERVAL_S", 300.0),
        min_gap_s=num("CAPTURE_MIN_GAP_S", 1.0),
        dedup_iou=num("CAPTURE_DEDUP_IOU", 0.85),
        max_per_hour=num("CAPTURE_MAX_PER_HOUR", 360, int),
        disk_max_used_pct=num("CAPTURE_DISK_MAX_USED_PCT", 85.0),
        disk_min_free_mb=num("CAPTURE_DISK_MIN_FREE_MB", 1024, int),
        max_snapshot_lag_s=num("CAPTURE_MAX_SNAPSHOT_LAG_S", 1.0),
        stats_interval_s=num("CAPTURE_STATS_INTERVAL_S", 60.0),
    )  # fmt: skip
    if not 0 <= cfg.uncertain_low < cfg.uncertain_high <= 1:
        raise ConfigError("Harus 0 <= CAPTURE_UNCERTAIN_LOW < CAPTURE_UNCERTAIN_HIGH <= 1")
    if any(c in prefix for c in "/\\ "):
        raise ConfigError("CAPTURE_PREFIX tidak boleh berisi '/', '\\' atau spasi")
    return cfg
