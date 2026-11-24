import functools
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from .devices import DEVICE_TYPES


@dataclass(frozen=True)
class Score:
    """How well NILM finds one device type on its bundle's held-out test split (REFIT's own plugs
    as truth, scored offline by dataset/training): energy matched step by step, the kWh error."""

    level: str  # high, medium, low
    energy_f1: float
    kwh_err_pct: float
    onoff_f1: float


def _level(f1: float) -> str:
    if f1 >= settings.nilm_high_f1:
        return "high"
    return "medium" if f1 >= settings.nilm_medium_f1 else "low"


def scores_from(sidecar: dict) -> dict[str, Score]:
    """Device type code -> its score, from a bundle's JSON sidecar; empty if never scored."""
    rows = sidecar.get("meta", {}).get("test_by_device") or {}
    return {
        DEVICE_TYPES[label]: Score(
            level=_level(r["energy F1"]),
            energy_f1=round(r["energy F1"], 3),
            kwh_err_pct=round(r["kWh err %"], 2),
            onoff_f1=round(r["F1 ON/OFF"], 3),
        )
        for label, r in rows.items()
        if label in DEVICE_TYPES
    }


@functools.lru_cache(maxsize=16)
def _read(path: str, mtime: float) -> dict[str, Score]:
    del mtime  # part of the key only: a re-scored sidecar is read again
    return scores_from(json.loads(Path(path).read_text()))


async def device_scores(session: AsyncSession, home_id: uuid.UUID) -> dict[str, Score]:
    """The scores of the bundle the NILM worker runs for this home (its own, else the shared one, as
    runner.TARGETS picks it); empty without a model or a scored sidecar."""
    artifact = await session.scalar(
        text(
            "SELECT artifact FROM public.tb_nilm_model WHERE active "
            "AND (home_id = :h OR home_id IS NULL) ORDER BY home_id NULLS LAST LIMIT 1"
        ),
        {"h": home_id},
    )
    if artifact is None:
        return {}
    sidecar = (Path(settings.nilm_model_dir) / artifact).with_suffix(".json")
    if not sidecar.is_file():
        return {}
    return _read(str(sidecar), sidecar.stat().st_mtime)
