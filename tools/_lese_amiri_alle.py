"""Alle Amiri-Anrufe heute ausgeben."""
from __future__ import annotations

import json
from datetime import datetime, timezone
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
            blob = json.dumps(m, ensure_ascii=False).lower()
            if "amiri" not in blob and "miriam" not in blob:
                continue
            start = _dt(m.get("startedAt") or "")
            if not start:
                continue
            rows.append((start, d.name, m))
    rows.sort(key=lambda x: x[0])
    print(f"n={len(rows)}")
    for start, sid, m in rows:
        print("=" * 60)
        print(start.isoformat(), "dir", sid, "pcid", m.get("phoneCallId"), "name", m.get("patientName"))
        print("sammler", json.dumps(m.get("sammler") or {}, ensure_ascii=False)[:400])
        print("anrufer", json.dumps(m.get("anrufer") or {}, ensure_ascii=False)[:400])
        print("lastBook", m.get("lastBook"), "lastNote", m.get("lastNote"))
        print("tools", json.dumps(m.get("tools") or [], ensure_ascii=False)[:800])
        for i, z in enumerate(m.get("zuege") or []):
            if not isinstance(z, dict):
                continue
            inn = (z.get("textIn") or "").replace("\n", " ")
            out = (z.get("text") or "").replace("\n", " ")
            print(f"{i:02d} {z.get('art')} IN: {inn}")
            print(f"   OUT: {out}")


if __name__ == "__main__":
    main()
