# So sánh xác suất bật theo giờ của từng thiết bị giữa hộ train và hộ đánh giá ở hai cặp hộ có F1 giảm nhiều nhất (mục 3.2).
# Chạy từ thư mục gốc: uv run python reports/ve_so_sanh_cap_ho.py
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from ve_phan_phoi_bat_tat import DEVICES, doc  # noqa: E402

OUT = Path(__file__).resolve().parent / "figures/hinh_so_sanh_cap_ho.png"
# (hộ train, hộ đánh giá): hai cặp có F1 giảm nhiều nhất so với đường chéo (Bảng 8).
PAIRS = [(20, 11), (20, 13)]
COLOR = {"train": "#1f5f99", "test": "#e07b1f"}


def main():
    stats = {h: doc(h) for pair in PAIRS for h in pair}
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(len(PAIRS), len(DEVICES), figsize=(14, 3.2 * len(PAIRS)), sharex=True, sharey=True)
    for row, (train, test) in zip(axes, PAIRS, strict=True):
        for ax, device in zip(row, DEVICES, strict=True):
            # doc() trả tỷ lệ phút bật theo giờ (%); đổi sang xác suất.
            ax.plot(range(24), stats[train][device] / 100, color=COLOR["train"], linewidth=2, label=f"Hộ {train} (train)")
            ax.plot(range(24), stats[test][device] / 100, color=COLOR["test"], linewidth=2, linestyle="--", label=f"Hộ {test} (đánh giá)")
            ax.set_title(f"{device}: hộ {train} → hộ {test}", fontsize=10)
            ax.set_xticks(range(0, 24, 6), [f"{h}h" for h in range(0, 24, 6)])
            ax.grid(alpha=0.3)
        row[0].set_ylabel("P(bật | giờ)")
        row[0].legend(frameon=False, fontsize=9)
    for ax in axes[-1]:
        ax.set_xlabel("Giờ trong ngày")
    fig.tight_layout()
    fig.savefig(OUT, dpi=150, bbox_inches="tight")
    print("Đã ghi", OUT)


if __name__ == "__main__":
    main()
