"""Uji ujung ke ujung dengan SysGuard palsu: HTTP (login, kamera, snapshot) dan WebSocket /ws."""

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from websockets.asyncio.server import serve

from lfcapture.runner import Recorder
from tests.helpers import JPEG, det_msg, item, make_config, track


class FakeSysGuard:
    def __init__(self):
        self.logins = 0
        self.ws_cookies: list[str | None] = []
        self.subscribed: list[list[int]] = []
        self.snapshots = 0
        self.connections = 0
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.http.server_address[1]}"

    def token(self):
        return f"tok{self.logins}"

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body=b"", ctype="application/json", headers=()):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authed(self):
                return f"sg_session={fake.token()}" in (self.headers.get("Cookie") or "")

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                # seperti OriginGuard SysGuard: POST tanpa Origin yang sama dengan Host ditolak
                if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
                    return self._send(403, b'{"detail":"cross-origin request refused"}')
                if self.path != "/api/auth/login" or body != {"username": "perekam", "password": "rahasia-uji"}:
                    return self._send(401, b'{"detail":"Wrong username or password"}')
                fake.logins += 1
                cookie = f"sg_session={fake.token()}; HttpOnly; Path=/; SameSite=lax"
                self._send(200, b'{"user":"perekam","role":"viewer","kind":"gw"}', headers=[("Set-Cookie", cookie)])

            def do_GET(self):
                if not self._authed():
                    return self._send(401, b'{"detail":"not signed in"}')
                if self.path == "/api/cameras":
                    cams = [{"id": 3, "name": "Line 3", "enabled": True, "uri": "rtsp://***@cam"},
                            {"id": 4, "name": "Gudang", "enabled": False}]
                    return self._send(200, json.dumps(cams).encode())
                if self.path.startswith("/api/cameras/3/snapshot"):
                    fake.snapshots += 1
                    return self._send(200, JPEG, "image/jpeg")
                self._send(404, b"{}")

        return Handler

    async def ws_handler(self, ws):
        self.connections += 1
        cookie = ws.request.headers.get("Cookie")
        self.ws_cookies.append(cookie)
        if cookie != f"sg_session={self.token()}":
            await ws.close(1008)
            return
        self.subscribed.append(json.loads(await ws.recv())["subscribe"])
        await ws.send(json.dumps({"type": "subscribed", "ids": self.subscribed[-1]}))
        await ws.send(json.dumps({"type": "camera_stats", "camera_id": 3, "infer_fps": 15}))
        for n in range(3):  # orang berpindah: tiap frame layak disimpan (interval kecil)
            x = 0.1 + 0.25 * n
            msg = det_msg(ts=time.time(), tracks=[track(tid=n, box=(x, 0.2, x + 0.1, 0.8),
                                                        missing=["Helmet"] if n == 2 else [])],
                          items=[item(box=(x + 0.02, 0.15, x + 0.08, 0.22), score=0.45)])  # fmt: skip
            await ws.send(json.dumps(msg))
            await asyncio.sleep(0.15)
        await ws.send(json.dumps(det_msg(camera_id=4, ts=time.time(), tracks=[track()])))  # tidak dipilih
        if self.connections == 1:
            await ws.close(4401)  # sesi berakhir: perekam harus login ulang
            self.logins += 1  # token lama tidak berlaku lagi
            return
        await asyncio.sleep(5)


@pytest.fixture
def fake():
    f = FakeSysGuard()
    yield f
    f.http.shutdown()


def test_record_end_to_end_with_relogin(tmp_path, fake, monkeypatch):
    monkeypatch.setattr("lfcapture.runner.BACKOFF_MIN", 0.05)
    cfg = make_config(tmp_path, SG_URL=fake.url, CAPTURE_INTERVAL_S=0.1, CAPTURE_MIN_GAP_S=0,
                      CAPTURE_UNCERTAIN_COOLDOWN_S=0.1, CAPTURE_STATS_INTERVAL_S=0.2)  # fmt: skip

    async def main():
        async with serve(fake.ws_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            rec = Recorder(cfg)
            rec.client.ws_endpoint = f"ws://127.0.0.1:{port}/ws"
            stop = asyncio.Event()
            task = asyncio.create_task(rec.run(stop))
            deadline = time.monotonic() + 10
            while fake.snapshots < 6 and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.4)  # beri waktu status.json ditulis
            stop.set()
            await asyncio.wait_for(task, 5)
            return rec

    rec = asyncio.run(main())
    assert fake.subscribed == [[3], [3]]  # hanya kamera aktif
    assert fake.ws_cookies[0] == "sg_session=tok1" and fake.ws_cookies[-1] == "sg_session=tok3"
    assert fake.logins == 3  # login awal, token dicabut, login ulang
    images = sorted((tmp_path).rglob("cam3_*.jpg"))
    assert len(images) == 6 and not list(tmp_path.rglob("cam4_*"))
    # Track 2 muncul lagi setelah sambung ulang, masih dalam jeda pelanggaran 5 detik:
    # frame itu tetap tersimpan, tetapi dengan alasan box ragu.
    assert rec.stats["saved_violation"] == 1 and rec.stats["saved_uncertain"] >= 1
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["cameras"] == [3] and status["counts"]["saved_violation"] == 1
    labels = images[0].parent.parent / "labels" / (images[0].stem + ".txt")
    assert [ln.split()[0] for ln in labels.read_text().splitlines()] == ["0", "1"]


def test_wrong_password_keeps_retrying_without_crash(tmp_path, fake, monkeypatch):
    monkeypatch.setattr("lfcapture.runner.BACKOFF_MIN", 0.05)
    cfg = make_config(tmp_path, SG_URL=fake.url, SG_PASSWORD="salah", CAPTURE_STATS_INTERVAL_S=60)

    async def main():
        stop = asyncio.Event()
        task = asyncio.create_task(Recorder(cfg).run(stop))
        await asyncio.sleep(0.5)
        stop.set()
        await asyncio.wait_for(task, 5)

    asyncio.run(main())
    assert fake.logins == 0 and not list(tmp_path.rglob("*.jpg"))


def test_status_pauses_and_resumes_with_usb(tmp_path, monkeypatch):
    import os

    from lfcapture.runner import Recorder

    root = tmp_path / "dataset-usb"
    cfg = make_config(root, CAPTURE_USB_UUID="D468-AC1E")
    mounted = {"on": False}
    monkeypatch.setattr(os.path, "ismount", lambda p: mounted["on"] and str(p) == str(root))
    rec = Recorder(cfg)
    rec._write_status()
    status = json.loads((root / "status.json").read_text())
    assert rec.disk_full and status["disk_full"] and "tidak terpasang" in status["storage_problem"]

    mounted["on"] = True
    rec._write_status()
    status = json.loads((root / "status.json").read_text())
    assert not rec.disk_full and status["storage_problem"] is None and status["disk"]["usb_mounted"]
