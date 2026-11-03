"""Every --interval seconds: if aggregate_power has minutes newer than the last prediction,
run NILMFormer on the last WINDOW minutes and store watts of each appliance for the NEW
minutes only (appliance_power).

  python scripts/nilm_worker.py --house 99 --nilmformer-repo third_party/NILMFormer \
      --ckpt kettle=checkpoints/NILMFormer_custom0_kettle.pt ... --interval 300
Needs SYNC_DATABASE_URL.
"""
import argparse
import os
import time

import numpy as np
import pandas as pd
import psycopg
import torch

import ingest_refit as ir  # load_model / predict / exo_features / STEP / CUTOFF / MIN_THRESHOLD


def tick(conn, house, models, W, scale, exo, thr, device):
    with conn.cursor() as cur:
        cur.execute("SELECT max(ts) FROM aggregate_power WHERE house_id = %s", (house,))
        newest = cur.fetchone()[0]
        cur.execute("SELECT max(ts) FROM appliance_power WHERE house_id = %s", (house,))
        done = cur.fetchone()[0]
        if newest is None or (done is not None and newest <= done):
            print("no new data")
            return

        end = pd.Timestamp(newest).tz_convert("UTC").floor("min")
        grid = pd.date_range(end=end, periods=W, freq=ir.STEP)  # W minutes ending at `end`
        cur.execute(
            "SELECT ts, watts FROM aggregate_power "
            "WHERE house_id = %s AND ts BETWEEN %s AND %s ORDER BY ts",
            (house, grid[0].to_pydatetime(), end.to_pydatetime()),
        )
        rows = cur.fetchall()
        if len(rows) < 0.9 * W:
            print(f"warming up: {len(rows)}/{W} minutes of history")
            return

        s = pd.Series(
            [r[1] for r in rows], index=pd.to_datetime([r[0] for r in rows], utc=True)
        ).reindex(grid)
        agg = s.fillna(0).clip(0, ir.CUTOFF).to_numpy(np.float32)  # gaps -> 0, like ingest
        x = (agg / scale)[None, :]                                  # (1, W)
        e = ir.exo_features([grid[0]], W, exo)                      # (1, 2*n_exo, W)
        if done is None:
            new = np.ones(W, dtype=bool)
        else:
            new = np.asarray(grid > pd.Timestamp(done).tz_convert("UTC"))

        out = []
        for name, model in models.items():
            y = ir.predict(model, x, e, device)[0] * scale
            y = np.clip(y, 0, None)
            y[y < thr.get(name, 0.0)] = 0
            out += [(t.to_pydatetime(), house, name, float(w)) for t, w, m in zip(grid, y, new) if m]

        cur.executemany(
            "INSERT INTO appliance_power (ts, house_id, appliance, watts) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (house_id, appliance, ts) DO UPDATE SET watts = EXCLUDED.watts",
            out,
        )
    conn.commit()
    print(f"predicted {int(new.sum())} new minutes up to {end}  ({len(out)} rows)")


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--house", type=int, required=True)
    a.add_argument("--nilmformer-repo", required=True)
    a.add_argument("--ckpt", nargs="+", required=True, help="appliance=path.pt ...")
    a.add_argument("--window-size", type=int, default=256)
    a.add_argument("--scale", type=float, default=ir.CUTOFF)
    a.add_argument("--exo", nargs="*", default=["minute", "hour", "dow", "month"])
    a.add_argument("--threshold", nargs="*", default=[], help="appliance=watts")
    a.add_argument("--interval", type=float, default=300, help="seconds between checks")
    a.add_argument("--once", action="store_true", help="check once and exit")
    args = a.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    models = {
        name: ir.load_model(args.nilmformer_repo, path, len(args.exo), device)
        for name, path in ir.kv(args.ckpt).items()
    }
    thr = {**ir.MIN_THRESHOLD, **{k: float(v) for k, v in ir.kv(args.threshold).items()}}
    print(f"worker ready on {device}, models: {list(models)}")

    with psycopg.connect(os.environ["SYNC_DATABASE_URL"]) as conn:
        while True:
            tick(conn, args.house, models, args.window_size, args.scale, args.exo, thr, device)
            if args.once:
                break
            time.sleep(args.interval)


if __name__ == "__main__":
    main()