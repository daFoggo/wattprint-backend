"""Load the system skills and tools into the database and embed them.

    python -m app.cli.copilot_skills sync      # after `alembic upgrade head`, on every deploy

Reads app/copilot/config/skills.yaml and the handler registry; unchanged chunks keep their
vectors, so a second run embeds nothing. Needs the cpu or gpu extra (bge-m3).
"""

import argparse
import asyncio

from ..copilot.skills.catalog_sync import sync
from ..copilot.tools.embedder import default_embedder


async def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli.copilot_skills", description=__doc__)
    p.add_argument("command", choices=["sync"])
    p.parse_args(argv)
    from ..database import SessionLocal, engine

    try:
        async with SessionLocal() as s:
            print(await sync(s, default_embedder()))
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
