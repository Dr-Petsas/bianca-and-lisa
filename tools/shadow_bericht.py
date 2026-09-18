"""Auswerter fuer die Shadow-Protokolle des Dialogkerns (CONTROLLER_SHADOW=1).

Liest die JSONL unter ``.data/controller-shadow/`` (oder ``--dir``) und fasst
zusammen, WO der Live-Fluss schlecht war und WAS der Kern entschieden haette:

  * Fragen zu bereits gefuelltem Feld (I1-Verdacht, live gemessen),
  * dieselbe Frage 3x in Folge (Schleife, live gemessen),
  * Divergenzen zwischen Live-Frage und Kern-Frage,
  * Verteilung nach Mandant und Sitzung.

STRIKT read-only. Schreibt nur, wenn ``--json <pfad>`` gesetzt ist.

Aufruf:
    python tools/shadow_bericht.py                # Textbericht letzte 24h
    python tools/shadow_bericht.py --tage 7       # Fenster 7 Tage
    python tools/shadow_bericht.py --sid <id>     # nur eine Sitzung, Zug fuer Zug
    python tools/shadow_bericht.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


def _lies(dir_: Path, tage: float) -> list[dict[str, Any]]:
    grenze = time.time() - tage * 86400 if tage > 0 else 0.0
    zeilen: list[dict[str, Any]] = []
    for pfad in sorted(dir_.glob("*.jsonl")):
        try:
            for roh in pfad.read_text(encoding="utf-8").splitlines():
                roh = roh.strip()
                if not roh:
                    continue
                try:
                    z = json.loads(roh)
                except Exception:
                    continue
                if float(z.get("ts") or 0) >= grenze:
                    zeilen.append(z)
        except Exception:
            continue
    zeilen.sort(key=lambda z: float(z.get("ts") or 0))
    return zeilen


def _auswerten(zeilen: Iterable[dict[str, Any]]) -> dict[str, Any]:
    z = list(zeilen)
    sids = {r.get("sid") for r in z if r.get("sid")}
    fehler = [r for r in z if r.get("fehler")]
    zuege = [r for r in z if not r.get("fehler")]

    i1 = [r for r in zuege if r.get("live_signale", {}).get("frage_zu_gefuelltem_feld")]
    schleifen = [r for r in zuege if r.get("live_signale", {}).get("schleife")]
    divergenzen = [r for r in zuege if r.get("divergenz_frage")]
    mit_kern = [r for r in zuege if r.get("kern")]

    nach_mandant: dict[str, Counter] = defaultdict(Counter)
    for r in zuege:
        m = r.get("mandant") or "?"
        nach_mandant[m]["zuege"] += 1
        if r.get("live_signale", {}).get("frage_zu_gefuelltem_feld"):
            nach_mandant[m]["frage_zu_gefuelltem_feld"] += 1
        if r.get("live_signale", {}).get("schleife"):
            nach_mandant[m]["schleife"] += 1
        if r.get("divergenz_frage"):
            nach_mandant[m]["divergenz_frage"] += 1

    div_paare = Counter(
        f"{r['divergenz_frage'].get('live')} -> {r['divergenz_frage'].get('kern')}"
        for r in divergenzen
    )

    return {
        "zuege_gesamt": len(zuege),
        "sitzungen": len(sids),
        "fehler": len(fehler),
        "mit_kern": len(mit_kern),
        "frage_zu_gefuelltem_feld": len(i1),
        "schleifen": len(schleifen),
        "divergenzen": len(divergenzen),
        "divergenz_paare": div_paare.most_common(15),
        "nach_mandant": {m: dict(c) for m, c in sorted(nach_mandant.items())},
    }


def _sid_verlauf(zeilen: Iterable[dict[str, Any]], sid: str) -> list[dict[str, Any]]:
    return [r for r in zeilen if r.get("sid") == sid and not r.get("fehler")]


def _druck_bericht(a: dict[str, Any]) -> None:
    print("=" * 60)
    print("SHADOW-BERICHT (Dialogkern vs. Live-Fluss)")
    print("=" * 60)
    print(f"Zuege gesamt        : {a['zuege_gesamt']}")
    print(f"Sitzungen           : {a['sitzungen']}")
    print(f"Kern mitgelaufen    : {a['mit_kern']}")
    print(f"Shadow-Fehler       : {a['fehler']}")
    print("-" * 60)
    print("LIVE-FEHLKLASSEN (am echten Fluss gemessen):")
    print(f"  Frage zu gefuelltem Feld : {a['frage_zu_gefuelltem_feld']}")
    print(f"  Schleife (Frage 3x)      : {a['schleifen']}")
    print("-" * 60)
    print(f"DIVERGENZEN Live vs. Kern  : {a['divergenzen']}")
    for paar, n in a["divergenz_paare"]:
        print(f"    {n:>4}x  {paar}")
    print("-" * 60)
    print("NACH MANDANT:")
    for m, c in a["nach_mandant"].items():
        print(f"  {m or '?':<26} {c}")
    print("=" * 60)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=".data/controller-shadow")
    ap.add_argument("--tage", type=float, default=1.0, help="Zeitfenster in Tagen (0 = alles)")
    ap.add_argument("--sid", default="", help="nur diese Sitzung, Zug fuer Zug")
    ap.add_argument("--json", default="", help="Zusammenfassung als JSON hierhin schreiben")
    args = ap.parse_args()

    d = Path(args.dir)
    if not d.exists():
        print(f"Kein Shadow-Verzeichnis: {d} (CONTROLLER_SHADOW=1 gesetzt? schon Anrufe/Zuege?)")
        return
    zeilen = _lies(d, args.tage)
    if not zeilen:
        print(f"Keine Zeilen im Fenster ({args.tage} Tage) unter {d}.")
        return

    if args.sid:
        verlauf = _sid_verlauf(zeilen, args.sid)
        print(f"Sitzung {args.sid} — {len(verlauf)} Zuege:\n")
        for r in verlauf:
            live = r.get("live", {})
            kern = r.get("kern", {})
            marke = []
            if r.get("divergenz_frage"):
                marke.append("DIVERGENZ")
            if r.get("live_signale", {}).get("frage_zu_gefuelltem_feld"):
                marke.append("I1")
            if r.get("live_signale", {}).get("schleife"):
                marke.append("SCHLEIFE")
            tag = (" [" + ",".join(marke) + "]") if marke else ""
            print(f"  Zug {r.get('zug'):>2} | \"{r.get('roh','')[:48]}\"{tag}")
            print(f"       live: frage={live.get('frage','')!r} "
                  f"{'book ' if live.get('book') else ''}"
                  f"{'hangup ' if live.get('hangup') else ''}"
                  f"{'transfer ' if live.get('transfer') else ''}".rstrip())
            if kern:
                print(f"       kern: {kern.get('frage_id') or kern.get('akt') or kern.get('naechste')}"
                      f"{' (wartet auf Werkzeug)' if kern.get('wartet_auf_werkzeug') else ''}")
        return

    a = _auswerten(zeilen)
    _druck_bericht(a)
    if args.json:
        Path(args.json).write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON geschrieben: {args.json}")


if __name__ == "__main__":
    main()
