"""Static data of the Copilot: measures, views, the tables each node may read, the guard lists."""

# measure -> (column, aggregation, divide by, unit). Cycle measures read copilot_ro.device_cycle.
MEASURES: dict[str, tuple[str, str, int | None, str]] = {
    "energy": ("energy_wh", "SUM", 1000, "kWh"),
    "average_power": ("avg_w", "AVG", None, "W"),
    "peak_power": ("max_w", "MAX", None, "W"),
    "cycles": ("*", "COUNT", None, "cycles"),
    "cycle_energy": ("energy_wh", "SUM", 1000, "kWh"),
}
CYCLE_MEASURES = {"cycles", "cycle_energy"}

# The read set of each node that runs built or compiled SQL ("Which tables each node may touch").
ALLOWED_TABLES: dict[str, set[str]] = {
    "execute": {
        *(f"copilot_ro.{f}_{r}"
          for f in ("reading", "device_estimate") for r in ("1m", "1h", "1d")),
        "copilot_ro.device",
        "copilot_ro.device_cycle",
    },
    "evaluate_rules": {"copilot_ro.motif_instance", "copilot_ro.device"},
}

# Functions generated SQL may call (sqlglot names, upper case).
FUNCTIONS = {
    "SUM", "AVG", "MIN", "MAX", "COUNT", "ROUND", "DATE_TRUNC", "TIMESTAMP_TRUNC", "EXTRACT",
    "CAST", "CASE", "COALESCE", "ARRAY_AGG", "LOGICAL_AND", "JSON_EXTRACT_SCALAR", "IF",
}

MAX_ROWS = 1000
PLUG_COVERS = 0.95  # a plug "covers" a period when it has data for 95% of its minutes

# Dropped from both sides of a word match; the same list is inside copilot_ro.match_key.
QUESTION_SYLLABLES = (
    "dien", "dung", "ton", "bao", "nhieu", "hom", "qua", "khong", "cai", "kwh", "do", "nay", "kia",
    "nao", "the",
)


def view_for(source: str, grain: str, group_by: str) -> str:
    """The one copilot_ro aggregate view a (source, grain, grouping) reads."""
    family = "device_estimate" if source == "estimated" else "reading"
    res = "1h" if grain == "hour" or group_by == "hour_of_day" else "1d"
    return f"copilot_ro.{family}_{res}"


def kind_for(source: str, target: str, group_by: str) -> str:
    """The energy.series kind: the main meter, the plugs or the NILM estimates."""
    if source == "estimated":
        return "device"
    return "main" if target == "whole_home" and group_by != "device" else "plug"
