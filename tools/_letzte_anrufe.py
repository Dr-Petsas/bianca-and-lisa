"""Kurzuebersicht der letzten Anrufe (read-only, laeuft im Container)."""
import glob
import json
import os
import sys

n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
pfade = sorted(
    glob.glob("/app/.data/anrufe/*/*/anruf.json"),
    key=os.path.getmtime,
    reverse=True,
)[:n]
for p in pfade:
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as exc:
        print("KAPUTT", p, exc)
        continue
    sid = str(d.get("sessionId") or os.path.basename(os.path.dirname(p)))
    zuege = d.get("zuege") or []
    print(
        sid[:12],
        d.get("startedAt"),
        "dauer", round((d.get("dauerMs") or 0) / 1000),
        "s | tenant", d.get("tenant") or d.get("mandant") or "?",
        "| did", d.get("did") or "-",
        "| zuege", len(zuege),
        "| patient", d.get("patientName") or "-",
        "| book", bool(d.get("lastBook")),
        "| notiz", bool(d.get("praxisNotiz")),
    )
