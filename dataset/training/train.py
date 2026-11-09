from pathlib import Path

import numpy as np
import pandas as pd
import torch
from tqdm.auto import tqdm
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .model.NILMFormer import NILMFormer, NILMFormerConfig

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "refit_house2_windows.npz"
SEEDS = [11, 22, 33, 44, 55]
EPOCHS = 50
BATCH_SIZE = 64
LEARNING_RATE = 1e-4
PATIENCE = 7


def metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    eps = 1e-8
    err = pred - y
    return {
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err**2))),
        "TECA": float(1 - np.abs(err).sum() / (2 * np.abs(y).sum() + eps)),
        "NDE": float((err**2).sum() / ((y**2).sum() + eps)),
        "SAE": float(np.abs(pred.sum() - y.sum()) / (np.abs(y).sum() + eps)),
        "MatchingRate": float(np.minimum(np.maximum(pred, 0), np.maximum(y, 0)).sum() /
                               (np.maximum(pred, 0) + np.maximum(y, 0)).sum().clip(min=eps)),
    }


if __name__ == "__main__":
    with np.load(DATA) as z:
        x, y = z["x"].astype(np.float32), z["y"].astype(np.float32)
        tau = float(z["tau_max"])
        names = z["appliance_names"].astype(str).tolist()
        starts = pd.to_datetime(z["window_start"])
    if y.shape[1] != len(names):
        raise ValueError(f"Targets have {y.shape[1]} channels but metadata has {len(names)}")

    gap2_start, gap2_end = starts.min(), starts.max()


    # Gap 2 is the latest continuous date range; reserve its final 20% of days.
    cutoff = gap2_start + (gap2_end - gap2_start) * 0.8
    gap2 = (starts >= gap2_start) & (starts <= gap2_end)
    train_pool = np.flatnonzero(gap2 & (starts < cutoff))
    test_count = int((gap2 & (starts >= cutoff)).sum())
    if len(train_pool) < 2:
        raise ValueError("Not enough pre-test windows in gap 2")

    val_start = int(len(train_pool) * 0.85)
    train_ids, val_ids = train_pool[:val_start], train_pool[val_start:]
    print(f"gap2={gap2_start.date()}..{gap2_end.date()} cutoff={cutoff.date()} "
          f"train={len(train_ids)} val={len(val_ids)} held_out_test={test_count}")

    def loader(index: np.ndarray, shuffle: bool) -> DataLoader:
        return DataLoader(TensorDataset(torch.from_numpy(x[index]), torch.from_numpy(y[index])),
                          batch_size=BATCH_SIZE, shuffle=shuffle)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    loss_fn = nn.MSELoss()
    output_dir = ROOT / "checkpoints"
    output_dir.mkdir(parents=True, exist_ok=True)
    for seed in SEEDS:
        torch.manual_seed(seed)
        np.random.seed(seed)
        train_loader, val_loader = loader(train_ids, True), loader(val_ids, False)
        model = NILMFormer(NILMFormerConfig(c_out=y.shape[1])).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE)
        best, stale = float("inf"), 0
        checkpoint = output_dir / f"nilmformer_full_channels_seed_{seed}.pt"
        for epoch in range(EPOCHS):
            model.train()
            progress = tqdm(train_loader, desc=f"seed {seed} epoch {epoch+1}/{EPOCHS}", leave=False)
            total, batches = 0.0, 0
            for xb, yb in progress:
                xb, yb = xb.to(device), yb.to(device)
                optimizer.zero_grad(set_to_none=True)
                loss = loss_fn(model(xb), yb)
                loss.backward()
                optimizer.step()
                total += loss.item(); batches += 1
                progress.set_postfix(loss=f"{total/batches:.5f}")
            model.eval()
            losses = []
            with torch.no_grad():
                for xb, yb in val_loader:
                    losses.append(loss_fn(model(xb.to(device)), yb.to(device)).item())
            val_loss = float(np.mean(losses))
            print(f"seed={seed} epoch={epoch+1} train_loss={total/max(batches,1):.6f} val_loss={val_loss:.6f}", flush=True)
            if val_loss < best:
                best, stale = val_loss, 0
                torch.save({"model": model.state_dict(), "config": model.config.__dict__,
                            "tau_max": tau, "appliance_names": names, "seed": seed,
                            "best_val_mse": best, "cutoff": str(cutoff)}, checkpoint)
            else:
                stale += 1
                if stale >= PATIENCE:
                    print(f"seed={seed} early stopping at epoch {epoch+1}")
                    break
        print(f"seed={seed} checkpoint={checkpoint} best_val_mse={best:.6f}")
