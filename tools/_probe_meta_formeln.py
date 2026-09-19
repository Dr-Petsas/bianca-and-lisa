"""Formel-Sweep fuer die Meta-Erkennung (controller/meta.py).

Read-only, kein Netz, kein Modell. Prueft Treffer UND Gegenproben je Gruppe.

    python tools/_probe_meta_formeln.py
"""

from __future__ import annotations

import sys

from bianca.controller import meta

WIEDERHOLEN: list[str] = [
    "Wie bitte?", "Was haben Sie gesagt?", "Koennen Sie das noch einmal sagen?",
    "Können Sie das noch einmal sagen?", "Können Sie das bitte wiederholen?",
    "Sagen Sie das noch einmal.", "Sagen Sie das bitte noch einmal.",
    "Noch einmal bitte.", "Nochmal bitte", "Noch mal bitte",
    "Wiederholen Sie das bitte.", "Ich habe Sie nicht gehört.",
    "Entschuldigung, was?", "Wie?", "Hä?", "Bitte?",
    "Die Zeiten noch einmal bitte.",
]

ABBRECHEN: list[str] = [
    "Vergessen Sie es.", "Vergessen Sie das.", "Hat sich erledigt.",
    "Lassen wir das.", "Ich möchte doch nicht.", "Möchte ich doch nicht.",
    "Vergiss es.",
]

AUSLASSEN: list[str] = [
    "Überspringen wir das.", "Das möchte ich nicht sagen.", "Muss das sein?",
    "Lassen wir das offen.", "Überspringen.", "Ist das nötig?",
    "Ist das notwendig?", "Ist das wirklich nötig?", "Keine Angabe.",
]

KEINE: list[str] = [
    # Diktat und Selbstwiederholung — hier darf nichts zuenden.
    "Null eins sieben sieben noch einmal drei vier",
    "Ich sage es noch einmal: Meier",
    "A wie Anton, noch einmal",
    "Ich buchstabiere noch einmal",
    # Echte Sachfragen, die zufaellig mit einem Formelwort beginnen.
    "Was kostet die Zahnreinigung?", "Wie komme ich zu Ihnen?",
    "Wie lange dauert das?", "Was für ein Wetter",
    "Ich möchte noch einmal einen Termin am Montag",
    # Semantisches Nichtverstehen ist KEINE Hoerbitte (eigener Weg: umformulieren).
    "Das habe ich nicht verstanden.",
    # Unwissen ist kein Auslassen-Wunsch.
    "Ich weiß es nicht.", "Keine Ahnung.", "Das weiß ich nicht mehr.",
    "Muss ich noch etwas mitbringen?",
    # Echte Sachfrage mit demselben Wortstamm wie die Auslassen-Formel.
    "Ist das nötig für die Behandlung?",
    "Ist das notwendig, wenn ich privat versichert bin?",
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    fehler = 0
    gruppen = (
        ("wiederholen", WIEDERHOLEN),
        ("abbrechen", ABBRECHEN),
        ("auslassen", AUSLASSEN),
        ("", KEINE),
    )
    for soll, saetze in gruppen:
        print(f"\n--- erwartet: {soll or 'keine Meta-Bitte'} ---")
        for satz in saetze:
            ist = meta.deute(satz)
            gut = ist == soll
            fehler += 0 if gut else 1
            print(f"  {'OK  ' if gut else 'FEHL'} {ist or '-':12} {satz}")
    print(f"\n{fehler} Abweichung(en)")
    return 1 if fehler else 0


if __name__ == "__main__":
    raise SystemExit(main())
