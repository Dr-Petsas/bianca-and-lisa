"""Ruhige Gespraechsfuehrung (W-RUHE 15.09.2026 — nicht rueckbauen).

Chef: "bianca ist hektisch. es werden wieder mehrere sachen direkt
hintereinander abgefeuert ... sie soll ruhiger sein und ein thema nach dem
anderen abarbeiten." Diese Wache ist die EINE gemeinsame Stelle (Bianca/Ben
UND beide Lisa-Pfade), die pro gesprochenem Zug durchsetzt:

- hoechstens EINE Frage,
- die Frage steht am ENDE,
- nach der Frage folgt KEIN zweites Thema.

Fail-safe wie fach_wache/zeiten_wache — im Zweifel BEHALTEN:
- Es wird NUR gearbeitet, wenn der Zug eine Frage enthaelt UND danach noch
  Saetze folgen. Reine Aussage-Zuege (Termin-/SMS-/Fakten-Bestaetigung ohne
  Frage) werden NIE beschnitten.
- Traegt ein Satz NACH der ersten Frage einen FAKT (Ziffer, Datum, Wochentag,
  Uhrzeit, Notfall/112/116 117, SMS/Link/E-Mail, Euro), bleibt der GANZE Text
  unveraendert — angebotene Alternativ-Slots und Sicherheits-/Terminfakten
  duerfen nie blind wegfallen.
- Nur das erschoepfende Nachgeplauder NACH der Frage (zweite Frage, Sonst-
  noch-Floskel, Empathie-Anhaengsel) wird gestrichen.

Stufen/Notaus: ``RUHE_WACHE=off|shadow|enforce`` (Default enforce).
"""
from __future__ import annotations

import os
import re

from kern import sprech

# Fakten, die NACH einer Frage nie stumm wegfallen duerfen (dann bleibt alles).
_FAKT_RE = re.compile(
    r"\d"  # jede Ziffer: Datum, Uhrzeit, Nummer, Betrag, angebotener Slot
    r"|\b(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag)s?\b"
    r"|\b(?:januar|februar|m(?:ä|ae)rz|april|mai|juni|juli|august|september|"
    r"oktober|november|dezember)\b"
    r"|\buhr\b|\bvormittags?\b|\bnachmittags?\b|\bmorgens\b|\babends\b"
    r"|\bnotfall\w*|\bnotdienst\w*|\bnotaufnahme\b|\b112\b|\b116\s*117\b"
    r"|\bsms\b|\blink\b|\be-?mail\b|\beuro\b|€",
    re.IGNORECASE,
)


def modus() -> str:
    """``off`` | ``shadow`` | ``enforce`` (Default enforce)."""
    roh = (os.getenv("RUHE_WACHE") or "enforce").strip().lower()
    if roh in {"0", "off", "aus", "false"}:
        return "off"
    if roh in {"shadow", "schatten", "log"}:
        return "shadow"
    return "enforce"


def _ist_frage(satz: str) -> bool:
    return satz.rstrip().endswith("?")


def saeubern(text: str) -> tuple[str, list[str]]:
    """(neuer_text, gestrichene_saetze).

    Gibt ``(text, [])`` zurueck, wenn nichts zu tun ist (keine Frage, Frage
    schon am Ende, oder ein Fakt haengt hinter der Frage)."""
    roh = " ".join(str(text or "").split())
    if not roh:
        return text, []
    saetze = sprech.tts_saetze(roh)
    if len(saetze) <= 1:
        return text, []
    # Erste Frage suchen.
    idx = next((i for i, s in enumerate(saetze) if _ist_frage(s)), -1)
    if idx < 0 or idx == len(saetze) - 1:
        # Keine Frage ODER Frage steht schon am Ende: ruhig genug.
        return text, []
    hinter = saetze[idx + 1:]
    # Fakt hinter der Frage? Dann NICHTS anfassen (angebotener Slot o. ae.).
    if any(_FAKT_RE.search(s) for s in hinter):
        return text, []
    behalten = saetze[: idx + 1]
    return " ".join(behalten).strip(), list(hinter)
