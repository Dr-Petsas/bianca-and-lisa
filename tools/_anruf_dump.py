"""Ein Anruf im Klartext (read-only, laeuft im Container).

Aufruf: python3 - <sessionId-Praefix>
"""
import glob
import json
import os
import sys


def kurz(v, n=400):
    t = " ".join(str(v or "").split())
    return t[:n] + ("…" if len(t) > n else "")


praefix = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
treffer = [
    p for p in glob.glob("/app/.data/anrufe/*/*/anruf.json")
    if os.path.basename(os.path.dirname(p)).startswith(praefix)
]
if not treffer:
    print("nichts gefunden fuer", praefix)
    raise SystemExit(1)
p = sorted(treffer, key=os.path.getmtime, reverse=True)[0]
d = json.load(open(p, encoding="utf-8"))
print("=" * 78)
for k in ("sessionId", "startedAt", "endedAt", "dauerMs", "tenant", "mandant",
          "did", "caller", "patientName", "lastBook", "lastCancel", "lastMove",
          "lastNote", "praxisNotiz", "weiterleitungZiel", "warteschleife",
          "begruessungText"):
    if d.get(k) not in (None, "", [], {}):
        print(f"{k}: {kurz(d.get(k), 300)}")
print("=" * 78)
for i, z in enumerate(d.get("zuege") or [], 1):
    off = round((z.get("offsetMs") or 0) / 1000, 1)
    ein = z.get("eingang") or z.get("gehoert") or {}
    if isinstance(ein, dict):
        gehoert = ein.get("text") or ein.get("transkript") or ""
    else:
        gehoert = ein
    print(f"\n--- Zug {i}  t+{off}s ---")
    if gehoert:
        print("  ANRUFER :", kurz(gehoert, 500))
    stt = z.get("stt") or {}
    if isinstance(stt, dict) and stt.get("qwen"):
        q = stt["qwen"]
        print("  (stt    :", kurz({k: q.get(k) for k in ("gewinner", "sperre", "spaet")}, 300), ")")
    for feld in ("vorab", "filler", "warte"):
        if z.get(feld):
            print(f"  {feld:8}:", kurz(z.get(feld), 200))
    print("  BIANCA  :", kurz(z.get("text") or z.get("reply") or "", 700))
    for t in (z.get("tools") or []):
        if isinstance(t, dict):
            print("    tool  :", t.get("name"), t.get("status") or t.get("ok"),
                  kurz({k: v for k, v in t.items()
                        if k not in ("name", "status", "ok", "args", "res")}, 220))
    if z.get("spuren") or z.get("spur"):
        print("    spur  :", kurz(z.get("spuren") or z.get("spur"), 400))
    tim = z.get("timings") or {}
    if tim:
        print("    zeit  :", kurz(tim, 200))
