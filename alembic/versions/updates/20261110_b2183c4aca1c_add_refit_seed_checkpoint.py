"""add REFIT House 2 seed data

Revision ID: b2183c4aca1c
Revises: c8d3f1a6b204
"""

revision = "b2183c4aca1c"
down_revision = "c8d3f1a6b204"
branch_labels = None
depends_on = None


import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import ClassVar, Literal
from uuid import UUID

import pandas as pd
import sqlalchemy as sa
from pydantic import BaseModel, Field

from alembic import context, op

HOUSE       = 2
OWNER_EMAIL = "admin@gmail.com"
HOME_NAME   = f"REFIT House {HOUSE}"
METER       = f"REFIT-H{HOUSE}"
SOURCE      = f"refit/CLEAN_House{HOUSE}.csv"
DIVIDE_DAY  = pd.Timestamp("2015-01-24 19:59:51", tz="UTC")  # NILM test_start, see train.ipynb
BATCH_ROWS  = 20_000                                          # CSV rows per INSERT, 10 readings each

# CSV channel -> (device name, cat_device_type.code), from REFIT metadata of House 2
APPLIANCES = {
    "Appliance1": ("Fridge-Freezer",  "fridge_freezer"),
    "Appliance2": ("Washing Machine", "washing_machine"),
    "Appliance3": ("Dishwasher",      "dishwasher"),
    "Appliance4": ("Television Site", "television"),
    "Appliance5": ("Microwave",       "microwave"),
    "Appliance6": ("Toaster",         "toaster"),
    "Appliance7": ("Hi-Fi",           "hifi"),
    "Appliance8": ("Kettle",          "kettle"),
    "Appliance9": ("Overhead Fan",    "other"),
}
CHANNELS = ("Aggregate", *APPLIANCES)

HomeType     = Literal["apartment", "house", "other"]
MemberRole   = Literal["owner", "member"]
MeterStatus  = Literal["new", "active", "retired"]
DeviceOrigin = Literal["nilm", "plug", "manual"]
SeriesKind   = Literal["main", "plug", "device"]


class User(BaseModel):
    table: ClassVar[str]     = "public.tb_users"
    key:   ClassVar[tuple]   = ("email",)

    id:           UUID | None = None
    email:        str        = Field(max_length=320)
    full_name:    str | None = Field(default=None, max_length=255)
    keycloak_sub: str | None = Field(default=None, max_length=255)
    is_active:    bool       = True


class Home(BaseModel):
    table: ClassVar[str]               = "public.tb_home"
    key:   ClassVar[tuple]             = ("name",)

    id:                UUID | None      = None
    name:              str             = Field(max_length=255)
    postal_code:       str | None      = Field(default=None, max_length=16)
    province_code:     str | None      = Field(default=None, max_length=16)
    home_type:         HomeType | None = None
    floor_area_m2:     Decimal | None  = Field(default=None, max_digits=8, decimal_places=2)
    year_built:        int | None      = None
    occupants:         int | None      = None
    timezone:          str             = "Asia/Ho_Chi_Minh"
    tariff_plan_code:  str | None      = Field(default=None, max_length=64)  # -> tb_tariff_plan.code
    billing_cycle_day: int             = Field(default=1, ge=1, le=28)


class HomeMember(BaseModel):
    table: ClassVar[str] = "public.tb_home_member"
    key:   ClassVar[tuple] = ("user_id",)

    home_id: UUID                     # -> tb_home.id
    user_id: UUID                     # -> tb_users.id (unique)
    role:    MemberRole  = "member"


class Meter(BaseModel):
    table: ClassVar[str]          = "public.tb_meter"
    key:   ClassVar[tuple]        = ("serial",)

    id:           UUID | None      = None
    serial:       str             = Field(max_length=64)  # unique
    home_id:      UUID | None      = None                  # -> tb_home.id
    firmware:     str | None      = Field(default=None, max_length=64)
    last_seen_at: datetime | None = None
    status:       MeterStatus     = "new"


