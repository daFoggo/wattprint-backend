"""Standalone source-group calibrated wrapper around frozen v1 bundles."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

try:
    from dataset.research_v1.model.inference import load as load_source
except ImportError as exc:
    raise ImportError("the delivered dataset/research_v1/model architecture is required") from exc


class CalibratedBundle:
    def __init__(self, directory: str | Path, source_house: int):
        root = Path(directory)
        metadata = json.loads((root / "metadata.json").read_text())
        entry = metadata["sources"][str(source_house)]
        self.source_house = source_house
        self.model = load_source(root / entry["checkpoint"])
        self.labels = self.model.labels
        self.event_thresholds = np.asarray(entry["event_thresholds"], dtype=np.float32)
        self.power_scale = np.asarray(entry["power_scale"], dtype=np.float32)

    @torch.no_grad()
    def predict(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return source detector probability and calibrated appliance watts."""
        base_watts = self.model.predict(x)
        probabilities = []
        for start in range(0, len(x), 16):
            xb = torch.as_tensor(x[start:start + 16], dtype=torch.float32)
            aggregate_kw = xb[:, :1] / 1000.0
            detector_x = torch.cat((aggregate_kw,
                torch.diff(aggregate_kw, dim=-1, prepend=aggregate_kw[..., :1]), xb[:, 1:]), dim=1)
            probabilities.append(torch.stack([
                torch.sigmoid(det(detector_x)) for det in self.model.detectors
            ]).mean(0).numpy())
        shape = (0, len(self.labels), self.model.window)
        p = np.concatenate(probabilities) if probabilities else np.empty(shape, np.float32)
        return p, base_watts * self.power_scale[None, :, None]
