"""How much routine the main meter alone gives away, per data resolution (REFIT files, no database).

Usage: uv run python scripts/privacy_risk_by_granularity.py   (writes docs/evidence/privacy/)
The reference is a rule on the raw ~8 s samples, not ground truth: nobody recorded the routine.
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/privacy"
HOUSES = (2, 3, 5, 6)

# Times are minutes since 04:00, so a bed time after midnight stays on the day it ends.
WAKE = (0, 8 * 60)  # 04:00-12:00
BED = (16 * 60, 24 * 60)  # 20:00-04:00
DAYTIME = (3 * 60, 19 * 60)  # 07:00-23:00
STEP_W = 200  # raw step-up counted as someone switching something on (wake, bed)
AWAY_STEP_W = 1000  # kettle-sized step: none all daytime = reference "away"
ABOVE_NIGHT_W = 200  # minute/hour mean this far above the night level = active
TOLERANCE_MIN = 30
MIN_DAYS = 5  # fewer than this and no level is given
NAMES = {"wake": "Giờ thức dậy", "bed": "Giờ đi ngủ", "away": "Ngày vắng nhà"}
RESOLUTIONS = {"minute": "Từng phút", "hour": "Từng giờ", "day": "Từng ngày"}


def level(hit: int, total: int) -> str:
    if total < MIN_DAYS:
        return "quá ít ngày"
    return "cao" if hit >= 0.7 * total else "vừa" if hit >= 0.4 * total else "thấp"


def routine_day(ts: pd.DatetimeIndex) -> tuple[pd.DatetimeIndex, np.ndarray]:
    shifted = ts - pd.Timedelta(hours=4)
    day = shifted.normalize()
    return day, ((shifted - day) // pd.Timedelta(minutes=1)).to_numpy()


def within(m: np.ndarray, window: tuple[int, int]) -> np.ndarray:
    return (m >= window[0]) & (m < window[1])


def reference(raw: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """From raw samples (local `ts`, `unix`, `watts`): two step-ups within 10 min = someone up."""
    step = raw["watts"].diff().where(raw["unix"].diff() <= 60)
    out = pd.DataFrame(index=days, columns=["wake", "bed", "away"], dtype=float)
    ev = raw.loc[step >= STEP_W, "ts"]
    day, m = routine_day(pd.DatetimeIndex(ev))
    e = pd.DataFrame({"day": day, "m": m})
    gap = pd.Timedelta(minutes=10)
    has_next = (ev.shift(-1) - ev <= gap).to_numpy()
    has_prev = (ev - ev.shift(1) <= gap).to_numpy()
    out["wake"] = e[has_next & within(m, WAKE)].groupby("day")["m"].min()
    out["bed"] = e[has_prev & within(m, BED)].groupby("day")["m"].max()
    day, m = routine_day(pd.DatetimeIndex(raw.loc[step >= AWAY_STEP_W, "ts"]))
    out["away"] = (~days.isin(day[within(m, DAYTIME)])).astype(float)
    return out


def from_series(power: pd.Series, width: int, run: int, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Estimate from mean power in `width`-minute slots; active = `run` slots in a row."""
    clock = power.index.hour
    night = power[(clock >= 1) & (clock < 5)]
    night = night.groupby(night.index.normalize()).median()
    day, m = routine_day(power.index)
    active = power > night.reindex(day).to_numpy() + ABOVE_NIGHT_W  # NaN compares False
    starts = active.copy()
    for k in range(1, run):
        starts &= active.shift(-k, fill_value=False)
    f = pd.DataFrame({"day": day, "m": m})[starts.to_numpy()]
    out = pd.DataFrame(index=days, columns=["wake", "bed", "away"], dtype=float)
    # A one-minute run is dated to its edge; an hour slot only to its middle.
    wake = f[within(f["m"], WAKE)].groupby("day")["m"].min()
    bed = f[within(f["m"], BED)].groupby("day")["m"].max()
    out["wake"] = wake + (width / 2 if width > 1 else 0)
    out["bed"] = bed + (width / 2 if width > 1 else run)
    busy = pd.Series(active.to_numpy() & within(m, DAYTIME), index=day).groupby(level=0).sum()
    out["away"] = (busy.reindex(days) <= (30 if width == 1 else 0)).astype(float)
    return out


