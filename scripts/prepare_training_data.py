"""Create normalized NILMFormer windows from the preprocessed CSV sources."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    subprocess.run([sys.executable, str(ROOT / "dataset" / "training" / "data.py")],
                   cwd=ROOT, check=True)
