"""Letzte Bianca-Anrufe mit vollem Transkript (heute nachmittag)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
AB = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)


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
            rows.append((start, d.name, m))
    rows.sort()
    print(f"n={len(rows)} ab={AB.isoformat()}")
    for start, sid, m in rows[-15:]:
        print("=" * 72)
        print(start.isoformat(), "dir", sid, "pcid", m.get("phoneCallId"),
              "name", m.get("patientName"))
        s = m.get("sammler") or {}
        print("sammler", json.dumps({
            "frage": s.get("frage"), "phase": s.get("phase"),
            "modus": s.get("modus"),
            "telefon": s.get("telefon"), "telefonOk": s.get("telefonOk"),
            "telefonOffen": s.get("telefonOffen"),
            "vorname": s.get("vorname"), "nachname": s.get("nachname"),
        }, ensure_ascii=False))
        print("anrufer", json.dumps(m.get("anrufer") or {}, ensure_ascii=False)[:300])
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
