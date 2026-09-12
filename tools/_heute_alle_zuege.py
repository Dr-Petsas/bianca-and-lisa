"""Alle Bianca/Lisa-Anrufe seit Mitternacht Berlin, volles Transkript."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

AB = datetime(2026, 9, 7, 22, 0, 0, tzinfo=timezone.utc)


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
    for stimme in ("bianca", "lisa"):
        root = Path(f"/app/.data/anrufe/{stimme}")
        if not root.is_dir():
            print(f"=== {stimme} kein_ordner")
            continue
        rows = []
        for d in root.iterdir():
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
        print(f"=== {stimme} n={len(rows)}")
        for start, sid, m in rows:
            sit = m.get("sammler") if isinstance(m.get("sammler"), dict) else {}
            t = m.get("tenant") if isinstance(m.get("tenant"), dict) else {}
            print("====")
            print(start.isoformat()[:19], stimme, sid)
            print(
                "name=", m.get("patientName"),
                "pcid=", m.get("phoneCallId"),
                "did=", m.get("did") or t.get("did"),
                "praxis=", (t.get("praxisName") or t.get("praxisNameMelde") or "")[:50],
            )
            print(
                "book=", bool(m.get("lastBook")),
                "cancel=", bool(m.get("lastCancel")),
                "move=", bool(m.get("lastMove")),
                "note=", bool(m.get("lastNote") or m.get("praxisNotiz")),
            )
            print(
                "sammler frage=", sit.get("frage"),
                "modus=", sit.get("modus"),
                "grund=", sit.get("grund"),
                "arzt=", sit.get("arzt"),
                "phase=", sit.get("phase"),
            )
            for i, z in enumerate(m.get("zuege") or []):
                if not isinstance(z, dict):
                    continue
                inn = (z.get("textIn") or "").replace("\n", " ")
                out = (z.get("text") or "").replace("\n", " ")
                print(f"{i:02d} {z.get('art')} IN={inn}")
                print(f"    OUT={out}")
                w = z.get("waechter") or []
                if w:
                    print("    W", w)


if __name__ == "__main__":
    main()
