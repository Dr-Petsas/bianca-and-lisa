"""W-EINWAND: Widerspruch gegen einen belegten Wert wird ZUERST korrigiert.

Chef 13.09.2026 (woertlich): "denk daran auch korrekturen einzubauen wenn eine
angabe nicht stimmt. telefon oder vorname oder was auch immer und der patient
da widerspricht, dass das dann zunaechst korrigiert wird und nicht uebergangen
wird — genau dafuer brauchen wir, dass auf das gesagte eingegangen wird."

Bis heute gab es die Korrektur nur an ZWEI Stellen: an der Readback-Frage
("Soll ich das so eintragen?" -> Nein -> `flow._aenderung_zug`) und beim Namen
(W-NAME-EINWAND). Mitten im Fragenfaden lief ein Widerspruch dagegen ins
Leere: "Moment, die Nummer stimmt nicht" brachte keine Ernte, die Maschine
stellte ihre offene Frage einfach weiter — der Einwand war ueberhoert.

Dieses Modul ist nur der ERKENNER (pur, ohne Bianca-Wissen): welches Feld
bestreitet der Satz? Geraeumt und neu erfragt wird in `bianca/flow.py`, weil
dort die Folgezustaende haengen (ein verworfener Behandler macht auch den
Slot-Vorrat wertlos).

Bewusst eng gehalten — ein falscher Treffer wuerde einen feststehenden Wert
wegwerfen (genau die Katastrophe aus Anruf 1fbda5db). Verlangt werden IMMER
drei Dinge: ein Widerspruchs-Marker, das Feldwort im selben Teilsatz und ein
Satz, der selbst keine Frage stellt.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Teilsaetze: der Marker muss beim Feldwort stehen. "Nein, ich wollte zur
# Kontrolle" bestreitet nicht den Behandler, nur weil irgendwo "Doktor" fiel.
_TEIL_RE = re.compile(r"[,;.!?]|\s+(?:aber|sondern|und)\s+")

# Widerspruch: Verneinung, Falsch-Wort oder "hat sich geaendert".
_MARKER_RE = re.compile(
    r"\b(?:nein|nich|nicht|nichts|kein|keine|keinen|falsch|verkehrt|"
    r"stimmt\s+(?:nicht|so\s+nicht)|"
    r"(?:ge)?ändert|(?:ge)?aendert|geändert|anders|andere[nrs]?|neue[nrs]?|"
    r"veraltet|alt|überholt|ueberholt)\b", re.I)

# "nicht mehr aktuell" / "stimmt nicht mehr" — eigener Marker, weil "aktuell"
# allein kein Widerspruch ist ("ist das aktuell?" fragt der Anrufer).
_NICHT_MEHR_RE = re.compile(r"\bnicht\s+mehr\b", re.I)

# Feldwoerter. Absichtlich ohne "Termin"/"Zeit": der Slot hat seine eigene
# Ablehnungs-Logik ("der passt nicht" waehlt einen anderen Slot) — die hier
# anzufassen wuerde die Buchungskette brechen.
#
# Fix 4 (13.09.2026): `arzt` steht VOR `name` — "Der Arzt heisst nicht
# Petsas" bestreitet den Behandler, nicht den Patientennamen (das Wort
# "heisst" gehoert sonst dem Namensfeld). `beschwerden` ist kein Feldwort
# mehr: "Ich habe keine Beschwerden" ist eine Zustandsangabe, kein
# Widerspruch gegen den Besuchsgrund.
_FELDER: list[tuple[str, re.Pattern[str]]] = [
    ("nummer", re.compile(
        r"\b(?:telefon|telefonnummer|handy|handynummer|mobilnummer|"
        r"rufnummer|nummer|festnetz)\b", re.I)),
    ("versicherung", re.compile(
        r"\b(?:versichert|versicherung|krankenkasse|kasse|privat|"
        r"gesetzlich|privatpatient|kassenpatient)\b", re.I)),
    ("arzt", re.compile(
        r"\b(?:arzt|ärztin|aerztin|zahnarzt|zahnärztin|behandler|"
        r"behandlerin|doktor|doc)\b", re.I)),
    ("name", re.compile(
        r"\b(?:name|namen|nachname|nachnamen|familienname|familiennamen|"
        r"vorname|vornamen|heiße|heisse|heiss|heisst|heißt)\b", re.I)),
    ("grund", re.compile(
        r"\b(?:grund|besuchsgrund|anliegen|behandlung)\b", re.I)),
]

# Der Anrufer FRAGT etwas ("Stimmt meine Nummer nicht?") — dann ist nichts
# bestritten, das gehoert dem Gespraech.
_FRAGE_RE = re.compile(r"[?]")

# Eine Bitte um Wiederholung ist kein Widerspruch ("wie war die Nummer?").
_NOCHMAL_RE = re.compile(
    r"\b(?:nochmal|noch\s+einmal|wiederhol\w*|wie\s+war)\b", re.I)

# --- Fix 4 (13.09.2026, Feldtest-Analyse): Fehltreffer eng machen -----------
# Ein falscher Einwand wirft einen feststehenden Wert weg und stellt die
# Frage neu — genau die Schleife, die wir bekaempfen. Deshalb werden
# Wendungen ausgenommen, in denen ein Marker steht, aber NICHTS bestritten
# wird. Jede Ausnahme hat eine Gegenprobe in tests/test_einwand.py.

# "keine andere Nummer" / "keinen anderen Arzt" = ausdruecklich KEINE
# Aenderung; "keine Beschwerden/Schmerzen" = Zustand; "8 Jahre alt" = Alter;
# "neue Patientin" = Neupatient, nicht "neuer Name".
_KEIN_WIDERSPRUCH_RE = re.compile(
    r"\bkein\w*\s+(?:andere\w*|neue\w*|zweite\w*|weitere\w*)\b"
    r"|\bkein\w*\s+(?:beschwerden|schmerzen|probleme?|ahnung|sorge)\b"
    r"|\bjahre?\s+alt\b"
    r"|\bneue[nrs]?\s+patient\w*"
    # Unwissen/Hoeren des ANRUFERS ist kein Widerspruch: "Ich weiss den Namen
    # nicht", "Ich habe den Namen nicht verstanden". (Umgekehrt "SIE haben
    # den Namen falsch verstanden" bleibt ein Einwand — kein "ich" davor.)
    r"|\b(?:wei(?:ß|ss)|wusste|kenne|kennen|erinnere)\b"
    r"|\bich\b[^,;.!?]*?\b(?:nicht|nichts)\s+(?:verstanden|geh(?:ö|oe)rt|mitbekommen)\b"
    # Rueckblick/Bewertung ("die Behandlung letztes Mal war nicht gut") ist
    # Erzaehlung, keine Korrektur der aktuellen Daten.
    r"|\b(?:letzte[sn]?\s+mal|damals|fr(?:ü|ue)her|neulich|beim\s+letzten)\b"
    r"|\b(?:gut|schlecht|toll|super|zufrieden|unzufrieden|unfreundlich|nett|"
    r"gewartet|teuer|schmerzhaft)\b",
    re.I,
)

# Bestaetigung mit vorangestelltem "Nein" ohne harte Verneinung im Teilsatz
# ("Nein die Nummer stimmt", "Nein der Name passt so") — STT verschluckt das
# Komma, der Anrufer bestaetigt aber. Nur ein HARTER Marker im selben
# Teilsatz macht daraus wieder einen Widerspruch ("die Nummer stimmt nicht").
_BESTAETIGT_RE = re.compile(
    r"\b(?:stimmt|passt|richtig|korrekt|bleibt|behalten|so\s+lassen|"
    r"ist\s+ok(?:ay)?|in\s+ordnung)\b", re.I)
_HART_RE = re.compile(
    r"\b(?:nicht|nich|nichts|kein\w*|falsch|verkehrt|(?:ge)?(?:ä|ae)ndert|"
    r"veraltet|alt|(?:ü|ue)berholt|ueberholt)\b", re.I)


def _teil_ist_kein_einwand(teil: str) -> bool:
    if _KEIN_WIDERSPRUCH_RE.search(teil):
        return True
    if _BESTAETIGT_RE.search(teil) and not _HART_RE.search(teil):
        return True
    return False


def modus() -> str:
    """``off`` | ``shadow`` | ``enforce`` (Default enforce).

    Ein ueberhoerter Einwand ist live jedes Mal als Schleife aufgefallen; der
    Rueckweg bleibt ueber ``EINWAND=off`` trotzdem offen.
    """
    roh = (os.getenv("EINWAND") or "enforce").strip().lower()
    if roh in {"0", "off", "aus", "false"}:
        return "off"
    if roh in {"shadow", "schatten", "log"}:
        return "shadow"
    return "enforce"


def _s(x: Any) -> str:
    return (x or "").strip() if isinstance(x, str) else ""


def feld(text: str) -> str:
    """Welchen belegten Wert bestreitet dieser Satz? ("" = keinen)

    Reihenfolge der Pruefung ist die Reihenfolge in ``_FELDER`` — bei einem
    Satz, der zwei Felder nennt, gewinnt das konkretere (Nummer vor Name).
    """
    t = _s(text)
    if not t or _FRAGE_RE.search(t) or _NOCHMAL_RE.search(t):
        return ""
    for teil in _TEIL_RE.split(t):
        teil = teil.strip()
        if not teil:
            continue
        if not (_MARKER_RE.search(teil) or _NICHT_MEHR_RE.search(teil)):
            continue
        if _teil_ist_kein_einwand(teil):
            # Fix 4: Marker ohne Widerspruch (Bestaetigung, Unwissen,
            # "keine andere", Rueckblick) — nichts bestritten.
            continue
        for name, cre in _FELDER:
            if cre.search(teil):
                return name
    return ""


def ist_widerspruch(text: str) -> bool:
    """Traegt der Satz ueberhaupt einen Widerspruchs-Marker?"""
    t = _s(text)
    return bool(t) and bool(_MARKER_RE.search(t) or _NICHT_MEHR_RE.search(t))
