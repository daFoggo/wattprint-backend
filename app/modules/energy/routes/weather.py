from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.dependencies import DbSession
from app.modules.home.api import Home, Province

from .. import services
from ..dependencies import CurrentHome
from ..schemas import Weather
from ..utils import HomeLocationUnsetError

router = APIRouter()


@router.get("/weather", summary="Weather now and the next 24 hours at the home's province")
async def weather(
    home_id: CurrentHome, db: DbSession, lang: Annotated[Literal["vi", "en"], Query()] = "vi"
) -> Weather:
    home = await db.get(Home, home_id)
    province = await db.get(Province, home.province_code) if home.province_code else None
    if province is None:
        raise HomeLocationUnsetError
    w = await services.weather_at(province.lat, province.lon, lang)
    return Weather.model_validate({"province": province.name, "now": w.now, "next": w.next})
