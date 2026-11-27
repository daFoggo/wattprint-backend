from collections.abc import Iterable, Mapping
from pathlib import Path

import torch
import torch.nn.functional as F
from tqdm.auto import tqdm

from .metrics import NILMMetricAccumulator
from .model.NILMFormer.NILMFormer import NILMFormer
from .seeds import BASE_SEED, seed_everything


def nilmformer_loss(prediction: torch.Tensor, target_power: torch.Tensor, valid: torch.Tensor | None = None):
    # B: số mẫu, C: số thiết bị, L: độ dài chuỗi; không cho phép broadcast nhãn.
    assert prediction.ndim == 3 and target_power.shape == prediction.shape, "Nhãn công suất phải cùng shape (B, C, L) với dự đoán."
    assert valid is None or (valid.shape == prediction.shape and valid.dtype == torch.bool), "valid phải là tensor boolean có shape (B, C, L)."
    keep = torch.isfinite(target_power)
    if valid is not None:
        keep = keep & valid
    assert keep.any(), "Batch không chứa nhãn hợp lệ."

    # Gom các điểm hợp lệ: (B, C, L) → (N_valid,); MSE rút gọn thành vô hướng.
    power = target_power[keep]
    assert (power >= 0).all(), "Nhãn công suất phải không âm."
    loss = F.mse_loss(prediction[keep], power)
    return {"loss": loss, "regression": loss, "valid_count": keep.sum()}


def run_nilmformer_epoch(
    model: NILMFormer,
    batches: Iterable[Mapping[str, torch.Tensor]],
    device: torch.device | str,
    optimizer: torch.optim.Optimizer | None = None,
    grad_clip: float = 1.0,
    metrics_config: dict | None = None,
):
    training = optimizer is not None
    accumulator = NILMMetricAccumulator(metrics_config["device_names"], metrics_config["thresholds_w"], metrics_config["sample_duration_s"]) if metrics_config else None
    model.train(training)
    total = 0.0
    count = 0
    with torch.set_grad_enabled(training):
        for batch in batches:
            # Chuyển thiết bị tính toán, giữ nguyên x: (B, 1 + e, L).
            x = batch["x"].to(device)
            assert x.ndim == 3 and x.shape[1] == 1 + model.config.c_embedding, "Đầu vào phải có shape (B, 1 + c_embedding, L)."
            assert torch.isfinite(x).all(), "Đầu vào phải hữu hạn; cần xử lý các cửa sổ thiếu dữ liệu trước khi huấn luyện."
            target = batch["power"].to(device)
            valid = batch.get("valid")
            if valid is not None:
                valid = valid.to(device)
            if training:
                optimizer.zero_grad(set_to_none=True)

            # Hồi quy trực tiếp: (B, 1 + e, L) → (B, C, L), giữ đầu ra gốc chưa chặn giá trị.
            prediction = model(x)
            if accumulator is not None:
                # Metrics theo epoch dùng cùng công thức và ngưỡng W với TwoStage; cần nhãn bật/tắt trong batch.
                scale = metrics_config["power_scale_w"]
                accumulator.update(prediction * scale, target * scale, batch["on"].to(device), valid if valid is not None else torch.ones_like(target, dtype=torch.bool))
            losses = nilmformer_loss(prediction, target, valid)
            assert torch.isfinite(losses["loss"]), "Loss của NILMFormer không hữu hạn."
            if training:
                losses["loss"].backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip, error_if_nonfinite=True)
                optimizer.step()
            n = int(losses["valid_count"])
            count += n
            total += float(losses["loss"].detach()) * n
    assert count, "Bộ nạp dữ liệu rỗng."
    # Trung bình theo số điểm hợp lệ để các batch ít nhãn không bị tính quá trọng số.
    regression = total / count
    if accumulator is not None:
        return {"loss": regression, "regression": regression, "metrics": accumulator.compute()}
    return {"loss": regression, "regression": regression}


def train_nilmformer(
    model: NILMFormer,
    train_loader: Iterable[Mapping[str, torch.Tensor]],
    val_loader: Iterable[Mapping[str, torch.Tensor]] | None = None,
    *,
    epochs: int = 10,
    lr: float = 1e-4,
    device: torch.device | str = "cpu",
    grad_clip: float = 1.0,
    checkpoint_path: str | Path | None = None,
    training_seed: int = BASE_SEED,
    model_seed: int | None = None,
    patience: int | None = None,
    min_delta: float = 0.0,
    metrics_config: dict | None = None,
    checkpoint_metadata: dict | None = None,
    progress_desc: str = "Huấn luyện NILMFormer",
) -> list[dict]:
    # Batch gồm x, power và valid tùy chọn; bộ nạp phải lặp lại được qua nhiều epoch.
    # Target dùng cùng thang công suất không âm với bản hai giai đoạn, tắt bằng 0.
    assert epochs >= 1 and lr > 0 and grad_clip > 0, "epochs, lr và grad_clip phải lớn hơn 0."
    assert model.config.c_in == 1, "NILMFormer yêu cầu một kênh công suất tổng."
    assert min_delta >= 0, "min_delta phải không âm."
    assert patience is None or (patience >= 1 and val_loader is not None), "Early stopping cần patience dương và tập validation riêng."
    seed_everything(training_seed)
    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0)
    history = []
    best, patience_best = float("inf"), float("inf")
    best_epoch, bad_epochs = 0, 0
    with tqdm(range(1, epochs + 1), desc=progress_desc, unit="epoch", dynamic_ncols=True) as progress:
        for epoch in progress:
            train = run_nilmformer_epoch(model, train_loader, device, optimizer, grad_clip, metrics_config)
            record = {"epoch": epoch, "train": train}
            if val_loader is not None:
                record["val"] = run_nilmformer_epoch(model, val_loader, device, metrics_config=metrics_config)
            history.append(record)
            score = record.get("val", train)["loss"]
            improved = score < best
            if improved:
                best, best_epoch = score, epoch
            # Cùng quy tắc early stopping với TwoStage: min_delta điều khiển patience, checkpoint ghi mọi cải thiện tuyệt đối.
            if score < patience_best - min_delta:
                patience_best, bad_epochs = score, 0
            else:
                bad_epochs += 1
            stopped = patience is not None and bad_epochs >= patience
            record.update(best_epoch=best_epoch, stopped_early=stopped)
            if improved:
                if checkpoint_path is not None:
                    path = Path(checkpoint_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    torch.save(
                        {
                            "epoch": epoch,
                            "model": model.state_dict(),
                            "optimizer": optimizer.state_dict(),
                            "metrics": record,
                            "model_config": vars(model.config),
                            "training_seed": training_seed,
                            "model_seed": model_seed,
                            "best_epoch": best_epoch,
                            "metadata": checkpoint_metadata or {},
                            "metrics_config": metrics_config,
                        },
                        path,
                    )
            # Cập nhật postfix sau khi hoàn tất train và validation của từng epoch.
            postfix = {
                "loss_train": f"{train['loss']:.6f}",
                "loss_reg": f"{train['regression']:.6f}",
                "loss_tốt_nhất": f"{best:.6f}",
            }
            if "val" in record:
                postfix["loss_val"] = f"{record['val']['loss']:.6f}"
            progress.set_postfix(postfix)
            if stopped:
                tqdm.write(f"Dừng sớm ở epoch {epoch}; epoch tốt nhất: {best_epoch}.")
                break
    # Mô hình trả về giữ trọng số epoch cuối; trọng số tốt nhất nằm trong checkpoint.
    model.eval()
    return history
