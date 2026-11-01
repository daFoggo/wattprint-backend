import sys
import threading
from pathlib import Path

import numpy as np
import torch

from app.core.config import settings

CKPT_FILES = {
    "kettle": "NILMFormer_custom0_kettle.pt",
    "microwave": "NILMFormer_custom0_microwave.pt",
    "dishwasher": "NILMFormer_custom0_dishwasher.pt",
    "washing_machine": "NILMFormer_custom0_washingmachine.pt",
}
MIN_THRESHOLD = {"kettle": 500, "microwave": 200, "dishwasher": 300, "washing_machine": 300}
EXO_VARS = ("minute", "hour", "dow", "month")  # order used in training (configs/expes.yaml)
EXO_DIV = {"minute": 60.0, "hour": 24.0, "dow": 7.0, "month": 12.0}

_models = None
_lock = threading.Lock()


def _load_models():
    repo = Path(settings.nilm_repo_path).resolve()
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from src.nilmformer.congif import NILMFormerConfig  
    from src.nilmformer.model import NILMFormer

    models = {}
    for name, fname in CKPT_FILES.items():
        model = NILMFormer(NILMFormerConfig(c_in=1, c_embedding=2 * len(EXO_VARS), c_out=1))
        ckpt = torch.load(Path(settings.nilm_ckpt_dir) / fname, map_location="cpu", weights_only=False)
        model.load_state_dict(ckpt.get("best_model_state_dict") or ckpt["model_state_dict"])
        models[name] = model.eval()
    return models


def get_models():
    global _models
    with _lock:
        if _models is None:
            _models = _load_models()
    return _models


def _exo(start_minute: int, window: int) -> np.ndarray:
    """(2*len(EXO_VARS), window): sin then cos per variable, like NILMDataset."""
    t = (start_minute + np.arange(window)).astype("datetime64[m]")
    hours, days = t.astype("datetime64[h]"), t.astype("datetime64[D]")
    vals = {
        "minute": (t - hours).astype(int),
        "hour": (hours - days).astype(int),
        "dow": (days.astype(int) + 3) % 7,  # 1970-01-01 is Thursday; pandas Monday = 0
        "month": t.astype("datetime64[M]").astype(int) % 12 + 1,
    }
    rows = []
    for v in EXO_VARS:
        ang = 2 * np.pi * vals[v] / EXO_DIV[v]
        rows += [np.sin(ang), np.cos(ang)]
    return np.stack(rows).astype(np.float32)


@torch.no_grad()
def predict(start_minutes: list[int], agg_watts: np.ndarray) -> dict[str, np.ndarray]:
    """agg_watts: (n_windows, W) watts, one row per window starting at start_minutes[i]
    (minutes since epoch). Returns {appliance: (n_windows, W) watts}."""
    W = agg_watts.shape[1]
    x_agg = np.clip(agg_watts, 0, settings.nilm_scale) / settings.nilm_scale
    exo = np.stack([_exo(m, W) for m in start_minutes])
    x = torch.from_numpy(np.concatenate([x_agg[:, None, :], exo], axis=1).astype(np.float32))
    out = {}
    for name, model in get_models().items():
        y = torch.cat([model(x[i : i + 64]) for i in range(0, len(x), 64)])[:, 0, :].numpy()
        y = np.clip(y * settings.nilm_scale, 0, None)
        y[y < MIN_THRESHOLD[name]] = 0
        out[name] = y
    return out

