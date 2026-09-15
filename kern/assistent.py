"""Wer spricht hier — Name und Genus der Telefonassistenz je Mandant.

Bis zum 15.09.2026 hiess die Stimme im Code ueberall fest "Bianca" und war
grammatisch weiblich ("Empfangsassistentin", "Ich bin die Neue!"). Mit der
gynaekologischen Praxis Ruether kam der erste MAENNLICHE Assistent ("Ben") —
seitdem kommen Name und Genus aus dem Mandanten.

OHNE Angabe bleibt alles byte-identisch bei Bianca/weiblich: ``formen()``
gibt den Text dann UNVERAENDERT zurueck (also bei MedDent, Thaler und
Blessing — kein Zeichen bewegt sich). Die Grammatik dreht sich nur fuer
maennliche Assistenten, der Name nur fuer einen anderen Namen als Bianca —
so kann eine neue Praxis die drei Live-Praxen nicht beruehren.

Quellen fuer den Namen, in dieser Reihenfolge:
1. Mandanten-Feld ``assistentName`` (tenants/*.json — gewinnt immer),
2. der Agent-Name aus der Pickadoc-DB, ABER nur wenn er wie ein einzelner
   Vorname aussieht. Die DB fuehrt dort teils den PRAXIS-Namen
   ('"Med Dent" Zahnklinik Duesseldorf - Robert') — den darf sich die
   Assistentin nie selbst sagen,
3. "Bianca".

Das Genus kommt aus ``assistentGenus`` (m/f), sonst aus der kleinen Tabelle
unten. Im Zweifel weiblich — das ist der Stand von vor dem 15.09.2026.
"""

from __future__ import annotations

import re
from typing import Any

NAME_DEFAULT = "Bianca"
GENUS_DEFAULT = "f"

# Nur die Namen, die wir wirklich als Assistenz verwenden. Bewusst NICHT
# ueber kern/vornamen.py: das ist der Waechter fuer PATIENTEN-Namen (dort
# gilt "unklar => weiblich + Notiz"), und "Ben" kennt er nicht.
_GENUS_NAMEN = {
    "ben": "m",
    "bianca": "f",
    "clara": "f",
    "lena": "f",
    "lisa": "f",
    "sophie": "f",
}

# Ein einzelner Vorname: ein Wort, nur Buchstaben (Bindestrich erlaubt),
# kein Punkt (schliesst "Dr. Pantas" aus), hoechstens 15 Zeichen.
_VORNAME_RE = re.compile(r"^[A-Za-zÄÖÜäöüß]+(?:-[A-Za-zÄÖÜäöüß]+)?$")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _aus_db(tenant: dict[str, Any] | None) -> str:
    """Agent-Name aus der DB — nur wenn er wie ein Vorname aussieht."""
    roh = _s((tenant or {}).get("agentName"))
    if not roh or len(roh) > 15 or not _VORNAME_RE.match(roh):
        return ""
    return roh


def name(tenant: dict[str, Any] | None = None) -> str:
    """Wie heisst die Assistenz dieses Mandanten?"""
    return _s((tenant or {}).get("assistentName")) or _aus_db(tenant) or NAME_DEFAULT


def genus(tenant: dict[str, Any] | None = None) -> str:
    """"m" oder "f" — im Zweifel "f" (Stand vor dem 15.09.2026)."""
    gesetzt = _s((tenant or {}).get("assistentGenus")).lower()[:1]
    if gesetzt in {"m", "f"}:
        return gesetzt
    return _GENUS_NAMEN.get(name(tenant).lower(), GENUS_DEFAULT)


def maennlich(tenant: dict[str, Any] | None = None) -> bool:
    return genus(tenant) == "m"


def stimme(tenant: dict[str, Any] | None = None) -> str:
    """Lokaler Stimmname im TTS-Container (Referenz in ``tts_serve/stimmen``).

    Mandanten-Feld ``stimme``; ohne Feld leer = Prozess-Stimme (bianca)."""
    return _s((tenant or {}).get("stimme")).lower()


# Weibliche Form -> maennliche Form. Reihenfolge ist Absicht: die laengeren,
# gebeugten Formen zuerst, damit "der Telefonassistentin" (Dativ-Apposition)
# nicht vorher von "Telefonassistentin" erwischt wird und ein falsches
# "der Telefonassistent" stehen bleibt.
_MAENNLICH = (
    ("der Telefonassistentin", "dem Telefonassistenten"),
    ("die digitale Assistentin", "der digitale Assistent"),
    ("die KI-Telefonassistentin", "der KI-Telefonassistent"),
    ("die Telefonassistentin", "der Telefonassistent"),
    ("die Assistentin", "der Assistent"),
    ("die Neue", "der Neue"),
    ("eine Kollegin", "ein Kollege"),
    ("Empfangsassistentin", "Empfangsassistent"),
    ("Terminassistentin", "Terminassistent"),
    ("Telefonassistentin", "Telefonassistent"),
    ("KI-Assistentin", "KI-Assistent"),
    ("Assistentin", "Assistent"),
)


def formen(text: str, tenant: dict[str, Any] | None = None) -> str:
    """Selbstbezeichnung auf den Mandanten drehen.

    Bei weiblicher Assistenz (Default) kommt der Text UNVERAENDERT zurueck —
    kein Regex laeuft, kein Zeichen bewegt sich. Erst ein maennlicher
    Assistent loest die Umschrift aus.

    Umgeschrieben wird nur die Selbstbezeichnung. Praxis-Fakten, Behandler-
    Namen und Anreden bleiben unberuehrt: "Frau Doktor" und "Ihre Kollegin"
    (der Anruferin!) stehen bewusst NICHT in der Tabelle.
    """
    t = str(text or "")
    if not t:
        return t
    if maennlich(tenant):
        for weiblich, maennl in _MAENNLICH:
            if weiblich in t:
                t = t.replace(weiblich, maennl)
    # Der Name wird unabhaengig vom Genus getauscht — eine Praxis darf ihre
    # Assistenz auch "Clara" nennen, ohne dass sich die Grammatik dreht.
    wie = name(tenant)
    if wie != NAME_DEFAULT:
        t = re.sub(rf"\b{re.escape(NAME_DEFAULT)}\b", wie, t)
    return t
