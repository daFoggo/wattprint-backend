from datetime import date

from sqlalchemy import text

from app.database import SessionLocal


async def test_history_lists_ended_cycles_of_this_home_only(client, make_member):
    me = await make_member("owner", tariff_plan_code="vn_residential")
    other = await make_member("owner", tariff_plan_code="vn_residential")
    async with SessionLocal() as s, s.begin():
        version = await s.scalar(text("SELECT id FROM public.tb_tariff_version LIMIT 1"))
        for home, start, end, kwh in (
            (me.home_id, "2026-09-01", "2026-09-30", 210.5),
            (me.home_id, "2026-10-01", "2026-10-31", 190),
            (me.home_id, "2099-01-01", "2099-01-31", 5),  # not ended
            (other.home_id, "2026-09-01", "2026-09-30", 999),
        ):
            await s.execute(
                text(
                    "INSERT INTO public.tb_bill (home_id, period_start, period_end, version_id, "
                    "kwh_total, amount_before_vat, vat_amount, amount_total, coverage, status) "
                    "VALUES (:h, :a, :b, :v, :k, 1000, 80, 1080, 0.5, 'partial')"
                ),
                {
                    "h": home,
                    "a": date.fromisoformat(start),
                    "b": date.fromisoformat(end),
                    "v": version,
                    "k": kwh,
                },
            )
    r = await client.get("/api/v1/billing/history", headers=me.headers)
    assert r.status_code == 200
    assert [(b["period_start"], b["kwh"], b["coverage"]) for b in r.json()] == [
        ("2026-09-01", 210.5, 0.5),
        ("2026-10-01", 190.0, 0.5),
    ]
