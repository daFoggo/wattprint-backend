import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update

from app.database import SessionLocal

from ..models import Conversation, Message, ToolCall
from ..utils import CopilotUnavailableError
from . import llm
from .tools import SPECS, TIERS, Ctx, Outcome, run_tool

log = logging.getLogger("copilot.chat")
ICT = timezone(timedelta(hours=7))
MAX_ROUNDS = 4  # tool rounds; the next turn must answer
HISTORY = 12  # earlier messages of the conversation the model sees
TOOL_CHARS = 6000  # a tool result is cut to this before the model reads it
FOLLOW = "FOLLOW-UPS:"

SOURCES = {
    "tariff": (
        {"vi": "Biểu giá bán lẻ điện (EVN)", "en": "EVN retail tariff"},
        "https://www.evn.com.vn/c3/evn-va-khach-hang/Bieu-gia-ban-le-dien-9-79.aspx",
    ),
    "meter": (
        {"vi": "Công tơ tổng của nhà", "en": "The home's main meter"},
        "/dashboard/statistics",
    ),
    "nilm": (
        {"vi": "Ước tính theo thiết bị (NILM)", "en": "Per-device estimates (NILM)"},
        "/dashboard/devices",
    ),
    "weather": ({"vi": "OpenWeather", "en": "OpenWeather"}, "https://openweathermap.org"),
    "cohort": ({"vi": "Các hộ tương tự", "en": "Similar homes"}, "/dashboard/statistics"),
}
LINKS = {
    "devices": "/dashboard/devices",
    "bill": "/dashboard/bill",
    "statistics": "/dashboard/statistics",
    "settings": "/dashboard/settings",
}
STEPS = {
    "devices_breakdown": ("Đọc điện năng theo thiết bị", "Read energy by device"),
    "current_bill": ("Tính hoá đơn kỳ này", "Price this cycle"),
    "bill_forecast": ("Dự báo hoá đơn cuối kỳ", "Forecast the cycle's bill"),
    "bill_history": ("Đọc các hoá đơn trước", "Read past bills"),
    "compare_periods": ("So với kỳ trước", "Compare with the previous period"),
    "weather": ("Xem thời tiết", "Check the weather"),
    "cohort": ("So với hộ tương tự", "Compare with similar homes"),
    "alerts": ("Xem cảnh báo", "Check alerts"),
    "standby": ("Đo điện nền ban đêm", "Measure night-time standby"),
    "query_data": ("Truy vấn dữ liệu của nhà", "Query the home's data"),
    "propose_plan": ("Lập kế hoạch tiết kiệm", "Draft a savings plan"),
}
INTENTS = {
    "devices_breakdown": "devices",
    "alerts": "devices",
    "current_bill": "bill",
    "bill_history": "bill",
    "compare_periods": "bill",
    "bill_forecast": "forecast",
    "weather": "weather",
    "cohort": "peers",
    "standby": "standby",
    "propose_plan": "plan",
    "query_data": "data",
}

PROMPT = """You are Wappi, the energy assistant of WattPrint for one household in Vietnam.
Today is {today} ({weekday}), local time {time}.
- Get every figure from the tools; never invent or guess numbers. If the tools cannot answer,
  say so plainly and suggest what the user can do in the app.
- Per-device figures are NILM estimates from the main meter, not separate meters: say "ước tính"
  / "estimated" when you use them. "Other" is load no device explains.
- Cite with [n] right after a figure, n being a number from the tool result's `cite` list.
- Answer in {language}, in at most 120 words, plain sentences (no tables, no headings), VND as
  "123.000 đ" in Vietnamese. Charts and links are added under your answer by the app: do not
  describe them or paste URLs.
- Call tools first, without writing anything before them.
- Only for a savings plan the user asks for, call propose_plan with tasks grounded in the data.
- Outside home energy, decline briefly.
After the answer write a line `{follow}` and then 2-3 short follow-up questions the user might
ask next, one per line, in {language}, without numbering."""


class FollowUps:
    """Splits the streamed text at the FOLLOW-UPS line, holding back what may start it."""

    def __init__(self) -> None:
        self.buf, self.answer, self.tail, self.split = "", "", "", False

    def feed(self, chunk: str) -> str:
        if self.split:
            self.tail += chunk
            return ""
        self.buf += chunk
        if (i := self.buf.find(FOLLOW)) >= 0:
            out, self.tail, self.split = self.buf[:i], self.buf[i + len(FOLLOW) :], True
            self.buf = ""
        else:
            keep = next(
                (
                    k
                    for k in range(min(len(FOLLOW), len(self.buf)), 0, -1)
                    if FOLLOW.startswith(self.buf[-k:])
                ),
                0,
            )
            out, self.buf = self.buf[: len(self.buf) - keep], self.buf[len(self.buf) - keep :]
        self.answer += out
        return out

    def close(self) -> tuple[str, list[str]]:
        self.answer += self.buf  # a held-back start that never became the marker
        lines = [q.strip(" -•*0123456789.") for q in self.tail.splitlines()]
        return self.answer.strip(), [q for q in lines if q][:3]


def _system(lang: str, now: datetime) -> dict[str, str]:
    local = now.astimezone(ICT)
    return {
        "role": "system",
        "content": PROMPT.format(
            today=local.date().isoformat(),
            weekday=local.strftime("%A"),
            time=local.strftime("%H:%M"),
            language="Vietnamese" if lang == "vi" else "English",
            follow=FOLLOW,
        ),
    }


