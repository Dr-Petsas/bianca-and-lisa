"""Sprech-Schnittstelle. Heute ElevenLabs — später nur diese Datei gegen lokales TTS tauschen."""

from __future__ import annotations

import array
import hashlib
import re
import struct
import time
from pathlib import Path
from typing import Protocol

import httpx

from kern.config import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_TTS_MODEL,
    ELEVENLABS_VOICE_ID,
    TTS_BASE,
    TTS_VOICE,
)

# Aussprache-Umschrift NUR fuer den Mund (Chef 27.08.2026: "Michael Petsas
# wird englisch ausgesprochen"): ElevenLabs liest englisch klingende Vornamen
# trotz language_code=de gern englisch ("Maikl"). Der Bindestrich erzwingt die
# deutsche Silbentrennung. Logs, Kalender und Transkript behalten die echte
# Schreibweise — nur der Text an die Stimme wird umgeschrieben.
_AUSSPRACHE = (
    (re.compile(r"\bMichael\b"), "Micha-el"),
    (re.compile(r"\bDavid\b"), "Dah-vid"),
)

# Lautheit — exakt das Demo-Clara-Rezept (Chef 27.08.2026 zweite Runde:
# "mach die audios genau so laut wie demo clara"). Demo Clara
# (worker_speech_out._demo_pcm_pegel) hebt NUR leise Sätze an: Ziel 0,82
# der Vollaussteuerung, Faktor höchstens 1,8, nie absenken, Stille bleibt
# Stille. Unser erster Wurf (Ziel 0,92, Faktor bis 6) riss leise Füller um
# bis zu +15 dB hoch, während normale Sätze unverändert blieben — DAS waren
# die verbliebenen Lautstärke-Schwankungen zwischen den Äußerungen.
ZIEL_PEGEL = 0.82          # Spitze relativ zur Vollaussteuerung (Demo-Parität)
MAX_ANHEBUNG = 1.8         # Demo Clara: "Nie übersteuern — klang wie runtergesampelt"
STILLE_SPITZE = 80         # int16-Spitzen darunter sind Atmen/Rauschen: nicht anfassen
PCM_RATE = 24000

_CACHE: dict[str, bytes] = {}
_CACHE_ORD: list[str] = []
_CLIENT: httpx.Client | None = None
_LOKAL_CLIENT: httpx.Client | None = None

# Platten-Cache NUR fuer statische Saetze (Fueller, Begruessungen — nie
# Patientendaten): die aendern sich nie, ein Neustart soll sie nicht neu
# synthetisieren (Chef 28.08.2026). Liegt unter .data/ und damit im
# Container-Volume bzw. gitignored.
_DISK_DIR = Path(__file__).resolve().parents[1] / ".data" / "tts-cache"

# Stimme pro PROZESS: Lisa und Bianca laufen als getrennte Dienste — Bianca
# setzt beim Start ihre eigene Voice-ID (kern.config.BIANCA_VOICE_ID) und
# ihren lokalen Stimmnamen ("bianca" = Referenz im TTS-Container).
_VOICE_ID = ELEVENLABS_VOICE_ID
_VOICE_NAME = TTS_VOICE or "lisa"


def set_voice(voice_id: str, name: str = "") -> None:
    global _VOICE_ID, _VOICE_NAME
    sauber = " ".join(str(voice_id or "").split()).strip()
    if sauber:
        _VOICE_ID = sauber
    sauber_name = " ".join(str(name or "").split()).strip().lower()
    if sauber_name:
        _VOICE_NAME = sauber_name


def _client() -> httpx.Client:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(
            timeout=httpx.Timeout(8.0, connect=2.0),
            headers={"xi-api-key": ELEVENLABS_API_KEY},
        )
    return _CLIENT


def _lokal_client() -> httpx.Client:
    global _LOKAL_CLIENT
    if _LOKAL_CLIENT is None:
        # Read-Timeout bewusst grosszuegig: nach Kaltstart oder bei langen
        # Saetzen braucht die lokale Synthese ein paar Sekunden.
        _LOKAL_CLIENT = httpx.Client(timeout=httpx.Timeout(30.0, connect=2.0))
    return _LOKAL_CLIENT


def _normalisieren(text: str) -> str:
    sauber = " ".join(str(text or "").split()).strip()
    for cre, ersatz in _AUSSPRACHE:
        sauber = cre.sub(ersatz, sauber)
    return sauber


def _ram_merken(schluessel: str, blob: bytes) -> None:
    _CACHE[schluessel] = blob
    _CACHE_ORD.append(schluessel)
    if len(_CACHE_ORD) > 48:
        _CACHE.pop(_CACHE_ORD.pop(0), None)