class Device(BaseModel):
    table: ClassVar[str]           = "public.tb_device"
    key:   ClassVar[tuple]         = ("home_id", "name")

    id:               UUID | None   = None
    home_id:          UUID                                  # -> tb_home.id
    device_type_code: str          = Field(max_length=64)  # -> cat_device_type.code
    name:             str          = Field(max_length=255)
    room:             str | None   = Field(default=None, max_length=128)
    origin:           DeviceOrigin
    show_on_timeline: bool         = True


class Series(BaseModel):
    table: ClassVar[str]       = "public.tb_series"
    key:   ClassVar[tuple]     = ("home_id", "kind", "device_id", "metric")

    series_id:      UUID | None = None
    home_id:        UUID                                                   # -> tb_home.id
    kind:           SeriesKind
    device_id:      UUID | None = None                                     # -> tb_device.id (NULL for main)
    meter_id:       UUID | None = None                                     # -> tb_meter.id
    source_channel: str | None = None                                     # Aggregate, Appliance1..9
    metric:         str        = Field(default="power_w", max_length=64)  # -> cat_metric.event_type
    unit:           str        = "W"


class Reading(BaseModel):
    table: ClassVar[str] = "public.tb_reading"
    key:   ClassVar[tuple] = ("series_id", "ts")

    ts:        datetime
    series_id: UUID                   # -> tb_series.series_id
    value:     float
    quality:   int        = 0        # 1 = CSV Issues flag


def upsert(conn: sa.Connection, row: BaseModel, returning: str | None = "id") -> UUID | None:
    values = row.model_dump(exclude_none=True)
    keys   = {k: getattr(row, k) for k in row.key}
    where  = " AND ".join(f"{k} IS NOT DISTINCT FROM :{k}" for k in keys)
    sets   = ", ".join(f"{k} = :{k}" for k in values if k not in keys)
    ret    = f" RETURNING {returning}" if returning else ""

    if conn.execute(sa.text(f"SELECT 1 FROM {row.table} WHERE {where}"), keys).first() is None:
        sql = f"INSERT INTO {row.table} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)}){ret}"
    elif sets:
        sql = f"UPDATE {row.table} SET {sets} WHERE {where}{ret}"
    elif returning:
        sql = f"SELECT {returning} FROM {row.table} WHERE {where}"
    else:
        return None
    result = conn.execute(sa.text(sql), {**values, **keys})
    return result.scalar_one() if returning else None

WATERMARK_DDL = (
    "CREATE SCHEMA IF NOT EXISTS etl",
    """
    CREATE TABLE IF NOT EXISTS etl.tb_watermark (
        source      text        NOT NULL,
        segment     text        NOT NULL,
        shift_days  integer     NOT NULL,
        range_from  timestamptz NOT NULL,
        range_to    timestamptz NOT NULL,
        last_ts     timestamptz,
        rows_loaded bigint      NOT NULL DEFAULT 0,
        status      text        NOT NULL DEFAULT 'pending',
        error       text,
        updated_at  timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_watermark PRIMARY KEY (source, segment),
        CONSTRAINT ck_watermark_status CHECK (status IN ('pending', 'running', 'done', 'failed'))
    )
    """,
    "COMMENT ON TABLE etl.tb_watermark IS 'Resumable bulk loads, one row per source segment. "
    "range_from/range_to bound the segment in database time (source time + shift_days); "
    "last_ts is the newest reading ts committed so far.'",
)

# One statement, so the readings and the watermark commit together.
LOAD_BATCH = sa.text("""
    WITH ins AS (
        INSERT INTO public.tb_reading (ts, series_id, value, quality)
        SELECT * FROM unnest(CAST(:ts AS timestamptz[]), CAST(:series_id AS uuid[]),
                             CAST(:value AS real[]), CAST(:quality AS smallint[]))
        ON CONFLICT (series_id, ts) DO NOTHING
        RETURNING 1
    )
    UPDATE etl.tb_watermark
    SET last_ts     = :last_ts,
        rows_loaded = rows_loaded + (SELECT count(*) FROM ins),
        status      = 'running',
        error       = NULL,
        updated_at  = now()
    WHERE source = :source AND segment = :segment
""")


