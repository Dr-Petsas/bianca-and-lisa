"""Anrufer-Audio fuer den Baukasten-Test: (Stimme, Text) -> WAV mit Cache.

Gerendert wird on demand ueber den Qwen3-TTS-Container (TTS_BASE, blocking
/speak) mit den Anrufer-Klonen aus tts_serve/stimmen/. Jeder Render laeuft
durch dieselbe Pegel-Schicht wie live (kern.tts.pcm16_wav) und landet unter
tests/baukasten/audio/<stimme>/<hash>.wav plus .txt-Beizettel — einmal
gerendert, fuer immer wiederverwendbar (Engine-Wechsel = neuer Hash, weil
die TTS-Basis im Schluessel steckt).
"""

from __future__ import annotations

import hashlib
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from kern.config import TTS_BASE  # noqa: E402
from kern.tts import pcm16_wav  # noqa: E402
from tests.baukasten import saetze  # noqa: E402

AUDIO_DIR = Path(__file__).resolve().parent / "audio"
PCM_RATE = 24000

# Qwen3-TTS bricht lange Renders nach ~8 s ab (Modell-Deckel) — der
# Grunewald-Buchstabier-Satz endete live bei "L wie" und Bianca lief in
# den Frage-Loop. Texte ueber dieser Laenge werden deshalb an Komma-/
# Satz-Fugen gestueckelt, einzeln gerendert und mit kurzer Pause gefuegt.
_HAPPEN_ZEICHEN = 80
_PAUSE_S = 0.22


def _happen(text: str) -> list[str]:
    """Langen Text an Satz-/Komma-Fugen in TTS-sichere Haeppchen teilen."""
    if len(text) <= _HAPPEN_ZEICHEN:
        return [text]
    teile = re.split(r"(?<=[.!?,;:])\s+", text)
    out: list[str] = []
    akt = ""
    for t in teile:
        if akt and len(akt) + 1 + len(t) > _HAPPEN_ZEICHEN:
            out.append(akt)
            akt = t
        else:
            akt = f"{akt} {t}".strip()
    if akt:
        out.append(akt)
    return out


def _schluessel(stimme: str, text: str) -> str:
    roh = f"{TTS_BASE}|{stimme}|{' '.join(text.split())}"
    return hashlib.sha1(roh.encode("utf-8")).hexdigest()[:20]


def audio_pfad(stimme: str, text: str) -> Path:
    return AUDIO_DIR / stimme / f"{_schluessel(stimme, text)}.wav"


def audio_holen(stimme: str, text: str, *, timeout: float = 180.0) -> Path:
    """WAV-Pfad fuer den Satz — rendert nur, wenn er nicht im Cache liegt."""
    if not TTS_BASE:
        raise RuntimeError("TTS_BASE fehlt — Baukasten-Audio braucht den lokalen Container.")
    pfad = audio_pfad(stimme, text)
    if pfad.is_file() and pfad.stat().st_size > 44:
        return pfad
    pfad.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    pcm = b""
    pause = b"\x00\x00" * int(PCM_RATE * _PAUSE_S)
    for i, teil in enumerate(_happen(text)):
        r = httpx.post(f"{TTS_BASE}/speak", json={"text": teil, "voice": stimme},
                       timeout=timeout)
        r.raise_for_status()
        if i:
            pcm += pause
        pcm += r.content
    wav = pcm16_wav(pcm)
    if len(wav) <= 44:
        raise RuntimeError(f"leerer Render fuer {stimme}: {text!r}")
    tmp = pfad.with_suffix(".tmp")
    tmp.write_bytes(wav)
    tmp.replace(pfad)
    pfad.with_suffix(".txt").write_text(text, encoding="utf-8")
    print(f"baukasten-klang: {stimme} {len(wav) / (PCM_RATE * 2):.1f}s "
          f"render={time.perf_counter() - t0:.1f}s {pfad.name}", flush=True)
    return pfad


def dauer_s(pfad: Path) -> float:
    """Spieldauer eines eigenen PCM16-WAV (44-Byte-Header, 24 kHz mono)."""
    try:
        groesse = pfad.stat().st_size
    except OSError:
        return 0.0
    return max(0.0, (groesse - 44) / (PCM_RATE * 2))


def vorwaermen(stimme: str, texte: list[str]) -> list[Path]:
    """Eine Satzliste fuer eine Stimme vorab rendern (Cache fuellen)."""
    return [audio_holen(stimme, t) for t in texte]


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Baukasten-Audio rendern/probieren")
    p.add_argument("--stimme", default="markus")
    p.add_argument("--text", default="")
    p.add_argument("--probe", action="store_true",
                   help="einen Testsatz mit allen acht Anrufer-Stimmen rendern")
    a = p.parse_args()

    if a.probe:
        satz = saetze.EROEFFNUNG_MACHEN[0]
        for s in saetze.STIMMEN_M + saetze.STIMMEN_W:
            audio_holen(s, satz)
        return
    if a.text:
        pfad = audio_holen(a.stimme, a.text)
        print(pfad)
        return
    p.print_help()


if __name__ == "__main__":
    main()
