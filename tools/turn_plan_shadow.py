"""TurnPlanV1 offline gegen eine gespeicherte Sitzung laufen lassen.

Beispiele:
  python tools/turn_plan_shadow.py .data/bianca_sessions/<sid>.json --llm
  python tools/turn_plan_shadow.py sitzung.json --plan entwurf.json

Kein Import in den Live-Server, keine Werkzeuge, keine Sitzungsänderung.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kern import llm, turn_context, turn_plan  # noqa: E402
from kern.tenants import laden  # noqa: E402


def _sitzung(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Sitzungsdatei enthält kein JSON-Objekt")
    if not isinstance(data.get("tenant"), dict):
        data["tenant"] = laden(str(data.get("tenantId") or ""))
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description="TurnPlanV1 nur offline/im Shadow prüfen")
    ap.add_argument("session", type=Path, help="gespeicherte Sitzungs-JSON")
    modus = ap.add_mutually_exclusive_group(required=True)
    modus.add_argument("--llm", action="store_true", help="lokales vLLM einmal aufrufen")
    modus.add_argument("--plan", type=Path, help="vorhandene Planner-Antwort validieren")
    ap.add_argument("--text", default="", help="letzten Nutzertext im Kontext überschreiben")
    ap.add_argument("--out", type=Path, help="Ergebnis zusätzlich als JSON speichern")
    args = ap.parse_args()

    sit = _sitzung(args.session)
    ctx = turn_context.projekt(sit, text_in=args.text)
    if args.llm:
        plan = turn_plan.planen(
            ctx,
            llm_call=lambda messages: llm.chat(
                messages, None, temperature=0.0, max_tokens=500,
            ),
        )
    else:
        raw = args.plan.read_text(encoding="utf-8")
        plan = turn_plan.validieren(raw, ctx)

    text = json.dumps(plan, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0 if plan.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
