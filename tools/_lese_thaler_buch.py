"""Thaler-Anrufe: Buchung, Kalender, Motiv."""
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
            start = _dt(m.get("startedAt") or "")
            if not start or start < AB:
                continue
            if "thaler" not in blob and "7ttnjzf" not in blob:
                continue
            rows.append((start, d.name, m))
    rows.sort(key=lambda x: x[0])
    print(f"n={len(rows)}")
    for start, sid, m in rows:
        booked = m.get("lastBook") or {}
        samm = m.get("sammler") or {}
        print("=" * 72)
        print(start.isoformat(), sid, "name=", m.get("patientName"),
              "pcid=", m.get("phoneCallId"))
        print("  phase=", samm.get("phase"), "grund=", samm.get("grund"),
              "motiv=", samm.get("motivName"), "arzt=", samm.get("arzt"))
        print("  lastBook booked=", booked.get("booked"),
              "iso=", booked.get("slotIso"),
              "cal=", booked.get("calendarId") or (booked.get("dispatch") or {}).get("request", {}).get("calendarId"),
              "spoken=", (booked.get("spoken") or "")[:140])
        for t in m.get("tools") or []:
            if not isinstance(t, dict):
                continue
            n = str(t.get("name") or "")
            req = ((t.get("dispatch") or {}).get("request") or {})
            if any(x in n.lower() for x in ("slot", "book", "motiv")):
                print("  TOOL", n, "ok=", t.get("ok"),
                      "cal=", req.get("calendarId"),
                      "vm=", req.get("visitMotiveId"),
                      req.get("visitMotiveName"),
                      (t.get("spoken") or "")[:80])
        for i, z in enumerate(m.get("zuege") or []):
            if not isinstance(z, dict):
                continue
            inn = (z.get("textIn") or "").replace("\n", " ")[:180]
            out = (z.get("text") or "").replace("\n", " ")[:220]
            print(f"  {i:02d} IN:{inn}")
            print(f"     OUT:{out}")


if __name__ == "__main__":
    main()
