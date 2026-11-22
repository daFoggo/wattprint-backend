"""Standalone dual-branch NILM architecture for 15 s, 256-step windows.

The detector estimates appliance ON probabilities. The regressor estimates
conditional ON power. They have separate temporal-convolution backbones so
either branch can be ablated or replaced independently.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import torch
from torch import nn
from torch.nn import functional as F


LABELS = ("Fridge", "WashMach", "Dishwash", "Microwave", "Toaster", "Kettle")


@dataclass(frozen=True)
class ModelConfig:
    labels: tuple[str, ...] = LABELS
    channels: int = 48
    kernel: int = 5
    dilations: tuple[int, ...] = (1, 2, 4, 8, 16, 32)
    dropout: float = 0.1
    aggregate_scale_w: float = 1000.0

    def to_dict(self) -> dict:
        return asdict(self)


def features(x: torch.Tensor, aggregate_scale_w: float = 1000.0) -> torch.Tensor:
    """Input (B,9,256): aggregate W and eight calendar features -> (B,11,256)."""
    if x.ndim != 3 or x.shape[1] != 9 or x.shape[2] != 256:
        raise ValueError(f"expected (B,9,256), got {tuple(x.shape)}")
    agg = x[:, :1] / aggregate_scale_w
    delta = torch.diff(agg, dim=-1, prepend=agg[..., :1])
    centered = agg - agg.median(dim=-1, keepdim=True).values
    return torch.cat((agg, delta, centered, x[:, 1:]), dim=1)


class ResidualTCNBlock(nn.Module):
    def __init__(self, channels: int, kernel: int, dilation: int, dropout: float):
        super().__init__()
        self.main = nn.Sequential(
            nn.Conv1d(channels, channels, kernel, padding=dilation * (kernel // 2), dilation=dilation),
            nn.GroupNorm(4, channels),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Conv1d(channels, channels, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.gelu(x + self.main(x))


class TemporalBackbone(nn.Module):
    def __init__(self, config: ModelConfig):
        super().__init__()
        self.projection = nn.Conv1d(11, config.channels, 1)
        self.blocks = nn.Sequential(*[
            ResidualTCNBlock(config.channels, config.kernel, d, config.dropout)
            for d in config.dilations
        ])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.blocks(self.projection(x))


class TCNDetector(nn.Module):
    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config
        self.backbone = TemporalBackbone(config)
        self.head = nn.Conv1d(config.channels, len(config.labels), 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.backbone(features(x, self.config.aggregate_scale_w)))


class TCNRegressor(nn.Module):
    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config
        self.backbone = TemporalBackbone(config)
        self.head = nn.Conv1d(config.channels, len(config.labels), 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.softplus(self.head(self.backbone(features(x, self.config.aggregate_scale_w))))
