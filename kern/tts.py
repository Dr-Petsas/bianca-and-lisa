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
    TTS_STREAM,
    TTS_VOICE,
)

# Aussprache-Umschrift NUR fuer den Mund (Chef 27.08.2026: "Michael Petsas
# wird englisch ausgesprochen"): ElevenLabs liest englisch klingende Vornamen
# trotz language_code=de gern englisch ("Maikl"). Der Bindestrich erzwingt die
# deutsche Silbentrennung. Logs, Kalender und Transkript behalten die echte
# Schreibweise — nur der Text an die Stimme wird umgeschrieben.
_AUSSPRACHE = (
    # Englisch klingende Vornamen — Qwen/ElevenLabs lesen sie sonst englisch.
    # Bindestrich erzwingt deutsche Silben; Logs behalten die echte Schreibweise.
    (re.compile(r"\bMichael\b", re.I), "Micha-el"),
    (re.compile(r"\bDavid\b", re.I), "Da-wid"),
    (re.compile(r"\bPeter\b", re.I), "Peh-ter"),
    (re.compile(r"\bJohn\b", re.I), "Dschon"),
    (re.compile(r"\bSteve\b", re.I), "Stief"),
    (re.compile(r"\bSteven\b", re.I), "Steh-wen"),
    (re.compile(r"\bStephen\b", re.I), "Steh-fen"),
    (re.compile(r"\bAndrew\b", re.I), "Än-dru"),
    (re.compile(r"\bJames\b", re.I), "Dschehms"),
    (re.compile(r"\bWilliam\b", re.I), "Will-jem"),
    (re.compile(r"\bGeorge\b", re.I), "Schorsch"),
    (re.compile(r"\bKevin\b", re.I), "Keh-win"),
    (re.compile(r"\bBrian\b", re.I), "Brai-en"),
    (re.compile(r"\bDaniel\b", re.I), "Dah-ni-el"),
    (re.compile(r"\bChristopher\b", re.I), "Kris-to-fer"),
    (re.compile(r"\bChris\b", re.I), "Kriss"),
    (re.compile(r"\bJennifer\b", re.I), "Dschen-ni-fer"),
    (re.compile(r"\bJessica\b", re.I), "Jess-i-ka"),
    (re.compile(r"\bSarah\b", re.I), "Sah-ra"),
    (re.compile(r"\bMichelle\b", re.I), "Mi-schell"),
    (re.compile(r"\bMike\b", re.I), "Maik"),
    (re.compile(r"\bJack\b", re.I), "Dschäck"),
    (re.compile(r"\bJoseph\b", re.I), "Joh-sef"),
    (re.compile(r"\bJoe\b", re.I), "Dscho"),
    (re.compile(r"\bJonathan\b", re.I), "Joh-na-tan"),
    (re.compile(r"\bNathan\b", re.I), "Nah-tan"),
    (re.compile(r"\bJustin\b", re.I), "Juss-tin"),
    (re.compile(r"\bJason\b", re.I), "Jeh-son"),
    (re.compile(r"\bRyan\b", re.I), "Rai-en"),
    (re.compile(r"\bSean\b", re.I), "Schohn"),
    (re.compile(r"\bRichard\b", re.I), "Ri-chard"),
    (re.compile(r"\bThomas\b", re.I), "Toh-mas"),
    (re.compile(r"\bBenjamin\b", re.I), "Ben-ja-min"),
    (re.compile(r"\bMatthew\b", re.I), "Mät-ju"),
    (re.compile(r"\bAnthony\b", re.I), "Än-to-ni"),
    (re.compile(r"\bCharles\b", re.I), "Tschahls"),
    (re.compile(r"\bHenry\b", re.I), "Henn-ri"),
    (re.compile(r"\bJeffrey\b", re.I), "Dscheff-ri"),
    (re.compile(r"\bAmy\b", re.I), "Eh-mi"),
    (re.compile(r"\bKate\b", re.I), "Keht"),
    (re.compile(r"\bStephanie\b", re.I), "Steh-fa-ni"),
    (re.compile(r"\bEmily\b", re.I), "Eh-mi-li"),
    (re.compile(r"\bPatrick\b", re.I), "Patt-rick"),
    (re.compile(r"\bPetsas\b", re.I), "Pet-sas"),
    (re.compile(r"\bPatrikis\b", re.I), "Pa-tri-kis"),
    (re.compile(r"\bNikolaou\b", re.I), "Ni-ko-la-u"),
)

