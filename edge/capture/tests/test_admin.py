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
    assert "status lama" in out and "TIDAK terhubung" in out and "BERHENTI, disk penuh" in out and "site 'lama'" in out
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


# --- vpn ------------------------------------------------------------------------
class FakeTailscale:
    def __init__(self, state="Running", up_rc=0):
        self.state, self.up_rc, self.calls = state, up_rc, []

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == "up":
            return subprocess.CompletedProcess(args, self.up_rc, "", "" if self.up_rc == 0 else "invalid key")
        st = {"BackendState": self.state, "CurrentTailnet": {"Name": "syspex.example"},
              "Self": {"HostName": "sysedge-b01d", "TailscaleIPs": ["100.64.0.7"],
                       "KeyExpiry": "2027-05-02T03:50:00Z"},
              "Peer": {"a": {"Online": True}, "b": {"Online": False}}}  # fmt: skip
        return subprocess.CompletedProcess(args, 0, json.dumps(st), "")


def test_vpn_status(capsys):
    assert admin.cmd_vpn_status(FakeTailscale(), FakeSystemctl()) == 0
    out = capsys.readouterr().out
    assert "sysedge-b01d  100.64.0.7" in out and "1 online dari 2" in out and "kedaluwarsa" in out
    assert admin.cmd_vpn_status(FakeTailscale("NeedsLogin"), FakeSystemctl()) == 1
    assert "lfc vpn up" in capsys.readouterr().out


def test_vpn_up_uses_key_file_and_deletes_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TAILSCALE_HOME", str(tmp_path))
    ts = FakeTailscale()
    assert admin.cmd_vpn_up("sysedge-b01d", "tag:edge", ts, FakeSystemctl()) == 1  # belum ada kunci
    key = tmp_path / "authkey"
    key.write_text("tskey-auth-contoh")
    assert admin.cmd_vpn_up("sysedge-b01d", "tag:edge", FakeTailscale(up_rc=1), FakeSystemctl()) == 1
    assert key.exists()  # gagal: kunci tetap ada untuk dicoba lagi
    assert admin.cmd_vpn_up("sysedge-b01d", "tag:edge", ts, FakeSystemctl()) == 0
    assert not key.exists()
    up = next(c for c in ts.calls if c[0] == "up")
    assert f"--auth-key=file:{key}" in up and "--advertise-tags=tag:edge" in up
    assert "tskey" not in capsys.readouterr().out  # isi kunci tidak pernah dicetak


# --- inventory / export (tarik dataset) ------------------------------------------
def test_inventory_counts_complete_frames_only(paths):
    import io

    d = make_day(paths.root, "mondelez-cikarang", "20261103", frames=3)
    (d / "images" / "cam4_99.jpg").write_bytes(b"x" * 10)  # gambar tanpa label: belum lengkap
    buf = io.StringIO()
    admin.cmd_inventory(paths, buf)
    [row] = [json.loads(x) for x in buf.getvalue().splitlines()]
    expected = sum(f.stat().st_size for f in (d / "labels").glob("*.txt")) + 3 * 1000
    assert row == {"site": "mondelez-cikarang", "day": "ppe-20261103", "frames": 3, "bytes": expected}


def test_export_sends_only_missing_frames(paths):
    import io
    import tarfile

    d = make_day(paths.root, "mondelez-cikarang", "20261103", frames=3)
    (d / "data.yaml").write_text("names: [\"person\"]\n")
    (d / "labels" / "cam4_7.txt").write_text("0 0.5 0.5 0.1 0.1 0.9\n")  # label tanpa gambar
    request = ["DAY mondelez-cikarang ppe-20261103", "HAVE mondelez-cikarang ppe-20261103 cam4_0", ""]
    out = io.BytesIO()
    assert admin.cmd_export(paths, request, out) == 0
    names = tarfile.open(fileobj=io.BytesIO(out.getvalue())).getnames()
    base = "mondelez-cikarang/ppe-20261103"
    assert f"{base}/data.yaml" in names and f"{base}/meta/20261103.jsonl" in names
    assert {n for n in names if "/images/" in n} == {f"{base}/images/cam4_1.jpg", f"{base}/images/cam4_2.jpg"}
    assert f"{base}/labels/cam4_0.txt" not in names and f"{base}/labels/cam4_7.txt" not in names


