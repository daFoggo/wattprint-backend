# Shared database updates

Place revisions here when changing objects that already exist or when a revision affects the shared migration flow across schemas.

Keep one linear Alembic history: set `down_revision` to the current head. Put revisions that introduce new public business objects in `../public/`, and new AI schema objects in `../ai/`.

This directory is included in `alembic.ini` as a version location. Generate a revision with:

```bash
docker compose exec api alembic revision -m "describe update" --version-path alembic/versions/updates
```
