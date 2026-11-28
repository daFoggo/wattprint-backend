import logging

import httpx

from app.config import settings

from . import outbound

log = logging.getLogger(__name__)

_transport: httpx.AsyncBaseTransport | None = None  # tests put a MockTransport here
MAX_CHARS = 3500  # Telegram refuses messages over 4096


async def tell_maintainers(
    text: str, data: list[str] | None = None, *, user_id=None, home_id=None
) -> None:
    """Posts to the maintainers' Telegram chat; does nothing unless both settings are set.

    Never raises: feedback must not fail because a chat is down. The error is logged by type only,
    since its text carries the bot token (it is in the URL).
    """
    token, chat = settings.feedback_telegram_token, settings.feedback_telegram_chat
    if not (token and chat):
        return
    try:
        await outbound.record(
            "telegram", "feedback", data or ["rating"], user_id=user_id, home_id=home_id
        )
        async with outbound.client("telegram", transport=_transport, timeout=5) as client:
            r = await client.post(
                f"/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text[:MAX_CHARS], "disable_web_page_preview": True},
            )
        if r.status_code != 200:
            log.warning("feedback note refused by Telegram (%s)", r.status_code)
    except (
        Exception
    ) as e:  # not only HTTPError: a malformed token raises InvalidURL, with the token
        log.warning("feedback note not sent: %s", type(e).__name__)
