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


TRAINED_DILATIONS = (1, 2, 4, 8)  # Trọng số đã lưu tương ứng đúng bốn khối này.


class DilatedResidualBlock(nn.Module):
    def __init__(self, c_in=32, c_out=32, kernel_size=8, dilated_list=TRAINED_DILATIONS, bias: bool = True):
        super().__init__()
        # Tên lớp theo dilation phải khớp trọng số đã lưu;
        # từ chối danh sách khác để tránh âm thầm dùng sai cấu hình.
        assert tuple(dilated_list) == TRAINED_DILATIONS, f"Danh sách dilation phải là {TRAINED_DILATIONS}, nhưng nhận được {tuple(dilated_list)}."

        self.dilated_1 = ResidualBlock(c_in, c_out, k=kernel_size, dilation=1, bias=bias)
        self.dilated_2 = ResidualBlock(c_out, c_out, k=kernel_size, dilation=2, bias=bias)
        self.dilated_4 = ResidualBlock(c_out, c_out, k=kernel_size, dilation=4, bias=bias)
        self.dilated_8 = ResidualBlock(c_out, c_out, k=kernel_size, dilation=8, bias=bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x  # (B, c_in, L)
        x = self.dilated_1(x)  # (B, c_out, L)
        x = self.dilated_2(x)  # (B, c_out, L)
        x = self.dilated_4(x)  # (B, c_out, L)
        x = self.dilated_8(x)  # (B, c_out, L)
        return x
