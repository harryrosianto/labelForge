"""Backup & restore seluruh data LabelForge untuk pindah ke laptop/PC lain.

Git hanya membawa kode. Yang dibawa di sini: database SQLite, file gambar/thumbnail/versi,
`.env` (berisi SECRET_KEY untuk URL kamera), catatan `docs/prompts`, dan opsional cache model
AI. Hasil backup berupa satu folder biasa yang bisa disalin lewat disk eksternal.
"""

import json
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from labelforge.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent
MANIFEST = "manifest.json"
SKIP_DIRS = {"exports"}  # ZIP export bisa dibuat ulang dan biasanya sangat besar


class TransferError(Exception):
    pass


def _db_path() -> Path:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        raise TransferError("Backup/restore otomatis hanya untuk database SQLite")
    path = Path(url.removeprefix("sqlite:///"))
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def _data_dir() -> Path:
    path = Path(get_settings().data_dir)
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def _hf_cache() -> Path:
    home = os.environ.get("HF_HOME")
    return Path(home) if home else Path.home() / ".cache" / "huggingface"


def _copy_tree(src: Path, dst: Path, skip_dirs: set[str] = frozenset(), label: str = "") -> tuple[int, int]:
    """Salin isi folder; file yang sudah ada dengan ukuran sama dilewati. Hasil: (file, byte)."""
    files = size = 0
    for root, dirs, names in os.walk(src):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        rel = Path(root).relative_to(src)
        for name in names:
            if name.endswith(".tmp"):
                continue
            s, d = Path(root) / name, dst / rel / name
            st = s.stat()
            if not (d.exists() and d.stat().st_size == st.st_size):
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)
            files += 1
            size += st.st_size
            if files % 1000 == 0:
                print(f"  {label}{files} file ({size / 1e9:.2f} GB)...", flush=True)
    return files, size


