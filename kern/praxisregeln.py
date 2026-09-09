"""Kompakte, DB-gesteuerte Praxisregeln fuer kritische Sonderwege.

Die Pickadoc-CF liefert aktuell nur einen Teil der Agent-Promptfelder an
TelefonKI. Kritische Praxisregeln tragen deshalb einen kurzen Marker in einem
tatsaechlich uebertragenen Promptfeld. Der feste Flow erkennt den Marker und
setzt die Regel deterministisch um; ohne Marker bleibt jede andere Praxis
byte-identisch.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


NOTFALL_MARKER = "NOTFALL-SOFORTREGEL"
DOKUMENT_MARKER = "DOKUMENT-VORSPRACHEREGEL"
TZ = ZoneInfo("Europe/Berlin")

_LEBENSGEFAHR_RE = re.compile(
    r"\batemnot\b|pfeifende?\s+atmung|enge\s+im\s+hals|"
    r"(?:zunge|mund|hals)[^.!?]{0,30}geschwollen|"
    r"kreislauf(?:kollaps|zusammenbruch)|bewusstlos|krampf(?:artig|anfall)|"
    r"gro(?:ß|ss)fl(?:ä|ae)chige?\s+hautabl(?:ö|oe)sung|"
    r"blutige?\s+lippen|schleimhaut[^.!?]{0,30}(?:blutig|abl(?:ö|oe)s)|"
    r"schwere?\s+(?:arzneimittel|medikamenten)(?:reaktion|allergie)",
    re.I,
)
_AKUT_RE = re.compile(
    r"\bnotfall\b|\bakut\w*|\bdringend\b|\bsofort\b|heute\s+unbedingt|"
    r"pl(?:ö|oe)tzlich[^.!?]{0,50}(?:haut|ausschlag|fleck|ver(?:ä|ae)nder)|"
    r"schnell[^.!?]{0,30}(?:schlimmer|ausbreit)|"
    r"starke?\s+(?:schmerz|brennen|juckreiz)|nicht\s+aus(?:zu)?halten|"
    r"(?:gesicht|lippe|augenlid|hals)[^.!?]{0,30}(?:schwell|geschwollen)|"
    r"\bblasen\b|n(?:ä|ae)ssende?\s+fl(?:ä|ae)che|offene?\s+stelle|eitrig|"
    r"hautausschlag[^.!?]{0,40}(?:fieber|kreislauf|krankheitsgef(?:ü|ue)hl)|"
    r"g(?:ü|ue)rtelrose|akute?\s+allergische?\s+reaktion|"
    r"(?:wunde|infektion)[^.!?]{0,40}(?:eingriff|operation|praxis)|"
    r"kind[^.!?]{0,40}(?:ausgedehnt|ganze[rm]?\s+k(?:ö|oe)rper)[^.!?]{0,30}ausschlag",
    re.I,
)
_VERNEINT_RE = re.compile(
    r"\b(?:kein|keine|nicht)\s+(?:akut\w*|notfall|dringend)\b", re.I)
_UHRFRAGE_RE = re.compile(
    r"\bwann\b|welche\s+uhrzeit|um\s+wie\s+viel\s+uhr|feste?\s+uhrzeit",
    re.I,
)
_WOCHENTAGE = {
    0: "montag", 1: "dienstag", 2: "mittwoch", 3: "donnerstag",
    4: "freitag", 5: "samstag", 6: "sonntag",
}
_ZEIT_RE = re.compile(
    r"(\d{1,2})(?:[:.](\d{2}))?\s*(?:uhr\s*)?(?:-|bis)\s*"
    r"(\d{1,2})(?:[:.](\d{2}))?",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _prompt(tenant: dict | None) -> str:
    return str((tenant or {}).get("dbPrompt") or "")


def notfall_sofort_aktiv(tenant: dict | None) -> bool:
    return NOTFALL_MARKER in _prompt(tenant)


def dokument_vorsprache_aktiv(tenant: dict | None) -> bool:
    return DOKUMENT_MARKER in _prompt(tenant)


def lebensgefahr(text: str) -> bool:
    return bool(_LEBENSGEFAHR_RE.search(_s(text)))


def akut(text: str) -> bool:
    t = _s(text)
    if not t or _VERNEINT_RE.search(t):
        return False
    return lebensgefahr(t) or bool(_AKUT_RE.search(t))


def praxis_offen(tenant: dict | None, jetzt: datetime | None = None) -> bool | None:
    """Sprechzeiten aus dem DB-Prompt lesen; None, wenn dort keine stehen."""
    now = jetzt or datetime.now(TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    tag = _WOCHENTAGE[now.weekday()]
    prompt = _prompt(tenant)
    zeile = next(
        (z for z in prompt.splitlines() if re.search(rf"\b{tag}\b", z, re.I)),
        "",
    )
    if not zeile:
        # Sind andere Wochentage mit Zeiten gepflegt, ist ein fehlender Tag
        # (typisch Samstag/Sonntag) geschlossen — nie versehentlich "jetzt
        # kommen" sagen. Nur bei ganz fehlendem Stundenplan bleibt es unbekannt.
        hat_plan = any(
            _ZEIT_RE.search(z) and any(
                re.search(rf"\b{wt}\b", z, re.I)
                for wt in _WOCHENTAGE.values()
            )
            for z in prompt.splitlines()
        )
        return False if hat_plan else None
    fenster = list(_ZEIT_RE.finditer(zeile))
    if not fenster:
        return None
    minute = now.hour * 60 + now.minute
    for m in fenster:
        start = int(m.group(1)) * 60 + int(m.group(2) or 0)
        ende = int(m.group(3)) * 60 + int(m.group(4) or 0)
        if start <= minute <= ende:
            return True
    return False


def notfall_antwort(
    tenant: dict | None,
    text: str,
    *,
    jetzt: datetime | None = None,
    bereits_akut: bool = False,
) -> str:
    """Feste, kurze Notfallantwort oder ""."""
    if not notfall_sofort_aktiv(tenant):
        return ""
    t = _s(text)
    if lebensgefahr(t):
        return (
            "Das ist ein medizinischer Notfall. Wählen Sie bitte jetzt die "
            "112."
        )
    if not (akut(t) or (bereits_akut and _UHRFRAGE_RE.search(t))):
        return ""
    offen = praxis_offen(tenant, jetzt)
    if offen is False:
        return (
            "Die Praxis ist gerade geschlossen. Wenden Sie sich bitte an den "
            "ärztlichen Bereitschaftsdienst unter 116 117. Bei Atemnot oder "
            "Kreislaufproblemen wählen Sie sofort die 112."
        )
    return (
        "Das klingt akut. Kommen Sie bitte jetzt direkt in die Praxis. "
        "Dafür gibt es keine feste Uhrzeit; bringen Sie bitte Wartezeit mit. "
        "Sie werden auf jeden Fall so schnell wie möglich gesehen und versorgt."
    )


def dokument_antwort() -> str:
    return (
        "Rezepte und Überweisungen gibt es bei uns nur nach persönlicher "
        "Vorsprache in der Praxis. Je nach Anliegen schaut die Ärztin Sie "
        "vorher noch kurz an. Kommen Sie dafür bitte während der "
        "Sprechzeiten vorbei."
    )
