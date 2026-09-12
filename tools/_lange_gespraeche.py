"""Liest die Anruf-Manifeste und listet die laengsten Gespraeche.

Laeuft IM bianca-Container (read-only):
    ssh pickadoc1 "docker exec -i telefonki-bianca-1 python3 -" < tools/_lange_gespraeche.py
"""
import json
import os

BASIS = "/app/.data/anrufe/bianca"

reihen = []
for name in os.listdir(BASIS):
    pfad = os.path.join(BASIS, name, "anruf.json")
    if not os.path.exists(pfad):
        continue
    try:
        with open(pfad, encoding="utf-8") as fh:
            m = json.load(fh)
    except Exception:
        continue
    zuege = m.get("zuege") or []
    reihen.append((
        len(zuege),
        str(m.get("startedAt") or "")[:19],
        name,
        round((m.get("dauerMs") or 0) / 1000),
        str(m.get("patientName") or ""),
    ))

reihen.sort(reverse=True)
print("zuege  start                sessionId                         dauer_s  name")
for r in reihen[:25]:
    print(f"{r[0]:5d}  {r[1]:19s}  {r[2]}  {r[3]:7d}  {r[4]}")
