"""Create the NILM training windows (128, 256 and 512 steps of 15 s) from the preprocessed CSVs."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    subprocess.run([sys.executable, str(ROOT / "dataset" / "training" / "data.py"), "--window", "128", "256", "512"],
                   cwd=ROOT, check=True)
