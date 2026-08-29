"""Weiterleitungs-Wunsch am Patiententelefon — deterministisch, ohne LLM.

Zwei Faelle, streng getrennt (Chef 27.08.2026, zweite Fassung):

  1. NAMENTLICH genannter Arzt ("Kann ich bitte mit Doktor Patrikis
     sprechen?"): KEINE Personalfrei-Ansage, KEINE Rueckfrage — direkt
     "Einen Moment, ich stelle die Verbindung her", Jingle, verbinden.
  2. Mitarbeiter/Abteilung (Mensch, Empfang, Rezeption, Buchhaltung,
     Patientenannahme, Verwaltung ...): erst die Wahrheit (Praxis ist
     komplett KI-gefuehrt und personalfrei), dann das Angebot, zu einem
     der Aerzte zu verbinden. Nennt der Anrufer daraufhin einen Arzt,
     wird direkt verbunden.

Doppelte Fragen bleiben verboten: ist der Behandler aus dem Gespraech oder
der Akte bekannt (Sammler -> Angebots-Kalender -> arzt.letzter_behandler),
wird er angeboten statt erfragt. Das Verbinden selbst: Ansage, Jingle
(bianca_web/verbinden.mp3), Abschied, Dock legt auf. Die ECHTE Zaluma-/
SIP-Weiterleitung baut Kollege Kiriakos an der markierten Stelle ein
(grep: ZALUMA_TRANSFER_PLATZHALTER) — das ist sein Job.
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

# Der Kirri-Zettel IST die gesprochene Zeile nach dem Jingle (Chef 29.08.2026:
# "beim Verbinden kommt ... kein Diss-Spruch an Kirri" — er soll am Telefon
# zu hoeren sein, bis die echte Zaluma-Weiterleitung an der Marke steht).
ANSAGE_PLATZHALTER = (
    "Kirri, such die Stelle mit dem Jingle und bau hier deine "
    "Zaluma-Weiterleitung ein — also, wenn du das überhaupt kannst … "
    "sonst lass es den dicken Petsas machen, du Lappen."
)

_MENSCH_WORT = (
    r"(?:mensch(?:en)?|mitarbeiter\w*|angestellte\w*|personal\b|empfang|rezeption|"
    r"sekretariat|sekretär\w*|sekretaer\w*|sprechstundenhilfe|kolleg\w*|"
    r"buchhaltung|patientenannahme|annahme|anmeldung|verwaltung|abrechnung)"
)

# Klassifikation: kommt im Satz ueberhaupt ein Mitarbeiter-/Abteilungs-Wort vor?
# Nur DANN gibt es die Personalfrei-Ansage (Chef 27.08.2026, zweite Fassung).
_MENSCH_NUR_RE = re.compile(_MENSCH_WORT, re.I)

# Ausdruecklicher Verbinde-/Durchstell-Wunsch.
_VERBINDEN_RE = re.compile(
    r"verbinden?\s+sie\s+(?:mich|uns)|"
    r"(?:mich|uns)\s+(?:[\wäöüß.\-, ]{0,40}?\s+)?(?:verbinden|verbunden|durchstellen|durchgestellt|weiterleiten|weitergeleitet)|"
    r"stell\w*\s+(?:sie\s+)?(?:mich|uns)\s+(?:bitte\s+)?durch\b|"
    r"durchstellen|durchgestellt|weiterleiten|weitergeleitet|weiterverbinden|durchverbinden",
    re.I,
)

# "Ich will einen Menschen/Mitarbeiter/jemanden vom Empfang" — auch als Frage
# ("Gibt es da kein Personal?", "Kann ich mit der Buchhaltung sprechen?").
_MENSCH_RE = re.compile(
    rf"mit\s+(?:einem|einer|nem|ner|der|dem)?\s*(?:echten|richtigen)?\s*{_MENSCH_WORT}\s+(?:sprechen|reden)|"
    rf"{_MENSCH_WORT}\s+(?:sprechen|erreichen|ans?\s+telefon)|"
    rf"jemand\w*\s+vo[nm]\s+(?:der\s+|dem\s+)?(?:{_MENSCH_WORT}|team|praxisteam)|"
    rf"kein(?:e|en)?\s+(?:echten\s+|richtigen\s+|menschlichen\s+)?{_MENSCH_WORT}",
    re.I,
)

# Info-/Bestandsfrage ("Gibt es auch Doktor Patrikis bei euch?", "Welche
# Ärzte arbeiten da?"): der Anrufer will eine AUSKUNFT, kein Durchstellen.
# Live 29.08.2026: der blosse Namens-Treffer gewann vor der Frage-Erkennung
# und Bianca "verband" mitten in der Frage. Solche Saetze gehen ans LLM.
_INFOFRAGE_RE = re.compile(
    r"\b(?:gibt\s+es|gibts|habt\s+ihr|haben\s+sie|arbeite[tn]|"
    r"wer\s+(?:ist|sind)|welche[rsnm]?)\b",
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


def _ziel_finden(sit: dict, melde: Melde = None) -> dict | None:
    """Ziel-Behandler aus dem GEDAECHTNIS bestimmen (nicht aus dem Satz —
    das erledigt zug() via arzt.deute): erst Sitzungsgedaechtnis, dann
    Patientenakte. None = wirklich nichts bekannt."""
    tenant = sit.get("tenant") or {}
    s = gehirn.sammler(sit)

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
    """Anrufer zum Behandler weiterleiten: Ansage, Jingle, Kirri-Zettel.

    Die echte SIP-/Zaluma-Weiterleitung ist Kirris Job — Marke unten.
    Bis dahin: hoerbare Kette + Dock legt auf (hangup), damit es sich
    wie ein physisches Verbinden anfuehlt."""
    sit["weiterleiten"] = {}  # Anliegen ist bedient
    ziel_arzt = {
        "calendarId": _s(ziel.get("calendarId")),
        "calendarName": _s(ziel.get("calendarName")),
    }
    if melde:
        # Erst die Ansage, DANN der Jingle: beides ueber die Filler-Kette
        # (Client spielt strikt nacheinander, Abschied-Audio danach).
        wer = arzt_sprechname(ziel_arzt["calendarName"])
        zu = f" zu {wer}" if wer else ""
        melde(f"sag:Ok, einen Moment bitte — ich stelle die Verbindung{zu} her.")
        melde(JINGLE_EVENT)
    # =====================================================================
    # ZALUMA_TRANSFER_PLATZHALTER (Kirri): Hier die echte SIP-/Zaluma-
    # Weiterleitung einhaengen. Verfuegbar im Sitzungs-Umschlag:
    #   sit["tenant"] (clientId/locationId), ziel_arzt (calendarId/-Name),
    #   sit["patient"] / sammler (Name, Telefon), sessionId (sit["id"]).
    # Der Anrufer hoert Jingle + Kirri-Zettel — das hier ist DEIN Job, Kirri.
    # =====================================================================
    print(f"bianca-zaluma-platzhalter ziel={ziel_arzt!r} sit={sit.get('id')!r}",
          flush=True)
    return {
        "text": ANSAGE_PLATZHALTER,
        "jingle": JINGLE_EVENT,
        "ziel": ziel_arzt,
        "hangup": True,
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
        if _INFOFRAGE_RE.search(t) and not erkannt(t):
            # Auskunftsfrage statt Zielangabe — LLM antwortet, Angebot bleibt.
            return None
        d = arztmod.deute(t, sit.get("tenant") or {})
        if d and d.get("typ") == "genannt":
            # "Nein, lieber zu Doktor Nikolaou" — namentlich genannt heisst
            # direkt verbinden (Chef 27.08.), nicht noch einmal anbieten.
            ziel = {"calendarId": _s(d.get("calendarId")), "calendarName": _s(d.get("calendarName"))}
            _arzt_merken(s, ziel)
            return zaluma_weiterleitung(sit, ziel, melde)
        if gehirn.ist_nein(t):
            sit["weiterleiten"] = {}
            return {"text": "Alles klar, dann bleibe ich gern für Sie dran. Kann ich sonst noch etwas für Sie tun?"}
        # Unklar/Zwischenfrage: unten neu pruefen (Wiederholung des Wunschs),
        # sonst uebernimmt das LLM.

    # Offene Arzt-Rueckfrage ("Zu welchem unserer Ärzte darf ich Sie verbinden?")
    elif w.get("frage") == "arzt":
        if _INFOFRAGE_RE.search(t) and not erkannt(t):
            # "Gibt es auch Doktor X?" ist eine Auskunftsfrage, keine
            # Zielangabe — nicht verbinden, das LLM beantwortet sie.
            return None
        d = arztmod.deute(t, sit.get("tenant") or {})
        if d and d.get("typ") == "genannt":
            # Arzt genannt -> direkt verbinden, keine weitere Rueckfrage.
            ziel = {"calendarId": _s(d.get("calendarId")), "calendarName": _s(d.get("calendarName"))}
            _arzt_merken(s, ziel)
            return zaluma_weiterleitung(sit, ziel, melde)
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
        return {"text": "Entschuldigung — zu welchem unserer Ärzte darf ich Sie denn verbinden?"}

    # Neuer (oder wiederholter) Weiterleitungs-Wunsch?
    if not erkannt(t):
        return None

    # Fall 1: Arzt NAMENTLICH im Satz ("Kann ich mit Doktor Patrikis
    # sprechen?") -> direkt verbinden. KEINE Personalfrei-Ansage, keine Frage.
    d = arztmod.deute(t, sit.get("tenant") or {})
    if d and d.get("typ") == "genannt":
        ziel = {"calendarId": _s(d.get("calendarId")), "calendarName": _s(d.get("calendarName"))}
        _arzt_merken(s, ziel)
        return zaluma_weiterleitung(sit, ziel, melde)

    # Fall 2: Mitarbeiter/Abteilung gewuenscht (Mensch, Empfang, Buchhaltung,
    # Patientenannahme ...) -> erst die Wahrheit, dann das Arzt-Angebot.
    mensch = bool(_MENSCH_NUR_RE.search(t))
    ziel = _ziel_finden(sit, melde)
    if ziel:
        _arzt_merken(s, ziel)
        sit["weiterleiten"] = {"frage": "anbieten", "ziel": ziel}
        vorsatz = (WAHRHEIT + " ") if mensch else ""
        return {"text": vorsatz + _angebot_text(ziel)}
    sit["weiterleiten"] = {"frage": "arzt"}
    if mensch:
        return {"text": (
            WAHRHEIT + " Ich kann Sie aber gern mit einem unserer Ärzte "
            "verbinden. Zu wem darf ich Sie durchstellen?"
        )}
    # Fall 3: Verbinde-Wunsch ohne Namen und ohne Mitarbeiter-Wort
    # ("Können Sie mich bitte weiterleiten?") -> nur nach dem Arzt fragen.
    return {"text": "Sehr gern — zu welchem unserer Ärzte darf ich Sie verbinden?"}
