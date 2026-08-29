"""Qwen3-TTS-12Hz-0.6B-Base — Vertrag siehe ../api.md.

Eine Aeusserung, EIN Render (blocking /speak). KEIN Text-Schnitt: Client-
Haeppchen und Server-Stueckelung des TEXTES waren das Genuschel (28.08.2026).

Hybrid (29.08.2026, Chef): Triton-Kerne + CUDA-Graph via qwen3-tts-triton
TritonFasterRunner auf GENAU diesem 0.6B-Base — nicht das Default-1.7B-
CustomVoice, und NICHT generate_voice_clone() des Runners (der laedt ein
zweites ungepatchtes 1.7B-Base). Notaus: TTS_HYBRID=0 => nacktes qwen-tts.
Kein TurboQuant, kein generate_batch.

Phase 2 (29.08.2026): /speak-stream — der GANZE Satz geht rein, AUDIO-Stuecke
kommen raus, sobald der Codec sie liefert (generate_voice_clone_streaming).
Das ist KEIN Text-Schnitt: die Prosodie bleibt ganz, nur die Auslieferung
ist frueher. Muss unter _LOCK laufen — eine GPU, vLLM daneben.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

PORT = int(os.environ.get("TTS_PORT", "8100"))
STIMMEN_DIR = Path(os.environ.get("STIMMEN_DIR", "/stimmen"))
MODEL_ID = os.environ.get("QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base")
SPRACHE = os.environ.get("TTS_SPRACHE", "German")
ZIEL_RATE = 24000
# Nur die produktiven Stimmen — quizmaster/mann wuerden nur Warmlauf fressen.
_STIMMEN = ("bianca", "lisa")

app = FastAPI(title="tts-qwen3")

_LOCK = threading.Lock()
_MODEL = None
_HYBRID = False
_VOICES: dict[str, Path] = {}
_TRANSKRIPT: dict[str, str] = {}
_ALIASE: dict[str, str] = {}
_PROMPTS: dict[str, object] = {}
_WARM = False


class SpeakIn(BaseModel):
    text: str
    voice: str = ""


def _stimmen_scannen() -> None:
    """Kurze Cosy-Referenzen zuerst, sonst Top-Level-WAVs."""
    _VOICES.clear()
    _TRANSKRIPT.clear()
    if not STIMMEN_DIR.is_dir():
        return
    for ordner in (STIMMEN_DIR / "cosyvoice", STIMMEN_DIR):
        if not ordner.is_dir():
            continue
        for name in _STIMMEN:
            if name in _VOICES:
                continue
            wav = ordner / f"{name}.wav"
            if not wav.is_file():
                continue
            txt = wav.with_suffix(".txt")
            _VOICES[name] = wav
            _TRANSKRIPT[name] = (
                " ".join(txt.read_text(encoding="utf-8").split()).strip()
                if txt.is_file() else ""
            )


def _aliase_lesen() -> None:
    datei = STIMMEN_DIR / "aliase.json"
    _ALIASE.clear()
    if not datei.is_file():
        return
    import json
    try:
        roh = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"aliase.json unlesbar: {e}", flush=True)
        return
    for alias, ziel in dict(roh).items():
        a, z = str(alias).strip().lower(), str(ziel).strip().lower()
        if z in _VOICES and a not in _VOICES:
            _ALIASE[a] = z


def _hybrid_gewollt() -> bool:
    return os.environ.get("TTS_HYBRID", "1").strip() != "0"


def _laden_hybrid() -> object:
    """Triton + CUDA-Graph auf dem 0.6B-Base. Wirft, wenn Import/Load knallt."""
    from qwen3_tts_triton import TritonFasterRunner

    # patch_range=None: alle Layer. Der Runner-Default (0, 24) gilt fuer
    # 1.7B/28 Layer — auf 0.6B waeren das zu viele Indizes oder die
    # falsche Aussprache-Reserve.
    runner = TritonFasterRunner(
        model_id=MODEL_ID,
        device="cuda",
        dtype="bf16",
        enable_turboquant=False,
        patch_range=None,
    )
    runner.load_model()
    model = runner.model
    if model is None:
        raise RuntimeError("TritonFasterRunner.model ist leer")
    return model


def _laden_nackt() -> object:
    from qwen_tts import Qwen3TTSModel

    return Qwen3TTSModel.from_pretrained(
        MODEL_ID, device_map="cuda:0", dtype=torch.bfloat16,
    )


def _laden() -> None:
    global _MODEL, _WARM, _HYBRID
    t0 = time.time()
    _HYBRID = False
    if _hybrid_gewollt():
        try:
            _MODEL = _laden_hybrid()
            _HYBRID = True
            print("qwen3-tts: hybrid (triton + cuda graph) "
                  f"modell={MODEL_ID}", flush=True)
        except Exception as e:
            print(f"qwen3-tts: hybrid fehlgeschlagen ({type(e).__name__}: {e}) "
                  "— nacktes qwen-tts", flush=True)
            _MODEL = None
    if _MODEL is None:
        _MODEL = _laden_nackt()
        print("qwen3-tts: sdpa (kein flash-attn, kein hybrid)", flush=True)
    _stimmen_scannen()
    _aliase_lesen()
    print(f"qwen3-tts geladen in {time.time() - t0:.0f}s, "
          f"hybrid={_HYBRID} stimmen={list(_VOICES)}, aliase={_ALIASE}",
          flush=True)
    for name in _VOICES:
        try:
            t1 = time.time()
            ref = str(_VOICES[name])
            txt = _TRANSKRIPT[name]
            if hasattr(_MODEL, "create_voice_clone_prompt") and txt:
                _PROMPTS[name] = _MODEL.create_voice_clone_prompt(
                    ref_audio=ref, ref_text=txt,
                )
            _synthese("Guten Tag, einen kleinen Moment bitte.", name)
            print(f"qwen3-tts warm {name} in {time.time() - t1:.1f}s", flush=True)
        except Exception as e:
            print(f"qwen3-tts warmlauf {name} fehlgeschlagen: {e}", flush=True)
    _WARM = True


def _synthese(text: str, voice: str) -> bytes:
    """Text -> PCM16 mono 24 kHz. Muss unter _LOCK laufen."""
    wavs, sr = _MODEL.generate_voice_clone(**_synthese_kwargs(text, voice))
    wav = wavs[0] if isinstance(wavs, (list, tuple)) else wavs
    return _pcm16(wav, int(sr))


def _pcm16(wav, rate: int) -> bytes:
    if torch.is_tensor(wav):
        if wav.dim() > 1:
            wav = wav.squeeze()
        arr = wav.detach().float().cpu().numpy()
    else:
        arr = np.asarray(wav, dtype=np.float32).reshape(-1)
    if rate != ZIEL_RATE and rate > 0:
        n = int(round(len(arr) * ZIEL_RATE / rate))
        if n > 1 and len(arr) > 1:
            arr = np.interp(
                np.linspace(0, 1, n, endpoint=False),
                np.linspace(0, 1, len(arr), endpoint=False),
                arr,
            )
    arr = np.clip(arr, -1.0, 1.0)
    return (arr * 32767.0).astype(np.int16).tobytes()


@app.on_event("startup")
def _startup() -> None:
    threading.Thread(target=_laden, daemon=True).start()


@app.get("/health")
def health():
    ok = _MODEL is not None
    body = {
        "ok": ok,
        "engine": "qwen3-hybrid" if _HYBRID else "qwen3",
        "model": MODEL_ID,
        "voices": sorted(_VOICES) if ok else [],
        "aliase": _ALIASE,
        "device": "cuda",
        "warm": _WARM,
        "hybrid": _HYBRID,
        # Audio-Chunk-Streaming (Phase 2): ganzer Satz rein, PCM-Stuecke
        # raus. Text-Haeppchen (Genuschel 28.08.2026) bleiben verboten.
        "stream": bool(ok and _stream_faehig()),
    }
    if not ok:
        raise HTTPException(503, "modell laedt noch")
    return body


def _speak_eingang(body: SpeakIn) -> tuple[str, str]:
    if _MODEL is None:
        raise HTTPException(503, "modell laedt noch")
    text = " ".join((body.text or "").split()).strip()
    if not text:
        raise HTTPException(400, "text fehlt")
    voice = (body.voice or "").strip().lower() or (sorted(_VOICES)[0] if _VOICES else "")
    voice = _ALIASE.get(voice, voice)
    if voice not in _VOICES:
        raise HTTPException(400, f"stimme unbekannt: {voice}")
    return text, voice


def _stream_faehig() -> bool:
    return _MODEL is not None and hasattr(_MODEL, "generate_voice_clone_streaming")


def _synthese_kwargs(text: str, voice: str) -> dict:
    kw: dict = {"text": text, "language": SPRACHE}
    if voice in _PROMPTS:
        kw["voice_clone_prompt"] = _PROMPTS[voice]
    else:
        kw["ref_audio"] = str(_VOICES[voice])
        if _TRANSKRIPT[voice]:
            kw["ref_text"] = _TRANSKRIPT[voice]
        else:
            kw["x_vector_only_mode"] = True
    return kw


@app.post("/speak-stream")
def speak_stream(body: SpeakIn):
    """Ganzer Satz -> PCM16-Stuecke (chunked), sobald der Codec sie liefert."""
    text, voice = _speak_eingang(body)
    if not _stream_faehig():
        raise HTTPException(501, "streaming nur im hybrid-modus")

    def gen():
        t0 = time.perf_counter()
        erster = -1.0
        gesamt = 0
        with _LOCK:
            try:
                for stueck, sr, _timing in _MODEL.generate_voice_clone_streaming(
                    **_synthese_kwargs(text, voice)
                ):
                    pcm = _pcm16(stueck, int(sr))
                    if not pcm:
                        continue
                    if erster < 0:
                        erster = time.perf_counter() - t0
                    gesamt += len(pcm)
                    yield pcm
            except Exception as e:
                # Mitten im Chunked-Response laesst sich kein 500 mehr senden —
                # Abbruch loggen, der Client hoert den Satz unvollstaendig.
                print(f"qwen3-tts stream-fehler: {e}", flush=True)
                return
        print(f"qwen3-tts stream voice={voice} zeichen={len(text)} "
              f"ttfa={erster:.2f}s gesamt={time.perf_counter() - t0:.2f}s "
              f"bytes={gesamt}", flush=True)

    return StreamingResponse(
        gen(),
        media_type="application/octet-stream",
        headers={"X-Sample-Rate": str(ZIEL_RATE),
                 "X-Engine": "qwen3-hybrid",
                 "X-Accel-Buffering": "no"},
    )


@app.post("/speak")
def speak(body: SpeakIn):
    text, voice = _speak_eingang(body)
    t0 = time.perf_counter()
    with _LOCK:
        try:
            pcm = _synthese(text, voice)
        except Exception as e:
            print(f"qwen3-tts synthese-fehler: {e}", flush=True)
            raise HTTPException(500, f"synthese: {e}")
    dauer = time.perf_counter() - t0
    print(f"qwen3-tts speak voice={voice} hybrid={_HYBRID} "
          f"zeichen={len(text)} s={dauer:.2f}", flush=True)
    return Response(
        content=pcm,
        media_type="application/octet-stream",
        headers={"X-Sample-Rate": str(ZIEL_RATE),
                 "X-Engine": "qwen3-hybrid" if _HYBRID else "qwen3",
                 "X-Dauer-S": f"{dauer:.2f}"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
