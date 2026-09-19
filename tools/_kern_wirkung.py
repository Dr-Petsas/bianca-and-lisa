"""Vorher/Nachher: Live-Qualitaet vs. konservative Kern-Projektion (read-only).

Nutzt den strengen Tages-Scorer fuer die LIVE-Klasse jedes Gespraechs und
projiziert daraus eine Kern-Klasse NUR mit belegbaren Gruenden:

* Der Kern erfindet keine Abschluesse. Wo live KEIN echtes Tool-Ergebnis
  vorliegt, gibt es auch beim Kern keinen Abschluss.
* Der Kern entfernt strukturelle Dialogdefekte, die die Invarianten +
  Property-Tests garantieren: I1 (Frage zu gefuelltem Feld), Schleifen
  (gleiche Frage 3x), Falsch-Erfolg ohne Beweis.
* Beforderung NUR, wenn ein echtes Ergebnis (book/cancel/move/transfer/notiz)
  vorliegt und der Live-Malus ausschliesslich Dialogreibung war.
* Cloud-Function-Fehler (write_fehlgeschlagen) kann der Dialog NICHT heilen.

Buckets: super / gut / mittel(=durchwachsen) / schlecht(=unvollstaendig+fehlerhaft).
Abschluss = super+gut (sauber geloest).
"""
from __future__ import annotations

import json
import os
from collections import Counter

import tages_scorer as ts

ROOT = "/app/.data/anrufe/bianca" if os.path.isdir("/app") else ".data/anrufe/bianca"

MAP = {"super": "super", "gut": "gut", "durchwachsen": "mittel",
       "unvollstaendig": "schlecht", "fehlerhaft": "schlecht"}


def _loops(b: ts.Bewertung) -> bool:
    marker = ("frage_wiederholt", "presence", "sonst_noch", "unklar")
    return any(any(m in g for m in marker) for g in (b.gruende + b.reibungen))


def projiziere(m: dict, b: ts.Bewertung) -> tuple[str, str]:
    """gibt (kern_bucket, grund) zurueck."""
    live = MAP.get(b.klasse, "schlecht")
    ev = set(b.evidenz)
    hart = bool(ev & {"book", "cancel", "move", "transfer"})
    notiz = "note" in ev
    krs = m.get("kernReplaySummary") or {}
    i1 = int(krs.get("i1") or 0) > 0
    schl = int(krs.get("schleifen") or 0) > 0 or _loops(b)
    write_fail = any(g.startswith("write_fehlgeschlagen") for g in b.gruende)
    false_ok = any(g.startswith("erfolg_ohne_beweis") for g in b.gruende)

    if b.klasse == "fehlerhaft":
        if write_fail and not hart:
            return "schlecht", "cf_fehler_nicht_dialog"
        if hart:
            return "gut", "echtes_ergebnis_ohne_schleife"
        if notiz:
            return "gut", "ehrliche_notiz_ohne_schleife"
        if false_ok:
            return "mittel", "kein_falsch_erfolg_ehrlich"
        if i1 or schl:
            return "mittel", "keine_schleife_besser_gefuehrt"
        return "schlecht", "kein_ergebnis"
    if b.klasse == "durchwachsen":
        if (hart or notiz) and (i1 or schl or b.reibungen):
            return "gut", "reibung_um_echtes_ergebnis_entfaellt"
        return "mittel", "unveraendert"
    return live, "unveraendert"


def main() -> int:
    fs = []
    if os.path.isdir(ROOT):
        for d in sorted(os.listdir(ROOT)):
            p = os.path.join(ROOT, d, "anruf.json")
            if os.path.isfile(p):
                fs.append(p)
    live_ct: Counter = Counter()
    kern_ct: Counter = Counter()
    gewertet = 0
    beispiele: list = []
    for p in fs:
        try:
            m = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if m.get("testAnruf"):
            continue
        b = ts.bewerten(m, session_id=str(m.get("id") or ""))
        if not b.gewertet:
            continue
        gewertet += 1
        lb = MAP.get(b.klasse, "schlecht")
        kb, grund = projiziere(m, b)
        live_ct[lb] += 1
        kern_ct[kb] += 1
        if lb != kb and len(beispiele) < 15:
            beispiele.append((str(m.get("id") or "")[:12], b.praxis, lb, kb, grund))

    def pct(n):
        return round(100.0 * n / gewertet, 1) if gewertet else 0.0

    reihen = ("super", "gut", "mittel", "schlecht")
    print("=" * 64)
    print(f" KERN-WIRKUNG  gewertete Gespraeche = {gewertet}")
    print("=" * 64)
    print(f" {'bucket':10s} {'live n':>7s} {'live %':>7s} {'kern n':>7s} {'kern %':>7s} {'d%pt':>6s}")
    print("-" * 64)
    for k in reihen:
        dl = pct(live_ct[k]); dk = pct(kern_ct[k])
        print(f" {k:10s} {live_ct[k]:7d} {dl:7.1f} {kern_ct[k]:7d} {dk:7.1f} {dk-dl:+6.1f}")
    print("-" * 64)
    la = live_ct["super"] + live_ct["gut"]
    ka = kern_ct["super"] + kern_ct["gut"]
    print(f" Abschluss (super+gut):  live {la} ({pct(la)}%)  ->  kern {ka} ({pct(ka)}%)")
    if la:
        print(f" Relativ mehr Abschluesse: {round(100.0*(ka-la)/la,1):+}%  (absolut +{ka-la})")
    ls = live_ct["schlecht"]; ks = kern_ct["schlecht"]
    print(f" Schlecht:  live {ls} ({pct(ls)}%)  ->  kern {ks} ({pct(ks)}%)  ({round(100.0*(ks-ls)/ls,1) if ls else 0:+}% )")
    print("=" * 64)
    print(" Beispiel-Verschiebungen (sid, praxis, live->kern, grund):")
    for sid, prx, lb, kb, grund in beispiele:
        print(f"   {sid}  {prx:9s} {lb:8s}->{kb:8s}  {grund}")
    print("=" * 64)
    # Maschinenlesbar fuer die E-Mail
    out = {
        "gewertet": gewertet,
        "live": {k: live_ct[k] for k in reihen},
        "kern": {k: kern_ct[k] for k in reihen},
        "abschlussLive": la, "abschlussKern": ka,
    }
    print("JSON " + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
