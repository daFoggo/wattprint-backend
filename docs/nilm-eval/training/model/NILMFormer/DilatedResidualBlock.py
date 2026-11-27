# Copyright © 2025 EDF; Apache-2.0.
# Điều chỉnh theo quy ước TwoStageNILMFormer của dự án; xem README.md.

import torch
import torch.nn as nn


class ResidualBlock(nn.Module):
    def __init__(
        self,
        c_in: int,
        c_out: int,
        k: int = 8,
        dilation: int = 1,
        stride: int = 1,
        bias: bool = True,
    ):
        super().__init__()

        self.block = nn.Sequential(
            nn.Conv1d(
                in_channels=c_in,
                out_channels=c_out,
                kernel_size=k,
                dilation=dilation,
                stride=stride,
                bias=bias,
                padding="same",
            ),
            nn.GELU(),
            nn.BatchNorm1d(c_out),
        )

        if c_in > 1 and c_in != c_out:
            self.match_residual = False
            self.conv = nn.Conv1d(in_channels=c_in, out_channels=c_out, kernel_size=1)
        else:
            self.match_residual = True

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x  # (B, c_in, L)
        # Tích chập giữ độ dài L; đổi c_in thành c_out trước khi cộng nhánh dư.
        out = self.block(x)  # (B, c_out, L)
        # Nhánh dư dùng Conv1d 1×1 khi cần đổi số kênh; c_in=1 có thể broadcast.
        if not self.match_residual:
            return torch.add(self.conv(x), out)  # (B, c_out, L)
        else:
            return torch.add(x, out)  # (B, c_out, L)


class DilatedResidualBlock(nn.Module):
    def __init__(
        self,
        c_in: int = 32,
        c_out: int = 32,
        kernel_size: int = 8,
        dilated_list: tuple[int, ...] | list[int] = (1, 2, 4, 8),
        bias: bool = True,
    ):
        super().__init__()
        # Giữ khả năng cấu hình dilation của bản gốc, kể cả dilation lặp.
        # Tên lớp mặc định tuân theo quy ước của mô hình hai giai đoạn.
        self.block_names: list[str] = []
        for index, dilation in enumerate(dilated_list):
            name = f"dilated_{dilation}"
            if name in self.block_names:
                name = f"{name}_{index}"
            self.add_module(
                name,
                ResidualBlock(
                    c_in if index == 0 else c_out,
                    c_out,
                    k=kernel_size,
                    dilation=dilation,
                    bias=bias,
                ),
            )
            self.block_names.append(name)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # (B, c_in, L) -> (B, c_out, L)
        for name in self.block_names:
            x = getattr(self, name)(x)
        return x
