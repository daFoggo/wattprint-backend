"""Load source files (front matter + text) into tb_document and tb_chunk.

The folder is the whole corpus: a document with the same title is replaced, and one whose title is
not in the folder any more (renamed or removed) is deleted. Embeds with OpenRouter, AstralX as the
fallback (about a cent for the folder).

    docker compose exec -T api rm -rf /tmp/sources  # else cp nests the folder inside the old one
    docker compose cp docs/sources api:/tmp/sources
    docker compose exec -T api python -m scripts.ingest_documents /tmp/sources
"""

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import delete

from app.database import SessionLocal
from app.models import Document
from app.modules.copilot.services.documents import ingest, parse_source


async def main(folder: Path) -> None:
    async with SessionLocal() as s:
        titles = []
        for path in sorted(folder.glob("*.md")):
            meta, body = parse_source(path.read_text())
            n = await ingest(s, meta, body)
            titles.append(meta["title"])
            print(f"{path.name}: {n} chunk(s) — {meta['title']}")
        if titles:  # an empty or wrong folder must not wipe the corpus
            gone = await s.execute(delete(Document).where(Document.title.not_in(titles)))
            print(f"removed {gone.rowcount} document(s) not in the folder")
        await s.commit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    asyncio.run(main(ap.parse_args().folder))