# Lautheit — RMS-Angleichung auf Clara-/ElevenLabs-Niveau (28.08.2026).
# Das Demo-Clara-Peak-Rezept (Ziel 0,82 FS, max 1,8, nie absenken) macht
# ElevenLabs laut, weil speaker_boost das Audio schon komprimiert. Qwen3
# hat hohe Spitzen bei leiser Sprache (gemessen: Peak 0,68 / RMS 0,08) —
# ein Peak-Deckel auf den Gain hielt Bianca bei −19 dBFS, Clara liegt bei
# etwa −13. Deshalb: Gain NUR aus dem Sprach-RMS, Peaks danach kappen.
# Gleicher RMS je Satz = kein Pumpen (Chef 28.08.).
ZIEL_RMS = 0.22            # Sprach-RMS ~ −13 dBFS, wie Clara Demo/V7 am Telefon
PEAK_DECKEL = 0.95         # nach dem Gain hart kappen — kein Klirren
MIN_GAIN = 0.5             # nie mehr als halbieren ...
MAX_GAIN = 5.0             # Qwen-leise Saetze brauchen mehr als 4x
AKTIV_SCHWELLE = 300       # |Sample| darunter = Pause/Atmen, zählt nicht zur Lautheit
MIN_AKTIV_SAMPLES = 1200   # unter ~50 ms Sprachanteil gilt das Stück als Stille
PCM_RATE = 24000

# Häppchen-Fahrplan im Stream (28.08.2026, "dramatisch schneller"): das erste
# Stück klein — der Anrufer hört nach dem ersten Container-Chunk sofort etwas.
# Danach darf jedes Stück höchstens so groß werden wie alles bisher Gesendete
# (Verdopplung) bis zur Zielgröße: Stück k wird erst fällig, wenn die Stücke
# davor noch spielen — die Kette bleibt gapless, solange der Container
# schneller als halbe Echtzeit rendert (CosyVoice-Turbo ~0,3, Chatterbox
# ~0,45). Der alte feste Start bei 1,2 s hängte den ersten Ton eine knappe
# Sekunde hinter den ersten Chunk ("kackelahm", Chef 28.08.2026).
HAEPPCHEN_START_S = 0.5
HAEPPCHEN_MAX_S = 3.2

# Naht-Regel (Vorfall 28.08.2026 "Artefakte/Genuschel"): geschnitten wird NUR
# in Sprechpausen, nie mitten im Wort. Der stumpfe Byte-Schnitt an der
# Fahrplan-Schwelle legte die Naht (2-ms-Rampen + eigenständiges Decode/
# Resampling je Häppchen im Dock) QUER durch Wörter — alle 0,5-2 s ein
# verwaschener Übergang, live als Genuschel gehört. Ein Fenster gilt als
# Pause, wenn sein RMS unter PAUSE_RMS liegt (deckt Chatterbox- wie
# CosyVoice-Renderstille); findet sich eine Extra-Sekunde lang keine Pause,
# schneidet der Notschnitt an der leisesten bekannten Stelle.
PAUSE_RMS = 300            # Fenster-RMS darunter = Sprechpause (wie AKTIV_SCHWELLE)
PAUSE_FENSTER = 720        # 30 ms bei 24 kHz
PAUSE_SCHRITT = 360        # 15 ms Raster
NOT_SCHNITT_EXTRA = PCM_RATE * 2  # 1 s über Soll ohne Pause => Notschnitt

_CACHE: dict[str, bytes] = {}
_CACHE_ORD: list[str] = []
# Gepinnter Bereich fuer dauerhaft gewarmte Saetze (Fueller, Begruessungen,
# feste Maschinen-Fragen): sie duerfen NICHT von dynamischen Antworten aus
# dem 48er-LRU verdraengt werden — sonst spricht die Maschine mitten im
# Gespraech ploetzlich wieder mit voller Synthese-Latenz (28.08.2026).
_FEST: dict[str, bytes] = {}
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


