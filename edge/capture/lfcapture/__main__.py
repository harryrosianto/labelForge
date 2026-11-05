"""Perekam dataset LabelForge di perangkat SysGuard.

Pemakaian di perangkat (lewat SSH), dengan pembungkus `lfc`:
  lfc status                     ringkasan: perekam, site, koneksi, frame hari ini, disk
  lfc start | stop               mulai / hentikan perekaman
  lfc autostart on|off           ikut jalan saat perangkat menyala
  lfc site [nama]                tampilkan / ganti site aktif (folder dataset per lokasi)
  lfc sites                      daftar site dan ukurannya
  lfc log [-f] [-n N]            lihat log
  lfc clean <site> --older-than N    hapus folder harian lama (sudah ditarik ke laptop)
  lfc reset <site>               hapus seluruh data satu site
  lfc check                      uji login, kamera, snapshot, dan disk
  lfc usb [pasang|lepas]         flashdisk penyimpan dataset: status / pasang / lepas aman
  lfc vpn [up]                   status akses jarak jauh / daftarkan perangkat ke Tailscale
  lfc lan [terapkan]             IP port LAN pengganti alamat recovery 192.168.100.1 (lan.env)
  lfc inventory | export         dipakai skrip tarik di laptop (deploy/tarik-dataset.ps1)
  lfc run                        jalan di foreground (dipakai service)

File env dibaca dari $LFCAPTURE_HOME (default ~/lfcapture): capture.env lalu site.env,
atau dari --env-file (boleh lebih dari sekali).
"""

import argparse
import asyncio
import logging
import os
import signal
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from lfcapture import admin
from lfcapture.client import ApiError, AuthError, SysGuardClient
from lfcapture.config import ConfigError, default_env_files, load_config, read_env_file
from lfcapture.runner import Recorder
from lfcapture.writer import DatasetWriter

LOG_MAX_BYTES, LOG_BACKUPS = 1024 * 1024, 2  # paling banyak sekitar 3 MB


def _env(args) -> dict[str, str]:
    env = dict(os.environ)
    files = [Path(f) for f in args.env_file] if args.env_file else default_env_files(env)
    for f in files:
        env.update(read_env_file(f))
    return env


def cmd_check(cfg) -> int:
    client = SysGuardClient(cfg)
    ok = True
    try:
        client.login()
        print(f"login      : OK sebagai {cfg.username}")
        cams = client.cameras()
    except (AuthError, ApiError, OSError) as e:
        print(f"login      : GAGAL ({e})")
        return 1
    targets = [c for c in cams if (c["id"] in cfg.camera_ids if cfg.camera_ids else c["enabled"])]
    print(f"kamera     : {len(cams)} terdaftar, {len(targets)} akan direkam")
    for cam in targets:
        try:
            jpeg, _ = client.snapshot(cam["id"])
            print(f"  cam{cam['id']:<4} {cam['name']!s:<30} snapshot OK ({len(jpeg) // 1024} KB)")
        except (AuthError, ApiError, OSError) as e:
            ok = False
            print(f"  cam{cam['id']:<4} {cam['name']!s:<30} snapshot GAGAL ({e})")
    print(f"site       : {cfg.site} ({cfg.out_dir})")
    writer = DatasetWriter(cfg)
    disk = writer.disk_status()
    if cfg.usb_uuid:
        print(f"flashdisk  : {cfg.usb_uuid} {'terpasang' if disk['usb_mounted'] else 'TIDAK terpasang'}")
    if disk["used_pct"] is not None:
        print(f"disk       : {disk['used_pct']}% terpakai, sisa {disk['free_mb']} MB")
    problem = writer.storage_problem()
    if problem:
        # Flashdisk yang belum dicolok bukan kegagalan pemasangan: perekam menunggu sampai dipasang.
        if disk["usb_mounted"]:
            ok = False
        print(f"             perekam tidak akan menyimpan frame: {problem}")
    return 0 if ok and targets else 1


async def _run(cfg) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, AttributeError):  # Windows: Ctrl+C lewat KeyboardInterrupt
            pass
    await Recorder(cfg).run(stop)


