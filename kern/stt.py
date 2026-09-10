"""Spracheingabe.

STT_QWEN_BASE gesetzt = Qwen3-ASR-1.7B auf der RTX 3060 ist die primaere
Final-Erkennung (PCM16 16 kHz, begin/end-WebSocket-Vertrag, Bearer-Auth).
Dieser Modus ist hart von Whisper getrennt: bei einem Ausfall darf nur
STT_BASE (Parakeet) als sichtbares Sicherheitsnetz uebernehmen, niemals
Whisper oder ElevenLabs.

Ohne Qwen-Konfiguration bleibt der fruehere STT_WHISPER_BASE-Pfad
abwaertskompatibel. STT_BASE ist der lokale Parakeet-Container auf der 5090.
``keywords`` (Komma-Liste, z. B. Behandler-Nachnamen aus dem Tenant) werden
als reiner Vokabular-Kontext an Qwen beziehungsweise Whisper uebergeben."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
import io
import json
import re
import subprocess
import time
import wave

import httpx

from kern.config import (
    ELEVENLABS_API_KEY,
    STT_BASE,
    STT_QWEN_BASE,
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


def _qwen_ws(pcm: bytes, keywords: str = "") -> str:
    """Qwen-Final vom 3060-Gateway; Partials steuern Bianca nie."""
    msg = _stream_final(
        pcm,
        base=STT_QWEN_BASE,
        key=STT_QWEN_KEY,
        keywords=keywords,
        engine="qwen",
    )
    source = str(msg.get("source") or "qwen")
    degraded = bool(msg.get("degraded"))
    if degraded or source not in {"qwen", "consensus"}:
        reason = str(msg.get("fallbackReason") or "qwen_result_rejected")
        disagreements = ",".join(
            str(x) for x in (msg.get("disagreements") or [])
        )
        print(
            f"stt-qwen: source={source} degraded=1 reason={reason} "
            f"disagreements={disagreements or '-'}",
            flush=True,
        )
    return str(msg.get("text") or "")


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
    return bool(STT_QWEN_BASE) and time.time() >= _qwen_pause_bis


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
    return _sauber(_qwen_ws(pcm, keywords))


# ------------------------------------------------------------------ Einstieg

def transcribe(audio: bytes, *, mime: str = "audio/webm", name: str = "turn.webm",
               keywords: str = "") -> str:
    if not audio or len(audio) < 800:
        return ""
    if STT_QWEN_BASE:
        if _qwen_aktiv():
            try:
                return _qwen(audio, mime=mime, keywords=keywords)
            except Exception as e:
                _qwen_sperren(e)
        if STT_BASE:
            return _lokal(audio, mime=mime, name=name, keywords=keywords)
        # Qwen-Modus ist absichtlich hart von Whisper/ElevenLabs getrennt.
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
        STT_QWEN_BASE
        or STT_WHISPER_BASE
        or STT_BASE
        or ELEVENLABS_API_KEY
    )


def engine_anzeige() -> str:
    """Fuer die Dock-/Health-Anzeige: wer hoert gerade zu?"""
    if STT_QWEN_BASE:
        if not _qwen_aktiv() and STT_BASE:
            return "Parakeet (lokal, Qwen pausiert)"
        return "Qwen3-ASR 1.7B (3060)" + (
            " + Parakeet-Rueckfall" if STT_BASE else ""
        )
    if STT_WHISPER_BASE:
        if not _whisper_aktiv() and STT_BASE:
            return "Parakeet (lokal, Whisper pausiert)"
        return "Whisper large-v3 (Dev-GPU)" + (
            " + Parakeet-Rueckfall" if STT_BASE else ""
        )
    if STT_BASE:
        return "Parakeet (lokal)"
    return "ElevenLabs Scribe" if ELEVENLABS_API_KEY else "keine"