def test_export_rejects_paths_outside_dataset(paths):
    import io

    for bad in (["DAY ../etc ppe-20261103"], ["DAY syspex-uji ../../etc"], ["DAY syspex-uji ppe-x"],
                ["RM syspex-uji ppe-20261103"], ["HAVE syspex-uji ppe-20261103"]):  # fmt: skip
        with pytest.raises((ValueError, ConfigError)):
            admin.cmd_export(paths, bad, io.BytesIO())


# --- flashdisk -------------------------------------------------------------------
class FakeSudo:
    def __init__(self, rc=0):
        self.rc, self.calls = rc, []

    def __call__(self, *args):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, self.rc, "", "target is busy" if self.rc else "")


@pytest.fixture
def usb(paths, tmp_path, monkeypatch):
    dev = tmp_path / "by-uuid" / "D468-AC1E"
    dev.parent.mkdir()
    monkeypatch.setattr(admin, "usb_device", lambda uuid: tmp_path / "by-uuid" / uuid)
    mounted = {"on": False}
    monkeypatch.setattr(admin.os.path, "ismount", lambda p: mounted["on"] and str(p) == str(paths.root))
    paths.usb_uuid = "D468-AC1E"
    return dev, mounted


def test_usb_pasang_mounts_by_uuid_and_starts_recorder(paths, usb, capsys):
    dev, _ = usb
    run, sudo = FakeSystemctl(active=False), FakeSudo()
    assert admin.cmd_usb_pasang(paths, run_sudo=sudo, run=run, fstype=lambda d: "vfat") == 1
    assert "tidak tercolok" in capsys.readouterr().out and not sudo.calls

    dev.write_text("")
    assert admin.cmd_usb_pasang(paths, run_sudo=sudo, run=run, fstype=lambda d: "vfat") == 0
    [call] = sudo.calls
    assert call[:3] == ("mount", "-t", "vfat") and call[-2:] == (str(dev), str(paths.root))
    assert "flush" in call[4] and "fmask=0177" in call[4] and "noexec" in call[4]
    assert ("start", admin.SERVICE) in run.calls

    sudo.calls.clear()
    assert admin.cmd_usb_pasang(paths, run_sudo=sudo, run=run, fstype=lambda d: "ext4") == 1
    assert not sudo.calls and "tidak didukung" in capsys.readouterr().out


def test_usb_pasang_waits_at_boot(paths, usb):
    dev, _ = usb
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        if len(sleeps) == 3:
            dev.write_text("")  # USB terdeteksi belakangan

    sudo = FakeSudo()
    assert admin.cmd_usb_pasang(paths, start=False, wait_s=30, run_sudo=sudo, run=FakeSystemctl(),
                                fstype=lambda d: "exfat", sleep=sleep) == 0  # fmt: skip
    assert len(sleeps) == 3 and sudo.calls and "flush" not in sudo.calls[0][4]


def test_usb_lepas_stops_recorder_then_unmounts(paths, usb, capsys):
    _, mounted = usb
    mounted["on"] = True
    run, sudo = FakeSystemctl(active=True), FakeSudo()
    assert admin.cmd_usb_lepas(paths, run_sudo=sudo, run=run) == 0
    assert ("stop", admin.SERVICE) in run.calls and sudo.calls == [("umount", str(paths.root))]
    assert "AMAN DICABUT" in capsys.readouterr().out

    assert admin.cmd_usb_lepas(paths, run_sudo=FakeSudo(rc=32), run=run) == 1
    assert "umount gagal" in capsys.readouterr().err


def test_status_shows_usb_and_storage_problem(paths, usb, capsys):
    paths.root.mkdir(parents=True)
    (paths.root / "status.json").write_text(json.dumps({
        "time": NOW.isoformat(), "connected": True, "cameras": [4], "site": paths.site,
        "disk": {"used_pct": None, "free_mb": None, "usb_mounted": False}, "disk_full": True,
        "storage_problem": "flashdisk D468-AC1E tidak terpasang"}))
    admin.cmd_status(paths, FakeSystemctl(), now=NOW)
    out = capsys.readouterr().out
    assert "flashdisk : D468-AC1E TIDAK terpasang (tidak tercolok)" in out
    assert "perekaman BERHENTI, flashdisk D468-AC1E tidak terpasang" in out


