"""Weiterleitungs-Wunsch am Patiententelefon — deterministisch, ohne LLM.

Der Anrufer will verbunden werden ("Verbinden Sie mich mit einem Mitarbeiter",
"Kann ich mit einem Menschen sprechen?", "Kann ich mit Doktor Petsas
sprechen?"). Ablauf (Chef 27.08.2026):

  1. Erst die Wahrheit: die Praxis ist komplett KI-gefuehrt und personalfrei.
  2. Doppelte Fragen sind verboten: der Ziel-Behandler kommt aus dem
     Sitzungsgedaechtnis (Sammler -> frueher erwaehnter Behandler ->
     Patientenakte via arzt.letzter_behandler). Nur wenn GAR nichts bekannt
     ist, wird gefragt: "Bei wem sind Sie denn in Behandlung?"
  3. Bei Ja: Jingle ("Wir verbinden Sie zu Ihrem Arzt", bianca_web/verbinden.mp3)
     und danach die Platzhalter-Ansage — die ECHTE Zaluma-/SIP-Weiterleitung
     baut Kollege Kiriakos spaeter an der markierten Stelle ein
     (grep: ZALUMA_TRANSFER_PLATZHALTER).
"""

from __future__ import annotations

import re
from typing import Any, Callable

from bianca import arzt as arztmod
from bianca import gehirn
from kern.patients import arzt_sprechname

Melde = Callable[[str], None] | None

# Festes Audio fuer die Filler-Kette des Clients: bianca/server.py legt
# bianca_web/verbinden.mp3 unter diesem Namen im Dienst ab.
JINGLE_NAME = "verbinden"
JINGLE_EVENT = f"audio:{JINGLE_NAME}"

WAHRHEIT = (
    "Bei uns gibt es keine menschlichen Mitarbeiter in dem Sinn — "
    "die Praxis ist komplett KI-geführt und personalfrei."
)

# Interner Platzhalter-Text (Chef 27.08.2026: wortwoertlich so, bis die echte
# Weiterleitung steht) — KEIN Patiententext.
ANSAGE_PLATZHALTER = (
    "Kirri, such die Stelle mit dem Jingle und bau hier deine "
    "Zaluma-Weiterleitung ein — also, wenn du das überhaupt kannst … "
    "sonst lass es den dicken Petsas machen, du Lappen."
)

_MENSCH_WORT = (
    r"(?:mensch(?:en)?|mitarbeiter\w*|angestellte\w*|personal\b|empfang|rezeption|"
    r"sekretariat|sekretär\w*|sekretaer\w*|sprechstundenhilfe|kolleg\w*)"
)

# Ausdruecklicher Verbinde-/Durchstell-Wunsch.
_VERBINDEN_RE = re.compile(
    r"verbinden?\s+sie\s+(?:mich|uns)|"
    r"(?:mich|uns)\s+(?:bitte\s+)?(?:mit\s+[\wäöüß.\- ]{2,30}\s+)?(?:verbinden|durchstellen|weiterleiten)|"
    r"stell\w*\s+(?:sie\s+)?(?:mich|uns)\s+(?:bitte\s+)?durch\b|"
    r"durchstellen|durchgestellt|weiterleiten|weitergeleitet|weiterverbinden|durchverbinden",
    re.I,
)

# "Ich will einen Menschen/Mitarbeiter/jemanden vom Empfang" — auch als Frage
# ("Gibt es da kein Personal?").
_MENSCH_RE = re.compile(
    rf"mit\s+(?:einem|einer|nem|ner)?\s*(?:echten|richtigen)?\s*{_MENSCH_WORT}\s+(?:sprechen|reden)|"
    rf"{_MENSCH_WORT}\s+(?:sprechen|erreichen|ans?\s+telefon)|"
    rf"jemand\w*\s+vom\s+(?:empfang|team|personal|praxisteam)|"
    rf"kein(?:e|en)?\s+(?:echten\s+|richtigen\s+|menschlichen\s+)?{_MENSCH_WORT}",
    re.I,
)

