import tomllib
from pathlib import Path

from app.config import settings


def demo_home_entries() -> list[dict]:
    """The `[[home]]` tables of the demo homes file: what makes a home a demo one."""
    return tomllib.loads(Path(settings.demo_homes_file).read_text())["home"]
