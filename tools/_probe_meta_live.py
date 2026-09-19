"""Hoerprobe der vier Meta-Bausteine (W-META) am reinen Kern.

Read-only: laeuft gegen ToolGatewaySim, ruehrt keinen Kalender an und braucht
kein LLM (die Meta-Erkennung ist bewusst deterministisch, vor dem Modell).

    python tools/_probe_meta_live.py
"""

from __future__ import annotations

import sys

from bianca.controller.orchestrator import TestGespraech
from bianca.controller.policy import default


def _lauf(titel: str, saetze: list[str | None]) -> None:
    print(f"\n=== {titel} ===")
    g = TestGespraech(default())
    print(f"  Bianca : {g.start()}")
    for satz in saetze:
        if satz is None:
            print("  (Anrufer schweigt)")
            print(f"  Bianca : {g.stille()}")
            continue
        print(f"  Anrufer: {satz}")
        print(f"  Bianca : {g.eingabe(satz)}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    _lauf("1. Wiederholen auf Zuruf — nie wortgleich", [
        "Ich braeuchte einen Termin zur Kontrolle.",
        "Wie bitte?",
        "Was haben Sie gesagt?",
        "Koennen Sie das noch einmal sagen?",
    ])

    _lauf("2. Anliegen abbrechen — kein Rueckruf, keine Notiz", [
        "Ich moechte einen Termin.",
        "Wissen Sie was, vergessen Sie es.",
    ])

    _lauf("3. Frage auslassen — Pflichtfeld wird ehrlich benannt", [
        "Ich moechte einen Termin zur Kontrolle.",
        "Ueberspringen wir das.",
    ])

    _lauf("4. Stille — Presence, dann Erinnerung, dann ehrlicher Schluss", [
        "Ich moechte einen Termin.",
        None,
        None,
        None,
    ])

    _lauf("5. Gegenprobe: im Diktat ist 'nochmal' KEINE Meta-Bitte", [
        "Ich moechte einen Termin zur Kontrolle.",
        "Mein Name ist Meier.",
        "Null eins sieben sieben nochmal drei vier",
    ])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