def seed_parents(conn: sa.Connection) -> dict[str, UUID]:
    """User, home, meter, devices and series of the house; returns series_id per CSV channel."""
    user = User(email=OWNER_EMAIL, full_name=HOME_NAME)
    user.id = upsert(conn, user)

    home = Home(name=HOME_NAME, home_type="house", occupants=4, tariff_plan_code="vn_residential")
    home.id = upsert(conn, home)

    upsert(conn, HomeMember(home_id=home.id, user_id=user.id, role="owner"), returning=None)

    meter = Meter(serial=METER, home_id=home.id, status="active")
    meter.id = upsert(conn, meter)

    series_ids = {"Aggregate": upsert(conn, Series(
        home_id=home.id, kind="main", meter_id=meter.id, source_channel="Aggregate",
    ), returning="series_id")}
    for channel, (name, type_code) in APPLIANCES.items():
        device = Device(home_id=home.id, device_type_code=type_code, name=name, origin="plug")
        device.id = upsert(conn, device)
        series_ids[channel] = upsert(conn, Series(
            home_id=home.id, kind="plug", device_id=device.id, meter_id=meter.id, source_channel=channel,
        ), returning="series_id")
    return series_ids


def plan_segments(conn: sa.Connection, filepath: Path) -> list[sa.Row]:
    """Upsert the test and train watermark rows; returns them in load order (test first).

    The shift moves the CSV to the present in whole weeks (weekday kept) so the retention policy
    of public.tb_reading keeps it; it is fixed on the first run and reused on every rerun.
    Readings older than the retention window are skipped, the policy would drop them anyway.
    """
    unix = pd.read_csv(filepath, usecols=["Unix"])["Unix"]
    first, last = (pd.Timestamp(unix.iloc[i], unit="s", tz="UTC") for i in (0, -1))

    shift_days = conn.scalar(sa.text("SELECT shift_days FROM etl.tb_watermark WHERE source = :s LIMIT 1"),
                             {"s": SOURCE})
    if shift_days is None:
        shift_days = (pd.Timestamp.now(tz="UTC") - last).days // 7 * 7
    shift = timedelta(days=shift_days)

    drop_after = conn.scalar(sa.text(
        "SELECT CAST(config->>'drop_after' AS interval) FROM timescaledb_information.jobs "
        "WHERE proc_name = 'policy_retention' AND hypertable_schema = 'public' "
        "AND hypertable_name = 'tb_reading' AND scheduled"
    ))
    floor = pd.Timestamp.now(tz="UTC") - drop_after + timedelta(days=1) if drop_after else first + shift

    segments = (
        ("test",  DIVIDE_DAY + shift,        last + shift + timedelta(seconds=1)),
        ("train", max(first + shift, floor), DIVIDE_DAY + shift),
    )
    for segment, range_from, range_to in segments:
        conn.execute(sa.text("""
            INSERT INTO etl.tb_watermark (source, segment, shift_days, range_from, range_to)
            VALUES (:source, :segment, :shift_days, :range_from, :range_to)
            ON CONFLICT (source, segment) DO UPDATE
            SET range_from = EXCLUDED.range_from, range_to = EXCLUDED.range_to, updated_at = now()
        """), {"source": SOURCE, "segment": segment, "shift_days": shift_days,
               "range_from": range_from.to_pydatetime(), "range_to": range_to.to_pydatetime()})
    return conn.execute(sa.text(
        "SELECT * FROM etl.tb_watermark WHERE source = :s ORDER BY segment = 'train'"
    ), {"s": SOURCE}).all()


