# Dua target dari satu Dockerfile:
#   web    : FastAPI (tanpa torch, image kecil)
#   worker : Celery + model AI (torch CPU default; GPU via build-arg TORCH_INDEX_URL)

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app


FROM base AS web
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY labelforge ./labelforge
RUN pip install .
EXPOSE 8000
# Migrasi DB dijalankan setiap start (idempotent), lalu API.
CMD ["sh", "-c", "python -m labelforge.cli migrate && uvicorn labelforge.api.main:app --host 0.0.0.0 --port 8000"]


FROM base AS worker
# CPU: https://download.pytorch.org/whl/cpu
# GPU: https://download.pytorch.org/whl/cu126 (atau cu130 untuk driver terbaru)
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
# Layer torch terpisah & sebelum kode, supaya tidak di-download ulang setiap kode berubah.
RUN pip install torch torchvision --index-url ${TORCH_INDEX_URL}
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY labelforge ./labelforge
RUN pip install ".[ml]"
CMD ["celery", "-A", "labelforge.worker.celery_app", "worker", "--pool=solo", "--concurrency=1", \
     "-Q", "inference", "--loglevel=INFO"]
