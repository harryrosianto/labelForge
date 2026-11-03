"""Klien API SysGuard Vision: login akun gateway, daftar kamera, snapshot, dan WebSocket /ws.

- Login: POST /api/auth/login {username, password} -> cookie `sg_session`. Akun dengan TOTP
  tidak bisa dipakai karena perekam berjalan tanpa orang.
- GET /api/cameras/{id}/snapshot: frame mentah terbaru dari grabber (tanpa box tergambar),
  sumber yang sama dengan frame yang dideteksi.
- /ws: kirim {"subscribe": [id kamera]}, lalu terima pesan `detections` per frame.
"""

import json
import ssl
import time
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from websockets.asyncio.client import ClientConnection, connect

from lfcapture.config import Config

COOKIE = "sg_session"
HTTP_TIMEOUT = 10.0
CLOSE_SESSION_ENDED = 4401  # SysGuard menutup /ws dengan kode ini saat sesi berakhir
CLOSE_POLICY = 1008  # tanpa sesi yang sah


class AuthError(Exception):
    """Login gagal atau sesi berakhir; perlu login ulang (atau konfigurasi diperbaiki)."""


class ApiError(Exception):
    pass


def ssl_context(cfg: Config) -> ssl.SSLContext | None:
    if urlsplit(cfg.sg_url).scheme != "https":
        return None
    if cfg.insecure_tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    ctx = ssl.create_default_context(cafile=cfg.ca_file)
    ctx.check_hostname = False  # sertifikat SysGuard dibuat untuk nama perangkat, bukan IP
    return ctx


class SysGuardClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.base = cfg.sg_url
        self._ssl = ssl_context(cfg)
        self.session: str | None = None
        self.ws_endpoint = self.ws_url()

    # --- HTTP ---------------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None,
                 accept: str = "application/json") -> tuple[int, dict, bytes]:
        headers = {"Accept": accept}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if method != "GET":
            # SysGuard menolak POST/PUT/DELETE ke /api bila Origin tidak sama dengan Host.
            parts = urlsplit(self.base)
            headers["Origin"] = f"{parts.scheme}://{parts.netloc}"
        if self.session:
            headers["Cookie"] = f"{COOKIE}={self.session}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=self._ssl) as r:
                return r.status, dict(r.headers.items()), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers.items()), e.read()

    def login(self) -> None:
        status, headers, raw = self._request(
            "POST", "/api/auth/login", {"username": self.cfg.username, "password": self.cfg.password})
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        detail = body.get("detail") if isinstance(body, dict) else None
        reason = f": {detail}" if isinstance(detail, str) else ""
        if status in (400, 401, 403, 409):  # 409: password awal gateway harus diganti dulu
            raise AuthError(f"login ditolak (HTTP {status}){reason}")
        if status != 200:
            raise ApiError(f"login gagal (HTTP {status}){reason}")
        if body.get("next") == "totp":
            raise AuthError("akun memakai TOTP; buat akun khusus perekam tanpa TOTP")
        cookie = SimpleCookie()
        for key, value in headers.items():
            if key.lower() == "set-cookie":
                cookie.load(value)
        if COOKIE not in cookie:
            raise ApiError("login berhasil tetapi cookie sesi tidak diterima")
        self.session = cookie[COOKIE].value

    def _get_json(self, path: str):
        status, _, raw = self._request("GET", path)
        if status == 401:
            self.session = None
            raise AuthError("sesi berakhir")
        if status != 200:
            raise ApiError(f"GET {path}: HTTP {status}")
        return json.loads(raw)

    def cameras(self) -> list[dict]:
        cams = self._get_json("/api/cameras")
        return [{"id": c.get("id"), "name": c.get("name"), "enabled": bool(c.get("enabled")),
                 "resolution": c.get("resolution")}
                for c in cams if isinstance(c, dict) and isinstance(c.get("id"), int)]  # fmt: skip

    def snapshot(self, camera_id: int) -> tuple[bytes, float]:
        """(JPEG, waktu diterima). Waktu diambil saat respons tiba, paling dekat ke frame."""
        status, headers, raw = self._request(
            "GET", f"/api/cameras/{camera_id}/snapshot?t={int(time.time() * 1000)}", accept="image/jpeg")
        received = time.time()
        if status == 401:
            self.session = None
            raise AuthError("sesi berakhir")
        if status != 200:
            raise ApiError(f"snapshot kamera {camera_id}: HTTP {status}")
        ctype = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
        if "jpeg" not in ctype or not raw.startswith(b"\xff\xd8"):
            raise ApiError(f"snapshot kamera {camera_id} bukan JPEG ({ctype})")
        return raw, received

    # --- WebSocket ----------------------------------------------------------
    def ws_url(self) -> str:
        parts = urlsplit(self.base)
        scheme = "wss" if parts.scheme == "https" else "ws"
        return f"{scheme}://{parts.netloc}/ws"

    def open_ws(self):
        """Context manager koneksi /ws (websockets). Tanpa header Origin: SysGuard menolak
        Origin yang berbeda dari Host, dan klien non-browser tidak perlu mengirimnya."""
        if not self.session:
            raise AuthError("belum login")
        return connect(self.ws_endpoint, ssl=self._ssl,
                       additional_headers={"Cookie": f"{COOKIE}={self.session}"},
                       max_size=4 * 1024 * 1024, open_timeout=HTTP_TIMEOUT)  # fmt: skip


async def subscribe(ws: ClientConnection, camera_ids: list[int]) -> None:
    await ws.send(json.dumps({"subscribe": camera_ids}))
