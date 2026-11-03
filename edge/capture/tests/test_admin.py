import json
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from lfcapture import admin
from lfcapture.__main__ import main
from lfcapture.config import ConfigError, check_site, default_env_files
from tests.helpers import make_config

NOW = datetime(2026, 11, 3, 2, 30, tzinfo=UTC)


class FakeSystemctl:
    def __init__(self, active=True, enabled=True):
        self.active, self.enabled, self.calls = active, enabled, []

    def __call__(self, *args):
        self.calls.append(args)
        out = ""
        if args[0] == "is-active":
            out = "active\n" if self.active else "inactive\n"
        elif args[0] == "show":
            out = (f"ActiveState={'active' if self.active else 'inactive'}\nNRestarts=1\n"
                   f"UnitFileState={'enabled' if self.enabled else 'disabled'}\n"
                   "ActiveEnterTimestamp=Tue 2026-11-03 02:11:52 UTC\n")  # fmt: skip
        return subprocess.CompletedProcess(args, 0, out, "")


def make_day(root: Path, site: str, day: str, frames=2, reasons=("violation", "interval")):
    d = root / site / f"ppe-{day}"
    for sub in ("images", "labels", "meta"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    for i in range(frames):
        (d / "images" / f"cam4_{i}.jpg").write_bytes(b"x" * 1000)
        (d / "labels" / f"cam4_{i}.txt").write_text("0 0.5 0.5 0.1 0.1 0.9\n")
    ts = datetime.strptime(day, "%Y%m%d").replace(hour=2, tzinfo=UTC).timestamp()
    rows = [json.dumps({"reason": reasons[i % len(reasons)], "snap_ts": ts + i}) for i in range(frames)]
    (d / "meta" / f"{day}.jsonl").write_text("\n".join(rows) + "\n")
    return d


@pytest.fixture
def paths(tmp_path):
    return admin.Paths(home=tmp_path / "lfcapture", root=tmp_path / "dataset", site="mondelez-cikarang")


def test_site_names():
    assert check_site("mondelez-cikarang") == "mondelez-cikarang"
    for bad in ("Mondelez", "-awal", "a b", "../etc", "a" * 41, "", "site_1"):
        with pytest.raises(ConfigError):
            check_site(bad)


def test_config_site_dirs(tmp_path):
    cfg = make_config(tmp_path, CAPTURE_SITE="mondelez-cikarang")
    assert cfg.out_dir == tmp_path / "mondelez-cikarang" and cfg.root_dir == tmp_path
    assert make_config(tmp_path).site == "umum"
    with pytest.raises(ConfigError):
        make_config(tmp_path, CAPTURE_SITE="../luar")


def test_default_env_files_site_overrides(tmp_path):
    home = tmp_path / "lfcapture"
    home.mkdir()
    (home / "capture.env").write_text(f"CAPTURE_DIR={tmp_path.as_posix()}/dataset\nCAPTURE_SITE=umum\n")
    assert default_env_files({"LFCAPTURE_HOME": str(home)}) == [home / "capture.env"]
    (home / "site.env").write_text("CAPTURE_SITE=mondelez-cikarang\n")
    assert [p.name for p in default_env_files({"LFCAPTURE_HOME": str(home)})] == ["capture.env", "site.env"]


def test_site_switch_writes_env_and_restarts(paths):
    fake = FakeSystemctl(active=True)
    assert admin.cmd_site(paths, "pabrik-dua", fake) == 0
    assert paths.site_env.read_text() == "CAPTURE_SITE=pabrik-dua\n"
    assert (paths.root / "pabrik-dua").is_dir()
    assert ("restart", admin.SERVICE) in fake.calls
    with pytest.raises(ConfigError):
        admin.cmd_site(paths, "Bukan Valid", fake)


def test_status_output(paths, capsys):
    make_day(paths.root, paths.site, "20261103", frames=3)
    (paths.root / "status.json").write_text(json.dumps({
        "time": "2026-11-03T02:29:30+00:00", "connected": True, "site": paths.site, "cameras": [4],
        "disk": {"used_pct": 56.4, "free_mb": 6900}, "disk_full": False, "counts": {}}))
    assert admin.cmd_status(paths, FakeSystemctl(), NOW) == 0
    out = capsys.readouterr().out
    assert "BERJALAN" in out and "restart 1x" in out and "autostart : on" in out
    assert "terhubung, kamera [4], diperbarui 30 detik lalu" in out
    assert "3 frame (violation 2, interval 1)" in out
    assert "2026-11-03 02:00:02 UTC" in out


def test_status_flags_stale_and_stopped(paths, capsys):
    (paths.root).mkdir(parents=True)
    (paths.root / "status.json").write_text(json.dumps({
        "time": "2026-11-03T01:00:00+00:00", "connected": False, "site": "lama", "cameras": [4],
        "disk": {"used_pct": 86, "free_mb": 900}, "disk_full": True, "counts": {}}))
    assert admin.cmd_status(paths, FakeSystemctl(active=True), NOW) == 0
    out = capsys.readouterr().out
    assert "status lama" in out and "TIDAK terhubung" in out and "PENUH" in out and "site 'lama'" in out
    assert admin.cmd_status(paths, FakeSystemctl(active=False), NOW) == 3


def test_sites_listing(paths, capsys):
    make_day(paths.root, "mondelez-cikarang", "20261102")
    make_day(paths.root, "mondelez-cikarang", "20261103")
    make_day(paths.root, "syspex-uji", "20261103", frames=5)
    admin.cmd_sites(paths)
    out = capsys.readouterr().out
    assert "* mondelez-cikarang" in out and "2 hari       4 frame" in out
    assert "  syspex-uji" in out and "5 frame" in out


def test_old_days_never_today():
    days = [(date(2026, 10, d), Path(f"ppe-202610{d:02d}")) for d in (20, 30, 31)] + \
           [(date(2026, 11, 3), Path("ppe-20261103"))]  # fmt: skip
    assert [p.name for p in admin.old_days(days, date(2026, 11, 3), 7)] == ["ppe-20261020"]
    assert len(admin.old_days(days, date(2026, 11, 3), 1)) == 3  # hari ini tidak ikut


def test_clean_with_confirmation(paths, capsys):
    old = make_day(paths.root, "syspex-uji", "20261020")
    today = make_day(paths.root, "syspex-uji", "20261103")
    assert admin.cmd_clean(paths, "syspex-uji", 7, "salah", date(2026, 11, 3)) == 1
    assert old.exists()
    assert admin.cmd_clean(paths, "syspex-uji", 7, "hapus", date(2026, 11, 3)) == 0
    assert not old.exists() and today.exists()


def test_reset_guards(paths, capsys, monkeypatch):
    make_day(paths.root, paths.site, "20261103")
    other = make_day(paths.root, "syspex-uji", "20261103").parent
    # site aktif yang sedang direkam tidak boleh dihapus
    assert admin.cmd_reset(paths, paths.site, paths.site, FakeSystemctl(active=True)) == 1
    assert (paths.root / paths.site).exists()
    # konfirmasi salah / non-interaktif tanpa --konfirmasi: batal
    assert admin.cmd_reset(paths, "syspex-uji", "mondelez-cikarang", FakeSystemctl()) == 1
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert admin.cmd_reset(paths, "syspex-uji", None, FakeSystemctl()) == 1
    assert other.exists()
    assert admin.cmd_reset(paths, "syspex-uji", "syspex-uji", FakeSystemctl()) == 0
    assert not other.exists() and paths.root.exists()
    assert admin.cmd_reset(paths, "tidak-ada", "tidak-ada", FakeSystemctl()) == 1


def test_cli_rejects_bad_site_and_reads_env_files(tmp_path, capsys, monkeypatch):
    home = tmp_path / "lfcapture"
    home.mkdir()
    (home / "capture.env").write_text(f"CAPTURE_DIR={tmp_path.as_posix()}/dataset\n")
    (home / "site.env").write_text("CAPTURE_SITE=pabrik-dua\n")
    monkeypatch.setenv("LFCAPTURE_HOME", str(home))
    assert main(["site"]) == 0
    assert capsys.readouterr().out.strip() == "pabrik-dua"
    assert main(["reset", "../etc", "--konfirmasi", "../etc"]) == 2
