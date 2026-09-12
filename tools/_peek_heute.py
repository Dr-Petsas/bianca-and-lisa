"""Letzte Bianca-Anrufe + Transkript (auf pickadoc1 im Container)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
AB = datetime(2026, 9, 7, 22, 0, 0, tzinfo=timezone.utc)


def _dt(s: str):
    t = (s or "").strip()
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def main() -> None:
    if not ROOT.is_dir():
        print("kein_ordner")
        return
    rows = []
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
        rows.append((start, d, m))
    rows.sort(key=lambda x: x[0])
    print(f"n={len(rows)}")
    for start, d, m in rows:
        zuege = [z for z in (m.get("zuege") or []) if isinstance(z, dict)]
        listen = [z for z in zuege if z.get("art") == "listen"]
        print("---")
        print(
            start.isoformat()[:19],
            d.name,
            "name=", m.get("patientName") or "-",
            "pcid=", m.get("phoneCallId") or "-",
            "listen=", len(listen),
        )
        an = m.get("anrufer")
        if isinstance(an, dict):
            print("  anrufer", an)
        for z in zuege:
            inn = (z.get("textIn") or "").replace("\n", " ")
            out = (z.get("text") or "").replace("\n", " ")
            print(f"  {z.get('art')} IN={inn!r}")
            print(f"       OUT={out!r}")


if __name__ == "__main__":
    main()
