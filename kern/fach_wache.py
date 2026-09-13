"""W-FACH-WACHE (13.09.2026): kein zahnmedizinischer Inhalt in Nicht-Zahn-Praxen.

Chef: "bei blessing darf auf gar keinen Fall ein zahnmedizinischer Einfluss
oder gesprächsverlauf entstehen — keine zahnmedizinischen Themen erlaubt."

Die MASCHINE ist katalog-gegated (``motive.ist_zahn`` / ``fuehrt_pzr``:
PZR-Frage, Bleaching, Zahn-Regeln im Prompt, Zahnarzt-Verweis — alles nur,
wenn der Motivkatalog der Praxis Zahnmedizin fuehrt; ``tests/test_zahn_
katalog.py``). Das MODELL sieht zwar den Praxis-Prompt, ist aber frei: sagt
ein Anrufer beim Hautarzt "Zahnschmerzen" oder fragt nach einer Zahnreinigung,
darf Bianca keinen Zahnarzt-Rat geben und kein Zahn-Angebot machen.

Diese Wache sitzt am LLM-AUSGANG (Endtext UND P5-Streaming-Satz) und streicht
jeden Satz mit Zahn-Vokabular, wenn die Praxis KEIN Zahnarzt ist. Bleibt
nichts uebrig, kommt eine ehrliche Fach-Antwort ("Das gehört nicht zu unserer
Praxis — wir sind eine Hautarztpraxis.") — der Frage-Anker/`_nie_stumm` haengt
die offene Pflichtfrage an.

Fail-safe in BEIDE Richtungen:
- Ohne belastbares Fach (leerer Katalog UND kein ``fachgebiet`` im Mandanten,
  ``fachprofil.fach_id`` == "allgemein") bleibt die Wache AUS — MedDent darf in
  der ersten Sekunde vor dem Katalog-Lauf nicht verstummen.
- Bei Zahnpraxen ist sie nie aktiv (dort ist Zahn-Vokabular der Job).
- Ein legitimes Nicht-Zahn-Wort wird nie getroffen: "Prophylaxe" (Hautkrebs-
  Prophylaxe), "Brücke", "Mund" bleiben absichtlich AUSSEN vor.

Stufen/Notaus: ``FACH_WACHE=off|shadow|enforce`` (Default enforce).
"""

from __future__ import annotations

import os
import re
from typing import Any

from kern import fachprofil, sprech

# Zahn-Vokabular: bewusst Woerter, die in einer Haut-/Frauen-/Ortho-Praxis
# KEINE legitime Bedeutung haben. "Prophylaxe", "Bruecke", "Mund", "Kiefer"
# (Kieferhoehle beim HNO) und "Fuellung" (Filler beim Hautarzt) fehlen
# absichtlich — ein gestrichener legitimer Satz waere der teurere Fehler.
_ZAHN_RE = re.compile(
    r"(?:"
    r"\w*z(?:a|ä|ae)hn\w*"                 # Zahn, Zähne, Zahnarzt, Weisheitszahn, Zahnreinigung
    r"|\bpzr\b"
    r"|\bbleaching\b|\bzahnaufhellung\w*"
    r"|\bkaries\b|\bparodont\w*|\bgingivitis\b"
    r"|\bwurzelbehandlung\w*|\bwurzelkanal\w*|\bwurzelspitzen\w*"
    r"|\bimplantat\w*|\bimplantolog\w*"
    r"|\bkronen?\b|\bteilkrone\w*|\bveneers?\b|\binlays?\b|\bonlays?\b"
    r"|\bprothesen?\b|\bteilprothese\w*|\bvollprothese\w*"
    r"|\bamalgam\w*"
    r"|\bkieferorthop\w*|\bkfo\b|\bzahnspange\w*"
    r"|\bdental\w*|\bdentist\w*|\bgebiss\w*|\bmundhygiene\b|\bplaque\b|\bzahnstein\w*"
    r"|\bprofessionelle\s+reinigung\b"
    r")",
    re.I,
)

_FACH_SATZ = {
    "dermatologie": "Das gehört nicht zu unserer Praxis — wir sind eine Hautarztpraxis.",
    "gynaekologie": "Das gehört nicht zu unserer Praxis — wir sind eine Frauenarztpraxis.",
    "orthopaedie": "Das gehört nicht zu unserer Praxis — wir sind eine orthopädische Praxis.",
}
_FACH_SATZ_ALLGEMEIN = "Das gehört nicht zu unserer Praxis."

# EINGANGS-Seite (Live-Probe 14.09.2026 00:50, Regel 8): "Ich habe furchtbare
# Zahnschmerzen" beim HAUTARZT lief in die Buchung ("Waren Sie schon einmal
# bei uns?"). Ein klar ZAHNMEDIZINISCHES ANLIEGEN gehoert in keiner Nicht-
# Zahn-Praxis in den Buchungsfluss — es wird ehrlich weiterverwiesen.
# Bewusst ENGER als _ZAHN_RE: hier wird ein ANRUFER abgewiesen, ein
# Fehltreffer schickt einen echten Patienten weg. Deshalb nur Beschwerden/
# Leistungen, die eindeutig zum Zahnarzt gehoeren — NICHT das blosse Wort
# "Zahnarzt" ("mein Zahnarzt hat mich zu Ihnen ueberwiesen") und NICHT
# "Zahnpasta" (Kontaktallergie ist Hautarzt-Alltag).
_ZAHN_ANLIEGEN_RE = re.compile(
    r"(?:"
    r"\bzahnschmerz\w*|\bzahnweh\b|\bzahnreinigung\w*|\bzahnersatz\w*"
    r"|\bzahnfleisch\w*|\bzahnkrone\w*|\bzahnimplantat\w*|\bzahnspange\w*"
    r"|\bzahnstein\w*|\bzahnf(?:ü|ue)llung\w*|\bzahnaufhellung\w*"
    r"|\bweisheitsz(?:a|ä|ae)hn\w*|\bbackenzahn\w*|\bschneidezahn\w*|\bmilchzahn\w*"
    r"|\bzahn\s+(?:abgebrochen|ausgeschlagen|gezogen|ziehen|tut|schmerzt|wackelt|pocht)"
    r"|\bz(?:ä|ae)hne\s+(?:tun|schmerzen|putzen|ziehen|reinigen|bleichen|richten)"
    r"|\bkaries\b|\bwurzelbehandlung\w*|\bwurzelkanal\w*|\bparodont\w*|\bpzr\b"
    r"|\bbleaching\b|\bkieferorthop\w*|\bkfo\b|\bgebiss\w*"
    r"|\b(?:zum|einen|beim|bei\s+einem|termin\s+beim)\s+zahnarzt\b|\bzahnarzttermin\w*"
    r")",
    re.I,
)

