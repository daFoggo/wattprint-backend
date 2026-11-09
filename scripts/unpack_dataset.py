"""Extract the dataset and NILM training artifacts into the repository.

- dataset/archive.zip            -> dataset/ (REFIT CSVs)
- dataset/training/artifacts.zip -> dataset/training/checkpoints/nilm_pipeline.pt (production weights)
                                    dataset/training/data/refit_house2_windows.npz (training windows)
"""
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = [ROOT / "dataset" / "archive.zip", ROOT / "dataset" / "training" / "artifacts.zip"]

if __name__ == "__main__":
    missing = [a for a in ARCHIVES if not a.exists()]
    if missing:
        raise FileNotFoundError(f"Archive(s) not found: {', '.join(map(str, missing))}")
    for archive_path in ARCHIVES:
        with ZipFile(archive_path) as archive:
            archive.extractall(ROOT)               # members are stored with repo-relative paths
        print(f"Extracted {archive_path.relative_to(ROOT)}")
