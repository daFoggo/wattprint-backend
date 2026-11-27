# Vẽ dumbbell plot Recall và Precision theo phút của từng thiết bị, mô hình chung trên toàn bộ tập test, so 2Stage với Baseline.
# Chạy từ thư mục gốc: uv run python reports/ve_dumbbell_bat_tat.py
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNS = {"2Stage": ROOT / "training/runs/twostage_20261126_042442", "Baseline": ROOT / "training/runs/nilmformer_20261126_042452"}
COLOR = {"2Stage": "#1f5f99", "Baseline": "#e07b1f"}
DEVICES = ["Dishwasher", "Kettle", "WashingMachine", "Microwave"]
OUT = ROOT / "reports/figures/hinh_dumbbell_bat_tat.png"


def ty_le(run_dir):
    frame = pd.read_csv(run_dir / "test_metrics.csv")
    # Cùng tập (hộ, thiết bị) với Bảng 3: mô hình chung, bỏ các cặp có quá ít phút bật.
    frame = frame[(frame["protocol"] == "pooled") & ~frame["low_support"]]
    assert len(frame), f"Không có dòng mô hình chung trong {run_dir}"
    # Cộng dồn số phút của các hộ rồi mới chia (micro), khác trung bình macro ở các bảng.
    count = frame.groupby("device")[["tp", "fp", "fn"]].sum()
    return pd.DataFrame({"Recall": count["tp"] / (count["tp"] + count["fn"]) * 100, "Precision": count["tp"] / (count["tp"] + count["fp"]) * 100})


def main():
    values = {model: ty_le(path) for model, path in RUNS.items()}
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    rows = range(len(DEVICES))
    for ax, metric in zip(axes, ["Recall", "Precision"], strict=True):
        for y, device in zip(rows, DEVICES, strict=True):
            pair = [values[model].loc[device, metric] for model in RUNS]
            ax.plot(pair, [y, y], color="#bbbbbb", linewidth=3, zorder=1)
            for model, x in zip(RUNS, pair, strict=True):
                ax.scatter(x, y, s=70, color=COLOR[model], zorder=2, label=model if y == 0 else None)
                # Nhãn của giá trị lớn hơn đặt bên phải, giá trị nhỏ hơn bên trái để hai nhãn không chồng nhau.
                right = x >= max(pair)
                ax.annotate(
                    f"{x:.1f}".replace(".", ","), (x, y), xytext=(8 if right else -8, 0), textcoords="offset points", ha="left" if right else "right", va="center", fontsize=9, color=COLOR[model]
                )
        ax.set_title(f"{metric} theo phút (%)")
        ax.set_xlim(0, 100)
        ax.grid(axis="x", alpha=0.3)
    axes[0].set_yticks(list(rows), DEVICES)
    axes[0].set_ylim(len(DEVICES) - 0.5, -0.6)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 1.06))
    fig.tight_layout()
    fig.savefig(OUT, dpi=150, bbox_inches="tight")
    print("Đã ghi", OUT)
    for model, frame in values.items():
        print(model, frame.round(1).to_dict("index"))


if __name__ == "__main__":
    main()
