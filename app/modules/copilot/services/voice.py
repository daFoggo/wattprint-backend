import asyncio
import logging
import re
from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal

from ..models import Speech
from ..utils import VoiceUnavailableError

log = logging.getLogger("copilot.voice")
TIMEOUT = httpx.Timeout(30.0, connect=5.0)
EXT = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}
# Whisper's prompt: the words of this domain, spelled and punctuated as the transcript should be.
VOCABULARY = {
    "vi": "Wappi ơi, tháng này nhà mình dùng bao nhiêu kWh, tiền điện bậc mấy? Tủ lạnh, điều hòa, "
    "bình nóng lạnh, máy giặt, nồi cơm điện, điện chờ.",
    "en": "Wappi, how many kWh did we use this month, which tier is the bill in? Fridge, air "
    "conditioner, water heater, washing machine, standby power.",
}
KEPT_FOR = timedelta(days=30)  # an answer is rarely heard again after that
MAX_SPOKEN = 1500  # characters read aloud per answer: each one is paid
FIRST, REST = 40, 300  # a short first piece starts the voice soon; longer ones after it read better


def _client() -> httpx.AsyncClient:
    if not settings.astralx_api_key:
        raise VoiceUnavailableError
    return httpx.AsyncClient(
        base_url=settings.astralx_base_url,
        timeout=TIMEOUT,
        headers={"Authorization": f"Bearer {settings.astralx_api_key}"},
    )


async def transcribe(audio: bytes, content_type: str, lang: str) -> dict:
    """Speech to text (Whisper through AstralX): {text, language, duration}."""
    async with _client() as client:
        try:
            r = await client.post(
                "/audio/transcriptions",
                files={"file": (f"speech.{EXT[content_type]}", audio, content_type)},
                data={
                    "model": settings.astralx_stt_model,
                    "response_format": "verbose_json",
                    "language": lang,
                    "prompt": VOCABULARY[lang],
                },
            )
            r.raise_for_status()
            body = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("transcription failed: %r", e)
            raise VoiceUnavailableError from e
    return {
        "text": (body.get("text") or "").strip(),
        "language": body.get("language"),
        "duration": body.get("duration"),
    }


# The voice reads digits, decimals, %, °C and dates well, but spells symbols out or skips them,
# and reads 1.250.000 digit by digit: those are written as words first.
UNITS = {
    "vi": {"kWh": "ki lô oát giờ", "kW": "ki lô oát", "Wh": "oát giờ", "W": "oát", "đ": "đồng"},
    "en": {
        "kWh": "kilowatt hours",
        "kW": "kilowatts",
        "Wh": "watt hours",
        "W": "watts",
        "đ": "dong",
    },
}
UNIT = re.compile(r"(?<![^\W\d_])(kWh|kW|Wh|VNĐ|VND|₫)(?!\w)|(?<=\d)\s*(W|đ)(?!\w)")
THOUSANDS = {
    "vi": re.compile(r"(?<![\d,.])\d{1,3}(?:\.\d{3})+(?!\d)"),
    "en": re.compile(r"(?<![\d,.])\d{1,3}(?:,\d{3})+(?!\d)"),
}
CLOCK = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
SENTENCE = re.compile(r"(?<=[.!?…;])\s+|\s*\n+\s*")


def spoken(text: str, lang: str) -> str:
    """The answer as read aloud: no citations or markdown, units and big numbers in words."""
    units = UNITS[lang]
    text = re.sub(r"\s*\[\d+\]", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url) → label
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?m)^\s*(#+|[-*•]|\d+\.)\s+", "", text)  # headings and list marks
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"\s*[~≈]\s*(?=\d)", " khoảng " if lang == "vi" else " about ", text)
    text = THOUSANDS[lang].sub(lambda m: re.sub(r"[.,]", "", m[0]), text)
    text = UNIT.sub(lambda m: " " + units.get(m[1] or m[2], units["đ"]), text)
    if lang == "vi":
        text = CLOCK.sub(
            lambda m: f"{int(m[1])} giờ" + (f" {int(m[2])}" if m[2] != "00" else ""), text
        )
    text = re.sub(r"\s*/\s*(?=[^\W\d_])", " mỗi " if lang == "vi" else " per ", text)  # đồng/kWh
    return re.sub(r"[ \t]+", " ", re.sub(r"\(\s+", "(", text)).strip()


