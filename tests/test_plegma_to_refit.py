import pandas as pd

from scripts.plegma_to_refit import LABELS, to_refit


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2022-07-15", periods=3, freq="10s"),
            "V": 230.0,
            "A": 1.0,
            "P_agg": [100.0, 200.0, 300.0],
            "ac_1": [0.0, 50.0, None],
            "fridge": [80.0, 0.0, 80.0],
            "washing_machine": [None, None, None],
            "issues": [0, 1, 0],
        }
    )


def test_plegma_columns_become_refit_columns_in_label_order():
    out = to_refit(_frame())
    cols = ["Time", "Unix", "Aggregate", "Appliance1", "Appliance2", "Issues"]
    assert list(out.columns) == cols
    assert out["Aggregate"].tolist() == [100.0, 200.0, 300.0]
    assert out["Issues"].tolist() == [0, 1, 0]


def test_each_appliance_keeps_its_own_values_and_gaps_and_a_dead_plug_is_dropped():
    out = to_refit(_frame())
    assert out["Appliance1"].isna().tolist() == [False, False, True]  # ac_1
    assert out["Appliance2"].tolist() == [80.0, 0.0, 80.0]  # fridge


def test_labels_name_the_channels_the_trainer_reads():
    want = {"AC": "Appliance1", "Fridge": "Appliance2"}
    assert LABELS(_frame()) == want


def test_unix_reads_the_local_clock_as_utc_like_refit():
    out = to_refit(_frame())
    assert out["Unix"].iloc[0] == int(pd.Timestamp("2022-07-15 00:00:00", tz="UTC").timestamp())


def test_every_air_conditioner_adds_up_to_one_ac_and_a_gap_in_one_is_a_gap():
    df = _frame().assign(ac_2=[10.0, 20.0, 30.0])
    out = to_refit(df)
    assert out["Appliance1"].isna().tolist() == [False, False, True]
    assert out["Appliance1"].tolist()[:2] == [10.0, 70.0]
    assert LABELS(df) == {"AC": "Appliance1", "Fridge": "Appliance2"}
