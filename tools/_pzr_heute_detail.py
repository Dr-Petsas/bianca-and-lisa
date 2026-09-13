"""Detail: heutige Bianca-Buchungen + Haila-PZR."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
AB = datetime(2026, 9, 9, 22, 0, 0, tzinfo=timezone.utc)
SIDS = {
    "e6824159335046f484a0ae55523b94dd",
    "81bae48326f945388571ea05f526113a",
    "2ec59b80ed824afb8937648b73d1e779",
}


def _dt(s: str):
    t = (s or "").strip().replace("Z", "+00:00")
    if not t:
        return None
    try:
        start = datetime.fromisoformat(t)
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start


def main() -> None:
    print("=== BUCHUNGEN HEUTE ===")
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
        rows.append((start, d.name, m))
    rows.sort()
    for start, sid, m in rows:
        book = m.get("lastBook") or {}
        if not book:
            continue
        req = ((book.get("dispatch") or {}).get("request") or {})
        print("-", start.isoformat()[11:19], m.get("patientName"), sid)
        print(
            "  booked=",
            book.get("booked"),
            "ok=",
            book.get("ok"),
            "iso=",
            book.get("slotIso"),
            "aid=",
            book.get("appointmentId"),
        )
        print(
            "  cal=",
            req.get("calendarId"),
            "vm=",
            req.get("visitMotiveId"),
            "spoken=",
            (book.get("spoken") or "")[:160],
        )
        note = m.get("lastNote") or {}
        print("  note=", (note.get("note") or book.get("note") or "")[:240])
        for t in m.get("tools") or []:
            if not isinstance(t, dict):
                continue
            n = str(t.get("name") or "")
            if "note" in n.lower() or "book" in n.lower():
                print(
                    "  TOOL",
                    n,
                    "ok=",
                    t.get("ok"),
                    "note=",
                    (t.get("note") or "")[:180],
                    "spoken=",
                    (t.get("spoken") or "")[:120],
                )

    print("=== DETAIL SIDS ===")
    for start, sid, m in rows:
        if sid not in SIDS:
            continue
        print("=" * 72)
        print(start.isoformat(), sid, m.get("patientName"))
        raw = json.dumps(m, ensure_ascii=False)
        for needle in ("PLUS PZR", "plus pzr", "pzr", "Zahnrein", "zahnrein"):
            idx = raw.lower().find(needle.lower())
            print("needle", needle, "idx", idx)
            if idx >= 0:
                print("  ctx", raw[max(0, idx - 80) : idx + 120].replace("\n", " "))
        for i, z in enumerate(m.get("zuege") or []):
            if not isinstance(z, dict):
                continue
            inn = (z.get("textIn") or "").replace("\n", " ")
            out = (z.get("text") or "").replace("\n", " ")
            print(f"{i:02d} IN={inn}")
            print(f"    OUT={out}")


if __name__ == "__main__":
    main()