def _ram_merken(schluessel: str, blob: bytes, *, fest: bool = False) -> None:
    if fest:
        _FEST[schluessel] = blob
        return
    _CACHE[schluessel] = blob
    _CACHE_ORD.append(schluessel)
    if len(_CACHE_ORD) > 48:
        _CACHE.pop(_CACHE_ORD.pop(0), None)


def _ram_holen(schluessel: str) -> bytes | None:
    return _FEST.get(schluessel) or _CACHE.get(schluessel)


def _lokal_schluessel(sauber: str) -> str:
    # TTS_BASE gehoert in den Schluessel: Chatterbox (:8210) und CosyVoice
    # (:8211) sind beide "lokal" — ohne Basis im Key wuerde ein Engine-Wechsel
    # alte Fueller aus dem Cache der anderen Stimme abspielen.
    return f"lokal|{TTS_BASE}|{_VOICE_NAME}|{sauber}"


def _gain_oder_none(samples: "array.array") -> float | None:
    """Lautheits-Gain für ein PCM-Stück — None, wenn zu wenig Sprache drin
    ist (Stille/Atmen), dann wird nichts angefasst."""
    quad = 0
    aktiv = 0
    for s in samples:
        a = abs(s)
        if a >= AKTIV_SCHWELLE:
            quad += s * s
            aktiv += 1
    if aktiv < MIN_AKTIV_SAMPLES:
        return None
    rms = (quad / aktiv) ** 0.5
    # Peak klemmt den Gain NICHT: sonst bleibt Qwen leise (Clara-Vergleich
    # 28.08.2026). Spitzen werden in _skaliert_bytes gekappt.
    return max(MIN_GAIN, min(MAX_GAIN, (ZIEL_RMS * 32767.0) / max(rms, 1.0)))


def _skaliert_bytes(samples: "array.array", gain: float) -> bytes:
    limit = int(PEAK_DECKEL * 32767.0)
    if 0.98 <= gain <= 1.02 and max((abs(s) for s in samples), default=0) <= limit:
        return samples.tobytes()
    skaliert = array.array("h", bytes(len(samples) * 2))
    for i, s in enumerate(samples):
        v = int(s * gain)
        if v > limit:
            v = limit
        elif v < -limit:
            v = -limit
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        skaliert[i] = v
    return skaliert.tobytes()


