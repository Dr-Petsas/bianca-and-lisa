"""Alle Bianca-Anrufe ab 08.09. 08:00 UTC, inkl. Transkript-Stichwort."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
AB = datetime(2026, 9, 8, 6, 0, 0, tzinfo=timezone.utc)


def _dt(s: str):
    t = (s or "").strip()
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def _blob(m: dict) -> str:
    teile = [str(m.get("patientName") or "")]
    for z in m.get("zuege") or []:
        if isinstance(z, dict):
            teile.append(str(z.get("textIn") or ""))
            teile.append(str(z.get("text") or ""))
    start = m.get("zuege") or []
    if start and isinstance(start[0], dict):
        teile.append(str(start[0].get("text") or ""))
    return " ".join(teile).lower()


def main() -> None:
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
    rows.sort()
    print(f"n={len(rows)}")
    for start, d, m in rows:
        blob = _blob(m)
        mark = []
        if "thaler" in blob:
            mark.append("THALER")
        if "zahnersatz" in blob or "besprechung" in blob:
            mark.append("ZE")
        if "noch dran" in blob:
            mark.append("STUPS")
        if "schmerz" in blob or "akut" in blob:
            mark.append("AKUT")
        print("---")
        print(start.isoformat()[:19], d.name, "name=", m.get("patientName"),
              "pcid=", m.get("phoneCallId"), " ".join(mark))
        gruss = ""
        zuege = m.get("zuege") or []
        if zuege and isinstance(zuege[0], dict):
            gruss = (zuege[0].get("text") or "")[:120]
        print("  gruss", gruss)
        for z in zuege:
            if not isinstance(z, dict):
                continue
            inn = (z.get("textIn") or "").replace("\n", " ")
            if inn:
                print("  IN ", inn[:200])


if __name__ == "__main__":
    main()
