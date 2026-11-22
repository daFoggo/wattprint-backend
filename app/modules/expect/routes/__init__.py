from datetime import datetime, timedelta
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Query
from fastapi.exceptions import RequestValidationError

from app.dependencies import DbSession
from app.modules.energy.api import CurrentHome

from ..schemas import ExpectedHour
from ..services import expected, hourly_actual

router = APIRouter(prefix="/expected", tags=["expected"])
MAX_SPAN = timedelta(days=8)


@router.get("", summary="Expected kWh per hour (P10–P90, P50 the usual) and the measured kWh")
async def hours(
    home_id: CurrentHome,
    db: DbSession,
    since: Annotated[datetime, Query(alias="from")],
    until: Annotated[datetime, Query(alias="to")],
) -> list[ExpectedHour]:
    if not timedelta(0) <= until - since <= MAX_SPAN:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("query", "to"),
                    "msg": "at most 8 days after from",
                    "input": until.isoformat(),
                }
            ]
        )
    frame = await expected(db, home_id, since, until)
    if frame.empty:
        return []
    actual = await hourly_actual(db, home_id, frame.index[0].to_pydatetime(), until)
    return [
        ExpectedHour(
            ts=ts.to_pydatetime(),
            p10=r.p10,
            p50=r.p50,
            p90=r.p90,
            kwh=None if pd.isna(actual.get(ts)) else float(actual[ts]),
        )
        for ts, r in frame.iterrows()
    ]
