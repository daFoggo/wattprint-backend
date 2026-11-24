import uuid
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.modules.nilm.services import runner, windows
from app.modules.ops.api import DemoScenario

T0 = pd.Timestamp("2026-11-21 11:00", tz="UTC")  # 18:00 in Hanoi, a heating hour


def heater(start, end=None, **params):
    return DemoScenario(name="heater", starts_at=start, ends_at=end, params=params, train=True)


def test_heater_watts_follow_the_hour_temperature_and_window():
    index = pd.date_range(T0, periods=4, freq="30min")  # 18:00, 18:30, 19:00, 19:30 local
    temps = pd.Series({T0: 6.0, T0 + pd.Timedelta(hours=1): 16.0})
    sc = heater(T0, T0 + pd.Timedelta(minutes=90))
    got = runner.heater_watts(index, [sc], temps, "Asia/Ho_Chi_Minh")
    # 19:00 is at the setpoint (no heat); the window ends at 19:30
    assert got.tolist() == [pytest.approx(1800), pytest.approx(1800), 0.0, 0.0]


def test_the_heater_comes_out_of_other_never_more_than_other(monkeypatch):
    index = pd.date_range(T0, periods=3, freq="15s")
    s = pd.Series([3000.0, 1000.0, 3000.0], index=index)
    apps = np.array([[500.0, 500.0, 500.0]])  # one appliance; Other = 2500, 500, 2500
    monkeypatch.setattr(windows, "model_inputs", lambda *a: None)
    monkeypatch.setattr(windows, "merge", lambda *a: apps)
    bundle = SimpleNamespace(window=4, labels=["Kettle"], predict=lambda x: None)
    plan = SimpleNamespace(series=s, starts=[0], write_from=0)
    ids = {"Kettle": uuid.uuid4(), "Other": uuid.uuid4(), "Heater": uuid.uuid4()}
    rows = runner.compute(bundle, plan, "Asia/Ho_Chi_Minh", ids, np.array([1800.0, 1800.0, 0.0]))
    by = {k: [v for _, sid, v in rows if sid == i] for k, i in ids.items()}
    assert by["Heater"] == [1800.0, 500.0, 0.0]
    assert by["Other"] == [700.0, 0.0, 2500.0]
    total = np.sum([by[k] for k in ids], axis=0)
    assert total.tolist() == s.tolist()  # the devices still add up to the meter
