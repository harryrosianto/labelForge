"""Migrasi Alembic harus bisa upgrade/downgrade tanpa kehilangan data.

Regresi: batch mode SQLite membuat ulang tabel; dengan foreign key aktif, DROP tabel lama
memicu ON DELETE CASCADE dan menghapus anotasi.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

import labelforge.db as db_module
from labelforge.db import make_engine

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def alembic_cfg(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    monkeypatch.setattr(db_module, "_engine", engine)  # env.py memakai get_engine()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    yield cfg, engine
    engine.dispose()


def _counts(engine) -> dict[str, int]:
    with engine.connect() as c:
        return {
            t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar()
            for t in ("projects", "classes", "images", "annotations", "labeling_jobs",
                      "labeling_job_items")
        }  # fmt: skip


def test_upgrade_downgrade_keeps_data(alembic_cfg):
    cfg, engine = alembic_cfg
    command.upgrade(cfg, "0001")
    with engine.begin() as c:
        c.execute(text("INSERT INTO projects (id, name, task_type, created_at, updated_at) "
                       "VALUES (1, 'p', 'object_detection', '2026-01-01', '2026-01-01')"))
        c.execute(text("INSERT INTO classes (id, project_id, name, color, order_index, created_at, "
                       "updated_at) VALUES (1, 1, 'pallet', '#00b0ad', 0, '2026-01-01', '2026-01-01')"))
        c.execute(text("INSERT INTO images (id, project_id, original_filename, storage_key, thumb_key, "
                       "width, height, sha256, status, created_at, updated_at) VALUES "
                       "(1, 1, 'a.jpg', 'k', 't', 10, 10, 'h', 'reviewed', '2026-01-01', '2026-01-01')"))
        c.execute(text("INSERT INTO annotations (image_id, class_id, x_min, y_min, x_max, y_max, "
                       "shape_type, source, is_approved, created_at, updated_at) VALUES "
                       "(1, 1, 0.1, 0.1, 0.5, 0.5, 'bbox', 'manual', 1, '2026-01-01', '2026-01-01')"))
        c.execute(text("INSERT INTO labeling_jobs (id, project_id, job_type, provider, params, target, "
                       "include_reviewed, status, total, processed, failed_count, warnings, "
                       "cancel_requested, created_at) VALUES (1, 1, 'autolabel', 'owlv2', '{}', "
                       "'all', 0, 'completed', 1, 1, 0, '[]', 0, '2026-01-01')"))
        c.execute(text("INSERT INTO labeling_job_items (job_id, image_id, status) VALUES (1, 1, 'done')"))
    before = _counts(engine)

    command.upgrade(cfg, "head")
    assert _counts(engine) == before
    with engine.connect() as c:
        assert c.execute(text("SELECT source_type FROM images")).scalar() == "upload"

    command.downgrade(cfg, "0001")
    assert _counts(engine) == before
    command.upgrade(cfg, "head")
    assert _counts(engine) == before

    with engine.connect() as c:
        assert c.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        # foreign key kembali aktif setelah migrasi
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_downgrade_drops_rows_without_0001_shape(alembic_cfg):
    cfg, engine = alembic_cfg
    command.upgrade(cfg, "head")
    with engine.begin() as c:
        c.execute(text("INSERT INTO projects (id, name, task_type, created_at, updated_at) "
                       "VALUES (1, 'p', 'object_detection', '2026-01-01', '2026-01-01')"))
        c.execute(text("INSERT INTO labeling_jobs (id, project_id, job_type, params, target, "
                       "include_reviewed, status, total, processed, failed_count, warnings, "
                       "cancel_requested, created_at) VALUES (1, 1, 'import', '{}', 'all', 0, "
                       "'completed', 1, 1, 0, '[]', 0, '2026-01-01')"))
        c.execute(text("INSERT INTO labeling_job_items (job_id, status, label) VALUES (1, 'done', 'x.jpg')"))
    command.downgrade(cfg, "0001")
    counts = _counts(engine)
    assert counts["labeling_jobs"] == 0 and counts["labeling_job_items"] == 0
