from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from labelforge import __version__
from labelforge.api.deps import DbSession
from labelforge.api.routers import annotations, classes, export, images, imports, jobs, projects
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

    for module in (projects, classes, images, annotations, jobs, export, imports):
        app.include_router(module.router, prefix="/api")

    @app.get("/api/health", tags=["health"])
    def health(db: DbSession, queue: Annotated[JobQueue, Depends(get_job_queue)]):
        db.execute(text("SELECT 1"))
        workers = queue.ping_workers(timeout=1.0)
        return {"status": "ok", "version": __version__, "db": "ok", "workers": workers}

    return app


app = create_app()
