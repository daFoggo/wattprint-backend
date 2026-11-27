import math

import torch


class NILMMetricAccumulator:
    def __init__(self, device_names: list[str], thresholds_w: list[float], sample_duration_s: float = 60):
        assert device_names and len(device_names) == len(thresholds_w), "Tên thiết bị và ngưỡng phải có cùng số kênh khác rỗng."
        assert sample_duration_s > 0, "Thời lượng mẫu phải lớn hơn 0."
        self.device_names = device_names
        self.thresholds = torch.tensor(thresholds_w, dtype=torch.float64)[None, :, None]
        assert (torch.isfinite(self.thresholds) & (self.thresholds >= 0)).all(), "Ngưỡng công suất phải hữu hạn và không âm."
        self.sample_duration_s = sample_duration_s
        names = ("count", "absolute", "squared", "actual", "actual_squared", "predicted", "minimum", "maximum", "negative", "tp", "fp", "fn", "tn")
        self.totals = {name: torch.zeros(len(device_names), dtype=torch.float64) for name in names}

    def update(self, prediction_w: torch.Tensor, target_w: torch.Tensor, target_on: torch.Tensor, valid: torch.Tensor) -> None:
        assert prediction_w.ndim == 3 and prediction_w.shape[1] == len(self.device_names), "Đầu vào metrics phải có shape (B, C, L) khớp số thiết bị."
        assert target_on.shape == valid.shape == target_w.shape == prediction_w.shape, "Công suất, nhãn và mask phải cùng shape."
        assert valid.dtype == torch.bool, "Mask hợp lệ phải có kiểu boolean."
        on = target_on.detach().to(device="cpu", dtype=torch.float64)
        effective_valid = valid.detach().cpu() & torch.isfinite(on)
        predicted, actual, keep = _prepare_pair(prediction_w, target_w, effective_valid)
        assert ((on[keep] == 0) | (on[keep] == 1)).all(), "Nhãn bật/tắt hợp lệ phải bằng 0 hoặc 1."
        assert (actual[keep] >= 0).all(), "Công suất thực tế phải không âm."
        predicted_on, actual_on = predicted >= self.thresholds, on == 1
        # Cộng theo batch và thời gian: (B, C, L) → (C,); không giữ dự đoán của toàn epoch.
        p = torch.where(keep, predicted, 0)
        y = torch.where(keep, actual, 0)
        values = {
            "count": keep,
            "absolute": (p - y).abs(),
            "squared": (p - y).square(),
            "actual": y,
            "actual_squared": y.square(),
            "predicted": p,
            "minimum": torch.minimum(p, y),
            "maximum": torch.maximum(p, y),
            "negative": (predicted < 0) & keep,
            "tp": predicted_on & actual_on & keep,
            "fp": predicted_on & ~actual_on & keep,
            "fn": ~predicted_on & actual_on & keep,
            "tn": ~predicted_on & ~actual_on & keep,
        }
        for name, value in values.items():
            self.totals[name] += value.sum(dim=(0, 2))

    def compute(self):
        per_device = {}
        for channel, name in enumerate(self.device_names):
            s = {key: float(value[channel]) for key, value in self.totals.items()}
            count = s["count"]
            zero = 0.0 if count else math.nan
            mse = _divide(s["squared"], count)
            energy_error = abs(s["predicted"] - s["actual"]) * self.sample_duration_s / 3_600_000 if count else math.nan
            per_device[name] = {
                "valid_count": int(count),
                "mae_w": _divide(s["absolute"], count),
                "rmse_w": math.sqrt(mse),
                "nde": _divide(s["squared"], s["actual_squared"]),
                "sae": _divide(abs(s["predicted"] - s["actual"]), s["actual"]),
                "mr": _divide(s["minimum"], s["maximum"]) if s["negative"] == 0 else math.nan,
                "energy_error_kwh": energy_error,
                "precision": _divide(s["tp"], s["tp"] + s["fp"], zero),
                "recall": _divide(s["tp"], s["tp"] + s["fn"], zero),
                "f1": _divide(2 * s["tp"], 2 * s["tp"] + s["fp"] + s["fn"], zero),
                "tp": int(s["tp"]),
                "fp": int(s["fp"]),
                "fn": int(s["fn"]),
                "tn": int(s["tn"]),
            }
        macro = {}
        for metric in ("mae_w", "rmse_w", "nde", "sae", "mr", "energy_error_kwh", "precision", "recall", "f1"):
            values = [row[metric] for row in per_device.values() if row["valid_count"] and math.isfinite(row[metric])]
            macro[metric] = sum(values) / len(values) if values else math.nan
        return {"macro": macro, "per_device": per_device}