async def history(session, conversation_id: uuid.UUID, before: uuid.UUID) -> list[dict[str, str]]:
    rows = (
        await session.execute(
            select(Message.role, Message.content)
            .where(
                Message.conversation_id == conversation_id,
                Message.id < before,
                Message.role.in_(("user", "assistant")),
            )
            .order_by(Message.id.desc())
            .limit(HISTORY)
        )
    ).all()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


class Answer:
    """What the reply is built from, filled as the tools run."""

    def __init__(self, lang: str) -> None:
        self.lang = lang
        self.steps: list[dict[str, str]] = []
        self.calls: list[tuple[str, dict, Outcome, bool, int]] = []
        self.sources: list[str] = []

    def cite(self, keys: list[str]) -> list[int]:
        for k in keys:
            if k not in self.sources:
                self.sources.append(k)
        return [self.sources.index(k) + 1 for k in keys]

    def reply(self, text: str, follow_ups: list[str]) -> dict[str, Any]:
        outcomes = [o for _, _, o, ok, _ in self.calls if ok]
        widgets: dict[str, dict] = {}
        links: list[str] = []
        for o in outcomes:
            for w in o.widgets:
                widgets[w["kind"]] = w  # a tool called twice: its last result
            links += [k for k in o.links if k not in links]
        if links:
            widgets["links"] = {
                "kind": "links",
                "links": [{"key": k, "href": LINKS[k]} for k in links],
            }
        tiers = [o.tier for o in outcomes]
        names = [n for n, *_ in self.calls]
        return {
            # A saved plan is what the answer is about, whatever was read to make it.
            "intent": "plan"
            if "propose_plan" in names
            else INTENTS.get(names[0], "data")
            if names
            else "chat",
            "tier": max(tiers, key=TIERS.index) if tiers else "inferred",
            "steps": self.steps,
            "sql": next((o.sql for o in reversed(outcomes) if o.sql), None),
            "text": text,
            "sources": [
                {"title": SOURCES[k][0][self.lang], "url": SOURCES[k][1]} for k in self.sources
            ],
            "widgets": list(widgets.values()),
            "followUps": follow_ups,
        }


def event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def answer(
    home_id: uuid.UUID, conversation_id: uuid.UUID, question_id: uuid.UUID, lang: str
) -> AsyncIterator[str]:
    """SSE of one answer: meta, step per tool, token per text delta, then done (stored) or error."""
    now = datetime.now(UTC)
    reply_id = uuid.uuid7()
    yield event("meta", {"conversation_id": conversation_id, "message_id": reply_id})
    state = Answer(lang)
    follow = FollowUps()
    async with SessionLocal() as s:
        question = await s.scalar(select(Message.content).where(Message.id == question_id))
        messages = [
            _system(lang, now),
            *await history(s, conversation_id, question_id),
            {"role": "user", "content": question},
        ]
        ctx = Ctx(s, home_id, now, lang)
        try:
            for round_no in range(MAX_ROUNDS + 1):
                # Commit what the tools wrote (a plan) and give the connection back while the model
                # thinks: an answer can take a minute, and the pool is shared with every request.
                await s.commit()
                turn = llm.Turn()
                async for delta in llm.stream(
                    messages, SPECS if round_no < MAX_ROUNDS else None, turn
                ):
                    if out := follow.feed(delta):
                        yield event("token", {"text": out})
                if not turn.calls:
                    break
                if turn.text and not follow.answer.endswith("\n"):
                    follow.feed("\n\n")  # words before a tool call stay; the answer goes on below
                messages.append(
                    {
                        "role": "assistant",
                        "content": turn.text or None,
                        "tool_calls": [
                            {
                                "id": c.id or f"call_{i}",
                                "type": "function",
                                "function": {"name": c.name, "arguments": c.arguments or "{}"},
                            }
                            for i, c in enumerate(turn.calls)
                        ],
                    }
                )
                for i, c in enumerate(turn.calls):
                    args = c.args()
                    outcome, ok, ms = await run_tool(ctx, c.name, args)
                    vi, en = STEPS.get(c.name, (c.name, c.name))
                    step = {
                        "tool": c.name,
                        "label": vi if lang == "vi" else en,
                        "detail": outcome.detail,
                    }
                    state.steps.append(step)
                    state.calls.append((c.name, args, outcome, ok, ms))
                    yield event("step", step)
                    content = json.dumps(
                        {"cite": state.cite(outcome.sources), "data": outcome.data},
                        ensure_ascii=False,
                        default=str,
                    )[:TOOL_CHARS]
                    messages.append(
                        {"role": "tool", "tool_call_id": c.id or f"call_{i}", "content": content}
                    )
        except CopilotUnavailableError as e:
            log.warning("copilot answer failed: %s", e.message)
            await s.rollback()
            partial = state.reply("", [])
            yield event("error", {"code": e.code, "message": e.message, "reply": partial})
            return
        text, follow_ups = follow.close()
        reply = state.reply(text, follow_ups)
        s.add(
            Message(
                id=reply_id,
                conversation_id=conversation_id,
                role="assistant",
                content=text,
                reply=reply,
            )
        )
        await s.flush()
        s.add_all(
            ToolCall(
                message_id=reply_id,
                tool=name,
                input=args,
                sql_text=o.sql,
                duration_ms=ms,
                ok=ok,
            )
            for name, args, o, ok, ms in state.calls
        )
        await s.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )
        await s.commit()
    yield event("done", {"message_id": reply_id, "reply": reply})
