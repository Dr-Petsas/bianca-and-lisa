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
from fastapi.responses import Response, StreamingResponse
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
_ALIASE: dict[str, str] = {}
_REGISTRIERT: set[str] = set()
_WARM = False


class SpeakIn(BaseModel):
    text: str
    voice: str = ""


def _stimmen_scannen() -> None:
    """stimmen/cosyvoice/<name>.wav hat Vorrang vor stimmen/<name>.wav.

    CosyVoice braucht KURZE Prompts (~10 s): der Prompt geht in jede
    Synthese ein — ist er laenger als der Sprech-Satz, entstehen Stummel
    und Conv-Fehler (live 28.08.2026). Chatterbox liest nur die Top-Ebene
    (lange Referenzen), dieser Server bevorzugt den Unterordner.
    """
    _VOICES.clear()
    _TRANSKRIPT.clear()
    if not STIMMEN_DIR.is_dir():
        return
    for ordner in (STIMMEN_DIR / "cosyvoice", STIMMEN_DIR):
        if not ordner.is_dir():
            continue
        for w in sorted(ordner.glob("*.wav")):
            name = w.stem.lower()
            if name in _VOICES:
                continue
            txt = w.with_suffix(".txt")
            if not txt.is_file():
                print(f"cosyvoice: {w.name} ohne {txt.name} — Stimme uebersprungen "
                      "(Zero-Shot braucht das Transkript)", flush=True)
                continue
            _VOICES[name] = w
            _TRANSKRIPT[name] = " ".join(txt.read_text(encoding="utf-8").split()).strip()


def _aliase_lesen() -> None:
    """stimmen/aliase.json: {"clara": "bianca"} — mehrere Rufnamen, EIN Klon.

    Ein Alias zeigt auf eine vorhandene Referenz; so teilen sich z. B.
    Clara V7, Demo-Clara und Bianca dieselbe Registrierung.
    """
    _ALIASE.clear()
    datei = STIMMEN_DIR / "aliase.json"
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
        else:
            print(f"alias ignoriert: {a} -> {z} (ziel fehlt oder name belegt)", flush=True)


def _modell_holen() -> None:
    if Path(MODEL_DIR, "cosyvoice3.yaml").is_file() or Path(MODEL_DIR, "cosyvoice2.yaml").is_file():
        return
    print(f"cosyvoice: lade {MODEL_HF} nach {MODEL_DIR} (einmalig) ...", flush=True)
    from huggingface_hub import snapshot_download

    snapshot_download(MODEL_HF, local_dir=MODEL_DIR)


def _load_vllm_sparsam(self, model_dir):
    """Ersatz fuer CosyVoices load_vllm: gleiche Logik, aber die Torch-LLM-
    Gewichte werden VOR dem Engine-Start freigegeben (Upstream: danach) und
    der Torch-Cache geleert. Neben dem grossen qwen-vLLM (25,7 GiB) waren
    sonst beim Engine-Start nur 1,66 GiB frei — zu wenig (live 28.08.2026)."""
    import cosyvoice.cli.model as cv_model

    cv_model.export_cosyvoice2_vllm(self.llm, model_dir, self.device)
    del self.llm.llm.model.model.layers
    torch.cuda.empty_cache()
    from vllm import EngineArgs, LLMEngine

    engine_args = EngineArgs(
        model=model_dir,
        skip_tokenizer_init=True,
        enable_prompt_embeds=True,
        gpu_memory_utilization=float(os.environ.get("COSY_VLLM_GPU_UTIL", "0.08")),
    )
    self.llm.vllm = LLMEngine.from_engine_args(engine_args)
    self.llm.lock = threading.Lock()


