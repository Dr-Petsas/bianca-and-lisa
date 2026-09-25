"""W-FRAGE-GATE: Vor jeder Frage das Session-Hirn lesen (13.09.2026).

Chef zum Anruf 1fbda5db (woertlich): "das session hirn braucht deutlich mehr
sicherheit in dem aufnehmen und ausstreuen von daten, konkret muss es vor jeder
zu stellenden frage fuer den datenwert der ermittelt werden soll ausgelesen
werden [...] es darf keine frage gestellt werden, zu der es bereits einen wert
gibt [...] jede frage muss erst im session hirn ueberprueft werden bevor bianca
sie stellt, ob antworten vorhanden sind."

Die deterministische Maschine tut das laengst (``gehirn.naechste_frage`` fragt
nur leere Felder). Live kam die Doppelfrage vom MODELL: die Zahnreinigung
wurde in Zug 8 vom LLM angeboten, in Zug 13 noch einmal von der Maschine —
das Modell hatte eine Job-Frage gestellt, von der der Sammler nichts wusste.

Darum die Regel: **Daten-Fragen gehoeren der Maschine.** Eine Frage des
Modells nach einem Job-Feld wird gestrichen; die Maschine stellt sie danach
selbst (Frage-Anker) — dann genau einmal und mit dem richtigen Zustand.

Bewusst NICHT angetastet:
- **Rueckfragen gegen einen belegten Wert** ("Ihr Vorname ist Maximilian,
  richtig?") — genau die will der Chef haben, wenn der Wert schon steht.
- Verstaendnis-/Sachfragen ohne Job-Feld ("Was meinen Sie damit?",
  "Was kostet das?") — die gehoeren dem Gespraech.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable

_SATZ_ENDE_RE = re.compile(r"(?<=[.!?…])\s+")


def modus() -> str:
    """``off`` | ``shadow`` | ``enforce`` (Default enforce).

    Eine doppelte Datenfrage ist live jedes Mal aufgefallen; der Rueckweg
    bleibt ueber die Umgebungsvariable ``FRAGE_GATE`` trotzdem offen.
    """
    roh = (os.getenv("FRAGE_GATE") or "enforce").strip().lower()
    if roh in {"0", "off", "aus", "false"}:
        return "off"
    if roh in {"shadow", "schatten", "log"}:
        return "shadow"
    return "enforce"


def _s(x: Any) -> str:
    return (x or "").strip() if isinstance(x, str) else ""


# Eine Rueckfrage gegen einen bekannten Wert ("…, richtig?", "Stimmt das so?",
# "Habe ich Sie richtig erkannt?") ist die GEWUENSCHTE Form und bleibt immer
# stehen — sonst nimmt das Gate der Bestaetigung die Sprache.
_RUECKFRAGE_RE = re.compile(
    r"\b(?:richtig|korrekt|stimmt\s+(?:das|es)|stimmt\s+so|"
    r"ist\s+das\s+richtig|habe\s+ich\s+(?:das|sie)\s+richtig|"
    r"passt\s+das|oder\s+nicht)\s*[?!]", re.I)

# Job-Felder: (Feldname, Frage-Muster des Modells, "steht der Wert schon?").
# Die Muster treffen die FRAGE-Formen ("wie ist Ihr Name?"), nicht die
# Erwaehnung ("Ihr Name steht in der Kartei").
_FELDER: list[tuple[str, re.Pattern[str], Callable[[dict], bool]]] = [
    ("name", re.compile(
        r"wie\s+(?:heißen|heissen|hieß|hiess)\s+(?:sie|du)|"
        r"wie\s+(?:ist|lautet)\s+(?:ihr|dein)\s+(?:vor|nach|familien)?name|"
        r"(?:ihren|deinen)\s+(?:vor|nach)?namen\b|"
        r"darf\s+ich\s+(?:ihren|den)\s+namen|"
        r"(?:nennen|sagen)\s+sie\s+mir\s+(?:bitte\s+)?(?:ihren|den)\s+namen|"
        r"auf\s+welchen\s+namen", re.I),
     lambda s: bool(_s(s.get("vorname")) and _s(s.get("nachname")))),
    ("telefon", re.compile(
        r"telefonnummer|handynummer|rufnummer|mobilnummer|"
        r"(?:ihre|deine)\s+nummer|unter\s+welcher\s+nummer|"
        r"welche\s+nummer\s+(?:darf|soll|kann)", re.I),
     lambda s: bool(s.get("telefonOk") or _s(s.get("telefonAkte")))),
    ("arzt", re.compile(
        r"bei\s+(?:welchem|wem)\b|welche[rm]?\s+(?:behandler|arzt|ärztin|aerztin)|"
        r"zu\s+welchem\s+(?:arzt|behandler)|"
        r"welchen\s+(?:arzt|behandler)\b", re.I),
     lambda s: bool((s.get("arzt") or {}).get("calendarId")
                    or (s.get("arzt") or {}).get("typ") == "egal")),
    ("grund", re.compile(
        r"worum\s+geht\s+es|welche[rm]?\s+grund|besuchsgrund|"
        r"was\s+für\s+ein\s+anliegen|was\s+führt\s+sie|was\s+fuehrt\s+sie|"
        r"weshalb\s+(?:möchten|moechten|wollen)\s+sie", re.I),
     lambda s: bool(_s(s.get("grund")))),
    ("schonmal", re.compile(
        r"schon\s+(?:ein)?mal\s+bei\s+uns|waren\s+sie\s+schon|"
        r"sind\s+sie\s+(?:bei\s+uns\s+)?(?:schon|bereits)\s+patient", re.I),
     lambda s: s.get("warSchonMal") is not None),
    ("buchstabieren", re.compile(r"buchstabier", re.I),
     lambda s: bool(s.get("buchstabiert"))),
    # Live MedDent 14.09.2026 (Anruf e7191c7e, Zug 7): das Modell fragte
    # „Haben Sie denn eine Vorstellung, wann es Ihnen am besten passt?“,
    # waehrend die Maschine noch auf den GRUND wartete — einen Zug spaeter
    # stellte sie die Zeitfrage selbst („Wann passt es Ihnen am besten —
    # eher vormittags oder nachmittags?“): dieselbe Frage zweimal. Die
    # Nebensatz-Form („wann es/Ihnen …“), „Vorstellung, wann“ und die
    # Tageszeit-Alternative gehoeren deshalb mit ins Muster.
    ("wunsch", re.compile(
        r"wann\s+(?:passt|hätten|haetten|würde|wuerde|wäre|waere|können|koennen|"
        r"möchten|moechten|wollen|darf|soll|es|ihnen|dir)\b|"
        r"vorstellung\w*,?\s+wann\b|"
        r"welche[rn]?\s+(?:tag|wochentag|uhrzeit|zeitpunkt)|"
        r"an\s+welchem\s+tag|zu\s+welcher\s+(?:zeit|uhrzeit)|"
        r"\b(?:vormittags?|nachmittags?)\s+oder\s+(?:nachmittags?|vormittags?)\b", re.I),
     lambda s: s.get("wunsch") is not None),
    ("versicherung", re.compile(
        r"privat\s+oder\s+gesetzlich|gesetzlich\s+oder\s+privat|"
        r"wie\s+sind\s+sie\s+versichert|welche\s+versicherung", re.I),
     lambda s: bool(_s(s.get("versicherung")))),
    ("pzr_kasse", re.compile(
        r"welche\s+(?:kranken)?kasse|bei\s+welcher\s+(?:kranken)?kasse", re.I),
     lambda s: bool(_s(s.get("pzrKasse")))),
    ("pzr", re.compile(
        r"zahnreinigung|prophylaxe|\bpzr\b", re.I),
     lambda s: _s(s.get("pzr")) not in {"", "gefragt"}),
    ("bleaching", re.compile(r"aufhell|bleach|zahnaufhellung", re.I),
     lambda s: _s(s.get("bleaching")) not in {"", "gefragt"}),
    ("slotwahl", re.compile(
        r"welche[rn]?\s+(?:termin|slot|der\s+(?:beiden|genannten))|"
        r"welche\s+(?:der\s+)?(?:zeiten|termine)", re.I),
     lambda s: bool(_s(s.get("slotIso")))),
    ("bestaetigung", re.compile(
        r"soll\s+ich\s+(?:den\s+termin\s+|das\s+|ihn\s+)?(?:so\s+)?"
        r"(?:fest\s+)?(?:eintragen|buchen|festhalten|vormerken)", re.I),
     lambda s: False),
    ("fuer_wen", re.compile(
        r"für\s+wen\s+(?:ist|soll|darf)|fuer\s+wen\s+(?:ist|soll|darf)", re.I),
     lambda s: bool(_s(s.get("fuerWen")))),
]


# Welches Job-Feld fragt die Maschine GERADE? Ihre eigene offene Frage darf
# das Gate nie streichen — sonst nimmt es ihr die Stimme (der Frage-Anker
# haengt genau diese Frage ans Zugende).
_OFFEN_FELD: dict[str, str] = {
    "name": "name", "vorname": "name", "nachname": "name",
    "vorname_check": "name", "nachname_check": "name",
    "buchstabieren": "buchstabieren",
    "telefon": "telefon", "telefon_check": "telefon", "telefon_alt": "telefon",
    "arzt": "arzt", "arzt_check": "arzt",
    "grund": "grund",
    "schonmal": "schonmal",
    "wunsch": "wunsch",
    "versicherung": "versicherung", "versicherung_check": "versicherung",
    "pzr": "pzr", "pzr_kasse": "pzr_kasse", "termin_anbieten": "pzr",
    "bleaching": "bleaching", "bleaching_check": "bleaching",
    "slotwahl": "slotwahl",
    "bestaetigung": "bestaetigung",
    "fuer_wen_check": "fuer_wen", "fuer_wen": "fuer_wen",
}


def offenes_feld(s: dict) -> str:
    """Job-Feld der offenen Maschinenfrage (leer, wenn keine offen ist)."""
    return _OFFEN_FELD.get(_s((s or {}).get("frage")), "")


def feld_der_frage(s: dict, satz: str) -> tuple[str, bool]:
    """Welches Job-Feld erfragt dieser Satz — und steht der Wert schon?

    Rueckgabe ``("", False)`` wenn der Satz keine Job-Frage ist (keine Frage,
    reine Rueckfrage gegen einen Wert, oder ein Thema ausserhalb der Felder).
    """
    t = _s(satz)
    if "?" not in t or _RUECKFRAGE_RE.search(t):
        return "", False
    for feld, cre, belegt in _FELDER:
        if cre.search(t):
            try:
                return feld, bool(belegt(s or {}))
            except Exception:              # pragma: no cover - nie werfend
                return feld, False
    return "", False


def saeubern(sit: dict, text: str) -> tuple[str, str, bool]:
    """Job-Fragen aus einer Modell-Antwort streichen.

    Rueckgabe ``(text, feld, belegt)`` — ``feld`` ist leer, wenn nichts
    gestrichen wurde. Im Modus ``shadow`` bleibt der Text unveraendert, das
    erkannte Feld wird aber gemeldet (fuer die Spur).

    Zwei Ausnahmen, damit das Gate nichts kaputt macht:

    - Laeuft ueberhaupt keine Aufgabe (kein ``modus``), gehoert die Frage dem
      Gespraech — ein "Worum geht es denn?" als Eroeffnung bleibt stehen.
    - Die GERADE offene Maschinenfrage bleibt stehen: das Modell spricht dann
      nur aus, worauf die Maschine schon wartet.
    """
    t = _s(text)
    lage = modus()
    if not t or lage == "off":
        return text, "", False
    s = (sit or {}).get("sammler") or {}
    if not _s(s.get("modus")):
        return text, "", False
    offen = offenes_feld(s)
    getroffen, war_belegt = "", False
    behalten: list[str] = []
    for satz in _SATZ_ENDE_RE.split(t):
        feld, belegt = feld_der_frage(s, satz)
        if feld and feld == offen:
            feld = ""
        if feld and not getroffen:
            getroffen, war_belegt = feld, belegt
        if feld:
            continue
        behalten.append(satz)
    if not getroffen:
        return text, "", False
    if lage != "enforce":
        return text, getroffen, war_belegt
    rest = " ".join(x for x in behalten if _s(x)).strip()
    return rest, getroffen, war_belegt
