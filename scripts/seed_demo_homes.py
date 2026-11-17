"""Create the demo homes of scripts/demo_homes.toml and load their recent history.

Idempotent: re-running updates profiles, accounts and models, and only adds missing readings.
Per home: Keycloak account(s) with role `user` (password DEMO_PASSWORD), local profile linked by
`sub`, home "REFIT House <n>" + membership, meter REFIT-H<n> with its main series, its NILM
devices under their REFIT names, its NILM model (if listed), the
time shift (etl.tb_watermark, segment 'demo'), then `history_days` of readings through
ops.ingest_readings, and the continuous aggregates over them. Then start scripts.replay_refit.

Runs on the host against the published ports, reading .env:
    uv run python -m scripts.seed_demo_homes [--house 5]
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REALM = "wattprint"


def load_env() -> None:
    """Read .env (KEY=VALUE lines) into os.environ without overriding what is already set."""
    for line in (ROOT / ".env").read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"'))
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@localhost:{DB_PORT}/{POSTGRES_DB}".format(
            **os.environ
        ),
    )


class Keycloak:
    """Just enough of the admin REST API to keep demo accounts in step with the config."""

    def __init__(self, base: str, admin_password: str):
        self.base = base.rstrip("/")
        self.password = admin_password
        self.token = None

    def login(self) -> None:
        """Admin tokens live 60 s: log in again before each account (a home takes longer)."""
        self.token = None
        body = urllib.parse.urlencode(
            {
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": "admin",
                "password": self.password,
            }
        ).encode()
        path = "/realms/master/protocol/openid-connect/token"
        self.token = self._call("POST", path, body, form=True)["access_token"]

    def _call(self, method: str, path: str, body=None, form: bool = False):
        headers = {
            "Content-Type": "application/x-www-form-urlencoded" if form else "application/json"
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = body if form or body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
                if r.status == 201 and not raw:
                    return r.headers["Location"].rsplit("/", 1)[-1]
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            sys.exit(f"Keycloak {method} {path}: {e.code} {e.read().decode()[:300]}")

    def find_user(self, email: str) -> str | None:
        """The id of an existing account (e.g. a Google sign-in), never creating or changing it."""
        self.login()
        q = urllib.parse.quote(email)
        found = self._call("GET", f"/admin/realms/{REALM}/users?exact=true&email={q}")
        return found[0]["id"] if found else None

    def ensure_user(self, email: str, name: str, password: str) -> str:
        """Create or update the account; returns its id (the token `sub`)."""
        self.login()
        admin = f"/admin/realms/{REALM}"
        found = self._call("GET", f"{admin}/users?exact=true&email={urllib.parse.quote(email)}")
        first, _, last = name.partition(" ")
        profile = {
            "username": email,
            "email": email,
            "firstName": first,
            "lastName": last or first,
            "enabled": True,
            "emailVerified": True,
            "requiredActions": [],
        }
        if found:
            uid = found[0]["id"]
            self._call("PUT", f"{admin}/users/{uid}", profile)
        else:
            uid = self._call("POST", f"{admin}/users", profile)
        self._call(
            "PUT",
            f"{admin}/users/{uid}/reset-password",
            {"type": "password", "value": password, "temporary": False},
        )
        role = self._call("GET", f"{admin}/roles/user")
        self._call("POST", f"{admin}/users/{uid}/role-mappings/realm", [role])
        return uid


async def ensure_profile(session, email: str, name: str | None, sub: str | None):
    from sqlalchemy import text

    return await session.scalar(
        text(
            "INSERT INTO public.tb_users (email, full_name, keycloak_sub) VALUES (:e, :n, :s) "
            "ON CONFLICT (email) DO UPDATE SET full_name = COALESCE(EXCLUDED.full_name, "
            "public.tb_users.full_name), keycloak_sub = COALESCE(EXCLUDED.keycloak_sub, "
            "public.tb_users.keycloak_sub) RETURNING id"
        ),
        {"e": email.lower(), "n": name, "s": sub},
    )


async def seed_home(cfg: dict, home: dict, kc: Keycloak, password: str, extra: list[str]) -> None:
    from sqlalchemy import text

    from app.database import SessionLocal, engine
    from app.modules.energy.api import backfill_aggregates
    from app.modules.nilm.api import OTHER, ensure_devices
    from scripts import refit, replay_refit

    house = home["house"]
    csv = ROOT / "dataset" / f"CLEAN_House{house}.csv"
    df = refit.load(csv)
    now = datetime.now(UTC)
    history = timedelta(days=cfg["history_days"])
    first, last = df["wall"].iloc[0].to_pydatetime(), df["wall"].iloc[-1].to_pydatetime()
    model_dir = ROOT / "dataset" / "models" / "nilm"

    people = [(home["owner"], "owner")] + [(m, "member") for m in home.get("members", [])]
    subs = {p["email"]: kc.ensure_user(p["email"], p["name"], password) for p, _ in people}
    # Real accounts: linked by their Keycloak id when they exist, else claimed on first login.
    subs |= {e: kc.find_user(e) for e in extra}

    async with SessionLocal() as s, s.begin():
        # The home is the one its REFIT meter is on, so a renamed home is found again.
        name = f"REFIT House {house}"
        home_id = await s.scalar(
            text("SELECT home_id FROM public.tb_meter WHERE serial = :m"), {"m": refit.meter(house)}
        )
        if home_id is None:
            home_id = await s.scalar(
                text(
                    "INSERT INTO public.tb_home (name, tariff_plan_code) "
                    "VALUES (:n, 'vn_residential') RETURNING id"
                ),
                {"n": name},
            )
        await s.execute(
            text(
                "UPDATE public.tb_home SET name = :n, province_code = NULL, home_type = NULL, "
                "floor_area_m2 = NULL, occupants = NULL, tariff_plan_code = 'vn_residential' "
                "WHERE id = :h"
            ),
            {"n": name, "h": home_id},
        )
        for p, role in people + [({"email": e, "name": None}, "member") for e in extra]:
            uid = await ensure_profile(s, p["email"], p["name"], subs.get(p["email"]))
            # Demo accounts move here; an extra (real) account already in a home stays there.
            on_conflict = (
                "DO NOTHING"
                if p["email"] in extra
                else ("DO UPDATE SET home_id = EXCLUDED.home_id, role = EXCLUDED.role")
            )
            added = await s.scalar(
                text(
                    "INSERT INTO public.tb_home_member (home_id, user_id, role) "
                    f"VALUES (:h, :u, :r) ON CONFLICT (user_id) {on_conflict} RETURNING user_id"
                ),
                {"h": home_id, "u": uid, "r": role},
            )
            if added is None:
                print(f"house {house}: {p['email']} already has a home, left there")
        meter_id = await s.scalar(
            text(
                "INSERT INTO public.tb_meter (serial, home_id, status, claimed_at) "
                "VALUES (:m, :h, 'active', now()) ON CONFLICT (serial) DO UPDATE "
                "SET home_id = EXCLUDED.home_id, status = 'active' RETURNING id"
            ),
            {"m": refit.meter(house), "h": home_id},
        )
        await s.execute(
            text(
                "INSERT INTO public.tb_series "
                "(home_id, kind, meter_id, source_channel, metric, unit) "
                "VALUES (:h, 'main', :m, :c, 'power_w', 'W') "
                "ON CONFLICT ON CONSTRAINT uq_series_home_kind_device_metric DO UPDATE "
                "SET meter_id = EXCLUDED.meter_id, source_channel = EXCLUDED.source_channel"
            ),
            {"h": home_id, "m": meter_id, "c": refit.CHANNEL},
        )
        for owner, artifact in ((home_id, home.get("model")), (None, cfg.get("shared_model"))):
            if artifact:
                await register_model(s, owner, artifact, model_dir)
        # The NILM devices, named as REFIT names that appliance in this house.
        names = home.get("devices", {})
        series = await ensure_devices(s, home_id, [label for label in names if label != OTHER])
        for label, refit_name in names.items():
            await s.execute(
                text(
                    "UPDATE public.tb_device d SET name = :n FROM public.tb_series x "
                    "WHERE x.series_id = :s AND d.id = x.device_id"
                ),
                {"n": refit_name, "s": series[label]},
            )
        row = (
            await s.execute(
                text("SELECT shift_days FROM etl.tb_watermark WHERE source = :s AND segment = :g"),
                {"s": refit.source(house), "g": refit.SEGMENT},
            )
        ).first()
        shift = row.shift_days if row else refit.pick_shift(first, now, history)
        span = refit.db_time([first, last], shift)
        await s.execute(
            text(
                "INSERT INTO etl.tb_watermark (source, segment, shift_days, range_from, range_to, "
                "status) VALUES (:s, :g, :d, :a, :b, 'running') ON CONFLICT (source, segment) "
                "DO UPDATE SET status = 'running', error = NULL, updated_at = now()"
            ),
            {"s": refit.source(house), "g": refit.SEGMENT, "d": shift, "a": span[0], "b": span[1]},
        )
    print(f"house {house}: home {home_id}, shift {shift} days ({shift // 364} years)", flush=True)

    h = replay_refit.Home(house, shift, df, now - history)
    new = await replay_refit.replay(h, now - history, now, source="seed")
    async with engine.connect() as c:
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        await backfill_aggregates(c, now - history, now)
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "UPDATE etl.tb_watermark SET status = 'done', last_ts = :t, "
                "rows_loaded = rows_loaded + :n, updated_at = now() "
                "WHERE source = :s AND segment = :g"
            ),
            {"t": now, "n": new, "s": refit.source(house), "g": refit.SEGMENT},
        )
    print(f"house {house}: {new} new readings over {cfg['history_days']} days", flush=True)


async def register_model(session, home_id, artifact: str, model_dir: Path) -> None:
    """Make `artifact` the active model of the home (or the shared one); version = file sha256."""
    from sqlalchemy import text

    path = model_dir / artifact
    if not path.is_file():
        sys.exit(f"model {path} not found (copy the bundle there first)")
    version = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    where = "home_id IS NOT DISTINCT FROM :h"
    await session.execute(
        text(f"UPDATE public.tb_nilm_model SET active = false WHERE {where} AND version <> :v"),
        {"h": home_id, "v": version},
    )
    await session.execute(
        text(
            "INSERT INTO public.tb_nilm_model (home_id, name, version, artifact) "
            "VALUES (:h, 'nilmformer-gru', :v, :a) "
            "ON CONFLICT ON CONSTRAINT uq_tb_nilm_model_home_name_version "
            "DO UPDATE SET active = true, artifact = EXCLUDED.artifact"
        ),
        {"h": home_id, "v": version, "a": artifact},
    )


async def main(only: int | None) -> None:
    load_env()
    password = os.environ.get("DEMO_PASSWORD") or sys.exit("Set DEMO_PASSWORD in .env")
    cfg = tomllib.loads((ROOT / "scripts" / "demo_homes.toml").read_text())
    kc = Keycloak(
        os.environ.get("KEYCLOAK_PUBLIC_URL") or f"http://localhost:{os.environ['KEYCLOAK_PORT']}",
        os.environ["KEYCLOAK_ADMIN_PASSWORD"],
    )
    extra = [e.strip() for e in os.environ.get("DEMO_EXTRA_MEMBERS", "").split(",") if e.strip()]
    for i, home in enumerate(cfg["home"]):
        if only is None or home["house"] == only:
            await seed_home(cfg, home, kc, password, extra if i == 0 else [])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", type=int)
    asyncio.run(main(ap.parse_args().house))