def _divide(numerator: float, denominator: float, zero_value: float = math.nan) -> float:
    return numerator / denominator if denominator != 0 else zero_value


def _prepare_pair(prediction: torch.Tensor, target: torch.Tensor, valid: torch.Tensor | None):
    assert prediction.shape == target.shape, "Dự đoán và nhãn phải có cùng shape."
    assert valid is None or (valid.shape == target.shape and valid.dtype == torch.bool), "valid phải là tensor boolean cùng shape với nhãn."
    # Chuyển sang CPU và float64 để đánh giá; không giữ đồ thị gradient.
    prediction = prediction.detach().to(device="cpu", dtype=torch.float64)
    target = target.detach().to(device="cpu", dtype=torch.float64)
    keep = torch.isfinite(target)
    if valid is not None:
        keep &= valid.detach().cpu()
    # Không âm thầm loại dự đoán NaN/Inf, vì đây là lỗi của mô hình trên nhãn hợp lệ.
    assert torch.isfinite(prediction[keep]).all(), "Dự đoán trên các điểm có nhãn hợp lệ phải hữu hạn."
    return prediction, target, keep


def power_metrics(prediction: torch.Tensor, target: torch.Tensor, valid: torch.Tensor | None = None) -> dict[str, float | int]:
    prediction, target, keep = _prepare_pair(prediction, target, valid)
    # Gom mọi trục về các điểm hợp lệ; với (B, C, L), kết quả có shape (N_valid,).
    predicted, actual = prediction[keep], target[keep]
    assert (actual >= 0).all(), "Nhãn công suất phải không âm và được đổi về đơn vị W."
    count = actual.numel()
    names = ("mae_w", "mse_w2", "rmse_w", "nde", "sae", "nep", "teca", "mr")
    metrics: dict[str, float | int] = {name: math.nan for name in names}
    metrics.update(valid_count=count, total_count=target.numel(), coverage=_divide(count, target.numel()))
    if not count:
        return metrics
    error = predicted - actual
    absolute_error = float(error.abs().sum())
    squared_error = float(error.square().sum())
    total_power = float(actual.sum())
    mse = squared_error / count
    metrics.update(
        mae_w=absolute_error / count,
        mse_w2=mse,
        rmse_w=math.sqrt(mse),
        nde=_divide(squared_error, float(actual.square().sum())),
        sae=_divide(abs(float(predicted.sum()) - total_power), total_power),
        nep=_divide(absolute_error, total_power),
        teca=1 - _divide(absolute_error, 2 * total_power),
    )
    # MR có ý nghĩa với công suất không âm; không tự chặn đầu ra âm của baseline.
    if (predicted >= 0).all():
        metrics["mr"] = _divide(float(torch.minimum(predicted, actual).sum()), float(torch.maximum(predicted, actual).sum()))
    return metrics


