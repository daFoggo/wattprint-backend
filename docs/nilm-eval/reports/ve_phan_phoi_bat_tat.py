# Vẽ phân phối trạng thái bật/tắt theo hộ: tỷ lệ phút bật theo giờ trong ngày của từng thiết bị (phần train), chung một thang màu.
# Chạy từ thư mục gốc: uv run python reports/ve_phan_phoi_bat_tat.py
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed/REFIT/temporal_7aea0ef86866"
HOUSES = [2, 3, 6, 9, 11, 13, 20]
DEVICES = ["Dishwasher", "Kettle", "WashingMachine", "Microwave"]
OUT = ROOT / "reports/figures/hinh_phan_phoi_theo_ho.png"
# Xác suất bật cao nhất trong ngày dưới ngưỡng này thì coi là hộ gần như không dùng thiết bị.
RARE = 0.005


def doc(house):
    cols = ["timestamp"] + [f"{d}_{k}" for d in DEVICES for k in ("on", "valid")]
    frame = pd.read_csv(DATA / f"train_house_{house:02d}.csv", usecols=cols, parse_dates=["timestamp"])
    hour = frame["timestamp"].dt.hour
    out = {}
    for device in DEVICES:
        valid = frame[f"{device}_valid"] == 1
        assert valid.any(), f"Hộ {house} không có phút hợp lệ cho {device}"
        on = frame.loc[valid, f"{device}_on"].astype(bool)
        # Tỷ lệ phút bật trong từng giờ của ngày (24 giá trị).
        out[device] = on.groupby(hour[valid]).mean().reindex(range(24), fill_value=0).to_numpy() * 100
    return out


def main():
    stats = {house: doc(house) for house in HOUSES}
    plt.rcParams.update({"font.size": 10})
    # P(bật | giờ h, hộ i): tỷ lệ phút bật trong giờ h, đổi từ % sang xác suất; ma trận (24 giờ × hộ).
    prob = {device: {h: stats[h][device] / 100 for h in HOUSES} for device in DEVICES}
    vmax = max(p.max() for device in DEVICES for p in prob[device].values())
    fig, axes = plt.subplots(2, 2, figsize=(10, 9), sharey=True)
    for ax, device in zip(axes.flat, DEVICES, strict=True):
        # Sắp hộ theo giờ cao điểm; hộ có xác suất cao nhất dưới RARE coi là gần như không dùng và xếp cuối.
        order = sorted(HOUSES, key=lambda h: (prob[device][h].max() < RARE, int(prob[device][h].argmax())))
        grid = np.array([prob[device][h] for h in order]).T
        image = ax.imshow(grid, aspect="auto", cmap="Blues", vmin=0, vmax=vmax)
        ax.set_xticks(range(len(order)), [f"{h}*" if prob[device][h].max() < RARE else str(h) for h in order])
        ax.set_yticks(range(0, 24, 3), [f"{h}h" for h in range(0, 24, 3)])
        ax.set_title(device, fontweight="bold")
        ax.set_xlabel("Hộ (sắp theo giờ cao điểm)")
    for ax in axes[:, 0]:
        ax.set_ylabel("Giờ trong ngày")
    fig.tight_layout(rect=(0, 0, 0.9, 1))
    fig.colorbar(image, cax=fig.add_axes((0.92, 0.15, 0.02, 0.7)), label="P(bật | giờ, hộ)")
    fig.savefig(OUT, dpi=150, bbox_inches="tight")
    print("Đã ghi", OUT)


if __name__ == "__main__":
    main()
