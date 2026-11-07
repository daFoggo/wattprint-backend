import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

ROOT = Path(__file__).resolve().parents[2]


def run_alembic(dsn: str, *args: str, **extra_env: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.endswith("_DB_PASSWORD")}
    env.update(extra_env)
    env["DATABASE_URL"] = dsn
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        cmd = " ".join(args)
        raise RuntimeError(f"alembic {cmd} failed:\n{proc.stdout}\n{proc.stderr}")


def load_revision(prefix: str):
    """Import an Alembic revision module by file prefix (file names are not importable)."""
    path = next((ROOT / "alembic" / "versions").glob(f"{prefix}*.py"))
    spec = importlib.util.spec_from_file_location(f"rev_{prefix}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _create_migrated_db():
    """Create a scratch database and migrate it. Returns (dsn, drop coroutine function)."""
    base = make_url(settings.database_url)
    name = f"wattprint_test_{uuid.uuid4().hex[:8]}"
    admin = create_async_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(text(f'CREATE DATABASE "{name}"'))

    async def drop():
        try:
            async with admin.connect() as c:
                await c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        finally:
            await admin.dispose()

    dsn = base.set(database=name).render_as_string(hide_password=False)
    try:
        run_alembic(dsn, "upgrade", "head")
    except BaseException:
        await drop()
        raise
    return dsn, drop


@pytest.fixture(scope="session")
async def scratch_dsn():
    dsn, drop = await _create_migrated_db()
    try:
        yield dsn
    finally:
        await drop()


@pytest.fixture
async def throwaway_dsn():
    """A private migrated database for tests that downgrade or otherwise mutate the schema."""
    dsn, drop = await _create_migrated_db()
    try:
        yield dsn
    finally:
        await drop()


@pytest.fixture(scope="session")
async def scratch_engine(scratch_dsn):
    engine = create_async_engine(scratch_dsn)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def conn(scratch_engine):
    async with scratch_engine.connect() as c:
        trans = await c.begin()
        try:
            yield c
        finally:
            await trans.rollback()


@pytest.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as s:
        yield s


@pytest.fixture
async def autocommit_conn(scratch_dsn):
    engine = create_async_engine(scratch_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            yield c
    finally:
        await engine.dispose()


# --- Copilot: the demo home loaded from the legacy dump, and a scripted chat model ---

DUMP = ROOT / "tests" / "data" / "wattprint_dump_20261103.tar.gz"
DEMO_TODAY = dt.date(2026, 11, 5)  # the dump is stored under 29 Oct .. 4 Nov 2026


@dataclass
class Demo:
    dsn: str
    sessions: async_sessionmaker
    user_id: uuid.UUID
    home_id: uuid.UUID
    email: str


@pytest.fixture(scope="session")
async def demo(tmp_path_factory):
    """A migrated database holding REFIT House 2 from the dump, owned by one registered user."""
    from app.cli.migrate_legacy import make_plan, migrate, read_legacy
    from app.schemas.user import UserCreate
    from app.services.aggregates import backfill_aggregates
    from app.services.auth import register_user
    from app.services.disaggregation import home_of, local_day_start

    folder = tmp_path_factory.mktemp("dump")
    with tarfile.open(DUMP) as tar:
        tar.extractall(folder, filter="data")
    dsn, drop = await _create_migrated_db()
    engine = create_async_engine(dsn)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    email = "owner@example.com"
    try:
        async with sessions() as s:
            user = await register_user(
                s, UserCreate(email=email, password="demo-password-123", full_name="Anh Demo")
            )
            legacy = read_legacy(folder)
            plan = make_plan(legacy, DEMO_TODAY - dt.timedelta(days=1), DEMO_TODAY)
            await migrate(s, legacy, plan, 2, email)
            home_id = await home_of(s, user.id)
        auto = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
        async with auto.connect() as c:
            await backfill_aggregates(c, local_day_start(plan.first_target),
                                      local_day_start(plan.last_target) + dt.timedelta(days=1))
        await auto.dispose()
        from app.copilot.skills import retrieval
        from app.copilot.skills.catalog_sync import sync

        # the fake embedder's cosines run lower than bge-m3's: its own "choose" floor
        retrieval.CFG["choose_min_sim"] = 0.3
        retrieval.CFG["memory_min_sim"] = 0.3
        from app.copilot.nodes import ingress_node

        ingress_node.LIMITS["messages_per_minute"] = 100_000  # one demo user asks every test
        async with sessions() as s:
            await sync(s, FakeEmbedder())
        yield Demo(dsn, sessions, user.id, home_id, email)
    finally:
        await engine.dispose()
        await drop()


class FakeEmbedder:
    """Deterministic stand-in for bge-m3: character trigrams of the toneless text, hashed into
    1024 dimensions and normalised, so similar wordings score high and the same text scores 1."""

    model_name = "fake-trigram"

    def _one(self, text: str) -> list[float]:
        import hashlib
        import math

        from app.copilot.skills.chunker import no_tone

        v = [0.0] * 1024
        t = f"  {no_tone(text)}  "
        for i in range(len(t) - 2):
            v[int(hashlib.md5(t[i:i + 3].encode()).hexdigest(), 16) % 1024] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._one(text)


class FakeChatModel:
    """Scripted stand-in for the OpenRouter model.

    `calls` maps the user's question to the tool calls of the first round: a list of
    (tool, args) or a function of the decide payload (it sees the linked terms, as the real model
    does). Later rounds return no call. The skill choice defaults to the top candidate; `choose`
    overrides it per question. Free text is `answer`.
    """

    def __init__(self, calls: dict | None = None, answer: str = "(câu trả lời mẫu)",
                 choose: dict | None = None, summary=None, rewrites: dict | None = None):
        self.calls, self.answer, self.choose = calls or {}, answer, choose or {}
        self.summary, self.rewrites = summary, rewrites or {}
        self.payloads: list[dict] = []
        self.model_name = "fake"

    def with_structured_output(self, schema, **_):
        return _Structured(self, schema)

    def bind_tools(self, tools):
        return _Bound(self, tools)

    async def ainvoke(self, messages):
        from langchain_core.messages import AIMessage

        return AIMessage(content=self.answer)


class _Bound:
    def __init__(self, model: FakeChatModel, tools):
        self.model, self.tools = model, tools

    async def ainvoke(self, messages):
        from langchain_core.messages import AIMessage, ToolMessage

        payload = json.loads(messages[1].content)
        payload["tools"] = [t["function"]["name"] for t in self.tools]
        payload["tool_params"] = {t["function"]["name"]: list(
            t["function"]["parameters"].get("properties", {})) for t in self.tools}
        self.model.payloads.append(payload)
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="")
        script = self.model.calls.get(payload["original"], [])
        calls = script(payload) if callable(script) else script
        return AIMessage(content="", tool_calls=[
            {"name": name, "args": args, "id": f"call_{i}"}
            for i, (name, args) in enumerate(calls)])


class _Structured:
    def __init__(self, model: FakeChatModel, schema):
        self.model, self.schema = model, schema

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        self.model.payloads.append(payload)
        name = self.schema.__name__
        if name == "SkillChoice":
            for question, code in self.model.choose.items():
                if payload["question"].startswith(question):
                    return self.schema(code=code)
            return self.schema(code=payload["candidates"][0]["code"])
        if name == "SessionSummaryOut" and self.model.summary:
            return self.model.summary(payload)
        if name == "Rewrite" and payload["follow_up"] in self.model.rewrites:
            return self.schema(question=self.model.rewrites[payload["follow_up"]])
        raise RuntimeError(f"no script for {name}")  # callers fall back
