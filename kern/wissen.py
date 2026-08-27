"""Praxiswissen aus dem Mandanten in den Systemprompt (Chef 27.08.2026).

Eine Quelle für beide Stimmen (Bianca und Lisa): Zahnmedizin-Grundwissen in
ein bis zwei Sätzen erlauben, Preise NUR aus der Mandanten-Liste nennen —
alles andere ehrlich an den Zahnarzt verweisen. Kein Erfinden, kein Schätzen
(Vorfall 27.08.2026: „feste Zahnarztschönheit" auf die Kontroll-Preisfrage).
"""

from __future__ import annotations

from typing import Any

VERWEIS_SATZ = "Das müssen Sie direkt mit Ihrem Zahnarzt besprechen."


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def wissen_block(wissen: dict | None) -> str:
    """Kompakter Prompt-Abschnitt aus tenant['wissen'] — bewusst klein (Token-Budget)."""
    w = wissen if isinstance(wissen, dict) else {}
    preise = [_s(p) for p in (w.get("preise") or []) if _s(p)]
    hinweise = [_s(h) for h in (w.get("hinweise") or []) if _s(h)]
    verweis = _s(w.get("preiseSonst")) or VERWEIS_SATZ

    zeilen = [
        "ZAHNMEDIZIN UND PREISE",
        "Allgemeine Zahnmedizinfragen (Was ist eine Wurzelbehandlung? Tut ein Implantat weh? Wie lange dauert eine Zahnreinigung?) beantwortest du in ein bis zwei allgemeinverständlichen Sätzen — keine Diagnosen, keine individuellen Heilaussagen.",
    ]
    if preise:
        zeilen.append("PREISE (grob, circa — NUR diese nennen):")
        zeilen.extend(f"- {p}" for p in preise)
        zeilen.append(
            f"Alle anderen Preise kennst du NICHT: nie schätzen, nichts erfinden, sondern wörtlich: „{verweis}“"
        )
    else:
        zeilen.append(f"Preise kennst du KEINE: nie schätzen, sondern wörtlich: „{verweis}“")
    zeilen.extend(hinweise)
    return "\n".join(zeilen)
