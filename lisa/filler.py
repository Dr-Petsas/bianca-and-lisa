"""Überbrückungssätze gegen die Stille beim Werkzeug-Aufruf.

Zwei Auslöser:
1. VORAB — aus dem, was der Anrufer gerade gesagt hat, wird geraten, dass ein
   Kalender-Zugriff kommt. Der Satz geht raus, BEVOR das Sprachmodell antwortet.
   Diese Sätze reden nur vom Nachschauen, nie von einer erledigten Buchung:
   ein geratener Satz darf niemals etwas behaupten.
2. SICHER — das Werkzeug läuft wirklich (Meldung aus dem Agenten). Jetzt darf
   der Satz auch die Handlung nennen ("ich trage den Termin ein").
"""

from __future__ import annotations

import re
from typing import Any

# Laenge ist hier eine Funktion, kein Stil: ein Fueller darf die Antwort NICHT
# überdauern, sonst wird der Zug langsamer statt schneller. ElevenLabs spricht
# rund 19 Zeichen je Sekunde.
MAX_VORAB = 52   # ~2,7 s — fuellt die 2 bis 4 s bis zur Antwort
MAX_TOOL = 46    # ~2,4 s — nach dem Sprachmodell fehlt nur noch der Netz-Umlauf

# Sätze, die nur vom Nachschauen sprechen — für den geratenen Fall erlaubt.
_SUCHEN = [
    "Hm, Moment mal, ich schaue eben in den Kalender.",
    "Eine Sekunde bitte, ich prüfe kurz den Kalender.",
    "Huch, ich schaue schnell, was frei ist.",
    "Einen Augenblick — was hat der Kalender frei?",
]
_AKTE = [
    "Eine Sekunde, ich suche gerade Ihren Termin.",
    "Moment, ich hole Ihre Termine auf den Schirm.",
    "Ganz kurz, ich schaue in Ihre Akte.",
]
_ALLGEMEIN = [
    "Hm, einen kleinen Moment bitte.",
    "Eine Sekunde, ich schaue eben nach.",
    "Ganz kurz bitte, ich bin gleich wieder da.",
]

# Diese Sätze nennen die Handlung — nur wenn das Werkzeug wirklich läuft.
_BUCHEN = [
    "Alles klar, ich trage das eben ein.",
    "Sehr gut, ich setze den Termin gerade rein.",
]
_ABSAGEN = [
    "Alles klar, ich nehme den Termin eben raus.",
    "Verstanden, ich streiche den Termin gerade.",
]
_VERSCHIEBEN = [
    "Gut, ich schiebe den Termin eben um.",
    "Alles klar, ich suche eben einen Platz.",
]
_ANLEGEN = [
    "Danke, ich lege Ihre Daten eben an.",
    "Alles klar, ich trage Sie gerade ein.",
]

GRUPPEN: dict[str, list[str]] = {
    "suchen": _SUCHEN,
    "akte": _AKTE,
    "allgemein": _ALLGEMEIN,
    "buchen": _BUCHEN,
    "absagen": _ABSAGEN,
    "verschieben": _VERSCHIEBEN,
    "anlegen": _ANLEGEN,
}

# Nur diese Gruppen dürfen geraten werden (keine Handlungs-Behauptung).
VORAB_ERLAUBT = {"suchen", "akte", "allgemein"}

TOOL_GRUPPE = {
    "offer_slots": "suchen",
    "list_appointments": "akte",
    "book_slot": "buchen",
    "cancel_appointment": "absagen",
    "move_appointment": "verschieben",
    "create_patient": "anlegen",
}

_TAGE = r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag"

# Anrufer fragt nach Terminen / nennt einen Wunschzeitpunkt.
_RE_SUCHEN = re.compile(
    r"\b(frei|freien|freie|termin|termine|platz|plätze|luecke|lücke|"
    r"vormittag\w*|nachmittag\w*|morgens|abends|frueher|früher|spaeter|später|"
    r"woche|naechste|nächste|uebernaechste|übernächste|"
    rf"{_TAGE}|uhr|wann|welche|welcher|moeglich|möglich|passt|haetten|hätten|"
    r"verschieb\w*|umleg\w*|absag\w*|streich\w*|storn\w*)\b",
    re.I,
)

# Anrufer will wissen, was in seiner Akte steht.
_RE_AKTE = re.compile(
    r"\b(mein\w*\s+termin|welchen\s+termin|wann\s+(?:habe|hab|hatte)\s+ich|"
    r"steht\s+(?:da|drin)|meine\s+termine|akte)\b",
    re.I,
)

# Kurze Zustimmung auf ein Angebot — dann kommt fast sicher ein Werkzeug.
_RE_ZUSAGE = re.compile(
    r"^(ja|jawohl|jo|genau|gerne|okay|ok|passt|gut|sehr\s+gut|einverstanden|"
    r"in\s+ordnung|machen\s+wir|nehme\s+ich|den\s+nehme\s+ich|abgemacht)\b",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def vermutet(text: str, *, angebot_offen: bool = False) -> str:
    """Gruppe für den Vorab-Füller — '' wenn kein Kalender-Zugriff erwartet wird."""
    t = _s(text)
    if not t:
        return ""
    if _RE_AKTE.search(t):
        return "akte"
    if _RE_SUCHEN.search(t):
        return "suchen"
    if angebot_offen and _RE_ZUSAGE.match(t):
        # Zusage auf ein Angebot: Werkzeug kommt sicher, die Handlung aber
        # bestätigt erst das Werkzeug selbst — darum der neutrale Satz.
        return "allgemein"
    return ""


def fuer_tool(name: str) -> str:
    return TOOL_GRUPPE.get(_s(name), "allgemein")


def satz(gruppe: str, nr: int = 0) -> str:
    liste = GRUPPEN.get(gruppe) or _ALLGEMEIN
    return liste[int(nr) % len(liste)]


def alle_saetze() -> list[str]:
    out: list[str] = []
    for liste in GRUPPEN.values():
        for s in liste:
            if s not in out:
                out.append(s)
    return out
