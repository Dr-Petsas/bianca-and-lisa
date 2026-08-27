"""Sprech-Schnittstelle. Heute ElevenLabs — später nur diese Datei gegen lokales TTS tauschen."""

from __future__ import annotations

import array
import re
import struct
from typing import Protocol

import httpx

from kern.config import ELEVENLABS_API_KEY, ELEVENLABS_TTS_MODEL, ELEVENLABS_VOICE_ID

# Aussprache-Umschrift NUR fuer den Mund (Chef 27.08.2026: "Michael Petsas
# wird englisch ausgesprochen"): ElevenLabs liest englisch klingende Vornamen
# trotz language_code=de gern englisch ("Maikl"). Der Bindestrich erzwingt die
# deutsche Silbentrennung. Logs, Kalender und Transkript behalten die echte
# Schreibweise — nur der Text an die Stimme wird umgeschrieben.
_AUSSPRACHE = (
    (re.compile(r"\bMichael\b"), "Micha-el"),
    (re.compile(r"\bDavid\b"), "Dah-vid"),
)

# Lautheit (Chef 27.08.2026: "Lautstärke schwankt, wie ein Kompressor"):
# Der alte feste Faktor 3,2 mit hartem Kappen übersteuerte normale Sprachpegel
# permanent — das klang wie ein einsetzender Limiter. Jetzt wird JEDE Äußerung
# auf denselben Spitzenpegel normalisiert: leise ElevenLabs-Ausgaben werden
# angehoben (max. Faktor 6), laute bleiben — nichts wird mehr gekappt.
ZIEL_PEGEL = 0.92          # Spitze relativ zur Vollaussteuerung
MAX_ANHEBUNG = 6.0
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


def pcm16_wav(pcm: bytes, *, rate: int = PCM_RATE) -> bytes:
    """s16le mono → WAV, auf einheitlichen Spitzenpegel normalisiert (kein Clipping)."""
    n = len(pcm) // 2
    if n <= 0:
        return b""
    samples = array.array("h")
    samples.frombytes(pcm[: n * 2])
    spitze = max(1, max(abs(s) for s in samples))
    gain = min(MAX_ANHEBUNG, (ZIEL_PEGEL * 32767.0) / spitze)
    if gain <= 1.02:
        # Schon laut genug — Originalbytes durchreichen, kein Umrechnen.
        data = samples.tobytes()
    else:
        boosted = array.array("h", bytes(len(samples) * 2))
        for i, s in enumerate(samples):
            boosted[i] = int(s * gain)
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
        for cre, ersatz in _AUSSPRACHE:
            sauber = cre.sub(ersatz, sauber)
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
                # Deutsch festnageln (Chef 27.08.: "english glitches") — nur
                # Turbo/Flash v2.5+ kennen den Parameter, multilingual_v2 nicht.
                **({"language_code": "de"} if ("v2_5" in ELEVENLABS_TTS_MODEL or "_v3" in ELEVENLABS_TTS_MODEL) else {}),
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
