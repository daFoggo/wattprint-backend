"""Load source files (front matter + text) into tb_document and tb_chunk.

A document with the same title is replaced. Embeds with AstralX (a few cents for the whole folder).

    docker compose cp docs/sources api:/tmp/sources
    docker compose exec -T api python -m scripts.ingest_documents /tmp/sources
"""

import argparse
import asyncio
from pathlib import Path

from app.database import SessionLocal
from app.modules.copilot.services.documents import ingest, parse_source


async def main(folder: Path) -> None:
    async with SessionLocal() as s:
        for path in sorted(folder.glob("*.md")):
            meta, body = parse_source(path.read_text())
            n = await ingest(s, meta, body)
            print(f"{path.name}: {n} chunk(s) — {meta['title']}")
        await s.commit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    asyncio.run(main(ap.parse_args().folder))
