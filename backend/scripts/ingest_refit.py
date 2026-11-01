"""Run per-appliance NILMFormer checkpoints on REFIT aggregate power and store the
result in TimescaleDB (table appliance_power).

NILMFormer (adrienpetralia/NILMFormer) is trained ONE MODEL PER APPLIANCE (c_out=1), so
pass one checkpoint per appliance.

Example (demo: house 2, 2015-01-05 .. 2015-01-11):

  export SYNC_DATABASE_URL=postgresql://USER:PASS@localhost:5434/wattprint
  python scripts/ingest_refit.py \
      --csv /data/REFIT/CLEAN_House2.csv --house 2 \
      --start 2015-01-05 --days 7 \
      --nilmformer-repo /path/to/NILMFormer \
      --window-size 256 --scale 6000 \
      --ckpt kettle=ckpt/Kettle.pt microwave=ckpt/Microwave.pt \
             dishwasher=ckpt/Dishwasher.pt washing_machine=ckpt/WashingMachine.pt \
      --truth

Preprocessing MUST equal training (see configs/expes.yaml in the NILMFormer repo):
  * resample to 1 min (mean)
  * MaxScaling: x_scaled = aggregate / SCALE, where SCALE = scaler.power_stat2 from training
    (the max aggregate power the scaler saw). Appliance output uses the same factor
    (appliance_scaling_type = SameAsPower).
  * exogenous channels, in order of list_exo_variables (default: minute hour dow month),
    each as [sin, cos] -> model input is (B, 1 + 2*n_exo, window_size).
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
import torch

STEP = "1min"  # must match training and app/modules/disaggregation/service.py (STEP_HOURS)
# REFIT_DataBuilder defaults in the NILMFormer repo (src/helpers/preprocessing.py)
CUTOFF = 10000.0  # aggregate is clipped to [0, CUTOFF] before scaling
MIN_THRESHOLD = {"kettle": 500, "washing_machine": 300, "dishwasher": 300, "microwave": 200}
EXO_DIV = {"month": 12.0, "dom": 31.0, "dow": 7.0, "hour": 24.0, "minute": 60.0}


def kv(items):
    return {k: v for k, v in (s.split("=", 1) for s in items)}


def exo_features(starts, window, variables):
    """(n_windows, 2*len(variables), window): sin then cos per variable, as in NILMDataset."""
    out = np.zeros((len(starts), 2 * len(variables), window), dtype=np.float32)
    for w, st in enumerate(starts):
        idx = pd.date_range(start=st, periods=window, freq=STEP)
        parts = {
            "month": idx.month, "dom": idx.day, "dow": idx.dayofweek,
            "hour": idx.hour, "minute": idx.minute,
        }
        k = 0
        for v in variables:
            ang = 2 * np.pi * np.asarray(parts[v]) / EXO_DIV[v]
            out[w, k], out[w, k + 1] = np.sin(ang), np.cos(ang)
            k += 2
    return out


def load_model(repo, ckpt_path, n_exo, device):
    sys.path.insert(0, repo)
    from src.nilmformer.congif import NILMFormerConfig  # "congif" typo is upstream's
    from src.nilmformer.model import NILMFormer

    # other fields keep defaults == configs/models.yaml (d_model=96, 3 layers, 8 heads...)
    model = NILMFormer(NILMFormerConfig(c_in=1, c_embedding=2 * n_exo, c_out=1))
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    state = ckpt.get("best_model_state_dict") or ckpt.get("model_state_dict") or ckpt
    model.load_state_dict(state)
    return model.to(device).eval()


@torch.no_grad()
def predict(model, agg_w, exo, device, bs=64):
    """agg_w (n_win, W) scaled -> (n_win, W) scaled appliance power."""
    x = np.concatenate([agg_w[:, None, :], exo], axis=1).astype(np.float32)
    outs = []
    for i in range(0, len(x), bs):
        y = model(torch.from_numpy(x[i:i + bs]).to(device))  # (B, 1, W)
        outs.append(y[:, 0, :].cpu().numpy())
    return np.concatenate(outs)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--csv", required=True, help="REFIT CLEAN_HouseN.csv")
    a.add_argument("--house", type=int, required=True)
    a.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    a.add_argument("--days", type=int, default=7)
    a.add_argument("--nilmformer-repo", required=True)
    a.add_argument("--window-size", type=int, default=256,
                   help="window used in training (repo default 256; paper sweeps 128/256/512/360/720)")
    a.add_argument("--scale", type=float, default=CUTOFF,
                   help="training scaler.power_stat2 (W); REFIT default = cutoff = 10000")
    a.add_argument("--cutoff", type=float, default=CUTOFF, help="clip aggregate to this (W)")
    a.add_argument("--exo", nargs="*", default=["minute", "hour", "dow", "month"])
    a.add_argument("--ckpt", nargs="+", required=True, help="appliance=path.pt ...")
    a.add_argument("--threshold", nargs="*", default=[], help="appliance=watts: below -> 0")
    a.add_argument("--truth", action="store_true", help="also print ground-truth sub-meter kWh")
    a.add_argument("--dry-run", action="store_true", help="do not write to the DB")
    a.add_argument("--owner-id", required=True,
                   help="Better Auth user id (auth.\"user\".id) that owns this house")
    args = a.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    ckpts = kv(args.ckpt)
    thr = {**MIN_THRESHOLD, **{k: float(v) for k, v in kv(args.threshold).items()}}

    df = pd.read_csv(args.csv, parse_dates=["Time"]).set_index("Time")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    t0 = pd.Timestamp(args.start, tz="UTC")
    t1 = t0 + pd.Timedelta(days=args.days)
    df = df.loc[t0 : t1 - pd.Timedelta(seconds=1)]
    full = pd.date_range(t0, t1, freq=STEP, inclusive="left")
    # same as REFIT_DataBuilder: 10s mean + ffill(limit=6), clip, then mean to 1 min
    def to_step(s):
        return s.resample("10s").mean().ffill(limit=6).clip(lower=0, upper=args.cutoff).resample(STEP).mean()

    agg = to_step(df["Aggregate"]).reindex(full)
    print(f"missing minutes in aggregate: {int(agg.isna().sum())} / {len(agg)}")
    agg = agg.fillna(0)

    W = args.window_size
    a_np = agg.to_numpy(dtype=np.float32)
    starts_i = list(range(0, len(a_np) - W + 1, W))
    if starts_i[-1] + W < len(a_np):
        starts_i.append(len(a_np) - W)  # last window overlaps so the tail is covered
    wins = np.stack([a_np[i : i + W] for i in starts_i]) / args.scale
    exo = exo_features(agg.index[starts_i], W, args.exo)

    series = {"aggregate": a_np}
    for name, path in ckpts.items():
        model = load_model(args.nilmformer_repo, path, len(args.exo), device)
        pred = predict(model, wins, exo, device) * args.scale  # inverse MaxScaling
        full_pred = np.zeros(len(a_np), dtype=np.float32)
        for row, i in zip(pred, starts_i):
            full_pred[i : i + W] = row
        full_pred = np.clip(full_pred, 0, None)
        full_pred[full_pred < thr.get(name, 0.0)] = 0
        series[name] = full_pred

    print("\nkWh over period (model):")
    for k, v in series.items():
        print(f"  {k:16s} {v.sum() / 60 / 1000:8.3f}")

    if args.truth:  # REFIT House 2 mapping per the REFIT readme - verify for other houses
        col = {"washing_machine": "Appliance2", "dishwasher": "Appliance3",
               "microwave": "Appliance5", "kettle": "Appliance8"}
        print("kWh over period (ground-truth sub-meters):")
        for name, c in col.items():
            if name in series and c in df:
                gt = to_step(df[c]).reindex(full).fillna(0)
                print(f"  {name:16s} {gt.sum() / 60 / 1000:8.3f}")

    if args.dry_run:
        return
    import psycopg

    # tách tổng cả nhà ra khỏi các thiết bị: hai bảng khác nhau
    agg_rows = [
        (t.to_pydatetime(), args.house, float(w))
        for t, w in zip(agg.index, series.pop("aggregate"))
    ]
    app_rows = [
        (t.to_pydatetime(), args.house, name, float(w))
        for name, arr in series.items()
        for t, w in zip(agg.index, arr)
    ]
    with psycopg.connect(os.environ["SYNC_DATABASE_URL"]) as conn, conn.cursor() as cur:
        # bảng appliance_power/aggregate_power có FK tới houses, nên phải có nhà trước
        cur.execute(
            "INSERT INTO houses (id, owner_id, name) VALUES (%s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET owner_id = EXCLUDED.owner_id",
            (args.house, args.owner_id, f"REFIT house {args.house}"),
        )
        cur.executemany(
            "INSERT INTO aggregate_power (ts, house_id, watts) VALUES (%s,%s,%s) "
            "ON CONFLICT (house_id, ts) DO UPDATE SET watts = EXCLUDED.watts",
            agg_rows,
        )
        cur.executemany(
            "INSERT INTO appliance_power (ts, house_id, appliance, watts) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (house_id, appliance, ts) DO UPDATE SET watts = EXCLUDED.watts",
            app_rows,
        )
    print(f"\ninserted {len(agg_rows)} aggregate rows + {len(app_rows)} appliance rows "
          f"for house {args.house}")


if __name__ == "__main__":
    main()
