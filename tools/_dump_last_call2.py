#!/usr/bin/env python3
"""Dump last call + download MP3."""
import json
import pathlib
import urllib.parse
import urllib.request

import httpx

BASE = "http://127.0.0.1:8096"

d = json.load(urllib.request.urlopen(BASE + "/api/last-call", timeout=10))
c = d.get("call") or {}
print("session", c.get("sessionId"), "started", c.get("startedAt"))
print("patient", c.get("patientName"), c.get("patientId"))
for i, z in enumerate(c.get("zuege") or []):
    art = z.get("art")
    tin = (z.get("textIn") or "")[:120]
    tout = (z.get("text") or z.get("note") or "")[:160]
    t = z.get("timings") or {}
    print(f"{i:02d} {art:8} stt={t.get('stt')} llm={t.get('llm')} tts={t.get('tts')} cache={t.get('ttsCache')}")
    if tin:
        print("   IN :", tin)
    if tout:
        print("   OUT:", tout)
    if z.get("book"):
        print("   BOOK:", z.get("book"))
print("sammler", json.dumps(c.get("sammler"), ensure_ascii=False))
print("lastCancel", c.get("lastCancel"))
print("lastMove", c.get("lastMove"))
print("lastBook", c.get("lastBook"))

# phoneCallId from logs / sit — try last from agentprofil via docker logs later
pathlib.Path("/tmp/last-call.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote /tmp/last-call.json")
