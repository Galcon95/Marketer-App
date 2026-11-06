"""The database (PostgreSQL at Supabase): all records of the app (files.py stores the uploaded files).

    database.py      the connection (DATABASE_URL) and sessions; DatabaseError
    tables.py        the tables as SQLAlchemy models (the schema; changes go through an Alembic migration)
    records.py       reading and writing the app's records (Pydantic models from schemas.py) in those tables

In the database: projects, books (sources) with their summaries and chunks (with pgvector embeddings), generated
assets, "Ask your book" chats and the usage log (schema public), and personal API keys (private.api_keys). The
uploaded files and their covers are in Supabase Storage (core/files.py).
Migrations live in server/migrations/ (Alembic): uv run alembic upgrade head
"""
