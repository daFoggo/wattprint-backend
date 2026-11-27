"""Phân tích lỗi có chủ đích cho 2Stage và Baseline: nhóm đúng/sai theo phút và theo sự kiện, cùng đặc trưng của từng nhóm.

Chạy:
    uv run python reports/phan_tich_loi.py [--cache <thư mục cache>]
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.data import REFITCSVDataset  # noqa: E402
from training.model.NILMFormer.NILMFormer import NILMFormer  # noqa: E402
from training.model.NILMFormer.NILMFormer import NILMFormerConfig as BaselineConfig  # noqa: E402
from training.model.TwoStageNILMFormer.GRUDetector import GRUConfig  # noqa: E402
from training.model.TwoStageNILMFormer.NILMFormerRegressor import NILMFormerConfig  # noqa: E402
from training.model.TwoStageNILMFormer.TwoStageNILMFormer import TwoStageNILMFormer  # noqa: E402
from training.seeds import BASE_SEED, seed_everything  # noqa: E402
from training.train_twostage_nilmformer import STUDY_HOUSES, ensemble_outputs, house_metric_rows, predict_house  # noqa: E402

RUNS = {
    "2Stage": ROOT / "training/runs/twostage_20261126_042442",
    "Baseline": ROOT / "training/runs/nilmformer_20261126_042452",
}
DATA_DIR = ROOT / "data/processed/REFIT/temporal_7aea0ef86866"
DEVICES = ["WashingMachine", "Dishwasher", "Kettle", "Microwave"]
SEEDS = [478163327, 107420369, 1181241943, 1051802512, 958682846]
GROUPS = ["pooled"] + [f"house_{h:02d}" for h in STUDY_HOUSES]
OUT_CSV = ROOT / "reports/data/phan_tich_loi"
OUT_FIG = ROOT / "reports/figures"
# Cache dự đoán ensemble (.npz, khoảng 90 MB), không đưa vào git.
DEFAULT_CACHE = ROOT / ".cache/phan_tich_loi"
# Đoạn báo bật nhầm cách phút bật thật gần nhất không quá chừng này (phút) được xem là lệch biên sự kiện.
BIEN_PHUT = 2
# Một sự kiện bật được xem là phát hiện khi ít nhất tỷ lệ này số phút của nó là TP.
NGUONG_PHAT_HIEN = 0.5
# Dự đoán dưới tỷ lệ này của ngưỡng θ được xem là "gần 0" khi phân rã FN.
GAN_0 = 0.1
CHECK_COLS = ["mae_w", "f1", "precision", "recall"]
# Bin (cạnh, nhãn) cho tỷ lệ phát hiện sự kiện theo thời lượng (phút), công suất đỉnh (W) và điện nền (W).
BINS = {
    "thoi_luong": ([0, 1, 3, 10, 30, 60, np.inf], ["1", "2–3", "4–10", "11–30", "31–60", ">60"]),
    "cong_suat_dinh": ([0, 300, 500, 1000, 2000, 3000, np.inf], ["<300", "300–500", "500–1000", "1000–2000", "2000–3000", "≥3000"]),
    "nen_tb": ([-np.inf, 200, 500, 1000, 2000, np.inf], ["<200", "200–500", "500–1000", "1000–2000", "≥2000"]),
}


def build_model(path: Path, device: str):
    ckpt = torch.load(path, map_location=device, weights_only=True)
    if "detector_config" in ckpt:
        # Cấu hình lưu dạng dict (asdict); dựng lại dataclass trước constructor.
        model = TwoStageNILMFormer(GRUConfig(**ckpt["detector_config"]), NILMFormerConfig(**ckpt["regressor_config"]), ckpt["threshold"])
    else:
        model = NILMFormer(BaselineConfig(**ckpt["model_config"]))
    model.load_state_dict(ckpt["model"])
    return model.to(device).eval()


def predict_all(cache: Path, device: str, batch_size: int) -> None:
    dataset = REFITCSVDataset(DATA_DIR, "test")
    dataset.shards = [row for row in dataset.shards if row["house"] in STUDY_HOUSES]
    dataset.ends = np.cumsum([row["windows"] for row in dataset.shards])
    for name, run in RUNS.items():
        for group in GROUPS:
            path = cache / f"{name}_{group}.npz"
            if path.exists():
                continue
            outputs: dict[int, list] = {h: [] for h in STUDY_HOUSES}
            for seed in SEEDS:
                model = build_model(run / group / f"seed_{seed}" / "best.pt", device)
                for house in STUDY_HOUSES:
                    outputs[house].append(predict_house(model, dataset, house, batch_size, device))
                del model
                torch.cuda.empty_cache()
            arrays = {}
            for house in STUDY_HOUSES:
                ens = ensemble_outputs(outputs.pop(house))
                arrays[f"pred_{house}"] = ens["prediction"].numpy()  # (N, C, L), W
                if "detector_on" in ens:
                    arrays[f"det_{house}"] = ens["detector_on"].numpy()
                data_path = cache / f"du_lieu_{house:02d}.npz"
                if not data_path.exists():
                    np.savez_compressed(data_path, **{k: ens[k].numpy() for k in ("power", "on", "valid", "aggregate", "start_time_ns")})
            np.savez_compressed(path, **arrays)
            print(f"Đã lưu dự đoán ensemble {name} {group}", flush=True)


def load_pair(cache: Path, name: str, group: str, house: int) -> dict[str, torch.Tensor]:
    data = np.load(cache / f"du_lieu_{house:02d}.npz")
    pred = np.load(cache / f"{name}_{group}.npz")
    tensors = {k: torch.from_numpy(data[k]) for k in data.files}
    tensors["prediction"] = torch.from_numpy(pred[f"pred_{house}"])
    if f"det_{house}" in pred.files:
        tensors["detector_on"] = torch.from_numpy(pred[f"det_{house}"])
    return tensors


def verify(cache: Path, thresholds: list[float]) -> pd.DataFrame:
    rows = []
    for name, run in RUNS.items():
        ref = pd.read_csv(run / "test_metrics.csv")
        for group in GROUPS:
            train = "6,9,11,20" if group == "pooled" else str(int(group[-2:]))
            for house in STUDY_HOUSES:
                for row in house_metric_rows(load_pair(cache, name, group, house), DEVICES, thresholds, 60):
                    hit = ref[(ref.train_houses.astype(str) == train) & (ref.house == house) & (ref.device == row["device"])]
                    assert len(hit) == 1, f"Không tìm thấy dòng duy nhất trong test_metrics cho {name} {group} hộ {house} {row['device']}."
                    out = {"model": name, "group": group, "house": house, "device": row["device"]}
                    for col in CHECK_COLS:
                        a, b = float(row[col]), float(hit[col].iloc[0])
                        out[f"{col}_tai_tao"], out[f"{col}_goc"] = a, b
                        out[f"{col}_lech"] = 0.0 if (np.isnan(a) and np.isnan(b)) else abs(a - b)
                    rows.append(out)
    frame = pd.DataFrame(rows)
    frame["lech_lon_nhat"] = frame[[f"{c}_lech" for c in CHECK_COLS]].max(axis=1)
    return frame


def runs_of(mask: np.ndarray, minute: np.ndarray) -> list[tuple[int, int]]:
    # Các đoạn liên tiếp [đầu, cuối] (chỉ số mảng, cuối bao gồm) của mask đúng; ngắt khi thời gian nhảy quá một phút.
    idx = np.flatnonzero(mask)
    if not len(idx):
        return []
    breaks = np.flatnonzero(np.diff(minute[idx]) != 1)
    return list(zip(idx[np.r_[0, breaks + 1]].tolist(), idx[np.r_[breaks, len(idx) - 1]].tolist(), strict=True))


def flatten(tensors: dict[str, torch.Tensor]) -> dict[str, np.ndarray]:
    # (N, C, L) → (N·L, C) theo thứ tự thời gian; (N, L) → (N·L,).
    n, c, length = tensors["power"].shape
    minute = (tensors["start_time_ns"].numpy()[:, None] // (60 * 10**9) + np.arange(length)[None, :]).reshape(-1)
    order = np.argsort(minute, kind="stable")
    assert np.all(np.diff(minute[order]) > 0), "Các phút test bị trùng thời điểm."
    flat = {k: tensors[k].numpy().transpose(0, 2, 1).reshape(n * length, c)[order] for k in ("power", "on", "valid", "prediction")}
    flat["on"] = flat["on"] == 1
    flat["aggregate"] = tensors["aggregate"].numpy().reshape(-1)[order]
    flat["minute"] = minute[order]
    return flat


def analyse_pair(flat: dict[str, np.ndarray], thresholds: list[float], keys: dict) -> tuple[list, list, list]:
    y, yhat, on, valid, agg, minute = flat["power"], flat["prediction"], flat["on"], flat["valid"], flat["aggregate"], flat["minute"]
    hour = (minute % 1440) // 60
    # Tải không giám sát = điện tổng − tổng công suất thật bốn thiết bị đích (kênh thiếu đã là 0).
    unmonitored = agg - y.sum(axis=1)
    on_valid = on & valid
    minutes, acts, fps = [], [], []
    for c, dev in enumerate(DEVICES):
        if keys["low_support"][dev]:
            continue
        theta = thresholds[c]
        v = valid[:, c]
        pred_on = yhat[:, c] >= theta
        others = np.delete(on_valid, c, axis=1).sum(axis=1)
        cls = np.where(on[:, c], np.where(pred_on, "TP", "FN"), np.where(pred_on, "FP", "TN"))
        # Vị trí phút bật trong sự kiện: biên (phút đầu/cuối) hay giữa.
        position = np.full(len(y), "", dtype=object)
        act_runs = runs_of(on[:, c] & v, minute)
        for a, b in act_runs:
            position[a : b + 1] = "giữa"
            position[[a, b]] = "biên"
        # Phân rã FN theo phút: trần nhãn (y < θ) / gần 0 / thiếu biên độ.
        fn_cause = np.where(y[:, c] < theta, "trần nhãn", np.where(yhat[:, c] < GAN_0 * theta, "dự đoán gần 0", "thiếu biên độ"))
        keep = v & (cls != "TN")
        part = pd.DataFrame(
            {
                "lop": cls[keep],
                "y": y[keep, c],
                "yhat": yhat[keep, c],
                "dien_tong": agg[keep],
                "nen": agg[keep] - y[keep, c],
                "khong_giam_sat": unmonitored[keep],
                "so_tb_khac_bat": others[keep],
                "gio": hour[keep],
                "vi_tri": position[keep],
                "bat_mot_phan": on[keep, c] & (y[keep, c] < theta),
                "nguyen_nhan_fn": np.where(cls[keep] == "FN", fn_cause[keep], ""),
            }
        )
        part["device"] = dev
        minutes.append(part)
        # TN chỉ đếm, không lưu từng phút để giữ bộ nhớ nhỏ.
        minutes.append(pd.DataFrame({"lop": ["TN"], "so_phut_tn": [int((v & (cls == "TN")).sum())], "device": [dev]}))
        for a, b in act_runs:
            s = slice(a, b + 1)
            tp_frac = float(pred_on[s].mean())
            acts.append(
                {
                    "device": dev,
                    "bat_dau": int(minute[a]),
                    "thoi_luong": b - a + 1,
                    "cong_suat_tb": float(y[s, c].mean()),
                    "cong_suat_dinh": float(y[s, c].max()),
                    "nang_luong_kwh": float(y[s, c].sum() / 60_000),
                    "nang_luong_du_doan_kwh": float(yhat[s, c].sum() / 60_000),
                    "dien_tong_tb": float(agg[s].mean()),
                    "nen_tb": float((agg[s] - y[s, c]).mean()),
                    "khong_giam_sat_tb": float(unmonitored[s].mean()),
                    "co_tb_khac_bat": bool((others[s] > 0).any()),
                    "gio": int(hour[a]),
                    "ty_le_phut_bat_mot_phan": float((y[s, c] < theta).mean()),
                    "ty_le_tp": tp_frac,
                    "trang_thai": "phát hiện" if tp_frac >= NGUONG_PHAT_HIEN else ("phát hiện một phần" if tp_frac > 0 else "bỏ sót"),
                }
            )
        on_minutes = minute[on[:, c] & v]
        for a, b in runs_of(pred_on & ~on[:, c] & v, minute):
            s = slice(a, b + 1)
            # Khoảng cách (phút) từ đoạn FP tới phút bật thật gần nhất của cùng thiết bị.
            pos = np.searchsorted(on_minutes, minute[a])
            near = [minute[a] - on_minutes[pos - 1]] if pos > 0 else []
            pos_b = np.searchsorted(on_minutes, minute[b])
            near += [on_minutes[pos_b] - minute[b]] if pos_b < len(on_minutes) else []
            gap = min(near) if near else np.inf
            other_names = [DEVICES[j] for j in range(4) if j != c and on_valid[s, j].any()]
            if gap <= BIEN_PHUT:
                cause = "lệch biên sự kiện thật"
            elif other_names:
                cause = "trùng thiết bị đích khác"
            elif unmonitored[s].mean() >= theta:
                cause = "trùng tải không giám sát lớn"
            else:
                cause = "khác"
            fps.append(
                {
                    "device": dev,
                    "thoi_luong": b - a + 1,
                    "du_doan_tb": float(yhat[s, c].mean()),
                    "dien_tong_tb": float(agg[s].mean()),
                    "khong_giam_sat_tb": float(unmonitored[s].mean()),
                    "khoang_cach_phut": float(gap),
                    "thiet_bi_khac": ",".join(other_names),
                    "gio": int(hour[a]),
                    "nguyen_nhan": cause,
                }
            )
    meta = {k: v for k, v in keys.items() if k != "low_support"}
    return [m.assign(**meta) for m in minutes], [{**meta, **a} for a in acts], [{**meta, **f} for f in fps]


def q(series: pd.Series) -> str:
    # Trung vị [Q1; Q3] để so phân phối giữa các nhóm.
    if series.empty:
        return ""
    return f"{series.median():.1f} [{series.quantile(0.25):.1f}; {series.quantile(0.75):.1f}]"


def summaries(minutes: pd.DataFrame, acts: pd.DataFrame, fps: pd.DataFrame, thresholds: list[float]) -> dict[str, pd.DataFrame]:
    ctx = ["model", "thiet_ke", "boi_canh"]
    out = {}
    # 1) Theo phút: số phút từng lớp và đặc trưng trung vị theo lớp.
    tn = minutes[minutes.lop == "TN"].groupby(ctx + ["device"]).so_phut_tn.sum().rename("TN")
    m = minutes[minutes.lop != "TN"].copy()
    m["sai_so_bien_do"] = np.where(m.lop == "TP", (m.yhat - m.y).abs() / m.y.clip(lower=1), np.nan)
    rows = []
    for key, g in m.groupby(ctx + ["device", "lop"]):
        rows.append(
            {
                **dict(zip(ctx + ["device", "lop"], key, strict=True)),
                "so_phut": len(g),
                "y_tb_W": q(g.y),
                "yhat_W": q(g.yhat),
                "dien_tong_W": q(g.dien_tong),
                "nen_W": q(g.nen),
                "khong_giam_sat_W": q(g.khong_giam_sat),
                "ty_le_co_tb_khac_bat": (g.so_tb_khac_bat > 0).mean(),
                "ty_le_phut_bien": (g.vi_tri == "biên").mean() if key[-1] != "FP" else np.nan,
                "ty_le_bat_mot_phan": g.bat_mot_phan.mean() if key[-1] != "FP" else np.nan,
                "sai_so_bien_do_tp": q(g.sai_so_bien_do.dropna() * 100) if key[-1] == "TP" else "",
            }
        )
    out["lop_theo_phut"] = pd.DataFrame(rows).merge(tn.reset_index(), on=ctx + ["device"], how="left")
    # 2) Theo sự kiện: đặc trưng của sự kiện phát hiện / một phần / bỏ sót.
    rows = []
    for key, g in acts.groupby(ctx + ["device", "trang_thai"]):
        rows.append(
            {
                **dict(zip(ctx + ["device", "trang_thai"], key, strict=True)),
                "so_su_kien": len(g),
                "thoi_luong_phut": q(g.thoi_luong),
                "cong_suat_dinh_W": q(g.cong_suat_dinh),
                "cong_suat_tb_W": q(g.cong_suat_tb),
                "nang_luong_Wh": q(g.nang_luong_kwh * 1000),
                "nen_tb_W": q(g.nen_tb),
                "khong_giam_sat_tb_W": q(g.khong_giam_sat_tb),
                "ty_le_co_tb_khac_bat": g.co_tb_khac_bat.mean(),
                "ty_le_dinh_duoi_nguong": (g.cong_suat_dinh < g.device.map(dict(zip(DEVICES, thresholds, strict=True)))).mean(),
                "ty_le_phut_bat_mot_phan_tb": g.ty_le_phut_bat_mot_phan.mean(),
                "gio_trung_vi": g.gio.median(),
            }
        )
    out["su_kien_theo_trang_thai"] = pd.DataFrame(rows)
    # 3) Tỷ lệ phát hiện theo bin thời lượng, công suất đỉnh, điện nền.
    rows = []
    for feat, (edges, labels) in BINS.items():
        binned = acts.assign(bin=pd.cut(acts[feat], edges, labels=labels, right=True))
        for key, g in binned.groupby(ctx + ["device", "bin"], observed=True):
            rows.append({**dict(zip(ctx + ["device", "bin"], key, strict=True)), "dac_trung": feat, "so_su_kien": len(g), "ty_le_phat_hien": (g.trang_thai == "phát hiện").mean()})
    out["ty_le_phat_hien_theo_bin"] = pd.DataFrame(rows)
    # 4) Cơ cấu nguyên nhân FN (phút) và FP (đoạn, phút).
    fn = m[m.lop == "FN"].groupby(ctx + ["device", "nguyen_nhan_fn"]).size().rename("so_phut").reset_index()
    fn["ty_le"] = fn.so_phut / fn.groupby(ctx + ["device"]).so_phut.transform("sum")
    out["nguyen_nhan_fn"] = fn
    fp = fps.groupby(ctx + ["device", "nguyen_nhan"]).agg(so_doan=("thoi_luong", "size"), so_phut=("thoi_luong", "sum"), thoi_luong_trung_vi=("thoi_luong", "median")).reset_index()
    fp["ty_le_phut"] = fp.so_phut / fp.groupby(ctx + ["device"]).so_phut.transform("sum")
    out["nguyen_nhan_fp"] = fp
    # Thiết bị đích nào trùng với FP do nhầm lẫn.
    conf = fps[fps.nguyen_nhan == "trùng thiết bị đích khác"].assign(thiet_bi_khac=lambda d: d.thiet_bi_khac.str.split(",")).explode("thiet_bi_khac")
    out["fp_nham_thiet_bi"] = conf.groupby(ctx + ["device", "thiet_bi_khac"]).thoi_luong.agg(so_doan="size", so_phut="sum").reset_index()
    # 5) So 2Stage với Baseline trên cùng sự kiện: nhóm 2Stage sửa được / làm tệ hơn.
    key = ["thiet_ke", "boi_canh", "group", "house", "device", "bat_dau"]
    a = acts[acts.model == "2Stage"].set_index(key)
    b = acts[acts.model == "Baseline"].set_index(key)
    assert a.index.equals(b.index) or a.index.sort_values().equals(b.index.sort_values()), "Hai mô hình phải có cùng tập sự kiện bật."
    both = a.join(b[["trang_thai", "ty_le_tp", "nang_luong_du_doan_kwh"]].add_suffix("_bl")).reset_index()
    da, db = both.trang_thai == "phát hiện", both.trang_thai_bl == "phát hiện"
    both["chuyen"] = np.select([da & db, da & ~db, ~da & db], ["cả hai phát hiện", "chỉ 2Stage phát hiện", "chỉ Baseline phát hiện"], "cả hai bỏ sót")
    rows = []
    for k, g in both.groupby(["thiet_ke", "boi_canh", "device", "chuyen"]):
        rows.append(
            {
                **dict(zip(["thiet_ke", "boi_canh", "device", "chuyen"], k, strict=True)),
                "so_su_kien": len(g),
                "thoi_luong_phut": q(g.thoi_luong),
                "cong_suat_dinh_W": q(g.cong_suat_dinh),
                "nen_tb_W": q(g.nen_tb),
                "ty_le_co_tb_khac_bat": g.co_tb_khac_bat.mean(),
                "ty_le_phut_bat_mot_phan_tb": g.ty_le_phut_bat_mot_phan.mean(),
            }
        )
    trans = pd.DataFrame(rows)
    trans["ty_le"] = trans.so_su_kien / trans.groupby(["thiet_ke", "boi_canh", "device"]).so_su_kien.transform("sum")
    out["so_sanh_2stage_baseline"] = trans
    return out


def figures(acts: pd.DataFrame, fps: pd.DataFrame, s: dict[str, pd.DataFrame]) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT_FIG.mkdir(parents=True, exist_ok=True)
    paths = []
    colors = {"2Stage": "#1f77b4", "Baseline": "#d62728"}
    styles = {"hộ được train": "-", "hộ mới": "--"}
    # Hình 1–2: tỷ lệ phát hiện sự kiện theo thời lượng và công suất đỉnh (gộp hai thiết kế, tách bối cảnh).
    panels = [
        ("thoi_luong", "Thời lượng sự kiện bật (phút)", "loi_ty_le_phat_hien_thoi_luong.png"),
        ("cong_suat_dinh", "Công suất đỉnh theo phút của sự kiện (W)", "loi_ty_le_phat_hien_cong_suat_dinh.png"),
    ]
    for feat, xlabel, fname in panels:
        t = s["ty_le_phat_hien_theo_bin"]
        t = t[t.dac_trung == feat]
        fig, axes = plt.subplots(1, 4, figsize=(18, 4.4), sharey=True)
        for ax, dev in zip(axes, DEVICES, strict=True):
            d = t[t.device == dev]
            order = [b for b in BINS[feat][1] if b in set(d.bin)]
            for (model, ctx), g in d.groupby(["model", "boi_canh"]):
                # Gộp hai thiết kế theo trung bình có trọng số số sự kiện.
                w = g.groupby("bin", observed=True).apply(lambda x: np.average(x.ty_le_phat_hien, weights=x.so_su_kien), include_groups=False).reindex(order)
                ax.plot(range(len(order)), w.values, styles[ctx], color=colors[model], marker="o", label=f"{model} – {ctx}")
            ax.set_xticks(range(len(order)), order, rotation=30)
            ax.set_title(dev)
            ax.set_xlabel(xlabel)
            ax.grid(alpha=0.3)
        axes[0].set_ylabel("Tỷ lệ sự kiện được phát hiện (≥ 50% phút TP)")
        axes[0].legend(fontsize=8)
        fig.suptitle(f"Tỷ lệ phát hiện sự kiện bật theo {xlabel.split(' (')[0].lower()} (gộp mô hình chung và mô hình riêng)")
        fig.tight_layout()
        fig.savefig(OUT_FIG / fname, dpi=150)
        plt.close(fig)
        paths.append(OUT_FIG / fname)
    # Hình 3: phân phối đặc trưng sự kiện phát hiện vs bỏ sót (2Stage, hộ mới, gộp hai thiết kế).
    d = acts[(acts.model == "2Stage") & (acts.boi_canh == "hộ mới") & (acts.trang_thai != "phát hiện một phần")]
    feats = [("thoi_luong", "Thời lượng (phút, thang log)", True), ("cong_suat_dinh", "Công suất đỉnh (W)", False), ("nen_tb", "Điện nền trung bình (W)", False)]
    fig, axes = plt.subplots(1, 3, figsize=(18, 4.8))
    for ax, (feat, label, log) in zip(axes, feats, strict=True):
        data, pos, ticks = [], [], []
        for i, dev in enumerate(DEVICES):
            for j, st in enumerate(["phát hiện", "bỏ sót"]):
                data.append(d[(d.device == dev) & (d.trang_thai == st)][feat].to_numpy())
                pos.append(i * 3 + j)
            ticks.append(i * 3 + 0.5)
        bp = ax.boxplot(data, positions=pos, widths=0.8, showfliers=False, patch_artist=True)
        for k, box in enumerate(bp["boxes"]):
            box.set_facecolor("#9ecae1" if k % 2 == 0 else "#fc9272")
        ax.set_xticks(ticks, DEVICES)
        ax.set_ylabel(label)
        if log:
            ax.set_yscale("log")
        ax.grid(alpha=0.3, axis="y")
    axes[0].legend([bp["boxes"][0], bp["boxes"][1]], ["Phát hiện", "Bỏ sót"])
    fig.suptitle("2Stage trên hộ mới: đặc trưng của sự kiện được phát hiện và bị bỏ sót (hộp = Q1–Q3, vạch = trung vị)")
    fig.tight_layout()
    fig.savefig(OUT_FIG / "loi_dac_trung_phat_hien_bo_sot.png", dpi=150)
    plt.close(fig)
    paths.append(OUT_FIG / "loi_dac_trung_phat_hien_bo_sot.png")
    # Hình 4: cơ cấu nguyên nhân FN và FP theo thiết bị, mô hình, bối cảnh.
    fig, axes = plt.subplots(1, 2, figsize=(18, 6.5))
    for ax, (table, col, val, title) in zip(
        axes,
        [(s["nguyen_nhan_fn"], "nguyen_nhan_fn", "so_phut", "Nguyên nhân phút bỏ sót (FN)"), (s["nguyen_nhan_fp"], "nguyen_nhan", "so_phut", "Nguyên nhân phút báo bật nhầm (FP)")],
        strict=True,
    ):
        p = table.groupby(["device", "model", "boi_canh", col])[val].sum().unstack(col).fillna(0)
        p = p.div(p.sum(axis=1), axis=0).reindex([(dv, m, c) for dv in DEVICES for m in ["2Stage", "Baseline"] for c in ["hộ được train", "hộ mới"]])
        left = np.zeros(len(p))
        for k, cause in enumerate(p.columns):
            ax.barh(range(len(p)), p[cause], left=left, label=cause, color=plt.cm.Set2(k))
            left += p[cause].to_numpy()
        ax.set_yticks(range(len(p)), [f"{dv} | {m} | {c}" for dv, m, c in p.index], fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Tỷ lệ số phút")
        ax.set_title(title)
        ax.legend(fontsize=8, loc="lower right")
    fig.suptitle("Cơ cấu nguyên nhân lỗi theo thiết bị, mô hình và bối cảnh (gộp hai thiết kế)")
    fig.tight_layout()
    fig.savefig(OUT_FIG / "loi_co_cau_nguyen_nhan.png", dpi=150)
    plt.close(fig)
    paths.append(OUT_FIG / "loi_co_cau_nguyen_nhan.png")
    # Hình 5: chuyển trạng thái phát hiện Baseline → 2Stage trên cùng sự kiện.
    t = s["so_sanh_2stage_baseline"].groupby(["device", "boi_canh", "chuyen"]).so_su_kien.sum().unstack("chuyen").fillna(0)
    t = t.div(t.sum(axis=1), axis=0).reindex([(dv, c) for dv in DEVICES for c in ["hộ được train", "hộ mới"]])
    order = ["cả hai phát hiện", "chỉ 2Stage phát hiện", "chỉ Baseline phát hiện", "cả hai bỏ sót"]
    cols = ["#74c476", "#1f77b4", "#d62728", "#bdbdbd"]
    fig, ax = plt.subplots(figsize=(11, 5))
    left = np.zeros(len(t))
    for cause, color in zip(order, cols, strict=True):
        ax.barh(range(len(t)), t[cause], left=left, label=cause, color=color)
        for i, (lv, v) in enumerate(zip(left, t[cause], strict=True)):
            if v >= 0.04:
                ax.text(lv + v / 2, i, f"{v * 100:.0f}%", ha="center", va="center", fontsize=8)
        left += t[cause].to_numpy()
    ax.set_yticks(range(len(t)), [f"{dv} | {c}" for dv, c in t.index])
    ax.invert_yaxis()
    ax.set_xlabel("Tỷ lệ sự kiện bật")
    ax.set_title("Cùng một sự kiện bật: mô hình nào phát hiện được (gộp hai thiết kế)")
    ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT_FIG / "loi_2stage_vs_baseline_su_kien.png", dpi=150)
    plt.close(fig)
    paths.append(OUT_FIG / "loi_2stage_vs_baseline_su_kien.png")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Phân tích lỗi có chủ đích cho 2Stage và Baseline.")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    torch.set_num_threads(1)
    # Bật chế độ xác định như lúc chạy thực nghiệm để tái tạo đúng dự đoán.
    seed_everything(BASE_SEED)
    assert torch.cuda.is_available(), "Cần GPU CUDA để tái tạo dự đoán trong thời gian hợp lý."
    args.cache.mkdir(parents=True, exist_ok=True)
    OUT_CSV.mkdir(parents=True, exist_ok=True)
    predict_all(args.cache, "cuda", args.batch_size)
    import json

    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    thresholds = [manifest["thresholds_w"][d][0] for d in DEVICES]
    check = verify(args.cache, thresholds)
    check.to_csv(OUT_CSV / "kiem_chung_tai_tao.csv", index=False)
    worst = check.lech_lon_nhat.max()
    print(f"Kiểm chứng {len(check)} cặp; sai khác lớn nhất {worst:.3e}", flush=True)
    assert worst <= 1e-6, "Dự đoán tái tạo lệch so với test_metrics.csv quá 1e-6; dừng phân tích."
    ref = pd.read_csv(RUNS["2Stage"] / "test_metrics.csv")
    minutes, acts, fps = [], [], []
    for group in GROUPS:
        train = [6, 9, 11, 20] if group == "pooled" else [int(group[-2:])]
        for house in STUDY_HOUSES:
            sub = ref[(ref.train_houses.astype(str) == ",".join(map(str, train))) & (ref.house == house)]
            low = dict(zip(sub.device, sub.low_support, strict=True))
            for name in RUNS:
                keys = {
                    "model": name,
                    "thiet_ke": "mô hình chung" if group == "pooled" else "mô hình riêng",
                    "boi_canh": "hộ được train" if house in train else "hộ mới",
                    "group": group,
                    "house": house,
                    "low_support": low,
                }
                m, a, f = analyse_pair(flatten(load_pair(args.cache, name, group, house)), thresholds, keys)
                minutes.extend(m)
                acts.extend(a)
                fps.extend(f)
    minutes, acts, fps = pd.concat(minutes, ignore_index=True), pd.DataFrame(acts), pd.DataFrame(fps)
    # Bảng chi tiết theo sự kiện và theo đoạn FP: bài báo dẫn một số tỷ lệ tính trực tiếp từ hai bảng này.
    acts.to_csv(OUT_CSV / "su_kien_bat.csv.gz", index=False)
    fps.to_csv(OUT_CSV / "doan_fp.csv.gz", index=False)
    s = summaries(minutes, acts, fps, thresholds)
    for name, frame in s.items():
        frame.to_csv(OUT_CSV / f"{name}.csv", index=False)
    for path in figures(acts, fps, s):
        print(f"Đã lưu hình {path}")
    print(f"Xong: {len(acts)} sự kiện bật, {len(fps)} đoạn FP. CSV ở {OUT_CSV}")


if __name__ == "__main__":
    main()
