"""Audit numbers: merged stage by stage into docs/audit-results.json (committed)."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "docs" / "audit-results.json"


def _path(path: Path | None) -> Path:
    return path or Path(os.environ.get("AUDIT_RESULTS", DEFAULT_PATH))


def load(path: Path | None = None) -> dict[str, Any]:
    p = _path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def record(stage: str, key: str, value: Any, path: Path | None = None) -> None:
    """Set results[stage][key] = value, keeping everything else (atomic replace)."""
    p = _path(path)
    data = load(p)
    data.setdefault(stage, {})[key] = value
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True, default=str)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
