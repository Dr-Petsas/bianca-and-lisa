"""Einmalig: eingeschleppte Zeilennummern-Praefixe aus einer Datei entfernen.

Muster: sechs rechtsbuendige Stellen + "|" (auch mehrfach hintereinander), der
Rest der Zeile ist der echte Inhalt samt Einrueckung. Aufruf:
    python tools/_fix_zeilennummern.py <datei> [--schreiben]
"""
import re
import sys
from pathlib import Path

PRAEFIX = re.compile(r"^(?:\s*\d+\|)+")

pfad = Path(sys.argv[1])
schreiben = "--schreiben" in sys.argv
roh = pfad.read_text(encoding="utf-8").splitlines()
neu = [PRAEFIX.sub("", z) for z in roh]
treffer = [i for i, (a, b) in enumerate(zip(roh, neu), 1) if a != b]
print(f"{pfad}: {len(treffer)} Zeilen mit Praefix")
for i in treffer[:6]:
    print(f"  {i}: {roh[i - 1]!r}\n   -> {neu[i - 1]!r}")
if schreiben and treffer:
    pfad.write_text("\n".join(neu) + "\n", encoding="utf-8")
    print("geschrieben")
