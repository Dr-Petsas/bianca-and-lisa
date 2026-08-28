"""Parakeet-STT-Dienst fuer Lisa/Bianca — Claras bewaehrte Telefon-Strecke.

Engine wie Claras Produktion (F:\\Clara-Voice providers/stt/streaming.py,
ParakeetStreamingSTT): primeline-parakeet (deutsches TDT-Finetune, 2,95 % WER)
als ONNX ueber onnx-asr auf CPU (~190 ms je Zug auf dem Dev-Rechner; der
5090-Server-CPU ist schneller). Danach dieselben Stufen wie bei Clara:
Whitespace-Normalisierung + Fuzzy-Hotword-Nachkorrektur (postcorrect.py,
Kopie von Claras stt_postcorrect). KEIN Torch, KEINE GPU — das qwen-vLLM
und der TTS-Container auf der 5090 bleiben unberuehrt.

Vertrag (stt_serve/api.md):
  POST /transcribe  multipart: file=<webm|m4a|wav>, keywords="Petsas,Tzannis"
                    -> {"text": "...", "korrekturen": [["Betsas","Petsas"]],
                        "namenszweifel": {"unsicher": false, ...}, "ms": 187}
  GET  /health      -> {"ok": true, "model": "parakeet-primeline-onnx", ...}
"""
from __future__ import annotations

import os
import subprocess
import threading
import time

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile

from postcorrect import assess_name_certainty, correct_transcript

MODELL_PFAD = os.environ.get("STT_MODELL_PFAD", "/modell")
PORT = int(os.environ.get("STT_PORT", "8100"))
SAMPLE_RATE = 16000

app = FastAPI()
_LOCK = threading.Lock()
_MODEL = None
_LADEZEIT = 0.0


def _laden() -> None:
    global _MODEL, _LADEZEIT
    import onnx_asr

    t0 = time.time()
    _MODEL = onnx_asr.load_model(
        "nemo-conformer-tdt", path=MODELL_PFAD, providers=["CPUExecutionProvider"],
    )
    # Warmup wie bei Clara: 0,6 s Stille einmal durch den Graphen.
    import numpy as np
    _MODEL.recognize(np.zeros(int(SAMPLE_RATE * 0.6), dtype="float32"),
                     sample_rate=SAMPLE_RATE)
    _LADEZEIT = round(time.time() - t0, 1)
    print(f"parakeet bereit (CPU) in {_LADEZEIT}s aus {MODELL_PFAD}", flush=True)


def _nach_pcm16k(blob: bytes) -> bytes:
    """Beliebiges Dock-Audio (WebM/Opus, M4A, WAV) -> rohes PCM16 16 kHz mono."""
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-i", "pipe:0", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "pipe:1"],
        input=blob, capture_output=True, timeout=20,
    )
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError(f"ffmpeg: {p.stderr.decode('utf-8', 'ignore')[:200]}")
    return p.stdout


def _normalisieren(text: str) -> str:
    """Wie Claras _normalize_transcript: trimmen, Mehrfach-Leerraum glaetten."""
    import re
    return re.sub(r"\s+", " ", text.strip())


def _transkribieren(pcm: bytes, keywords: list[str]) -> tuple[str, list, dict]:
    import numpy as np

    # Claras Mindestlaengen-Gate: unter 200 ms gibt es nichts zu verstehen.
    if len(pcm) < SAMPLE_RATE * 2 // 5:
        return "", [], {"unsicher": False, "wort": "", "grund": "", "kandidaten": []}
    audio = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
    with _LOCK:
        text = str(_MODEL.recognize(audio, sample_rate=SAMPLE_RATE) or "").strip()
    text = _normalisieren(text)
    text, korrekturen = correct_transcript(text, keywords)
    zweifel = assess_name_certainty(text, keywords)
    return text, korrekturen, zweifel


@app.get("/health")
def health():
    return {
        "ok": _MODEL is not None,
        "model": "parakeet-primeline-onnx",
        "device": "cpu",
        "loadSeconds": _LADEZEIT,
    }


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), keywords: str = Form("")):
    if _MODEL is None:
        return {"text": "", "error": "model_not_ready"}
    blob = await file.read()
    if not blob or len(blob) < 200:
        return {"text": ""}
    kw = [k.strip() for k in keywords.split(",") if k.strip()]
    t0 = time.perf_counter()
    try:
        pcm = _nach_pcm16k(blob)
        text, korrekturen, zweifel = _transkribieren(pcm, kw)
    except Exception as e:  # noqa: BLE001 — Fehler gehoert in die Antwort, nicht in einen Crash
        print(f"transcribe fail bytes={len(blob)}: {e}", flush=True)
        return {"text": "", "error": str(e)[:200]}
    ms = round((time.perf_counter() - t0) * 1000.0, 1)
    if korrekturen:
        print(f"postcorrect: {korrekturen}", flush=True)
    print(f"transcribe {len(blob)}B -> {len(text)} Zeichen in {ms}ms", flush=True)
    return {"text": text, "korrekturen": korrekturen, "namenszweifel": zweifel, "ms": ms}


if __name__ == "__main__":
    _laden()
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
