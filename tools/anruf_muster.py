"""Zaehlt die Fehlermuster der laufenden Befund-Sammlung ueber echte Bianca-Anrufe.

Nur lesend: holt die Mitschnitte ueber die Live-API (`/api/anrufe`),
Testanrufe (`testAnruf`) bleiben draussen. Musterkatalog und Belege:
`docs/BEFUND-SAMMLUNG-LAUFEND.md`.

    python tools/anruf_muster.py 2026-09-22 2026-09-29      # Zeitraum (Tage inkl.)
    python tools/anruf_muster.py --ids a8fa761f 881ade70     # einzelne Anrufe (Praefix reicht)
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

BASE = "http://pickadoc1.tail22c4dd.ts.net:8096/api/anrufe"

NAMENSFRAGE = re.compile(
    r"(wie hei(ß|ss)t|wie ist (der|ihr) .*name|unter wem|vollst(ä|a)ndige name|vor- und nachnamen)", re.I)
PRAEFIX = r"(Meine Frage war|Noch einmal die Frage|Ich frage noch einmal|Kurz zurück zur Frage|Damit ich weiterkomme)"
PRAEFIX_DOPPELT = re.compile(rf"{PRAEFIX}: {PRAEFIX}")
NEUE_PLUS_BEZUG = re.compile(r"Ich bin (die|der) Neue! (Verstehe|Alles klar|Gerne|In Ordnung|Mhm)")
VERBINDEN = re.compile(r"(verbinden|durchstellen|mitarbeiter)", re.I)

MUSTER = {
    "M1": "Antwort auf eine LLM-Frage gegen veraltete Maschinen-Frage bewertet",
    "M2": "Erledigte Aufgabe, danach Auto-Resume einer Schein-Aufgabe",
    "M3": "Nachfrage-Vorsaetze gestapelt",
    "M4": "Sprachwache verworfen -> Nachfrage (ohne Anruferaudio)",
    "M4a": "davon mitten in Biancas eigener Ansage",
    "M5": "Verbindungswunsch ohne Ergebnis (Buchung/Absage/Verschiebung/Notiz)",
    "M6": "\"Ich bin die Neue!\" + Bezugswort",
    "M7": "Ganzsatz-Belehrung",
    "M8": "Qwen lernt Phrase -> Kleinwort (Verdacht Fehl-Lernen)",
    "M9": "Antwort im selben Anruf wortgleich wiederholt",
}


def _json(url: str):
    return json.load(urllib.request.urlopen(url, timeout=30))


def _tage(von: str, bis: str) -> tuple[str, ...]:
    a, b = date.fromisoformat(von), date.fromisoformat(bis)
    return tuple((a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1))


def _laden(sid: str):
    try:
        return _json(f"{BASE}/{sid}")["anruf"]
    except Exception:
        return None


def _waechter(z: dict) -> list[str]:
    return [x.get("w") for x in z.get("waechter") or [] if isinstance(x, dict)]


def pruefen(m: dict, treffer) -> None:
    sid = m.get("id", "")
    zuege = [z for z in m.get("zuege") or [] if isinstance(z, dict)]
    gesagt: set[str] = set()
    erledigt = False
    for i, z in enumerate(zuege):
        nr, w, text = z.get("nr"), _waechter(z), z.get("text") or ""
        vorher = zuege[i - 1] if i else {}
        if NAMENSFRAGE.search(vorher.get("text") or "") and ({"talk-unklar", "ja-nein-unklar"} & set(w)):
            treffer("M1", sid, nr)
        if "auto-resume" in w and erledigt:
            treffer("M2", sid, nr)
        book = z.get("book") or {}
        erledigt = erledigt or bool(book.get("cancelled") or book.get("booked") or book.get("moved"))
        if PRAEFIX_DOPPELT.search(text):
            treffer("M3", sid, nr)
        if "stt-sprachwache" in w and not z.get("audioIn") and i:
            treffer("M4", sid, nr)
            ende = (vorher.get("offsetMs") or 0) + sum(a.get("ms", 0) for a in vorher.get("audioOut") or [])
            if (z.get("offsetMs") or 0) < ende:
                treffer("M4a", sid, nr)
        if NEUE_PLUS_BEZUG.search(text):
            treffer("M6", sid, nr)
        if "ganzsatz-waechter" in w:
            treffer("M7", sid, nr)
        for g in ((z.get("stt") or {}).get("qwen") or {}).get("spaet", {}).get("gelernt") or []:
            links, _, rechts = g.partition("->")
            if " " in links and rechts[:1].islower():
                treffer("M8", sid, nr)
        if z.get("art") == "listen" and text and text in gesagt:
            treffer("M9", sid, nr)
        if text:
            gesagt.add(text)
    if VERBINDEN.search(" ".join(z.get("textIn") or "" for z in zuege)):
        if not any(m.get(k) for k in ("praxisNotiz", "lastBook", "lastCancel", "lastMove")):
            treffer("M5", sid, 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("von", nargs="?")
    ap.add_argument("bis", nargs="?")
    ap.add_argument("--ids", nargs="*")
    args = ap.parse_args()

    liste = _json(BASE)["anrufe"]
    if args.ids:
        auswahl = [a for a in liste if any(a["id"].startswith(p) for p in args.ids)]
    else:
        heute = date.today().isoformat()
        tage = _tage(args.von or heute, args.bis or args.von or heute)
        auswahl = [a for a in liste if str(a.get("startedAt", ""))[:10] in tage and not a.get("testAnruf")]
    with ThreadPoolExecutor(8) as ex:
        anrufe = [m for m in ex.map(_laden, [a["id"] for a in auswahl]) if m]

    zaehler: Counter[str] = Counter()
    belege: dict[str, list[str]] = {}

    def treffer(key: str, sid: str, nr) -> None:
        zaehler[key] += 1
        belege.setdefault(key, []).append(f"{sid[:8]}/z{nr}" if nr else sid[:8])

    for m in anrufe:
        pruefen(m, treffer)

    mandanten = Counter(m.get("tenantId", "") for m in anrufe)
    verbinden = sum(1 for m in anrufe if VERBINDEN.search(" ".join(z.get("textIn") or "" for z in m.get("zuege") or [])))
    print(f"Anrufe: {len(anrufe)} | Mandanten: {dict(mandanten)} | mit Verbindungswunsch: {verbinden}")
    for key, titel in MUSTER.items():
        n = zaehler.get(key, 0)
        print(f"{key:4s} {n:4d}  {titel}  {', '.join(belege.get(key, [])[:8])}")


if __name__ == "__main__":
    main()
