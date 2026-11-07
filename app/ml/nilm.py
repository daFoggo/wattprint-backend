"""NILMFormer inference: one checkpoint per appliance, one window of aggregate power in.

torch is imported at module level, so import this module lazily (the replay job does) to keep
the API start-up light and to let the API run without the torch extra installed.
"""

import sys
import threading
import types
from pathlib import Path

import numpy as np
import torch

from ..config import settings
from . import NILM_APPLIANCES, WINDOW  # noqa: F401  (WINDOW re-exported for callers)

# Appliance (catalog.device_type code) -> checkpoint file in settings.nilm_ckpt_dir.
CKPT_FILES = {
    "kettle": "NILMFormer_custom0_kettle.pt",
    "microwave": "NILMFormer_custom0_microwave.pt",
    "dishwasher": "NILMFormer_custom0_dishwasher.pt",
    "washing_machine": "NILMFormer_custom0_washingmachine.pt",
}
assert tuple(CKPT_FILES) == NILM_APPLIANCES, "CKPT_FILES and app.ml.NILM_APPLIANCES must match"
MIN_THRESHOLD = {"kettle": 500, "microwave": 200, "dishwasher": 300, "washing_machine": 300}
EXO_VARS = ("minute", "hour", "dow", "month")  # order used in training (configs/expes.yaml)
EXO_DIV = {"minute": 60.0, "hour": 24.0, "dow": 7.0, "month": 12.0}

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

_models: dict | None = None
_lock = threading.Lock()


def _stub_xformers() -> None:
    """NILMFormer imports xformers.ops but never calls it (use_efficient_attention=False).

    A stub avoids installing xformers, which would pull in its own pinned torch build.
    """
    if "xformers" in sys.modules:
        return
    pkg = types.ModuleType("xformers")
    ops = types.ModuleType("xformers.ops")
    pkg.ops = ops
    sys.modules["xformers"] = pkg
    sys.modules["xformers.ops"] = ops


def _load_models() -> dict:
    repo = str(Path(settings.nilm_repo_path).resolve())
    if repo not in sys.path:
        sys.path.insert(0, repo)
    _stub_xformers()
    from src.nilmformer.congif import NILMFormerConfig  # "congif" is the upstream spelling
    from src.nilmformer.model import NILMFormer

    models = {}
    for name, fname in CKPT_FILES.items():
        model = NILMFormer(NILMFormerConfig(c_in=1, c_embedding=2 * len(EXO_VARS), c_out=1))
        ckpt = torch.load(
            Path(settings.nilm_ckpt_dir) / fname, map_location="cpu", weights_only=False
        )
        model.load_state_dict(ckpt.get("best_model_state_dict") or ckpt["model_state_dict"])
        models[name] = model.to(DEVICE).eval()
    print(f"NILM models loaded on {DEVICE}: {list(models)}", flush=True)
    return models


def get_models() -> dict:
    global _models
    with _lock:
        if _models is None:
            _models = _load_models()
    return _models


def _exo(start_minute: int, window: int) -> np.ndarray:
    """(2 * len(EXO_VARS), window): sin then cos per variable, like NILMDataset."""
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
    (minutes since the epoch, in the clock the models were trained on).
    Returns {appliance: (n_windows, W) watts}."""
    w = agg_watts.shape[1]
    scale = settings.nilm_scale
    x_agg = np.clip(agg_watts, 0, scale) / scale
    exo = np.stack([_exo(m, w) for m in start_minutes])
    x = torch.from_numpy(np.concatenate([x_agg[:, None, :], exo], axis=1).astype(np.float32))
    x = x.to(DEVICE)
    out = {}
    for name, model in get_models().items():
        y = torch.cat([model(x[i : i + 64]) for i in range(0, len(x), 64)])[:, 0, :].cpu().numpy()
        y = np.clip(y * scale, 0, None)
        y[y < MIN_THRESHOLD[name]] = 0
        out[name] = y
    return out
