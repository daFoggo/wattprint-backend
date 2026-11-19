"""Execute the EDA notebook to produce clipped, preprocessed REFIT CSVs."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "dataset" / "scripts" / "eda.ipynb"

if __name__ == "__main__":
    subprocess.run([
        sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook",
        "--execute", str(NOTEBOOK), "--output", "eda.executed.ipynb",
        "--output-dir", str(NOTEBOOK.parent),
    ], cwd=ROOT, check=True)
