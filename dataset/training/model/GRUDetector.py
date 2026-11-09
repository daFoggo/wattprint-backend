from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn

@dataclass
class GRUConfig:
    c_in: int = 1
    c_out: int = 9

    kernel_size: int = 5
    conv_channels: int = 64
    hidden: int = 64
    num_layers: int = 2
    dropout: float = 0.1

class GRUDetector(nn.Module):
    def __init__(self, GRUconfig: GRUConfig):
        super().__init__()
        self.config = GRUconfig

        self.EmbedBlock = nn.Sequential(
            nn.Conv1d(
                in_channels=self.config.c_in,
                out_channels=self.config.conv_channels,
                kernel_size=self.config.kernel_size,
                padding=self.config.kernel_size // 2,
            ),
            nn.ReLU(),
        )

        self.EncoderBlock = nn.GRU(
            input_size=self.config.conv_channels,
            hidden_size=self.config.hidden,
            num_layers=self.config.num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=self.config.dropout,
        )

        self.DownstreamTaskHead = nn.Linear(
            in_features=2 * self.config.hidden,
            out_features=self.config.c_out,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x                                               # (B, c_in, L)

        # Embedding Block: local edge / shape features
        x_embed = self.EmbedBlock(x)                        # (B, conv_channels, L)
        x_embed = x_embed.transpose(1, 2)                   # (B, L, conv_channels)

        # Bidirectional GRU Encoder
        x_encoded, _ = self.EncoderBlock(x_embed)           # (B, L, 2*hidden)

        # Prediction Head: per-timestep ON/OFF logits
        x_pred = self.DownstreamTaskHead(x_encoded)         # (B, L, c_out)
        x_pred = x_pred.transpose(1, 2)                     # (B, c_out, L)
        return x_pred
