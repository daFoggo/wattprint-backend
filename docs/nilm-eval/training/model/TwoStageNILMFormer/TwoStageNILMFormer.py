from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

from .GRUDetector import GRUConfig, GRUDetector
from .NILMFormerRegressor import NILMFormerConfig, NILMFormerRegressor


@dataclass
class TwoStageOutput:
    logits: torch.Tensor
    probability: torch.Tensor
    mask: torch.Tensor
    power: torch.Tensor
    prediction: torch.Tensor


class TwoStageNILMFormer(nn.Module):
    def __init__(self, detector_config: GRUConfig, regressor_config: NILMFormerConfig, threshold: float = 0.5):
        super().__init__()
        self.initialization_seed: int | None = None
        assert detector_config.c_in == 1 and regressor_config.c_in == 1, "Cả hai giai đoạn đều yêu cầu một kênh công suất tổng."
        assert detector_config.c_out == regressor_config.c_out, "Detector và regressor phải có cùng số kênh đầu ra."
        assert 0 < threshold < 1, "Ngưỡng threshold phải lớn hơn 0 và nhỏ hơn 1."
        self.threshold = threshold
        self.c_embedding = regressor_config.c_embedding
        self.Detector = GRUDetector(detector_config)
        self.Regressor = NILMFormerRegressor(regressor_config)

    def forward(self, x: torch.Tensor) -> TwoStageOutput:
        # Đầu vào (B, 1 + e, L); detector chỉ nhận kênh công suất tổng.
        assert x.ndim == 3 and x.shape[1] == 1 + self.c_embedding, "Đầu vào phải có shape (B, 1 + c_embedding, L)."
        logits = self.Detector(x[:, :1, :])  # (B, c_out, L)
        probability = logits.sigmoid()  # (B, c_out, L); sigmoid giữ nguyên chiều.
        # So ngưỡng tại từng thiết bị và thời điểm; giữ nguyên (B, c_out, L).
        hard_mask = (probability >= self.threshold).to(probability.dtype)
        # Forward dùng mask cứng; backward dùng đạo hàm sigmoid khi huấn luyện.
        mask = hard_mask + (probability - probability.detach()) if self.training else hard_mask

        # Công suất không âm giúp lỗi tắt nhầm đẩy detector về phía bật
        # thông qua loss công suất; softplus giữ nguyên (B, c_out, L).
        power = F.softplus(self.Regressor(x))  # (B, c_out, L)
        # Nhân từng phần tử cùng shape; thiết bị dự đoán tắt có công suất bằng 0.
        prediction = power * mask  # (B, c_out, L)
        return TwoStageOutput(logits, probability, mask, power, prediction)
