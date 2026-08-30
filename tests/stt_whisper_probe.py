"""Live-Probe W-STT-WHISPER: echter Whisper-Stream-Container + Parakeet-Rueckfall.

Schickt einen per Windows-SAPI gebauten deutschen Testsatz durch den ECHTEN
Adapter (kern/stt.py) — einmal ueber den Whisper-Container (Standard: die
Tailscale-IP des Dev-Rechners, derselbe Weg, den pickadoc1 nimmt) und einmal
mit absichtlich totem Whisper-Ziel, um den automatischen Parakeet-Rueckfall
zu sehen. Schreibt nichts, bucht nichts.

Aufruf: .venv\\Scripts\\python tests\\stt_whisper_probe.py
        [--whisper ws://100.81.214.94:8092] [--parakeet http://...:8212]
Exit 0 = beide Wege gruen.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import kern.stt as stt  # noqa: E402
from kern.config import STT_BASE  # noqa: E402

DATEN = pathlib.Path(__file__).resolve().parent / "daten"
SATZ = "Ich haette gern einen Termin bei Doktor Petsas am Dienstag um neun Uhr."
DATEI = "termin_petsas_hedda.wav"
KEYWORDS = "Petsas,Nikolaou,Patrikis"


def _sapi_bauen(pfad: pathlib.Path, text: str) -> None:
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.SelectVoice('Microsoft Hedda Desktop'); "
        "$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        "[System.Speech.AudioFormat.AudioChannel]::Mono); "
        f"$s.SetOutputToWaveFile('{pfad}', $fmt); $s.Speak('{text}'); $s.Dispose()"
    )
    pfad.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=30)


def _lauf(name: str, blob: bytes) -> tuple[str, float]:
    start = time.perf_counter()
    text = stt.transcribe(blob, mime="audio/wav", name="probe.wav", keywords=KEYWORDS)
    dauer = time.perf_counter() - start
    print(f"  {name:<22} {dauer:5.2f}s -> {text!r}")
    return text, dauer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--whisper", default="ws://100.81.214.94:8092")
    ap.add_argument("--parakeet", default=STT_BASE)
    args = ap.parse_args()

    pfad = DATEN / DATEI
    if not pfad.exists():
        _sapi_bauen(pfad, SATZ)
    blob = pfad.read_bytes()
    rot = 0

    print(f"Whisper-Weg ({args.whisper}):")
    stt.STT_WHISPER_BASE = args.whisper
    stt.STT_BASE = args.parakeet
    stt._whisper_pause_bis = 0.0
    text, _ = _lauf("whisper", blob)
    if "Termin" not in text or "Petsas" not in text:
        print("  ROT: Soll-Woerter (Termin, Petsas) fehlen")
        rot += 1

    print(f"Rueckfall-Weg (Whisper tot -> Parakeet {args.parakeet}):")
    stt.STT_WHISPER_BASE = "ws://127.0.0.1:9"  # nichts lauscht dort
    stt._whisper_pause_bis = 0.0
    text, dauer = _lauf("fallback", blob)
    if "Termin" not in text:
        print("  ROT: Parakeet-Rueckfall hat nicht uebernommen")
        rot += 1
    if stt._whisper_pause_bis <= time.time():
        print("  ROT: Whisper-Pause wurde nicht gesetzt")
        rot += 1
    text, dauer = _lauf("fallback (pausiert)", blob)
    if dauer > 3.0:
        print("  ROT: pausierter Whisper darf keinen Connect-Timeout kosten")
        rot += 1

    print("ALLES GRUEN" if rot == 0 else f"{rot} Probe(n) ROT")
    return 0 if rot == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