class _PausenSpur:
    """Inkrementelle Pausen-Suche im wachsenden PCM-Puffer (16 Bit mono).

    scan() vermisst nur den Zuwachs seit dem letzten Aufruf (30-ms-Fenster im
    15-ms-Raster); pausen_schnitt() liefert die späteste Sprechpause ab einer
    Mindestgröße als sample-geraden Byte-Offset, not_schnitt() die leiseste
    bekannte Stelle für den Notfall ohne echte Pause."""

    def __init__(self) -> None:
        self.fenster: list[tuple[int, float]] = []  # (Mitte als Byte-Offset, RMS)
        self.ab_sample = 0

    def scan(self, puffer: bytes) -> None:
        n = len(puffer) // 2
        f = self.ab_sample
        if f + PAUSE_FENSTER > n:
            return
        roh = array.array("h", puffer[f * 2 : n * 2])
        while f + PAUSE_FENSTER <= n:
            rel = f - self.ab_sample
            quad = 0
            for s in roh[rel : rel + PAUSE_FENSTER]:
                quad += s * s
            rms = (quad / PAUSE_FENSTER) ** 0.5
            self.fenster.append(((f + PAUSE_FENSTER // 2) * 2, rms))
            f += PAUSE_SCHRITT
        self.ab_sample = f

    def pausen_schnitt(self, min_ab: int) -> int:
        for mitte, rms in reversed(self.fenster):
            if mitte < min_ab:
                break
            if rms < PAUSE_RMS:
                return mitte
        return -1

    def not_schnitt(self, min_ab: int) -> int:
        """Leiseste bekannte Stelle ab min_ab — bei (fast) gleich leisen
        gewinnt die SPAETESTE: das Stueck bleibt nah an der Sollgroesse."""
        beste, beste_rms = -1, None
        for mitte, rms in reversed(self.fenster):
            if mitte < min_ab:
                break
            if beste_rms is None or rms < beste_rms * 0.98:
                beste, beste_rms = mitte, rms
        return beste

    def verschieben(self, schnitt_bytes: int) -> None:
        """Nach einem Schnitt: Offsets auf den Restpuffer umrechnen."""
        self.fenster = [(m - schnitt_bytes, r) for m, r in self.fenster if m > schnitt_bytes]
        self.ab_sample = max(0, self.ab_sample - schnitt_bytes // 2)


def _haeppchen_wav(stueck: bytes, gain: float | None) -> tuple[bytes, float | None]:
    """Ein Stream-Stück -> fertiges WAV-Häppchen + (ggf. neu bestimmter) Gain.

    Der Äußerungs-Gain wird beim ersten sprach-aktiven Stück bestimmt und
    danach festgehalten; pro Stück schützt zusätzlich der Peak-Deckel vor
    Clipping (spätere Stücke können lauter sein als das erste). 2-ms-Rampen
    an den Rändern schlucken Klicks, falls der Player doch eine Lücke lässt."""
    samples = array.array("h")
    samples.frombytes(stueck[: (len(stueck) // 2) * 2])
    if not samples:
        return b"", gain
    if gain is None:
        gain = _gain_oder_none(samples)
    eff = gain if gain is not None else 1.0
    # Peak wird in _skaliert_bytes gekappt, der Äußerungs-Gain bleibt.
    skaliert = array.array("h")
    skaliert.frombytes(_skaliert_bytes(samples, eff))
    rampe = min(48, len(skaliert) // 2)  # 2 ms bei 24 kHz
    for i in range(rampe):
        f = i / rampe
        skaliert[i] = int(skaliert[i] * f)
        skaliert[-1 - i] = int(skaliert[-1 - i] * f)
    data = skaliert.tobytes()
    return _wav_header(len(data), PCM_RATE) + data, gain


def _wav_header(data_len: int, rate: int) -> bytes:
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_len,
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
        data_len,
    )


def pcm16_wav(pcm: bytes, *, rate: int = PCM_RATE) -> bytes:
    """s16le mono → WAV. Jede Äußerung auf dieselbe Sprach-Lautheit ziehen:
    RMS über sprach-aktive Samples auf ZIEL_RMS (anheben UND absenken),
    Peak-Deckel gegen Klirren, Stille/Atmen bleibt unangetastet."""
    n = len(pcm) // 2
    if n <= 0:
        return b""
    samples = array.array("h")
    samples.frombytes(pcm[: n * 2])
    gain = _gain_oder_none(samples)
    data = _skaliert_bytes(samples, gain if gain is not None else 1.0)
    return _wav_header(len(data), rate) + data


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
        hit = _ram_holen(schluessel)
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
        schluessel = _lokal_schluessel(sauber)
        hit = _ram_holen(schluessel)
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

    def kann_stream(self) -> bool:
        """Chunk-Streaming nur, wenn der Container es im /health meldet
        (CosyVoice-Turbo: stream=true; Chatterbox: Feld fehlt => blocking)."""
        return TTS_STREAM and bool(_health_holen().get("stream"))

    def speak_stream(self, text: str):
        """Generator: abspielfertige WAV-Häppchen (~>=0,6 s) aus dem
        Chunk-Strom von /speak-stream — das erste kommt nach wenigen hundert
        Millisekunden, lange bevor die Äußerung fertig gerendert ist.

        Pegel: der Gain wird aus dem ERSTEN sprach-aktiven Häppchen bestimmt
        und für die ganze Äußerung festgehalten — sonst pumpt es zwischen
        den Häppchen derselben Antwort. Kein Cache: hier laufen nur
        dynamische Gesprächsantworten, nie Füller."""
        sauber = _normalisieren(text)
        if not sauber:
            return
        # Fahrplan: klein anfangen, verdoppelnd wachsen (HAEPPCHEN_START_S/
        # HAEPPCHEN_MAX_S oben) — jede Naht ist ein potenzielles Mini-Knacken,
        # also nur so viele Übergänge wie fürs Tempo nötig. Geschnitten wird
        # NUR in Sprechpausen (PAUSE_RMS): der stumpfe Byte-Schnitt legte die
        # Naht mitten in Wörter — live als Genuschel gehört (28.08.2026).
        # NIE mitten im 16-Bit-Sample: alle Offsets sind sample-gerade,
        # der Überhang bleibt im Puffer und geht dem nächsten Stück voran.
        start_bytes = int(HAEPPCHEN_START_S * PCM_RATE) * 2
        max_bytes = int(HAEPPCHEN_MAX_S * PCM_RATE) * 2
        min_bytes = start_bytes
        gesendet_bytes = 0
        gain: float | None = None
        puffer = b""
        spur = _PausenSpur()
        with _lokal_client().stream(
            "POST", f"{TTS_BASE}/speak-stream",
            json={"text": sauber[:1200], "voice": _VOICE_NAME},
        ) as r:
            if r.status_code != 200:
                raise RuntimeError(f"tts_lokal_stream_http_{r.status_code}")
            for chunk in r.iter_bytes():
                puffer += chunk
                if len(puffer) < min_bytes:
                    continue
                spur.scan(puffer)
                # Naht fruehestens ab ~60 % der Sollgroesse — eine Satzpause
                # kurz vor der Schwelle ist besser als ein Schnitt kurz danach.
                min_ab = (int(min_bytes * 0.6) // 2) * 2
                schnitt = spur.pausen_schnitt(min_ab)
                if schnitt < 0 and len(puffer) >= min_bytes + NOT_SCHNITT_EXTRA:
                    schnitt = spur.not_schnitt(min_ab)
                if schnitt <= 0:
                    continue
                stueck, puffer = puffer[:schnitt], puffer[schnitt:]
                spur.verschieben(schnitt)
                gesendet_bytes += len(stueck)
                min_bytes = min(max_bytes, max(gesendet_bytes, start_bytes))
                wav, gain = _haeppchen_wav(stueck, gain)
                if wav:
                    yield wav
        if puffer:
            wav, gain = _haeppchen_wav(puffer, gain)
            if wav:
                yield wav


def engine() -> TtsEngine:
    if TTS_BASE:
        return LokalTts()
    return ElevenLabsTts()


def im_cache(text: str) -> bool:
    """RAM-Cache-Blick fuer den Haeppchen-Entscheid in dienst.py: gewarmte
    Begruessungen und Fueller sollen EIN Block bleiben — ihr Cache-Key
    traegt den Gesamttext, ein Satz-Split wuerde ihn verfehlen."""
    sauber = _normalisieren(text)
    if not sauber:
        return False
    schluessel = _lokal_schluessel(sauber) if TTS_BASE else f"{_VOICE_ID}|{sauber}"
    return schluessel in _FEST or schluessel in _CACHE


def bereit() -> bool:
    return bool(TTS_BASE or ELEVENLABS_API_KEY)


def modell_info() -> str:
    """Fuer die /health-Anzeige: was spricht hier gerade?"""
    return TTS_BASE if TTS_BASE else ELEVENLABS_TTS_MODEL


_HEALTH: tuple[float, dict] | None = None


def _health_holen() -> dict:
    """Container-/health, 60 s gecacht — speist Dock-Anzeige und
    Stream-Faehigkeit, ohne den Container pro Zug zu belaestigen."""
    global _HEALTH
    if not TTS_BASE:
        return {}
    jetzt = time.monotonic()
    if _HEALTH and jetzt - _HEALTH[0] < 60.0:
        return _HEALTH[1]
    daten: dict = {}
    try:
        r = _lokal_client().get(f"{TTS_BASE}/health", timeout=2.0)
        if r.status_code == 200:
            daten = r.json() or {}
    except Exception:
        pass
    _HEALTH = (jetzt, daten)
    return daten


def engine_anzeige() -> str:
    """Lesbarer Stimm-Name fuers Dock: 'Chatterbox (lokal)', 'CosyVoice
    (lokal)' oder 'ElevenLabs'. Fragt den Container-Health nach der Engine
    (60 s gecacht, kurzer Timeout) — so zeigt das Dock nach einem Wechsel
    automatisch das richtige Modell."""
    if not TTS_BASE:
        return "ElevenLabs"
    eng = str(_health_holen().get("engine") or "").strip().lower()
    if eng == "chatterbox":
        return "Chatterbox (lokal)"
    if eng.startswith("cosy"):
        return "CosyVoice (lokal)"
    if eng in ("qwen3", "qwen"):
        return "Qwen3-TTS (lokal)"
    if eng:
        return f"{eng} (lokal)"
    return "lokal — Container antwortet nicht"


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
        schluessel = _lokal_schluessel(sauber)
    else:
        schluessel = f"{_VOICE_ID}|{sauber}"
    hit = _ram_holen(schluessel)
    if hit:
        return hit
    datei = _DISK_DIR / (hashlib.sha1(schluessel.encode("utf-8")).hexdigest() + ".wav")
    try:
        if datei.is_file():
            blob = datei.read_bytes()
            if blob:
                _ram_merken(schluessel, blob, fest=True)
                return blob
    except OSError:
        pass
    blob = eng.speak(sauber)
    if blob:
        _ram_merken(schluessel, blob, fest=True)
        try:
            _DISK_DIR.mkdir(parents=True, exist_ok=True)
            datei.write_bytes(blob)
        except OSError:
            pass
    return blob


# Plausibilitaets-Deckel fuers Vorwaermen — STRENGER als das Live-Gate im
# Chatterbox-Container (tts_serve/chatterbox/pegel.py): live kostet ein
# Retry Latenz, beim Wärmen kostet er nichts. Kalibrierung 28.08.2026:
# gute Renders 47-97 ms/Zeichen, Grauzone/Babble ab ~116. Ein gepinnter
# Babble-Render wuerde sonst bei JEDER Maschinen-Frage abgespielt
# (Vorfall 28.08.2026: 5,88 s fuer "Wie lautet der Nachname?").
_WARM_S_JE_ZEICHEN = 0.105
_WARM_GRUND_S = 0.3


def _warm_unplausibel(text: str, blob: bytes) -> bool:
    if not blob or blob[:4] != b"RIFF":
        return False  # nur eigene PCM-WAVs pruefen (ElevenLabs liefert MP3)
    dauer = max(0, len(blob) - 44) / 2 / PCM_RATE
    return dauer > _WARM_GRUND_S + _WARM_S_JE_ZEICHEN * len(text)


def _dauerhaft_key(text: str) -> str:
    sauber = _normalisieren(text)
    return _lokal_schluessel(sauber) if TTS_BASE else f"{_VOICE_ID}|{sauber}"


def _vergessen(text: str) -> None:
    """Cache-Eintrag (RAM-Pin + Platte) eines Satzes verwerfen."""
    schluessel = _dauerhaft_key(text)
    _FEST.pop(schluessel, None)
    _CACHE.pop(schluessel, None)
    try:
        (_DISK_DIR / (hashlib.sha1(schluessel.encode("utf-8")).hexdigest() + ".wav")).unlink(missing_ok=True)
    except OSError:
        pass


def _dauerhaft_speichern(text: str, blob: bytes) -> None:
    """Ein fertiges Blob als dauerhaften Cache-Eintrag setzen (RAM-Pin + Platte)."""
    schluessel = _dauerhaft_key(text)
    _ram_merken(schluessel, blob, fest=True)
    try:
        _DISK_DIR.mkdir(parents=True, exist_ok=True)
        (_DISK_DIR / (hashlib.sha1(schluessel.encode("utf-8")).hexdigest() + ".wav")).write_bytes(blob)
    except OSError:
        pass


def warm(text: str) -> None:
    """Startup-Vorwaermen statischer Saetze — dauerhaft gecacht.

    Zweitpruefung vor dem Pinnen: ist der Render unplausibel lang fuer den
    Text (Chatterbox wuerfelt Tempo und Babble), wird EINMAL neu geholt und
    das KUERZERE der beiden Ergebnisse gepinnt — nie endlos wuerfeln, der
    Dienststart muss durchlaufen."""
    try:
        erste = speak_dauerhaft(text)
        if not _warm_unplausibel(text, erste):
            return
        print(f"tts-warm: unplausibler Render ({len(text)} Z, "
              f"{max(0, len(erste) - 44) / 2 / PCM_RATE:.1f}s) — neuer Wurf", flush=True)
        _vergessen(text)
        zweite = speak_dauerhaft(text)
        if erste and zweite and len(zweite) > len(erste):
            _dauerhaft_speichern(text, erste)
    except Exception:
        pass
