"""STT-Dienst: deutscher Conformer-Transducer (NVIDIA NeMo) hinter FastAPI.

Vertrag (stt_serve/api.md):
    POST /transcribe  multipart file=<audio>  ->  {"text": "..."}
    GET  /health                              ->  {"ok": true, ...}

Der Dienst nimmt, was die Docks liefern (WebM/Opus vom MediaRecorder,
M4A von iOS, WAV aus Tests), wandelt per ffmpeg nach 16 kHz mono PCM und
dekodiert mit dem Conformer. Ein Decode zur Zeit (Lock) — bei einem
Gespraech gleichzeitig ist das kein Engpass, und die GPU gehoert zu
grossen Teilen dem qwen-vLLM daneben.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time

import uvicorn
from fastapi import FastAPI, File, UploadFile

MODEL_NAME = os.environ.get("STT_MODEL", "stt_de_conformer_transducer_large")
DEVICE = os.environ.get("STT_DEVICE", "cuda")
PORT = int(os.environ.get("STT_PORT", "8100"))

app = FastAPI()
_LOCK = threading.Lock()
_MODEL = None
_GERAET = "cpu"
_LADEZEIT = 0.0


def _laden() -> None:
    global _MODEL, _GERAET, _LADEZEIT
    import torch
    import nemo.collections.asr as nemo_asr

    t0 = time.time()
    m = nemo_asr.models.ASRModel.from_pretrained(MODEL_NAME)
    m.eval()
    if DEVICE == "cuda" and torch.cuda.is_available():
        m = m.cuda()
        _GERAET = "cuda"
    _MODEL = m
    # Warmup: erster CUDA-Decode laedt Kernel — nicht dem ersten Anrufer
    # aufbuerden. 1 s Stille reicht.
    try:
        _transkribieren(b"\x00\x00" * 16000, roh_pcm=True)
    except Exception as e:
        print(f"warmup uebersprungen: {e}", flush=True)
    _LADEZEIT = round(time.time() - t0, 1)
    print(f"stt bereit: {MODEL_NAME} auf {_GERAET} in {_LADEZEIT}s", flush=True)


def _nach_wav16k(blob: bytes) -> bytes:
    """Beliebiges Container-Format (webm/m4a/wav/...) -> WAV 16 kHz mono."""
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-i", "pipe:0", "-f", "wav", "-ar", "16000", "-ac", "1", "pipe:1"],
        input=blob, capture_output=True, timeout=20,
    )
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError(f"ffmpeg: {p.stderr.decode('utf-8', 'ignore')[:200]}")
    return p.stdout


def _text_aus(ergebnis) -> str:
    """NeMo-transcribe-Rueckgaben je nach Version normalisieren."""
    e = ergebnis
    while isinstance(e, (list, tuple)):
        if not e:
            return ""
        e = e[0]
    if isinstance(e, str):
        return e
    return str(getattr(e, "text", "") or "")


def _transkribieren(blob: bytes, roh_pcm: bool = False) -> str:
    if roh_pcm:
        import struct
        header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(blob), b"WAVE",
                             b"fmt ", 16, 1, 1, 16000, 32000, 2, 16, b"data", len(blob))
        wav = header + blob
    else:
        wav = _nach_wav16k(blob)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav)
        pfad = f.name
    try:
        with _LOCK:
            out = _MODEL.transcribe([pfad], batch_size=1, verbose=False)
        return " ".join(_text_aus(out).split()).strip()
    finally:
        try:
            os.unlink(pfad)
        except OSError:
            pass


@app.get("/health")
def health():
    return {
        "ok": _MODEL is not None,
        "model": MODEL_NAME,
        "device": _GERAET,
        "loadSeconds": _LADEZEIT,
    }


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    if _MODEL is None:
        return {"text": "", "error": "model_not_ready"}
    blob = await file.read()
    if not blob or len(blob) < 200:
        return {"text": ""}
    t0 = time.perf_counter()
    try:
        text = _transkribieren(blob)
    except Exception as e:
        print(f"transcribe fail bytes={len(blob)}: {e}", flush=True)
        return {"text": "", "error": str(e)[:200]}
    dauer = time.perf_counter() - t0
    print(f"transcribe {len(blob)}B -> {len(text)} Zeichen in {dauer:.2f}s", flush=True)
    return {"text": text}


if __name__ == "__main__":
    _laden()
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
