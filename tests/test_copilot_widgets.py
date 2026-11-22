import pytest
from pydantic import ValidationError

from app.modules.copilot.schemas import WIDGET
from app.modules.copilot.services.tools import chart_widget

# One widget of each kind, in the JSON shape the web's WidgetSchema reads (as stored answers).
SAMPLES = [
    {"kind": "devices", "slices": [{"id": "d1", "label": "Fridge", "value": 1.2}]},
    {
        "kind": "compare",
        "period": "week",
        "data": [{"key": "2026-11-20", "current": 9.5, "previous": 8.0}],
    },
    {"kind": "forecast", "used": 120.5, "limit": 150.0, "kwh": 210.0, "vnd": 630000.0},
    {"kind": "forecast", "used": 420.5, "limit": None, "kwh": 480.0, "vnd": 1630000.0},
    {"kind": "weather", "temp": 31, "feels": 35, "humidity": 70},
    {
        "kind": "plan",
        "id": "p1",
        "tasks": [{"label": "AC at 26", "detail": "..."}],
        "kwh": 12.0,
        "vnd": None,
        "status": "proposed",
    },
    {"kind": "peers", "you": 9.1, "median": 7.4, "days": 30, "homes": 12},
    {"kind": "standby", "watts": [80, 82], "kwh": 59.0, "vnd": 180000},
    {"kind": "links", "links": [{"key": "bill", "href": "/dashboard/bill"}]},
    {
        "kind": "watch",
        "id": "w1",
        "label": "Tiền điện kỳ này",
        "op": "gt",
        "threshold": 1000000.0,
        "unit": "vnd",
        "value": 640000.0,
        "ends_at": "2026-11-30T17:00:00Z",
    },
]


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s["kind"])
def test_every_kind_round_trips(sample):
    assert WIDGET.validate_python(sample).model_dump(mode="json") == sample


def test_rejects_bad_widget():
    with pytest.raises(ValidationError):
        WIDGET.validate_python({"kind": "forecast", "used": "x"})
    with pytest.raises(ValidationError):
        WIDGET.validate_python({"kind": "alert_card"})


# The data step of a real text2sql stream ("Điện năng tiêu thụ mỗi ngày trong 7 ngày qua"), trimmed.
STEP = {
    "tool": "query_metric",
    "result_id": "r1",
    "sql": "select ...",
    "error": None,
    "display": "chart_if_last",
    "chart": {
        "version": 1,
        "type": "line",
        "encoding": {
            "x": {"field": "bucket", "label": "Thời điểm bắt đầu bucket", "time_unit": "day"},
            "y": [{"field": "total_kwh", "label": "Tổng điện năng cả nhà", "aggregate": "none"}],
        },
    },
    "columns": ["bucket", "total_kwh"],
    "rows": [["2026-11-13T00:00:00+07:00", 9.74], ["2026-11-14T00:00:00+07:00", 15.51]],
}


def step(**over):
    return {**STEP, **over}


def chart(type_="line", **encoding):
    return {**STEP["chart"], "type": type_, "encoding": {**STEP["chart"]["encoding"], **encoding}}


def test_line_from_real_step():
    w = chart_widget([STEP])
    assert w.type == "line"
    assert w.labels == ["2026-11-13T00:00:00+07:00", "2026-11-14T00:00:00+07:00"]
    assert [(s.label, s.values) for s in w.series] == [("Tổng điện năng cả nhà", [9.74, 15.51])]
    assert (w.columns, w.rows) == (STEP["columns"], STEP["rows"])


def test_agent_chart_wins():
    agent = {
        "tool": "make_chart",
        "result_id": "r1",
        "chart": chart("bar"),
        "columns": [],
        "rows": [],
    }
    other = {**agent, "result_id": "r2", "chart": chart("donut")}
    assert chart_widget([STEP, agent, other]).type == "bar"


@pytest.mark.parametrize(
    "s",
    [
        step(chart=None),
        step(display="none"),
        step(chart=chart("sankey")),
        step(chart=chart(series={"field": "bucket"})),
        step(chart={**chart(), "transform": {"top_n": {"n": 5}}}),
        step(chart=chart(y=[{"field": "total_kwh", "aggregate": "sum"}])),
        step(chart=chart(y=[{"field": "missing"}])),
        step(rows=[["a", 1], ["a", 2]]),
    ],
    ids=[
        "no-chart",
        "display-none",
        "sankey",
        "series",
        "transform",
        "sum",
        "no-field",
        "repeat-x",
    ],
)
def test_table_when_not_drawable_as_is(s):
    w = chart_widget([s])
    assert (w.type, w.series, w.rows) == ("table", [], s["rows"])


@pytest.mark.parametrize(
    ("given", "drawn"),
    [("pie", "donut"), ("donut", "donut"), ("area_stacked", "area"), ("bar_horizontal", "bar")]
    + [("lollipop", "bar"), ("kpi", "kpi")],
)
def test_type_mapping(given, drawn):
    assert chart_widget([step(chart=chart(given))]).type == drawn


def test_non_finite_becomes_null():
    w = chart_widget([step(rows=[["a", "abc"], ["b", float("nan")], ["c", 3]])])
    assert w.series[0].values == [None, None, 3.0]
    assert w.rows == [["a", "abc"], ["b", None], ["c", 3]]


def test_caps_200():
    w = chart_widget([step(rows=[[f"d{i}", i] for i in range(250)])])
    assert (len(w.labels), len(w.rows)) == (200, 200)


@pytest.mark.parametrize(
    "steps",
    [[], [step(error="boom")], [step(rows=[])], [step(sql=None)]],
    ids=["none", "error", "empty", "no-sql"],
)
def test_no_widget_without_data(steps):
    assert chart_widget(steps) is None


@pytest.mark.parametrize(
    ("rows", "kept"),
    [
        ([["a", [1, 2]], ["b", 3]], [["a", "[1, 2]"], ["b", 3]]),
        ([["a", {"k": 1}], ["b", 3]], [["a", '{"k": 1}'], ["b", 3]]),
        ([["a"], ["b", 3]], [["a", None], ["b", 3]]),
    ],
    ids=["array", "json", "short-row"],
)
def test_odd_cells_never_break_the_tool(rows, kept):
    w = chart_widget([step(rows=rows)])
    assert w.rows == kept
    assert w.series[0].values == [None, 3.0]


def test_null_x_and_booleans_read_plainly():
    w = chart_widget([step(rows=[[None, 1], ["2026-11-14T00:00:00+07:00", 2]])])
    assert w.labels[0] == ""
    t = chart_widget([step(chart=None, columns=["on", "n"], rows=[[True, 1], [False, 2]])])
    assert t.rows == [["true", 1], ["false", 2]]


def test_infinity_in_a_table_cell_is_null():
    w = chart_widget([step(chart=None, rows=[["a", float("inf")], ["b", 2]])])
    assert w.rows == [["a", None], ["b", 2]]
