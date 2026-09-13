"""Spracheingabe.

STT_BASE-Parakeet auf der 5090 ist das schnelle lokale Haupt-Ohr. Ist Qwen
konfiguriert, startet Qwen3-ASR auf der separaten GPU parallel: plausible
Parakeet-Texte warten exakt null Sekunden; nur auffaellige Texte duerfen
kurz auf ein rechtzeitig fertiges Qwen-Final warten. Partials steuern Bianca
nie. Der alte Gateway-Weg (STT_QWEN_BASE) und der schnellere direkte
Qwen-only-Weg (STT_QWEN_FINAL_BASE) bleiben beide unterstuetzt.

Ohne Qwen-Konfiguration bleibt der fruehere STT_WHISPER_BASE-Pfad
abwaertskompatibel. ``keywords`` (Komma-Liste, z. B. Behandler-Nachnamen)
werden als reiner Vokabular-Kontext an Qwen beziehungsweise Whisper gegeben."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from difflib import SequenceMatcher
import io
import json
import re
import subprocess
import threading
import time
import wave

import httpx

from kern.config import (
    ELEVENLABS_API_KEY,
    STT_BASE,
    STT_QWEN_BASE,
    STT_QWEN_FINAL_BASE,
    STT_QWEN_GRACE_S,
    STT_QWEN_KEY,
    STT_WHISPER_BASE,
    STT_WHISPER_BUDGET_S,
    STT_WHISPER_KEY,
)

_CLIENT: httpx.Client | None = None

# Whisper-Sicherung: nach einem Fehlschlag (Dev-Rechner aus, Tunnel weg)
# pausiert der Whisper-Pfad, damit nicht JEDER Zug den Connect-Timeout
# bezahlt — solange hoert Parakeet. Naechster Versuch nach Ablauf.
WHISPER_PAUSE_S = 30.0
_whisper_pause_bis = 0.0
# W-STT-VORFALLBACK (09.09.2026): Wenn Whisper sein Latenzbudget fast
# aufgebraucht hat, Parakeet schon parallel anwerfen. Bei einem gesunden
# Whisper bleibt dessen genauerer Text primaer; beim Timeout ist der lokale
# Rueckfall bereits fertig und kostet nicht noch einmal ~0,2-0,3 s seriell.
WHISPER_FALLBACK_LEAD_S = 0.30
_FALLBACK_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="stt-fallback")
_QWEN_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt-qwen-parallel")
_QWEN_LOCK = threading.Lock()
_qwen_future: Future | None = None
QWEN_PAUSE_S = 30.0
_qwen_pause_bis = 0.0


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
    # Parakeet schreibt sehr kurze deutsche Antworten phonetisch gelegentlich
    # englisch ("Ja" -> "Yeah/Yep", "Nein" -> "Nine"). Nur GANZE,
    # eindeutige Kurzantworten normalisieren — nie Woerter in Namen, freier
    # Prosa oder Ziffernketten ersetzen. Das ist deterministisch, kein LLM.
    kurz = re.sub(r"[^a-z]+", " ", text.lower()).strip()
    if kurz in {"yeah", "yep", "yea", "yes", "jep"}:
        return "Ja."
    if kurz in {"bitte ja", "please yes", "yes please"}:
        return "Ja, bitte."
    if kurz in {"no", "nope", "nine"}:
        return "Nein."
    if kurz in {"hello"}:
        return "Hallo."
    return text


_DEUTSCHE_STRUKTUR = {
    "aber", "also", "bitte", "brauche", "danke", "das", "dem", "den",
    "der", "die", "doch", "du", "ein", "eine", "einen", "für", "gerne",
    "habe", "haben", "hat", "heute", "ich", "ist", "ja", "kann", "kein",
    "keine", "mein", "meine", "möchte", "morgen", "nein", "nicht", "noch",
    "oder", "sie", "sind", "termin", "uhr", "um", "und", "uns", "was",
    "wir", "zu", "zum", "zur",
}
_ZAHLWORT = {
    "null": "0", "eins": "1", "ein": "1", "eine": "1", "einen": "1",
    "zwei": "2", "zwo": "2", "drei": "3", "vier": "4", "fünf": "5",
    "fuenf": "5", "sechs": "6", "sieben": "7", "acht": "8", "neun": "9",
}


def _woerter(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", str(text or "").casefold(), re.UNICODE)


def _qwen_konfiguriert() -> bool:
    return bool(STT_QWEN_FINAL_BASE or STT_QWEN_BASE)


def _parakeet_braucht_qwen(text: str, keywords: str) -> bool:
    """Konservativ: nur lexikalisch auffaellige Parakeet-Texte warten kurz."""
    words = _woerter(text)
    if not words:
        return True
    haystack = f" {' '.join(words)} "
    for keyword in (k.strip() for k in keywords.split(",")):
        needle = " ".join(_woerter(keyword))
        if needle and f" {needle} " in haystack:
            return False
    evidence = sum(word in _DEUTSCHE_STRUKTUR for word in words)
    return evidence / len(words) < 0.5


def _zahlenfolgen(text: str) -> list[str]:
    folgen: list[str] = []
    aktuell = ""
    for token in re.findall(r"\d+|[^\W\d_]+", str(text or "").casefold(), re.UNICODE):
        ziffer = token if token.isdigit() else _ZAHLWORT.get(token, "")
        if ziffer:
            aktuell += ziffer
        elif aktuell:
            if len(aktuell) >= 2:
                folgen.append(aktuell)
            aktuell = ""
    if len(aktuell) >= 2:
        folgen.append(aktuell)
    return folgen


def _vergleich(text: str) -> str:
    return " ".join(re.findall(r"\d+|[^\W\d_]+", str(text or "").casefold()))


def _qwen_darf_uebernehmen(lokal: str, kandidat: dict, auffaellig: bool) -> bool:
    qwen = _sauber(kandidat.get("text"))
    if not qwen or not kandidat.get("authoritative"):
        return False
    if not lokal:
        return True
    if len(qwen.split()) < 2 and len(lokal.split()) >= 5:
        return False
    lokal_zahlen, qwen_zahlen = _zahlenfolgen(lokal), _zahlenfolgen(qwen)
    if (lokal_zahlen or qwen_zahlen) and lokal_zahlen != qwen_zahlen:
        return False
    similarity = SequenceMatcher(None, _vergleich(lokal), _vergleich(qwen)).ratio()
    return auffaellig or similarity >= 0.72


# ---------------------------------------------------------------- Parakeet

def _lokal(audio: bytes, *, mime: str, name: str, keywords: str = "") -> str:
    r = _client().post(
        f"{STT_BASE}/transcribe",
        files={"file": (name, audio, mime or "application/octet-stream")},
        data={"keywords": keywords} if keywords else None,
    )
    if r.status_code != 200:
        raise RuntimeError(f"stt_lokal_http_{r.status_code}")
    # Der Container korrigiert bereits. Die lokale, idempotente zweite Runde
    # hält aber neue marker-gated Tenant-Aliase sofort nutzbar, ohne das
    # bewährte Parakeet-Modell oder seinen Container neu zu starten.
    text = _sauber(r.json().get("text"))
    return _sauber(_nachkorrigieren(text, keywords))


# ----------------------------------------------------------------- Whisper

def _stream_url(raw_base: str) -> str:
    """HTTP-/WS-/nackte Basis -> WebSocket-Endpunkt /stream."""
    base = raw_base
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    elif not base.startswith(("ws://", "wss://")):
        base = "ws://" + base
    return base.rstrip("/") + "/stream"


def _ws_url() -> str:
    """Abwaertskompatibler Whisper-URL-Helfer fuer bestehende Tests."""
    return _stream_url(STT_WHISPER_BASE)


def _qwen_ws_url() -> str:
    return _stream_url(STT_QWEN_BASE)


def _pcm16k(audio: bytes, mime: str) -> bytes:
    """Beliebiges Zug-Audio (webm/m4a/wav) -> rohes PCM16 mono 16 kHz.
    Passendes WAV geht ohne ffmpeg, alles andere dekodiert ffmpeg."""
    if audio[:4] == b"RIFF":
        try:
            with wave.open(io.BytesIO(audio)) as w:
                if (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000):
                    return w.readframes(w.getnframes())
        except Exception:
            pass
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
             "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"],
            input=audio, capture_output=True, timeout=10,
        )
    except FileNotFoundError:
        raise RuntimeError("stt_stream_kein_ffmpeg")
    except subprocess.TimeoutExpired:
        raise RuntimeError("stt_stream_dekodier_timeout")
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError("stt_stream_dekodieren")
    return proc.stdout


def _stream_final(
    pcm: bytes,
    *,
    base: str,
    key: str,
    keywords: str = "",
    engine: str = "stream",
    timeout_s: float = 15.0,
) -> dict:
    """Ein Zug zum kompatiblen Stream-Dienst; nur ``final`` zaehlt."""
    from websockets.sync.client import connect

    connect_kwargs = {
        "open_timeout": min(2.0, max(0.2, float(timeout_s))),
        "close_timeout": 2.0,
        "max_size": 16 * 1024 * 1024,
    }
    if key:
        connect_kwargs["additional_headers"] = {
            "Authorization": f"Bearer {key}"
        }
    with connect(
        _stream_url(base),
        **connect_kwargs,
    ) as ws:
        begin: dict = {
            "op": "begin",
            "sampleRate": 16000,
            "channels": 1,
            "format": "pcm_s16le",
            "req": 1,
        }
        if keywords:
            begin["prompt"] = ", ".join(
                k.strip() for k in keywords.split(",") if k.strip()
            )
        ws.send(json.dumps(begin))
        for i in range(0, len(pcm), 64000):
            ws.send(pcm[i:i + 64000])
        ws.send(json.dumps({"op": "end", "req": 1}))
        frist = time.monotonic() + max(0.2, float(timeout_s))
        while True:
            rest = frist - time.monotonic()
            if rest <= 0:
                raise RuntimeError(f"stt_{engine}_timeout")
            raw = ws.recv(timeout=rest)
            if isinstance(raw, (bytes, bytearray)):
                continue
            msg = json.loads(raw)
            if msg.get("type") == "error":
                raise RuntimeError(str(msg.get("error") or "stt_stream_error"))
            if msg.get("type") == "final" and msg.get("req") == 1:
                if msg.get("error"):
                    raise RuntimeError(str(msg["error"]))
                return msg


def _whisper_budget_s() -> float:
    """Morgen-Freeze: Whisper darf den Zug nie länger als dieses Budget
    blockieren. 0/negativ = alter 15-s-Timeout."""
    budget = float(STT_WHISPER_BUDGET_S or 0.0)
    return 15.0 if budget <= 0 else budget


def _whisper_ws(pcm: bytes, keywords: str = "") -> str:
    """Abwaertskompatibler Whisper-Stream-Pfad (mit Latenz-Deckel)."""
    msg = _stream_final(
        pcm,
        base=STT_WHISPER_BASE,
        key=STT_WHISPER_KEY,
        keywords=keywords,
        engine="whisper",
        timeout_s=_whisper_budget_s(),
    )
    return str(msg.get("text") or "")


def _qwen_gateway_message(pcm: bytes, keywords: str = "") -> dict:
    """Final vom alten Hybrid-Gateway; Partials steuern Bianca nie."""
    return _stream_final(
        pcm,
        base=STT_QWEN_BASE,
        key=STT_QWEN_KEY,
        keywords=keywords,
        engine="qwen",
    )


def _qwen_ws(pcm: bytes, keywords: str = "") -> str:
    """Abwaertskompatibler Test-Helfer fuer den Gateway-Vertrag."""
    return str(_qwen_gateway_message(pcm, keywords).get("text") or "")


def _nachkorrigieren(text: str, keywords: str) -> str:
    """Claras Fuzzy-Nachkorrektur (Kopie in stt_serve/) auch auf dem
    Whisper-Pfad — Parakeet macht das serverseitig im Container."""
    if not text or not keywords:
        return text
    try:
        from stt_serve.postcorrect import correct_transcript
    except Exception:
        return text
    try:
        korrigiert, _ = correct_transcript(
            text, [k.strip() for k in keywords.split(",") if k.strip()]
        )
        return korrigiert
    except Exception:
        return text


def _qwen_context(keywords: str) -> str:
    vocabulary = ", ".join(
        k.strip() for k in keywords.split(",") if k.strip()
    )
    return f"Vokabular: {vocabulary}."[:800] if vocabulary else ""


def _qwen_context_echo(text: str, context: str) -> bool:
    heard = _vergleich(text).strip()
    prompt = _vergleich(context).strip()
    if len(heard) < 16 or len(prompt) < 16:
        return False
    return (
        heard in prompt
        or prompt in heard
        or SequenceMatcher(None, heard, prompt).ratio() >= 0.85
    )


def _qwen_final_message(pcm: bytes, keywords: str = "") -> dict:
    """Direkter Qwen-only-Container: kein zweites Parakeet auf der GPU-Box."""
    response = _client().post(
        f"{STT_QWEN_FINAL_BASE}/final",
        files={"file": ("audio.pcm", pcm, "application/octet-stream")},
        data={"context": _qwen_context(keywords)},
        headers={"X-Internal-Token": STT_QWEN_KEY},
    )
    if response.status_code != 200:
        raise RuntimeError(f"stt_qwen_final_http_{response.status_code}")
    payload = dict(response.json())
    payload.setdefault("source", "qwen")
    payload.setdefault("degraded", False)
    return payload


def _qwen_candidate(pcm: bytes, keywords: str = "") -> dict:
    message = (
        _qwen_final_message(pcm, keywords)
        if STT_QWEN_FINAL_BASE
        else _qwen_gateway_message(pcm, keywords)
    )
    text = _sauber(_nachkorrigieren(str(message.get("text") or ""), keywords))
    language = str(message.get("language") or "German").casefold()
    source = str(message.get("source") or "qwen")
    degraded = bool(message.get("degraded"))
    context = _qwen_context(keywords)
    echo = _qwen_context_echo(text, context)
    authoritative = (
        bool(text)
        and language in {"de", "deutsch", "german"}
        and source in {"qwen", "consensus"}
        and not degraded
        and not echo
    )
    return {
        "text": "" if echo else text,
        "source": source,
        "authoritative": authoritative,
        "reason": (
            "qwen_context_echo"
            if echo
            else str(message.get("fallbackReason") or "")
        ),
    }


def _whisper_aktiv() -> bool:
    return bool(STT_WHISPER_BASE) and time.time() >= _whisper_pause_bis


def _whisper_sperren(grund: Exception) -> None:
    global _whisper_pause_bis
    _whisper_pause_bis = time.time() + WHISPER_PAUSE_S
    print(f"stt-whisper: fallback auf parakeet ({type(grund).__name__}: {grund}), "
          f"pause {WHISPER_PAUSE_S:.0f}s", flush=True)


def _whisper(audio: bytes, *, mime: str, keywords: str = "") -> str:
    pcm = _pcm16k(audio, mime)
    if len(pcm) < 1600:  # unter 50 ms ist nichts zu hoeren
        return ""
    text = _whisper_ws(pcm, keywords)
    return _sauber(_nachkorrigieren(text, keywords))


def _whisper_mit_vorgezogenem_fallback(
    audio: bytes,
    *,
    mime: str,
    name: str,
    keywords: str = "",
) -> tuple[str, Future | None, Exception | None]:
    """Whisper bleibt primaer, Parakeet wird nur nahe am Deckel vorbereitet.

    Das Ergebnis des Rueckfalls wird hier noch nicht verwendet: Ein gesundes,
    knappes Whisper-Final gewinnt weiterhin. Nur bei Fehler oder leerem Final
    nimmt ``transcribe`` das bereits laufende Parakeet-Ergebnis. Dadurch
    aendert sich die Erkennungsqualitaet im Normalfall nicht.
    """
    if not STT_BASE:
        try:
            return _whisper(audio, mime=mime, keywords=keywords), None, None
        except Exception as e:
            return "", None, e

    budget = _whisper_budget_s()
    # Beim expliziten 15-s-Altpfad keinen fast 15 Sekunden spaeten
    # Spekulationsfaden aufmachen; dieses Verhalten ist nur Teil des harten
    # Produktionsdeckels.
    if budget >= 15.0:
        try:
            return _whisper(audio, mime=mime, keywords=keywords), None, None
        except Exception as e:
            return "", None, e

    whisper: Future = _FALLBACK_POOL.submit(
        _whisper, audio, mime=mime, keywords=keywords
    )
    fallback: Future | None = None
    vorlauf = min(max(0.05, WHISPER_FALLBACK_LEAD_S), max(0.05, budget / 2))
    try:
        return str(whisper.result(timeout=max(0.05, budget - vorlauf)) or ""), None, None
    except FutureTimeout:
        fallback = _FALLBACK_POOL.submit(
            _lokal, audio, mime=mime, name=name, keywords=keywords
        )
    except Exception as e:
        return "", None, e

    try:
        # _whisper_ws besitzt selbst den harten Deckel. Ein Final kurz vor
        # Ablauf gewinnt weiterhin; der Future kostet beim Zurueckkehren keine
        # Wartezeit auf den parallel laufenden Parakeet-Faden.
        return str(whisper.result() or ""), fallback, None
    except Exception as e:
        return "", fallback, e


def _qwen_aktiv() -> bool:
    return _qwen_konfiguriert() and time.time() >= _qwen_pause_bis


def _qwen_sperren(grund: Exception) -> None:
    global _qwen_pause_bis
    _qwen_pause_bis = time.time() + QWEN_PAUSE_S
    print(
        f"stt-qwen: fallback auf parakeet "
        f"({type(grund).__name__}: {grund}), pause {QWEN_PAUSE_S:.0f}s",
        flush=True,
    )


def _qwen(audio: bytes, *, mime: str, keywords: str = "") -> str:
    pcm = _pcm16k(audio, mime)
    if len(pcm) < 1600:
        return ""
    return str(_qwen_candidate(pcm, keywords).get("text") or "")


def _qwen_parallel_task(audio: bytes, mime: str, keywords: str) -> dict:
    try:
        pcm = _pcm16k(audio, mime)
        if len(pcm) < 1600:
            return {"text": "", "authoritative": False, "reason": "too_short"}
        return _qwen_candidate(pcm, keywords)
    except Exception as exc:
        _qwen_sperren(exc)
        return {
            "text": "",
            "authoritative": False,
            "reason": f"{type(exc).__name__}: {exc}",
        }


def _qwen_parallel_start(audio: bytes, mime: str, keywords: str) -> Future | None:
    """Genau ein Qwen-Lauf gleichzeitig; alte Zuege werden nie aufgestaut."""
    global _qwen_future
    if not _qwen_aktiv():
        return None
    with _QWEN_LOCK:
        if _qwen_future is not None and not _qwen_future.done():
            return None
        _qwen_future = _QWEN_POOL.submit(
            _qwen_parallel_task,
            audio,
            mime,
            keywords,
        )
        return _qwen_future


def _parallel_transcribe(
    audio: bytes,
    *,
    mime: str,
    name: str,
    keywords: str,
) -> str:
    """Parakeet sofort; nur auffaellige Texte warten gedeckelt auf Qwen."""
    qwen = _qwen_parallel_start(audio, mime, keywords)
    try:
        lokal = _lokal(audio, mime=mime, name=name, keywords=keywords)
    except Exception:
        # Nur bei echtem Ausfall des Haupt-Ohrs darf Qwen laenger retten.
        if qwen is not None:
            try:
                kandidat = qwen.result(timeout=15.0)
                if kandidat.get("authoritative") and kandidat.get("text"):
                    return str(kandidat["text"])
            except FutureTimeout:
                pass
        raise

    if qwen is None:
        return lokal

    auffaellig = _parakeet_braucht_qwen(lokal, keywords)
    kandidat: dict | None = None
    if qwen.done():
        kandidat = qwen.result()
    elif auffaellig and STT_QWEN_GRACE_S > 0:
        try:
            kandidat = qwen.result(timeout=max(0.0, STT_QWEN_GRACE_S))
        except FutureTimeout:
            print(
                f"stt-qwen-parallel: spaet, parakeet nach "
                f"{STT_QWEN_GRACE_S:.2f}s Zusatzdeckel",
                flush=True,
            )

    if kandidat and _qwen_darf_uebernehmen(lokal, kandidat, auffaellig):
        print(
            f"stt-qwen-parallel: qwen uebernommen source="
            f"{kandidat.get('source') or 'qwen'}",
            flush=True,
        )
        return str(kandidat["text"])
    return lokal


# ------------------------------------------------------------------ Einstieg

def transcribe(audio: bytes, *, mime: str = "audio/webm", name: str = "turn.webm",
               keywords: str = "") -> str:
    if not audio or len(audio) < 800:
        return ""
    if _qwen_konfiguriert():
        if STT_BASE:
            return _parallel_transcribe(
                audio,
                mime=mime,
                name=name,
                keywords=keywords,
            )
        if _qwen_aktiv():
            try:
                return _qwen(audio, mime=mime, keywords=keywords)
            except Exception as e:
                _qwen_sperren(e)
        # Qwen-only ohne lokales Parakeet: nie Whisper/ElevenLabs kaschieren.
        raise RuntimeError("stt_qwen_pause_ohne_fallback")
    if _whisper_aktiv():
        text, fallback, fehler = _whisper_mit_vorgezogenem_fallback(
            audio, mime=mime, name=name, keywords=keywords
        )
        if text:
            return text
        if fehler is not None:
            _whisper_sperren(fehler)
            if not STT_BASE:
                raise fehler  # kein Parakeet konfiguriert — NIE still zu ElevenLabs
        elif STT_BASE:
            # Live 09.09.: leeres Whisper-Final bei hörbarem Kurz-Zug — ohne
            # Gegenhören verschwanden Ja/Nein. Whisper bleibt aktiv.
            print("stt-whisper: leeres Final, Parakeet hoert gegen", flush=True)
        else:
            return ""
        if fallback is not None:
            return str(fallback.result() or "")
    if STT_BASE:
        return _lokal(audio, mime=mime, name=name, keywords=keywords)
    if STT_WHISPER_BASE:
        # Whisper pausiert und kein Parakeet: Fehler hoerbar machen statt
        # still auf Scribe auszuweichen (Chef 28.08.2026).
        raise RuntimeError("stt_whisper_pause_ohne_fallback")
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
    return bool(
        STT_QWEN_FINAL_BASE
        or STT_QWEN_BASE
        or STT_WHISPER_BASE
        or STT_BASE
        or ELEVENLABS_API_KEY
    )


def engine_anzeige() -> str:
    """Fuer die Dock-/Health-Anzeige: wer hoert gerade zu?"""
    if _qwen_konfiguriert():
        if not _qwen_aktiv() and STT_BASE:
            return "Parakeet (lokal, Qwen pausiert)"
        if STT_BASE:
            return "Parakeet (lokal) + Qwen3-ASR parallel (3060)"
        return "Qwen3-ASR 1.7B (3060)"
    if STT_WHISPER_BASE:
        if not _whisper_aktiv() and STT_BASE:
            return "Parakeet (lokal, Whisper pausiert)"
        return "Whisper large-v3 (Dev-GPU)" + (
            " + Parakeet-Rueckfall" if STT_BASE else ""
        )
    if STT_BASE:
        return "Parakeet (lokal)"
    return "ElevenLabs Scribe" if ELEVENLABS_API_KEY else "keine"
