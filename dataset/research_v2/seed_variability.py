"""Score individual v2.1 seed members on the frozen LOHO target windows."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dataset.research_v2.architecture import ModelConfig  # noqa: E402
from dataset.research_v2.preprocess import time_features  # noqa: E402
from dataset.research_v2.run_v21 import ON_W, predict_members, f1  # noqa: E402

HERE = Path(__file__).resolve().parent


def main():
    torch.set_num_threads(4)
    rows = []
    for house in (2, 3, 5, 6):
        path = HERE / "v2_1" / "weights" / f"loho_target{house}_v2.1.0.pt"
        bundle = torch.load(path, map_location="cpu", weights_only=True)
        config = ModelConfig(**bundle["config"])
        with np.load(HERE / "v2_1" / "predictions" / f"loho_target{house}.npz", allow_pickle=False) as z:
            data = {k: z[k] for k in z.files}
        n = len(data["selected_window_indices"])
        aggregate = data["aggregate_w"].reshape(n, 1, 256)
        calendar = time_features(pd.DatetimeIndex(data["timestamp"])).reshape(8, n, 256).transpose(1, 0, 2)
        x = np.concatenate((aggregate, calendar), axis=1).astype(np.float32)
        labels = data["labels"].astype(str).tolist()
        cols = [bundle["labels"].index(label) for label in labels]
        calibration = np.asarray(bundle["energy_calibration"], dtype=np.float32)[cols]
        thresholds = np.asarray(bundle["event_thresholds"], dtype=np.float32)[cols]
        for member in bundle["members"]:
            p, watts = predict_members([member], x, config, torch.device("cpu"))
            p = p[:, cols].transpose(0, 2, 1).reshape(-1, len(cols))
            watts = (watts[:, cols] * calibration[None, :, None]).transpose(0, 2, 1).reshape(-1, len(cols))
            for c, label in enumerate(labels):
                actual = data["y_true_w"][:, c]
                on = actual >= ON_W[cols[c]]
                tkwh, pkwh = actual.sum() * 15 / 3.6e6, watts[:, c].sum() * 15 / 3.6e6
                rows.append({"house": house, "seed": int(member["seed"]), "device": label,
                             "f1_on_off": f1(on, p[:, c] >= thresholds[c]),
                             "true_kwh": float(tkwh), "predicted_kwh": float(pkwh),
                             "absolute_error_kwh": float(abs(pkwh - tkwh))})
        print(f"scored two seeds for held-out house {house}", flush=True)
    out = HERE / "v2_1" / "seed_metrics.csv"
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(), writer.writerows(rows)
    print(out)


if __name__ == "__main__":
    main()
