import json
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.common import notify
from app.config import settings
from app.database import SessionLocal


@pytest.fixture
def telegram(monkeypatch):
    """A Telegram chat that records what it is sent."""
    sent: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append({"url": str(request.url), **json.loads(request.content)})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(notify, "_transport", httpx.MockTransport(handle))
    monkeypatch.setattr(settings, "feedback_telegram_token", "123:abc")
    monkeypatch.setattr(settings, "feedback_telegram_chat", "-100")
    return sent


async def test_silent_until_both_settings_are_set(monkeypatch):
    def refuse(request):
        raise AssertionError("nothing may be sent")

    monkeypatch.setattr(notify, "_transport", httpx.MockTransport(refuse))
    monkeypatch.setattr(settings, "feedback_telegram_token", "123:abc")
    monkeypatch.setattr(settings, "feedback_telegram_chat", "")
    await notify.tell_maintainers("hi")


async def test_posts_to_the_chat_and_cuts_long_text(telegram):
    await notify.tell_maintainers("x" * 5000)
    assert len(telegram) == 1
    assert telegram[0]["url"] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert telegram[0]["chat_id"] == "-100"
    assert len(telegram[0]["text"]) <= 3500


async def test_a_chat_that_is_down_does_not_fail_the_caller(telegram, monkeypatch):
    def down(request):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(notify, "_transport", httpx.MockTransport(down))
    await notify.tell_maintainers("hi")  # must not raise


async def _conversation(home_id, user_id, question, answer):
    cid, q, a = uuid.uuid4(), uuid.uuid7(), uuid.uuid7()
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text("INSERT INTO ai.ai_conversation (id, home_id, user_id) VALUES (:c, :h, :u)"),
            {"c": cid, "h": home_id, "u": user_id},
        )
        for mid, role, content in ((q, "user", question), (a, "assistant", answer)):
            await s.execute(
                text(
                    "INSERT INTO ai.ai_message (id, conversation_id, role, content) "
                    "VALUES (:i, :c, :r, :t)"
                ),
                {"i": mid, "c": cid, "r": role, "t": content},
            )
    return a


async def test_a_thumbs_down_sends_the_question_and_answer_but_a_thumbs_up_does_not(
    client, make_member, telegram
):
    member = await make_member()
    reply = await _conversation(
        member.home_id, member.user_id, "Tại sao tiền điện cao?", "Vì trời nóng."
    )
    url = f"/api/v1/copilot/messages/{reply}/feedback"

    assert (await client.put(url, headers=member.headers, json={"value": "up"})).status_code == 204
    assert (await client.put(url, headers=member.headers, json={"value": None})).status_code == 204
    assert telegram == []

    assert (
        await client.put(url, headers=member.headers, json={"value": "down"})
    ).status_code == 204
    assert len(telegram) == 1
    assert "Tại sao tiền điện cao?" in telegram[0]["text"]
    assert "Vì trời nóng." in telegram[0]["text"]


async def test_a_thumbs_down_repeated_does_not_message_again(client, make_member, telegram):
    member = await make_member()
    reply = await _conversation(member.home_id, member.user_id, "Hỏi gì đó?", "Đáp gì đó.")
    url = f"/api/v1/copilot/messages/{reply}/feedback"
    for value in ("down", "down", None, "down"):
        assert (
            await client.put(url, headers=member.headers, json={"value": value})
        ).status_code == 204
    # the first down, and the one after the rating was cleared; a retry or double click adds none
    assert len(telegram) == 2


async def test_a_malformed_token_does_not_fail_the_caller(monkeypatch):
    monkeypatch.setattr(settings, "feedback_telegram_token", "bad token\n")
    monkeypatch.setattr(settings, "feedback_telegram_chat", "-100")
    await notify.tell_maintainers(
        "hi"
    )  # httpx.InvalidURL is not an HTTPError: must still not raise
