"""Fun-CosyVoice3-Server — Vertrag siehe ../api.md.

Zero-Shot-Klonen braucht bei CosyVoice BEIDES: Referenz-WAV UND wortgetreues
Transkript (`<stimme>.txt`). Der Speaker wird beim Start einmal registriert
(add_zero_shot_spk), danach kostet er pro Satz nichts mehr; klappt das nicht,
faellt der Server auf Prompt-pro-Satz zurueck.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

REPO = os.environ.get("COSYVOICE_REPO", "/opt/CosyVoice")
sys.path.insert(0, REPO)
sys.path.insert(0, f"{REPO}/third_party/Matcha-TTS")

import torch
import torchaudio
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

PORT = int(os.environ.get("TTS_PORT", "8100"))
STIMMEN_DIR = Path(os.environ.get("STIMMEN_DIR", "/stimmen"))
MODEL_DIR = os.environ.get("MODEL_DIR", "/models/cosyvoice/Fun-CosyVoice3-0.5B")
MODEL_HF = os.environ.get("MODEL_HF", "FunAudioLLM/Fun-CosyVoice3-0.5B-2512")
ZIEL_RATE = 24000
# CosyVoice3-Beispiele tragen dieses Praefix im prompt_text (example.py).
CV3_PRAEFIX = "You are a helpful assistant.<|endofprompt|>"

app = FastAPI(title="tts-cosyvoice")

_LOCK = threading.Lock()
_MODEL = None
_VOICES: dict[str, Path] = {}
_TRANSKRIPT: dict[str, str] = {}
_REGISTRIERT: set[str] = set()
_WARM = False


class SpeakIn(BaseModel):
    text: str
    voice: str = ""


def _stimmen_scannen() -> None:
    _VOICES.clear()
    _TRANSKRIPT.clear()
    if not STIMMEN_DIR.is_dir():
        return
    for w in sorted(STIMMEN_DIR.glob("*.wav")):
        name = w.stem.lower()
        txt = w.with_suffix(".txt")
        if not txt.is_file():
            print(f"cosyvoice: {w.name} ohne {txt.name} — Stimme uebersprungen "
                  "(Zero-Shot braucht das Transkript)", flush=True)
            continue
        _VOICES[name] = w
        _TRANSKRIPT[name] = " ".join(txt.read_text(encoding="utf-8").split()).strip()


def _modell_holen() -> None:
    if Path(MODEL_DIR, "cosyvoice3.yaml").is_file() or Path(MODEL_DIR, "cosyvoice2.yaml").is_file():
        return
    print(f"cosyvoice: lade {MODEL_HF} nach {MODEL_DIR} (einmalig) ...", flush=True)
    from huggingface_hub import snapshot_download

    snapshot_download(MODEL_HF, local_dir=MODEL_DIR)


def _laden() -> None:
    global _MODEL, _WARM
    from cosyvoice.cli.cosyvoice import AutoModel

    t0 = time.time()
    _modell_holen()
    _MODEL = AutoModel(model_dir=MODEL_DIR)
    _stimmen_scannen()
    print(f"cosyvoice geladen in {time.time() - t0:.0f}s, stimmen={list(_VOICES)}", flush=True)
    for name in _VOICES:
        try:
            _MODEL.add_zero_shot_spk(
                CV3_PRAEFIX + _TRANSKRIPT[name], str(_VOICES[name]), name,
            )
            _REGISTRIERT.add(name)
        except Exception as e:
            print(f"cosyvoice add_zero_shot_spk {name} scheitert ({e}) — Prompt pro Satz", flush=True)
        try:
            t1 = time.time()
            _synthese("Guten Tag, einen kleinen Moment bitte.", name)
            print(f"cosyvoice warm {name} in {time.time() - t1:.1f}s", flush=True)
        except Exception as e:
            print(f"cosyvoice warmlauf {name} fehlgeschlagen: {e}", flush=True)
    _WARM = True


def _synthese(text: str, voice: str) -> bytes:
    """Text -> rohes PCM16 mono 24 kHz. Muss unter _LOCK laufen."""
    if voice in _REGISTRIERT:
        gen = _MODEL.inference_zero_shot(text, "", "", zero_shot_spk_id=voice, stream=False)
    else:
        gen = _MODEL.inference_zero_shot(
            text, CV3_PRAEFIX + _TRANSKRIPT[voice], str(_VOICES[voice]), stream=False,
        )
    teile = [out["tts_speech"] for out in gen]
    if not teile:
        raise RuntimeError("keine ausgabe")
    wav = torch.cat(teile, dim=-1)
    return _pcm16(wav, int(_MODEL.sample_rate))


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
        "engine": "cosyvoice",
        "model": MODEL_HF,
        "voices": sorted(_VOICES),
        "device": "cuda",
        "warm": _WARM,
    }
    if not ok:
        raise HTTPException(503, "modell laedt noch")
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
        except HTTPException:
            raise
        except Exception as e:
            print(f"cosyvoice synthese-fehler: {e}", flush=True)
            raise HTTPException(500, f"synthese: {e}")
    dauer = time.perf_counter() - t0
    print(f"cosyvoice speak voice={voice} zeichen={len(text)} s={dauer:.2f}", flush=True)
    return Response(
        content=pcm,
        media_type="application/octet-stream",
        headers={"X-Sample-Rate": str(ZIEL_RATE), "X-Engine": "cosyvoice",
                 "X-Dauer-S": f"{dauer:.2f}"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
