"""Inference server HTTP: menjalankan provider lokal untuk dipanggil RemoteApiProvider.

Tidak butuh DB maupun storage LabelForge — cukup gambar + daftar class per request.
Kontrak lengkap ada di docstring `labelforge.providers.remote_api`.
"""

import json
import secrets
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request

from labelforge import __version__
from labelforge.config import get_settings
from labelforge.providers.base import ClassDef, ProviderError
from labelforge.providers.registry import describe_providers, get_provider

app = FastAPI(title="LabelForge Inference Server", version=__version__)


def check_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().inference_server_token
    if not expected:
        return
    if not authorization or not secrets.compare_digest(authorization, f"Bearer {expected}"):
        raise HTTPException(401, "Token tidak valid")


Auth = Depends(check_token)


@app.get("/v1/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/v1/providers", dependencies=[Auth])
def providers():
    return [p for p in describe_providers() if p["name"] != "remote"]


@app.post("/v1/detect", dependencies=[Auth])
async def detect(request: Request, payload: Annotated[str, Form()]):
    try:
        body = json.loads(payload)
        provider_name = body["provider"]
        params = body.get("params") or {}
        class_specs = body["classes"]
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(422, f"payload tidak valid: {e}")
    if provider_name == "remote":
        raise HTTPException(422, "Provider 'remote' tidak bisa dipanggil dari inference server")

    form = await request.form()
    image = form.get("image")
    if image is None or not hasattr(image, "read"):
        raise HTTPException(422, "Field 'image' wajib berupa file")

    with tempfile.TemporaryDirectory(prefix="lf-infer-") as tmp:
        tmp_dir = Path(tmp)
        image_path = tmp_dir / "image"
        image_path.write_bytes(await image.read())

        classes = []
        for spec in class_specs:
            exemplar_paths = []
            for field in spec.get("exemplars", []):
                upload = form.get(field)
                if upload is None or not hasattr(upload, "read"):
                    raise HTTPException(422, f"File exemplar '{field}' tidak dikirim")
                path = tmp_dir / field
                path.write_bytes(await upload.read())
                exemplar_paths.append(path)
            classes.append(ClassDef(int(spec["id"]), spec["name"], spec.get("text_prompt"),
                                    tuple(exemplar_paths)))  # fmt: skip

        try:
            provider = get_provider(provider_name)
            # Inference berat & sinkron → jalankan di threadpool supaya event loop tidak terblok.
            from starlette.concurrency import run_in_threadpool

            result = await run_in_threadpool(provider.detect_with_info, image_path, classes, params)
            mode = provider.resolve_params(params)["mode"]
        except ProviderError as e:
            raise HTTPException(422, str(e))

    return {
        "detections": [d.to_dict() for d in result.detections],
        "source": provider.source_tag(mode),
        "device": provider.device,
        "duration_ms": result.duration_ms,
        "warnings": result.warnings,
    }
