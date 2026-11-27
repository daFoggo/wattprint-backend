# Chuẩn bị gói triển khai 2Stage chung: gộp trọng số 5 seed, tạo dữ liệu mẫu và dự đoán tham chiếu.
# Chạy trên máy train, từ thư mục gốc: uv run python deploy/xuat_trong_so.py
import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.data import REFITCSVDataset  # noqa: E402
from training.model.TwoStageNILMFormer.GRUDetector import GRUConfig  # noqa: E402
from training.model.TwoStageNILMFormer.NILMFormerRegressor import NILMFormerConfig  # noqa: E402
from training.model.TwoStageNILMFormer.TwoStageNILMFormer import TwoStageNILMFormer  # noqa: E402

DEPLOY = ROOT / "deploy"
DATA_DIR = ROOT / "data/processed/REFIT/temporal_7aea0ef86866"


def as_dict(config) -> dict:
    return asdict(config) if is_dataclass(config) else dict(config)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default=str(ROOT / "training/runs/twostage_20261126_042442"), help="Lượt chạy 2Stage đã train.")
    parser.add_argument("--house", type=int, default=3, help="Hộ lấy dữ liệu mẫu; mặc định hộ 3, chưa có trong mô hình chung.")
    parser.add_argument("--windows", type=int, default=12, help="Số cửa sổ 128 phút liên tiếp của dữ liệu mẫu.")
    # Cửa sổ 111 là đoạn liên tiếp đầu tiên của hộ 3 có cả bốn thiết bị bật; chọn để minh họa, không đại diện độ chính xác.
    parser.add_argument("--start-window", type=int, default=111, help="Chỉ số cửa sổ test đầu tiên của dữ liệu mẫu.")
    args = parser.parse_args()
    torch.set_num_threads(1)
    study = json.loads((Path(args.run) / "study.json").read_text(encoding="utf-8"))
    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    targets = manifest["target_channels"]
    assert args.house not in study["pooled_train_houses"], "Dữ liệu mẫu nên lấy từ hộ chưa có trong mô hình chung."

    # Chỉ giữ cấu hình và state_dict; bỏ optimizer, lịch sử train để gói nhẹ.
    bundle = {"targets": targets, "power_scale_w": float(manifest["config"]["power_scale_w"]), "window_size": manifest["config"]["window_size"], "seeds": [], "state_dicts": []}
    models = []
    for seed in study["model_seeds"]:
        checkpoint = torch.load(Path(args.run) / "pooled" / f"seed_{seed}" / "best.pt", map_location="cpu", weights_only=False)
        detector, regressor = as_dict(checkpoint["detector_config"]), as_dict(checkpoint["regressor_config"])
        assert "detector_config" not in bundle or (bundle["detector_config"], bundle["regressor_config"]) == (detector, regressor), "Các seed phải cùng cấu hình."
        bundle.update(detector_config=detector, regressor_config=regressor, threshold=float(checkpoint["threshold"]))
        bundle["seeds"].append(seed)
        bundle["state_dicts"].append(checkpoint["model"])
        model = TwoStageNILMFormer(GRUConfig(**detector), NILMFormerConfig(**regressor), checkpoint["threshold"])
        model.load_state_dict(checkpoint["model"])
        models.append(model.eval())
    (DEPLOY / "trong_so").mkdir(parents=True, exist_ok=True)
    torch.save(bundle, DEPLOY / "trong_so" / "twostage_chung.pt")

    # Dữ liệu mẫu: các cửa sổ test liên tiếp của hộ, giống một chuỗi đo thật.
    dataset = REFITCSVDataset(DATA_DIR, "test", house_id=args.house)
    items = [dataset[i] for i in range(args.start_window, args.start_window + args.windows)]
    starts = torch.tensor([item["start_time_ns"] for item in items])
    assert (starts.diff() == bundle["window_size"] * 60 * 10**9).all(), "Các cửa sổ mẫu phải liên tiếp nhau."
    x = torch.stack([item["x"] for item in items])  # (N, 9, L)
    timestamps = pd.to_datetime(starts[0].item()) + pd.to_timedelta(range(args.windows * bundle["window_size"]), unit="min")
    aggregate = (x[:, 0] * dataset.scale).reshape(-1)  # (N, L) → (N × L,)
    (DEPLOY / "vi_du").mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"timestamp": timestamps, "aggregate_w": aggregate.numpy()}).to_csv(DEPLOY / "vi_du" / f"ho_{args.house:02d}_dien_tong.csv", index=False)

    # Dự đoán tham chiếu theo đúng quy tắc của runner: trung bình công suất 5 seed, chặn âm, đổi về W.
    with torch.no_grad():
        prediction = torch.stack([model(x).prediction.clamp(min=0) for model in models]).mean(dim=0) * dataset.scale  # (S, N, C, L) → (N, C, L)
    flat = prediction.permute(0, 2, 1).reshape(-1, len(targets))  # (N, C, L) → (N × L, C)
    reference = pd.DataFrame(flat.numpy(), columns=[f"{name}_w" for name in targets])
    reference.insert(0, "timestamp", timestamps)
    reference.to_csv(DEPLOY / "vi_du" / f"ho_{args.house:02d}_tham_chieu.csv", index=False)
    # Công suất đo thật của từng thiết bị để đối chiếu kết quả demo.
    truth = torch.stack([item["power"] for item in items]) * dataset.scale  # (N, C, L)
    actual = pd.DataFrame(truth.permute(0, 2, 1).reshape(-1, len(targets)).numpy(), columns=[f"{name}_w" for name in targets])
    actual.insert(0, "timestamp", timestamps)
    actual.to_csv(DEPLOY / "vi_du" / f"ho_{args.house:02d}_thuc_te.csv", index=False)
    print("Đã ghi trọng số", len(bundle["seeds"]), "seed và dữ liệu mẫu", len(timestamps), "phút của hộ", args.house)


if __name__ == "__main__":
    main()
