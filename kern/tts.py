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
    # Behandler-Namen: Qwen3 liest sie sonst englisch/lateinisch an.
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


# Ziffern-Ketten fuer den lokalen Mund (29.08.2026): CosyVoice verschmilzt
# wiederholte Zahlwoerter ("null null" -> EIN "null") und verlor so live
# Ziffern der Telefonnummer; Ziffern-Probe: Wortform 1/5, Einzelziffern
# mit Leerzeichen 5/5 ("0 1 7 7" spricht die Engine als "null eins sieben
# sieben"). Nur der Text AN DEN CONTAINER wird umgeschrieben — Cache-Key,
# Logs und Transkript behalten die Wortform. Gilt erst ab ZWEI Zahlwoertern
# in Folge (Telefonnummern-Muster); Uhrzeiten ("neun Uhr fuenfzehn") und
# Mengen ("zwoelf Termine") bleiben unberuehrt.
_ZIFFER_WORT = {
    "null": "0", "eins": "1", "zwei": "2", "drei": "3", "vier": "4",
    "fünf": "5", "fuenf": "5", "sechs": "6", "sieben": "7", "acht": "8",
    "neun": "9",
}
_ZIFFER_KETTE_RE = re.compile(
    r"\b(?:null|eins|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun)"
    r"(?:\s+(?:null|eins|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun))+\b",
    re.I,
)


def _ziffern_einzeln(text: str) -> str:
    def _ersetzen(m: "re.Match[str]") -> str:
        return " ".join(_ZIFFER_WORT[w.lower()] for w in m.group(0).split())
    return _ZIFFER_KETTE_RE.sub(_ersetzen, text)


# Nachhoer-Waechter fuer Ziffern-Saetze (29.08.2026): auch in Ziffern-Form
# wuerfelt CosyVoice GELEGENTLICH einen Abbruch/Babble-Wurf (E2E-Probe:
# 14-s-Audio, Nummer riss nach '0 1 7 7 6 0' ab). Eine Nummern-Ansage darf
# den Anrufer nur erreichen, wenn der lokale Parakeet ALLE Soll-Ziffern in
# Reihenfolge gegengehoert hat — sonst wird neu gerendert (max. 3 Wuerfe,
# ~1 s je Pruefung). Ohne lokales STT wird nicht geprueft (ElevenLabs-Pfad
# bleibt unberuehrt). Notaus: TTS_ZIFFERN_CHECK=0.
_ZIFFERN_VERSUCHE = 3


def _ziffern_soll(payload: str) -> str:
    """Alle Ziffern des Sprech-Texts in Reihenfolge — '' wenn kein
    Nummern-Satz (keine Kette, nichts zu pruefen)."""
    import os

    if os.environ.get("TTS_ZIFFERN_CHECK", "1").strip() == "0":
        return ""
    ziffern = re.findall(r"\d", payload)
    return "".join(ziffern) if len(ziffern) >= 4 else ""


def _ziffern_gehoert(blob: bytes, soll: str) -> bool:
    """Stimmen die gehoerten Ziffern? STT-Fehler => nicht blockieren (True)."""
    from kern import config as _cfg
    from kern import stt as _stt

    if not _cfg.STT_BASE or not blob or blob[:4] != b"RIFF":
        return True
    try:
        gehoert = _stt.transcribe(blob, mime="audio/wav", name="ziffern.wav")
    except Exception:
        return True
    return soll in re.sub(r"\D", "", gehoert)


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
        payload = _ziffern_einzeln(sauber)[:400]
        soll = _ziffern_soll(payload)
        blob = b""
        for versuch in range(_ZIFFERN_VERSUCHE if soll else 1):
            r = _lokal_client().post(
                f"{TTS_BASE}/speak",
                json={"text": payload, "voice": _VOICE_NAME},
            )
            if r.status_code != 200:
                raise RuntimeError(f"tts_lokal_http_{r.status_code}")
            raw = r.content
            if not raw:
                return b""
            # Container liefert rohes PCM16/24k — dieselbe Pegel-Schicht wie
            # beim ElevenLabs-Pfad, damit lokale Zuege gleich laut klingen.
            blob = pcm16_wav(raw)
            if not soll or _ziffern_gehoert(blob, soll):
                break
            print(f"tts-ziffern: Wurf {versuch + 1} unvollstaendig ({soll}) — neu", flush=True)
        _ram_merken(schluessel, blob)
        return blob


def engine() -> TtsEngine:
    if TTS_BASE:
        return LokalTts()
    return ElevenLabsTts()


def im_cache(text: str) -> bool:
    """RAM-Cache-Blick fuer den Satz-Split-Entscheid in dienst.py: gewarmte
    Begruessungen und Fueller sollen EIN Block bleiben — ihr Cache-Key
    traegt den Gesamttext, ein Satz-Split wuerde ihn verfehlen."""
    sauber = _normalisieren(text)
    if not sauber:
        return False
    schluessel = _lokal_schluessel(sauber) if TTS_BASE else f"{_VOICE_ID}|{sauber}"
    return schluessel in _FEST or schluessel in _CACHE