def energy_metrics(
    prediction: torch.Tensor,
    target: torch.Tensor,
    sample_duration_s: float | torch.Tensor,
    valid: torch.Tensor | None = None,
) -> dict[str, float | int]:
    prediction, target, keep = _prepare_pair(prediction, target, valid)
    duration = torch.as_tensor(sample_duration_s, dtype=torch.float64, device="cpu").detach()
    assert duration.ndim == 0 or duration.shape == target.shape, "Thời lượng mẫu phải là số vô hướng hoặc tensor cùng shape với công suất."
    # Mỗi công suất được xem là giá trị trung bình/giữ nguyên trong khoảng thời gian tương ứng.
    duration = duration.expand_as(target)
    assert (torch.isfinite(duration[keep]) & (duration[keep] >= 0)).all(), "Thời lượng mẫu hợp lệ phải hữu hạn và không âm."
    assert (target[keep] >= 0).all(), "Nhãn công suất phải không âm và được đổi về đơn vị W."
    keep &= duration > 0
    if not keep.any():
        return dict.fromkeys(("predicted_energy_kwh", "target_energy_kwh", "energy_bias_kwh", "energy_error_kwh", "relative_energy_error"), math.nan) | {"energy_valid_count": 0}
    # W × giây / 3.600.000 → kWh; chỉ tích phân trên các khoảng được đánh giá.
    predicted_energy = float((prediction[keep] * duration[keep]).sum()) / 3_600_000
    target_energy = float((target[keep] * duration[keep]).sum()) / 3_600_000
    bias = predicted_energy - target_energy
    return {
        "predicted_energy_kwh": predicted_energy,
        "target_energy_kwh": target_energy,
        "energy_bias_kwh": bias,
        "energy_error_kwh": abs(bias),
        "relative_energy_error": _divide(abs(bias), target_energy),
        "energy_valid_count": int(keep.sum()),
    }


def state_metrics(predicted_on: torch.Tensor, target_on: torch.Tensor, valid: torch.Tensor | None = None) -> dict[str, float | int]:
    predicted_on, target_on, keep = _prepare_pair(predicted_on, target_on, valid)
    predicted, actual = predicted_on[keep], target_on[keep]
    assert ((predicted == 0) | (predicted == 1)).all(), "Trạng thái dự đoán phải bằng 0 hoặc 1; không truyền trực tiếp logits hoặc xác suất."
    assert ((actual == 0) | (actual == 1)).all(), "Nhãn bật/tắt phải bằng 0 hoặc 1."
    predicted, actual = predicted.bool(), actual.bool()
    tp = int((predicted & actual).sum())
    fp = int((predicted & ~actual).sum())
    fn = int((~predicted & actual).sum())
    tn = int((~predicted & ~actual).sum())
    count = tp + fp + fn + tn
    # Tập có dữ liệu nhưng mẫu số precision/recall/F1 bằng 0 được quy ước trả 0.
    zero_value = 0.0 if count else math.nan
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": _divide(tp, tp + fp, zero_value),
        "recall": _divide(tp, tp + fn, zero_value),
        "f1": _divide(2 * tp, 2 * tp + fp + fn, zero_value),
        "accuracy": _divide(tp + tn, count),
        "false_negative_rate": _divide(fn, tp + fn),
        "state_valid_count": count,
        "on_count": tp + fn,
    }


def compute_nilm_metrics(
    prediction: torch.Tensor,
    target: torch.Tensor,
    valid: torch.Tensor | None = None,
    *,
    sample_duration_s: float | torch.Tensor | None = None,
    predicted_on: torch.Tensor | None = None,
    target_on: torch.Tensor | None = None,
) -> dict[str, float | int]:
    # Mọi trục được gộp; cắt theo hộ/thiết bị trước khi gọi nếu cần bảng riêng.
    metrics = power_metrics(prediction, target, valid)
    if sample_duration_s is not None:
        metrics.update(energy_metrics(prediction, target, sample_duration_s, valid))
    assert (predicted_on is None) == (target_on is None), "Cần truyền đồng thời predicted_on và target_on để đánh giá bật/tắt."
    if predicted_on is not None:
        assert target_on is not None, "Cần truyền target_on khi đánh giá trạng thái dự đoán."
        assert predicted_on.shape == prediction.shape and target_on.shape == target.shape, "Các tensor trạng thái phải cùng shape với công suất."
        # Dùng chung các điểm có nhãn công suất hợp lệ khi tính chỉ số bật/tắt kết hợp.
        state_valid = torch.isfinite(target)
        if valid is not None:
            state_valid &= valid.to(target.device)
        metrics.update(state_metrics(predicted_on, target_on, state_valid))
    return metrics
