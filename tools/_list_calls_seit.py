"""Liste Bianca-Anrufe ab Mitternacht (Europe/Berlin)."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
# 08.09.2026 00:00 CEST = 07.09.2026 22:00 UTC
AB = datetime(2026, 9, 7, 22, 0, 0, tzinfo=timezone.utc)


def _dt(s: str) -> datetime | None:
    t = (s or "").strip()
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def main() -> None:
    if not ROOT.is_dir():
        print("kein_ordner", ROOT)
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
        zuege = [z for z in (m.get("zuege") or []) if isinstance(z, dict)]
        listen = [z for z in zuege if z.get("art") == "listen"]
        audio = 0
        for z in listen:
            ein = z.get("audioIn")
            if isinstance(ein, list):
                audio += sum(1 for x in ein if isinstance(x, dict) and (d / str(x.get("datei") or "")).is_file())
            elif isinstance(ein, dict) and (d / str(ein.get("datei") or "")).is_file():
                audio += 1
        rows.append({
            "sid": d.name,
            "started": (m.get("startedAt") or "")[:19],
            "name": m.get("patientName") or "",
            "listen": len(listen),
            "audio": audio,
        })
    rows.sort(key=lambda r: r["started"])
    print(f"n={len(rows)} ab={AB.isoformat()}")
    for r in rows:
        print(f"{r['started']} {r['sid'][:12]} listen={r['listen']} audio={r['audio']} {r['name']}")


if __name__ == "__main__":
    main()
