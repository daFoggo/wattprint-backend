import torch
import torch.nn as nn


class ResidualBlock(nn.Module):
    def __init__(self, c_in: int, c_out: int, k: int=8, dilation: int=1, stride: int=1, bias: bool=True):
        super().__init__()

        self.block = nn.Sequential(
            nn.Conv1d(
                in_channels=c_in, out_channels=c_out, kernel_size=k,
                dilation=dilation, stride=stride, bias=bias, padding="same"
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
        x = x                                           # (B, c_in, L)
        out = self.block(x)                             # (B, c_out, L)
        if not self.match_residual:
            return torch.add(self.conv(x), out)         # (B, c_out, L)
        else:
            return torch.add(x, out)                    # (B, c_out, L)

class DilatedResidualBlock(nn.Module):
    # shortcut: dilated_list is ignored (dilations hardcoded below); wire it up or drop it
    def __init__(self, c_in=32, c_out=32, kernel_size=8, dilated_list=(1, 2, 4, 8), bias: bool = True):
        super().__init__()

        self.dilated_1 = ResidualBlock(c_in, c_out, k=kernel_size, dilation=1, bias=bias)
        self.dilated_2 = ResidualBlock(c_out, c_out, k=kernel_size, dilation=2, bias=bias)
        self.dilated_4 = ResidualBlock(c_out, c_out, k=kernel_size, dilation=4, bias=bias)
        self.dilated_8 = ResidualBlock(c_out, c_out, k=kernel_size, dilation=8, bias=bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x                                           # (B, c_in, L)
        x = self.dilated_1(x)                           # (B, c_out, L)
        x = self.dilated_2(x)                           # (B, c_out, L)
        x = self.dilated_4(x)                           # (B, c_out, L)
        x = self.dilated_8(x)                           # (B, c_out, L)
        return x
