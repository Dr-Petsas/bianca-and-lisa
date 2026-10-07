"""W-RESAMPLE A/B: linear (audioop) gegen soxr fuer 8 -> 16 kHz vor Parakeet.

Laeuft IM bianca-test-Container (TTS_BASE/STT_BASE, ffmpeg, audioop):
  python /tmp/rs/_probe_resampler_ab.py /tmp/rs/skripte.json /tmp/rs/stimme.py

Saetze aus ohr_korpus/skripte.json, gesprochen von Anrufer-Stimmen, dann
telefoniert (300-3400 Hz, 8 kHz, A-law hin und zurueck). Vier Wege je Satz:
linear+EQ (live bis 07.10.), soxr+EQ (neu), linear ohne EQ, soxr ohne EQ.
Schreibt nichts ausser /tmp/rs/.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

import httpx

sys.path.insert(0, "/app")
from kern import tenants  # noqa: E402

AUS = Path("/tmp/rs")
CACHE = AUS / "pcm"
CACHE.mkdir(parents=True, exist_ok=True)
STIMMEN = ["andreas", "julia", "petra", "sabine", "thomas",
           "juergen", "stefan", "markus", "lena", "mann"]
MAX_SAETZE = int(os.environ.get("MAX_SAETZE", "120"))


def _stimme_laden(pfad: str):
    spec = importlib.util.spec_from_file_location("stimme_neu", pfad)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _saetze(pfad: str) -> list[tuple[str, str]]:
    daten = json.loads(Path(pfad).read_text(encoding="utf-8"))
    gesehen, aus = set(), []
    for skript in daten.get("skripte") or []:
        praxis = skript.get("praxis") or "meddent"
        for zug in skript.get("zuege") or []:
            satz = (zug.get("sage") or "").strip()
            if len(satz.split()) < 2 or satz in gesehen:
                continue
            gesehen.add(satz)
            aus.append((praxis, satz))
    return aus[:MAX_SAETZE]


def _tts(http: httpx.Client, text: str, stimme: str, i: int) -> bytes:
    datei = CACHE / f"{i:03d}_{stimme}.pcm"
    if datei.exists():
        return datei.read_bytes()
    r = http.post(f"{os.environ['TTS_BASE'].rstrip('/')}/speak",
                  json={"text": text, "voice": stimme}, timeout=60)
    r.raise_for_status()
    datei.write_bytes(r.content)
    time.sleep(0.3)
    return r.content


def _rauschen(pcm24: bytes, snr_db: float, saat: int) -> bytes:
    """Weisses Rauschen mit festem Abstand zum Sprach-RMS (deterministisch)."""
    import array
    import random

    x = array.array("h")
    x.frombytes(pcm24)
    if not x:
        return pcm24
    rms = (sum(v * v for v in x) / len(x)) ** 0.5
    sigma = rms / (10 ** (snr_db / 20))
    zufall = random.Random(saat)
    aus = array.array("h", (
        max(-32768, min(32767, int(v + zufall.gauss(0.0, sigma)))) for v in x))
    return aus.tobytes()


def _telefon(pcm24: bytes) -> bytes:
    alaw = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", "pipe:0",
         "-af", "highpass=f=300:poles=2,lowpass=f=3400:poles=2,"
                "aresample=8000:resampler=soxr:precision=28",
         "-c:a", "pcm_alaw", "-f", "alaw", "-ar", "8000", "pipe:1"],
        input=pcm24, capture_output=True, check=True).stdout
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "alaw", "-ar", "8000", "-ac", "1", "-i", "pipe:0",
         "-f", "s16le", "-ar", "8000", "-ac", "1", "pipe:1"],
        input=alaw, capture_output=True, check=True).stdout


def _wav(pcm: bytes, rate: int) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return b.getvalue()


def _stt(http: httpx.Client, pcm16: bytes, keywords: list[str]) -> str:
    r = http.post(f"{os.environ['STT_BASE'].rstrip('/')}/transcribe",
                  files={"file": ("zug.wav", _wav(pcm16, 16000), "audio/wav")},
                  data={"keywords": ",".join(keywords)}, timeout=60)
    r.raise_for_status()
    return str(r.json().get("text") or "")


def _woerter(t: str) -> list[str]:
    t = t.lower().replace("ß", "ss")
    return [w for w in re.split(r"[^0-9a-zäöü]+", t) if w]


def _fehler(ref: list[str], hyp: list[str]) -> int:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        vor, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            vor, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, vor + (r != h))
    return d[-1]


def main() -> None:
    saetze = _saetze(sys.argv[1])
    stim = _stimme_laden(sys.argv[2])
    wege = {
        "linear+eq": (True, "linear"),
        "soxr+eq": (True, "soxr"),
        "linear": (False, "linear"),
        "soxr": (False, "soxr"),
    }
    summe = {k: [0, 0] for k in wege}
    zeit = {k: 0.0 for k in wege}
    unterschiede = []
    kw_cache: dict[str, list[str]] = {}
    with httpx.Client() as http:
        for i, (praxis, satz) in enumerate(saetze):
            if praxis not in kw_cache:
                kw_cache[praxis] = tenants.stt_keywords(tenants.laden(praxis))
            pcm24 = _tts(http, satz, STIMMEN[i % len(STIMMEN)], i)
            if os.environ.get("RAUSCH_SNR"):
                pcm24 = _rauschen(pcm24, float(os.environ["RAUSCH_SNR"]), i)
            pcm8 = _telefon(pcm24)
            ref = _woerter(satz)
            zeile = {"satz": satz, "stimme": STIMMEN[i % len(STIMMEN)]}
            for name, (eq, resampler) in wege.items():
                stim.BRIDGE_STIMME = eq
                stim.BRIDGE_RESAMPLER = resampler
                t0 = time.perf_counter()
                pcm16 = stim.fuer_stt(pcm8, 8000, 16000)
                zeit[name] += time.perf_counter() - t0
                text = _stt(http, pcm16, kw_cache[praxis])
                f = _fehler(ref, _woerter(text))
                summe[name][0] += f
                summe[name][1] += len(ref)
                zeile[name] = (f, text)
            if zeile["linear+eq"][0] != zeile["soxr+eq"][0]:
                unterschiede.append(zeile)
            print(f"{i + 1}/{len(saetze)} " + " ".join(
                f"{k}={zeile[k][0]}" for k in wege), flush=True)
    n = len(saetze)
    bericht = {
        "saetze": n,
        "wer": {k: round(100 * f / max(w, 1), 2) for k, (f, w) in summe.items()},
        "fehler": {k: f for k, (f, _) in summe.items()},
        "woerter": summe["linear+eq"][1],
        "msJeZug": {k: round(1000 * zeit[k] / max(n, 1), 1) for k in wege},
        "unterschiede": unterschiede,
    }
    bericht["rauschSnrDb"] = os.environ.get("RAUSCH_SNR") or None
    (AUS / f"bericht{os.environ.get('RAUSCH_SNR') or ''}.json").write_text(
        json.dumps(bericht, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in bericht.items() if k != "unterschiede"},
                     ensure_ascii=False))
    for z in unterschiede:
        print(f"- [{z['stimme']}] {z['satz']}")
        print(f"    linear+eq ({z['linear+eq'][0]}): {z['linear+eq'][1]}")
        print(f"    soxr+eq   ({z['soxr+eq'][0]}): {z['soxr+eq'][1]}")


if __name__ == "__main__":
    main()
