"""Anrufe nach Pourianmehr + sein Transkript (im Container)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
AB = datetime(2026, 9, 8, 8, 35, tzinfo=timezone.utc)
SID = "032f8ff0df644ae28934842c3271a1ff"


def _dt(s: str):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def dump(m: dict, sid: str) -> None:
    print("sid", sid)
    print("started", m.get("startedAt"))
    print("ended", m.get("endedAt"))
    print("name", m.get("patientName"))
    print("pcid", m.get("phoneCallId"))
    print("sammler", json.dumps(m.get("sammler") or {}, ensure_ascii=False)[:800])
    print("---TURNS---")
    for i, z in enumerate(m.get("zuege") or []):
        if not isinstance(z, dict):
            continue
        inn = (z.get("textIn") or "").replace("\n", " ")
        out = (z.get("text") or "").replace("\n", " ")
        print(f"{i:02d} {z.get('art')}")
        print(f"   IN : {inn}")
        print(f"   OUT: {out}")


def main() -> None:
    ziel = ROOT / SID / "anruf.json"
    if ziel.is_file():
        print("===== POURIANMEHR =====")
        dump(json.loads(ziel.read_text(encoding="utf-8")), SID)
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
    print("===== NACH 08:35 UTC n=", len(rows), "=====")
    for start, sid, m in rows:
        zuege = [z for z in (m.get("zuege") or []) if isinstance(z, dict)]
        listen = [z for z in zuege if z.get("art") == "listen"]
        an = m.get("anrufer") if isinstance(m.get("anrufer"), dict) else {}
        print("---")
        print(start.isoformat()[:19], sid, "name=", m.get("patientName") or "-",
              "pcid=", m.get("phoneCallId") or "-", "listen=", len(listen),
              "tel=", an.get("telefon") or m.get("callerPhone") or "-")


if __name__ == "__main__":
    main()
