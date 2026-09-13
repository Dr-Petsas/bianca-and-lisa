"""Adobe-ähnliche Sprachbereinigung für ClonR-Stimmproben.

Resemble Enhance (MIT): Denoise + generative Restauration auf 44.1 kHz.
Kein EQ/Kompressor — das Modell rekonstruiert die Stimme.

Port 8214. MAS proxyt /voice-enhance -> hier.
"""

from __future__ import annotations

import io
import os
import tempfile
import threading
import time
import traceback

import numpy as np
import soundfile as sf
import torch
import torchaudio
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

PORT = int(os.environ.get("ENHANCE_PORT", "8214"))
NFE = int(os.environ.get("ENHANCE_NFE", "32"))


def _pick_device() -> str:
    forced = (os.environ.get("ENHANCE_DEVICE") or "").strip().lower()
    if forced in ("cpu", "cuda"):
        return forced
    if not torch.cuda.is_available():
        return "cpu"
    free, _total = torch.cuda.mem_get_info()
    # vLLM + Qwen-TTS belegen die 5090 fast voll. Unter 4 GB wird Enhance OOM.
    if free < 4 * 1024**3:
        print(f"enhance-device cpu (cuda free={free / 1024**3:.1f}G)", flush=True)
        return "cpu"
    return "cuda"


DEVICE = _pick_device()
_LOCK = threading.Lock()
_READY = False
_ERR = ""

app = FastAPI(title="ClonR Voice Enhance", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load() -> None:
    global _READY, _ERR
    try:
        from resemble_enhance.enhancer.inference import denoise, enhance
        warm = torch.zeros(24000)
        with torch.inference_mode():
            denoise(warm.to(DEVICE), 24000, DEVICE)
            enhance(warm.to(DEVICE), 24000, DEVICE, nfe=8, solver="midpoint", lambd=0.5, tau=0.5)
        _READY = True
        _ERR = ""
        print(f"enhance-ready device={DEVICE} nfe={NFE}", flush=True)
    except Exception as e:
        _ERR = f"{type(e).__name__}: {e}"
        print(f"enhance-load-fail {_ERR}", flush=True)


@app.on_event("startup")
def _startup() -> None:
    threading.Thread(target=_load, daemon=True).start()


@app.get("/health")
def health():
    return {"ok": _READY, "service": "voice-enhance", "device": DEVICE, "error": _ERR}


def _wav_bytes(wav: torch.Tensor, sr: int) -> bytes:
    if wav.ndim > 1:
        wav = wav.mean(dim=0)
    pcm = wav.detach().float().cpu().numpy()
    peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
    if peak > 1e-6:
        pcm = pcm * (0.89 / peak)  # ~ -1 dBTP
    buf = io.BytesIO()
    sf.write(buf, pcm, int(sr), format="WAV", subtype="PCM_16")
    return buf.getvalue()


@app.post("/enhance")
async def enhance_upload(audio: UploadFile = File(...)):
    if not _READY:
        raise HTTPException(503, f"Enhance lädt noch ({_ERR or 'Gewichte'}).")
    raw = await audio.read()
    if len(raw) < 2000:
        raise HTTPException(400, "Aufnahme zu kurz.")
    t0 = time.perf_counter()
    suffix = os.path.splitext(audio.filename or "in.wav")[1] or ".wav"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(raw)
        tmp.close()
        dwav, sr = torchaudio.load(tmp.name)
        dwav = dwav.mean(dim=0)
        from resemble_enhance.enhancer.inference import denoise, enhance
        with _LOCK:
            with torch.inference_mode():
                clean, sr1 = denoise(dwav.to(DEVICE), int(sr), DEVICE)
                out, sr2 = enhance(
                    clean, int(sr1), DEVICE,
                    nfe=NFE, solver="midpoint", lambd=0.5, tau=0.5,
                )
        blob = _wav_bytes(out, int(sr2))
    except Exception as e:
        print(f"enhance-fail {e}\n{traceback.format_exc()[-800:]}", flush=True)
        raise HTTPException(500, f"Enhance fehlgeschlagen: {e}") from e
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    print(f"enhance-ok bytes_in={len(raw)} out={len(blob)} s={time.perf_counter() - t0:.1f}", flush=True)
    return Response(blob, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
