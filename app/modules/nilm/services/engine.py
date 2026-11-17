import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch

from app.ml.nilm.GRUDetector import GRUConfig, GRUDetector
from app.ml.nilm.NILMFormerRegressor import NILMFormerConfig, NILMFormerRegressor

BATCH = 45  # windows per forward pass: ~1.3 s on 4 CPU threads, peak RSS stays under 1 GB


@dataclass(frozen=True)
class Bundle:
    """A `wattprint-nilm/2` bundle: GRU detector + NILMFormer regressor ensemble."""

    labels: list[str]
    window: int
    sha256: str
    detectors: list[GRUDetector]
    regressors: list[NILMFormerRegressor]
    scales: torch.Tensor  # (M, C) watts per regressor unit
    tau_w: float
    gate: str
    event_thresholds: torch.Tensor

    @torch.no_grad()
    def predict(self, x: np.ndarray) -> np.ndarray:
        """(B, 9, window) -> appliance W (B, C, window); same maths as dataset/.../inference.py."""
        out = [self._predict(torch.as_tensor(x[i : i + BATCH])) for i in range(0, len(x), BATCH)]
        return np.concatenate(out) if out else np.empty((0, len(self.labels), self.window))

    def _predict(self, xb: torch.Tensor) -> np.ndarray:
        agg_kw = xb[:, :1] / 1000.0
        z = torch.cat([agg_kw, torch.diff(agg_kw, dim=-1, prepend=agg_kw[..., :1]), xb[:, 1:]], 1)
        xr = torch.cat([xb[:, :1] / self.tau_w, xb[:, 1:]], dim=1)
        p_on = torch.stack([torch.sigmoid(d(z)) for d in self.detectors]).mean(0)
        power = torch.stack(
            [r(xr) * s[None, :, None] for r, s in zip(self.regressors, self.scales, strict=True)]
        )
        power = power.median(0).values.clamp(min=0)
        if self.gate == "soft":
            watts = p_on * power
        else:
            watts = power * (p_on >= self.event_thresholds[None, :, None])
        return watts.numpy()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@lru_cache(maxsize=16)
def load(path: Path) -> Bundle:
    """Load a bundle once per path (each is ~10 MB of weights, ~60 MB in memory)."""
    b = torch.load(path, map_location="cpu", weights_only=True)
    if b.get("format") != "wattprint-nilm/2":
        raise ValueError(f"{path}: unsupported bundle format {b.get('format')!r}")
    detectors, regressors, scales = [], [], []
    for m in b["members"]:
        d = GRUDetector(GRUConfig(**m["detector_config"]))
        d.load_state_dict(m["detector_state"])
        r = NILMFormerRegressor(NILMFormerConfig(**m["regressor_config"]))
        r.load_state_dict(m["regressor_state"])
        detectors.append(d.eval())
        regressors.append(r.eval())
        scales.append(torch.tensor(m["scale_w"], dtype=torch.float32))
    return Bundle(
        labels=list(b["labels"]),
        window=int(b["window"]),
        sha256=_sha256(path),
        detectors=detectors,
        regressors=regressors,
        scales=torch.stack(scales),
        tau_w=float(b["tau_w"]),
        gate=b["gate"],
        event_thresholds=torch.tensor(b["event_thresholds"]),
    )
