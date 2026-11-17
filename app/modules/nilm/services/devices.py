import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

OTHER = "Other"  # the remainder: aggregate minus every modelled appliance

# Bundle label -> cat_device_type.code. A label missing here fails the pass (KeyError) rather than
# sharing Other's series and overwriting it.
DEVICE_TYPES = {
    "Fridge": "fridge_freezer",
    "Freezer": "freezer",
    "WashMach": "washing_machine",
    "Dishwash": "dishwasher",
    "Microwave": "microwave",
    "Toaster": "toaster",
    "Kettle": "kettle",
    OTHER: "other",
}


async def ensure_devices(
    session: AsyncSession, home_id: uuid.UUID, labels: list[str]
) -> dict[str, uuid.UUID]:
    """Create (once) one origin='nilm' device and its 'device' series per label plus Other.

    Returns label -> series_id. A device is matched on (home, origin 'nilm', type), so renaming it
    in the app keeps its series; the default name is the type's Vietnamese label. Fridges and Other
    stay off the timeline: their dozens of runs a day (or none) would bury the rest. Flushes only.
    """
    out: dict[str, uuid.UUID] = {}
    for label in [*labels, OTHER]:
        code = DEVICE_TYPES[label]
        device_id = await session.scalar(
            text(
                "SELECT id FROM public.tb_device WHERE home_id = :h AND origin = 'nilm' "
                "AND device_type_code = :c AND deleted_at IS NULL ORDER BY created_at LIMIT 1"
            ),
            {"h": home_id, "c": code},
        )
        if device_id is None:
            device_id = await session.scalar(
                text(
                    "INSERT INTO public.tb_device "
                    "(home_id, device_type_code, name, origin, show_on_timeline) "
                    "SELECT :h, code, label_vi, 'nilm', code NOT IN ('fridge_freezer', 'freezer', "
                    "'other') FROM public.cat_device_type "
                    "WHERE code = :c RETURNING id"
                ),
                {"h": home_id, "c": code},
            )
        out[label] = await session.scalar(
            text(
                "INSERT INTO public.tb_series (home_id, kind, device_id, metric, unit) "
                "VALUES (:h, 'device', :d, 'power_w', 'W') "
                "ON CONFLICT ON CONSTRAINT uq_series_home_kind_device_metric "
                "DO UPDATE SET unit = EXCLUDED.unit RETURNING series_id"
            ),
            {"h": home_id, "d": device_id},
        )
    await session.flush()
    return out
