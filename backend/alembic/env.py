from logging.config import fileConfig

from alembic import context

from labelforge.db import get_engine
from labelforge.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(get_engine().url),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        if is_sqlite:
            # Batch mode SQLite membuat ulang tabel (copy → DROP → rename). Dengan foreign key
            # aktif, DROP tabel lama memicu ON DELETE CASCADE dan menghapus data tabel anak
            # (mis. anotasi saat tabel images dibuat ulang). PRAGMA ini harus di luar transaksi.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite tidak mendukung ALTER COLUMN; batch mode membuat ulang tabel.
            render_as_batch=is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()
        if is_sqlite:
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            if violations:
                raise RuntimeError(f"Migrasi meninggalkan foreign key tidak valid: {violations[:5]}")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
