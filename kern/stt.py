"""Spracheingabe. Heute ElevenLabs Scribe — spaeter nur diese Datei tauschen."""

from __future__ import annotations

import httpx

from kern.config import ELEVENLABS_API_KEY


def transcribe(audio: bytes, *, mime: str = "audio/webm", name: str = "turn.webm") -> str:
    if not audio or len(audio) < 800 or not ELEVENLABS_API_KEY:
        return ""
    r = httpx.post(
        "https://api.elevenlabs.io/v1/speech-to-text",
        headers={"xi-api-key": ELEVENLABS_API_KEY},
        data={
            "model_id": "scribe_v2",
            "language_code": "de",
            "tag_audio_events": "false",
        },
        files={"file": (name, audio, mime or "application/octet-stream")},
        timeout=8.0,
    )
    if r.status_code != 200:
        raise RuntimeError(f"stt_http_{r.status_code}")
    data = r.json()
    text = " ".join(str(data.get("text") or "").split()).strip()
    if any(0x0400 <= ord(c) < 0x0500 for c in text):
        return ""
    return text


def bereit() -> bool:
    return bool(ELEVENLABS_API_KEY)
