"""Heutige Bianca-Anrufe nur Eva Thaler: PZR mitverkauft?"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
AB = datetime(2026, 9, 9, 22, 0, 0, tzinfo=timezone.utc)
THALER = "7ttnjzfjkb801r2rmyed"


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


def _tenant(m: dict) -> dict:
    for k in ("tenant", "mandant", "sitTenant"):
        v = m.get(k)
        if isinstance(v, dict):
            return v
    return {}


def _ist_thaler(m: dict) -> bool:
    t = _tenant(m)
    cid = str(t.get("clientId") or m.get("clientId") or "").lower()
    if cid == THALER:
        return True
    raw = json.dumps(
        {
            "t": t,
            "book": ((m.get("lastBook") or {}).get("dispatch") or {}).get("request") or {},
            "gruss": ((m.get("zuege") or [{}])[0] or {}).get("text") if m.get("zuege") else "",
        },
        ensure_ascii=False,
    ).lower()
    return "thaler" in raw or THALER in raw


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
            if not _ist_thaler(m):
                continue
            rows.append((start, d.name, m))
    rows.sort()
    print("THALER_HEUTE", len(rows))
    for start, sid, m in rows:
        t = _tenant(m)
        samm = m.get("sammler") if isinstance(m.get("sammler"), dict) else {}
        book = m.get("lastBook") or {}
        note = m.get("lastNote") or {}
        raw = json.dumps(m, ensure_ascii=False)
        low = raw.lower()
        plus = "plus pzr" in low
        pzr_frage = '"frage": "pzr"' in raw or "zahnreinigung mit dazu" in low
        pzr_ja = samm.get("pzr") == "ja" or plus
        req = ((book.get("dispatch") or {}).get("request") or {})
        print("---")
        print(start.isoformat()[:19], sid, "name=", m.get("patientName") or "-")
        print(
            "cid=",
            t.get("clientId") or m.get("clientId") or "-",
            "praxis=",
            (t.get("praxisName") or t.get("praxisNameMelde") or "")[:50],
            "pzrState=",
            samm.get("pzr"),
            "pzrFrage=",
            pzr_frage,
            "plus=",
            plus,
            "pzrJa=",
            pzr_ja,
            "book=",
            bool(book.get("booked") or book.get("ok")),
        )
        if book:
            print(
                "  book vm=",
                req.get("visitMotiveId"),
                "iso=",
                book.get("slotIso"),
                "spoken=",
                (book.get("spoken") or "")[:140],
            )
        if note.get("note") or book.get("note"):
            print("  note=", ((note.get("note") or book.get("note") or "")[:240]))
        if plus:
            idx = low.find("plus pzr")
            print("  PLUSCTX", raw[max(0, idx - 60) : idx + 140].replace("\n", " "))
        for z in m.get("zuege") or []:
            if not isinstance(z, dict):
                continue
            inn = z.get("textIn") or ""
            out = z.get("text") or ""
            if any(x in (inn + out).lower() for x in ("pzr", "zahnrein", "reinigung")):
                print("  IN ", inn[:200])
                print("  OUT", out[:240])


if __name__ == "__main__":
    main()
