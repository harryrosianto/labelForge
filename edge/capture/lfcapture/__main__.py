"""CLI perekam.

    python -m lfcapture check --env-file capture.env   cek login, kamera, snapshot, dan disk
    python -m lfcapture run --env-file capture.env     mulai merekam (Ctrl+C / SIGTERM berhenti)
"""

import argparse
import asyncio
import logging
import os
import signal
import sys

from lfcapture.client import ApiError, AuthError, SysGuardClient
from lfcapture.config import ConfigError, load_config, read_env_file
from lfcapture.runner import Recorder
from lfcapture.writer import DatasetWriter


def _config(args):
    env = dict(os.environ)
    if args.env_file:
        env.update(read_env_file(args.env_file))
    return load_config(env)


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
    disk = DatasetWriter(cfg).disk_status()
    print(f"disk       : {disk['used_pct']}% terpakai, sisa {disk['free_mb']} MB di {cfg.out_dir}")
    if disk["used_pct"] >= cfg.disk_max_used_pct or disk["free_mb"] < cfg.disk_min_free_mb:
        ok = False
        print("             di atas batas, perekam tidak akan menyimpan frame")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lfcapture", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["check", "run"])
    parser.add_argument("--env-file", help="file KEY=VALUE (lihat capture.env.example)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log tiap frame tersimpan")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = _config(args)
    except (ConfigError, OSError) as e:
        print(f"Konfigurasi: {e}", file=sys.stderr)
        return 2
    if args.command == "check":
        return cmd_check(cfg)
    try:
        asyncio.run(_run(cfg))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
