"""Create the NILM training windows (128, 256 and 512 steps of 15 s) from the preprocessed CSVs."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    script = ROOT / "dataset" / "training" / "data.py"
    subprocess.run(
        [sys.executable, str(script), "--window", "128", "256", "512"], cwd=ROOT, check=True
    )
