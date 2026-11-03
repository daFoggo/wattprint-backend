"""Replay REFIT aggregate power into aggregate_power, a few minutes at a time (fake sensor).

  python scripts/simulate_sensor.py --csv data/CLEAN_House2.csv --house 99 \
      --owner-id <user id> --start 2015-01-05 --days 7 --interval 300
Needs SYNC_DATABASE_URL. --interval is real seconds between chunks (300 = real time).
"""
import argparse
import os
import time

import pandas as pd
import psycopg

import ingest_refit as ir  # reuse CUTOFF so preprocessing equals training


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--csv", required=True)
    a.add_argument("--house", type=int, required=True)
    a.add_argument("--owner-id", required=True)
    a.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    a.add_argument("--days", type=int, default=7)
    a.add_argument("--preload", type=int, default=256, help="minutes inserted at once at start")
    a.add_argument("--chunk", type=int, default=5, help="minutes inserted per tick")
    a.add_argument("--interval", type=float, default=300, help="real seconds between ticks")
    args = a.parse_args()

    df = pd.read_csv(args.csv, parse_dates=["Time"]).set_index("Time")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    t0 = pd.Timestamp(args.start, tz="UTC")
    t1 = t0 + pd.Timedelta(days=args.days)
    s = (
        df.loc[t0 : t1 - pd.Timedelta(seconds=1), "Aggregate"]
        .resample("10s").mean().ffill(limit=6)
        .clip(lower=0, upper=ir.CUTOFF)
        .resample(ir.STEP).mean()
        .dropna()  # minutes with no reading = sensor outage, nothing is inserted
    )
    TRUTH_COLS = {"washing_machine": "Appliance2", "dishwasher": "Appliance3",
                  "microwave": "Appliance5", "kettle": "Appliance8"}

    def to_minute(col):
        return (
            df.loc[t0 : t1 - pd.Timedelta(seconds=1), col]
            .resample("10s").mean().ffill(limit=6)
            .clip(lower=0, upper=ir.CUTOFF)
            .resample(ir.STEP).mean()
        )

    truth = {n: to_minute(c).reindex(s.index).fillna(0) for n, c in TRUTH_COLS.items() if c in df.columns}
    print(f"{len(s)} minutes to replay")

    with psycopg.connect(os.environ["SYNC_DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO houses (id, owner_id, name) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET owner_id = EXCLUDED.owner_id",
                (args.house, args.owner_id, f"REFIT simulated house {args.house}"),
            )
        conn.commit()

        i = 0
        while i < len(s):
            n = args.preload if i == 0 else args.chunk
            part = s.iloc[i : i + n]
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO aggregate_power (ts, house_id, watts) VALUES (%s,%s,%s) "
                    "ON CONFLICT (house_id, ts) DO UPDATE SET watts = EXCLUDED.watts",
                    [(t.to_pydatetime(), args.house, float(w)) for t, w in part.items()],
                )
                for name, ser in truth.items():
                    cur.executemany(
                        "INSERT INTO appliance_truth (ts, house_id, appliance, watts) VALUES (%s,%s,%s,%s) "
                        "ON CONFLICT (house_id, appliance, ts) DO UPDATE SET watts = EXCLUDED.watts",
                        [(t.to_pydatetime(), args.house, name, float(w)) for t, w in ser.loc[part.index].items()],
                    )
            conn.commit()
            print(f"sensor: +{len(part)} min  ({part.index[0]} -> {part.index[-1]})")
            i += n
            time.sleep(args.interval)
    print("replay finished")


if __name__ == "__main__":
    main()