def pieces(text: str) -> list[str]:
    """Whole sentences in pieces voiced one by one: the first short, the rest up to REST."""
    out: list[str] = []
    total = 0
    for s in filter(None, SENTENCE.split(text)):
        s = s[:MAX_SPOKEN]
        if total + len(s) > MAX_SPOKEN and out:
            break
        total += len(s)
        if out and len(out[-1]) + len(s) < (FIRST if len(out) == 1 else REST):
            out[-1] += (" " if out[-1][-1] in ".!?…;:," else ". ") + s  # a list line pauses too
        else:
            out.append(s)
    return out


L3_KBPS = {
    1: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def frames(mp3: bytes) -> bytes:
    """The MP3's audio frames alone: without its ID3 tag, and without the Xing/Info frame that gives
    the length of this piece only. Pieces stripped so play one after another as one stream."""
    at = 0
    if mp3[:3] == b"ID3" and len(mp3) >= 10:
        size = sum((b & 0x7F) << (7 * (3 - i)) for i, b in enumerate(mp3[6:10]))
        at = 10 + size + (10 if mp3[5] & 0x10 else 0)
    head = mp3[at : at + 4]
    if len(head) == 4 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:
        version, layer = (head[1] >> 3) & 3, (head[1] >> 1) & 3
        kbps, rate = (head[2] >> 4), (head[2] >> 2) & 3
        if layer == 1 and version != 1 and 0 < kbps < 15 and rate < 3:  # Layer III
            length = (144 if version == 3 else 72) * L3_KBPS[1 if version == 3 else 2][kbps] * 1000
            length = length // RATES[version][rate] + ((head[2] >> 1) & 1)
            if b"Xing" in mp3[at : at + 40] or b"Info" in mp3[at : at + 40]:
                at += length
    return mp3[at:]


async def _voice(client: httpx.AsyncClient, text: str) -> bytes:
    try:
        r = await client.post(
            "/audio/speech",
            json={
                "model": settings.astralx_tts_model,
                "input": text,
                "voice": settings.astralx_tts_voice,
                "response_format": "mp3",
            },
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("speech failed: %r", e)
        raise VoiceUnavailableError from e
    return frames(r.content)


async def speech(text: str, lang: str) -> AsyncIterator[bytes]:
    """Text to speech (AstralX, voice speaker_05) as one MP3 stream, a sentence or a few at a time.
    AstralX does not stream and voices one request at a time, so the next piece is voiced while the
    one before it is sent and played: the voice starts after the first sentence, not the answer."""
    parts = pieces(spoken(text, lang))
    if not parts:
        return
    async with _client() as client:
        nxt = asyncio.create_task(_voice(client, parts[0]))
        try:
            for i in range(len(parts)):
                audio = await nxt
                if i + 1 < len(parts):
                    nxt = asyncio.create_task(_voice(client, parts[i + 1]))
                yield audio
        finally:
            nxt.cancel()


def _voice_name() -> str:
    return f"{settings.astralx_tts_model}/{settings.astralx_tts_voice}"


async def kept_speech(s: AsyncSession, message_id, lang: str) -> bytes | None:
    """The answer as it was read aloud before, in this language and voice."""
    return await s.scalar(
        select(Speech.audio).where(
            Speech.message_id == message_id, Speech.lang == lang, Speech.voice == _voice_name()
        )
    )


async def keep_speech(message_id, lang: str, audio: bytes) -> None:
    """Keeps a reading that went to its end; a failure to keep it only costs a new reading."""
    try:
        async with SessionLocal() as s:
            await s.execute(
                insert(Speech)
                .values(message_id=message_id, lang=lang, voice=_voice_name(), audio=audio)
                .on_conflict_do_nothing()
            )
            await s.commit()
    except SQLAlchemyError as e:
        log.warning("speech not kept: %r", e)


async def prune_speech(s: AsyncSession) -> None:
    await s.execute(delete(Speech).where(Speech.created_at < func.now() - KEPT_FOR))
