#!/bin/bash
set -e
docker logs --since 60m telefonki-bianca-1 2>&1 | grep -E 'phoneCallId=|listen ok|anrufaudio|verwalten|nicht gefunden|kein Termin|kartei|Behandler|Petzer|Petsas|Patrik|buch|absage|tts-ziffern|weicht' | tail -n 100
echo '==== LAST CALL ===='
curl -sS http://127.0.0.1:8096/api/last-call > /tmp/last-call.json
python3 <<'PY'
import json
c=json.load(open("/tmp/last-call.json"))["call"]
print("session", c["sessionId"], c["startedAt"])
print("patient", c.get("patientName"), c.get("patientId"))
for i,z in enumerate(c.get("zuege") or []):
    t=z.get("timings") or {}
    print(f"{i:02d} {z.get('art'):8} tts={t.get('tts')} cache={t.get('ttsCache')} stt={t.get('stt')} llm={t.get('llm')}")
    if z.get("textIn"): print("  IN ", z["textIn"][:160])
    if z.get("text"): print("  OUT", (z.get("text") or "")[:200])
    if z.get("note"): print("  NOTE", z["note"][:200])
    if z.get("book"): print("  BOOK", z["book"])
print("sammler", json.dumps(c.get("sammler"), ensure_ascii=False))
print("lastBook", c.get("lastBook"))
print("lastCancel", c.get("lastCancel"))
print("lastMove", c.get("lastMove"))
print("lastNote", c.get("lastNote"))
PY
echo '==== MP3s ===='
docker logs --since 90m telefonki-bianca-1 2>&1 | grep 'anrufaudio hochgeladen' | tail -n 8
