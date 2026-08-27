"""Erste Zeile ohne LLM — der Mund darf nicht auf das Gehirn warten."""

from __future__ import annotations

import re

from lisa.mission import ist_termin_auftrag

_SATZ = re.compile(r"(?<=[.!?])\s+")


def _s(v: object) -> str:
    return " ".join(str(v or "").split()).strip()


def erste_botschaft(auftrag: str) -> str:
    text = _s(auftrag)
    if not text:
        return ""
    satz = _SATZ.split(text, maxsplit=1)[0]
    woerter = satz.split()
    if len(woerter) > 16:
        satz = " ".join(woerter[:16])
    return satz


def begruessung(praxis: str, auftrag: str = "") -> str:
    name = _s(praxis) or "der Praxis"
    if ist_termin_auftrag(auftrag):
        return (
            f"Guten Tag, hier ist Lisa aus der {name}. "
            "Ich rufe wegen Ihres Termins an. "
            "Passt es Ihnen vormittags oder nachmittags besser?"
        )
    botschaft = erste_botschaft(auftrag)
    if botschaft:
        return f"Guten Tag, hier ist Lisa aus der {name}. {botschaft}"
    return f"Guten Tag, hier ist Lisa aus der {name}."
