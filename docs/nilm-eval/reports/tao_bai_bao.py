"""Sinh bảng (Markdown/HTML) và hình cho bài báo từ kết quả runner của 2Stage và Baseline.

uv run python reports/tao_bai_bao.py --bang <tệp bang.md>
"""

import argparse
import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402
from tao_bao_cao_ket_qua import NHOM, ROOT, bang, nap, so  # noqa: E402

DATA = ROOT / "data/processed/REFIT/temporal_7aea0ef86866"
FIG = ROOT / "reports/figures"
DEVICES = ["WashingMachine", "Dishwasher", "Kettle", "Microwave"]
MODELS = ["2Stage", "Baseline"]
COLOR = {"2Stage": "#1f5f99", "Baseline": "#e07b1f"}
CONFIGS = [("2Stage", "riêng"), ("2Stage", "chung"), ("Baseline", "riêng"), ("Baseline", "chung")]
CONFIG_STYLE = {"2Stage riêng": (COLOR["2Stage"], "//"), "2Stage chung": (COLOR["2Stage"], ""), "Baseline riêng": (COLOR["Baseline"], "//"), "Baseline chung": (COLOR["Baseline"], "")}
CONCURRENT = ["0", "1", "2", "3+"]
LOAD = ["[0, 500)", "[500, 1500)", "[1500, 3000)", "[3000, inf)"]


