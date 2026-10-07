import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from labelforge.api.main import create_app
from labelforge.db import get_db, make_engine
from labelforge.models import Base
from labelforge.storage import LocalStorage, get_storage


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


@pytest.fixture
def client(session_factory, storage):
    app = create_app()

    def _get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "Warehouse"}).json()
