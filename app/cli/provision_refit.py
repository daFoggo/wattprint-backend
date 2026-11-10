"""Provision the rows a REFIT house needs before its CSV can be loaded (idempotent)."""

import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Device, Home, HomeMember, Meter, Series, User

METADATA: dict[str, dict] = json.loads(
    (Path(__file__).resolve().parents[1] / "seed" / "refit_metadata.json").read_text(
        encoding="utf-8"
    )
)

TARIFF_PLAN = "vn_residential"
CHANNELS = ("Aggregate", *[f"Appliance{k}" for k in range(1, 10)])

# First match wins, so the longer names come first (fridge-freezer before freezer before fridge).
_DEVICE_TYPE_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), code)
    for pattern, code in (
        (r"fridge[\s-]*freezer", "fridge_freezer"),
        (r"freezer", "freezer"),
        (r"fridge", "fridge"),
        (r"washer[\s-]*dryer", "washer_dryer"),
        (r"washing\s*machine", "washing_machine"),
        (r"tumble\s*dryer", "tumble_dryer"),
        (r"dishwasher", "dishwasher"),
        (r"television|\btv\b", "television"),
        (r"computer", "computer"),
        (r"heater", "electric_heater"),
        (r"microwave", "microwave"),
        (r"kettle", "kettle"),
        (r"toaster", "toaster"),
        (r"hi-?fi", "hifi"),
        (r"router|network", "router"),
    )
)


def device_type_for(name: str) -> str:
    """Map a REFIT appliance name to a seeded public.cat_device_type code ('other' if unmapped)."""
    for pattern, code in _DEVICE_TYPE_RULES:
        if pattern.search(name):
            return code
    return "other"


def device_names(meta: dict) -> dict[str, str]:
    """Device name per Appliance channel, unique within the house.

    A name used by several channels becomes "<name> (<note>)" when every channel of the group
    has a short, distinct note (e.g. Freezer (1), Freezer (2)), else "<name> #<k>" with k the
    1-based order of the channel within the group. Unrepeated names are kept as they are.
    """
    chans = [(c, meta["channels"][c]) for c in CHANNELS[1:]]
    groups: dict[str, list[tuple[str, dict]]] = {}
    for channel, info in chans:
        groups.setdefault(info["name"].lower(), []).append((channel, info))
    out: dict[str, str] = {}
    for members in groups.values():
        if len(members) == 1:
            out[members[0][0]] = members[0][1]["name"]
            continue
        notes = [(i.get("note") or "") for _, i in members]
        usable = all(n and len(n) <= 20 and ";" not in n for n in notes)
        by_note = usable and len(set(notes)) == len(notes)
        for k, (channel, info) in enumerate(members, start=1):
            out[channel] = f"{info['name']} ({notes[k - 1]})" if by_note else f"{info['name']} #{k}"
    return out


def meter_serial(house: int) -> str:
    return f"REFIT-H{house}"


def _year_built(construction: str | None) -> int | None:
    """First four-digit year of a value like '1975-1980' (None when there is none)."""
    m = re.search(r"\b(1[89]\d\d|20\d\d)\b", construction or "")
    return int(m.group(1)) if m else None


async def provision_house(session: AsyncSession, house: int, owner_email: str) -> int:
    """Create (or complete) the user, home, meter, devices and series of a REFIT house.

    Idempotent: existing rows are reused, so a second call changes nothing and returns the same
    home id. Flushes only; the caller commits. Raises ValueError for a house not in the metadata.
    """
    meta = METADATA.get(str(house))
    if meta is None:
        raise ValueError(f"unknown REFIT house {house}")
    email = owner_email.lower()
    serial = meter_serial(house)
    home_name = f"REFIT House {house}"

    # Validate before any write, so a refusal leaves nothing behind.
    user = await session.scalar(select(User).where(User.email == email))
    home_id = None
    if user is not None:
        home_id = await session.scalar(
            select(HomeMember.home_id).where(HomeMember.user_id == user.id)
        )
    meter = await session.scalar(select(Meter).where(Meter.serial == serial))
    if home_id is not None:
        name = await session.scalar(select(Home.name).where(Home.id == home_id))
        if name != home_name and (meter is None or meter.home_id != home_id):
            raise ValueError(
                f"{owner_email} already owns a home ({name!r}) that is not {home_name!r}; "
                "use a different --owner-email"
            )
    elif meter is not None:
        raise ValueError(f"meter {serial} already belongs to another home")

    if user is None:
        user = User(email=email)
        session.add(user)
        await session.flush()
    if home_id is None:
        home = Home(
            name=home_name,
            home_type="house",
            occupants=meta.get("occupancy"),
            year_built=_year_built(meta.get("construction")),
            tariff_plan_code=TARIFF_PLAN,
            billing_cycle_day=1,
            timezone="Asia/Ho_Chi_Minh",
        )
        session.add(home)
        await session.flush()
        home_id = home.id
        session.add(HomeMember(home_id=home_id, user_id=user.id, role="owner"))
        await session.flush()

    if meter is None:
        meter = Meter(serial=serial, home_id=home_id, status="active")
        session.add(meter)
        await session.flush()

    have = set(
        await session.scalars(
            select(Series.source_channel).where(
                Series.meter_id == meter.id, Series.source_channel.is_not(None)
            )
        )
    )
    names = device_names(meta)
    for channel in CHANNELS:
        if channel in have:
            continue
        if channel == "Aggregate":
            session.add(
                Series(
                    home_id=home_id,
                    kind="main",
                    metric="power_w",
                    unit="W",
                    meter_id=meter.id,
                    source_channel=channel,
                )
            )
            continue
        name = names[channel]
        device = Device(
            home_id=home_id, device_type_code=device_type_for(name), name=name, origin="plug"
        )
        session.add(device)
        await session.flush()
        session.add(
            Series(
                home_id=home_id,
                kind="plug",
                device_id=device.id,
                metric="power_w",
                unit="W",
                meter_id=meter.id,
                source_channel=channel,
            )
        )
    await session.flush()
    return home_id
