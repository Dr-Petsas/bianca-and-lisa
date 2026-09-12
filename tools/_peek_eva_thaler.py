"""Letztes Bianca-Gespraech Eva Thaler (im Container)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")


def _dt(s: str):
    t = (s or "").strip()
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def _name(m: dict) -> str:
    n = str(m.get("patientName") or "")
    an = m.get("anrufer") if isinstance(m.get("anrufer"), dict) else {}
    return f"{n} {an.get('vorname') or ''} {an.get('nachname') or ''}".lower()


def main() -> None:
    hits = []
    if not ROOT.is_dir():
        print("kein_ordner")
        return
    for d in ROOT.iterdir():
        p = d / "anruf.json"
        if not p.is_file():
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "thaler" not in _name(m) and "eva" not in _name(m):
            continue
        start = _dt(m.get("startedAt") or "")
        hits.append((start or datetime.min, d, m))
    hits.sort(key=lambda x: x[0])
    print(f"hits={len(hits)}")
    if not hits:
        # letzte 8 Anrufe als Fallback
        alle = []
        for d in ROOT.iterdir():
            p = d / "anruf.json"
            if not p.is_file():
                continue
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            start = _dt(m.get("startedAt") or "")
            alle.append((start or datetime.min, d.name, m.get("patientName"), m.get("phoneCallId")))
        alle.sort()
        print("letzte:")
        for start, sid, name, pcid in alle[-12:]:
            print(start.isoformat()[:19] if start != datetime.min else "?", sid, name, pcid)
        return
    start, d, m = hits[-1]
    print("sid", d.name)
    print("started", m.get("startedAt"))
    print("ended", m.get("endedAt"))
    print("name", m.get("patientName"))
    print("pcid", m.get("phoneCallId"))
    print("sammler", json.dumps(m.get("sammler") or {}, ensure_ascii=False)[:2000])
    print("lastBook", json.dumps(m.get("lastBook") or {}, ensure_ascii=False)[:1500])
    print("praxisNotiz", (m.get("praxisNotiz") or "")[:400])
    print("---TOOLS---")
    for t in m.get("tools") or []:
        if not isinstance(t, dict):
            continue
        print(" TOOL", t.get("name"), "ok=", t.get("ok"),
              "spoken=", (t.get("spoken") or "")[:160],
              "err=", t.get("error") or t.get("note") or "")
        disp = t.get("dispatch") or {}
        req = disp.get("request") or {}
        resp = disp.get("response") or {}
        name = str(t.get("name") or "")
        if any(x in name.lower() for x in ("book", "slot", "motiv", "offer")):
            print("  req", json.dumps(req, ensure_ascii=False)[:700])
            print("  resp", json.dumps(resp, ensure_ascii=False)[:900])
            if t.get("args"):
                print("  args", json.dumps(t.get("args"), ensure_ascii=False)[:400])
    print("---TURNS---")
    for i, z in enumerate(m.get("zuege") or []):
        inn = (z.get("textIn") or "").replace("\n", " ")
        out = (z.get("text") or "").replace("\n", " ")
        tm = z.get("timings") or {}
        w = [x.get("w") for x in (z.get("waechter") or [])]
        print(f"{i:02d} {z.get('art')} stt={tm.get('stt')} llm={tm.get('llm')} tts={tm.get('tts')} tot={tm.get('total')} w={w}")
        print(f"   IN : {inn}")
        print(f"   OUT: {out}")
        if z.get("book"):
            print("   BOOK", json.dumps(z.get("book"), ensure_ascii=False)[:500])


if __name__ == "__main__":
    main()
