"""Chatterbox-Multilingual-V3-Server — Vertrag siehe ../api.md.

Ein Prozess, eine GPU, serielle Synthese (Lock): auf der 5090 laeuft daneben
vLLM — parallele TTS-Laeufe bringen nur VRAM-Gedraengel statt Tempo.
"""

from __future__ import annotations

import io
import os
import threading
import time
from pathlib import Path

import torch
import torchaudio
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

PORT = int(os.environ.get("TTS_PORT", "8100"))
STIMMEN_DIR = Path(os.environ.get("STIMMEN_DIR", "/stimmen"))
ZIEL_RATE = 24000
# Chatterbox-Defaults (README): 0.5/0.5 fuer die meisten Prompts. Referenz mit
# schnellem Sprechtempo -> CHATTERBOX_CFG=0.3 probieren.
EXAGGERATION = float(os.environ.get("CHATTERBOX_EXAGGERATION", "0.5"))
CFG_WEIGHT = float(os.environ.get("CHATTERBOX_CFG", "0.5"))
SPRACHE = os.environ.get("TTS_SPRACHE", "de")

app = FastAPI(title="tts-chatterbox")

_LOCK = threading.Lock()
_MODEL = None
_VOICES: dict[str, Path] = {}
_WARM = False
_AKTIVE_STIMME = ""       # fuer prepare_conditionals-Wiederverwendung
_KANN_PREPARE = True      # bis das Gegenteil bewiesen ist


class SpeakIn(BaseModel):
    text: str
    voice: str = ""


def _stimmen_scannen() -> dict[str, Path]:
    out: dict[str, Path] = {}
    if STIMMEN_DIR.is_dir():
        for w in sorted(STIMMEN_DIR.glob("*.wav")):
            out[w.stem.lower()] = w
    return out


def _laden() -> None:
    """Modell + Stimmen laden, dann je Stimme einen Warmlauf-Satz rendern."""
    global _MODEL, _VOICES, _WARM
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    t0 = time.time()
    _MODEL = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model="v3")
    _VOICES = _stimmen_scannen()
    print(f"chatterbox geladen in {time.time() - t0:.0f}s, stimmen={list(_VOICES)}", flush=True)
    for name in _VOICES:
        try:
            t1 = time.time()
            _synthese("Guten Tag, einen kleinen Moment bitte.", name)
            print(f"chatterbox warm {name} in {time.time() - t1:.1f}s", flush=True)
        except Exception as e:
            print(f"chatterbox warmlauf {name} fehlgeschlagen: {e}", flush=True)
    _WARM = True


def _synthese(text: str, voice: str) -> bytes:
    """Text -> rohes PCM16 mono 24 kHz. Muss unter _LOCK laufen."""
    global _AKTIVE_STIMME, _KANN_PREPARE
    ref = _VOICES[voice]
    wav = None
    if _KANN_PREPARE:
        # Speaker-Konditionierung einmal pro Stimmwechsel rechnen statt pro
        # Satz — Speed ist die Vorgabe (Chef 27.08.2026).
        try:
            if _AKTIVE_STIMME != voice:
                _MODEL.prepare_conditionals(str(ref), exaggeration=EXAGGERATION)
                _AKTIVE_STIMME = voice
            wav = _MODEL.generate(
                text, language_id=SPRACHE,
                exaggeration=EXAGGERATION, cfg_weight=CFG_WEIGHT,
            )
        except (AttributeError, TypeError) as e:
            print(f"chatterbox prepare_conditionals nicht nutzbar ({e}) — pro Satz", flush=True)
            _KANN_PREPARE = False
            _AKTIVE_STIMME = ""
    if wav is None:
        wav = _MODEL.generate(
            text, language_id=SPRACHE, audio_prompt_path=str(ref),
            exaggeration=EXAGGERATION, cfg_weight=CFG_WEIGHT,
        )
    return _pcm16(wav, int(_MODEL.sr))


def _pcm16(wav: torch.Tensor, rate: int) -> bytes:
    if wav.dim() > 1:
        wav = wav.squeeze(0)
    wav = wav.detach().cpu()
    if rate != ZIEL_RATE:
        wav = torchaudio.functional.resample(wav, rate, ZIEL_RATE)
    wav = torch.clamp(wav, -1.0, 1.0)
    return (wav * 32767.0).to(torch.int16).numpy().tobytes()


@app.on_event("startup")
def _startup() -> None:
    threading.Thread(target=_laden, daemon=True).start()


@app.get("/health")
def health():
    ok = _MODEL is not None
    body = {
        "ok": ok,
        "engine": "chatterbox",
        "model": "Chatterbox-Multilingual-V3",
        "voices": sorted(_VOICES) if ok else sorted(_stimmen_scannen()),
        "device": "cuda",
        "warm": _WARM,
    }
    if not ok:
        return Response(
            content=io.StringIO(str(body)).getvalue(),
            status_code=503, media_type="application/json",
        )
    return body


@app.post("/speak")
def speak(body: SpeakIn):
    if _MODEL is None:
        raise HTTPException(503, "modell laedt noch")
    text = " ".join((body.text or "").split()).strip()
    if not text:
        raise HTTPException(400, "text fehlt")
    voice = (body.voice or "").strip().lower() or (sorted(_VOICES)[0] if _VOICES else "")
    if voice not in _VOICES:
        raise HTTPException(400, f"stimme unbekannt: {voice}")
    t0 = time.perf_counter()
    with _LOCK:
        try:
            pcm = _synthese(text, voice)
        except Exception as e:
            print(f"chatterbox synthese-fehler: {e}", flush=True)
            raise HTTPException(500, f"synthese: {e}")
    dauer = time.perf_counter() - t0
    print(f"chatterbox speak voice={voice} zeichen={len(text)} s={dauer:.2f}", flush=True)
    return Response(
        content=pcm,
        media_type="application/octet-stream",
        headers={"X-Sample-Rate": str(ZIEL_RATE), "X-Engine": "chatterbox",
                 "X-Dauer-S": f"{dauer:.2f}"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
