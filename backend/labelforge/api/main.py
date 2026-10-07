from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from labelforge import __version__
from labelforge.api.deps import DbSession
from labelforge.api.routers import classes, projects
from labelforge.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="LabelForge API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for module in (projects, classes):
        app.include_router(module.router, prefix="/api")

    @app.get("/api/health", tags=["health"])
    def health(db: DbSession):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "version": __version__, "db": "ok"}

    return app


app = create_app()
