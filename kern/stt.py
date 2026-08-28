"""Spracheingabe. STT_BASE gesetzt = lokaler Conformer-Container (5090),
OHNE ElevenLabs-Rueckfall (Chef 28.08.2026: "es geht nichts mehr zu
elevenlabs"). Leer = ElevenLabs Scribe wie frueher."""

from __future__ import annotations

import httpx

from kern.config import ELEVENLABS_API_KEY, STT_BASE

_CLIENT: httpx.Client | None = None


def _client() -> httpx.Client:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(timeout=httpx.Timeout(15.0, connect=3.0))
    return _CLIENT


def _sauber(text) -> str:
    text = " ".join(str(text or "").split()).strip()
    # Nicht-lateinische Ausreisser (kyrillische Halluzinationen) verwerfen.
    if any(0x0400 <= ord(c) < 0x0500 for c in text):
        return ""
    return text


def _lokal(audio: bytes, *, mime: str, name: str) -> str:
    r = _client().post(
        f"{STT_BASE}/transcribe",
        files={"file": (name, audio, mime or "application/octet-stream")},
    )
    if r.status_code != 200:
        raise RuntimeError(f"stt_lokal_http_{r.status_code}")
    return _sauber(r.json().get("text"))


def transcribe(audio: bytes, *, mime: str = "audio/webm", name: str = "turn.webm") -> str:
    if not audio or len(audio) < 800:
        return ""
    if STT_BASE:
        return _lokal(audio, mime=mime, name=name)
    if not ELEVENLABS_API_KEY:
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
    return _sauber(r.json().get("text"))


def bereit() -> bool:
    return bool(STT_BASE or ELEVENLABS_API_KEY)
