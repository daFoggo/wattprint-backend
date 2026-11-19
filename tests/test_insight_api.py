from sqlalchemy import text

from app.database import SessionLocal


async def test_cohort_is_404_until_a_cohort_is_stored(client, make_member):
    me = await make_member("member", home_type="house")
    r = await client.get("/api/v1/insights/cohort", headers=me.headers)
    assert (r.status_code, r.json()["code"]) == (404, "cohort_too_small")

    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_cohort_stat VALUES "
                "('all', '2026-11-09', 100, 200, 300, 400, 12)"
            )
        )
    try:
        r = await client.get("/api/v1/insights/cohort", headers=me.headers)
        assert r.status_code == 200
        body = r.json()
        assert (body["cohort_key"], body["homes"], body["p10"], body["kwh"]) == (
            "all",
            12,
            72.0,
            None,  # 100 W over 30 days; this home has no readings
        )
    finally:
        async with SessionLocal() as s, s.begin():
            await s.execute(text("DELETE FROM public.tb_cohort_stat WHERE cohort_key = 'all'"))
