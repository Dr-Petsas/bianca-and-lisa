"""Praxiswissen aus dem Mandanten in den Systemprompt (Chef 27.08.2026).

Eine Quelle für beide Stimmen (Bianca und Lisa): Zahnmedizin-Grundwissen in
ein bis zwei Sätzen erlauben, Preise NUR aus der Mandanten-Liste nennen —
alles andere ehrlich an den Zahnarzt verweisen. Kein Erfinden, kein Schätzen
(Vorfall 27.08.2026: „feste Zahnarztschönheit" auf die Kontroll-Preisfrage).
"""

from __future__ import annotations

import re
from typing import Any

from kern import motive, pzr_kassen

VERWEIS_SATZ = "Das müssen Sie direkt mit Ihrem Zahnarzt besprechen."
VERWEIS_PRAXIS = "Das müssen Sie direkt mit der Praxis besprechen."

# Anfahrts-/Wegfragen sind die EINE erlaubte Langtext-Antwort: der volle
# Anfahrtstext (~110 Tokens) riss am Standard-Antwortlimit (max_tokens=90)
# mitten im Wort ab ("in die zweite Et", E2E 27.08.2026). Die Agenten heben
# das Limit NUR fuer solche Zuege an.
LANGTEXT_MAX_TOKENS = 260
_LANGTEXT_RE = re.compile(
    r"anfahrt|anreise|adresse|wegbeschreibung|hinkommen|"
    r"wie\s+komm\w*\s+(?:ich|man|wir)|wo\s+(?:genau\s+)?(?:sind\s+sie|finde\s+ich|liegt|ist\s+die\s+praxis)",
    re.I,
)


def braucht_langtext(text: str) -> bool:
    """True, wenn der Anrufer nach Weg/Adresse fragt — dann darf die Antwort
    laenger sein als die ueblichen ein bis zwei Saetze."""
    return bool(_LANGTEXT_RE.search(text or ""))


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def wissen_block(wissen: dict | None, sit: dict | None = None) -> str:
    """Kompakter Prompt-Abschnitt aus tenant['wissen'] — bewusst klein (Token-Budget).

    sit=None: bisheriges Zahn-Verhalten (Unit-Tests ohne Sitzung).
    sit mit Nicht-Zahn-Katalog: kein Zahnarzt-Verweis, keine PZR-Tabelle."""
    w = wissen if isinstance(wissen, dict) else {}
    zahn = True if sit is None else motive.ist_zahn(sit)
    preise = [_s(p) for p in (w.get("preise") or []) if _s(p)]
    hinweise = [_s(h) for h in (w.get("hinweise") or []) if _s(h)]
    verweis = _s(w.get("preiseSonst")) or (VERWEIS_SATZ if zahn else VERWEIS_PRAXIS)
    anfahrt = _s(w.get("anfahrt"))
    oepnv = _s(w.get("oepnv"))

    zeilen = [
        "ZAHNMEDIZIN UND PREISE" if zahn else "PREISE",
    ]
    if zahn:
        zeilen.append(
            "Allgemeine Zahnmedizinfragen (Was ist eine Wurzelbehandlung? Tut ein Implantat weh? "
            "Wie lange dauert eine Zahnreinigung?) beantwortest du in ein bis zwei "
            "allgemeinverständlichen Sätzen — keine Diagnosen, keine individuellen Heilaussagen."
        )
    else:
        zeilen.append(
            "Keine Diagnosen, keine individuellen Heilaussagen. Fachfremde Leistungen "
            "(Zahnreinigung, Bleaching, Implantate) bietest du NICHT an und nennst dafür keine Preise."
        )
    if preise:
        zeilen.append("PREISE (ungefähr, circa — NUR diese nennen):")
        zeilen.extend(f"- {p}" for p in preise)
        zeilen.append(
            f"Alle anderen Preise kennst du NICHT: nie schätzen, nichts erfinden, sondern wörtlich: „{verweis}“"
        )
    else:
        zeilen.append(f"Preise kennst du KEINE: nie schätzen, sondern wörtlich: „{verweis}“")
    pzr = pzr_kassen.fuer_wissen(w) if zahn else ""
    if pzr:
        zeilen.append(pzr)
    if anfahrt:
        zeilen.append(
            "ANFAHRT — fragt jemand nach dem Weg, der Adresse oder „wie komme ich zu Ihnen“, "
            "sprich AUSNAHMSWEISE diesen vollen Text (nichts weglassen, nichts dazuerfinden, "
            "KEINE Parkplatz-Aussagen — Parken kennst du nicht):"
        )
        zeilen.append(anfahrt)
    if oepnv:
        zeilen.append(
            "ÖPNV — bei Fragen nach Bahn oder Bus; Linien-Nummern GENAU so in Worten lassen: "
            + oepnv
        )
    zeilen.extend(hinweise)
    return "\n".join(zeilen)
