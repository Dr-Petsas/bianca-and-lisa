"""Heutige Thaler-Anrufe (15.09.2026 CEST) aus dem Bianca-Mitschnitt."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
AB = datetime(2026, 9, 14, 22, 0, 0, tzinfo=timezone.utc)
BIS = datetime(2026, 9, 15, 22, 0, 0, tzinfo=timezone.utc)
CLIENT = "7tTnJZfJkb801r2rmYed"
DIDS = {"+4921154244105", "4921154244105", "021154244105"}


def _dt(s: str):
    t = (s or "").strip().replace("Z", "+00:00")
    if not t:
        return None
    try:
        x = datetime.fromisoformat(t)
    except ValueError:
        return None
    if x.tzinfo is None:
        x = x.replace(tzinfo=timezone.utc)
    return x


def _tenant(m: dict) -> dict:
    t = m.get("tenant")
    return t if isinstance(t, dict) else {}


def _is_thaler(m: dict) -> bool:
    t = _tenant(m)
    tid = str(m.get("tenantId") or t.get("id") or t.get("tenantId") or "").lower()
    cid = str(t.get("clientId") or m.get("clientId") or "")
    praxis = str(t.get("praxisName") or t.get("praxisNameMelde") or "")
    did = str(t.get("did") or m.get("did") or "").replace(" ", "")
    if tid == "thaler" or cid == CLIENT:
        return True
    if "thaler" in praxis.lower():
        return True
    if did in DIDS:
        return True
    zuege = m.get("zuege") or []
    gruss = ""
    if zuege and isinstance(zuege[0], dict):
        gruss = str(zuege[0].get("text") or "")
    return "thaler zahnmedizin" in gruss.lower()


def _dauer(m: dict, start):
    ende = _dt(m.get("endedAt") or "")
    if ende and start:
        return (ende - start).total_seconds()
    return None


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
        if not start or start < AB or start >= BIS:
            continue
        if not _is_thaler(m):
            continue
        rows.append((start, d.name, m))
    rows.sort(key=lambda x: x[0])
    print("n=%d ab=%s" % (len(rows), AB.isoformat()))
    for start, sid, m in rows:
        sit = m.get("sammler") if isinstance(m.get("sammler"), dict) else {}
        t = _tenant(m)
        dauer = _dauer(m, start)
        ds = "%02d:%02d" % (int(dauer // 60), int(dauer % 60)) if dauer is not None else "?"
        zuege = [z for z in (m.get("zuege") or []) if isinstance(z, dict)]
        listen = [z for z in zuege if (z.get("textIn") or "").strip()]
        print("=" * 72)
        print(
            start.isoformat()[:19],
            sid,
            ds,
            "z=%d" % len(zuege),
            "in=%d" % len(listen),
            "book=%d" % int(bool(m.get("lastBook"))),
            "cancel=%d" % int(bool(m.get("lastCancel"))),
            "move=%d" % int(bool(m.get("lastMove"))),
            "note=%d" % int(bool(m.get("lastNote") or m.get("praxisNotiz"))),
            m.get("patientName") or "-",
        )
        print(
            "pcid=", m.get("phoneCallId") or "-",
            "did=", t.get("did") or m.get("did") or "-",
            "tid=", m.get("tenantId") or t.get("id") or "-",
            "modus=", sit.get("modus") or "",
            "frage=", sit.get("frage") or "",
            "grund=", sit.get("grund") or "",
            "phase=", sit.get("phase") or "",
        )
        if m.get("praxisNotiz"):
            print("notiz", str(m.get("praxisNotiz")).replace("\n", " ")[:240])
        if m.get("lastBook"):
            print("lastBook", json.dumps(m.get("lastBook"), ensure_ascii=False)[:280])
        if m.get("warteschleife"):
            print("ws", json.dumps(m.get("warteschleife"), ensure_ascii=False)[:220])
        tools = m.get("tools") or []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name") or "")
            if any(x in name.lower() for x in (
                "book", "slot", "cancel", "move", "note", "offer", "find", "create",
            )):
                print(
                    "TOOL", name,
                    "ok=", tool.get("ok"),
                    "err=", tool.get("error") or tool.get("note") or "",
                )
        for i, z in enumerate(zuege):
            inn = (z.get("textIn") or "").replace("\n", " ")
            out = (z.get("text") or "").replace("\n", " ")
            w = [x.get("w") for x in (z.get("waechter") or []) if isinstance(x, dict)]
            print("%02d %s IN: %s" % (i, z.get("art"), inn))
            print("   OUT: %s" % out)
            if w:
                print("   W: %s" % w)
            if z.get("book"):
                print("   BOOK", json.dumps(z.get("book"), ensure_ascii=False)[:200])


if __name__ == "__main__":
    main()
