import json, glob, os
files = sorted(glob.glob("/app/.data/bianca_sessions/*"), key=os.path.getmtime, reverse=True)[:8]
for f in files:
    d = json.load(open(f, encoding="utf-8"))
    print(os.path.basename(f), "pcid=", d.get("phoneCallId"), "started=", str(d.get("startedAt") or "")[:19], "zuege=", len(d.get("zuege") or []))
print("--- last_call ---")
d = json.load(open("/app/.data/bianca_last_call.json", encoding="utf-8"))
print("sid", d.get("sessionId"))
print("pcid", d.get("phoneCallId"))
print("started", d.get("startedAt"))
print("zuege", len(d.get("zuege") or []))
print("tenant_quelle", (d.get("tenant") or {}).get("_quelle"))
