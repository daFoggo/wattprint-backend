"""Standalone CPU-capable inference for this directory's wattprint-nilm/2 bundles."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

try:  # package import: dataset.research_v1.model.inference
    from .architecture.GRUDetector import GRUConfig, GRUDetector
    from .architecture.NILMFormerRegressor import NILMFormerConfig, NILMFormerRegressor
except ImportError:  # direct script execution from this directory
    from architecture.GRUDetector import GRUConfig, GRUDetector
    from architecture.NILMFormerRegressor import NILMFormerConfig, NILMFormerRegressor

BATCH = 16


@dataclass
class Bundle:
    labels: list[str]
    window: int
    sha256: str
    detectors: list[GRUDetector]
    regressors: list[NILMFormerRegressor]
    scales: torch.Tensor
    tau_w: float
    gate: str
    event_thresholds: torch.Tensor

    @torch.no_grad()
    def predict(self, x: np.ndarray) -> np.ndarray:
        """Map (B, 9, window) input to (B, labels, window) appliance watts."""
        if x.ndim != 3 or x.shape[1:] != (9, self.window):
            raise ValueError(f"expected (B, 9, {self.window}) float input, got {x.shape}")
        outputs = []
        device = next(self.detectors[0].parameters()).device
        for start in range(0, len(x), BATCH):
            xb = torch.as_tensor(x[start:start + BATCH], dtype=torch.float32, device=device)
            aggregate_kw = xb[:, :1] / 1000.0
            detector_x = torch.cat([
                aggregate_kw,
                torch.diff(aggregate_kw, dim=-1, prepend=aggregate_kw[..., :1]),
                xb[:, 1:],
            ], dim=1)
            regressor_x = torch.cat([xb[:, :1] / self.tau_w, xb[:, 1:]], dim=1)
            p_on = torch.stack([torch.sigmoid(d(detector_x)) for d in self.detectors]).mean(0)
            power = torch.stack([
                r(regressor_x) * scale[None, :, None]
                for r, scale in zip(self.regressors, self.scales, strict=True)
            ]).median(0).values.clamp(min=0)
            if self.gate == "soft":
                watts = p_on * power
            else:
                watts = power * (p_on >= self.event_thresholds[None, :, None])
            outputs.append(watts.cpu().numpy())
        return np.concatenate(outputs) if outputs else np.empty((0, len(self.labels), self.window), np.float32)


def load(path: str | Path, *, device: str = "cpu") -> Bundle:
    path = Path(path)
    payload = torch.load(path, map_location=device, weights_only=True)
    if payload.get("format") != "wattprint-nilm/2":
        raise ValueError(f"unsupported model format: {payload.get('format')!r}")
    detectors, regressors, scales = [], [], []
    for member in payload["members"]:
        detector = GRUDetector(GRUConfig(**member["detector_config"]))
        detector.load_state_dict(member["detector_state"])
        regressor = NILMFormerRegressor(NILMFormerConfig(**member["regressor_config"]))
        regressor.load_state_dict(member["regressor_state"])
        detectors.append(detector.to(device).eval())
        regressors.append(regressor.to(device).eval())
        scales.append(torch.tensor(member["scale_w"], dtype=torch.float32, device=device))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return Bundle(
        labels=list(payload["labels"]), window=int(payload["window"]), sha256=digest,
        detectors=detectors, regressors=regressors, scales=torch.stack(scales),
        tau_w=float(payload["tau_w"]), gate=payload["gate"],
        event_thresholds=torch.tensor(payload["event_thresholds"], dtype=torch.float32, device=device),
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    model = load(args.checkpoint, device=args.device)
    prediction = model.predict(np.zeros((1, 9, model.window), dtype=np.float32))
    print({"labels": model.labels, "shape": prediction.shape, "sha256": model.sha256})
