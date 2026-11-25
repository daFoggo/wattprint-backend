async def test_owner_reads_and_changes_the_home(client, make_member):
    owner = await make_member("owner", name="Nhà A", billing_cycle_day=5)
    r = await client.get("/api/v1/homes/current", headers=owner.headers)
    assert r.status_code == 200
    assert r.json() | {"id": None} == {
        "id": None,
        "name": "Nhà A",
        "home_type": None,
        "floor_area_m2": None,
        "occupants": None,
        "billing_cycle_day": 5,
        "province_code": None,
        "role": "owner",
    }

    patch = {
        "name": "Nhà B",
        "home_type": "apartment",
        "floor_area_m2": "72.5",
        "occupants": 3,
        "billing_cycle_day": 12,
        "province_code": "79",
    }
    r = await client.patch("/api/v1/homes/current", json=patch, headers=owner.headers)
    assert r.status_code == 200, r.text
    assert {k: r.json()[k] for k in patch} == patch | {"floor_area_m2": "72.50"}

    # null clears an optional field and is ignored on a required one
    r = await client.patch(
        "/api/v1/homes/current", json={"occupants": None, "name": None}, headers=owner.headers
    )
    assert r.json()["occupants"] is None and r.json()["name"] == "Nhà B"


async def test_member_cannot_change_the_home(client, make_member):
    owner = await make_member("owner")
    member = await make_member("member", home_id=owner.home_id)
    assert (await client.get("/api/v1/homes/current", headers=member.headers)).json()["role"] == (
        "member"
    )
    r = await client.patch("/api/v1/homes/current", json={"name": "x"}, headers=member.headers)
    assert r.status_code == 403 and r.json()["code"] == "home_owner_required"


async def test_invalid_changes_are_rejected(client, make_member):
    owner = await make_member("owner")
    for body in (
        {"billing_cycle_day": 29},
        {"occupants": 0},
        {"home_type": "castle"},
        {"floor_area_m2": -1},
        {"name": ""},
        {"timezone": "UTC"},  # not a field the API accepts
    ):
        r = await client.patch("/api/v1/homes/current", json=body, headers=owner.headers)
        assert r.status_code == 422, body
    r = await client.patch(
        "/api/v1/homes/current", json={"province_code": "XX"}, headers=owner.headers
    )
    assert r.status_code == 422 and r.json()["code"] == "unknown_province"


async def test_provinces_are_the_34_units(client, make_member):
    owner = await make_member("owner")
    r = await client.get("/api/v1/homes/provinces", headers=owner.headers)
    assert r.status_code == 200 and len(r.json()) == 34
    assert {"code": "01", "name": "Hà Nội"} in r.json()


async def test_no_home_is_404(client, make_token):
    r = await client.get(
        "/api/v1/homes/current", headers={"Authorization": f"Bearer {make_token()}"}
    )
    assert r.status_code == 404 and r.json()["code"] == "home_not_found"


async def test_preferences_default_then_saved_per_user(client, make_member):
    a = await make_member("owner")
    b = await make_member("member", home_id=a.home_id)
    defaults = {
        "notify_anomaly": True,
        "notify_tier": True,
        "weekly_summary": False,
    }
    assert (await client.get("/api/v1/users/me/preferences", headers=a.headers)).json() == defaults
    r = await client.patch(
        "/api/v1/users/me/preferences", json={"weekly_summary": True}, headers=a.headers
    )
    assert r.json() == defaults | {"weekly_summary": True}
    r = await client.patch(
        "/api/v1/users/me/preferences", json={"notify_tier": False}, headers=a.headers
    )
    assert r.json() == defaults | {"weekly_summary": True, "notify_tier": False}
    # another member of the same home keeps their own
    assert (await client.get("/api/v1/users/me/preferences", headers=b.headers)).json() == defaults
    r = await client.patch(
        "/api/v1/users/me/preferences", json={"notify_tier": "maybe"}, headers=a.headers
    )
    assert r.status_code == 422


async def test_changing_the_cycle_day_drops_the_device_forecast_cache(client, make_member):
    import sys
    from datetime import date

    df = sys.modules["app.modules.billing.services.device_forecast"]
    owner = await make_member("owner", billing_cycle_day=5)
    df._CACHE[owner.home_id] = ("sentinel", None)
    later = min(date.today().day + 1, 28)  # a day after today: the cycle start moves back a month
    r = await client.patch(
        "/api/v1/homes/current", json={"billing_cycle_day": later}, headers=owner.headers
    )
    assert r.status_code == 200, r.text
    assert owner.home_id not in df._CACHE


async def test_changing_only_the_name_keeps_the_device_forecast_cache(client, make_member):
    import sys

    df = sys.modules["app.modules.billing.services.device_forecast"]
    owner = await make_member("owner", billing_cycle_day=5)
    df._CACHE[owner.home_id] = ("sentinel", None)
    r = await client.patch("/api/v1/homes/current", json={"name": "X"}, headers=owner.headers)
    assert r.status_code == 200 and df._CACHE.pop(owner.home_id) == ("sentinel", None)
