"""Gibt ein Anruf-Manifest als lesbares Protokoll aus (read-only).

    ssh pickadoc1 "docker exec -i -e SID=<sessionId> telefonki-bianca-1 python3 -" < tools/_dump_gespraech.py

Optional: VON/BIS als Zug-Nummern, WAECHTER=1 zeigt die Waechter-Spur.
"""
import json
import os

SID = os.environ.get("SID", "").strip()
VON = int(os.environ.get("VON", "1"))
BIS = int(os.environ.get("BIS", "999"))
MIT_WAECHTER = os.environ.get("WAECHTER", "1") == "1"

pfad = f"/app/.data/anrufe/bianca/{SID}/anruf.json"
with open(pfad, encoding="utf-8") as fh:
    m = json.load(fh)

print("start:", m.get("startedAt"), "dauer_s:", round((m.get("dauerMs") or 0) / 1000))
print("name:", m.get("patientName"))
print("notiz:", m.get("praxisNotiz"))
print("=" * 100)
for z in m.get("zuege") or []:
    nr = z.get("nr") or 0
    if nr < VON or nr > BIS:
        continue
    off = round((z.get("offsetMs") or 0) / 1000)
    ein = str(z.get("textIn") or "").strip()
    aus = str(z.get("text") or "").strip()
    frage = str(z.get("frage") or "")
    print(f"--- #{nr:3d} [{off:5d}s] ({z.get('art')}) frage={frage}")
    if ein:
        print(f"  ANRUFER: {ein}")
    print(f"  BIANCA : {aus or '(STUMM)'}")
    if MIT_WAECHTER and z.get("waechter"):
        for w in z["waechter"]:
            print(f"     * {w}")
