from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from labelforge import __version__
from labelforge.api.deps import DbSession
from labelforge.api.routers import (
    annotations,
    classes,
    export,
    images,
    imports,
    jobs,
    media,
    projects,
    review,
    stats,
    versions,
)
from labelforge.config import get_settings
from labelforge.worker.queue import JobQueue, get_job_queue


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="LabelForge API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for module in (projects, classes, images, annotations, jobs, export, imports, versions, stats, media, review):
        app.include_router(module.router, prefix="/api")

    @app.get("/api/health", tags=["health"])
    def health(db: DbSession, queue: Annotated[JobQueue, Depends(get_job_queue)]):
        db.execute(text("SELECT 1"))
        workers = queue.ping_workers(timeout=1.0)
        served = {q for w in workers if w.get("state") == "ready" for q in w.get("queues", [])}
        return {
            "status": "ok", "version": __version__, "db": "ok",
            "workers": [w["name"] for w in workers],
            "worker_details": workers,
            # Queue tanpa worker siap: job di queue itu akan menunggu.
            "queues_without_worker": sorted({"inference", "io"} - served),
        }  # fmt: skip

    return app


app = create_app()
