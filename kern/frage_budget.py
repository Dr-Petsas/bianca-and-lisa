"""Anrufweites Budget fuer offene Formularfelder.

Eine offene Datenfrage darf einmal gestellt und hoechstens zweimal
wiederholt werden. Danach wird der vorhandene Stand erhalten und der Anruf
deterministisch beendet, statt in ein anderes Formular oder in eine
Endlosschleife zu springen.

Das Modul zaehlt nur. Die fachliche Abschlussreaktion (Notiz, Text, Hangup)
bleibt bei Bianca, damit dieser Kern weder ``bianca`` importiert noch
Werkzeuge ausfuehrt.

Notaus: ``FRAGE_BUDGET=0`` stellt das Verhalten vor V5.6 wieder her.
"""

from __future__ import annotations

import os
from typing import Any


# Erste Frage plus zwei Wiederholungen.
MAX_VERSUCHE = 3

# Presence-Stupse und allgemeine Unklar-Zuege teilen sich einen anrufweiten
# Deckel. Acht entspricht der bestehenden Stille-Notleine.
MAX_STALL = 8

# Nur echte Erhebungsfelder werden gedeckelt. Destruktive Bestaetigungen,
# Slotwahl und Ruecklese muessen in ihren bewaehrten, strengeren
# Zustandsmaschinen bleiben.
FELDER = frozenset({
    "schonmal",
    "arzt",
    "name",
    "vorname",
    "nachname",
    "nachname_korr",
    "grund",
    "wunsch",
    "wann",
    "behandlung",
    "neubuchung",
    "buchstabieren",
    "telefon",
    "versicherung",
    "geburtsdatum",
})


def _s(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def an() -> bool:
    return (os.environ.get("FRAGE_BUDGET") or "1").strip() != "0"


def gilt(frage_id: str) -> bool:
    return an() and _s(frage_id) in FELDER


def _stand(sit: dict) -> dict:
    stand = sit.get("frageBudget")
    if not isinstance(stand, dict):
        stand = {}
        sit["frageBudget"] = stand
    stand.setdefault("fid", "")
    stand.setdefault("versuche", 0)
    stand.setdefault("unklar", 0)
    return stand


def synchronisieren(sit: dict, frage_id: str) -> dict:
    """Zaehler an die aktuell offene Frage binden.

    Ein Feldwechsel beginnt ein neues Budget. Ein voruebergehend
    ausgeschmueckter Antwortsatz ohne Feldfrage setzt das Budget dagegen
    nicht zurueck.
    """
    stand = _stand(sit)
    fid = _s(frage_id)
    if _s(stand.get("fid")) != fid:
        stand["fid"] = fid
        stand["versuche"] = 0
    return stand


def vor_mund(sit: dict, frage_id: str, *, zaehlt: bool) -> str:
    """``ok`` oder ``erschoepft`` VOR dem Sprechen liefern.

    Der vierte Sprechversuch desselben Feldes wird nicht mehr ausgegeben.
    """
    if not an():
        return "ok"
    stand = synchronisieren(sit, frage_id)
    if not gilt(frage_id) or not zaehlt:
        return "ok"
    if int(stand.get("versuche") or 0) >= MAX_VERSUCHE:
        return "erschoepft"
    stand["versuche"] = int(stand.get("versuche") or 0) + 1
    return "ok"


def unklar_zaehlen(sit: dict) -> bool:
    """Allgemeinen Unklar-Zug merken; True bedeutet globale Notleine."""
    if not an():
        return False
    stand = _stand(sit)
    stand["unklar"] = int(stand.get("unklar") or 0) + 1
    return stall_erschoepft(sit)


def stall_gesamt(sit: dict) -> int:
    """Presence und Unklar gemeinsam, ueber den ganzen Anruf."""
    stand = _stand(sit)
    stille_stand = sit.get("stille")
    presence = (
        int(stille_stand.get("gesamt") or 0)
        if isinstance(stille_stand, dict)
        else 0
    )
    return presence + int(stand.get("unklar") or 0)


def stall_erschoepft(sit: dict) -> bool:
    return an() and stall_gesamt(sit) >= MAX_STALL


def kontext_reicht(sit: dict) -> bool:
    """Nur mit Identitaet/Kontakt UND Anliegen ist eine Notiz sinnvoll."""
    sammler = sit.get("sammler")
    s = sammler if isinstance(sammler, dict) else {}
    anrufer = sit.get("anrufer")
    a = anrufer if isinstance(anrufer, dict) else {}

    identitaet = bool(
        _s(s.get("name"))
        or _s(s.get("vorname"))
        or _s(s.get("nachname"))
        or _s(s.get("patientId"))
        or _s(sit.get("patientId"))
        or _s(s.get("telefon"))
        or _s(s.get("aktePhone"))
        or _s(s.get("kontaktTelefon"))
        or _s(a.get("telefon"))
        or _s(a.get("patientId"))
    )
    anliegen = bool(
        _s(s.get("modus"))
        or _s(s.get("grund"))
        or _s(s.get("grundWortlaut"))
        or _s(s.get("wunschText"))
        or s.get("wunsch")
        or _s(s.get("slotIso"))
        or _s(sit.get("verwHinweisText"))
        or _s(sit.get("rechnungStand"))
    )
    return identitaet and anliegen


def notiz_text(sit: dict, frage_id: str) -> str:
    """Datensparsamer, aber fuer die Praxis brauchbarer Rueckrufgrund."""
    sammler = sit.get("sammler")
    s = sammler if isinstance(sammler, dict) else {}
    grund = _s(s.get("grundWortlaut")) or _s(s.get("grund"))
    wunsch = _s(s.get("wunschText"))
    modus = _s(s.get("modus")) or "Anliegen"
    teile = [grund, wunsch]
    details = " — ".join(x for x in teile if x)
    basis = f"{modus}: {details}" if details else modus
    return f"{basis}; Feld {_s(frage_id) or 'Angabe'} blieb nach drei Versuchen unklar"
