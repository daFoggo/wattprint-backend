from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

# Widgets under an answer, built by the tools from their results (never by the model). The web's
# features/copilot/schemas.ts WidgetSchema reads the same shapes and drops a widget it cannot read.


class Slice(BaseModel):
    id: str
    label: str
    value: float


class DevicesWidget(BaseModel):
    kind: Literal["devices"] = "devices"
    slices: list[Slice]


class CompareDay(BaseModel):
    key: str  # the current period's day, yyyy-mm-dd
    current: float
    previous: float


class CompareWidget(BaseModel):
    kind: Literal["compare"] = "compare"
    period: Literal["week", "cycle"]
    data: list[CompareDay]


class ForecastWidget(BaseModel):
    kind: Literal["forecast"] = "forecast"
    used: float
    limit: float | None  # the next tier's start; None in the last tier
    kwh: float
    vnd: float


class WeatherWidget(BaseModel):
    kind: Literal["weather"] = "weather"
    temp: float
    feels: float
    humidity: float


class PlanAction(BaseModel):
    """One of the plan page's actions: `id` is `<device_id>.<key>`, its `?add=` value."""

    id: str
    key: str
    device: str
    params: dict[str, float]
    kwh: float
    vnd: float


class PlanWidget(BaseModel):
    kind: Literal["plan"] = "plan"
    actions: list[PlanAction]
    kwh: float
    vnd: float  # each action's saving summed; the plan page prices them together


class PeersWidget(BaseModel):
    kind: Literal["peers"] = "peers"
    you: float
    median: float
    days: int
    homes: int


class StandbyWidget(BaseModel):
    kind: Literal["standby"] = "standby"
    watts: list[float]
    kwh: float
    vnd: float | None


class Link(BaseModel):
    key: Literal["devices", "bill", "statistics", "settings"]
    href: str


class LinksWidget(BaseModel):
    kind: Literal["links"] = "links"
    links: list[Link]


class ChartSeries(BaseModel):
    label: str
    unit: str | None
    values: list[float | None]


class ChartWidget(BaseModel):
    """A text2sql result as a chart the web draws, or a table when it cannot be drawn as is."""

    kind: Literal["chart"] = "chart"
    type: Literal["line", "area", "bar", "donut", "kpi", "table"]
    title: str | None
    labels: list[str]
    series: list[ChartSeries]
    columns: list[str]
    rows: list[list[str | float | None]]


class WatchWidget(BaseModel):
    """An alert Wappi just saved; the web links it to its row on the alerts page."""

    kind: Literal["watch"] = "watch"
    id: str
    label: str
    op: Literal["gt", "lt"]
    threshold: float
    unit: str
    value: float | None
    ends_at: datetime


Widget = Annotated[
    DevicesWidget
    | CompareWidget
    | ForecastWidget
    | WeatherWidget
    | PlanWidget
    | PeersWidget
    | StandbyWidget
    | LinksWidget
    | ChartWidget
    | WatchWidget,
    Field(discriminator="kind"),
]
WIDGET: TypeAdapter[Widget] = TypeAdapter(Widget)