# Der Verweis selbst traegt KEIN Zahn-Wort (Regel 8 gilt auch fuer Biancas
# eigenen Mund; test_llm_zug_beim_hautarzt_ohne_zahn prueft genau das) —
# "Hautarztpraxis" sagt dem Anrufer mit Zahnschmerzen alles.
_FREMD_SATZ = {
    "dermatologie": ("Damit sind Sie bei uns leider nicht richtig — wir sind eine "
                     "Hautarztpraxis. Bitte wenden Sie sich dafür an die passende Fachpraxis."),
    "gynaekologie": ("Damit sind Sie bei uns leider nicht richtig — wir sind eine "
                     "Frauenarztpraxis. Bitte wenden Sie sich dafür an die passende Fachpraxis."),
    "orthopaedie": ("Damit sind Sie bei uns leider nicht richtig — wir sind eine "
                    "orthopädische Praxis. Bitte wenden Sie sich dafür an die passende Fachpraxis."),
}
_FREMD_SATZ_ALLGEMEIN = ("Damit sind Sie bei uns leider nicht richtig. "
                         "Bitte wenden Sie sich dafür an die passende Fachpraxis.")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def modus() -> str:
    """``off`` | ``shadow`` | ``enforce`` (Default enforce)."""
    roh = (os.getenv("FACH_WACHE") or "enforce").strip().lower()
    if roh in {"0", "off", "aus", "false"}:
        return "off"
    if roh in {"shadow", "schatten", "log"}:
        return "shadow"
    return "enforce"


def fach(sit: dict | None) -> str:
    """Fach der Sitzung (``fachprofil.fach_id``), '' ohne Sitzung."""
    if not isinstance(sit, dict):
        return ""
    try:
        return _s(fachprofil.fach_id(sit))
    except Exception:
        return ""


def aktiv(sit: dict | None) -> bool:
    """Wache scharf? NUR bei bekanntem Nicht-Zahn-Fach.

    "allgemein" (leerer Katalog, kein fachgebiet) => AUS: dann wissen wir
    nicht, ob die Praxis Zahnarzt ist — und eine Zahnpraxis darf nie
    verstummen, nur weil ihr Katalog eine Sekunde spaeter kommt."""
    f = fach(sit)
    return bool(f) and f not in {"", "allgemein", "zahnmedizin"}


def zahn_treffer(text: str) -> list[str]:
    """Alle Zahn-Woerter im Text (fuer Spur und Tests)."""
    return [m.group(0) for m in _ZAHN_RE.finditer(_s(text))]


def fach_satz(sit: dict | None) -> str:
    return _FACH_SATZ.get(fach(sit), _FACH_SATZ_ALLGEMEIN)


def zahn_anliegen(text: str) -> list[str]:
    """Eindeutig zahnmedizinische Anliegen im ANRUFER-Satz (fuer Spur/Tests)."""
    return [m.group(0) for m in _ZAHN_ANLIEGEN_RE.finditer(_s(text))]


def fremdes_anliegen(sit: dict | None, text: str) -> str:
    """Ehrlicher Verweis-Satz, wenn ein Anrufer in einer Nicht-Zahn-Praxis ein
    zahnmedizinisches Anliegen vortraegt — sonst "".

    Nur im Modus ``enforce`` und nur bei AKTIVER Wache (bekanntes Nicht-Zahn-
    Fach). Der Aufrufer (bianca/agent.user_turn) spricht den Satz statt den
    Buchungsfluss zu starten; eine laufende Aufgabe bleibt stehen."""
    if modus() != "enforce" or not aktiv(sit):
        return ""
    if not zahn_anliegen(text):
        return ""
    return _FREMD_SATZ.get(fach(sit), _FREMD_SATZ_ALLGEMEIN)


def saeubern(sit: dict | None, text: str) -> tuple[str, list[str]]:
    """(neuer Text, gestrichene Zahn-Woerter).

    Ohne aktive Wache oder ohne Treffer kommt der Text unveraendert zurueck.
    Streicht SATZWEISE (``sprech.tts_saetze`` — nie hinter Abkuerzungen);
    bleibt kein Satz uebrig, steht der ehrliche Fach-Satz da."""
    t = _s(text)
    if not t or not aktiv(sit):
        return text, []
    treffer = zahn_treffer(t)
    if not treffer:
        return text, []
    behalten = [s for s in sprech.tts_saetze(t) if not _ZAHN_RE.search(s)]
    neu = " ".join(behalten).strip()
    if not neu:
        neu = fach_satz(sit)
    return neu, treffer
