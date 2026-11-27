# So sánh tỷ lệ phút bật theo giờ của bốn thiết bị giữa hộ 20 và hộ 11 trên phần dữ liệu train.
# Chạy từ thư mục gốc: uv run python reports/ve_xu_huong_hai_ho.py
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from ve_phan_phoi_bat_tat import DEVICES, doc  # noqa: E402

OUT = Path(__file__).resolve().parent / "figures/hinh_xu_huong_hai_ho.png"
HOUSES = [20, 11]


def main():
    # Mỗi ô là tỷ lệ phút bật trong một giờ của ngày, tính trên các phút hợp lệ ở phần train.
    stats = {house: doc(house) for house in HOUSES}
    values = {house: np.stack([stats[house][device] for device in DEVICES]) for house in HOUSES}
    vmax = max(matrix.max() for matrix in values.values())
    plt.rcParams.update({"font.size": 10})
    fig, axes = plt.subplots(2, 1, figsize=(10, 5.2), sharex=True, layout="constrained")
    for ax, house in zip(axes, HOUSES, strict=True):
        image = ax.imshow(values[house], cmap="YlGnBu", vmin=0, vmax=vmax, aspect="auto", interpolation="nearest")
        ax.set_yticks(range(len(DEVICES)), DEVICES)
        ax.set_title(f"Hộ {house}", loc="left", fontweight="bold")
        ax.set_xticks(range(0, 24, 3), [f"{hour}h" for hour in range(0, 24, 3)])
        ax.tick_params(axis="both", length=0)
    axes[-1].set_xlabel("Giờ trong ngày")
    fig.colorbar(image, ax=axes, label="Tỷ lệ phút bật trong giờ (%)", shrink=0.85)
    fig.savefig(OUT, dpi=180)
    print("Đã ghi", OUT)


if __name__ == "__main__":
    main()
