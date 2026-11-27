"""Sinh reports/ket_qua_thuc_nghiem.md từ kết quả runner của TwoStage và NILMFormer.

Chạy lại sau mỗi lần có kết quả mới:
    uv run python reports/tao_bao_cao_ket_qua.py --twostage-run <thư mục> --baseline-run <thư mục>
"""

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NONE_CONTEXT = "Không thiết bị đích khác bật"
MARKER = "<!-- có nhận xét viết tay -->"
DEVICES = ["Dishwasher", "Kettle", "WashingMachine", "Microwave"]
# cột → (tên hiển thị, càng cao càng tốt hay không (None: không so), số chữ số thập phân).
M = {
    "precision": ("Precision", True, 3),
    "recall": ("Recall", True, 3),
    "f1": ("F1", True, 3),
    "accuracy": ("Accuracy", True, 4),
    "mae_w": ("MAE (W)", False, 1),
    "rmse_w": ("RMSE (W)", False, 1),
    "nde": ("NDE", False, 3),
    "sae": ("SAE", False, 3),
    "energy_error_kwh": ("Sai số năng lượng (kWh)", False, 2),
    "nep": ("NEP", False, 3),
    "teca": ("TECA", True, 3),
    "mr": ("MR", True, 3),
    "fp": ("Phút báo bật nhầm", False, 0),
    "fn_none": ("FN khi không thiết bị khác bật (%)", None, 1),
    "fp_other": ("FP khi thiết bị khác đang bật (%)", None, 1),
}
NHOM = [
    ("Dự đoán bật/tắt", ["precision", "recall", "f1", "accuracy"]),
    ("Dự đoán công suất", ["mae_w", "rmse_w", "nde"]),
    ("Dự đoán năng lượng", ["sae", "energy_error_kwh", "nep", "teca", "mr"]),
]


def so(value, digits):
    if value is None or pd.isna(value):
        return "–"
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def bang(rows, bigs, subs, value):
    # rows: [(nhãn hàng, metric)]; value(metric, nhãn hàng, cột lớn, cột nhỏ) → số hoặc None. In đậm giá trị tốt nhất trong mỗi cột lớn.
    head = [
        "<table>",
        "  <thead>",
        '    <tr><th rowspan="2">Chỉ số</th>' + "".join(f'<th colspan="{len(subs)}">{b}</th>' for b in bigs) + "</tr>",
        "    <tr>" + "".join(f"<th>{s}</th>" for _ in bigs for s in subs) + "</tr>",
        "  </thead>",
        "  <tbody>",
    ]
    body = []
    for label, metric in rows:
        name, higher, digits = M[metric]
        cells = []
        for big in bigs:
            values = [value(metric, label, big, sub) for sub in subs]
            texts = [so(v, digits) for v in values]
            shown = [(float(t.replace(" ", "").replace(",", ".")), i) for i, t in enumerate(texts) if t != "–"]
            if higher is not None and len(shown) > 1 and len({v for v, _ in shown}) > 1:
                best = (max if higher else min)(shown)[0]
                texts = [f"<b>{t}</b>" if t != "–" and float(t.replace(" ", "").replace(",", ".")) == best else t for t in texts]
            cells += texts
        arrow = "" if higher is None else (" ↑" if higher else " ↓")
        title = f"{label} – {name}{arrow}" if label else f"{name}{arrow}"
        body.append(f"    <tr><td>{title}</td>" + "".join(f'<td align="right">{c}</td>' for c in cells) + "</tr>")
    return "\n".join(head + body + ["  </tbody>", "</table>", ""])