# Direkter Behandlerwunsch: "Kann ich mit Doktor Petsas sprechen?"
_ARZT_SPRECHEN_RE = re.compile(
    r"mit\s+(?:dem\s+|der\s+|herrn\s+|frau\s+)?(?:doktor|dr\.?|prof\w*|arzt|ärztin|aerztin|zahnarzt|behandler(?:in)?)\b"
    r"[^.!?]{0,40}?\b(?:sprechen|reden)|"
    r"\b(?:doktor|dr\.?)\s+[\wäöüß-]+\s+(?:selbst\s+|persönlich\s+|persoenlich\s+)?(?:sprechen|erreichen)",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def erkannt(text: str) -> bool:
    """Will der Anrufer verbunden werden / einen Menschen sprechen?"""
    t = _s(text)
    if not t:
        return False
    return bool(_VERBINDEN_RE.search(t) or _MENSCH_RE.search(t) or _ARZT_SPRECHEN_RE.search(t))


def _arzt_merken(s: dict, ziel: dict) -> None:
    """Doppelte Fragen sind verboten: ein hier geklaerter Behandler zaehlt
    auch fuer eine spaetere Buchung im selben Anruf."""
    if ziel.get("calendarId") and not (s.get("arzt") or {}).get("calendarId"):
        s["arzt"] = {
            "typ": "genannt",
            "calendarId": ziel["calendarId"],
            "calendarName": ziel.get("calendarName") or "",
        }


def _ziel_finden(sit: dict, t: str, melde: Melde = None) -> dict | None:
    """Ziel-Behandler OHNE Rueckfrage bestimmen — erst Sitzungsgedaechtnis,
    dann Patientenakte. None = wirklich nichts bekannt."""
    tenant = sit.get("tenant") or {}
    s = gehirn.sammler(sit)

    # Im Satz selbst genannt ("Kann ich mit Doktor Petsas sprechen?").
    d = arztmod.deute(t, tenant)
    if d and d.get("typ") == "genannt":
        return {"calendarId": _s(d.get("calendarId")), "calendarName": _s(d.get("calendarName"))}

    # 1) Sammler: Behandler wurde im Gespraech schon geklaert.
    a = s.get("arzt") or {}
    if a.get("calendarId") or a.get("calendarName"):
        return {"calendarId": _s(a.get("calendarId")), "calendarName": _s(a.get("calendarName"))}

    # 2) Frueher erwaehnt: ein Angebot lief schon in einem konkreten Kalender.
    bind = sit.get("angebotKalender") or {}
    if bind.get("calendarId") or bind.get("calendarName"):
        return {"calendarId": _s(bind.get("calendarId")), "calendarName": _s(bind.get("calendarName"))}
    if _s(sit.get("angebotArzt")):
        name = _s(sit.get("angebotArzt"))
        d2 = arztmod.deute(name, tenant)
        if d2 and d2.get("typ") == "genannt":
            return {"calendarId": _s(d2.get("calendarId")), "calendarName": _s(d2.get("calendarName"))}
        return {"calendarId": "", "calendarName": name}

    # 3) Patientenakte: letzter Behandler (gleicher Weg wie bianca/hintergrund).
    if s.get("patientId"):
        if melde:
            melde("list_appointments")  # Fueller: "Ganz kurz, ich schaue in Ihre Akte."
        info = arztmod.letzter_behandler(tenant, s["patientId"])
        if info.get("ok") and (info.get("calendarId") or info.get("calendarName")):
            return {
                "calendarId": _s(info.get("calendarId")),
                "calendarName": _s(info.get("calendarName")) or _s(info.get("doctorName")),
            }
    return None


def _angebot_text(ziel: dict) -> str:
    wer = arzt_sprechname(_s(ziel.get("calendarName"))) or "Ihrem Behandler"
    return f"Soll ich Sie zu {wer} weiterleiten?"


def zaluma_weiterleitung(sit: dict, ziel: dict, melde: Melde = None) -> dict:
    """Anrufer zum Behandler weiterleiten — heute eine Attrappe:
    Jingle-Ereignis plus Platzhalter-Ansage."""
    sit["weiterleiten"] = {}  # Anliegen ist bedient
    ziel_arzt = {
        "calendarId": _s(ziel.get("calendarId")),
        "calendarName": _s(ziel.get("calendarName")),
    }
    if melde:
        # Jingle "Wir verbinden Sie zu Ihrem Arzt": laeuft als festes Audio
        # ueber die bestehende Filler-Kette (kern/dienst.py -> Client).
        melde(JINGLE_EVENT)
    # =====================================================================
    # ZALUMA_TRANSFER_PLATZHALTER (Kirri): Hier die echte SIP-/Zaluma-
    # Weiterleitung einhaengen. Verfuegbar im Sitzungs-Umschlag:
    #   sit["tenant"] (clientId/locationId), ziel_arzt (calendarId/-Name),
    #   sit["patient"] / sammler (Name, Telefon), sessionId (sit["id"]).
    # Bis dahin: Jingle + Ansage unten als Attrappe.
    # =====================================================================
    return {
        "text": ANSAGE_PLATZHALTER + " Kann ich sonst noch etwas für Sie tun?",
        "jingle": JINGLE_EVENT,
        "ziel": ziel_arzt,
    }


def zug(sit: dict, gesagt: str, melde: Melde = None) -> dict | None:
    """Ein Anrufer-Satz durch den Weiterleitungs-Zweig. None => andere Fluesse."""
    s = gehirn.sammler(sit)
    t = _s(gesagt)
    if not t:
        return None
    w = sit.get("weiterleiten") or {}

    # Offenes Weiterleitungs-Angebot ("Soll ich Sie zu Doktor X weiterleiten?")
    if w.get("frage") == "anbieten":
        if gehirn.ist_ja(t):
            return zaluma_weiterleitung(sit, w.get("ziel") or {}, melde)
        if gehirn.ist_nein(t):
            sit["weiterleiten"] = {}
            return {"text": "Alles klar, dann bleibe ich gern für Sie dran. Kann ich sonst noch etwas für Sie tun?"}
        d = arztmod.deute(t, sit.get("tenant") or {})
        if d and d.get("typ") == "genannt":
            # "Nein, lieber zu Doktor Nikolaou" — Ziel umhaengen, neu anbieten.
            ziel = {"calendarId": _s(d.get("calendarId")), "calendarName": _s(d.get("calendarName"))}
            sit["weiterleiten"] = {"frage": "anbieten", "ziel": ziel}
            return {"text": _angebot_text(ziel)}
        # Unklar/Zwischenfrage: unten neu pruefen (Wiederholung des Wunschs),
        # sonst uebernimmt das LLM.

    # Offene Behandler-Rueckfrage ("Bei wem sind Sie denn in Behandlung?")
    elif w.get("frage") == "arzt":
        d = arztmod.deute(t, sit.get("tenant") or {})
        if d and d.get("typ") == "genannt":
            ziel = {"calendarId": _s(d.get("calendarId")), "calendarName": _s(d.get("calendarName"))}
            _arzt_merken(s, ziel)
            sit["weiterleiten"] = {"frage": "anbieten", "ziel": ziel}
            return {"text": _angebot_text(ziel)}
        if gehirn.ist_nein(t) or (d and d.get("typ") in {"egal", "unbekannt"}):
            sit["weiterleiten"] = {}
            return {"text": "Kein Problem — dann helfe ich Ihnen einfach direkt weiter. Was kann ich für Sie tun?"}
        if gehirn.ist_zwischenfrage(t):
            return None
        zaehler = int(w.get("leer") or 0) + 1
        if zaehler >= 2:
            # Nie im Kreis fragen (Chef 27.08.: keine Schleifen).
            sit["weiterleiten"] = {}
            return {"text": "Machen wir es anders: Ich helfe Ihnen einfach direkt. Was kann ich für Sie tun?"}
        w["leer"] = zaehler
        sit["weiterleiten"] = w
        return {"text": "Entschuldigung — bei welchem Behandler sind Sie denn in Behandlung?"}

    # Neuer (oder wiederholter) Weiterleitungs-Wunsch?
    if not erkannt(t):
        return None
    ziel = _ziel_finden(sit, t, melde)
    if ziel:
        _arzt_merken(s, ziel)
        sit["weiterleiten"] = {"frage": "anbieten", "ziel": ziel}
        return {"text": WAHRHEIT + " " + _angebot_text(ziel)}
    sit["weiterleiten"] = {"frage": "arzt"}
    return {"text": (
        WAHRHEIT + " Ich kann Sie aber zu Ihrem Behandler weiterleiten. "
        "Bei wem sind Sie denn in Behandlung?"
    )}