def _sqlite_copy(src: Path, dst: Path) -> None:
    """Salinan konsisten walau DB sedang dipakai aplikasi (API backup SQLite)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    # closing(): `with sqlite3.connect()` saja tidak menutup koneksi (file tetap terkunci di Windows).
    with closing(_ro(src)) as s, closing(sqlite3.connect(dst)) as d:
        s.backup(d)
        # Satu file utuh tanpa -wal/-shm; aplikasi menyalakan WAL lagi saat membuka DB.
        d.execute("PRAGMA journal_mode=DELETE")


def _ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def _db_info(db: Path) -> dict:
    with closing(_ro(db)) as conn:
        revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        return {
            "schema": revision[0] if revision else None,
            "projects": conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
            "images": conn.execute("SELECT COUNT(*) FROM images").fetchone()[0],
            "annotations": conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0],
        }


def missing_files(db: Path, data_dir: Path) -> list[str]:
    """File gambar/thumbnail yang tercatat di DB tetapi tidak ada di folder data."""
    with closing(_ro(db)) as conn:
        keys = [k for row in conn.execute("SELECT storage_key, thumb_key FROM images") for k in row]
    return [k for k in keys if not (data_dir / k).is_file()]


def backup(output: Path, include_exports: bool = False, include_models: bool = False) -> Path:
    db = _db_path()
    if not db.is_file():
        raise TransferError(f"Database tidak ditemukan: {db}")
    target = Path(output).resolve() / f"labelforge-backup-{datetime.now():%Y%m%d-%H%M%S}"
    target.mkdir(parents=True)

    print(f"Backup ke {target}")
    print("- database")
    _sqlite_copy(db, target / "labelforge.db")
    info = _db_info(target / "labelforge.db")

    print("- file gambar, thumbnail, versi")
    projects = _data_dir() / "projects"
    files, size = (0, 0)
    if projects.is_dir():
        skip = set() if include_exports else SKIP_DIRS
        files, size = _copy_tree(projects, target / "data" / "projects", skip)

    copied = []
    env = REPO_DIR / ".env"
    if env.is_file():
        shutil.copy2(env, target / "env")
        copied.append(".env")
    prompts = REPO_DIR / "docs" / "prompts"
    if prompts.is_dir():
        shutil.copytree(prompts, target / "docs-prompts")
        copied.append("docs/prompts")
    if include_models and _hf_cache().is_dir():
        print("- cache model AI")
        _copy_tree(_hf_cache(), target / "huggingface", label="model: ")
        copied.append("cache model")

    missing = missing_files(target / "labelforge.db", target / "data")
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        **info,
        "files": files,
        "bytes": size,
        "include_exports": include_exports,
        "extras": copied,
        "missing_files": len(missing),
    }
    (target / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (target / "PULIHKAN.txt").write_text(
        "Pulihkan di laptop/PC baru (setelah git clone):\n\n"
        f"  .\\setup.ps1 -Restore \"<lokasi folder ini>\"\n\n"
        "atau bila setup sudah pernah dijalankan:\n\n"
        "  cd backend\n"
        "  .venv\\Scripts\\python -m labelforge.cli restore --input \"<lokasi folder ini>\"\n\n"
        "File `env` berisi SECRET_KEY untuk URL kamera RTSP. Simpan backup ini di tempat aman.\n",
        encoding="utf-8",
    )

    print(f"\nSelesai: {info['images']} gambar, {info['annotations']} anotasi, "
          f"{files} file ({size / 1e9:.2f} GB). Tambahan: {', '.join(copied) or '-'}")  # fmt: skip
    if missing:
        print(f"Peringatan: {len(missing)} file yang tercatat di DB tidak ditemukan, mis. {missing[0]}")
    if not include_exports:
        print("ZIP export tidak ikut dibackup; buat ulang dari menu Export bila perlu.")
    return target


def _set_env_value(env: Path, key: str, value: str) -> None:
    lines = env.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _env_value(env: Path, key: str) -> str:
    for line in env.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip()
    return ""


def _ensure_db_unused(db: Path) -> None:
    if not db.exists():
        return
    try:
        with closing(sqlite3.connect(db, timeout=1)) as conn:
            conn.execute("BEGIN EXCLUSIVE")
            conn.rollback()
    except sqlite3.OperationalError:
        raise TransferError("Database sedang dipakai. Matikan LabelForge dulu: .\\dev.ps1 -Stop")


def restore(source: Path, force: bool = False) -> None:
    source = Path(source).resolve()
    manifest_file = source / MANIFEST
    if not manifest_file.is_file():
        raise TransferError(f"{source} bukan folder backup LabelForge ({MANIFEST} tidak ada)")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    db, data_dir = _db_path(), _data_dir()

    if db.exists():
        _ensure_db_unused(db)
        current = _db_info(db)
        if current["images"] and not force:
            raise TransferError(
                f"Database di laptop ini sudah berisi {current['images']} gambar. Restore akan "
                "menggantinya; ulangi dengan --force bila memang itu yang diinginkan."
            )
        keep = data_dir / "backups" / f"sebelum-restore-{datetime.now():%Y%m%d-%H%M%S}.db"
        _sqlite_copy(db, keep)
        print(f"DB lama disimpan di {keep}")

    print(f"Restore dari backup {manifest['created_at']}: {manifest['images']} gambar")
    print("- database")
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    db.parent.mkdir(parents=True, exist_ok=True)
    _sqlite_copy(source / "labelforge.db", db)

    if (source / "data" / "projects").is_dir():
        print("- file gambar, thumbnail, versi")
        files, size = _copy_tree(source / "data" / "projects", data_dir / "projects")
        print(f"  {files} file ({size / 1e9:.2f} GB)")

    env, old_env = REPO_DIR / ".env", source / "env"
    if old_env.is_file():
        if not env.exists():
            shutil.copy2(old_env, env)
            print("- .env dipulihkan")
        else:
            key = _env_value(old_env, "SECRET_KEY")
            if key and key != _env_value(env, "SECRET_KEY"):
                _set_env_value(env, "SECRET_KEY", key)
                print("- SECRET_KEY di .env diganti dengan kunci dari backup (URL kamera tetap bisa dibuka)")
            print(f"  .env yang ada dipertahankan; pengaturan lama ada di {old_env}")
    prompts = REPO_DIR / "docs" / "prompts"
    if (source / "docs-prompts").is_dir() and not prompts.exists():
        shutil.copytree(source / "docs-prompts", prompts)
        print("- docs/prompts dipulihkan")
    if (source / "huggingface").is_dir():
        print("- cache model AI")
        _copy_tree(source / "huggingface", _hf_cache(), label="model: ")

    missing = missing_files(db, data_dir)
    if missing:
        print(f"Peringatan: {len(missing)} file gambar tidak ditemukan, mis. {missing[0]}")
    else:
        print("Semua file gambar yang tercatat di DB tersedia.")
