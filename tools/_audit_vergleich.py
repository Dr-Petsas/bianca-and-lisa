"""Gepaarte Auswertung: Live-Verhalten gegen Kern-Verhalten, Anruf fuer Anruf.

Read-only. Liest das Audit-JSON (tools/kern_audit.py lauf) und stellt je Anruf
gegenueber, wer sich festgefahren hat: die Live-Bianca oder der neue Kern.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def lade(pfad: str) -> dict:
    return json.loads(Path(pfad).read_text(encoding="utf-8"))


def quote(a: int, b: int) -> str:
    return f"{100 * a / max(1, b):5.1f} %"


def main(pfad: str) -> int:
    d = lade(pfad)
    bs = d["calls"]
    g = d["summary"]
    n = len(bs)

    # ---- Die drei harten Schleifen-Klassen, gepaart -----------------------
    live_schleife = [b for b in bs if b["live"]["schleife"]]
    live_wortgl = [b for b in bs if b["live"]["wortgleich_max"] >= 2]
    kern_schleife = [b for b in bs if b["frage_ueber_budget"]]
    kern_wortgl = [b for b in bs if b["wortgleich"]]

    print("=" * 70)
    print(f" GEPAARTER VERGLEICH  n={n} Anrufe, {g['anrufer_zuege']} Anrufersaetze")
    print("=" * 70)
    print(f"{'Fehlklasse':38s} {'Live':>10s} {'Kern':>10s}")
    print("-" * 70)
    print(f"{'Anrufe mit Frage-Schleife (3x+)':38s} {len(live_schleife):10d} {len(kern_schleife):10d}")
    print(f"{'  laengster Frage-Lauf':38s} {g['live']['frage_max']:10d} {g['frage_max']:10d}")
    print(f"{'Anrufe mit wortgleicher Doppelung':38s} {len(live_wortgl):10d} {len(kern_wortgl):10d}")
    print(f"{'  laengster wortgleicher Lauf':38s} {g['live']['wortgleich_max']:10d} "
          f"{max(b['wortgleich_max'] for b in bs):10d}")
    print(f"{'Abstuerze':38s} {'-':>10s} {g['crash']:10d}")
    print(f"{'stumme Zuege':38s} {'-':>10s} {g['stumm']:10d}")

    # ---- Was macht der Kern in genau den Anrufen, die Live entglitten? ----
    print()
    print("-- Die 213 Live-Schleifen-Anrufe im Kern ---------------------------")
    geheilt = [b for b in live_schleife if b["souveraen"]]
    mit_aufsicht = [b for b in live_schleife if b["aufsicht"]]
    abgegeben = [b for b in live_schleife if b["uebergeben"]]
    print(f"   souveraen (keine der 4 Fehlklassen):  {len(geheilt):4d} / {len(live_schleife)}"
          f"   {quote(len(geheilt), len(live_schleife))}")
    print(f"   davon Aufsicht hat eingegriffen:      {len(mit_aufsicht):4d}")
    print(f"   davon ehrlich an Legacy abgegeben:    {len(abgegeben):4d}")
    art: dict[str, int] = {}
    for b in live_schleife:
        art[b["ende_art"]] = art.get(b["ende_art"], 0) + 1
    print(f"   Ausgang:                              {dict(sorted(art.items(), key=lambda x: -x[1]))}")

    # ---- Wie die Aufsicht greift ------------------------------------------
    print()
    print("-- Eingriffe der Aufsicht (Gesamtkorpus) --------------------------")
    for k, v in sorted(g["aufsicht"].items(), key=lambda x: -x[1]):
        print(f"   {k:20s} {v:5d}")
    print(f"   Anrufe mit Eingriff:  {g['aufsicht_anrufe']} / {n}  {quote(g['aufsicht_anrufe'], n)}")

    # ---- Reichweite: wie weit traegt der Kern selbst ----------------------
    print()
    print("-- Reichweite des Kerns -------------------------------------------")
    print(f"   selbst getragene Zuege:   {g['getragen']} / {g['anrufer_zuege']}"
          f"   {quote(g['getragen'], g['anrufer_zuege'])}")
    print(f"   Ende der Zustaendigkeit:  {g['ende_art']}")
    print(f"   Aufgabe am Ende offen:    {g['offen_am_ende']}  {quote(g['offen_am_ende'], n)}")

    # ---- Abgabegruende ---------------------------------------------------
    gr: dict[str, int] = {}
    for b in bs:
        for r in b["uebergeben_gruende"]:
            kurz = str(r).split(":")[0]
            gr[kurz] = gr.get(kurz, 0) + 1
    print()
    print("-- Warum gibt der Kern ab? ----------------------------------------")
    for k, v in sorted(gr.items(), key=lambda x: -x[1])[:10]:
        print(f"   {k:24s} {v:5d}")

    # ---- Ehrlichkeit: was ist NICHT gemessen ------------------------------
    print()
    print("-- Grenzen dieser Messung -----------------------------------------")
    print(f"   Zuege, in denen der Kern etwas anderes fragte als Live: {g['off_policy']}"
          f"  ({quote(g['off_policy'], g['getragen'])} der getragenen Zuege)")
    print("   Dort passt die echte Anrufer-Antwort nicht auf die Kern-Frage.")
    print("   Folge: Buchungs-/Abschlussquoten sind NICHT vergleichbar,")
    print("   Schleifen-/Absturz-/Stille-Zahlen sind es (haerter als echt).")
    print(f"   Live gebucht (echt):          {g['live']['gebucht']} Anrufe")
    print(f"   Schreibvorgaenge im Sim:      {g['writes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ".data/audit-regel9.json"))
