import argparse
import hashlib
import json
import math
import time
from collections.abc import Callable, Iterable, Mapping, Sized
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset
from tqdm.auto import tqdm

from .data import REFITCSVDataset
from .metrics import NILMMetricAccumulator, compute_nilm_metrics, state_metrics
from .model.NILMFormer.NILMFormer import NILMFormer
from .model.NILMFormer.NILMFormer import NILMFormerConfig as BaselineConfig
from .model.TwoStageNILMFormer.GRUDetector import GRUConfig
from .model.TwoStageNILMFormer.NILMFormerRegressor import NILMFormerConfig
from .model.TwoStageNILMFormer.TwoStageNILMFormer import TwoStageNILMFormer, TwoStageOutput
from .seeds import BASE_SEED, MODEL_SEED_COUNT, generate_model_seeds, make_data_generator, seed_everything, seed_worker
from .train_nilmformer import train_nilmformer

# Các hộ REFIT có nhãn đủ bốn thiết bị đích; loại hộ 15 vì kênh Kettle có thể là Hi-Fi theo mô tả nguồn.
STUDY_HOUSES = [2, 3, 6, 9, 11, 13, 20]
MODEL_NAMES = {"twostage": "TwoStageNILMFormer", "nilmformer": "NILMFormer"}
# Mức tải theo điện tổng, W; ngưỡng cố định dùng chung mọi hộ và mọi mô hình để so sánh được.
LOAD_BINS_W = [0.0, 500.0, 1500.0, 3000.0, math.inf]
# Cặp hộ × thiết bị có ít phút bật hơn mức này trong test cho F1 và sai số điện năng tương đối không ổn định; loại khỏi bảng tổng hợp.
MIN_TEST_ON_MINUTES = 60


def initialize_twostage_nilmformer(detector_config: GRUConfig, regressor_config: NILMFormerConfig, model_seed: int, threshold: float = 0.5) -> TwoStageNILMFormer:
    # Đặt seed trước constructor để cả detector và regressor nhận trọng số tái lập được.
    seed_everything(model_seed)
    model = TwoStageNILMFormer(detector_config, regressor_config, threshold)
    model.initialization_seed = model_seed
    return model


@dataclass
class TwoStageLossConfig:
    regression_weight: float = 1.0
    detector_weight: float = 1.0
    # Giám sát thêm công suất trước mask tại các điểm thực sự bật giúp regressor vẫn học khi dự đoán tắt nhầm chặn gradient chính.
    auxiliary_on_weight: float = 0.1
    positive_weight: float | list[float] = 1.0

    def __post_init__(self):
        positive_weights = torch.as_tensor(self.positive_weight, dtype=torch.float64)
        weights = (self.regression_weight, self.detector_weight, self.auxiliary_on_weight)

        assert all(torch.isfinite(torch.tensor(v)) and v >= 0 for v in weights), "Trọng số các loss phải hữu hạn và không âm."
        assert positive_weights.ndim <= 1 and positive_weights.numel() > 0, "positive_weight phải là số hoặc danh sách trọng số theo thiết bị."
        assert (torch.isfinite(positive_weights) & (positive_weights > 0)).all(), "Trọng số positive_weight phải hữu hạn và lớn hơn 0."
        assert any(v > 0 for v in weights[:3]), "Ít nhất một trọng số loss phải lớn hơn 0."


def two_stage_loss(output: TwoStageOutput, target_power: torch.Tensor, target_on: torch.Tensor, valid: torch.Tensor | None = None, config: TwoStageLossConfig | None = None):
    config = config or TwoStageLossConfig()

    # Các tensor dự đoán và nhãn có shape (B, C, L).
    shape = output.prediction.shape
    assert target_power.shape == shape and target_on.shape == shape, "Nhãn công suất và bật/tắt phải cùng shape (B, C, L) với dự đoán."
    assert valid is None or (valid.shape == shape and valid.dtype == torch.bool), "valid phải là tensor boolean có shape (B, C, L)."

    keep = torch.isfinite(target_power) & torch.isfinite(target_on)
    if valid is not None:
        keep = keep & valid
    assert keep.any(), "Batch không chứa nhãn hợp lệ."

    # Đánh chỉ mục boolean gom các điểm hợp lệ: (B, C, L) → (N_valid,).
    power, on = target_power[keep], target_on[keep].to(output.logits.dtype)
    assert (power >= 0).all() and ((on == 0) | (on == 1)).all(), "Nhãn công suất phải không âm; nhãn bật/tắt phải bằng 0 hoặc 1."

    # MSE và BCE rút gọn N_valid điểm thành các loss vô hướng.
    regression = F.mse_loss(output.prediction[keep], power)
    positive_weight = output.logits.new_tensor(config.positive_weight)
    if positive_weight.ndim == 1:
        assert positive_weight.numel() == shape[1], "Số trọng số BCE phải khớp số thiết bị."
        # (C,) → (1, C, 1) → (B, C, L) → (N_valid,), giữ đúng trọng số sau khi lọc mask.
        positive_weight = positive_weight[None, :, None].expand_as(output.logits)[keep]
    detector = F.binary_cross_entropy_with_logits(
        output.logits[keep],
        on,
        pos_weight=positive_weight,
    )

    # Chọn tiếp các điểm thực sự bật: (N_valid,) → (N_on,).
    true_on = on == 1
    auxiliary = F.mse_loss(output.power[keep][true_on], power[true_on]) if true_on.any() else output.power[keep].sum() * 0
    loss = config.regression_weight * regression + config.detector_weight * detector + config.auxiliary_on_weight * auxiliary
    return {"loss": loss, "regression": regression, "detector": detector, "auxiliary_on": auxiliary, "valid_count": keep.sum(), "on_count": true_on.sum()}