def from_daily(power: pd.Series, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Daily totals carry no clock time: only "unusually low day" can be guessed."""
    day, _ = routine_day(power.index)
    mean = power.groupby(day).mean().reindex(days)  # mean W, so small gaps do not lower a day
    out = pd.DataFrame(index=days, columns=["wake", "bed", "away"], dtype=float)
    out["away"] = (mean < 0.5 * mean.median()).astype(float)
    return out


def analyse(raw: pd.DataFrame) -> list[dict]:
    minute = raw.set_index("ts")["watts"].resample("1min").mean()
    day, _ = routine_day(minute.index)
    covered = minute.notna().groupby(day).sum()
    days = pd.DatetimeIndex(covered[covered >= 0.9 * 1440].index)
    ref = reference(raw, days)
    estimates = {
        "minute": from_series(minute, 1, 3, days),
        "hour": from_series(minute.resample("1h").mean(), 60, 1, days),
        "day": from_daily(minute, days),
    }
    rows = []
    for res, est in estimates.items():
        for item in NAMES:
            row = {"resolution": res, "item": item, "days_compared": len(days)}
            if item == "away":
                r, e = ref[item] == 1, est[item] == 1
                hit, total = int((r & e).sum()), int((r | e).sum())
                row |= {"reference_days": int(r.sum()), "estimate_days": int(e.sum())}
                row |= {"agree": hit, "out_of": total, "level": level(hit, total)}
            elif res == "day":
                row |= {"level": "không có giờ"}
            else:
                has = ref[item].notna()
                hit = int(((est[item] - ref[item]).abs()[has] <= TOLERANCE_MIN).sum())
                row |= {"reference_days": int(has.sum())}
                row |= {"estimate_days": int(est[item].notna().sum())}
                row |= {"agree": hit, "out_of": int(has.sum())}
                row |= {"level": level(hit, int(has.sum()))}
            rows.append(row)
    return rows


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=["Unix", "Aggregate"]).dropna().sort_values("Unix")
    wall = pd.to_datetime(df["Unix"], unit="s", utc=True).dt.tz_convert("Europe/London")
    return pd.DataFrame(
        {"ts": wall.dt.tz_localize(None), "unix": df["Unix"], "watts": df["Aggregate"]}
    ).reset_index(drop=True)


def chart(table: pd.DataFrame) -> str:
    fills = {"cao": "#bf4520", "vừa": "#4f5d75", "thấp": "#ffffff"}
    houses = sorted(table["house"].unique())
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 360" role="img" '
        "font-family=\"'Geist', system-ui, sans-serif\">",
        "<title>Mức khớp với mốc tham chiếu theo độ mịn dữ liệu công tơ tổng</title>",
        '<rect width="960" height="360" fill="#f5f5f5"/>',
    ]

    def text(x, y, s, size=12, fill="#2d3142", anchor="middle"):
        parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}">{s}</text>'
        )

    text(24, 32, "Công tơ tổng để lộ nếp sinh hoạt đến đâu (REFIT)", 18, anchor="start")
    text(24, 52, "Mức khớp với mốc suy từ mẫu ~8 giây. Không phải sự thật.", 11, "#4f5d75", "start")
    for c, res in enumerate(RESOLUTIONS):
        x = 170 + c * 260
        text(x + 122, 84, RESOLUTIONS[res], 13)
        for h, house in enumerate(houses):
            text(x + 30 + h * 62, 104, f"Nhà {house}", 10, "#4f5d75")
        for r, item in enumerate(NAMES):
            y = 116 + r * 64
            if c == 0:
                text(24, y + 31, NAMES[item], anchor="start")
            cell = table[(table["resolution"] == res) & (table["item"] == item)]
            if (cell["level"] == "không có giờ").all():
                parts.append(
                    f'<rect x="{x}" y="{y}" width="244" height="52" rx="6" fill="none" '
                    'stroke="#5a6580" stroke-dasharray="4 4"/>'
                )
                text(x + 122, y + 31, "Không có giờ trong ngày", fill="#4f5d75")
                continue
            for h, house in enumerate(houses):
                value = cell.loc[cell["house"] == house, "level"].item()
                fill = fills.get(value, "#f5f5f5")
                parts.append(
                    f'<rect x="{x + h * 62}" y="{y}" width="58" height="52" rx="6" '
                    f'fill="{fill}" stroke="#5a6580"/>'
                )
                ink = "#ffffff" if value in ("cao", "vừa") else "#2d3142"
                label = value if value in fills else "ít ngày"
                text(x + 29 + h * 62, y + 31, label, 12, ink)
    text(
        24, 330, "Giờ: lệch không quá 30 phút. Ngày vắng: trùng trên tổng ngày", 11, anchor="start"
    )
    text(
        24, 346, "mà một trong hai bên đánh dấu. Số đếm: granularity-risk.csv.", 11, anchor="start"
    )
    return "\n".join([*parts, "</svg>", ""])


def self_check() -> None:
    # 8 identical days: 100 W idle, two 2 kW kettle runs after 06:30 and two before 23:00.
    unix = np.arange(0, 8 * 86400, 10)
    sec = unix % 86400
    on = np.zeros(len(unix), bool)
    for hhmm in (6 * 60 + 30, 6 * 60 + 36, 22 * 60 + 50, 22 * 60 + 56):
        on |= (sec >= hhmm * 60) & (sec < (hhmm + 4) * 60)
    ts = pd.Timestamp("2014-01-06") + pd.to_timedelta(unix, unit="s")
    raw = pd.DataFrame({"ts": ts, "unix": unix, "watts": np.where(on, 2100.0, 100.0)})
    got = {(r["resolution"], r["item"]): r for r in analyse(raw)}
    for item in ("wake", "bed"):
        assert got["minute", item]["level"] == "cao", got["minute", item]
        assert got["day", item]["level"] == "không có giờ"
    assert got["minute", "away"]["reference_days"] == 0
    assert [level(7, 10), level(4, 10), level(3, 10), level(4, 4)] == [
        "cao",
        "vừa",
        "thấp",
        "quá ít ngày",
    ]


def main() -> None:
    self_check()
    rows = []
    for house in HOUSES:
        raw = load(ROOT / f"dataset/CLEAN_House{house}.csv")
        rows += [{"house": house, **r} for r in analyse(raw)]
    table = pd.DataFrame(rows)
    counts = ["reference_days", "estimate_days", "agree", "out_of"]
    table[counts] = table[counts].astype("Int64")
    OUT.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT / "granularity-risk.csv", index=False)
    (OUT / "granularity-risk.svg").write_text(chart(table))
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
