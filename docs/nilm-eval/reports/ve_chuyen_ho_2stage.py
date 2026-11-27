# Vẽ heatmap 7 × 7 (màu theo mức tốt/xấu) (hàng: mô hình riêng train trên hộ, cột: hộ được đánh giá) của 2Stage cho mục 3.2, mỗi nhóm chỉ số một hình.
# Chạy từ thư mục gốc: uv run python reports/ve_chuyen_ho_2stage.py
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "training/runs/twostage_20261126_042442"
BASELINE_RUN = ROOT / "training/runs/nilmformer_20261126_042452"
FIG = ROOT / "reports/figures"
# (cột, tên, True nếu càng cao càng tốt, số chữ số thập phân)
GROUPS = {
    "bat_tat": [("precision", "Precision ↑", True, 2), ("recall", "Recall ↑", True, 2), ("f1", "F1 ↑", True, 2)],
    "cong_suat": [("mae_w", "MAE (W) ↓", False, 1), ("rmse_w", "RMSE (W) ↓", False, 0), ("nde", "NDE ↓", False, 2)],
    "nang_luong": [("sae", "SAE ↓", False, 2), ("energy_error_kwh", "Sai số năng lượng (kWh) ↓", False, 1), ("nep", "NEP ↓", False, 2), ("teca", "TECA ↑", True, 2), ("mr", "MR ↑", True, 2)],
}


def nap():
    # Bỏ cùng các cặp (hộ, thiết bị) ít phút bật như các bảng khác (danh sách lấy từ lượt chạy Baseline, như tao_bai_bao.py).
    base = pd.read_csv(BASELINE_RUN / "test_metrics.csv")
    low = set(map(tuple, base.loc[base["low_support"], ["house", "device"]].drop_duplicates().to_numpy()))
    frame = pd.read_csv(RUN / "test_metrics.csv")
    keep = np.array([(h, d) not in low for h, d in zip(frame["house"], frame["device"], strict=True)])
    frame = frame[(frame["protocol"] == "cross_house").to_numpy() & keep].copy()
    assert len(frame), "Không có dòng mô hình riêng trong lượt chạy 2Stage"
    frame["train"] = frame["train_houses"].astype(int)
    return frame


def ve(frame, metrics, name):
    # Tối đa 3 heatmap mỗi hàng; ô thừa ở hàng cuối được ẩn.
    rows = -(-len(metrics) // 3)
    fig, axes = plt.subplots(rows, 3, figsize=(13, 4.2 * rows), layout="constrained", squeeze=False)
    for ax in axes.flat[len(metrics) :]:
        ax.set_visible(False)
    for ax, (column, title, higher, digits) in zip(axes.flat, metrics, strict=False):
        # Trung bình macro theo thiết bị cho từng cặp (hộ train, hộ đánh giá).
        matrix = frame.groupby(["train", "house"])[column].mean().unstack()
        houses = list(matrix.index)
        assert houses == list(matrix.columns), "Ma trận phải vuông, cùng thứ tự hộ"
        values = matrix.to_numpy()
        # Màu theo mức tốt/xấu chứ không theo giá trị: đổi mỗi ma trận về điểm 0 (kém nhất) đến 1 (tốt nhất), đảo dấu với chỉ số càng thấp càng tốt.
        low, high = np.nanmin(values), np.nanmax(values)
        score = (values - low) / (high - low) if high > low else np.full_like(values, 0.5)
        score = score if higher else 1 - score
        image = ax.imshow(score, cmap="RdYlGn", vmin=0, vmax=1)
        for i in range(len(houses)):
            for j in range(len(houses)):
                ax.text(j, i, f"{values[i, j]:.{digits}f}".replace(".", ","), ha="center", va="center", fontsize=8, color="black")
            ax.add_patch(Rectangle((i - 0.5, i - 0.5), 1, 1, fill=False, edgecolor="#1f3a93", linewidth=2.5))
        ax.set_xticks(range(len(houses)), houses)
        ax.set_yticks(range(len(houses)), houses)
        ax.set_xlabel("Đánh giá trên hộ")
        ax.set_ylabel("Mô hình train trên hộ")
        ax.set_title(title)
        bar = fig.colorbar(image, ax=ax, fraction=0.046, ticks=[0, 1])
        bar.ax.set_yticklabels(["Kém", "Tốt"])
    path = FIG / f"hinh_chuyen_ho_{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("Đã ghi", path)


def main():
    frame = nap()
    plt.rcParams.update({"font.size": 10})
    for name, metrics in GROUPS.items():
        ve(frame, metrics, name)


if __name__ == "__main__":
    main()
