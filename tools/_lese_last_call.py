"""Letzten Bianca-Anruf oder Treffer auf Name ausgeben."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
SUCHE = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()


def _dt(s: str):
    t = (s or "").strip()
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def _dump(m: dict) -> None:
    print("sid", m.get("sessionId") or "-")
    print("started", m.get("startedAt"))
    print("name", m.get("patientName"))
    print("pcid", m.get("phoneCallId"))
    print("sammler", json.dumps(m.get("sammler") or {}, ensure_ascii=False))
    print("anrufer", json.dumps(m.get("anrufer") or {}, ensure_ascii=False))
    print("---")
    for i, z in enumerate(m.get("zuege") or []):
        if not isinstance(z, dict):
            continue
        inn = (z.get("textIn") or "").replace("\n", " ")
        out = (z.get("text") or "").replace("\n", " ")
        w = z.get("waechter") or []
        print(f"{i:02d} {z.get('art')} IN: {inn}")
        print(f"   OUT: {out}")
        if w:
            print(f"   W: {w}")


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
            if not start:
                continue
            blob = json.dumps(m, ensure_ascii=False).lower()
            if SUCHE and SUCHE not in blob:
                continue
            rows.append((start, m))
    rows.sort(key=lambda x: x[0])
    if not rows:
        print("kein_treffer")
        return
    print(f"treffer={len(rows)} suche={SUCHE or '-'}")
    _dump(rows[-1][1])


if __name__ == "__main__":
    main()
