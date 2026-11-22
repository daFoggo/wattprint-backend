"""Standalone inference for wattprint-nilm-tcn/1 research checkpoints."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import torch

try:
    from .architecture import ModelConfig, TCNDetector, TCNRegressor
except ImportError:
    from architecture import ModelConfig, TCNDetector, TCNRegressor


class Bundle:
    def __init__(self, path: str | Path, device: str = "cpu"):
        self.path = Path(path)
        payload = torch.load(self.path, map_location=device, weights_only=True)
        if payload.get("format") != "wattprint-nilm-tcn/1":
            raise ValueError(f"unsupported checkpoint format {payload.get('format')!r}")
        config = ModelConfig(**payload["config"])
        self.labels = list(payload["labels"])
        self.sample_seconds = int(payload["sample_seconds"])
        self.window = int(payload["window"])
        self.event_thresholds = np.asarray(payload["event_thresholds"], dtype=np.float32)
        self.on_threshold_w = np.asarray(payload["on_threshold_w"], dtype=np.float32)
        self.power_scale_w = np.asarray(payload["power_scale_w"], dtype=np.float32)
        self.energy_calibration = np.asarray(payload.get("energy_calibration", [1.0] * len(self.labels)), dtype=np.float32)
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.device = torch.device(device)
        self.detectors = []
        self.regressors = []
        for member in payload["members"]:
            detector = TCNDetector(config).to(self.device).eval()
            regressor = TCNRegressor(config).to(self.device).eval()
            detector.load_state_dict(member["detector_state"])
            regressor.load_state_dict(member["regressor_state"])
            self.detectors.append(detector)
            self.regressors.append(regressor)

    @torch.no_grad()
    def predict(self, x: np.ndarray, batch_size: int = 64) -> tuple[np.ndarray, np.ndarray]:
        """Return (ON probabilities, appliance watts), each (B,C,256)."""
        if x.ndim != 3 or x.shape[1:] != (9, self.window):
            raise ValueError(f"expected (B,9,{self.window}), got {x.shape}")
        if not np.isfinite(x).all():
            raise ValueError("input contains nonfinite values")
        probabilities, powers = [], []
        scales = torch.as_tensor(self.power_scale_w, device=self.device)[None, :, None]
        calibration = torch.as_tensor(self.energy_calibration, device=self.device)[None, :, None]
        for start in range(0, len(x), batch_size):
            xb = torch.as_tensor(x[start:start + batch_size], dtype=torch.float32, device=self.device)
            p = torch.stack([torch.sigmoid(det(xb)) for det in self.detectors]).mean(0)
            a = torch.stack([reg(xb) * scales for reg in self.regressors]).mean(0)
            probabilities.append(p.cpu().numpy())
            powers.append(((p * a) * calibration).clamp_min(0).cpu().numpy())
        shape = (0, len(self.labels), self.window)
        return (np.concatenate(probabilities) if probabilities else np.empty(shape, np.float32),
                np.concatenate(powers) if powers else np.empty(shape, np.float32))


if __name__ == "__main__":
    import argparse
    try:
        from .preprocess import load_house
    except ImportError:
        from preprocess import load_house

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--house", type=int, required=True)
    parser.add_argument("--window-index", type=int, default=0)
    args = parser.parse_args()
    x, _, starts, _ = load_house(args.csv, args.house)
    bundle = Bundle(args.checkpoint)
    p, watts = bundle.predict(x[args.window_index:args.window_index + 1])
    print({"time": str(starts[args.window_index]), "labels": bundle.labels,
           "shape": watts.shape, "mean_w": watts.mean(-1).round(2).tolist(),
           "mean_on_probability": p.mean(-1).round(3).tolist()})
