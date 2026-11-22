"""Standalone equal-source inference for v2_source_blend."""
from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    from .inference import Bundle, load
except ImportError:
    from inference import Bundle, load


class SourceBlend:
    def __init__(self, source2: Bundle, source5: Bundle):
        self.sources = (source2, source5)
        self.common_labels = [name for name in source2.labels if name in source5.labels]

    def predict(self, x: np.ndarray, labels: list[str] | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Return equal-mean watts and normalized-threshold scores for requested labels.

        ON is predicted when normalized score >= 1.0, equivalently returned `p_on` >= 0.5.
        The second return is a monotone score for thresholded decisions, not a calibrated posterior.
        """
        labels = labels or self.common_labels
        if any(label not in self.common_labels for label in labels):
            raise ValueError(f"requested labels must be present in both sources: {labels}")
        pred_parts, score_parts = [], []
        for source in self.sources:
            power = source.predict(x)
            source_cols = [source.labels.index(label) for label in labels]
            thresholds = source.event_thresholds[source_cols].cpu().numpy()
            # The standalone Bundle returns appliance watts; detector probability is not public,
            # so recover p_on with the same supported modules and input transform.
            import torch

            device = next(source.detectors[0].parameters()).device
            probabilities = []
            with torch.no_grad():
                for i in range(0, len(x), 16):
                    xb = torch.as_tensor(x[i:i + 16], dtype=torch.float32, device=device)
                    aggregate_kw = xb[:, :1] / 1000.0
                    detector_x = torch.cat([
                        aggregate_kw,
                        torch.diff(aggregate_kw, dim=-1, prepend=aggregate_kw[..., :1]),
                        xb[:, 1:],
                    ], dim=1)
                    p = torch.stack([torch.sigmoid(d(detector_x)) for d in source.detectors]).mean(0)
                    probabilities.append(p.cpu().numpy())
            p_on = np.concatenate(probabilities, axis=0)[:, source_cols]
            pred_parts.append(power[:, source_cols])
            score_parts.append(p_on / thresholds[None, :, None])
        watts = 0.5 * (pred_parts[0] + pred_parts[1])
        score = 0.5 * (score_parts[0] + score_parts[1])
        return watts, score / (1.0 + score)


def load_blend(path: str | Path) -> SourceBlend:
    root = Path(path)
    return SourceBlend(load(root / "weights/house2.pt"), load(root / "weights/house5.pt"))
