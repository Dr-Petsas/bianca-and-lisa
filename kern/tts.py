"""Sprech-Schnittstelle. Heute ElevenLabs — später nur diese Datei gegen lokales TTS tauschen."""

from __future__ import annotations

import array
import struct
from typing import Protocol

import httpx

from kern.config import ELEVENLABS_API_KEY, ELEVENLABS_TTS_MODEL, ELEVENLABS_VOICE_ID

# Demo-Clara spricht PCM nahe Vollaussteuerung. Lisa lag deutlich darunter.
GAIN = 3.2
PCM_RATE = 24000

_CACHE: dict[str, bytes] = {}
_CACHE_ORD: list[str] = []
_CLIENT: httpx.Client | None = None

# Stimme pro PROZESS: Lisa und Bianca laufen als getrennte Dienste — Bianca
# setzt beim Start ihre eigene Voice-ID (kern.config.BIANCA_VOICE_ID).
_VOICE_ID = ELEVENLABS_VOICE_ID


def set_voice(voice_id: str) -> None:
    global _VOICE_ID
    sauber = " ".join(str(voice_id or "").split()).strip()
    if sauber:
        _VOICE_ID = sauber


def _client() -> httpx.Client:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(
            timeout=httpx.Timeout(8.0, connect=2.0),
            headers={"xi-api-key": ELEVENLABS_API_KEY},
        )
    return _CLIENT


def pcm16_wav(pcm: bytes, *, rate: int = PCM_RATE, gain: float = GAIN) -> bytes:
    """s16le mono → WAV, laut wie Demo-Clara (Gain + Soft-Clip)."""
    n = len(pcm) // 2
    if n <= 0:
        return b""
    samples = array.array("h")
    samples.frombytes(pcm[: n * 2])
    boosted = array.array("h")
    lim = 32767
    for s in samples:
        v = int(s * gain)
        if v > lim:
            v = lim
        elif v < -lim:
            v = -lim
        boosted.append(v)
    data = boosted.tobytes()
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(data),
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        rate,
        rate * 2,
        2,
        16,
        b"data",
        len(data),
    )
    return header + data


def _ist_mp3(blob: bytes) -> bool:
    return bool(blob) and (blob[:3] == b"ID3" or blob[:2] in (b"\xff\xfb", b"\xff\xfa", b"\xff\xf3", b"\xff\xf2"))


class TtsEngine(Protocol):
    name: str

    def speak(self, text: str) -> bytes: ...


class ElevenLabsTts:
    name = "elevenlabs"

    def speak(self, text: str) -> bytes:
        sauber = " ".join(str(text or "").split()).strip()
        if not sauber or not ELEVENLABS_API_KEY:
            return b""
        schluessel = f"{_VOICE_ID}|{sauber}"
        hit = _CACHE.get(schluessel)
        if hit:
            return hit
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{_VOICE_ID}/stream"
        r = _client().post(
            url,
            params={
                "optimize_streaming_latency": "3",
                "output_format": "pcm_24000",
            },
            headers={"Accept": "application/octet-stream", "Content-Type": "application/json"},
            json={
                "text": sauber[:400],
                "model_id": ELEVENLABS_TTS_MODEL,
                "voice_settings": {
                    "stability": 0.45,
                    "similarity_boost": 0.85,
                    "use_speaker_boost": True,
                },
            },
        )
        if r.status_code != 200:
            raise RuntimeError(f"elevenlabs_http_{r.status_code}")
        raw = r.content
        if not raw:
            return b""
        if _ist_mp3(raw) or raw[:4] == b"RIFF":
            blob = raw
        else:
            blob = pcm16_wav(raw)
        _CACHE[schluessel] = blob
        _CACHE_ORD.append(schluessel)
        if len(_CACHE_ORD) > 48:
            _CACHE.pop(_CACHE_ORD.pop(0), None)
        return blob


def engine() -> ElevenLabsTts:
    return ElevenLabsTts()


def bereit() -> bool:
    return bool(ELEVENLABS_API_KEY)


def warm(text: str) -> None:
    if not bereit():
        return
    try:
        engine().speak(text)
    except Exception:
        pass
