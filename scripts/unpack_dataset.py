"""Extract dataset/archive.zip into the repository's dataset/ directory."""
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "dataset" / "archive.zip"

if __name__ == "__main__":
    if not ARCHIVE.exists():
        raise FileNotFoundError(f"Dataset archive not found: {ARCHIVE}")
    with ZipFile(ARCHIVE) as archive:
        archive.extractall(ROOT)
    print(f"Extracted dataset files into {ROOT / 'dataset'}")
