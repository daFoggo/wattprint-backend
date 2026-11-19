import logging

import httpx

from app.config import settings

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


async def speech(text: str) -> bytes:
    """Text to speech (AstralX, voice speaker_05): MP3."""
    async with _client() as client:
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
    return r.content
