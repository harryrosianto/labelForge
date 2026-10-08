"""Enkripsi URL kamera (berisi username/password) dan penyamarannya untuk tampilan/log."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken

from labelforge.config import get_settings

SENSITIVE_QUERY_KEYS = {"password", "pass", "pwd", "user", "username", "token", "key", "auth"}


class SecretKeyError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().secret_key
    if not key:
        raise SecretKeyError(
            "SECRET_KEY belum diatur di .env. Buat dengan: python -c \"from cryptography.fernet "
            "import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as e:
        raise SecretKeyError("SECRET_KEY tidak valid (harus kunci Fernet base64 32 byte)") from e


def encrypt_url(url: str) -> str:
    return _fernet().encrypt(url.encode()).decode()


def decrypt_url(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise SecretKeyError("URL kamera tidak bisa dibuka; SECRET_KEY berubah sejak kamera ditambahkan") from e


def mask_url(url: str) -> str:
    """rtsp://admin:rahasia@10.0.0.5:554/stream?password=x → rtsp://***@10.0.0.5:554/stream?password=***"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "***"
    netloc = parts.netloc
    if "@" in netloc:
        netloc = "***@" + netloc.rsplit("@", 1)[1]
    query = urlencode(
        [(k, "***" if k.lower() in SENSITIVE_QUERY_KEYS else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)],
        safe="*",
    )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def scrub(text: str, url: str) -> str:
    """Hapus URL asli (dan kredensialnya) dari pesan error sebelum disimpan/ditampilkan."""
    if not text:
        return text
    out = text.replace(url, mask_url(url))
    parts = urlsplit(url)
    if parts.password:
        out = out.replace(parts.password, "***")
    return re.sub(r"(rtsps?|https?)://[^\s@/]+@", r"\1://***@", out)
