import json
import urllib.request

raw = urllib.request.urlopen("http://127.0.0.1:8096/api/last-call", timeout=10).read()
d = json.loads(raw)
c = d.get("call") or d
print("sid", c.get("sessionId") or c.get("id"))
print("started", c.get("startedAt"))
print("name", c.get("patientName"))
print("pcid", c.get("phoneCallId"))
print("sammler", json.dumps(c.get("sammler") or {}, ensure_ascii=False)[:800])
print("anrufer", json.dumps(c.get("anrufer") or {}, ensure_ascii=False)[:400])
print("lastBook", json.dumps(c.get("lastBook") or {}, ensure_ascii=False)[:500])
print("lastNote", json.dumps(c.get("lastNote") or {}, ensure_ascii=False)[:400])
print("---")
for i, z in enumerate(c.get("zuege") or []):
    inn = (z.get("textIn") or "").replace("\n", " ")
    out = (z.get("text") or "").replace("\n", " ")
    w = [x.get("w") for x in (z.get("waechter") or []) if isinstance(x, dict)]
    print(f"{i:02d} {z.get('art')} IN: {inn}")
    print(f"   OUT: {out}")
    if w:
        print(f"   W: {w}")
