"""Mitschnitte zu den leeren CallR-Nummern suchen."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("/app/.data/anrufe")
NEED = ("17657742037", "21525511485", "4921525511485", "4917657742037")


def _blob(m: dict) -> str:
    return json.dumps(m, ensure_ascii=False)


def main() -> None:
    n = 0
    for p in ROOT.rglob("anruf.json"):
        try:
            t = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if not any(x in t for x in NEED):
            continue
        n += 1
        m = json.loads(t)
        print("HIT", p.parent.name, m.get("startedAt"), m.get("patientName"),
              m.get("phoneCallId"), m.get("callerPhone"))
    print("hits", n)


if __name__ == "__main__":
    main()
