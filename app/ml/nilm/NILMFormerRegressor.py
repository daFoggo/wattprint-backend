from dataclasses import dataclass, field

import torch
import torch.nn as nn

from .DilatedResidualBlock import DilatedResidualBlock
from .Transformer import EncoderLayer


@dataclass
class NILMFormerConfig:
    c_in: int = 1
    c_out: int = 9
    c_embedding: int = 8

    kernel_size: int = 3
    kernel_size_head: int = 3
    dilations: list[int] = field(default_factory=lambda: [1, 2, 4, 8])
    conv_bias: bool = True

    use_efficient_attention: bool = False
    n_encoder_layers: int = 3
    d_model: int = 96
    dp_rate: float = 0.2
    pffn_ratio: int = 4
    n_head: int = 8
    norm_eps: float = 1e-5

class NILMFormerRegressor(nn.Module):
    def __init__(self, NFConfig: NILMFormerConfig):
        super().__init__()
        self.config = NFConfig
        d_model = self.config.d_model
        assert d_model % 4 == 0

        self.TokenStats = nn.Linear(2, d_model)
        self.ProjStats2 = nn.Linear(d_model, 2)

        self.EmbedBlock = DilatedResidualBlock(
            c_in=self.config.c_in,
            c_out=3 * d_model // 4,
            kernel_size=self.config.kernel_size,
            dilated_list=self.config.dilations,
            bias=self.config.conv_bias,
        )

        self.TimeRPE = nn.Conv1d(
            in_channels=self.config.c_embedding,
            out_channels=d_model // 4,
            kernel_size=1,
        )

        self.EncoderBlock = nn.Sequential(
            *[EncoderLayer(self.config) for _ in range(self.config.n_encoder_layers)],
            nn.LayerNorm(d_model, eps=self.config.norm_eps)
        )

        self.DownstreamTaskHead = nn.Conv1d(
            in_channels=d_model,
            out_channels=self.config.c_out,
            kernel_size=self.config.kernel_size_head,
            padding=self.config.kernel_size_head // 2,
            padding_mode="replicate"
        )

        self.initialize_weights()

    def initialize_weights(self):
        self.apply(self._init_weights)

    @staticmethod
    def _init_weights(m):
        if isinstance(m, nn.Linear):
            nn.init.xavier_uniform_(m.weight)
            if m.bias is not None:
                nn.init.zeros_(m.bias)
        elif isinstance(m, nn.LayerNorm):
            nn.init.ones_(m.weight)
            nn.init.zeros_(m.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x                               # (B, 1+e, L): batch, 1 raw + e feature vectors, length
        x_raw = x[:, :1, :]                 # (B, 1, L)
        x_features = x[:, 1:, :]            # (B, e, L)

        """
        Token Stats: x_raw -> Mean & STD
        - Mean & STD -> Linear(2 -> d_model) -> Token Stats
        - x_raw + (Mean & STD) -> x_z_normalized
        """
        x_mean = x_raw.mean(dim=-1, keepdim=True).detach()              # (B, 1, 1)
        x_std = torch.sqrt(                                             # (B, 1, 1)
            x_raw.var(dim=-1, keepdim=True, unbiased=False) + 1e-6
        ).detach()

        x_z_normalized = (x_raw - x_mean) / x_std                                                   # (B, 1, L)
        token_stats = self.TokenStats(torch.cat([x_mean, x_std], dim=1).transpose(1, 2))            # (B, 1, d_model)

        """
        - Embedding Block: x_z_normalized -> DilatedResBlock
        - TimeRPE: x_features -> Conv1d
        """
        x_embed = self.EmbedBlock(x_z_normalized)                           # (B, 3*d_model//4, L)
        x_timerpe = self.TimeRPE(x_features)                                # (B, d_model//4, L)
        x_tokens = torch.cat([x_embed, x_timerpe], dim=1)                   # (B, d_model, L)
        x_tokens = x_tokens.transpose(1, 2)                                 # (B, L, d_model)

        x_tokens = torch.cat([x_tokens, token_stats], dim=1)                # (B, L+1, d_model)

        # Transformer Encoder
        x_encoded = self.EncoderBlock(x_tokens)               # (B, L+1, d_model)
        x_encoded = x_encoded[:, :-1, :]                      # (B, L, d_model)

        # Prediction Head
        x_encoded = x_encoded.transpose(1, 2)                 # (B, d_model, L)
        x_pred = self.DownstreamTaskHead(x_encoded)            # (B, c_out, L)

        # Reverse Instance Normalization
        stats_out = self.ProjStats2(token_stats)               # (B, 1, 2)
        out_mean = stats_out[:, :, 0:1]                        # (B, 1, 1)
        out_std = stats_out[:, :, 1:2]                         # (B, 1, 1)

        x_pred = x_pred * out_std + out_mean                   # (B, c_out, L)
        return x_pred
