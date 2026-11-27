# Vẽ điện tổng, công suất thật và dự đoán ensemble của 2Stage và Baseline trên cùng cửa sổ test.
# Chạy từ thư mục gốc: uv run python reports/ve_du_doan.py --cache <thư mục cache của phan_tich_loi.py>
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FIG = Path(__file__).resolve().parent / "figures" / "hinh_du_doan.png"
DEVICES = ["WashingMachine", "Dishwasher", "Kettle", "Microwave"]
COLORS = {"Thực tế": "#222222", "2Stage": "#1f5f9f", "Baseline": "#e07b20"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(__file__).resolve().parents[1] / ".cache/phan_tich_loi")
    parser.add_argument("--train-house", type=int, default=2)
    parser.add_argument("--test-house", type=int, default=3)
    args = parser.parse_args()
    data = np.load(args.cache / f"du_lieu_{args.test_house:02d}.npz")
    group = f"house_{args.train_house:02d}"
    pred = {m: np.load(args.cache / f"{m}_{group}.npz")[f"pred_{args.test_house}"] for m in ("2Stage", "Baseline")}
    truth, valid, agg = data["power"], data["valid"], data["aggregate"]  # (N, C, L), (N, C, L), (N, L)
    assert all(p.shape == truth.shape for p in pred.values()), "Dự đoán và nhãn phải cùng shape (N, C, L)."
    # Hai cửa sổ chọn theo dữ liệu, chung cho cả hai mô hình: nhiều thiết bị cùng bật nhất, và tổng sai số của hai mô hình lớn nhất.
    n_on = (data["on"] * valid).max(axis=2).sum(axis=1)  # (N,)
    energy = (truth * valid).sum(axis=(1, 2))
    busy = int(np.lexsort((energy, n_on))[-1])
    err = sum(np.abs(p - truth) * valid for p in pred.values()).sum(axis=(1, 2))
    err[busy] = -1
    worst = int(err.argmax())
    windows = [(busy, "Cửa sổ có nhiều thiết bị bật nhất"), (worst, "Cửa sổ có tổng sai số lớn nhất")]

    fig, axes = plt.subplots(5, 2, figsize=(13, 12), sharex=True)
    minutes = np.arange(truth.shape[2])
    for col, (w, title) in enumerate(windows):
        start = pd.to_datetime(int(data["start_time_ns"][w]))
        ax = axes[0, col]
        ax.fill_between(minutes, agg[w], color="#a9cbe8", lw=0)
        ax.plot(minutes, agg[w], color="#3d7cc9", lw=1)
        ax.set_title(f"{title}\n(bắt đầu {start:%d/%m/%Y %H:%M})", fontsize=11)
        ax.set_ylabel("Điện tổng (W)")
        for row, name in enumerate(DEVICES, start=1):
            ax = axes[row, col]
            ax.plot(minutes, truth[w, row - 1], color=COLORS["Thực tế"], lw=1.6, label="Thực tế")
            ax.plot(minutes, pred["2Stage"][w, row - 1], color=COLORS["2Stage"], lw=1.3, label="2Stage")
            ax.plot(minutes, pred["Baseline"][w, row - 1], color=COLORS["Baseline"], lw=1.3, ls="--", label="Baseline")
            ax.set_ylabel(f"{name} (W)")
        axes[4, col].set_xlabel("Phút trong cửa sổ")
    for ax in axes.flat:
        ax.spines[["top", "right"]].set_visible(False)
    fig.legend(*axes[1, 0].get_legend_handles_labels(), loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(FIG, dpi=150)
    print("Đã ghi", FIG, "cửa sổ", windows)


if __name__ == "__main__":
    main()
