# Suy luận NILM trên CPU: điện tổng theo phút (CSV) → công suất và điện năng từng thiết bị.
# Ví dụ: python deploy/suy_luan.py --input deploy/vi_du/ho_03_dien_tong.csv --output ket_qua.csv
import argparse
import resource
import sys
import time
from pathlib import Path

import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.data import timestamp_features  # noqa: E402
from training.model.TwoStageNILMFormer.GRUDetector import GRUConfig  # noqa: E402
from training.model.TwoStageNILMFormer.NILMFormerRegressor import NILMFormerConfig  # noqa: E402
from training.model.TwoStageNILMFormer.TwoStageNILMFormer import TwoStageNILMFormer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="CSV gồm cột timestamp và aggregate_w, nhịp 1 phút liên tục.")
    parser.add_argument("--output", required=True, help="CSV ghi công suất dự đoán từng thiết bị.")
    parser.add_argument("--weights", default=str(ROOT / "deploy/trong_so/twostage_chung.pt"), help="Gói trọng số do xuat_trong_so.py tạo.")
    parser.add_argument("--threads", type=int, default=1, help="Số luồng CPU.")
    args = parser.parse_args()
    started = time.perf_counter()
    torch.set_num_threads(args.threads)
    bundle = torch.load(args.weights, map_location="cpu", weights_only=False)
    models = []
    for state in bundle["state_dicts"]:
        model = TwoStageNILMFormer(GRUConfig(**bundle["detector_config"]), NILMFormerConfig(**bundle["regressor_config"]), bundle["threshold"])
        model.load_state_dict(state)
        models.append(model.eval())
    loaded = time.perf_counter()

    frame = pd.read_csv(args.input, parse_dates=["timestamp"])
    length, scale, targets = bundle["window_size"], bundle["power_scale_w"], bundle["targets"]
    assert len(frame) > 0 and frame["aggregate_w"].notna().all(), "Điện tổng phải có giá trị ở mọi phút."
    assert (frame["timestamp"].diff().dropna() == pd.Timedelta(minutes=1)).all(), "Dữ liệu phải liên tục theo nhịp 1 phút."
    minutes = len(frame)
    # Cửa sổ cuối thiếu phút được đệm bằng giá trị cuối, phần đệm bị bỏ khỏi kết quả.
    padded = -(-minutes // length) * length
    index = pd.DatetimeIndex(frame["timestamp"].iloc[0] + pd.to_timedelta(range(padded), unit="min"))
    aggregate = torch.tensor(frame["aggregate_w"].to_numpy(dtype="float32"))
    aggregate = torch.cat([aggregate, aggregate[-1:].repeat(padded - minutes)]) / scale  # (T',)
    windows = padded // length
    encoding = torch.from_numpy(timestamp_features(index)).reshape(8, windows, length).permute(1, 0, 2)  # (8, T') → (N, 8, L)
    x = torch.cat([aggregate.reshape(windows, 1, length), encoding], dim=1)  # (N, 1 + 8, L)
    with torch.no_grad():
        # Ensemble 5 seed: (S, N, C, L) → trung bình (N, C, L), đổi về W.
        prediction = torch.stack([model(x).prediction.clamp(min=0) for model in models]).mean(dim=0) * scale
    power = prediction.permute(0, 2, 1).reshape(padded, len(targets))[:minutes]  # (N, C, L) → (T, C)
    inferred = time.perf_counter()

    result = pd.DataFrame(power.numpy(), columns=[f"{name}_w" for name in targets])
    result.insert(0, "timestamp", frame["timestamp"])
    result.to_csv(args.output, index=False)
    energy = power.sum(dim=0) * 60 / 3_600_000  # W × phút → kWh
    print(f"Số phút: {minutes}; số seed: {len(models)}; luồng CPU: {args.threads}")
    print("Điện năng ước tính (kWh): " + ", ".join(f"{name} {value:.3f}" for name, value in zip(targets, energy.tolist(), strict=True)))
    print(f"Điện tổng (kWh): {frame['aggregate_w'].sum() * 60 / 3_600_000:.3f}")
    print(f"Thời gian nạp mô hình: {loaded - started:.2f} s; suy luận: {inferred - loaded:.3f} s")
    # ru_maxrss tính bằng KB trên Linux.
    print(f"Bộ nhớ đỉnh: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB")


if __name__ == "__main__":
    main()
