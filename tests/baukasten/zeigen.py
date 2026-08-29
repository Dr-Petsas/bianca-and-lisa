"""Bericht eines Baukasten-Laufs kompakt in der Konsole zeigen.

Aufruf: python -m tests.baukasten.zeigen [<lauf-id-oder-pfad>] [--voll]
Ohne Argument: der neueste Lauf. Zeigt je Story die Checks und den
Gespraechsverlauf mit Latenzen, Waechter-Spur und STT-Abweichungen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.baukasten.runner import BERICHTE_DIR  # noqa: E402


def _bericht_zeigen(pfad: Path, voll: bool = False) -> None:
    b = json.loads(pfad.read_text(encoding="utf-8"))
    erg = b.get("ergebnis") or {}
    print(f"\n=== {b.get('id')} — {'GRUEN' if erg.get('ok') else 'ROT'} "
          f"(Zuege {erg.get('zuege')}, Latenz max {erg.get('latenzMaxS')}s, "
          f"mittel {erg.get('latenzMittelS')}s)")
    if b.get("fehler"):
        print(f"  FEHLER: {b['fehler'][:300]}")
    for c in erg.get("checks") or []:
        merk = "ok " if c.get("ok") else "ROT"
        rest = ""
        if c.get("soll") or c.get("ist"):
            rest = f"  soll={c.get('soll')!r} ist={c.get('ist')!r}"
        print(f"  [{merk}] {c.get('name')}{rest}")
    if erg.get("waechter"):
        print(f"  Waechter im Anruf: {', '.join(erg['waechter'])}")
    print("  --- Verlauf:")
    for z in b.get("zuege") or []:
        wer = z.get("wer") or "?"
        text = (z.get("text") or "").replace("\n", " ")
        if not voll and len(text) > 110:
            text = text[:110] + "…"
        zeile = f"  {wer:8s} {text!r}"
        if wer == "bianca":
            if z.get("warte"):
                zeile = f"  {wer:8s} (haelt still — Halbsatz-Wache)"
            if z.get("latenzS") is not None:
                zeile += f"  [lat {z.get('latenzS')}s"
                if z.get("ersterTonS") is not None:
                    zeile += f", Ton {z.get('ersterTonS')}s"
                zeile += "]"
            w = [e.get("w") for e in (z.get("waechter") or [])]
            if w:
                zeile += f"  W:{','.join(w)}"
            if z.get("frage"):
                zeile += f"  frage={z.get('frage')}"
            book = z.get("book") or {}
            if isinstance(book, dict) and (book.get("booked") or book.get("cancelled") or book.get("moved")):
                zeile += f"  BOOK={ {k: v for k, v in book.items() if k in ('booked', 'cancelled', 'moved', 'slotIso')} }"
        else:
            if z.get("baustein"):
                zeile += f"  [{z['baustein']}]"
            gehoert = z.get("gehoert")
            if gehoert is not None and gehoert.strip() and gehoert.strip() != (z.get("text") or "").strip():
                zeile += f"\n           GEHOERT: {gehoert!r}"
        print(zeile)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("lauf", nargs="?", default="", help="Lauf-Id oder Pfad (leer = neuester)")
    p.add_argument("--voll", action="store_true", help="Texte nicht kuerzen")
    a = p.parse_args()

    if a.lauf and Path(a.lauf).is_file():
        _bericht_zeigen(Path(a.lauf), a.voll)
        return
    lauf_dir = (BERICHTE_DIR / a.lauf) if a.lauf else None
    if not lauf_dir or not lauf_dir.is_dir():
        kandidaten = sorted([d for d in BERICHTE_DIR.iterdir() if d.is_dir()],
                            key=lambda d: d.name) if BERICHTE_DIR.is_dir() else []
        if not kandidaten:
            print("keine Berichte gefunden")
            return
        lauf_dir = kandidaten[-1]
    print(f"Lauf: {lauf_dir.name}")
    for bericht in sorted(lauf_dir.glob("*/bericht.json")):
        _bericht_zeigen(bericht, a.voll)


if __name__ == "__main__":
    main()