def run_two_stage_epoch(
    model: TwoStageNILMFormer,
    batches: Iterable[Mapping[str, torch.Tensor]],
    device: torch.device | str,
    loss_config: TwoStageLossConfig,
    optimizer: torch.optim.Optimizer | None = None,
    grad_clip: float = 1.0,
    metrics_config: dict | None = None,
    progress_callback: Callable[[int, int | None, float], None] | None = None,
) -> dict[str, Any]:
    training = optimizer is not None
    model.train(training)
    totals = dict(regression=0.0, detector=0.0, auxiliary_on=0.0)
    count = on_count = 0
    total_batches = len(batches) if isinstance(batches, Sized) else None
    accumulator = NILMMetricAccumulator(metrics_config["device_names"], metrics_config["thresholds_w"], metrics_config["sample_duration_s"]) if metrics_config else None
    with torch.set_grad_enabled(training):
        for batch_index, batch in enumerate(batches, start=1):
            # Chuyển thiết bị tính toán, giữ nguyên x: (B, 1 + e, L).
            x = batch["x"].to(device)
            assert torch.isfinite(x).all(), "Đầu vào phải hữu hạn; cần xử lý các cửa sổ thiếu dữ liệu trước khi huấn luyện."
            target = batch["power"].to(device)
            on = batch["on"].to(device)
            valid = batch.get("valid")
            if valid is not None:
                valid = valid.to(device)
            if training:
                optimizer.zero_grad(set_to_none=True)
            output = model(x)
            if accumulator is not None:
                assert metrics_config is not None, "Thiếu cấu hình để tính metrics theo epoch."
                accumulator.update(
                    output.prediction * metrics_config["power_scale_w"], target * metrics_config["power_scale_w"], on, valid if valid is not None else torch.ones_like(on, dtype=torch.bool)
                )
            losses = two_stage_loss(output, target, on, valid, loss_config)
            assert torch.isfinite(losses["loss"]), "Loss của mô hình hai giai đoạn không hữu hạn."
            if training:
                # Một lần backward truyền gradient qua cả regressor và detector.
                losses["loss"].backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip, error_if_nonfinite=True)
                optimizer.step()
            n, n_on = int(losses["valid_count"]), int(losses["on_count"])
            count += n
            on_count += n_on
            totals["regression"] += float(losses["regression"].detach()) * n
            totals["detector"] += float(losses["detector"].detach()) * n
            totals["auxiliary_on"] += float(losses["auxiliary_on"].detach()) * n_on
            if progress_callback is not None:
                running_loss = (
                    loss_config.regression_weight * totals["regression"] / count
                    + loss_config.detector_weight * totals["detector"] / count
                    + loss_config.auxiliary_on_weight * totals["auxiliary_on"] / max(on_count, 1)
                )
                progress_callback(batch_index, total_batches, running_loss)
    assert count, "Bộ nạp dữ liệu rỗng."
    totals["regression"] /= count
    totals["detector"] /= count
    totals["auxiliary_on"] /= max(on_count, 1)
    totals["loss"] = loss_config.regression_weight * totals["regression"] + loss_config.detector_weight * totals["detector"] + loss_config.auxiliary_on_weight * totals["auxiliary_on"]
    if accumulator is not None:
        return {**totals, "metrics": accumulator.compute()}
    return totals


