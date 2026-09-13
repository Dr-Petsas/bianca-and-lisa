"""Heutige Bianca-Anrufe mit Mandant/DID (im Container)."""
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


def _tenant(m: dict) -> dict:
    for k in ("tenant", "mandant", "sitTenant"):
        v = m.get(k)
        if isinstance(v, dict):
            return v
    return {}


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
        t = _tenant(m)
        sit = m.get("sammler") if isinstance(m.get("sammler"), dict) else {}
        rows.append((start, d.name, m, t, sit))
    rows.sort(key=lambda x: x[0])
    print(f"n={len(rows)}")
    for start, sid, m, t, sit in rows:
        print("---")
        print(
            start.isoformat()[:19],
            sid,
            "name=", m.get("patientName") or "-",
            "pcid=", m.get("phoneCallId") or "-",
            "cid=", t.get("clientId") or m.get("clientId") or "-",
            "did=", t.get("did") or m.get("did") or "-",
            "praxis=", (t.get("praxisName") or t.get("name") or "")[:50],
            "book=", bool(m.get("lastBook")),
            "cal=", sit.get("calendarId") or "",
        )
        tools = m.get("tools") or []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name") or "")
            if any(x in name.lower() for x in ("book", "slot", "offer")):
                print(
                    " TOOL",
                    name,
                    "ok=",
                    tool.get("ok"),
                    "err=",
                    tool.get("error") or tool.get("note") or "",
                )
                disp = tool.get("dispatch") or {}
                req = disp.get("request") or {}
                resp = disp.get("response") or {}
                print("  req", json.dumps(req, ensure_ascii=False)[:500])
                print("  resp", json.dumps(resp, ensure_ascii=False)[:800])


if __name__ == "__main__":
    main()
