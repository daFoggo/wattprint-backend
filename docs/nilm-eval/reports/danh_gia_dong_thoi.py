"""Đánh giá khi nhiều thiết bị đích bật đồng thời: nhóm phút theo số thiết bị bật thật (0, 1, 2, 3, ≥2), so 2Stage và Baseline (mô hình riêng).

Chạy:
    uv run python reports/danh_gia_dong_thoi.py [--cache <thư mục cache của phan_tich_loi.py>]
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import torch  # noqa: E402
from phan_tich_loi import DATA_DIR, DEFAULT_CACHE, DEVICES, OUT_FIG, ROOT, RUNS, load_pair, predict_all, verify  # noqa: E402

from training.seeds import BASE_SEED, seed_everything  # noqa: E402
from training.train_twostage_nilmformer import STUDY_HOUSES  # noqa: E402

OUT_CSV = ROOT / "reports/data/dong_thoi"
NHOM = ["0", "1", "2", "3", "≥2"]
# Hai mức điện tổng cao (W) để tách tác động của chồng lấp khỏi tác động của tải cao.
MUC_TAI = [(1500.0, 3000.0, "[1500, 3000)"), (3000.0, np.inf, "[3000, ∞)")]
WM, DW = DEVICES.index("WashingMachine"), DEVICES.index("Dishwasher")
COLORS = {"Thực tế": "#222222", "2Stage": "#1f5f9f", "Baseline": "#e07b20"}


def phang(tensors: dict[str, torch.Tensor]) -> dict[str, np.ndarray]:
    # (N, C, L) → (N·L, C); (N, L) → (N·L,). Không cần thứ tự thời gian vì chỉ đếm theo phút.
    n, c, length = tensors["power"].shape
    out = {k: tensors[k].numpy().transpose(0, 2, 1).reshape(n * length, c) for k in ("power", "on", "valid", "prediction")}
    out["on"] = out["on"] == 1
    out["aggregate"] = tensors["aggregate"].numpy().reshape(-1)
    return out


def dem_cap(flat: dict[str, np.ndarray], thresholds: np.ndarray, low_support: dict[str, bool]) -> list[dict]:
    # Thiết bị có trong hộ = kênh có ít nhất một nhãn hợp lệ; chỉ giữ phút mà mọi thiết bị có trong hộ đều hợp lệ.
    present = flat["valid"].any(axis=0)  # (C,)
    keep = flat["valid"][:, present].all(axis=1)  # (T,)
    on = flat["on"] & present[None, :]  # (T, C)
    pred_on = flat["prediction"] >= thresholds[None, :]  # (T, C) ↔ (1, C)
    n_on = on.sum(axis=1)  # (T,)
    agg = flat["aggregate"]
    group_masks = {g: keep & (n_on >= 2 if g == "≥2" else n_on == int(g)) for g in NHOM}
    masks = [(g, "tất cả", group_masks[g]) for g in NHOM]
    masks += [(g, label, group_masks[g] & (agg >= lo) & (agg < hi)) for g in ("1", "≥2") for lo, hi, label in MUC_TAI]
    rows = []
    for g, tai, m in masks:
        # Nhầm giữa hai máy gia nhiệt: đúng một trong hai bật thật, mô hình báo bật máy còn lại.
        wm_dw = {}
        if present[WM] and present[DW]:
            only_wm, only_dw = m & on[:, WM] & ~on[:, DW], m & on[:, DW] & ~on[:, WM]
            wm_dw = {
                "chi_wm_bat": int(only_wm.sum()),
                "chi_dw_bat": int(only_dw.sum()),
                "wm_bat_bao_dw": int((only_wm & pred_on[:, DW]).sum()),
                "dw_bat_bao_wm": int((only_dw & pred_on[:, WM]).sum()),
                "wm_bat_doi_cho": int((only_wm & pred_on[:, DW] & ~pred_on[:, WM]).sum()),
                "dw_bat_doi_cho": int((only_dw & pred_on[:, WM] & ~pred_on[:, DW]).sum()),
            }
        # Phút có ít nhất một thiết bị đang bật bị bỏ sót, và phút có báo nhầm thiết bị đang tắt.
        fn_any = (on & ~pred_on)[:, present].any(axis=1)
        fp_any = (~on & pred_on)[:, present].any(axis=1)
        base = {"nhom": g, "muc_tai": tai, "so_phut": int(m.sum()), "phut_bo_sot": int((m & fn_any).sum()), "phut_bat_nham": int((m & fp_any).sum()), **wm_dw}
        for c, dev in enumerate(DEVICES):
            if not present[c] or low_support[dev]:
                continue
            y, yhat, t, p = flat["power"][m, c], flat["prediction"][m, c], on[m, c], pred_on[m, c]
            rows.append(
                base
                | {
                    "device": dev,
                    "tp": int((t & p).sum()),
                    "fp": int((~t & p).sum()),
                    "fn": int((t & ~p).sum()),
                    "abs_err_w": float(np.abs(yhat - y).sum()),
                    # Mỗi mẫu là một phút: W × 1/60 h → Wh.
                    "e_pred_wh": float(yhat.sum() / 60),
                    "e_true_wh": float(y.sum() / 60),
                }
            )
    return rows


def tong_hop(rows: pd.DataFrame) -> pd.DataFrame:
    # Cộng số đếm của mọi cặp hộ theo thiết bị, tính chỉ số theo thiết bị rồi lấy trung bình bốn thiết bị.
    rows = rows.assign(abs_de_wh=(rows.e_pred_wh - rows.e_true_wh).abs(), du_wh=rows.e_pred_wh - rows.e_true_wh)
    keys = ["model", "boi_canh", "nhom", "muc_tai"]
    dev = rows.groupby(keys + ["device"], as_index=False)[["tp", "fp", "fn", "abs_err_w", "e_true_wh", "abs_de_wh", "du_wh"]].sum()
    dev["n"] = rows.groupby(keys + ["device"]).so_phut.sum().values
    dev["f1"] = 2 * dev.tp / (2 * dev.tp + dev.fp + dev.fn).replace(0, np.nan)
    dev["precision"] = dev.tp / (dev.tp + dev.fp).replace(0, np.nan)
    dev["recall"] = dev.tp / (dev.tp + dev.fn).replace(0, np.nan)
    dev["mae_w"] = dev.abs_err_w / dev.n
    dev["sai_so_dien_nang"] = dev.abs_de_wh / dev.e_true_wh.replace(0, np.nan)
    out = dev.groupby(keys, as_index=False).agg(
        f1=("f1", "mean"),
        precision=("precision", "mean"),
        recall=("recall", "mean"),
        mae_w=("mae_w", "mean"),
        sai_so_dien_nang=("sai_so_dien_nang", "mean"),
        fp_tb=("fp", "sum"),
        fn_tb=("fn", "sum"),
        tp_tb=("tp", "sum"),
        du_kwh=("du_wh", "sum"),
    )
    out["du_kwh"] /= 1000
    # Số phút và đếm theo phút lấy một lần cho mỗi cặp hộ (không nhân theo thiết bị).
    pair = rows.drop_duplicates(keys + ["train", "house"])
    cnt_cols = ["so_phut", "phut_bo_sot", "phut_bat_nham", "chi_wm_bat", "chi_dw_bat", "wm_bat_bao_dw", "dw_bat_bao_wm", "wm_bat_doi_cho", "dw_bat_doi_cho"]
    return out.merge(pair.groupby(keys, as_index=False)[cnt_cols].sum(), on=keys)


def ve_cua_so(cache: Path) -> tuple[Path, str]:
    # Chọn trong mọi cặp mô hình riêng trên hộ mới cửa sổ có nhiều phút ≥2 thiết bị đích cùng bật nhất.
    best = (-1, None)
    for train in STUDY_HOUSES:
        for house in STUDY_HOUSES:
            if train == house:
                continue
            data = np.load(cache / f"du_lieu_{house:02d}.npz")
            n_on = (data["on"] * data["valid"]).sum(axis=1)  # (N, C, L) → (N, L)
            score = (n_on >= 2).sum(axis=1)  # (N,)
            w = int(score.argmax())
            if score[w] > best[0]:
                best = (int(score[w]), (train, house, w))
    _, (train, house, w) = best
    data = np.load(cache / f"du_lieu_{house:02d}.npz")
    pred = {m: np.load(cache / f"{m}_house_{train:02d}.npz")[f"pred_{house}"][w] for m in ("2Stage", "Baseline")}  # (C, L)
    truth, valid, agg = data["power"][w], data["valid"][w], data["aggregate"][w]
    overlap = (data["on"][w] * valid).sum(axis=0) >= 2  # (L,)
    minutes = np.arange(truth.shape[1])
    fig, axes = plt.subplots(len(DEVICES) + 1, 1, figsize=(11, 11), sharex=True)
    edges = np.flatnonzero(np.diff(np.r_[0, overlap.astype(int), 0]))
    for ax in axes:
        for a, b in zip(edges[::2], edges[1::2], strict=True):
            ax.axvspan(a - 0.5, b - 0.5, color="#f2c94c", alpha=0.3, lw=0)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].fill_between(minutes, agg, color="#a9cbe8", lw=0)
    axes[0].plot(minutes, agg, color="#3d7cc9", lw=1)
    axes[0].set_ylabel("Điện tổng (W)")
    start = pd.to_datetime(int(data["start_time_ns"][w]))
    axes[0].set_title(f"Mô hình riêng train trên hộ {train}, kiểm tra trên hộ {house} (bắt đầu {start:%d/%m/%Y %H:%M}); nền vàng: ≥2 thiết bị đích cùng bật", fontsize=10)
    for row, name in enumerate(DEVICES, start=1):
        ax = axes[row]
        ax.plot(minutes, np.where(valid[row - 1], truth[row - 1], np.nan), color=COLORS["Thực tế"], lw=1.6, label="Thực tế")
        ax.plot(minutes, pred["2Stage"][row - 1], color=COLORS["2Stage"], lw=1.3, label="2Stage")
        ax.plot(minutes, pred["Baseline"][row - 1], color=COLORS["Baseline"], lw=1.3, ls="--", label="Baseline")
        ax.set_ylabel(f"{name} (W)")
    axes[-1].set_xlabel("Phút trong cửa sổ")
    fig.legend(*axes[1].get_legend_handles_labels(), loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    path = OUT_FIG / "hinh_dong_thoi.png"
    fig.savefig(path, dpi=150)
    return path, f"train hộ {train}, test hộ {house}, cửa sổ {w}, {int(overlap.sum())} phút chồng lấp"


def main() -> None:
    parser = argparse.ArgumentParser(description="Đánh giá theo số thiết bị đích bật đồng thời.")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    torch.set_num_threads(1)
    seed_everything(BASE_SEED)
    args.cache.mkdir(parents=True, exist_ok=True)
    OUT_CSV.mkdir(parents=True, exist_ok=True)
    # Dự đoán ensemble dùng chung cache với phan_tich_loi.py; chỉ chạy lại khi cache chưa có.
    predict_all(args.cache, "cuda" if torch.cuda.is_available() else "cpu", args.batch_size)
    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    thresholds = np.array([manifest["thresholds_w"][d][0] for d in DEVICES])
    worst = verify(args.cache, thresholds.tolist()).lech_lon_nhat.max()
    assert worst <= 1e-6, "Dự đoán tái tạo lệch so với test_metrics.csv quá 1e-6; dừng đánh giá."
    ref = pd.read_csv(RUNS["2Stage"] / "test_metrics.csv")
    rows = []
    for train in STUDY_HOUSES:
        for house in STUDY_HOUSES:
            sub = ref[(ref.train_houses.astype(str) == str(train)) & (ref.house == house)]
            low = dict(zip(sub.device, sub.low_support, strict=True))
            for name in RUNS:
                flat = phang(load_pair(args.cache, name, f"house_{train:02d}", house))
                for r in dem_cap(flat, thresholds, low):
                    rows.append({"model": name, "boi_canh": "hộ được train" if house == train else "hộ mới", "train": train, "house": house} | r)
    rows = pd.DataFrame(rows)
    rows.to_csv(OUT_CSV / "dem_theo_cap.csv", index=False)
    summary = tong_hop(rows)
    summary.to_csv(OUT_CSV / "tong_hop.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(summary)
    path, info = ve_cua_so(args.cache)
    print("Đã ghi", path, info)


if __name__ == "__main__":
    main()