def batch_params(chunk: pd.DataFrame, ts: pd.Series, series_ids: dict[str, UUID]) -> dict[str, list]:
    """Unnest arrays for one CSV chunk: one reading per (row, channel), NaN values dropped."""
    quality = (chunk["Issues"] == 1).astype("int16").to_numpy()
    params = {"ts": [], "series_id": [], "value": [], "quality": []}
    for channel in CHANNELS:
        ok = chunk[channel].notna().to_numpy()
        params["ts"]        += ts[ok].dt.to_pydatetime().tolist()
        params["series_id"] += [series_ids[channel]] * int(ok.sum())
        params["value"]     += chunk[channel][ok].tolist()
        params["quality"]   += quality[ok].tolist()
    return params


def load_segment(conn: sa.Connection, wm: sa.Row, filepath: Path, series_ids: dict[str, UUID]) -> None:
    """Stream the CSV and insert the rows of one segment after its watermark, BATCH_ROWS at a time."""
    if wm.status == "done":
        return
    shift = timedelta(days=wm.shift_days)
    lo, hi = pd.Timestamp(wm.range_from), pd.Timestamp(wm.range_to)
    if wm.last_ts is not None:
        lo = max(lo, pd.Timestamp(wm.last_ts) + timedelta(microseconds=1))

    chunks = pd.read_csv(filepath, usecols=["Unix", *CHANNELS, "Issues"], chunksize=BATCH_ROWS,
                         dtype={c: "float32" for c in CHANNELS})
    for chunk in chunks:
        ts = pd.to_datetime(chunk["Unix"], unit="s", utc=True) + shift
        if ts.iloc[-1] < lo:
            continue
        if ts.iloc[0] >= hi:
            break
        keep = ((ts >= lo) & (ts < hi)).to_numpy()
        if not keep.any():
            continue
        chunk, ts = chunk[keep], ts[keep]
        conn.execute(LOAD_BATCH, {**batch_params(chunk, ts, series_ids),
                                  "last_ts": ts.iloc[-1].to_pydatetime(),
                                  "source": SOURCE, "segment": wm.segment})

    conn.execute(sa.text(
        "UPDATE etl.tb_watermark SET status = 'done', updated_at = now() "
        "WHERE source = :source AND segment = :segment"
    ), {"source": SOURCE, "segment": wm.segment})


def upgrade() -> None:
    if os.environ.get("SEED_REFIT", "1") == "0":  # test databases migrate without seed data
        return
    if context.is_offline_mode():
        raise RuntimeError("REFIT seed reads a CSV and streams readings: run it online")

    filepath = Path(__file__).resolve().parents[1] / "data" / f"CLEAN_House{HOUSE}.csv"
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"REFIT dataset not found: {filepath}")

    conn = op.get_bind()
    for ddl in WATERMARK_DDL:
        op.execute(ddl)
    series_ids = seed_parents(conn)
    segments = plan_segments(conn, filepath)

    # Commit per batch, so a failed run keeps its progress and the rerun resumes from the watermark.
    with op.get_context().autocommit_block():
        for wm in segments:
            try:
                load_segment(conn, wm, filepath, series_ids)
            except Exception as exc:
                conn.execute(sa.text(
                    "UPDATE etl.tb_watermark SET status = 'failed', error = :error, updated_at = now() "
                    "WHERE source = :source AND segment = :segment"
                ), {"error": repr(exc)[:2000], "source": SOURCE, "segment": wm.segment})
                raise


def downgrade() -> None:
    conn = op.get_bind()
    home = {"name": HOME_NAME}
    conn.execute(sa.text(
        "DELETE FROM public.tb_reading WHERE series_id IN (SELECT s.series_id FROM public.tb_series s "
        "JOIN public.tb_home h ON h.id = s.home_id WHERE h.name = :name)"
    ), home)
    conn.execute(sa.text("DELETE FROM public.tb_meter WHERE serial = :serial"), {"serial": METER})
    conn.execute(sa.text("DELETE FROM public.tb_home WHERE name = :name"), home)  # cascades devices, series, member
    conn.execute(sa.text("DELETE FROM public.tb_users WHERE email = :email"), {"email": OWNER_EMAIL})
    op.execute("DROP TABLE IF EXISTS etl.tb_watermark")
    op.execute("DROP SCHEMA IF EXISTS etl")
