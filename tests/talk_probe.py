"""Einmal-Probe (27.08.2026): Talk-Schicht am echten LLM hoeren.

Spielt mitten in einer Bianca-Aufnahme eine Abschweifung durch:
Hochzeits-Erzaehlung (talk: KEIN Frage-Anker), Weiterziehen des Fadens,
Loslassen ("Na gut") -> EINE Bruecke + offene Frage. Bricht VOR dem
Angebot ab — es wird nichts gebucht, nichts geschrieben.

Start: .venv\\Scripts\\python.exe tests\\talk_probe.py
"""

import os
import sys

os.environ["WRITE_LIVE"] = "0"  # Probe schreibt NIE in den echten Kalender

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bianca import agent, session  # noqa: E402
from kern import gespraech  # noqa: E402


def zug(sit: dict, satz: str) -> str:
    out = agent.user_turn(sit, satz)
    floor = (sit.get("talk") or {}).get("floor") or "job"
    text = (out.get("text") or "").strip()
    print(f"\n>> {satz}\n<< [{floor}] {text}")
    if out.get("error"):
        print(f"   FEHLER: {out['error']}")
    return text


def main() -> int:
    sit = session.neu(tenant_id="meddent")
    start = agent.start_reply(sit)
    print(f"<< {start['text']}")

    zug(sit, "Guten Tag, ich haette gern einen Termin.")
    zug(sit, "Ja, ich war schon mal bei Ihnen.")
    zug(sit, "Bei Doktor Petsas.")

    # 1) Abschweifung mitten in der Namensfrage: talk-Floor, KEIN Anker.
    a = zug(sit, "Ach, wissen Sie — meine Tochter heiratet naemlich, ich bin ganz aufgeregt!")
    floor = (sit.get("talk") or {}).get("floor")
    ok1 = floor in (gespraech.TALK, gespraech.BLENDED)
    ok2 = "nachname" not in a.lower() and "wie ist ihr" not in a.lower()
    print(f"   PROBE talk-floor={floor} ohne_anker={ok2}")

    # 2) Faden weiterziehen: bleibt beim Thema.
    zug(sit, "Ja! Und die ganze Familie kommt, sogar aus Amerika.")

    # 3) Loslassen: EINE Bruecke, dann die offene Frage (Name).
    b = zug(sit, "Na gut, alles klar.")
    ok3 = "?" in b
    print(f"   PROBE bruecke_mit_frage={ok3}")

    # 4) Job geht nahtlos weiter.
    zug(sit, "Anna Probemann.")

    print("\ntalk_probe: fertig (nichts gebucht, nichts geschrieben)")
    return 0 if (ok1 and ok2 and ok3) else 1


if __name__ == "__main__":
    raise SystemExit(main())
