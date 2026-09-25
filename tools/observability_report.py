#!/usr/bin/env python3
"""Read-only Bericht über die PII-freie V5.6-Manifestspur.

Das Werkzeug liest ausschließlich ``manifest["observability"]``. Es gibt
weder Gesprächsinhalte noch Sitzungs-, Patienten-, Termin- oder Pfad-IDs aus.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SCHEMA = "pickadoc.observability/v1"


def manifeste(root: Path) -> Iterable[dict]:
    for pfad in root.glob("*/anruf.json"):
        try:
            data = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            yield data


def _alter_minuten(manifest: dict, now: datetime) -> float:
    roh = manifest.get("endedAt") or manifest.get("startedAt") or ""
    try:
        zeit = datetime.fromisoformat(str(roh))
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=timezone.utc)
        return max(0.0, (now - zeit.astimezone(timezone.utc)).total_seconds() / 60)
    except (TypeError, ValueError):
        return 0.0


def auswerten(
    daten: Iterable[dict],
    *,
    orphan_after_minutes: int = 120,
    now: datetime | None = None,
) -> dict:
    jetzt = now or datetime.now(timezone.utc)
    calls = 0
    mit_spur = 0
    stale_pending = 0
    funnel_calls = Counter()
    phasen: dict[str, Counter] = {
        "reservation": Counter(),
        "verwaltung": Counter(),
    }
    ergebnisse: dict[str, Counter] = {
        "reservation": Counter(),
        "verwaltung": Counter(),
    }
    for manifest in daten:
        calls += 1
        obs = manifest.get("observability")
        if not isinstance(obs, dict) or obs.get("schema") != SCHEMA:
            continue
        mit_spur += 1
        for funnel in ("reservation", "verwaltung"):
            events = [e for e in (obs.get(funnel) or []) if isinstance(e, dict)]
            if not events:
                continue
            funnel_calls[funnel] += 1
            for event in events:
                phasen[funnel][str(event.get("phase") or "unknown")] += 1
                ergebnisse[funnel][str(event.get("outcome") or "unknown")] += 1
        reservation = [
            e for e in (obs.get("reservation") or []) if isinstance(e, dict)
        ]
        erstellt = any(
            e.get("phase") == "create" and e.get("outcome") == "ok"
            for e in reservation
        )
        terminal = any(
            e.get("phase") in {"done", "expired", "cleanup"}
            for e in reservation
        )
        if (
            erstellt
            and not terminal
            and _alter_minuten(manifest, jetzt) >= orphan_after_minutes
        ):
            stale_pending += 1
    return {
        "schema": SCHEMA,
        "callsScanned": calls,
        "callsWithObservability": mit_spur,
        "funnelCalls": dict(sorted(funnel_calls.items())),
        "phases": {
            k: dict(sorted(v.items())) for k, v in phasen.items()
        },
        "outcomes": {
            k: dict(sorted(v.items())) for k, v in ergebnisse.items()
        },
        "stalePendingReservations": stale_pending,
        "staleAfterMinutes": int(orphan_after_minutes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PII-freier Reservierungs-/Verwaltungsbericht"
    )
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path(".data/anrufe/bianca"),
        help="Ordner mit <session>/anruf.json (Default: .data/anrufe/bianca)",
    )
    parser.add_argument("--stale-minutes", type=int, default=120)
    args = parser.parse_args()
    bericht = auswerten(
        manifeste(args.root),
        orphan_after_minutes=max(1, args.stale_minutes),
    )
    print(json.dumps(bericht, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
