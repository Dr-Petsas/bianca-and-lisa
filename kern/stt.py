"""Spracheingabe. STT_WHISPER_BASE gesetzt = ZUERST der Whisper-Stream-
Container auf dem Dev-Rechner (pickadoc-stt, large-v3 auf GPU, WebSocket-
Vertrag: PCM16 16 kHz + begin/end-Ops, Bearer-Auth) — ist der Dev-Rechner
nicht erreichbar, faellt der Zug automatisch auf STT_BASE zurueck
(W-STT-WHISPER, Chef 30.08.2026). STT_BASE gesetzt = lokaler Parakeet-
Container (5090, Claras bewaehrte Telefon-Engine + Fuzzy-Namens-
Nachkorrektur), OHNE ElevenLabs-Rueckfall (Chef 28.08.2026: "es geht
nichts mehr zu elevenlabs"). Beides leer = ElevenLabs Scribe wie frueher.
``keywords`` (Komma-Liste, z. B. Behandler-Nachnamen aus dem Tenant) gehen
als Hotwords an die Nachkorrektur im Parakeet-Container; der Whisper-Pfad
biast damit den Decoder (initial_prompt) und laeuft danach durch DIESELBE
Nachkorrektur-Kopie (stt_serve/postcorrect.py) im Prozess."""

from __future__ import annotations

import io
import json
import subprocess
import time
import wave

import httpx

from kern.config import (
    ELEVENLABS_API_KEY,
    STT_BASE,
    STT_WHISPER_BASE,
    STT_WHISPER_KEY,
)

_CLIENT: httpx.Client | None = None

# Whisper-Sicherung: nach einem Fehlschlag (Dev-Rechner aus, Tunnel weg)
# pausiert der Whisper-Pfad, damit nicht JEDER Zug den Connect-Timeout
# bezahlt — solange hoert Parakeet. Naechster Versuch nach Ablauf.
WHISPER_PAUSE_S = 30.0
_whisper_pause_bis = 0.0


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


# ---------------------------------------------------------------- Parakeet

def _lokal(audio: bytes, *, mime: str, name: str, keywords: str = "") -> str:
    r = _client().post(
        f"{STT_BASE}/transcribe",
        files={"file": (name, audio, mime or "application/octet-stream")},
        data={"keywords": keywords} if keywords else None,
    )
    if r.status_code != 200:
        raise RuntimeError(f"stt_lokal_http_{r.status_code}")
    return _sauber(r.json().get("text"))


# ----------------------------------------------------------------- Whisper

def _ws_url() -> str:
    """STT_WHISPER_BASE (http/ws/nackt) -> ws://host:port/stream."""
    base = STT_WHISPER_BASE
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    elif not base.startswith(("ws://", "wss://")):
        base = "ws://" + base
    return base.rstrip("/") + "/stream"


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
        raise RuntimeError("stt_whisper_kein_ffmpeg")
    except subprocess.TimeoutExpired:
        raise RuntimeError("stt_whisper_dekodier_timeout")
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError("stt_whisper_dekodieren")
    return proc.stdout


def _whisper_ws(pcm: bytes, keywords: str = "") -> str:
    """Ein Zug ueber den Whisper-Stream-Container: begin -> PCM -> end ->
    final. Partials/ready werden ueberlesen, nur das final zaehlt."""
    from websockets.sync.client import connect

    with connect(
        _ws_url(),
        additional_headers={"Authorization": f"Bearer {STT_WHISPER_KEY}"},
        open_timeout=2.0,
        close_timeout=2.0,
        max_size=16 * 1024 * 1024,
    ) as ws:
        begin: dict = {"op": "begin"}
        if keywords:
            begin["prompt"] = ", ".join(
                k.strip() for k in keywords.split(",") if k.strip()
            )
        ws.send(json.dumps(begin))
        for i in range(0, len(pcm), 64000):
            ws.send(pcm[i:i + 64000])
        ws.send(json.dumps({"op": "end", "req": 1}))
        frist = time.monotonic() + 15.0
        while True:
            rest = frist - time.monotonic()
            if rest <= 0:
                raise RuntimeError("stt_whisper_timeout")
            raw = ws.recv(timeout=rest)
            if isinstance(raw, (bytes, bytearray)):
                continue
            msg = json.loads(raw)
            if msg.get("type") == "final" and msg.get("req") == 1:
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


# ------------------------------------------------------------------ Einstieg

def transcribe(audio: bytes, *, mime: str = "audio/webm", name: str = "turn.webm",
               keywords: str = "") -> str:
    if not audio or len(audio) < 800:
        return ""
    if _whisper_aktiv():
        try:
            return _whisper(audio, mime=mime, keywords=keywords)
        except Exception as e:
            _whisper_sperren(e)
            if not STT_BASE:
                raise  # kein Parakeet konfiguriert — NIE still zu ElevenLabs
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
    return bool(STT_WHISPER_BASE or STT_BASE or ELEVENLABS_API_KEY)


def engine_anzeige() -> str:
    """Fuer die Dock-/Health-Anzeige: wer hoert gerade zu?"""
    if STT_WHISPER_BASE:
        if not _whisper_aktiv() and STT_BASE:
            return "Parakeet (lokal, Whisper pausiert)"
        return "Whisper large-v3 (Dev-GPU)" + (
            " + Parakeet-Rueckfall" if STT_BASE else ""
        )
    if STT_BASE:
        return "Parakeet (lokal)"
    return "ElevenLabs Scribe" if ELEVENLABS_API_KEY else "keine"