def _setup_logging(verbose: bool, log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_file, maxBytes=LOG_MAX_BYTES,
                                            backupCount=LOG_BACKUPS, encoding="utf-8"))  # fmt: skip
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(message)s")  # fmt: skip


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lfc", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", action="append", help="file KEY=VALUE (boleh berulang)")
    sub = parser.add_subparsers(dest="command", required=True, metavar="perintah")
    run = sub.add_parser("run", help="rekam di foreground")
    run.add_argument("-v", "--verbose", action="store_true", help="log tiap frame tersimpan")
    run.add_argument("--log-file", help="tulis log juga ke file ini (dirotasi, maks ~3 MB)")
    sub.add_parser("check", help="uji login, kamera, snapshot, disk")
    sub.add_parser("status", help="ringkasan perekam")
    sub.add_parser("start", help="mulai perekaman")
    sub.add_parser("stop", help="hentikan perekaman")
    auto = sub.add_parser("autostart", help="ikut jalan saat perangkat menyala")
    auto.add_argument("mode", choices=["on", "off"])
    site = sub.add_parser("site", help="tampilkan / ganti site aktif")
    site.add_argument("nama", nargs="?")
    sub.add_parser("sites", help="daftar site")
    log = sub.add_parser("log", help="lihat log")
    log.add_argument("-f", "--follow", action="store_true")
    log.add_argument("-n", "--lines", type=int, default=50)
    clean = sub.add_parser("clean", help="hapus folder harian lama satu site")
    clean.add_argument("site")
    clean.add_argument("--older-than", type=int, required=True, metavar="HARI")
    clean.add_argument("--konfirmasi", help="isi 'hapus' untuk tanpa tanya (mis. dari skrip)")
    sub.add_parser("inventory", help="daftar folder harian (JSON per baris), dipakai skrip tarik")
    sub.add_parser("export", help="tar frame yang belum dimiliki (permintaan dari stdin) ke stdout")
    usb = sub.add_parser("usb", help="flashdisk penyimpan dataset: status / pasang / lepas")
    usb.add_argument("aksi", nargs="?", choices=["status", "pasang", "lepas"], default="status")
    usb.add_argument("--tanpa-start", action="store_true", help="pasang tanpa memulai perekam")
    usb.add_argument("--tunggu", type=float, default=0, metavar="DETIK",
                     help="tunggu flashdisk terdeteksi (dipakai saat boot)")
    lan = sub.add_parser("lan", help="IP port LAN pengganti alamat recovery (lan.env)")
    lan.add_argument("aksi", nargs="?", choices=["status", "terapkan"], default="status")
    vpn = sub.add_parser("vpn", help="status / daftar akses jarak jauh (Tailscale)")
    vpn.add_argument("aksi", nargs="?", choices=["status", "up"], default="status")
    vpn.add_argument("--hostname", default=socket.gethostname())
    vpn.add_argument("--tags", help="mis. tag:edge (harus diizinkan di ACL tailnet)")
    reset = sub.add_parser("reset", help="hapus seluruh data satu site")
    reset.add_argument("site")
    reset.add_argument("--konfirmasi", help="isi nama site untuk tanpa tanya (mis. dari skrip)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = paths = None
    try:
        env = _env(args)
        if args.command in ("run", "check"):
            cfg = load_config(env)
        else:
            paths = admin.load_paths(env)
    except (ConfigError, OSError) as e:
        print(f"Konfigurasi: {e}", file=sys.stderr)
        return 2

    try:
        return _dispatch(args, cfg, paths)
    except ConfigError as e:  # nama site tidak valid
        print(e, file=sys.stderr)
        return 2


def _dispatch(args, cfg, paths) -> int:
    match args.command:
        case "run":
            _setup_logging(args.verbose, args.log_file)
            try:
                asyncio.run(_run(cfg))
            except KeyboardInterrupt:
                pass
            return 0
        case "check":
            return cmd_check(cfg)
        case "status":
            return admin.cmd_status(paths)
        case "start" | "stop":
            return admin.cmd_service(args.command)
        case "autostart":
            return admin.cmd_autostart(args.mode == "on")
        case "site":
            return admin.cmd_site(paths, args.nama)
        case "sites":
            return admin.cmd_sites(paths)
        case "log":
            return admin.cmd_log(paths, args.lines, args.follow)
        case "clean":
            return admin.cmd_clean(paths, args.site, args.older_than, args.konfirmasi)
        case "reset":
            return admin.cmd_reset(paths, args.site, args.konfirmasi)
        case "inventory":
            return admin.cmd_inventory(paths)
        case "export":
            try:
                return admin.cmd_export(paths, sys.stdin, sys.stdout.buffer)
            except ValueError as e:
                print(f"permintaan export ditolak: {e}", file=sys.stderr)
                return 2
        case "usb":
            if args.aksi == "pasang":
                return admin.cmd_usb_pasang(paths, start=not args.tanpa_start, wait_s=args.tunggu)
            if args.aksi == "lepas":
                return admin.cmd_usb_lepas(paths)
            return admin.cmd_usb_status(paths)
        case "lan":
            if args.aksi == "terapkan":
                return admin.cmd_lan_terapkan(paths.home)
            return admin.cmd_lan_status(paths.home)
        case "vpn":
            if args.aksi == "up":
                return admin.cmd_vpn_up(args.hostname, args.tags)
            return admin.cmd_vpn_status()
    return 2


if __name__ == "__main__":
    sys.exit(main())
