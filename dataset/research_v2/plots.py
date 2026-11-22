"""Paired unseen-House-3 traces for frozen reference and both TCN recipes."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ON_W = {"Fridge": 50, "WashMach": 20, "Dishwash": 10,
        "Microwave": 200, "Toaster": 200, "Kettle": 1000}


def read(path):
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def make_plot(window: int, title: str, output: Path):
    files = {
        "reference (source 2)": ROOT / "dataset/research_v1/baseline/source2_target3.npz",
        "TCN v2.0 LOHO": HERE / "predictions/loho_target3.npz",
        "TCN v2.1 LOHO": HERE / "v2_1/predictions/loho_target3.npz",
    }
    data = {name: read(path) for name, path in files.items()}
    first = next(iter(data.values()))
    for z in data.values():
        for key in ("timestamp", "aggregate_w", "y_true_w", "labels"):
            if not np.array_equal(z[key], first[key]):
                raise ValueError(f"unpaired {key} in trace inputs")
    labels = first["labels"].astype(str).tolist()
    sl = slice(window * 256, (window + 1) * 256)
    x = np.arange(256) * 15 / 60
    actual_on = sum(first["y_true_w"][sl, c] >= ON_W[label] for c, label in enumerate(labels))
    fig, axes = plt.subplots(len(labels) + 1, 1, figsize=(16, 2.1 * (len(labels) + 1)), sharex=True)
    axes[0].plot(x, first["aggregate_w"][sl], color="black", linewidth=1.3)
    axes[0].set_ylabel("Aggregate W")
    axes[0].set_title(f"{title} | unseen House 3 | {first['timestamp'][sl][0]} | concurrent ON max {actual_on.max()}")
    for c, label in enumerate(labels):
        ax = axes[c + 1]
        ax.plot(x, first["y_true_w"][sl, c], label="truth", color="black", linewidth=1.4)
        for name, z in data.items():
            ax.plot(x, z["y_pred_w"][sl, c], label=name, linewidth=1.0, alpha=0.85)
        ax.set_ylabel(f"{label} W")
        ax.grid(alpha=0.2)
    axes[1].legend(loc="upper right", ncol=2, fontsize=8)
    axes[-1].set_xlabel("Minutes from window start")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=130)
    plt.close(fig)


def main():
    make_plot(120, "Representative reference window", HERE / "figures/house3_representative.png")
    make_plot(65, "High-error reference window", HERE / "figures/house3_high_error.png")
    print(HERE / "figures")


if __name__ == "__main__":
    main()