def wav_fuegen(blobs: list[bytes]) -> bytes:
    """Mehrere eigene PCM16-WAVs (44-Byte-Header, 24 kHz mono) zu EINEM
    fuegen. Liefert b"" wenn ein Teil kein fuegbares WAV ist — der Aufrufer
    faellt dann auf einen Ein-Block-Render zurueck."""
    teile = [b for b in blobs if b]
    if not teile:
        return b""
    if len(teile) == 1:
        return teile[0]
    for b in teile:
        if len(b) <= 44 or b[:4] != b"RIFF" or b[36:40] != b"data":
            return b""
    data = b"".join(b[44:] for b in teile)
    return _wav_header(len(data), PCM_RATE) + data


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
            elif "hybrid" in eng:
                anzeige = "Qwen3 Hybrid (lokal)"
            elif eng.startswith("qwen"):
                anzeige = "Qwen3 (lokal)"
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


# Plausibilitaets-Deckel fuers Vorwaermen — beim Wärmen kostet ein Retry
# nichts. Kalibrierung 28.08.2026: gute Renders 47-97 ms/Zeichen, Grauzone/
# Babble ab ~116. Ein gepinnter Babble-Render wuerde sonst bei JEDER
# Maschinen-Frage abgespielt (Vorfall 28.08.2026: 5,88 s fuer
# "Wie lautet der Nachname?").
_WARM_GRUND_S = 0.3
_WARM_S_JE_ZEICHEN = 0.105


def _warm_unplausibel(text: str, blob: bytes) -> bool:
    if not blob or blob[:4] != b"RIFF":
        return False  # nur eigene PCM-WAVs pruefen (ElevenLabs liefert MP3)
    dauer = max(0, len(blob) - 44) / 2 / PCM_RATE
    return dauer > _WARM_GRUND_S + _WARM_S_JE_ZEICHEN * len(text)


# Warm-Abnahme per Gegenhoeren (29.08.2026): der Laengen-Deckel allein liess
# Babble-Renders durch (CosyVoice plapperte live '...hissio' in eine feste
# Ansage, der Pin spielte das bei JEDER Frage). Ist der lokale Parakeet da
# (STT_BASE), hoert er jeden Warm-Render gegen: zu wenig Soll-Woerter im
# Gehoerten => ein neuer Wurf, der besser passende wird gepinnt.
# Notaus: TTS_WARM_CHECK=0.
_WARM_CHECK_MIN = 0.6


def _warm_score(text: str, blob: bytes) -> float | None:
    """Anteil der Soll-Woerter (ab 3 Zeichen), die das STT im Render hoert.
    None = nicht pruefbar (kein lokales STT, kein WAV, STT-Fehler)."""
    import os

    if os.environ.get("TTS_WARM_CHECK", "1").strip() == "0":
        return None
    if not blob or blob[:4] != b"RIFF":
        return None
    from kern import config as _cfg
    from kern import stt as _stt

    if not _cfg.STT_BASE:
        return None
    try:
        gehoert = _stt.transcribe(blob, mime="audio/wav", name="warm.wav")
    except Exception:
        return None
    soll = [w for w in re.findall(r"[a-zäöüß]+", text.lower()) if len(w) >= 3]
    if not soll:
        return None
    da = set(re.findall(r"[a-zäöüß]+", gehoert.lower()))
    return sum(w in da for w in soll) / len(soll)


def _dauerhaft_key(text: str) -> str:
    sauber = _normalisieren(text)
    return _lokal_schluessel(sauber) if TTS_BASE else f"{_VOICE_ID}|{sauber}"


def _dauerhaft_datei(text: str) -> Path:
    return _DISK_DIR / (hashlib.sha1(_dauerhaft_key(text).encode("utf-8")).hexdigest() + ".wav")


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

    Zwei Abnahmen vor dem Pinnen: (1) unplausibel LANGER Render (TTS
    wuerfelt Tempo und Babble) und (2) Gegenhoeren per lokalem STT —
    fehlen Soll-Woerter im Gehoerten, war der Wurf Babble. Jeweils EINMAL
    neu holen und den besseren behalten — nie endlos wuerfeln, der
    Dienststart muss durchlaufen."""
    try:
        # Platten-Eintrag vorhanden = frueher schon abgenommen (Laenge +
        # Gegenhoeren liefen beim ERSTEN Waermen). Nur laden, nicht erneut
        # pruefen — sonst kostet jeder Dienststart ~0,4 s STT je Satz und
        # der 2-Sekunden-Start waere dahin.
        schon_abgenommen = _dauerhaft_datei(text).is_file()
        erste = speak_dauerhaft(text)
        if schon_abgenommen:
            return
        score1 = None
        if not _warm_unplausibel(text, erste):
            score1 = _warm_score(text, erste)
            if score1 is None or score1 >= _WARM_CHECK_MIN:
                return
            print(f"tts-warm: Gegenhoeren {score1:.0%} fuer {text[:40]!r} — neuer Wurf", flush=True)
        else:
            print(f"tts-warm: unplausibler Render ({len(text)} Z, "
                  f"{max(0, len(erste) - 44) / 2 / PCM_RATE:.1f}s) — neuer Wurf", flush=True)
        _vergessen(text)
        zweite = speak_dauerhaft(text)
        if not erste or not zweite:
            return
        if score1 is not None:
            # Gegenhoer-Fall: den Wurf mit mehr getroffenen Soll-Woertern pinnen.
            score2 = _warm_score(text, zweite)
            if score2 is not None and score2 < score1:
                _dauerhaft_speichern(text, erste)
            return
        # Laengen-Fall: der KUERZERE Render gewinnt (Babble ist lang).
        if len(zweite) > len(erste):
            _dauerhaft_speichern(text, erste)
    except Exception:
        pass
