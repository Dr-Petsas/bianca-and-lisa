"""Schatten-Entscheidungen eines Anrufs zeigen (read-only, laeuft im Container).

Ohne Argument: der neueste Schatten-Lauf.
"""
import glob
import json
import os
import sys

praefix = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
dateien = sorted(
    glob.glob("/app/.data/controller-shadow/**/*.jsonl", recursive=True)
    + glob.glob("/app/.data/controller-shadow/*.json*"),
    key=os.path.getmtime,
    reverse=True,
)
if not dateien:
    print("kein Schatten-Log gefunden")
    raise SystemExit(1)

zeilen: list[dict] = []
for p in dateien[:6]:
    try:
        with open(p, encoding="utf-8") as fh:
            for roh in fh:
                roh = roh.strip()
                if not roh:
                    continue
                try:
                    d = json.loads(roh)
                except Exception:
                    continue
                sid = str(d.get("sessionId") or d.get("sid") or "")
                if praefix and not sid.startswith(praefix):
                    continue
                zeilen.append(d)
    except Exception as exc:
        print("KAPUTT", p, exc)
    if zeilen and praefix:
        break

if not zeilen:
    print("nichts fuer", praefix or "(neueste)")
    raise SystemExit(1)

if not praefix:
    letzte = str(zeilen[0].get("sessionId") or zeilen[0].get("sid") or "")
    zeilen = [z for z in zeilen
              if str(z.get("sessionId") or z.get("sid") or "") == letzte]
    print("Sitzung:", letzte)

for z in zeilen[:40]:
    def k(v, n=220):
        return " ".join(str(v or "").split())[:n]
    print("-", "zug", z.get("zug"), "|", k(z.get("gehoert") or z.get("text")))
    print("   kern:", k(z.get("kernText") or z.get("sprich") or z.get("antwort")))
    for feld in ("grund", "naechste", "tool", "task", "stockZahl", "uebergeben",
                 "intent", "abweichung"):
        if z.get(feld) not in (None, "", [], {}):
            print(f"   {feld}: {k(z.get(feld), 160)}")
