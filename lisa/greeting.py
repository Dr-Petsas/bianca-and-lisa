"""Erste Zeile ohne LLM — der Mund darf nicht auf das Gehirn warten."""

from __future__ import annotations

import re

from lisa.mission import ist_termin_auftrag, praxis_an

_SATZ = re.compile(r"(?<=[.!?])\s+")

_HERR = {"m", "male", "herr", "mann", "männlich", "maennlich"}
_FRAU = {"f", "w", "female", "frau", "weiblich"}


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


def anrede(patient: dict | None) -> str:
    """'Frau Müller', 'Herr Müller' — ohne bekanntes Geschlecht der ganze Name."""
    p = patient or {}
    last = _s(p.get("lastName"))
    name = _s(p.get("name"))
    if not last and name:
        teile = name.split()
        last = teile[-1] if len(teile) >= 2 else ""
    g = _s(p.get("gender")).lower()
    if last:
        if g in _HERR:
            return f"Herr {last}"
        if g in _FRAU:
            return f"Frau {last}"
    # Nicht raten: lieber der volle Name als eine falsche Anrede.
    return name or last


def vorstellung(praxis: str, behandler: str = "") -> str:
    haus = _s(praxis)
    arzt = _s(behandler)
    kern = f"hier ist Lisa {praxis_an(haus)}" if haus else "hier ist Lisa"
    if arzt:
        kern += f", ich rufe im Auftrag von {arzt} an"
    return kern


def begruessung(praxis: str, auftrag: str = "", *, patient: dict | None = None,
                behandler: str = "") -> str:
    """Erster Zug. Mit bekanntem Namen: Vorstellung + Identitaetsfrage.

    Chef 27.08.2026: Lisa vergewissert sich zuerst, WER am Telefon ist. Anrede,
    Behandler und Anliegen kommen erst nach der Bestaetigung (lisa/identitaet.py)
    — sonst erzaehlt sie einem Fremden das Anliegen.
    """
    from lisa.identitaet import frage_satz, moeglich

    haus = _s(praxis)
    kopf = f"Guten Tag, hier ist Lisa {praxis_an(haus)}." if haus else "Guten Tag, hier ist Lisa."
    if moeglich(patient):
        return f"{kopf} {frage_satz(patient)}"

    # Ohne vollstaendigen Namen gibt es nichts zu bestaetigen: alter Ablauf.
    wen = anrede(patient)
    gruss = f"Guten Tag, {wen}," if wen else "Guten Tag,"
    kopf = f"{gruss} {vorstellung(praxis, behandler)}."
    if ist_termin_auftrag(auftrag):
        return (
            f"{kopf} Es geht um Ihren Termin. "
            "Passt es Ihnen vormittags oder nachmittags besser?"
        )
    botschaft = erste_botschaft(auftrag)
    if botschaft:
        return f"{kopf} {botschaft}"
    return kopf