def nap(run_dir, ten):
    run_dir = Path(run_dir)
    study = json.loads((run_dir / "study.json").read_text(encoding="utf-8"))
    out = {"study": study, "dir": run_dir}
    for key, name in [("metrics", "test_metrics.csv"), ("strata", "stratified_metrics.csv"), ("errors", "error_analysis.csv")]:
        frame = pd.read_csv(run_dir / name)
        frame["train_houses"] = frame["train_houses"].astype(str)
        out[key] = frame.assign(mo_hinh=ten)
    houses = [str(h) for h in study["houses"]]
    done = set(out["metrics"]["train_houses"].unique())
    out["pooled_done"] = ",".join(str(h) for h in study["pooled_train_houses"]) in done
    out["cross_done"] = {h for h in houses if h in done}
    out["cross_complete"] = out["cross_done"] == set(houses)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--twostage-run", default=str(ROOT / "training/runs/twostage_20261126_042442"))
    parser.add_argument("--baseline-run", default=str(ROOT / "training/runs/nilmformer_20261126_042452"))
    parser.add_argument("--output", default=str(ROOT / "reports/ket_qua_thuc_nghiem.md"))
    parser.add_argument("--force", action="store_true", help="Ghi đè cả báo cáo đã có phần nhận xét viết tay.")
    args = parser.parse_args()
    runs = {"2Stage": nap(args.twostage_run, "2Stage"), "Baseline": nap(args.baseline_run, "Baseline")}
    base = runs["Baseline"]
    assert base["pooled_done"] and base["cross_complete"], "Baseline phải có đủ kết quả mới sinh được báo cáo."
    assert runs["2Stage"]["study"]["pooled_train_houses"] == base["study"]["pooled_train_houses"], "Hai lượt chạy phải dùng cùng cách chia hộ."
    houses = [str(h) for h in base["study"]["houses"]]
    pooled_train = [str(h) for h in base["study"]["pooled_train_houses"]]
    pooled_key = ",".join(pooled_train)
    unseen_pooled = [h for h in houses if h not in pooled_train]
    # Cặp ít phút bật chỉ phụ thuộc nhãn test nên giống nhau giữa hai mô hình.
    low = base["metrics"].loc[base["metrics"]["low_support"], ["house", "device"]].drop_duplicates()
    low_pairs = set(map(tuple, low.to_numpy()))

    def keep(frame):
        return frame[[(h, d) not in low_pairs for h, d in zip(frame["house"], frame["device"], strict=True)]]

    def cross(model):
        run = runs[model]
        if not run["cross_complete"]:
            return None
        frame = keep(run["metrics"])
        return frame[frame["protocol"] == "cross_house"]

    # ---------- Câu hỏi 1 ----------
    rq1_bigs, models = ["Hộ được train", "Hộ mới"], ["2Stage", "Baseline"]

    def rq1_value(frame_fn, metric, label, big, model, extra=None):
        frame = frame_fn(model)
        if frame is None:
            return None
        frame = frame[frame["unseen_house"] == (big == "Hộ mới")]
        if extra is not None:
            frame = extra(frame, label)
        if frame.empty:
            return None
        return frame[metric].sum() if metric == "fp" else frame[metric].mean()

    lines = ["# Kết quả thực nghiệm: TwoStageNILMFormer (đề xuất) và NILMFormer (baseline)", ""]
    status = []
    for model in models:
        run = runs[model]
        status.append(f"- {model}: `{run['dir'].relative_to(ROOT)}`; mô hình chung {'đã có' if run['pooled_done'] else 'chưa có'}; mô hình một hộ {len(run['cross_done'])}/{len(houses)} hộ.")
    lines += [
        "TwoStageNILMFormer (2Stage) là phương pháp đề xuất, cải tiến từ NILMFormer bằng bộ phát hiện bật/tắt GRU",
        "và mask đầu ra; NILMFormer gốc là baseline. Hai mô hình dùng chung dữ liệu, cách chia hộ, 5 seed,",
        'early stopping và hàm đánh giá. Ô ghi "–" là kết quả chưa có vì lượt chạy chưa xong.',
        "",
        "Trạng thái kết quả:",
        "",
        *status,
        "",
        "## Thiết lập chung",
        "",
        f"- REFIT, bảy hộ nghiên cứu {', '.join(houses)}; bốn thiết bị WashingMachine, Dishwasher, Kettle,",
        "  Microwave; cửa sổ 128 phút, mẫu 1 phút. Mỗi hộ chia theo thời gian: 80% đầu train, 20% cuối test.",
        "- Mỗi mô hình là ensemble 5 seed: trung bình công suất dự đoán rồi tính chỉ số một lần. Early",
        "  stopping theo validation loss (20% cuối phần train), patience 10, tối đa 150 epoch.",
        "- Mỗi ô là trung bình macro theo cặp (hộ train, hộ test, thiết bị). Loại các cặp có dưới 60 phút",
        f"  bật trong test: {', '.join(f'{d} hộ {h}' for h, d in sorted(low_pairs))}.",
        "- ↑: càng cao càng tốt; ↓: càng thấp càng tốt; in đậm là giá trị tốt nhất trong cột lớn.",
        "  Công thức và ý nghĩa chỉ số: `reports/chi_so_danh_gia_nilm.md`.",
        "",
        "## Câu hỏi 1. Hiệu năng NILM ở hộ mới",
        "",
        "Ứng với yêu cầu 1: đo sai số điện năng và F1 theo thiết bị, hộ mới, mức tải và số thiết bị bật",
        "đồng thời, với tập test tách theo hộ.",
        "",
        "**Thiết kế (`cross_house`).** Train 7 mô hình, mỗi mô hình chỉ dùng phần train của một hộ, rồi",
        'test trên 20% thời gian cuối của cả bảy hộ. "Hộ được train" là ô mô hình test trên chính hộ đã',
        'train (7 ô mỗi thiết bị); "Hộ mới" là 6 hộ còn lại (42 ô mỗi thiết bị). Phạm vi thiết bị cố định',
        "bốn loại, nên câu hỏi này đo hộ mới chứ không đo loại thiết bị chưa thấy.",
        "",
        "### 1.1. Kết quả tổng thể",
        "",
    ]
    for i, (ten, metrics) in enumerate(NHOM, 1):
        lines += [f"**{ten}**", "", bang([("", m) for m in metrics], rq1_bigs, models, lambda m, lb, b, s: rq1_value(cross, m, lb, b, s)), ""]

    def by(column):
        return lambda frame, label: frame[frame[column].astype(str) == str(label)]

    lines += ["### 1.2. Theo thiết bị", ""]
    rows = [(d, m) for d in DEVICES for m in ["f1", "mae_w", "sae", "energy_error_kwh"]]
    lines += [bang(rows, rq1_bigs, models, lambda m, lb, b, s: rq1_value(cross, m, lb, b, s, by("device"))), ""]
    lines += [
        "### 1.3. Theo hộ test",
        "",
        "Hộ được train: mô hình của chính hộ đó. Hộ mới: trung bình 6 mô hình train trên hộ khác. Trung bình 4 thiết bị.",
        "",
    ]
    rows = [(f"Hộ {h}", m) for h in houses for m in ["f1", "mae_w", "sae"]]

    def house_filter(frame, label):
        return frame[frame["house"].astype(str) == label.removeprefix("Hộ ")]

    lines += [bang(rows, rq1_bigs, models, lambda m, lb, b, s: rq1_value(cross, m, lb, b, s, house_filter)), ""]

    def strata(model, stratum_type):
        frame = cross(model)
        if frame is None:
            return None
        st = keep(runs[model]["strata"])
        return st[(st["protocol"] == "cross_house") & (st["stratum_type"] == stratum_type)]

    lines += [
        "### 1.4. Theo số thiết bị đích bật đồng thời",
        "",
        "Tầng 0 không có phút bật nên chỉ báo MAE và tổng số phút báo bật nhầm.",
        "",
    ]
    rows = [("0", "mae_w"), ("0", "fp")] + [(k, m) for k in ["1", "2", "3+"] for m in ["f1", "mae_w", "sae"]]
    lines += [bang(rows, rq1_bigs, models, lambda m, lb, b, s: rq1_value(lambda mo: strata(mo, "concurrent_on"), m, lb, b, s, by("stratum"))), ""]
    lines += [
        "### 1.5. Theo mức tải điện tổng",
        "",
        "Ngưỡng cố định cho mọi hộ. Ở [0, 500) W rất ít phút bật nên SAE không ổn định.",
        "",
    ]
    load = ["[0, 500)", "[500, 1500)", "[1500, 3000)", "[3000, inf)"]
    rows = [(k, m) for k in load for m in ["f1", "mae_w", "sae"]]
    lines += [bang(rows, rq1_bigs, models, lambda m, lb, b, s: rq1_value(lambda mo: strata(mo, "load_w"), m, lb, b, s, by("stratum"))), ""]

    def error_share(model, label, big, metric):
        frame = cross(model)
        if frame is None:
            return None
        err = keep(runs[model]["errors"])
        err = err[(err["protocol"] == "cross_house") & (err["device"] == label) & (err["unseen_house"] == (big == "Hộ mới"))]
        kind = "FN" if metric == "fn_none" else "FP"
        err = err[err["error_type"] == kind]
        total = err.drop_duplicates(["train_houses", "house"])["error_total"].sum()
        none = err.loc[err["context"] == NONE_CONTEXT, "error_points"].sum()
        if not total:
            return None
        share = none / total if metric == "fn_none" else 1 - none / total
        return 100 * share

    lines += [
        "### 1.6. Phân tích lỗi",
        "",
        "Tỷ lệ phút bỏ sót (FN) xảy ra khi không có thiết bị đích nào khác bật, và tỷ lệ phút báo nhầm (FP)",
        "xảy ra khi có ít nhất một thiết bị đích khác đang bật. Bảng chi tiết theo từng bối cảnh: `error_analysis.csv`.",
        "",
    ]
    rows = [(d, m) for d in DEVICES for m in ["fn_none", "fp_other"]]
    lines += [bang(rows, rq1_bigs, models, lambda m, lb, b, s: error_share(s, lb, b, m)), ""]
    lines += [
        "### 1.7. Đồ thị dự đoán",
        "",
        "Mỗi lượt chạy lưu đồ thị tại `<nhóm>/predictions/house_XX.png`: điện tổng, công suất thật từng",
        "thiết bị, dự đoán ensemble và dải min–max giữa các seed, ở cửa sổ sai số lớn nhất và cửa sổ có",
        "nhiều thiết bị bật nhất. Ví dụ mô hình train trên hộ 2, test trên hộ 3:",
        "",
    ]
    for model in models:
        path = runs[model]["dir"] / "house_02/predictions/house_03.png"
        if path.exists():
            lines += [f"![{model}: train hộ 2, test hộ 3]({Path('..') / path.relative_to(ROOT)})", ""]
        else:
            lines += [f"{model}: chưa có đồ thị.", ""]

    # ---------- Câu hỏi 2 ----------
    configs = [("2Stage", "riêng"), ("2Stage", "chung"), ("Baseline", "riêng"), ("Baseline", "chung")]
    subs = [f"{m} {s}" for m, s in configs]
    groups = {f"Hộ đã có trong mô hình chung ({', '.join(pooled_train)})": pooled_train, f"Hộ mới với mô hình chung ({', '.join(unseen_pooled)})": unseen_pooled}

    def rq2_value(metric, label, big, sub):
        model, setting = sub.split(" ")
        run, wanted = runs[model], groups[big]
        frame = keep(run["metrics"])
        if setting == "chung":
            if not run["pooled_done"]:
                return None
            frame = frame[frame["protocol"] == "pooled"]
        else:
            if not set(wanted) <= run["cross_done"]:
                return None
            frame = frame[(frame["protocol"] == "cross_house") & (frame["train_houses"] == frame["house"].astype(str))]
        frame = frame[frame["house"].astype(str).isin(wanted)]
        return frame[metric].mean() if len(frame) else None

    lines += [
        "## Câu hỏi 2. Lợi ích và chi phí của cá nhân hóa",
        "",
        "Ứng với yêu cầu 3: so NILM baseline, bản đề xuất và bản không cá nhân hóa trên cùng đầu vào.",
        "",
        "**Thiết kế.** Với mỗi hộ test h, so hai cách triển khai trên cùng 20% thời gian cuối của hộ h:",
        "",
        "- **Riêng (cá nhân hóa):** mô hình chỉ train trên dữ liệu đo riêng từng thiết bị của chính hộ h.",
        f"- **Chung (không cá nhân hóa):** một mô hình train trên các hộ {', '.join(pooled_train)}, dùng cho mọi hộ.",
        "",
        "Hai nhóm hộ trả lời hai câu hỏi khác nhau. Với hộ đã có trong mô hình chung, câu hỏi là mô hình",
        "riêng có tốt hơn mô hình chung đã học cả hộ đó không. Với hộ mới, câu hỏi là có đáng đo riêng từng",
        "thiết bị tại hộ mới để train mô hình riêng, thay vì dùng ngay mô hình chung.",
        "",
        "### 2.1. Độ chính xác",
        "",
    ]
    for ten, metrics in NHOM:
        lines += [f"**{ten}**", "", bang([("", m) for m in metrics], list(groups), subs, rq2_value), ""]

    lines += ["### 2.2. Chi phí huấn luyện và dữ liệu", ""]
    windows = {str(r["house"]): r["train_windows"] + r["validation_windows"] for r in base["study"]["validation_splits"]}
    cost = [
        "| Cấu hình | Số mô hình cần train | Dữ liệu đo riêng từng thiết bị tại hộ dùng | Epoch đã chạy (trung vị) | Thời gian train 5 seed (s) |",
        "| --- | ---: | --- | ---: | ---: |",
    ]
    for model, setting in configs:
        frame = runs[model]["metrics"].drop_duplicates(["protocol", "train_houses"])
        if setting == "chung":
            frame = frame[frame["train_houses"] == pooled_key]
            n_models, data = "1 cho mọi hộ", "không cần"
        else:
            frame = frame[frame["protocol"] == "cross_house"]
            days = sum(windows[h] for h in houses) * 128 / 1440 / len(houses)
            n_models, data = "1 mỗi hộ", f"khoảng {days:.0f} ngày (trung bình)"
        if frame.empty:
            cost.append(f"| {model} {setting} | {n_models} | {data} | – | – |")
            continue
        epochs = pd.Series([int(e) for v in frame["epochs_trained"] for e in str(v).split(",")]).median()
        note = "" if setting == "chung" or runs[model]["cross_complete"] else f" ({len(frame)}/{len(houses)} hộ)"
        cost.append(f"| {model} {setting} | {n_models} | {data} | {epochs:.0f} | {so(frame['train_seconds_total'].mean(), 0)}{note} |")
    lines += cost + [
        "",
        "- Thời gian đo trên GPU NVIDIA L40S dùng chung, 1 luồng CPU, chưa tính bước đánh giá.",
        "- Cấu hình riêng: thời gian là trung bình mỗi hộ. Ngoài đồng hồ tổng, cần thêm thiết bị đo cho",
        "  từng thiết bị đích (4 ổ cắm đo) trong thời gian thu dữ liệu train ở mỗi hộ. Số ngày tính từ số",
        "  cửa sổ train và validation hợp lệ, chưa tính các đoạn mất dữ liệu.",
        "- Cấu hình chung: tại hộ mới chỉ cần đồng hồ tổng; chi phí train trả một lần cho mọi hộ.",
        "- Chưa đo độ trễ suy luận và chưa ước tính chi phí theo đơn giá GPU hoặc cấu hình Docker.",
        "",
        "## Giới hạn",
        "",
        "- Hai mô hình có số epoch rất khác nhau dưới cùng quy tắc early stopping: baseline thường dừng",
        "  trước epoch 50. Cần chạy lại baseline với `--patience 20` để kiểm tra độ nhạy.",
        "- F1 đang so trạng thái dự đoán (công suất trung bình phút ≥ ngưỡng) với nhãn tạo ở nhịp 10 giây.",
        "  Kể cả dự đoán đúng hoàn toàn công suất, F1 tối đa chỉ khoảng 0,92 (WashingMachine, Kettle) đến",
        "  0,95 (Microwave).",
        f"- Mô hình chung chỉ có một cách chia hộ; kết quả hộ mới của nó dựa trên {len(unseen_pooled)} hộ.",
        "- Chưa đánh giá loại thiết bị chưa thấy, độ trễ suy luận và bản không trợ lý.",
        "",
    ]
    output = Path(args.output)
    # Báo cáo đã thêm nhận xét viết tay có dấu này; không ghi đè nếu không yêu cầu rõ.
    assert args.force or not output.exists() or MARKER not in output.read_text(encoding="utf-8"), "Báo cáo đã có nhận xét viết tay; dùng --output khác hoặc --force."
    output.write_text("\n".join(lines), encoding="utf-8")
    print("Đã ghi", args.output)


if __name__ == "__main__":
    main()
