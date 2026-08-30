"""Parakeet-STT-Dienst fuer Lisa/Bianca — Claras bewaehrte Telefon-Strecke.

Engine wie Claras Produktion (F:\\Clara-Voice providers/stt/streaming.py,
ParakeetStreamingSTT): primeline-parakeet (deutsches TDT-Finetune, 2,95 % WER)
als ONNX ueber onnx-asr auf CPU (~190 ms je Zug auf dem Dev-Rechner; der
5090-Server-CPU ist schneller). Danach dieselben Stufen wie bei Clara:
Whitespace-Normalisierung + Fuzzy-Hotword-Nachkorrektur (postcorrect.py,
Kopie von Claras stt_postcorrect). KEIN Torch, KEINE GPU — das qwen-vLLM
und der TTS-Container auf der 5090 bleiben unberuehrt.

Stille-Trim (W-STT-TRIM 29.08.2026): Vor- und Nachlauf-Stille wird VOR der
Inferenz energie-basiert abgeschnitten (Rand 160/320 ms). Grund: Parakeet-TDT
normalisiert die Log-Mel-Features ueber das GANZE Segment — dominiert Stille
(das Dock schickt Zoeger-Vorlauf + ~0,7 s Nachlauf mit), wird ein kurzes "Ja"
wegnormalisiert (NeMo #15757: leeres oder erfundenes Transkript). Reine
Stille-Blobs werden verworfen statt halluziniert. Notaus: STT_TRIM=0 =>
byte-identisches Alt-Verhalten. Dazu ein Retry-Guard fuer onnx-asr #138
(AssertionError bei bestimmten Eingabelaengen). Abnahme: tests/stt_kurz_probe.py.

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

# Stille-Trim (W-STT-TRIM): Notaus + Tuning. Die Schwellen sind bewusst
# Konstanten (kein Env-Wildwuchs) — nur der Notaus ist eine Umgebungsvariable.
_TRIM_AN = os.environ.get("STT_TRIM", "1").strip() != "0"
_TRIM_FENSTER_MS = 20       # RMS-Fenster
_TRIM_RAND_VORN = 8         # 160 ms Rand vor der Sprache (Plosive nicht koepfen)
_TRIM_RAND_HINTEN = 16      # 320 ms Rand danach (TDT-Decoder braucht Auslauf)
_TRIM_REL_SCHWELLE = 0.05   # aktiv = lauter als 5 % vom Peak ...
_TRIM_ABS_SCHWELLE = 0.003  # ... aber nie unter dem Grundrausch-Boden
# W-STT-SCHWANZ (30.08.2026): die 5-%-Schwelle bestimmte auch die
# SCHNITT-Grenzen — ein leise ausklingendes Nummern-Ende (Stimme senkt
# sich am Satzende um 10-20 dB) unter 5 % vom Peak wurde mitsamt der
# letzten Ziffer weggeschnitten, bevor Parakeet es je sah. Die Raender
# nimmt jetzt eine ZARTE Schwelle (1,5 % vom Peak, nie unter dem
# Grundrausch-Boden); ob ueberhaupt Sprache da ist (Verwerfen-Gates),
# entscheidet weiter die strenge 5-%-Schwelle.
_TRIM_REL_ZART = 0.015      # Schnitt-Grenzen: leiser Sprach-Auslauf bleibt drin
_TRIM_STILLE_PEAK = 0.001   # Peak darunter = reine Stille (z. B. Opus-Leerlauf)
_TRIM_MIN_SPRACHE = 5       # < 5 laute Fenster (100 ms) = Knackser, keine Sprache

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


def _stille_trimmen(audio):
    """Schneidet Vor-/Nachlauf-Stille energie-basiert ab (W-STT-TRIM).

    Rueckgabe: (audio, grund) — grund ist None, wenn nichts zu schneiden war,
    sonst die Log-Zeile ("2960ms->760ms" bzw. "verworfen: ..."). Verworfene
    Segmente (reine Stille, Brummen, Knackser) kommen als leeres Array zurueck,
    damit das Nach-Trim-Gate sauber "" liefert statt zu halluzinieren.
    """
    import numpy as np

    fenster = SAMPLE_RATE * _TRIM_FENSTER_MS // 1000
    n = audio.size // fenster
    if n < 3:
        return audio, None
    rms = np.sqrt(np.mean(audio[: n * fenster].reshape(n, fenster) ** 2, axis=1))
    peak = float(rms.max())
    if peak < _TRIM_STILLE_PEAK:
        return audio[:0], "verworfen: reine stille"
    schwelle = max(peak * _TRIM_REL_SCHWELLE, _TRIM_ABS_SCHWELLE)
    laut = np.flatnonzero(rms > schwelle)
    if laut.size == 0:
        return audio[:0], "verworfen: nur grundrauschen"
    if laut.size < _TRIM_MIN_SPRACHE:
        return audio[:0], f"verworfen: transient {laut.size * _TRIM_FENSTER_MS}ms"
    # W-STT-SCHWANZ: Schnitt-Grenzen ueber die zarte Schwelle — leise
    # An-/Auslaeufe (weiche Anlaute, ausklingende Schluss-Ziffern) bleiben
    # im Segment. zart <= streng, also nur je MEHR Audio, nie weniger.
    zart = np.flatnonzero(rms > max(peak * _TRIM_REL_ZART, _TRIM_ABS_SCHWELLE))
    a = max(0, int(zart[0]) - _TRIM_RAND_VORN) * fenster
    b = min(n, int(zart[-1]) + 1 + _TRIM_RAND_HINTEN) * fenster
    if a == 0 and b >= n * fenster:
        return audio, None
    vorher_ms = audio.size * 1000 // SAMPLE_RATE
    audio = audio[a:b]
    return audio, f"{vorher_ms}ms->{audio.size * 1000 // SAMPLE_RATE}ms"


def _transkribieren(pcm: bytes, keywords: list[str]) -> tuple[str, list, dict]:
    import numpy as np

    # Claras Mindestlaengen-Gate: unter 200 ms gibt es nichts zu verstehen.
    if len(pcm) < SAMPLE_RATE * 2 // 5:
        return "", [], {"unsicher": False, "wort": "", "grund": "", "kandidaten": []}
    audio = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
    if _TRIM_AN:
        audio, trim_grund = _stille_trimmen(audio)
        if trim_grund:
            print(f"trim: {trim_grund}", flush=True)
        # Nach-Trim-Gate: was nach dem Schnitt unter 200 ms liegt, war keine
        # Sprache — leer zurueck, bevor das Modell etwas erfinden kann.
        if audio.size < SAMPLE_RATE // 5:
            return "", [], {"unsicher": False, "wort": "", "grund": "", "kandidaten": []}
    with _LOCK:
        try:
            text = str(_MODEL.recognize(audio, sample_rate=SAMPLE_RATE) or "").strip()
        except AssertionError:
            # onnx-asr #138: bestimmte Eingabelaengen kippen die Laengen-
            # Arithmetik des TDT-Decoders (AssertionError statt Ergebnis).
            # 40 ms Stille hinten dran verschieben die Laenge — ein zweiter
            # Wurf genuegt, statt den ganzen Zug zu verlieren.
            print("recognize: AssertionError (onnx-asr #138), retry +40ms", flush=True)
            audio = np.concatenate(
                [audio, np.zeros(SAMPLE_RATE // 25, dtype=audio.dtype)])
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
        "trim": _TRIM_AN,
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
