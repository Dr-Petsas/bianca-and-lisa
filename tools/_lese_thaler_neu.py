"""Thaler-Anrufe seit dem letzten Deploy (heute nach 11:00 UTC)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
AB = datetime(2026, 9, 8, 11, 0, 0, tzinfo=timezone.utc)


def _dt(s: str):
    t = (s or "").strip()
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def main() -> None:
    rows = []
    if ROOT.is_dir():
        for d in ROOT.iterdir():
            p = d / "anruf.json"
            if not p.is_file():
                continue
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            start = _dt(m.get("startedAt") or "")
            if not start or start < AB:
                continue
            blob = json.dumps(m, ensure_ascii=False).lower()
            if "thaler" not in blob:
                continue
            rows.append((start, d.name, m))
    rows.sort(key=lambda x: x[0])
    print(f"n={len(rows)} ab={AB.isoformat()}")
    for start, sid, m in rows:
        print("=" * 72)
        print(start.isoformat(), "dir", sid, "pcid", m.get("phoneCallId"), "name", m.get("patientName"))
        print("sammler", json.dumps(m.get("sammler") or {}, ensure_ascii=False)[:600])
        print("anrufer", json.dumps(m.get("anrufer") or {}, ensure_ascii=False)[:400])
        print("lastBook", json.dumps(m.get("lastBook") or {}, ensure_ascii=False)[:500])
        print("lastNote", json.dumps(m.get("lastNote") or {}, ensure_ascii=False)[:400])
        print("praxisNotiz", (m.get("praxisNotiz") or "")[:300])
        tools = m.get("tools") or []
        for t in tools:
            if not isinstance(t, dict):
                continue
            print(" TOOL", t.get("name"), "ok=", t.get("ok"),
                  "spoken=", (t.get("spoken") or "")[:140])
            req = ((t.get("dispatch") or {}).get("request") or {})
            if req.get("visitMotiveId") or req.get("visitMotiveName"):
                print("  motiv", req.get("visitMotiveId"), req.get("visitMotiveName"))
        for i, z in enumerate(m.get("zuege") or []):
            if not isinstance(z, dict):
                continue
            inn = (z.get("textIn") or "").replace("\n", " ")
            out = (z.get("text") or "").replace("\n", " ")
            w = [x.get("w") for x in (z.get("waechter") or []) if isinstance(x, dict)]
            print(f"{i:02d} {z.get('art')} IN: {inn}")
            print(f"   OUT: {out}")
            if w:
                print(f"   W: {w}")


if __name__ == "__main__":
    main()
