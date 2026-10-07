import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from labelforge.api.main import create_app
from labelforge.db import get_db, make_engine
from labelforge.models import Base
from labelforge.services.jobs import run_autolabel_job
from labelforge.storage import LocalStorage, get_storage
from labelforge.worker.queue import get_job_queue


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "data")


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def db(session_factory):
    with session_factory() as session:
        yield session


class InlineQueue:
    """Pengganti Celery di test: job dijalankan langsung (atau ditahan jika run=False)."""

    def __init__(self, session_factory, storage):
        self.session_factory = session_factory
        self.storage = storage
        self.run = True
        self.enqueued: list[int] = []
        self.revoked: list[str] = []

    def enqueue_autolabel(self, job_id: int) -> str:
        self.enqueued.append(job_id)
        if self.run:
            run_autolabel_job(job_id, self.session_factory, self.storage)
        return f"task-{job_id}"

    def revoke(self, task_id: str) -> None:
        self.revoked.append(task_id)

    def ping_workers(self, timeout: float = 1.0) -> list[str]:
        return ["inline@test"]


@pytest.fixture
def queue(session_factory, storage):
    return InlineQueue(session_factory, storage)


@pytest.fixture
def client(session_factory, storage, queue):
    app = create_app()

    def _get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_job_queue] = lambda: queue
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "Warehouse"}).json()