def pcm16_wav(pcm: bytes, *, rate: int = PCM_RATE) -> bytes:
    """s16le mono → WAV. Pegel wie Demo Clara: nur leise Sätze anheben
    (Ziel 0,82 FS, Faktor max. 1,8), nie absenken, nie kappen."""
    n = len(pcm) // 2
    if n <= 0:
        return b""
    samples = array.array("h")
    samples.frombytes(pcm[: n * 2])
    spitze = max(1, max(abs(s) for s in samples))
    gain = min(MAX_ANHEBUNG, (ZIEL_PEGEL * 32767.0) / spitze)
    if spitze < STILLE_SPITZE or gain <= 1.02:
        # Stille/Atmen nie hochziehen; Lautes unverändert durchreichen.
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
        sauber = _normalisieren(text)
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
        _ram_merken(schluessel, blob)
        return blob


class LokalTts:
    """Spricht den TTS-Container auf der 5090 (tts_serve/, Vertrag api.md).

    In der Testphase gibt es bewusst KEINEN ElevenLabs-Rueckfall (Chef
    27.08.2026): schlaegt der Container fehl, fliegt ein RuntimeError —
    Dienst.stimme() faengt ihn, der Zug erscheint im Dock ohne Audio und
    der Fehler ist sofort hoerbar statt still kaschiert.
    """

    name = "lokal"

    def speak(self, text: str) -> bytes:
        sauber = _normalisieren(text)
        if not sauber:
            return b""
        schluessel = f"lokal|{_VOICE_NAME}|{sauber}"
        hit = _CACHE.get(schluessel)
        if hit:
            return hit
        r = _lokal_client().post(
            f"{TTS_BASE}/speak",
            json={"text": sauber[:400], "voice": _VOICE_NAME},
        )
        if r.status_code != 200:
            raise RuntimeError(f"tts_lokal_http_{r.status_code}")
        raw = r.content
        if not raw:
            return b""
        # Container liefert rohes PCM16/24k — dieselbe Pegel-Schicht wie beim
        # ElevenLabs-Pfad, damit lokale Zuege gleich laut klingen.
        blob = pcm16_wav(raw)
        _ram_merken(schluessel, blob)
        return blob


def engine() -> TtsEngine:
    if TTS_BASE:
        return LokalTts()
    return ElevenLabsTts()


def bereit() -> bool:
    return bool(TTS_BASE or ELEVENLABS_API_KEY)


def modell_info() -> str:
    """Fuer die /health-Anzeige: was spricht hier gerade?"""
    return TTS_BASE if TTS_BASE else ELEVENLABS_TTS_MODEL


_ENGINE_ANZEIGE: tuple[float, str] | None = None


def engine_anzeige() -> str:
    """Lesbarer Stimm-Name fuers Dock: 'Chatterbox (lokal)', 'CosyVoice
    (lokal)' oder 'ElevenLabs'. Fragt den Container-Health nach der Engine
    (60 s gecacht, kurzer Timeout) — so zeigt das Dock nach einem Wechsel
    automatisch das richtige Modell."""
    global _ENGINE_ANZEIGE
    if not TTS_BASE:
        return "ElevenLabs"
    jetzt = time.monotonic()
    if _ENGINE_ANZEIGE and jetzt - _ENGINE_ANZEIGE[0] < 60.0:
        return _ENGINE_ANZEIGE[1]
    anzeige = "lokal — Container antwortet nicht"
    try:
        r = _lokal_client().get(f"{TTS_BASE}/health", timeout=2.0)
        if r.status_code == 200:
            eng = str((r.json() or {}).get("engine") or "").strip().lower()
            if eng == "chatterbox":
                anzeige = "Chatterbox (lokal)"
            elif eng.startswith("cosy"):
                anzeige = "CosyVoice (lokal)"
            elif eng:
                anzeige = f"{eng} (lokal)"
    except Exception:
        pass
    _ENGINE_ANZEIGE = (jetzt, anzeige)
    return anzeige


def speak_dauerhaft(text: str) -> bytes:
    """Wie engine().speak(), aber mit Platten-Cache unter .data/tts-cache.

    NUR fuer statische Saetze ohne Patientenbezug (Fueller, Begruessungen):
    einmal gerendert, ueberlebt Neustarts — der Dienststart braucht dann
    Millisekunden statt 18 Synthesen. Gespraechs-Antworten laufen weiter
    ueber speak() und landen NIE auf der Platte.
    """
    if not bereit():
        return b""
    sauber = _normalisieren(text)
    if not sauber:
        return b""
    eng = engine()
    if eng.name == "lokal":
        schluessel = f"lokal|{_VOICE_NAME}|{sauber}"
    else:
        schluessel = f"{_VOICE_ID}|{sauber}"
    hit = _CACHE.get(schluessel)
    if hit:
        return hit
    datei = _DISK_DIR / (hashlib.sha1(schluessel.encode("utf-8")).hexdigest() + ".wav")
    try:
        if datei.is_file():
            blob = datei.read_bytes()
            if blob:
                _ram_merken(schluessel, blob)
                return blob
    except OSError:
        pass
    blob = eng.speak(sauber)
    if blob:
        try:
            _DISK_DIR.mkdir(parents=True, exist_ok=True)
            datei.write_bytes(blob)
        except OSError:
            pass
    return blob


def warm(text: str) -> None:
    """Startup-Vorwaermen statischer Saetze — dauerhaft gecacht."""
    try:
        speak_dauerhaft(text)
    except Exception:
        pass
