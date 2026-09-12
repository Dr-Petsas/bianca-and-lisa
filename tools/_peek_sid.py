"""Einen Anruf voll ausgeben. SID=..."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
SID = (os.environ.get("SID") or "a47707f114954785a237766e6930fa77").strip()


def main() -> None:
    p = ROOT / SID / "anruf.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    print("sid", SID)
    print("started", m.get("startedAt"))
    print("ended", m.get("endedAt"))
    print("name", m.get("patientName"))
    print("pcid", m.get("phoneCallId"))
    print("sammler", json.dumps(m.get("sammler") or {}, ensure_ascii=False))
    print("lastBook", json.dumps(m.get("lastBook") or {}, ensure_ascii=False)[:2000])
    print("praxisNotiz", (m.get("praxisNotiz") or "")[:500])
    print("---TOOLS---")
    for t in m.get("tools") or []:
        if not isinstance(t, dict):
            continue
        print(" TOOL", t.get("name"), "ok=", t.get("ok"),
              "spoken=", (t.get("spoken") or "")[:180])
        disp = t.get("dispatch") or {}
        req = disp.get("request") or {}
        resp = disp.get("response") or {}
        name = str(t.get("name") or "")
        if any(x in name.lower() for x in ("book", "slot", "motiv")):
            print("  req", json.dumps(req, ensure_ascii=False)[:800])
            print("  resp", json.dumps(resp, ensure_ascii=False)[:1000])
        if t.get("args"):
            print("  args", json.dumps(t.get("args"), ensure_ascii=False)[:500])
    print("---TURNS---")
    for i, z in enumerate(m.get("zuege") or []):
        inn = (z.get("textIn") or "").replace("\n", " ")
        out = (z.get("text") or "").replace("\n", " ")
        tm = z.get("timings") or {}
        w = [x.get("w") for x in (z.get("waechter") or [])]
        print(f"{i:02d} {z.get('art')} tot={tm.get('total')} w={w}")
        print(f"   IN : {inn}")
        print(f"   OUT: {out}")
        if z.get("book"):
            print("   BOOK", json.dumps(z.get("book"), ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
