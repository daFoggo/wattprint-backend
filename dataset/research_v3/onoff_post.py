"""Research v3, step 1: can the production ON/OFF detector do better without retraining?

The production bundles (dataset/models/nilm/house<N>/nilm_pipeline.pt) learnt every window before
the test split, validation included, so validation cannot tune anything here. The test split (last
20 %) is cut in two by time: the first half tunes each device's post-processing, the second half
scores it once, against the bundle as shipped on the same half.

Post-processing per device, all on P(ON) (mean of the 5 detectors):
  - threshold: one cut (the bundle's own, then re-tuned);
  - hysteresis: ON from `hi`, OFF under `lo` (lo <= hi), so a run does not flicker around one cut;
  - minimum durations: ON runs shorter than `min_on` steps dropped, OFF gaps shorter than
    `min_off` steps filled (a fridge's compressor runs for minutes, not 15 s).
Energy with the chosen mask: hard gate (mask x regressor power) against the shipped soft gate.

    uv run python dataset/research_v3/onoff_post.py --house 5
    -> dataset/research_v3/onoff_post_house5.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dataset" / "training"))
sys.path.insert(0, str(ROOT))

import train_house as th  # noqa: E402
from app.ml.nilm.GRUDetector import GRUConfig, GRUDetector  # noqa: E402
from app.ml.nilm.NILMFormerRegressor import NILMFormerConfig, NILMFormerRegressor  # noqa: E402

GRID = np.round(np.arange(0.04, 0.97, 0.04), 2)
DURATIONS = [0, 1, 2, 4, 8, 16, 32]  # steps of 15 s


@torch.no_grad()
def p_and_power(members, x):
    """P(ON) (mean of the detectors) and ON power (median of the regressors), (N, C, L)."""
    dets, regs, scales = [], [], []
    for m in members:
        d = GRUDetector(GRUConfig(**m["detector_config"]))
        d.load_state_dict(m["detector_state"])
        r = NILMFormerRegressor(NILMFormerConfig(**m["regressor_config"]))
        r.load_state_dict(m["regressor_state"])
        dets.append(d.to(th.DEVICE).eval()), regs.append(r.to(th.DEVICE).eval())
        scales.append(torch.as_tensor(m["scale_w"], device=th.DEVICE))
    ps, ws = [], []
    for i in range(0, len(x), 256):
        xb = torch.from_numpy(x[i : i + 256]).to(th.DEVICE)
        ps.append(torch.stack([torch.sigmoid(d(th.detector_inputs(xb))) for d in dets]).mean(0))
        w = [r(th.regressor_inputs(xb)) * s[None, :, None] for r, s in zip(regs, scales, strict=True)]
        ws.append(torch.stack(w).median(0).values.clamp(min=0))
    return torch.cat(ps).cpu().numpy(), torch.cat(ws).cpu().numpy()


def stitch(a: np.ndarray, starts) -> tuple[np.ndarray, np.ndarray]:
    """(N, C, L) windows in time order -> (C, N*L) and the first step of each contiguous run."""
    flat = a.transpose(1, 0, 2).reshape(a.shape[1], -1)
    step = th.SAMPLE * th.WINDOW
    gaps = np.r_[True, np.diff(starts.values) != step.to_timedelta64()]
    breaks = np.zeros(flat.shape[1], dtype=bool)
    breaks[np.flatnonzero(gaps) * th.WINDOW] = True
    return flat, breaks


def hysteresis(p: np.ndarray, lo: float, hi: float, breaks: np.ndarray) -> np.ndarray:
    """ON from p >= hi until p < lo; a run starts OFF unless p >= hi."""
    state = np.where(p >= hi, 1.0, np.where(p < lo, 0.0, np.nan))
    state[breaks & np.isnan(state)] = 0.0
    idx = np.where(~np.isnan(state), np.arange(len(p)), 0)
    np.maximum.accumulate(idx, out=idx)
    return state[idx] == 1.0


def min_durations(m: np.ndarray, min_on: int, min_off: int, breaks: np.ndarray) -> np.ndarray:
    """Fill OFF gaps shorter than min_off, then drop ON runs shorter than min_on; runs never
    cross a break (a gap in the recording)."""
    out = m.copy()
    for value, shortest in ((False, min_off), (True, min_on)):
        if shortest <= 1:
            continue
        change = np.r_[True, out[1:] != out[:-1]] | breaks
        starts = np.flatnonzero(change)
        lengths = np.diff(np.r_[starts, len(out)])
        short = (out[starts] == value) & (lengths < shortest)
        # A gap is filled only between two ON runs (not at a run's edge): look at neighbours.
        if not value:
            prev_on = np.r_[False, out[starts[:-1]]] & ~breaks[starts]
            next_on = np.r_[out[starts[1:]], False] & ~np.r_[breaks[starts[1:]], True]
            short &= prev_on & next_on
        out[np.repeat(short, lengths)] = not value
    return out


def f1(t: np.ndarray, p: np.ndarray) -> float:
    tp, fp, fn = (t & p).sum(), (~t & p).sum(), (t & ~p).sum()
    return float(2 * tp / max(2 * tp + fp + fn, 1))


def energy(t_w: np.ndarray, p_w: np.ndarray) -> dict:
    k = th.SAMPLE.total_seconds() / 3.6e6
    return {
        "energy F1": float(2 * np.minimum(t_w, p_w).sum() / max(t_w.sum() + p_w.sum(), 1e-9)),
        "kWh err %": float(100 * (p_w.sum() / max(t_w.sum(), 1e-9) - 1)),
        "true kWh": float(t_w.sum() * k),
    }


def tune(p, t, breaks):
    """Best (lo, hi, min_on, min_off) by F1 on the tuning half: the cut, then the hysteresis
    around it, then the durations, then the hysteresis again with them."""
    best = max(((f1(t, p >= c), c) for c in GRID))
    lo = hi = best[1]
    pairs = [(a, b) for a in GRID for b in GRID if a <= b and abs(a - lo) <= 0.32 and abs(b - hi) <= 0.32]
    score, lo, hi = max((f1(t, hysteresis(p, a, b, breaks)), a, b) for a, b in pairs)
    on_off = [(a, b) for a in DURATIONS for b in DURATIONS]
    score, mon, moff = max(
        (f1(t, min_durations(hysteresis(p, lo, hi, breaks), a, b, breaks)), a, b) for a, b in on_off
    )
    score, lo, hi = max(
        (f1(t, min_durations(hysteresis(p, a, b, breaks), mon, moff, breaks)), a, b)
        for a, b in pairs
    )
    return {"cut": float(best[1]), "lo": float(lo), "hi": float(hi), "min_on": mon, "min_off": moff}


def main(house: int) -> None:
    bundle = torch.load(
        ROOT / "dataset" / "models" / "nilm" / f"house{house}" / "nilm_pipeline.pt",
        map_location="cpu",
        weights_only=True,
    )
    labels = bundle["labels"]
    on_w = np.array(bundle["on_threshold_w"], dtype=np.float32)
    x, y, start, end = th.load(house)
    lab = th.split(start, end)
    test = np.flatnonzero(lab == "test")
    test = test[np.argsort(start[test])]
    halves = {"tune": test[: len(test) // 2], "score": test[len(test) // 2 :]}
    out = {"house": house, "bundle": str(bundle["meta"].get("trained_until")), "devices": {}}
    data = {}
    for name, ids in halves.items():
        p, w = p_and_power(bundle["members"], x[ids])
        pf, breaks = stitch(p, start[ids])
        wf, _ = stitch(w, start[ids])
        yf, _ = stitch(y[ids], start[ids])
        data[name] = (pf, wf, yf, breaks)
        print(f"house {house} {name}: {pf.shape[1]:,} steps, {breaks.sum()} runs", flush=True)
    for c, label in enumerate(labels):
        pt, _, yt, bt = data["tune"]
        ps, ws, ys, bs = data["score"]
        t_tune, t_score = yt[c] >= on_w[c], ys[c] >= on_w[c]
        chosen = tune(pt[c], t_tune, bt)
        shipped = ps[c] >= bundle["event_thresholds"][c]
        cut = ps[c] >= chosen["cut"]
        hyst = hysteresis(ps[c], chosen["lo"], chosen["hi"], bs)
        post = min_durations(hyst, chosen["min_on"], chosen["min_off"], bs)
        out["devices"][label] = {
            "on share": float(t_score.mean()),
            "chosen": chosen,
            "F1 ON/OFF": {
                "shipped cut": f1(t_score, shipped),
                "re-tuned cut": f1(t_score, cut),
                "hysteresis": f1(t_score, hyst),
                "hysteresis + durations": f1(t_score, post),
            },
            "energy": {
                "soft gate (shipped)": energy(ys[c], ps[c] * ws[c]),
                "hard gate, shipped cut": energy(ys[c], shipped * ws[c]),
                "hard gate, post mask": energy(ys[c], post * ws[c]),
            },
        }
        d = out["devices"][label]
        print(
            f"{label:10s} on {d['on share']:.2f} | F1 "
            + " ".join(f"{k} {v:.3f}" for k, v in d["F1 ON/OFF"].items())
            + " | energy F1 / kWh err: "
            + " ".join(f"{k} {v['energy F1']:.3f}/{v['kWh err %']:+.0f}%" for k, v in d["energy"].items()),
            flush=True,
        )
    path = ROOT / "dataset" / "research_v3" / f"onoff_post_house{house}.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"saved {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", type=int, required=True, choices=sorted(th.CHANNELS))
    main(ap.parse_args().house)
