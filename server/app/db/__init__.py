"""The database (PostgreSQL at Supabase), step by step replacing the JSON files in server/assets/.

    database.py      the connection (DATABASE_URL) and sessions; DatabaseError
    tables.py        the tables as SQLAlchemy models (the schema; changes go through an Alembic migration)
    records.py       reading and writing the app's records (Pydantic models from schemas.py) in those tables
    import_files.py  one-time import of the old JSON files: uv run python -m app.db.import_files

In the database so far: projects (public.projects) and personal API keys (private.api_keys).
Migrations live in server/migrations/ (Alembic): uv run alembic upgrade head
"""
