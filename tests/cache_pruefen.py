"""Platten-Cache-Pruefung: Dauer/Stille je gewarmtem Satz — Ausreisser finden.

Werkzeug aus der Artefakt-Diagnose 28.08.2026: rechnet fuer alle Warm-Texte
(Fueller, Begruessung, feste Maschinen-Fragen) die Cache-Keys nach, misst
die WAVs und markiert unplausible Renders (zu lang fuer den Text oder halb
leer). Aufruf: python tests/cache_pruefen.py [--loeschen]
--loeschen entfernt die markierten Dateien; der naechste Dienststart waermt
sie durchs Runaway-Gate + den Warm-Zweitwurf frisch nach.
"""
from __future__ import annotations

import hashlib
import io
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bianca import gehirn  # noqa: E402
from bianca.greeting import begruessung  # noqa: E402
from kern import filler, sprech, tenants  # noqa: E402
from kern.config import TTS_BASE  # noqa: E402

CACHE = Path(__file__).resolve().parents[1] / ".data" / "tts-cache"


def _messen(blob: bytes) -> tuple[float, float]:
    with wave.open(io.BytesIO(blob)) as w:
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
    samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
    dauer = (len(pcm) // 2) / rate if rate else 0.0
    fenster = max(1, int(rate * 0.02))
    still = gesamt = 0
    for i in range(0, len(samples) - fenster, fenster):
        gesamt += 1
        block = samples[i:i + fenster]
        if (sum(s * s for s in block) / len(block)) ** 0.5 < 300:
            still += 1
    return dauer, 100.0 * still / max(1, gesamt)


def main() -> None:
    loeschen = "--loeschen" in sys.argv[1:]
    t = tenants.laden("meddent")
    texte: dict[str, str] = {}
    for satz in filler.alle_saetze():
        texte[satz] = "filler"
    texte[begruessung(t.get("praxisName") or "")] = "begruessung"
    for satz in gehirn.feste_saetze():
        texte[sprech.sanitize(satz)] = "maschine"
    schlecht = 0
    for text, art in sorted(texte.items(), key=lambda x: x[1]):
        for stimme in ("bianca", "lisa"):
            key = f"lokal|{TTS_BASE}|{stimme}|{text}"
            datei = CACHE / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".wav")
            if not datei.is_file():
                continue
            dauer, still = _messen(datei.read_bytes())
            je_zeichen = dauer / max(1, len(text))
            # Innere Pausen sind legitim (Trim kappt nur Raender) — erst ab
            # deutlicher Leere oder Grauzonen-Tempo gilt der Render als Murks.
            auffaellig = je_zeichen > 0.115 or still > 55.0
            if auffaellig:
                schlecht += 1
                if loeschen:
                    datei.unlink(missing_ok=True)
            marke = "!!" if auffaellig else "  "
            print(f"{marke} {stimme:6s} {art:11s} {dauer:5.2f}s  {je_zeichen*1000:4.0f} ms/Z  "
                  f"still={still:4.1f}%  {text[:60]!r}")
    print(f"\nauffaellig: {schlecht}" + (" — geloescht" if loeschen and schlecht else ""))


if __name__ == "__main__":
    main()