def _laden() -> None:
    global _MODEL, _WARM
    import cosyvoice.cli.model as cv_model
    from cosyvoice.cli.cosyvoice import AutoModel

    for _name in ("CosyVoiceModel", "CosyVoice2Model", "CosyVoice3Model"):
        _kls = getattr(cv_model, _name, None)
        if _kls is not None and hasattr(_kls, "load_vllm"):
            _kls.load_vllm = _load_vllm_sparsam

    t0 = time.time()
    _modell_holen()
    # Turbo (28.08.2026): load_vllm gibt den autoregressiven LLM-Teil an eine
    # eigene kleine vLLM-Engine (Export beim ersten Start nach MODEL_DIR/vllm,
    # Speicher via COSY_VLLM_GPU_UTIL), load_trt jagt den Flow-Decoder durch
    # TensorRT (Engine-Bau beim ersten Start, ~Minuten, gecacht im Volume).
    # Notausgaenge: TTS_VLLM=0, TTS_TRT=0, TTS_FP16=0 => wie vorher.
    fp16 = os.environ.get("TTS_FP16", "1").strip() != "0"
    nutze_vllm = os.environ.get("TTS_VLLM", "1").strip() != "0"
    nutze_trt = os.environ.get("TTS_TRT", "1").strip() != "0"
    print(f"cosyvoice lade: fp16={fp16} vllm={nutze_vllm} trt={nutze_trt}", flush=True)
    # Reihenfolge gedreht (Upstream: vllm vor trt): TensorRT braucht beim
    # Engine-Laden freie Puffer und gab neben der vLLM-Reservierung nur ein
    # stilles None zurueck (live 28.08.2026). Also TRT zuerst, vLLM danach —
    # die sparsame load_vllm-Variante gibt vorher die Torch-LLM-Gewichte frei.
    _MODEL = AutoModel(model_dir=MODEL_DIR, fp16=fp16, load_vllm=False, load_trt=nutze_trt)
    if nutze_vllm:
        _MODEL.model.load_vllm(os.path.join(MODEL_DIR, "vllm"))
    _stimmen_scannen()
    _aliase_lesen()
    print(f"cosyvoice geladen in {time.time() - t0:.0f}s, "
          f"stimmen={list(_VOICES)}, aliase={_ALIASE}", flush=True)
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
        "aliase": _ALIASE,
        "device": "cuda",
        "warm": _WARM,
        "vllm": os.environ.get("TTS_VLLM", "1").strip() != "0",
        "trt": os.environ.get("TTS_TRT", "1").strip() != "0",
        "stream": True,
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


@app.post("/speak")
def speak(body: SpeakIn):
    text, voice = _speak_eingang(body)
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


@app.post("/speak-stream")
def speak_stream(body: SpeakIn):
    """Wie /speak, aber chunked: rohe PCM16-Stuecke, sobald sie fertig sind.

    Erster Chunk nach wenigen hundert Millisekunden statt nach der kompletten
    Synthese — der Client (kern/tts.py) baut daraus Haeppchen fuers Dock.
    """
    text, voice = _speak_eingang(body)

    def erzeuger():
        t0 = time.perf_counter()
        erster = 0.0
        with _LOCK:
            try:
                if voice in _REGISTRIERT:
                    gen = _MODEL.inference_zero_shot(text, "", "", zero_shot_spk_id=voice, stream=True)
                else:
                    gen = _MODEL.inference_zero_shot(
                        text, CV3_PRAEFIX + _TRANSKRIPT[voice], str(_VOICES[voice]), stream=True,
                    )
                for out in gen:
                    if not erster:
                        erster = time.perf_counter() - t0
                    yield _pcm16(out["tts_speech"], int(_MODEL.sample_rate))
            except Exception as e:
                # Mitten im Stream gibt es keinen HTTP-Fehler mehr — Abbruch
                # loggen, der Client hoert das fehlende Ende.
                print(f"cosyvoice stream-fehler: {e}", flush=True)
                return
        dauer = time.perf_counter() - t0
        print(f"cosyvoice stream voice={voice} zeichen={len(text)} "
              f"erster_chunk_s={erster:.2f} gesamt_s={dauer:.2f}", flush=True)

    return StreamingResponse(
        erzeuger(),
        media_type="application/octet-stream",
        headers={"X-Sample-Rate": str(ZIEL_RATE), "X-Engine": "cosyvoice"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
