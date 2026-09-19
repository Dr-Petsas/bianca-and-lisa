"""Rauchtest: treibt den Dialogkern rein ueber den Orchestrator (kein Netz)."""
from __future__ import annotations

from bianca.controller import policy as pol
from bianca.controller.orchestrator import Szenario, TestGespraech


def lauf(titel: str, zuege: list[str], sz: Szenario | None = None) -> None:
    print("=" * 66)
    print(titel)
    print("=" * 66)
    g = TestGespraech(pol.default(), sz)
    print("  BIANCA:", g.start())
    for z in zuege:
        a = g.eingabe(z)
        print(f"\n  ANRUFER: {z}")
        print(f"  BIANCA : {a.antwort or '(kein Satz)'}")
        marke = a.tool or a.naechste
        if a.uebergeben:
            marke += " [UEBERGEBEN]"
        if a.hangup:
            marke += " [AUFLEGEN]"
        print(f"    -> {marke}  grund={a.grund}  dbg={a.debug}")


if __name__ == "__main__":
    lauf(
        "BUCHEN (glueckl. Pfad, 3 Slots, Buchung ok)",
        [
            "Ich haette gern einen Termin",
            "bei Doktor Petsas",
            "zur Kontrolle",
            "naechste Woche vormittags",
            "Mueller",
            "gesetzlich",
            "der erste",
            "ja",
            "0171 2345678",
            "ja",
        ],
    )
    lauf(
        "ABSAGEN (ein Bestandstermin gefunden)",
        [
            "Ich moechte meinen Termin absagen",
            "Schmidt",
            "ja",
        ],
        Szenario(termine=1),
    )
    lauf(
        "NOTFALL (ohne Regel -> Uebergabe)",
        ["Ich habe ganz starke Schmerzen und eine dicke Backe"],
    )