def test_usb_needs_config(paths):
    with pytest.raises(SystemExit, match="CAPTURE_USB_UUID"):
        admin.cmd_usb_status(paths)


def test_sites_ignore_foreign_folders(paths, capsys):
    import io

    make_day(paths.root, "mondelez-cikarang", "20261103")
    (paths.root / "System Volume Information").mkdir()
    admin.cmd_sites(paths)
    assert "System Volume" not in capsys.readouterr().out
    buf = io.StringIO()
    admin.cmd_inventory(paths, buf)
    assert "System Volume" not in buf.getvalue()


# --- IP port LAN (lan.env) -------------------------------------------------------
def write_lan(home: Path, text="LAN_IFACE=eth0\nLAN_ADDR=192.168.100.245/24\n"):
    home.mkdir(parents=True, exist_ok=True)
    (home / "lan.env").write_text(text)


def test_lan_config(paths):
    assert admin.load_lan(paths.home) is None  # site tanpa lan.env
    write_lan(paths.home)
    cfg = admin.load_lan(paths.home)
    assert (cfg.iface, cfg.addr, cfg.drop) == ("eth0", "192.168.100.245/24", "192.168.100.1/24")
    for bad in ("LAN_ADDR=192.168.100.245\n", "LAN_ADDR=bukan-ip/24\n", "LAN_IFACE=eth0;rm\nLAN_ADDR=10.0.0.2/24\n",
                "LAN_ADDR=192.168.100.1/24\n"):  # fmt: skip
        write_lan(paths.home, bad)
        with pytest.raises(ConfigError):
            admin.load_lan(paths.home)


def test_lan_drops_recovery_and_adds_free_address(paths):
    write_lan(paths.home)
    sudo, probes = FakeSudo(), []
    rc = admin.cmd_lan_terapkan(paths.home, run_sudo=sudo, addrs=lambda i: ["169.254.1.2/16", "192.168.100.1/24"],
                                is_up=lambda i: True, probe=lambda i, ip: probes.append(ip))  # fmt: skip
    assert rc == 0 and probes == ["192.168.100.245"]
    assert sudo.calls == [("ip", "addr", "del", "192.168.100.1/24", "dev", "eth0"),
                          ("ip", "addr", "add", "192.168.100.245/24", "dev", "eth0")]  # fmt: skip


def test_lan_does_not_add_address_in_use_or_without_link(paths, capsys):
    write_lan(paths.home)
    sudo = FakeSudo()
    rc = admin.cmd_lan_terapkan(paths.home, run_sudo=sudo, addrs=lambda i: ["192.168.100.1/24"],
                                is_up=lambda i: True, probe=lambda i, ip: "e4:30:22:ac:cb:15")  # fmt: skip
    assert rc == 1 and "sudah dipakai" in capsys.readouterr().err
    assert sudo.calls == [("ip", "addr", "del", "192.168.100.1/24", "dev", "eth0")]  # .1 tetap dilepas

    sudo = FakeSudo()
    assert admin.cmd_lan_terapkan(paths.home, run_sudo=sudo, addrs=lambda i: [], is_up=lambda i: False,
                                  probe=lambda i, ip: pytest.fail("tanpa kabel tidak ada probe")) == 0  # fmt: skip
    assert sudo.calls == []


def test_lan_idempotent_and_summary(paths):
    write_lan(paths.home)
    sudo = FakeSudo()
    ok = lambda i: ["192.168.100.245/24"]  # noqa: E731
    assert admin.cmd_lan_terapkan(paths.home, run_sudo=sudo, addrs=ok, is_up=lambda i: True,
                                  probe=lambda i, ip: pytest.fail("sudah terpasang")) == 0  # fmt: skip
    assert sudo.calls == []
    assert admin.lan_summary(paths.home, addrs=ok) == "eth0 192.168.100.245/24 [OK]"
    bad = admin.lan_summary(paths.home, addrs=lambda i: ["192.168.100.1/24"], is_up=lambda i: False)
    assert "192.168.100.1/24 masih terpasang" in bad and "kabel tidak tercolok" in bad