def plot_training_history(history: list[dict], output_path: str | Path, model_name: str = "TwoStageNILMFormer") -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    assert history, "Lịch sử huấn luyện không được rỗng khi vẽ biểu đồ."
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    epochs = [row["epoch"] for row in history]
    best_epoch = history[-1]["best_epoch"]
    panels = [
        ("loss", "Loss tổng", "Loss"),
        ("mae_w", "MAE trung bình theo thiết bị", "W"),
        ("rmse_w", "RMSE trung bình theo thiết bị", "W"),
        ("f1", "F1 trung bình theo thiết bị", "F1"),
        ("precision", "Precision trung bình theo thiết bị", "Precision"),
        ("recall", "Recall trung bình theo thiết bị", "Recall"),
    ]
    figure = Figure(figsize=(15, 12), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots(3, 2).ravel()
    flat_rows = []
    for record in history:
        flat = {"epoch": record["epoch"], "best_epoch": record["best_epoch"]}
        for split in ("train", "val"):
            if split not in record:
                continue
            # NILMFormer gốc chỉ có loss hồi quy; bỏ qua các thành phần loss không tồn tại.
            for key in ("loss", "regression", "detector", "auxiliary_on"):
                if key in record[split]:
                    flat[f"{split}_{key}"] = record[split][key]
            metrics = record[split].get("metrics", {})
            for key, value in metrics.get("macro", {}).items():
                flat[f"{split}_{key}"] = value
            for device, values in metrics.get("per_device", {}).items():
                for key, value in values.items():
                    flat[f"{split}_{device}_{key}"] = value
        flat_rows.append(flat)
    for axis, (metric, title, unit) in zip(axes, panels, strict=True):
        for split, label in (("train", "Huấn luyện"), ("val", "Validation")):
            if split not in history[0]:
                continue
            values = [row[split]["loss"] if metric == "loss" else row[split].get("metrics", {}).get("macro", {}).get(metric, float("nan")) for row in history]
            axis.plot(epochs, values, marker="o", markersize=3, label=label)
        axis.axvline(best_epoch, color="red", linestyle="--", alpha=0.6, label="Epoch tốt nhất")
        axis.set(title=title, xlabel="Epoch", ylabel=unit)
        axis.set_xticks(epochs if len(epochs) <= 10 else np.unique(np.linspace(epochs[0], epochs[-1], 10, dtype=int)))
        if metric in {"f1", "precision", "recall"}:
            axis.set_ylim(-0.02, 1.02)
        axis.grid(alpha=0.25)
        axis.legend()
    figure.suptitle(f"{path.parent.parent.name} / {path.parent.name} — {model_name}", fontsize=15)
    figure.savefig(path, dpi=150)
    figure.savefig(path.with_suffix(".svg"))
    pd.DataFrame(flat_rows).to_csv(path.with_name("epoch_metrics.csv"), index=False)


def _save_checkpoint(path: str | Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    temporary.replace(path)


def train_twostage_nilmformer(
    model: TwoStageNILMFormer,
    train_loader: Iterable[Mapping[str, torch.Tensor]],
    val_loader: Iterable[Mapping[str, torch.Tensor]] | None = None,
    *,
    epochs: int = 50,
    lr: float = 1e-4,
    device: torch.device | str = "cpu",
    loss_config: TwoStageLossConfig | None = None,
    grad_clip: float = 1.0,
    checkpoint_path: str | Path | None = None,
    training_seed: int = BASE_SEED,
    model_seed: int | None = None,
    patience: int | None = None,
    min_delta: float = 0.0,
    last_checkpoint_path: str | Path | None = None,
    checkpoint_metadata: dict | None = None,
    metrics_config: dict | None = None,
    progress_desc: str = "Huấn luyện hai giai đoạn",
) -> list[dict]:
    assert epochs >= 1 and lr > 0 and grad_clip > 0, "epochs, lr và grad_clip phải lớn hơn 0."
    assert min_delta >= 0, "min_delta phải không âm."
    assert patience is None or (patience >= 1 and val_loader is not None), "Early stopping cần patience dương và tập validation riêng."
    seed_everything(training_seed)
    initialization_seed = model.initialization_seed
    assert model_seed is None or initialization_seed is None or model_seed == initialization_seed, "model_seed không khớp seed khởi tạo."
    if model_seed is None:
        model_seed = initialization_seed
    if checkpoint_path is not None and last_checkpoint_path is None:
        path = Path(checkpoint_path)
        last_checkpoint_path = path.with_stem(path.stem + "_last")
    assert checkpoint_path is None or last_checkpoint_path is None or Path(checkpoint_path).resolve() != Path(last_checkpoint_path).resolve(), "Hai checkpoint tốt nhất và cuối phải khác đường dẫn."
    model.to(device)
    config = loss_config or TwoStageLossConfig()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0)
    history = []
    best, patience_best = float("inf"), float("inf")
    best_epoch, bad_epochs = 0, 0
    best_state = None
    train_batches = len(train_loader) if isinstance(train_loader, Sized) else None
    val_batches = 0 if val_loader is None else len(val_loader) if isinstance(val_loader, Sized) else None
    epoch_batches = train_batches + val_batches if train_batches is not None and val_batches is not None else None
    # Một đối tượng tqdm cho mô hình × seed; tái sử dụng thanh này và reset theo từng epoch.
    with tqdm(total=epoch_batches, desc=progress_desc, unit="batch", dynamic_ncols=True, leave=True, mininterval=0.5) as progress:
        for epoch in range(1, epochs + 1):
            if epoch > 1:
                progress.reset(total=epoch_batches)
            phase = "Train"

            def on_batch(batch_index: int, batch_total: int | None, running_loss: float) -> None:
                progress.set_postfix(epoch=f"{epoch}/{epochs}", pha=phase, batch=f"{batch_index}/{batch_total or '?'}", loss=f"{running_loss:.6f}", refresh=False)
                progress.update(1)

            progress.set_postfix(epoch=f"{epoch}/{epochs}", pha="Nạp batch train", batch=f"0/{train_batches or '?'}", refresh=True)
            train = run_two_stage_epoch(model, train_loader, device, config, optimizer, grad_clip, metrics_config=metrics_config, progress_callback=on_batch)
            record = {"epoch": epoch, "train": train}
            if val_loader is not None:
                phase = "Validation"
                progress.set_postfix(epoch=f"{epoch}/{epochs}", pha=phase, batch=f"0/{val_batches or '?'}", refresh=True)
                record["val"] = run_two_stage_epoch(model, val_loader, device, config, metrics_config=metrics_config, progress_callback=on_batch)
            history.append(record)
            score = record.get("val", train)["loss"]
            improved = score < best
            if improved:
                best, best_epoch = score, epoch
                # Giữ bản CPU độc lập; optimizer không được làm thay đổi trọng số tốt nhất đã lưu.
                best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            # min_delta điều khiển patience; checkpoint vẫn ghi nhận mọi cải thiện tuyệt đối.
            if score < patience_best - min_delta:
                patience_best, bad_epochs = score, 0
            else:
                bad_epochs += 1
            stopped = patience is not None and bad_epochs >= patience
            record.update(best_epoch=best_epoch, stopped_early=stopped)
            payload = {
                "epoch": epoch,
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "metrics": record,
                "detector_config": asdict(model.Detector.config),
                "regressor_config": asdict(model.Regressor.config),
                "threshold": model.threshold,
                "loss_config": asdict(config),
                "training_seed": training_seed,
                "model_seed": model_seed,
                "best_epoch": best_epoch,
                "best_score": best,
                "patience": patience,
                "min_delta": min_delta,
                "epochs_without_improvement": bad_epochs,
                "history": history,
                "metadata": checkpoint_metadata or {},
                "metrics_config": metrics_config,
            }
            if improved and checkpoint_path is not None:
                _save_checkpoint(checkpoint_path, payload)
            if last_checkpoint_path is not None:
                _save_checkpoint(last_checkpoint_path, payload)
            postfix = {
                "epoch": f"{epoch}/{epochs}",
                "pha": "Hoàn tất epoch",
                "loss_train": f"{train['loss']:.6f}",
                "loss_reg": f"{train['regression']:.6f}",
                "loss_detector": f"{train['detector']:.6f}",
                "loss_phụ": f"{train['auxiliary_on']:.6f}",
                "loss_tốt_nhất": f"{best:.6f}",
                "epoch_tốt_nhất": best_epoch,
                "chờ": bad_epochs,
            }
            if "val" in record:
                postfix["loss_val"] = f"{record['val']['loss']:.6f}"
            if metrics_config is not None:
                postfix["F1_val"] = f"{record['val']['metrics']['macro']['f1']:.4f}" if "val" in record else "Không có"
            if epoch_batches is not None:
                progress.update(max(0, epoch_batches - progress.n))
            progress.set_postfix(postfix)
            if stopped:
                tqdm.write(f"Dừng sớm ở epoch {epoch}; epoch tốt nhất: {best_epoch}.")
                break
    assert best_state is not None, "Không có trọng số tốt nhất sau huấn luyện."
    # Đánh giá bằng trọng số validation tốt nhất; checkpoint cuối vẫn giữ trạng thái epoch cuối.
    model.load_state_dict(best_state)
    model.eval()
    return history


def temporal_validation_indices(dataset: REFITCSVDataset, fraction: float = 0.2, limit: int | None = None):
    assert 0 < fraction < 1, "Tỷ lệ validation bên trong train phải nằm giữa 0 và 1."
    train_by_house, val_by_house, rows = {}, {}, []
    offset = 0
    for shard_index, shard in enumerate(dataset.shards):
        if shard_index not in dataset.cached:
            dataset.cached[shard_index] = dataset._load_shard(shard_index)
        starts = dataset.cached[shard_index]["start_time_ns"]
        clock = dataset.manifest["time_splits"][str(shard["house"])]
        start, end = pd.Timestamp(clock["start"]), pd.Timestamp(clock["train_end_exclusive"])
        boundary = (start + (end - start) * (1 - fraction)).ceil("min").value
        # Chỉ giữ cửa sổ nằm trọn một phía; không dùng cửa sổ cắt ngang train/validation.
        ends = starts + dataset.length * dataset.manifest["config"]["sampling_seconds"] * 10**9
        train_indices = np.flatnonzero(ends <= boundary) + offset
        val_indices = np.flatnonzero(starts >= boundary) + offset
        assert len(train_indices) and len(val_indices), f"Hộ {shard['house']} không đủ cửa sổ train/validation."
        dropped = len(starts) - len(train_indices) - len(val_indices)
        if limit is not None:
            assert limit >= 1, "Giới hạn cửa sổ phải lớn hơn 0."
            train_indices = train_indices[:limit]
            val_indices = val_indices[:limit]
        house = shard["house"]
        train_by_house[house], val_by_house[house] = train_indices.tolist(), val_indices.tolist()
        rows.append({"house": house, "validation_start": str(pd.Timestamp(boundary)), "train_windows": len(train_indices), "validation_windows": len(val_indices), "boundary_windows_dropped": dropped})
        offset += shard["windows"]
    return train_by_house, val_by_house, rows


def detector_class_weights(dataset: REFITCSVDataset, indices: list[int], maximum: float = 100.0):
    assert maximum >= 1, "Giới hạn trọng số lớp dương phải ít nhất bằng 1."
    positive = np.zeros(len(dataset.targets), dtype="int64")
    negative = np.zeros_like(positive)
    indices_array = np.asarray(indices)
    offset = 0
    for shard_index, shard in enumerate(dataset.shards):
        local = indices_array[(indices_array >= offset) & (indices_array < offset + shard["windows"])] - offset
        if len(local):
            if shard_index not in dataset.cached:
                dataset.cached[shard_index] = dataset._load_shard(shard_index)
            # (N, C, L) → (C,): chỉ đếm nhãn hợp lệ của các cửa sổ train thực tế.
            values = dataset.cached[shard_index]
            on, valid = values["on"][local], values["valid"][local]
            positive += ((on == 1) & valid).sum(axis=(0, 2))
            negative += ((on == 0) & valid).sum(axis=(0, 2))
        offset += shard["windows"]
    # Làm trơn và chặn trọng số để lớp hiếm không tạo gradient quá lớn.
    weights = np.clip((negative + 1) / (positive + 1), 0.01, maximum)
    weights[positive == 0] = 1.0
    statistics = [
        {"device": name, "on_count": int(pos), "off_count": int(neg), "positive_weight": float(weight), "has_positive_train_labels": bool(pos), "has_train_labels": bool(pos + neg)}
        for name, pos, neg, weight in zip(dataset.targets, positive, negative, weights, strict=True)
    ]
    return weights.tolist(), statistics


def predict_house(model: TwoStageNILMFormer | NILMFormer, dataset: REFITCSVDataset, house: int, batch_size: int, device: str, limit: int | None = None) -> dict[str, torch.Tensor]:
    offset, indices = 0, []
    for shard in dataset.shards:
        if shard["house"] == house:
            indices.extend(range(offset, offset + shard["windows"]))
        offset += shard["windows"]
    assert indices, f"Hộ {house} không có dữ liệu test."
    if limit is not None:
        indices = indices[:limit]
    loader = DataLoader(Subset(dataset, indices), batch_size=batch_size, shuffle=False, num_workers=0, generator=make_data_generator())
    chunks: dict[str, list[torch.Tensor]] = {key: [] for key in ("prediction", "power", "on", "valid", "aggregate", "start_time_ns")}
    detector_chunks = []
    model.eval()
    with torch.no_grad():
        for batch in loader:
            output = model(batch["x"].to(device))
            # TwoStage trả TwoStageOutput; NILMFormer gốc trả trực tiếp công suất (B, C, L).
            prediction = output.prediction if isinstance(output, TwoStageOutput) else output
            # Cùng một quy tắc cho mọi mô hình: chặn công suất âm về 0. TwoStage không đổi vì softplus × mask luôn không âm.
            chunks["prediction"].append(prediction.clamp(min=0).cpu() * dataset.scale)
            chunks["power"].append(batch["power"] * dataset.scale)
            chunks["on"].append(batch["on"])
            chunks["valid"].append(batch["valid"])
            # (B, 1 + e, L) → (B, L): chỉ giữ kênh điện tổng, đổi lại về W.
            chunks["aggregate"].append(batch["x"][:, 0] * dataset.scale)
            chunks["start_time_ns"].append(batch["start_time_ns"])
            if isinstance(output, TwoStageOutput):
                detector_chunks.append(output.mask.cpu())
    # Ghép mọi batch của một hộ trước tính F1/SAE; không lấy trung bình các tỷ lệ theo batch.
    tensors = {key: torch.cat(value, dim=0) for key, value in chunks.items()}
    if detector_chunks:
        tensors["detector_on"] = torch.cat(detector_chunks, dim=0)
    return tensors


def house_metric_rows(tensors: dict[str, torch.Tensor], targets: list[str], thresholds_w: list[float], sample_duration_s: float) -> list[dict]:
    # Ngưỡng (C,) → (1, C, 1), broadcast với dự đoán (N, C, L); ghi lại để phân tầng và bảng lỗi dùng cùng trạng thái.
    tensors["predicted_on"] = tensors["prediction"] >= torch.tensor(thresholds_w)[None, :, None]
    rows = []
    for channel, name in enumerate(targets):
        predicted, actual = tensors["prediction"][:, channel], tensors["power"][:, channel]
        valid, target_on = tensors["valid"][:, channel], tensors["on"][:, channel]
        # F1 chính dùng công suất cuối với cùng ngưỡng vật lý; F1 detector chỉ có ở TwoStage, báo riêng để phân tích mask.
        scores = compute_nilm_metrics(predicted, actual, valid, sample_duration_s=sample_duration_s, predicted_on=tensors["predicted_on"][:, channel], target_on=target_on)
        detector = state_metrics(tensors["detector_on"][:, channel], target_on, valid) if "detector_on" in tensors else {}
        rows.append({"device": name, "test_windows": len(actual), "evaluated": bool(valid.any()), **scores, **{f"detector_{key}": value for key, value in detector.items()}})
    return rows


def stratified_rows(tensors: dict[str, torch.Tensor], targets: list[str], sample_duration_s: float) -> list[dict]:
    valid, on = tensors["valid"], tensors["on"] == 1
    # Số thiết bị đích đang bật theo nhãn tại từng phút: (N, C, L) → (N, L); chỉ đếm kênh có nhãn hợp lệ.
    active = (on & valid).sum(dim=1)
    strata = [("concurrent_on", str(k), active == k) for k in range(3)] + [("concurrent_on", "3+", active >= 3)]
    # Nhóm mức tải theo điện tổng (N, L), dùng ngưỡng W cố định nên không ước lượng từ test.
    for low, high in zip(LOAD_BINS_W[:-1], LOAD_BINS_W[1:], strict=True):
        strata.append(("load_w", f"[{low:g}, {high:g})", (tensors["aggregate"] >= low) & (tensors["aggregate"] < high)))
    rows = []
    for stratum_type, stratum, mask in strata:
        for channel, name in enumerate(targets):
            # Mask nhóm (N, L) giao với mask hợp lệ của kênh (N, L); nhóm rỗng trả NaN, không đổi thành 0.
            keep = valid[:, channel] & mask
            scores = compute_nilm_metrics(
                tensors["prediction"][:, channel],
                tensors["power"][:, channel],
                keep,
                sample_duration_s=sample_duration_s,
                predicted_on=tensors["predicted_on"][:, channel],
                target_on=tensors["on"][:, channel],
            )
            rows.append({"device": name, "stratum_type": stratum_type, "stratum": stratum, **scores})
    return rows


def error_analysis_rows(tensors: dict[str, torch.Tensor], targets: list[str]) -> list[dict]:
    valid, on, predicted_on = tensors["valid"], tensors["on"] == 1, tensors["predicted_on"]
    rows = []
    for channel, name in enumerate(targets):
        # Thiết bị đích khác đang bật theo nhãn hợp lệ: (N, C, L), bỏ chính kênh đang xét.
        others = on & valid
        others[:, channel] = False
        errors = {
            "FP": predicted_on[:, channel] & ~on[:, channel] & valid[:, channel],
            "FN": ~predicted_on[:, channel] & on[:, channel] & valid[:, channel],
        }
        for error_type, error in errors.items():
            total = int(error.sum())
            # Một điểm lỗi có thể trùng nhiều thiết bị khác bật, nên tổng tỷ lệ các bối cảnh có thể lớn hơn 1.
            contexts = [(other, error & others[:, index]) for index, other in enumerate(targets) if index != channel]
            contexts.append(("Không thiết bị đích khác bật", error & ~others.any(dim=1)))
            for context, mask in contexts:
                count = int(mask.sum())
                rows.append({"device": name, "error_type": error_type, "context": context, "error_points": count, "error_total": total, "share": count / total if total else math.nan})
    return rows


def plot_house_predictions(tensors: dict[str, torch.Tensor], targets: list[str], output_path: str | Path, title: str) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    valid, on = tensors["valid"], tensors["on"] == 1
    # Sai số tuyệt đối mỗi cửa sổ: (N, C, L) → (N,); số thiết bị bật tối đa mỗi cửa sổ: (N, C, L) → (N, L) → (N,).
    error = ((tensors["prediction"] - tensors["power"]).abs() * valid).sum(dim=(1, 2))
    active = (on & valid).sum(dim=1).amax(dim=1)
    windows = [
        ("Sai số lớn nhất", int(error.argmax())),
        # Trong các cửa sổ có nhiều thiết bị bật đồng thời nhất, chọn cửa sổ sai số lớn nhất.
        (f"Nhiều thiết bị bật nhất ({int(active.max())})", int(torch.where(active == active.max(), error, -1).argmax())),
    ]
    figure = Figure(figsize=(16, 3 * (len(targets) + 1)), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots(len(targets) + 1, len(windows), squeeze=False)
    for column, (label, index) in enumerate(windows):
        minutes = np.arange(tensors["aggregate"].shape[1])
        start = pd.Timestamp(int(tensors["start_time_ns"][index]))
        axes[0, column].plot(minutes, tensors["aggregate"][index].numpy(), color="black")
        axes[0, column].set(title=f"{label} — bắt đầu {start:%Y-%m-%d %H:%M}", ylabel="Điện tổng (W)")
        for row, name in enumerate(targets, start=1):
            # Điểm thiếu nhãn để NaN để không vẽ như công suất bằng 0.
            actual = torch.where(valid[index, row - 1], tensors["power"][index, row - 1], torch.nan).numpy()
            axis = axes[row, column]
            axis.plot(minutes, actual, label="Thực tế")
            axis.plot(minutes, tensors["prediction"][index, row - 1].numpy(), label="Dự đoán", alpha=0.8)
            if "prediction_min" in tensors:
                # Dải giữa dự đoán nhỏ nhất và lớn nhất của các seed quanh đường trung bình.
                axis.fill_between(
                    minutes, tensors["prediction_min"][index, row - 1].numpy(), tensors["prediction_max"][index, row - 1].numpy(), alpha=0.2, color="tab:orange", label="Min–max các seed"
                )
            axis.set(ylabel=f"{name} (W)")
            axis.legend(loc="upper right")
        axes[-1, column].set(xlabel="Phút trong cửa sổ")
    for axis in axes.ravel():
        axis.grid(alpha=0.25)
    figure.suptitle(title, fontsize=14)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=120)


def run_study(args: argparse.Namespace) -> Path:
    seed_everything(BASE_SEED)
    assert 1 <= args.num_seeds <= MODEL_SEED_COUNT, "Số seed phải nằm trong khoảng 1 đến 5."
    assert args.batch_size >= 1 and args.epochs >= 1 and args.patience >= 1, "Batch size, số epoch và patience phải dương."
    assert args.model in MODEL_NAMES, "Mô hình phải là twostage hoặc nilmformer."
    model_name = MODEL_NAMES[args.model]
    assert args.cpu_threads >= 1, "Số luồng CPU phải ít nhất bằng 1."
    # Các phép CPU chỉ là đọc batch và cộng metrics trên tensor nhỏ; chia cho nhiều luồng trên máy đang tải nặng làm mỗi batch chậm hàng trăm lần.
    torch.set_num_threads(args.cpu_threads)
    assert args.device != "cuda" or torch.cuda.is_available(), "Không có CUDA khả dụng trong môi trường hiện tại."
    tqdm.write(f"Thiết bị huấn luyện: {torch.cuda.get_device_name(0) if args.device == 'cuda' else 'CPU'}")
    processed_dir = Path(args.data_dir).resolve()
    manifest_path = processed_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = ["WashingMachine", "Dishwasher", "Kettle", "Microwave"]
    assert manifest["target_channels"] == expected, "Dữ liệu phải có đúng bốn loại thiết bị theo thứ tự đã chốt."
    available = {row["house"] for row in manifest["shards"] if row["split"] == "train"}
    houses = sorted(set(args.houses or STUDY_HOUSES))
    assert set(houses) <= available, "Danh sách hộ có ID không tồn tại trong dữ liệu."
    smoke = args.smoke_test
    if smoke:
        houses = houses[:2]
    seeds = generate_model_seeds(count=1 if smoke else args.num_seeds)
    output_dir = Path(args.output_dir or Path(__file__).resolve().parents[1] / "training/runs" / datetime.now().strftime(f"{args.model}_%Y%m%d_%H%M%S")).resolve()
    assert not (output_dir / "study.json").exists(), "Thư mục đã có thực nghiệm; chọn output-dir mới để tránh ghi đè."
    output_dir.mkdir(parents=True, exist_ok=True)
    train_dataset, test_dataset = REFITCSVDataset(processed_dir, "train"), REFITCSVDataset(processed_dir, "test")
    # Chỉ nạp các hộ được chọn; dùng chung cache dữ liệu giữa các seed và nhánh.
    train_dataset.shards = [row for row in train_dataset.shards if row["house"] in houses]
    test_dataset.shards = [row for row in test_dataset.shards if row["house"] in houses]
    for dataset in (train_dataset, test_dataset):
        dataset.ends = np.cumsum([row["windows"] for row in dataset.shards])
    limit = 2 if smoke else None
    train_indices, val_indices, validation_rows = temporal_validation_indices(train_dataset, args.validation_fraction, limit)
    for house in houses:
        _, house_balance = detector_class_weights(train_dataset, train_indices[house], args.max_positive_weight)
        assert all(row["has_train_labels"] for row in house_balance), f"Hộ {house} không có nhãn train hợp lệ cho đủ bốn thiết bị đích."
    groups = []
    # Hoán vị cố định theo seed gốc: nửa số hộ (làm tròn lên) train mô hình chung, các hộ còn lại chỉ dùng làm hộ chưa thấy khi test.
    pooled_houses = sorted(np.random.default_rng(BASE_SEED).permutation(houses).tolist()[: (len(houses) + 1) // 2])
    if "pooled" in args.protocols:
        groups.append(("pooled", pooled_houses, sum([train_indices[h] for h in pooled_houses], []), sum([val_indices[h] for h in pooled_houses], [])))
    if "cross_house" in args.protocols:
        # Mỗi mô hình chỉ học dữ liệu train của một hộ; validation cũng lấy từ chính hộ đó, không nhìn các hộ còn lại.
        groups.extend((f"house_{h:02d}", [h], train_indices[h], val_indices[h]) for h in houses)
    study = {
        "model": model_name,
        "data_dir": str(processed_dir),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "houses": houses,
        "pooled_train_houses": pooled_houses,
        "model_seeds": seeds,
        "training_seed": BASE_SEED,
        "validation_splits": validation_rows,
        "planned_trainings": len(groups) * len(seeds),
        "smoke_test": smoke,
        "arguments": vars(args),
    }
    (output_dir / "study.json").write_text(json.dumps(study, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(validation_rows).to_csv(output_dir / "validation_split.csv", index=False)
    thresholds_w = [manifest["thresholds_w"][name][0] for name in expected]
    duration = manifest["config"]["sampling_seconds"]
    all_rows, all_seed_rows, all_strata, all_errors = [], [], [], []
    for group, train_houses, train_ids, val_ids in groups:
        weights, balance = detector_class_weights(train_dataset, train_ids, args.max_positive_weight)
        protocol = "pooled" if group == "pooled" else "cross_house"
        # Dự đoán của từng seed theo hộ test; kết quả của mô hình là ensemble trung bình cộng các seed.
        seed_outputs: dict[int, list[dict[str, torch.Tensor]]] = {house: [] for house in houses}
        seed_runs = []
        for model_seed in seeds:
            run_dir = output_dir / group / f"seed_{model_seed}"
            run_dir.mkdir(parents=True, exist_ok=True)
            train_loader = DataLoader(Subset(train_dataset, train_ids), batch_size=args.batch_size, shuffle=True, num_workers=0, generator=make_data_generator(), worker_init_fn=seed_worker)
            val_loader = DataLoader(Subset(train_dataset, val_ids), batch_size=args.batch_size, shuffle=False, num_workers=0, generator=make_data_generator())
            small = dict(d_model=16, n_head=4, n_encoder_layers=1, dp_rate=0) if smoke else {}
            if args.model == "twostage":
                detector_config = GRUConfig(c_out=4, conv_channels=4, hidden=4, dropout=0) if smoke else GRUConfig(c_out=4)
                model = initialize_twostage_nilmformer(detector_config, NILMFormerConfig(c_out=4, **small), model_seed)
            else:
                # Đặt seed trước constructor như TwoStage để trọng số khởi tạo tái lập được.
                seed_everything(model_seed)
                model = NILMFormer(BaselineConfig(c_out=4, **small))
            pd.DataFrame(balance).to_csv(run_dir / "class_balance.csv", index=False)
            metadata = {
                "protocol": protocol,
                "train_houses": train_houses,
                "class_balance": balance,
                "validation_fraction_within_original_train": args.validation_fraction,
                "smoke_test": smoke,
                "manifest_sha256": study["manifest_sha256"],
            }
            tqdm.write(f"Huấn luyện {model_name} {group}, seed {model_seed}" + (f"; trọng số bật: {weights}" if args.model == "twostage" else ""))
            # Cùng dữ liệu, early stopping và checkpoint cho hai mô hình; chỉ loss và kiến trúc khác nhau.
            common = dict(
                epochs=1 if smoke else args.epochs,
                lr=args.lr,
                device=args.device,
                checkpoint_path=run_dir / "best.pt",
                training_seed=BASE_SEED,
                model_seed=model_seed,
                patience=args.patience,
                min_delta=args.min_delta,
                checkpoint_metadata=metadata,
                progress_desc=f"{model_name} | {'Chung các hộ' if group == 'pooled' else f'Hộ {train_houses[0]}'} | seed={model_seed}",
                metrics_config={
                    "device_names": expected,
                    "thresholds_w": thresholds_w,
                    "sample_duration_s": duration,
                    "power_scale_w": train_dataset.scale,
                },
            )
            started = time.perf_counter()
            if args.model == "twostage":
                loss_config = TwoStageLossConfig(positive_weight=weights, auxiliary_on_weight=args.auxiliary_on_weight)
                history = train_twostage_nilmformer(model, train_loader, val_loader, loss_config=loss_config, last_checkpoint_path=run_dir / "last.pt", **common)
            else:
                history = train_nilmformer(model, train_loader, val_loader, **common)
            train_seconds = time.perf_counter() - started
            plot_training_history(history, run_dir / "training_curves.png", model_name)
            (run_dir / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            # Nạp lại checkpoint validation tốt nhất trước khi chạm vào test.
            best = torch.load(run_dir / "best.pt", map_location=args.device, weights_only=True)
            model.load_state_dict(best["model"])
            seed_runs.append({"best_epoch": best["best_epoch"], "epochs_trained": len(history), "train_seconds": train_seconds})
            # Metrics validation tại epoch được chọn; dùng để chọn siêu tham số mà không nhìn test.
            validation_at_best = {f"val_{key}_at_best": value for key, value in history[best["best_epoch"] - 1]["val"]["metrics"]["macro"].items()}
            seed_rows = []
            # Mọi mô hình đều test trên cùng 20% cuối của mọi hộ; hộ không có trong train là hộ chưa thấy.
            for house in houses:
                tensors = predict_house(model, test_dataset, house, args.batch_size, args.device, limit)
                seed_outputs[house].append(tensors)
                # Metrics của riêng seed chỉ để truy vết; kết quả báo cáo lấy từ ensemble bên dưới.
                pair_keys = {"model": model_name, "protocol": protocol, "train_houses": ",".join(map(str, train_houses)), "house": house, "unseen_house": house not in train_houses}
                seed_rows.extend(
                    {**pair_keys, "model_seed": model_seed, "best_epoch": best["best_epoch"], **validation_at_best, **row} for row in house_metric_rows(tensors, expected, thresholds_w, duration)
                )
            pd.DataFrame(seed_rows).to_csv(run_dir / "test_metrics.csv", index=False)
            all_seed_rows.extend(seed_rows)
            pd.DataFrame(all_seed_rows).to_csv(output_dir / "seed_test_metrics.csv", index=False)
            del model, best
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        for house in houses:
            keys = dict(model=model_name, protocol=protocol, train_houses=",".join(map(str, train_houses)), house=house, unseen_house=house not in train_houses)
            ensemble = ensemble_outputs(seed_outputs.pop(house))
            ensemble_rows = house_metric_rows(ensemble, expected, thresholds_w, duration)
            # on_count là số phút bật hợp lệ theo nhãn test; cờ áp dụng chung cho dòng chính, phân tầng và bảng lỗi của cùng thiết bị.
            low_support = {row["device"]: row["on_count"] < MIN_TEST_ON_MINUTES for row in ensemble_rows}
            for row in ensemble_rows:
                support = balance[expected.index(row["device"])]
                all_rows.append(
                    {
                        **keys,
                        **row,
                        "low_support": low_support[row["device"]],
                        "n_seeds": len(seeds),
                        "best_epochs": ",".join(str(run["best_epoch"]) for run in seed_runs),
                        "epochs_trained": ",".join(str(run["epochs_trained"]) for run in seed_runs),
                        "train_seconds_total": sum(run["train_seconds"] for run in seed_runs),
                        "train_windows": len(train_ids),
                        "validation_windows": len(val_ids),
                        "has_positive_train_labels": support["has_positive_train_labels"],
                        "smoke_test": smoke,
                    }
                )
            all_strata.extend({**keys, **row, "low_support": low_support[row["device"]]} for row in stratified_rows(ensemble, expected, duration))
            all_errors.extend({**keys, **row, "low_support": low_support[row["device"]]} for row in error_analysis_rows(ensemble, expected))
            status = "hộ chưa thấy" if keys["unseen_house"] else "hộ đã thấy"
            title = f"{model_name} | train hộ {keys['train_houses']} | test hộ {house} ({status}) | ensemble {len(seeds)} seed"
            plot_house_predictions(ensemble, expected, output_dir / group / "predictions" / f"house_{house:02d}.png", title)
        # Ghi lại sau mỗi nhóm để không mất kết quả đã chạy nếu tiến trình dừng giữa chừng.
        pd.DataFrame(all_rows).to_csv(output_dir / "test_metrics.csv", index=False)
        pd.DataFrame(all_strata).to_csv(output_dir / "stratified_metrics.csv", index=False)
        pd.DataFrame(all_errors).to_csv(output_dir / "error_analysis.csv", index=False)
    summarize_study(all_rows, all_strata, all_errors, output_dir)
    tqdm.write(f"Đã hoàn tất {study['planned_trainings']} lượt train. Kết quả: {output_dir}")
    return output_dir


def ensemble_outputs(outputs: list[dict[str, torch.Tensor]]) -> dict[str, torch.Tensor]:
    assert outputs, "Cần ít nhất một seed để tạo ensemble."
    # Nhãn, mask hợp lệ, điện tổng và timestamp giống nhau giữa các seed vì cùng tập test và thứ tự cửa sổ.
    ensemble = {key: outputs[0][key] for key in ("power", "on", "valid", "aggregate", "start_time_ns")}
    assert all(torch.equal(output["start_time_ns"], ensemble["start_time_ns"]) for output in outputs), "Các seed phải dự đoán trên cùng cửa sổ test."
    # Các seed: S × (N, C, L) → (S, N, C, L) → trung bình cộng (N, C, L); giữ min–max để vẽ độ phân tán giữa các seed.
    stacked = torch.stack([output["prediction"] for output in outputs])
    ensemble.update(prediction=stacked.mean(dim=0), prediction_min=stacked.amin(dim=0), prediction_max=stacked.amax(dim=0))
    if "detector_on" in outputs[0]:
        # Mask detector là 0/1 nên dùng bỏ phiếu: bật khi ít nhất một nửa số seed bật.
        ensemble["detector_on"] = torch.stack([output["detector_on"] for output in outputs]).float().mean(dim=0) >= 0.5
    return ensemble


def summarize_study(all_rows: list[dict], all_strata: list[dict], all_errors: list[dict], output_dir: Path) -> None:
    results = pd.DataFrame(all_rows)
    metric_names = ["mae_w", "rmse_w", "nde", "sae", "mr", "energy_error_kwh", "relative_energy_error", "f1", "precision", "recall", "false_negative_rate", "detector_f1"]
    # NILMFormer gốc không có detector nên không có cột detector_f1.
    metric_names = [name for name in metric_names if name in results]
    # Ghi riêng các cặp bị loại để báo cáo số cặp và lý do, không âm thầm bỏ đi.
    low = results["low_support"].astype(bool)
    results[low][["model", "protocol", "train_houses", "house", "unseen_house", "device", "on_count"]].to_csv(output_dir / "low_support_pairs.csv", index=False)
    results = results[~low]
    # Mỗi dòng là ensemble các seed của một mô hình × nhánh × hộ train × hộ test × thiết bị.
    # Macro theo các cặp hộ, tách hộ đã thấy và hộ chưa thấy; std là độ lệch giữa các cặp hộ; trung vị ít bị cặp cực trị chi phối.
    group_keys = ["model", "protocol", "unseen_house"]
    macro = results.groupby([*group_keys, "device"])[metric_names].agg(["mean", "median", "std", "count"])
    macro.columns = [f"{metric}_{stat}" for metric, stat in macro.columns]
    macro.to_csv(output_dir / "macro_summary.csv")

    stratum_metrics = ["mae_w", "relative_energy_error", "f1", "precision", "recall", "valid_count", "on_count"]
    # Tầng rỗng có NaN và không được tính vào trung bình.
    strata = pd.DataFrame(all_strata)
    strata = strata[~strata["low_support"].astype(bool)]
    stratum_summary = strata.groupby([*group_keys, "stratum_type", "stratum", "device"])[stratum_metrics].agg(["mean", "median", "std", "count"])
    stratum_summary.columns = [f"{metric}_{stat}" for metric, stat in stratum_summary.columns]
    stratum_summary.to_csv(output_dir / "stratified_summary.csv")

    # Cộng số điểm lỗi trên các cặp hộ trước khi chia để có tỷ lệ bối cảnh của toàn nhóm.
    errors = pd.DataFrame(all_errors)
    errors = errors[~errors["low_support"].astype(bool)]
    error_summary = errors.groupby([*group_keys, "device", "error_type", "context"])[["error_points", "error_total"]].sum()
    error_summary["share"] = error_summary["error_points"] / error_summary["error_total"].where(error_summary["error_total"] > 0)
    error_summary.to_csv(output_dir / "error_summary.csv")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Train TwoStageNILMFormer hoặc NILMFormer gốc chung các hộ và riêng từng hộ, đánh giá trên cả hộ đã thấy và hộ chưa thấy.")
    parser.add_argument("--model", default="twostage", choices=list(MODEL_NAMES), help="Kiến trúc: twostage (mặc định) hoặc nilmformer làm baseline.")
    parser.add_argument("--data-dir", default=str(root / "data/processed/REFIT/temporal_7aea0ef86866"), help="Thư mục manifest CSV đã tiền xử lý.")
    parser.add_argument("--output-dir", help="Thư mục mới để lưu kết quả; mặc định training/runs/<model>_<thời điểm>.")
    parser.add_argument("--epochs", type=int, default=150, help="Số epoch tối đa; early stopping theo patience thường dừng sớm hơn.")
    parser.add_argument("--patience", type=int, default=10, help="Số epoch không cải thiện validation trước khi dừng.")
    parser.add_argument("--min-delta", type=float, default=0.0, help="Mức cải thiện validation tối thiểu để đặt lại patience.")
    parser.add_argument("--batch-size", type=int, default=64, help="Số cửa sổ mỗi batch.")
    parser.add_argument("--lr", type=float, default=1e-4, help="Tốc độ học.")
    parser.add_argument("--num-seeds", type=int, default=MODEL_SEED_COUNT, help="Số seed khởi tạo, mặc định 5.")
    parser.add_argument("--validation-fraction", type=float, default=0.2, help="Tỷ lệ thời gian cuối trong phần train gốc để làm validation.")
    # Mức 5 được chọn trên validation (nhánh pooled, 1 seed): tốt hơn 10, 30 ở F1, precision, MAE và SAE; xem docs/train_twostage.md.
    parser.add_argument("--max-positive-weight", type=float, default=5.0, help="Giới hạn trọng số lớp bật trong BCE, mặc định 5 theo kết quả chọn trên validation.")
    parser.add_argument("--auxiliary-on-weight", type=float, default=0.1, help="Trọng số loss phụ công suất tại điểm thực sự bật; chỉ dùng với twostage.")
    parser.add_argument("--device", default="cuda", choices=["cpu", "cuda"], help="Thiết bị tính toán, mặc định CUDA; không tự chuyển sang CPU.")
    parser.add_argument("--cpu-threads", type=int, default=1, help="Số luồng CPU của PyTorch, mặc định 1; GPU vẫn làm phần train chính.")
    parser.add_argument("--houses", type=int, nargs="+", help=f"Chỉ chạy các hộ được chỉ định; mặc định các hộ đủ bốn thiết bị {STUDY_HOUSES}.")
    parser.add_argument("--protocols", nargs="+", choices=["pooled", "cross_house"], default=["pooled", "cross_house"], help="Các nhánh thực nghiệm.")
    parser.add_argument("--smoke-test", action="store_true", help="Chỉ kiểm tra kết nối: tối đa 2 hộ, 1 seed, 1 epoch, 2 cửa sổ và mô hình nhỏ.")
    run_study(parser.parse_args())
