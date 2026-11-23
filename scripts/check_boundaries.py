"""Fail when code imports another module's internals instead of its `api.py` (README, Layout).

Usage: python scripts/check_boundaries.py [file ...]   (no files: every .py under app/)
"""

import re
import sys
from pathlib import Path

IMPORT = re.compile(r"^\s*(?:from|import)\s+app\.modules(?:\.(\w+))?(?:\.(\w+))?", re.M)


def owner(path: Path) -> str | None:
    parts = path.as_posix().split("/")
    return parts[parts.index("modules") + 1] if "modules" in parts[:-1] else None


def violations(path: Path) -> list[str]:
    own = owner(path)
    found = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        m = IMPORT.match(line)
        if m and m.group(1) != own and m.group(2) != "api":
            found.append(f"{path}:{n}: import {m.group(1) or 'app.modules'} through its api.py")
    return found


if __name__ == "__main__":
    args = sys.argv[1:]
    files = [Path(a) for a in args if a.startswith("app/")] if args else Path("app").rglob("*.py")
    errors = [v for f in files for v in violations(f)]
    print("\n".join(errors) or "module boundaries ok")
    sys.exit(1 if errors else 0)
