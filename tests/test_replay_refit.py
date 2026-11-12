import importlib.util
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

_path = (
    Path(__file__).resolve().parents[1] / "scripts" / "replay_refit.py"
)  # mounted in the api container
_spec = importlib.util.spec_from_file_location("replay_refit", _path)
replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay)

T = datetime(2015, 5, 1, tzinfo=UTC)
BASE = timedelta(days=4179)


def test_shift_for_moves_back_whole_weeks_only_when_needed():
    last = T
    assert replay.shift_for(T + BASE, BASE, last) == BASE  # already inside
    assert replay.shift_for(T + BASE + timedelta(seconds=1), BASE, last) == BASE + replay.WEEK
    assert replay.shift_for(T + BASE + timedelta(days=8), BASE, last) == BASE + 2 * replay.WEEK
    assert replay.shift_for(T, BASE, last) == BASE  # never less than the seed's shift


def test_rows_in_skips_nan_cells_and_flags_issues():
    cols = {c: [1.0, 2.0] for c in replay.CHANNELS}
    cols["Appliance3"] = [math.nan, 5.0]
    df = pd.DataFrame(
        {**cols, "Issues": [0, 1]}, index=pd.DatetimeIndex([T, T + timedelta(seconds=7)])
    )
    rows = replay.rows_in(
        df, T + BASE - timedelta(seconds=1), T + BASE + timedelta(seconds=7), BASE
    )
    assert len(rows) == 19  # 10 + 10 channels, one NaN dropped
    assert {r.quality for r in rows if r.ts == T + BASE + timedelta(seconds=7)} == {1}
    assert rows[0].ts == T + BASE and rows[0].channel == "Aggregate"
    assert (
        replay.rows_in(df, T + BASE + timedelta(seconds=7), T + BASE + timedelta(days=1), BASE)
        == []
    )
