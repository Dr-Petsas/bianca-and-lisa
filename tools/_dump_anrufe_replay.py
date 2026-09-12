"""Baut Replay-JSON aus echten Mitschnitten — nur Original, kein LLM."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
AB = datetime(2026, 9, 7, 22, 0, 0, tzinfo=timezone.utc)
OUT = Path("/tmp/replay-anrufe.json")


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
    n_anrufe = 0
    for d in sorted(ROOT.iterdir() if ROOT.is_dir() else [], key=lambda p: p.name):
        p = d / "anruf.json"
        if not p.is_file():
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        start = _dt(m.get("startedAt") or "")
        if start and start < AB:
            continue
        n_anrufe += 1
        name = (m.get("patientName") or "").strip()
        for z in m.get("zuege") or []:
            if not isinstance(z, dict):
                continue
            inn = " ".join(str(z.get("textIn") or "").split())
            out = " ".join(str(z.get("text") or "").split())
            if not inn and not out:
                continue
            rows.append({
                "nr": len(rows) + 1,
                "sid": d.name[:8],
                "wann": (start.isoformat()[:19] if start else ""),
                "score": 0,
                "name": name,
                "input_orig": inn,
                "stt_heute": inn,
                "antwort_orig": out,
                "antwort_heute": out,
                "stt_gleich": True,
                "antwort_gleich": True,
                "frage": str(z.get("frage") or ""),
                "fehler": "",
                "art": str(z.get("art") or ""),
            })
    OUT.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print("anrufe", n_anrufe, "zuege", len(rows), "out", OUT)


if __name__ == "__main__":
    main()
