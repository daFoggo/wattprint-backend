"""Validate v2.1 weights, fold boundaries, paired rows, standalone inference."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

try:
    from .inference import Bundle
    from .preprocess import time_features
except ImportError:
    from inference import Bundle
    from preprocess import time_features

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    torch.set_num_threads(4)
    manifest = json.loads((HERE / "v2_1/manifest.json").read_text())
    results = {}
    for house in (2, 3, 5, 6):
        info = manifest["folds"][str(house)]
        training = info["training"]
        assert house not in training["outer_source_houses"]
        assert training["inner_validation_house"] in training["outer_source_houses"]
        checkpoint = HERE / "v2_1" / info["checkpoint"]
        digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        assert digest == info["sha256"]
        bundle = Bundle(checkpoint)
        with np.load(HERE / "v2_1" / info["prediction"], allow_pickle=False) as z:
            data = {k: z[k] for k in z.files}
        base = HERE.parent / "research_v1/baseline" / f"source{5 if house == 2 else 2}_target{house}.npz"
        with np.load(base, allow_pickle=False) as z:
            assert np.array_equal(data["timestamp"], z["timestamp"])
            assert np.array_equal(data["aggregate_w"], z["aggregate_w"])
            assert np.array_equal(data["selected_window_indices"], z["selected_window_indices"])
        assert np.isfinite(data["y_pred_w"]).all() and np.isfinite(data["p_on"]).all()
        assert np.all((data["p_on"] >= 0) & (data["p_on"] <= 1))
        if house == 6:
            assert "Fridge" not in data["labels"] and "Freezer" not in data["labels"]
        x = np.concatenate((data["aggregate_w"][:256].reshape(1, 1, 256),
                            time_features(pd.DatetimeIndex(data["timestamp"][:256])).reshape(1, 8, 256)), axis=1).astype(np.float32)
        p, watts = bundle.predict(x)
        cols = [bundle.labels.index(str(label)) for label in data["labels"]]
        p_diff = float(np.max(np.abs(p[:, cols].transpose(0, 2, 1).reshape(256, -1) - data["p_on"][:256])))
        w_diff = float(np.max(np.abs(watts[:, cols].transpose(0, 2, 1).reshape(256, -1) - data["y_pred_w"][:256])))
        assert p_diff < 1e-5 and w_diff < 1e-3
        results[str(house)] = {"checkpoint_sha256": digest, "sample_count": len(data["timestamp"]),
                               "labels": data["labels"].astype(str).tolist(),
                               "standalone_probability_max_abs_difference": p_diff,
                               "standalone_watt_max_abs_difference": w_diff}
    output = {"status": "passed", "folds": results,
              "checks": ["outer train excludes target house", "checkpoint hashes",
                         "baseline target row alignment", "finite predictions", "House6 label scope",
                         "standalone inference on a real 256-sample window"]}
    (HERE / "v2_1/verification.json").write_text(json.dumps(output, indent=2) + "\n")
    print("PASS: four LOHO checkpoints, pairing, and standalone inference")


if __name__ == "__main__":
    main()
