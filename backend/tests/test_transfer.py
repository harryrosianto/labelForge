import json
import sqlite3

import pytest

from labelforge.cli import transfer
from labelforge.cli.transfer import TransferError, backup, restore
from tests.test_api_images import upload
from tests.test_images_service import make_jpeg


class Machine:
    """Satu 'laptop': repo (berisi .env & docs/prompts), DB, dan folder data."""

    def __init__(self, root, monkeypatch):
        self.repo = root / "repo"
        self.data = self.repo / "backend" / "data"
        self.db = self.data / "labelforge.db"
        self.hf = root / "hf"
        self.data.mkdir(parents=True)
        self.monkeypatch = monkeypatch

    def activate(self):
        mp = self.monkeypatch
        mp.setattr(transfer, "REPO_DIR", self.repo)
        mp.setattr(transfer, "_db_path", lambda: self.db)
        mp.setattr(transfer, "_data_dir", lambda: self.data)
        mp.setattr(transfer, "_hf_cache", lambda: self.hf)
        return self


@pytest.fixture
def old_pc(tmp_path, monkeypatch, client, project, storage, session_factory):
    """Laptop lama: data dari API test (2 gambar) disalin ke struktur repo."""
    pid = project["id"]
    upload(client, pid, ("a.jpg", make_jpeg((40, 30), "red")), ("b.jpg", make_jpeg((40, 30), "blue")))
    pc = Machine(tmp_path / "old", monkeypatch)
    src_db = session_factory.kw["bind"].url.database
    with sqlite3.connect(src_db) as s, sqlite3.connect(pc.db) as d:
        s.backup(d)
    with sqlite3.connect(pc.db) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32))")
        conn.execute("INSERT INTO alembic_version VALUES ('0003')")
    import shutil

    shutil.copytree(storage.root / "projects", pc.data / "projects")
    (pc.data / "projects" / str(pid) / "exports").mkdir()
    (pc.data / "projects" / str(pid) / "exports" / "besar.zip").write_bytes(b"x" * 100)
    (pc.repo / ".env").write_text("DATA_DIR=./data\nSECRET_KEY=kunci-lama\nOWLV2_SCORE_THRESHOLD=0.2\n")
    (pc.repo / "docs" / "prompts").mkdir(parents=True)
    (pc.repo / "docs" / "prompts" / "SPEC.md").write_text("catatan")
    (pc.hf / "hub").mkdir(parents=True)
    (pc.hf / "hub" / "model.bin").write_bytes(b"m")
    return pc.activate()


def test_backup_then_restore_on_new_pc(old_pc, tmp_path, monkeypatch):
    out = backup(tmp_path / "usb", include_models=True)
    manifest = json.loads((out / "manifest.json").read_text())
    assert (manifest["images"], manifest["schema"], manifest["missing_files"]) == (2, "0003", 0)
    assert set(manifest["extras"]) == {".env", "docs/prompts", "cache model"}
    assert not list(out.rglob("besar.zip"))  # export tidak ikut secara default
    assert (out / "PULIHKAN.txt").is_file()

    new = Machine(tmp_path / "new", monkeypatch).activate()
    (new.repo / ".env").write_text("DATA_DIR=./data\nSECRET_KEY=\n")  # dibuat setup.ps1
    restore(out)
    with sqlite3.connect(new.db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 2
    assert transfer.missing_files(new.db, new.data) == []
    env = (new.repo / ".env").read_text()
    assert "SECRET_KEY=kunci-lama" in env and "OWLV2" not in env  # .env baru dipertahankan, kunci dipulihkan
    assert (new.repo / "docs" / "prompts" / "SPEC.md").read_text() == "catatan"
    assert (new.hf / "hub" / "model.bin").is_file()


def test_restore_copies_env_when_missing_and_refuses_overwrite(old_pc, tmp_path, monkeypatch):
    out = backup(tmp_path / "usb")
    new = Machine(tmp_path / "new", monkeypatch).activate()
    restore(out)
    assert "OWLV2_SCORE_THRESHOLD=0.2" in (new.repo / ".env").read_text()

    with pytest.raises(TransferError, match="sudah berisi 2 gambar"):
        restore(out)
    restore(out, force=True)
    assert list((new.data / "backups").glob("sebelum-restore-*.db"))


def test_backup_with_exports_and_invalid_restore_source(old_pc, tmp_path):
    out = backup(tmp_path / "usb", include_exports=True)
    assert list(out.rglob("besar.zip"))
    with pytest.raises(TransferError, match="bukan folder backup"):
        restore(tmp_path)
