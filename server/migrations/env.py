"""Alembic environment: migrates the database at DATABASE_URL (server/.env) to the tables in app/db/tables.py.

    uv run alembic upgrade head                               apply all migrations (run from server/)
    uv run alembic revision --autogenerate -m "what changed"  draft a migration after changing tables.py; check it
    uv run alembic current                                    which migration the database is at

The version table lives in the "private" schema, so Supabase's REST API does not serve it.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

from app.core.config import DATABASE_URL
from app.db.tables import PRIVATE, Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
_OUR_TABLES = {t.name for t in target_metadata.sorted_tables}


def include_name(name, type_, parent_names) -> bool:
    """Compare only our schemas and tables. Supabase's database also holds its own (auth, storage, ...); without
    this filter, autogenerate would propose to drop them."""
    if type_ == "schema":
        return name in (None, "public", PRIVATE)
    if type_ == "table":
        return name in _OUR_TABLES
    return True


def _options() -> dict:
    return dict(target_metadata=target_metadata, include_schemas=True, include_name=include_name,
                version_table_schema=PRIVATE, compare_type=True)


def run_migrations_offline() -> None:
    """Print the SQL instead of running it: uv run alembic upgrade head --sql"""
    context.configure(url=DATABASE_URL, literal_binds=True, dialect_opts={"paramstyle": "named"}, **_options())
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL is not set (server/.env).")
    engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as connection:
        # The version table is created before the first migration runs, so its schema must exist already.
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {PRIVATE}"))
        connection.commit()
        context.configure(connection=connection, **_options())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
