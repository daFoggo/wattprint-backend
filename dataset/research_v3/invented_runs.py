"""Research v3, step 5: what the detector sees when it invents a device run (no retraining).

Reads overcount.py's saved test predictions. Each run the detector calls (a contiguous ON stretch in
a window) is "real" when it overlaps the plug's ON, else "invented". At each run's start: the
aggregate's step (mean of the 4 steps after minus the 4 before), whether another metered device
switched ON within 30 s, and the aggregate's level.

    uv run python dataset/research_v3/invented_runs.py --house 2 --seed 11 --device Fridge
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import train_house as th  # noqa: E402

SIDE = 4  # steps (1 min) each side of a start
NEAR = 2  # steps (30 s) for another device's switch-on


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    edges = np.diff(np.r_[0, mask.astype(np.int8), 0])
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True))


def main(house: int, seed: int, device: str) -> None:
    d = np.load(HERE / f"overcount_house{house}_seed{seed}.npz")
    labels = list(d["labels"])
    i = labels.index(device)
    on = (
        d["y"].astype(np.float32) >= np.array([th.ON_THRESHOLD_W[k] for k in labels])[None, :, None]
    )
    called = d["p_on"][:, i].astype(np.float32) >= d["cuts"][i]
    agg = d["x"][:, 0]
    others = np.delete(on, i, axis=1)
    rows = {"real": [], "invented": []}
    for w in range(len(agg)):
        for s, e in runs(called[w]):
            if s < SIDE or s + SIDE > agg.shape[1]:
                continue
            kind = "real" if on[w, i, s:e].any() else "invented"
            step = agg[w, s : s + SIDE].mean() - agg[w, s - SIDE : s].mean()
            lo, hi = max(s - NEAR, 1), min(s + NEAR + 1, agg.shape[1])
            switched = bool((others[w, :, lo:hi] & ~others[w, :, lo - 1 : hi - 1]).any())
            rows[kind].append((step, switched, agg[w, s : s + SIDE].mean(), e - s))
    for kind, r in rows.items():
        if not r:
            print(kind, "none")
            continue
        a = np.array(r, dtype=np.float64)
        q = np.percentile(a[:, 0], [10, 25, 50, 75, 90]).round(0)
        print(
            f"{device} {kind:8s} runs {len(a):5d}  step W p10/25/50/75/90 {q}  "
            f"step >= 50 W {np.mean(a[:, 0] >= 50):.2f}  another device on {a[:, 1].mean():.2f}  "
            f"agg W median {np.median(a[:, 2]):.0f}  length min median {np.median(a[:, 3]) / 4:.1f}"
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", type=int, required=True)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--device", default="Fridge")
    a = ap.parse_args()
    main(a.house, a.seed, a.device)
