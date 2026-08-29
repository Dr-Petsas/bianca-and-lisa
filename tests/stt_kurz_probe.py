"""Kurz-Antwort-Probe gegen den Parakeet-Container (Abnahme W-STT-TRIM).

Genau der Fall, der live wehtat: kurze Antworten ("Ja", "Nein") kommen im
Dock-Blob mit Sekunden Vorlauf-Stille (Anrufer zoegert nach der Frage) und
~0,5-0,7 s Nachlauf-Stille an. Parakeet-TDT normalisiert die Log-Mel-Features
ueber das GANZE Segment — die Stille drueckt das kurze Wort weg (NeMo #15757),
heraus kommt "" oder Muell. Der Container trimmt deshalb seit W-STT-TRIM
energie-basiert (Notaus STT_TRIM=0). Diese Probe prueft je Quell-WAV:

  roh         wie synthetisiert (etwas Rand)             -> Soll-Wort
  eng         Sprache knapp geschnitten (±60 ms)         -> Soll-Wort
  gepolstert  eng + 2 s Vorlauf + 0,7 s Nachlauf Nullen  -> Soll-Wort
  rauschig    wie gepolstert, Stille = leises Rauschen   -> Soll-Wort (Opus-Boden)

dazu einmal:  stille  4 s Nullen -> MUSS leer bleiben.

Quell-WAVs (tests/daten/*_hedda.wav, 16 kHz mono PCM16) baut die Probe bei
Bedarf selbst per Windows-SAPI (Microsoft Hedda Desktop, de-DE) — zum
Neu-Erzeugen einfach loeschen.

Aufruf: .venv\\Scripts\\python tests\\stt_kurz_probe.py [--base http://...:8212]
Exit 0 = alle Proben bestanden. Schreibt nichts, bucht nichts.
"""
from __future__ import annotations

import argparse
import array
import io
import pathlib
import random
import subprocess
import sys
import wave

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kern.config import STT_BASE  # noqa: E402

RATE = 16000
DATEN = pathlib.Path(__file__).resolve().parent / "daten"
# (datei, SAPI-Text, akzeptierte Transkripte). Heddas geclippte Kurzwoerter
# dekodiert Parakeet mal als englische Zwillinge ("Yeah."/"Nine." — phonetisch
# identisch); fuer die Trim-Abnahme zaehlt: nicht leer und stabil ueber alle
# Polster-Varianten. Live-Stimmen + Hotword-Nachkorrektur treffen die
# deutsche Schreibung.
QUELLEN = [
    ("ja_hedda.wav", "Ja", {"ja", "yeah"}),
    ("nein_hedda.wav", "Nein", {"nein", "nine"}),
    ("ja_gerne_hedda.wav", "Ja, gerne", {"ja gerne"}),
]


def _sapi_bauen(pfad: pathlib.Path, wort: str) -> None:
    """Erzeugt das Quell-WAV per Windows-SAPI (nur auf dem Dev-Rechner noetig)."""
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.SelectVoice('Microsoft Hedda Desktop'); "
        "$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        "[System.Speech.AudioFormat.AudioChannel]::Mono); "
        f"$s.SetOutputToWaveFile('{pfad}', $fmt); $s.Speak('{wort}'); $s.Dispose()"
    )
    pfad.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=30)


def _wav_lesen(pfad: pathlib.Path) -> array.array:
    with wave.open(str(pfad), "rb") as w:
        passt = (w.getframerate() == RATE and w.getnchannels() == 1
                 and w.getsampwidth() == 2)
        if not passt:
            raise SystemExit(f"{pfad.name}: erwartet 16 kHz mono PCM16")
        return array.array("h", w.readframes(w.getnframes()))


def _wav_bytes(samples: array.array) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def _sprachgrenzen(samples: array.array) -> tuple[int, int]:
    """Erster/letzter 20-ms-Block ueber 5 % vom Peak (Spiegel des Server-Trims)."""
    fenster = RATE // 50
    bloecke = [max(abs(x) for x in samples[i:i + fenster])
               for i in range(0, len(samples) - fenster + 1, fenster)]
    schwelle = max(max(bloecke) * 0.05, 100)
    laut = [i for i, p in enumerate(bloecke) if p > schwelle]
    if not laut:
        raise SystemExit("Quell-WAV enthaelt keine Sprache")
    return laut[0] * fenster, (laut[-1] + 1) * fenster


def _stille(sekunden: float) -> array.array:
    return array.array("h", bytes(2 * int(RATE * sekunden)))


def _rauschen(sekunden: float, pegel: int = 16) -> array.array:
    """Leiser Zufallsboden (~-60 dBFS), wie ihn der Opus-Decode hinterlaesst."""
    rnd = random.Random(4711)
    return array.array("h", (rnd.randint(-pegel, pegel)
                             for _ in range(int(RATE * sekunden))))


def _varianten(samples: array.array) -> list[tuple[str, array.array]]:
    a, b = _sprachgrenzen(samples)
    rand = RATE * 60 // 1000
    eng = samples[max(0, a - rand):min(len(samples), b + rand)]
    return [
        ("roh", samples),
        ("eng", eng),
        ("gepolstert", _stille(2.0) + eng + _stille(0.7)),
        ("rauschig", _rauschen(2.0) + eng + _rauschen(0.7)),
    ]


def _hoeren(client: httpx.Client, basis: str, samples: array.array) -> tuple[str, float]:
    r = client.post(f"{basis}/transcribe",
                    files={"file": ("probe.wav", _wav_bytes(samples), "audio/wav")})
    r.raise_for_status()
    j = r.json()
    return str(j.get("text", "")), float(j.get("ms") or 0.0)


def _norm(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalpha() or c == " ").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=STT_BASE or "http://192.168.0.246:8212")
    args = ap.parse_args()
    basis = args.base.rstrip("/")

    client = httpx.Client(timeout=30)
    health = client.get(f"{basis}/health").json()
    print(f"Container: {basis}  trim={health.get('trim', 'FEHLT (alter Stand)')}  "
          f"model={health.get('model')}")

    rot = 0
    for datei, sapi_text, akzeptiert in QUELLEN:
        pfad = DATEN / datei
        if not pfad.exists():
            _sapi_bauen(pfad, sapi_text)
        samples = _wav_lesen(pfad)
        label = sorted(akzeptiert)[0]
        for name, probe in _varianten(samples):
            text, ms = _hoeren(client, basis, probe)
            ok = _norm(text) in akzeptiert
            rot += not ok
            print(f"  {label:<8} {name:<10} {len(probe) / RATE:4.1f}s "
                  f"-> {text!r:<18} {ms:6.1f}ms  {'OK' if ok else 'ROT'}")

    text, ms = _hoeren(client, basis, _stille(4.0))
    ok = text == ""
    rot += not ok
    print(f"  stille (4 s Nullen)     -> {text!r:<18} {ms:6.1f}ms  {'OK' if ok else 'ROT'}")

    print(f"\n{'ALLES GRUEN' if rot == 0 else str(rot) + ' Probe(n) ROT'}")
    return 0 if rot == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
