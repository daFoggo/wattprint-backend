"""Extract the dataset and NILM training artifacts into the repository.

- dataset/archive.zip            -> dataset/ (REFIT CSVs); the REFIT seed revision reads
                                    dataset/CLEAN_House2.csv (mounted at /data in the api container)
- dataset/training/artifacts.zip -> dataset/training/artifacts/
                                      nilm_pipeline.pt2   architecture + weights (torch.export)
                                      nilm_pipeline.pt    weights + config (torch.load weights_only=True)
                                      nilm_pipeline.json  metadata (appliances, thresholds, I/O spec, test results)
                                      inference.py, model/  architecture source + NILMModel.predict
                                    dataset/training/data/refit_house2_windows{,_L256,_L512}.npz
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