def vn(value, digits):
    return so(value, digits)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--twostage-run", default=str(ROOT / "training/runs/twostage_20261126_042442"))
    parser.add_argument("--baseline-run", default=str(ROOT / "training/runs/nilmformer_20261126_042452"))
    parser.add_argument("--bang", required=True, help="Tệp Markdown ghi các bảng.")
    args = parser.parse_args()
    runs = {"2Stage": nap(args.twostage_run, "2Stage"), "Baseline": nap(args.baseline_run, "Baseline")}
    for run in runs.values():
        assert run["pooled_done"] and run["cross_complete"], f"Lượt chạy {run['dir']} chưa có đủ kết quả."
    study = runs["Baseline"]["study"]
    assert runs["2Stage"]["study"]["pooled_train_houses"] == study["pooled_train_houses"], "Hai lượt chạy phải dùng cùng cách chia hộ."
    houses = [str(h) for h in study["houses"]]
    pooled_train = [str(h) for h in study["pooled_train_houses"]]
    pooled_key = ",".join(pooled_train)
    unseen_pooled = [h for h in houses if h not in pooled_train]
    low = runs["Baseline"]["metrics"].loc[runs["Baseline"]["metrics"]["low_support"], ["house", "device"]].drop_duplicates()
    low_pairs = set(map(tuple, low.to_numpy()))

    def keep(frame):
        frame = frame[[(h, d) not in low_pairs for h, d in zip(frame["house"], frame["device"], strict=True)]]
        return frame.assign(house=frame["house"].astype(str))

    met = {m: keep(runs[m]["metrics"]) for m in MODELS}
    strata = {m: keep(runs[m]["strata"]) for m in MODELS}

    def pooled(m):
        return met[m][met[m]["protocol"] == "pooled"]

    def cross(m):
        return met[m][met[m]["protocol"] == "cross_house"]

    def own(m):
        frame = cross(m)
        return frame[frame["train_houses"] == frame["house"]]

    def agg(frame, metric):
        if frame.empty:
            return None
        if metric in ("f1", "recall") and "stratum" in frame:
            # Cặp không có phút bật trong tầng thì F1/Recall không xác định, không tính là 0.
            frame = frame[frame["on_count"] > 0]
        return frame[metric].sum() if metric == "fp" else frame[metric].mean()

    def split_value(source, big_new, extra=None):
        # Giá trị cho bảng có cột lớn "đã train" / "mới"; extra lọc thêm theo nhãn hàng.
        def value(metric, label, big, model):
            frame = source(model)
            frame = frame[frame["unseen_house"] == (big == big_new)]
            if extra is not None:
                frame = extra(frame, label)
            return agg(frame, metric)

        return value

    def by(column, prefix=""):
        return lambda frame, label: frame[frame[column].astype(str) == label.removeprefix(prefix)]

    tables = {}
    pooled_bigs = [f"Hộ được train ({', '.join(pooled_train)})", f"Hộ chưa thấy ({', '.join(unseen_pooled)})"]
    for key, (_, metrics) in zip(["tong_quan_bat_tat", "tong_quan_cong_suat", "tong_quan_nang_luong"], NHOM, strict=True):
        tables[key] = bang([("", m) for m in metrics], pooled_bigs, MODELS, split_value(pooled, pooled_bigs[1]))

    cross_bigs = ["Hộ được train", "Hộ mới"]
    ch1 = [m for _, metrics in NHOM for m in metrics]
    tables["ch1_tong_the"] = bang([("", m) for m in ch1], cross_bigs, MODELS, split_value(cross, "Hộ mới"))
    rows = [(d, m) for d in DEVICES for m in ["f1", "mae_w", "sae", "energy_error_kwh"]]
    tables["ch1_thiet_bi"] = bang(rows, cross_bigs, MODELS, split_value(cross, "Hộ mới", by("device")))
    rows = [(f"Hộ {h}", m) for h in houses for m in ["f1", "mae_w", "sae"]]
    tables["ch1_ho"] = bang(rows, cross_bigs, MODELS, split_value(cross, "Hộ mới", by("house", "Hộ ")))

    def strata_of(kind):
        return lambda m: strata[m][(strata[m]["protocol"] == "cross_house") & (strata[m]["stratum_type"] == kind)]

    rows = [("0", "mae_w"), ("0", "fp")] + [(k, m) for k in CONCURRENT[1:] for m in ["recall", "f1", "mae_w", "sae"]]
    tables["ch1_dong_thoi"] = bang(rows, cross_bigs, MODELS, split_value(strata_of("concurrent_on"), "Hộ mới", by("stratum")))
    rows = [(k, m) for k in LOAD for m in ["f1", "mae_w", "sae"]]
    tables["ch1_muc_tai"] = bang(rows, cross_bigs, MODELS, split_value(strata_of("load_w"), "Hộ mới", by("stratum")))

    groups = {f"Hộ có trong mô hình chung ({', '.join(pooled_train)})": pooled_train, f"Hộ mới với mô hình chung ({', '.join(unseen_pooled)})": unseen_pooled}
    subs = [f"{m} {s}" for m, s in CONFIGS]

    def config_frame(sub):
        model, setting = sub.split(" ")
        return pooled(model) if setting == "chung" else own(model)

    def ch2_value(metric, label, big, sub):
        frame = config_frame(sub)
        return agg(frame[frame["house"].isin(groups[big])], metric)

    for key, (_, metrics) in zip(["ch2_bat_tat", "ch2_cong_suat", "ch2_nang_luong"], NHOM, strict=True):
        tables[key] = bang([("", m) for m in metrics], list(groups), subs, ch2_value)

    f1_house = pd.DataFrame({sub: config_frame(sub).groupby("house")["f1"].mean() for sub in subs}).loc[houses]
    lines = ["| Cấu hình | " + " | ".join(f"Hộ {h}{'' if h in pooled_train else ' (mới)'}" for h in houses) + " |", "| --- |" + " ---: |" * len(houses)]
    for sub in subs:
        cells = [f"**{vn(v, 3)}**" if v == f1_house.loc[h].max() else vn(v, 3) for h, v in f1_house[sub].items()]
        lines.append(f"| {sub} | " + " | ".join(cells) + " |")
    tables["ch2_theo_ho"] = "\n".join(lines) + "\n"

    windows = {str(r["house"]): r["train_windows"] + r["validation_windows"] for r in study["validation_splits"]}
    days = np.mean([windows[h] for h in houses]) * 128 / 1440
    split_dates = json.loads((DATA / "split.json").read_text(encoding="utf-8"))
    # Ngày lịch của phần train (gồm validation): khoảng thời gian thực phải gắn ổ cắm đo.
    calendar_days = np.mean([(pd.Timestamp(split_dates[h]["train_end_exclusive"]) - pd.Timestamp(split_dates[h]["start"])).total_seconds() / 86400 for h in houses])
    lines = [
        "| Cấu hình | Số mô hình cần train | Dữ liệu đo riêng từng thiết bị tại hộ dùng | Epoch đã chạy (trung vị) | Thời gian train 5 seed (s) | GPU-giờ để phục vụ 7 hộ |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    cost = {}
    for model, setting in CONFIGS:
        frame = runs[model]["metrics"].drop_duplicates(["protocol", "train_houses"])
        if setting == "chung":
            frame = frame[frame["train_houses"] == pooled_key]
            n_models, data, total = "1 cho mọi hộ", "không cần", frame["train_seconds_total"].sum()
        else:
            frame = frame[frame["protocol"] == "cross_house"]
            n_models, data, total = "1 mỗi hộ (7)", f"khoảng {days:.0f} ngày dữ liệu dùng được ({calendar_days:.0f} ngày lịch) mỗi hộ", frame["train_seconds_total"].sum()
        assert len(frame) == (1 if setting == "chung" else len(houses)), f"Số mô hình {model} {setting} không đúng."
        epochs = pd.Series([int(e) for v in frame["epochs_trained"] for e in str(v).split(",")]).median()
        cost[f"{model} {setting}"] = total / 3600
        seconds = vn(frame["train_seconds_total"].mean(), 0) + ("" if setting == "chung" else " (trung bình/hộ)")
        lines.append(f"| {model} {setting} | {n_models} | {data} | {epochs:.0f} | {seconds} | {vn(total / 3600, 2)} |")
    tables["ch2_chi_phi"] = "\n".join(lines) + "\n"

    split = json.loads((DATA / "split.json").read_text(encoding="utf-8"))
    dev = pd.read_csv(DATA / "device_report.csv", encoding="utf-8-sig")
    dev = dev[dev["split"] == "test"].assign(house=lambda f: f["house"].astype(str)).set_index(["house", "device"])
    test = runs["Baseline"]["metrics"]
    test = test[test["protocol"] == "pooled"].assign(house=lambda f: f["house"].astype(str)).set_index(["house", "device"])
    vsplit = {str(r["house"]): r for r in study["validation_splits"]}
    lines = [
        "| Hộ | Giai đoạn dữ liệu | Ngày train / test | Cửa sổ train / validation / test | " + " | ".join(DEVICES) + " |",
        "| --- | --- | ---: | ---: |" + " ---: |" * len(DEVICES),
    ]
    for h in houses:
        s = {k: pd.Timestamp(v) for k, v in split[h].items()}
        n_test = int(test.loc[(h, DEVICES[0]), "test_windows"])
        cells = []
        for d in DEVICES:
            energy = test.loc[(h, d), "target_energy_kwh"]
            assert abs(energy - dev.loc[(h, d), "retained_energy_kwh"]) < 1e-6, f"Năng lượng test hộ {h} {d} lệch giữa device_report và test_metrics."
            cells.append(f"{vn(test.loc[(h, d), 'on_count'], 0)} phút; {vn(energy, 1)} kWh" + (" (loại)" if (int(h), d) in low_pairs else ""))
        train_days = (s["train_end_exclusive"] - s["start"]).total_seconds() / 86400
        test_days = (s["end_exclusive"] - s["test_start"]).total_seconds() / 86400
        period = f"{s['start']:%d/%m/%Y} – {s['end_exclusive']:%d/%m/%Y}"
        lines.append(f"| {h} | {period} | {train_days:.0f} / {test_days:.0f} | {vsplit[h]['train_windows']} / {vsplit[h]['validation_windows']} / {n_test} | " + " | ".join(cells) + " |")
    tables["du_lieu"] = "\n".join(lines) + "\n"

    out = ["# Bảng cho bài báo", "", f"Sinh bởi `reports/tao_bai_bao.py` từ `{runs['2Stage']['dir'].relative_to(ROOT)}` và `{runs['Baseline']['dir'].relative_to(ROOT)}`.", ""]
    for key, text in tables.items():
        out += [f"## BANG: {key}", "", text, ""]
    Path(args.bang).write_text("\n".join(out), encoding="utf-8")
    print("Đã ghi", args.bang)

    # ---------- Hình ----------
    FIG.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})

    def save(fig, name):
        fig.savefig(FIG / name, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print("Đã ghi", FIG / name)

    def bars(ax, labels, series, fmt="{:.3f}"):
        # series: [(tên, màu, hatch, giá trị theo labels)]; vẽ cột nhóm và ghi số trên đỉnh cột.
        width = 0.8 / len(series)
        x = np.arange(len(labels))
        for i, (name, color, hatch, values) in enumerate(series):
            pos = x - 0.4 + width * (i + 0.5)
            ax.bar(pos, values, width, color=color, hatch=hatch, edgecolor="white" if not hatch else "black", linewidth=0.5, label=name, alpha=1 if not hatch else 0.55)
            for p, v in zip(pos, values, strict=True):
                ax.text(p, v, fmt.format(v).replace(".", ","), ha="center", va="bottom", fontsize=7)
        ax.set_xticks(x, labels)

    # Hình tổng quan: mô hình chung.
    fig, axes = plt.subplots(1, 4, figsize=(14, 3.6))
    for ax, (metric, title, fmt) in zip(axes, [("f1", "F1 ↑", "{:.3f}"), ("mae_w", "MAE (W) ↓", "{:.1f}"), ("nep", "NEP ↓", "{:.2f}"), ("mr", "MR ↑", "{:.3f}")], strict=True):
        # Ba nhóm cột: mô hình chung trên toàn bộ tập test; mô hình riêng trên hộ được train và hộ chưa thấy.
        series = [(m, COLOR[m], "", [pooled(m)[metric].mean()] + [cross(m)[cross(m)["unseen_house"] == u][metric].mean() for u in (False, True)]) for m in MODELS]
        bars(ax, ["-all\ntoàn bộ\ntập test", "-sep\nhộ được\ntrain", "-sep\nhộ chưa\nthấy"], series, fmt)
        ax.set_title(title)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper right", frameon=False, ncol=2)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.suptitle("2Stage so với Baseline trong từng thiết lập (trung bình macro theo hộ × thiết bị)")
    save(fig, "hinh_tong_quan.png")

    def four(frame_fn, metric, column, labels):
        # Bốn chuỗi: mô hình × (hộ được train, hộ mới); hộ mới vẽ gạch chéo.
        series = []
        for m in MODELS:
            for unseen, name, hatch in [(False, "hộ được train", ""), (True, "hộ mới", "//")]:
                frame = frame_fn(m)
                frame = frame[frame["unseen_house"] == unseen]
                values = [agg(frame[frame[column].astype(str) == lb], metric) for lb in labels]
                series.append((f"{m} – {name}", COLOR[m], hatch, values))
        return series

    fig, axes = plt.subplots(1, 2, figsize=(13, 3.8))
    for ax, (metric, title, fmt) in zip(axes, [("f1", "F1 ↑", "{:.2f}"), ("mae_w", "MAE (W) ↓", "{:.0f}")], strict=True):
        bars(ax, DEVICES, four(cross, metric, "device", DEVICES), fmt)
        ax.set_title(title)
    fig.tight_layout(rect=(0, 0.06, 1, 0.93))
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=4, frameon=False)
    fig.suptitle("Mô hình riêng: F1 và MAE theo thiết bị (hộ được train: 7 cặp; hộ mới: 42 cặp mỗi thiết bị)")
    save(fig, "hinh_thiet_bi.png")

    matrices = {m: cross(m).groupby(["train_houses", "house"])["f1"].mean().unstack().loc[houses, houses] for m in MODELS}
    matrices["2Stage − Baseline"] = matrices["2Stage"] - matrices["Baseline"]
    fig, axes = plt.subplots(1, 3, figsize=(17, 5), layout="constrained")
    for ax, (name, mat) in zip(axes, matrices.items(), strict=True):
        diff = "−" in name
        lim = np.nanmax(np.abs(mat.to_numpy()))
        im = ax.imshow(mat.to_numpy(), cmap="RdBu" if diff else "viridis", vmin=-lim if diff else 0, vmax=lim if diff else 0.8)
        for i in range(len(houses)):
            for j in range(len(houses)):
                v = mat.iloc[i, j]
                ax.text(
                    j,
                    i,
                    (f"{v:+.2f}" if diff else f"{v:.2f}").replace("-0.00", "0.00").replace("+0.00", "0.00").replace(".", ",").replace("-", "−"),
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="black" if diff or v > 0.45 else "white",
                )
            ax.add_patch(Rectangle((i - 0.5, i - 0.5), 1, 1, fill=False, edgecolor="red", linewidth=2))
        ax.set_xticks(range(len(houses)), houses)
        ax.set_yticks(range(len(houses)), houses)
        ax.set_xlabel("Hộ test")
        ax.set_ylabel("Hộ train")
        ax.set_title(f"F1 – {name}")
        fig.colorbar(im, ax=ax, fraction=0.046)
    fig.suptitle("Ma trận F1 của mô hình riêng (trung bình 4 thiết bị; viền đỏ: đường chéo, hộ được train)")
    save(fig, "hinh_ma_tran_f1.png")

    fig, ax = plt.subplots(figsize=(9, 3.6))
    series = [(m, COLOR[m], "", [cross(m)[cross(m)["unseen_house"] & (cross(m)["house"] == h)]["f1"].mean() for h in houses]) for m in MODELS]
    bars(ax, [f"Hộ {h}" for h in houses], series)
    ax.set_ylabel("F1 ↑")
    ax.legend(frameon=False)
    ax.set_title("F1 trên hộ mới theo hộ test (mô hình riêng, trung bình 6 mô hình train trên hộ khác)")
    save(fig, "hinh_theo_ho.png")

    # Chỉ trục mức điện tổng; trục số thiết bị bật đồng thời được giải thích ở mục thiết kế, không vẽ riêng.
    fig, axes = plt.subplots(1, 2, figsize=(13, 3.8))
    for ax, (metric, title, fmt) in zip(axes, [("f1", "F1 ↑", "{:.2f}"), ("mae_w", "MAE (W) ↓", "{:.0f}")], strict=True):
        bars(ax, LOAD, four(strata_of("load_w"), metric, "stratum", LOAD), fmt)
        ax.set_title(f"{title} theo mức điện tổng")
        ax.set_xlabel("Mức điện tổng (W)")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.06))
    fig.suptitle("Mô hình riêng: hiệu năng theo mức điện tổng")
    fig.tight_layout()
    save(fig, "hinh_phan_tang.png")

    fig, ax = plt.subplots(figsize=(12, 4))
    bars(ax, [f"Hộ {h}" + ("" if h in pooled_train else "\n(mới)") for h in houses], [(s, *CONFIG_STYLE[s], f1_house[s].to_list()) for s in subs], "{:.2f}")
    ax.set_ylabel("F1 ↑")
    ax.legend(
        handles=[Patch(facecolor=c, hatch=hh, alpha=0.55 if hh else 1, edgecolor="black" if hh else "white", label=s) for s, (c, hh) in CONFIG_STYLE.items()],
        frameon=False,
        ncol=4,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
    )
    ax.set_title("F1 theo hộ test: mô hình riêng (train trên chính hộ) và mô hình chung (train trên hộ 6, 9, 11, 20)")
    save(fig, "hinh_ca_nhan_hoa.png")

    for m, name in [("2Stage", "hinh_du_doan_2stage.png"), ("Baseline", "hinh_du_doan_baseline.png")]:
        shutil.copyfile(runs[m]["dir"] / "house_02/predictions/house_03.png", FIG / name)
        print("Đã chép", FIG / name)
    print("GPU-giờ:", {k: round(v, 2) for k, v in cost.items()})


if __name__ == "__main__":
    main()
