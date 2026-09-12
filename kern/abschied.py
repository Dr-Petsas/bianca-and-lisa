"""Abschied erkennen und den Anruf wirklich beenden (W-ABSCHIED 12.09.2026).

Chef 12.09.2026 (wörtlich): "Bianca soll lernen aufzulegen bei eindeutigen
sätzen die ein gespräch beenden wie thüss auf wieder höhren wiedersehen bis
denn etc."

Live-Befund Session 9395e2ce (11.09.2026, 109 Züge / 23 Minuten): der
Anrufer war längst fertig, Bianca fragte weiter nach der Handynummer und die
Leitung blieb offen, bis der Anrufer selbst auflegte. `bianca/flow`
verabschiedete sich zwar mit "Auf Wiederhören", setzte aber NIE `hangup` —
ausgesprochen wurde der Abschied, technisch lief der Anruf weiter.

Zwei Sicherheitsstufen, damit ein verhörtes Wort keinen laufenden Vorgang
abwürgt (der letzte Satz zählt, davor geerntete Daten bleiben erhalten):

- **Unmissverständliche Kerne** ("auf Wiederhören", "auf Wiedersehen",
  "tschüss") — reichen allein.
- **Kurzformen** ("bis denn", "ciao", "schönen Tag noch") — nur, wenn der
  Satz nach Abzug der Höflichkeitsfloskeln nichts anderes mehr enthält.

In BEIDEN Fällen darf der Schlusssatz nach Abzug der Floskeln höchstens
`MAX_KERN_WOERTER` Wörter tragen. "Ich möchte den Termin verschieben,
tschüss." ist damit KEIN Abschied, "Okay, danke, tschüss." schon.

Ein blosses "Danke" oder "nein, danke" ist hier bewusst KEIN Abschied — das
entscheidet `bianca/flow._ABSCHIED_RE` zustandsabhängig weiter (nach
erledigtem Vorgang verabschiedet sich der Fluss, mitten im Formular fragt er
weiter).

Notaus: `ABSCHIED_AUFLEGEN=0` => nie auflegen (Verhalten wie vor dem Patch).
Tests: `tests/test_abschied.py`
"""

from __future__ import annotations

import os
import re
from typing import Any

# So viele Wörter darf der Schlusssatz nach Abzug der Floskeln noch tragen.
MAX_KERN_WOERTER = 5

_SATZ_ENDE_RE = re.compile(r"(?<=[.!?…])\s+")

# Umlaute kommen je nach Quelle als ö/oe/o an (STT, Dock-Tastatur, alte
# ASCII-Transkripte). Live 12.09.2026 rutschte „Auf Wiederhoeren!" deshalb
# durch und das Modell bettelte „bitte nicht auflegen".
_OE = r"(?:ö|oe|o)"
_UE = r"(?:ü|ue|u)"
_AE = r"(?:ä|ae|a)"

# Unmissverständlich: diese Formen sagt niemand mitten im Anliegen.
_KLAR_RE = re.compile(
    rf"auf\s*wieder\s*h{_OE}r|auf\s*wieder\s*seh|auf\s*wieder\s*schau|"
    rf"\bwiederh{_OE}ren\b|\bwiedersehen\b|"
    rf"\btsch{_UE}s{{1,2}}(?:i|chen)?\b|\badieu\b|\bad(?:i|ie)os\b",
    re.I,
)

# Kurzformen — nur wenn sonst nichts mehr im Satz steht.
_KURZ_RE = re.compile(
    rf"^(?:(?:dann|denn|na|tja|ach)\s+)?(?:"
    rf"bis\s+(?:denn|dann|bald|sp{_AE}ter|demn{_AE}chst|nachher)|"
    rf"ciao|tschau|servus|"
    rf"mach(?:en\s+sie)?(?:\s+es)?\s+gut|"
    rf"sch{_OE}nen\s+(?:tag|abend|feierabend|sonntag)(?:\s+noch)?|"
    rf"sch{_OE}nes\s+wochenende|"
    rf"alles\s+gute"
    rf")$",
    re.I,
)

# Höflichkeit trägt keine Bedeutung — sie darf den Abschied nicht verdecken.
_FLOSKEL_RE = re.compile(
    r"\b(?:ja|jaja|jo|okay|ok|oki|gut|klar|alles\s+klar|"
    r"danke(?:sch[oö]n)?|vielen(?:\s+lieben)?\s+dank|dank|bitte|"
    r"also|so|prima|super|perfekt|gerne|gern|ihnen|dir|euch|"
    r"ebenfalls|gleichfalls|desgleichen|nein|nee|"
    r"frau|herr|herrn|doktor|dr)\b",
    re.I,
)

# Anlauf-Wörter am Satzanfang — sie stehen dem Abschied nur im Weg.
_ANLAUF_WORT = {
    "ja", "jaja", "jo", "okay", "ok", "oki", "also", "so", "na", "tja", "ach",
    "gut", "danke", "dankeschön", "dankeschoen", "vielen", "lieben", "dank",
    "bitte", "nein", "nee", "prima", "super", "perfekt", "alles", "klar",
    "gerne", "gern", "und",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def an() -> bool:
    """Darf Bianca von sich aus auflegen? Notaus ABSCHIED_AUFLEGEN=0."""
    return (os.environ.get("ABSCHIED_AUFLEGEN") or "1").strip() != "0"


def _letzter_satz(text: str) -> str:
    saetze = [x for x in _SATZ_ENDE_RE.split(_s(text)) if _s(x)]
    return _s(saetze[-1]) if saetze else _s(text)


def _kern(satz: str) -> str:
    """Satz ohne Höflichkeitsfloskeln und Satzzeichen."""
    ohne = _FLOSKEL_RE.sub(" ", _s(satz))
    ohne = re.sub(r"[^\wäöüßÄÖÜ ]+", " ", ohne)
    return " ".join(ohne.split()).strip().casefold()


def _ohne_anlauf(satz: str) -> str:
    """Nur den Anlauf abräumen („Ja, okay, ciao." -> „ciao").

    Der Kern taugt für die Wortzahl, nicht für die Kurzform-Erkennung: er
    schluckt Wörter, die selbst zum Abschied gehören („machen Sie es gut")."""
    worte = re.sub(r"[^\wäöüßÄÖÜ ]+", " ", _s(satz)).casefold().split()
    i = 0
    while i < len(worte) and worte[i] in _ANLAUF_WORT:
        i += 1
    return " ".join(worte[i:])


def ist_abschied(text: str, streng: bool = False) -> bool:
    """Beendet dieser Satz das Gespräch unmissverständlich?

    `streng=True` (während Anrufer Ziffern oder Buchstaben diktiert) lässt
    NUR die unmissverständlichen Kerne gelten — ein verhörtes „ciao" darf
    keine halb erfasste Rufnummer wegwerfen."""
    satz = _letzter_satz(text)
    if not satz:
        return False
    kern = _kern(satz)
    if not kern:
        # Nur Floskeln ("Danke.", "Nein, danke.") — das entscheidet der Fluss
        # zustandsabhängig, nicht dieser Wächter.
        return False
    if len(kern.split()) > MAX_KERN_WOERTER:
        return False
    if _KLAR_RE.search(satz):
        return True
    if streng:
        return False
    return any(_KURZ_RE.match(k) for k in (_ohne_anlauf(satz), kern) if k)


def satz(anrede: str = "") -> str:
    """Freundlicher Schlusssatz — kurz, ohne neue Frage."""
    wer = _s(anrede)
    if wer:
        return f"Vielen Dank für Ihren Anruf, {wer}. Auf Wiederhören!"
    return "Vielen Dank für Ihren Anruf. Auf Wiederhören!"


def notbremse_satz(notiz: bool = False) -> str:
    """Schluss, wenn ein Gespräch nicht mehr vorankommt (Stille-Notleine).

    Live 11.09.2026 lief ein Anruf 23 Minuten im Wechsel aus „Sind Sie noch
    dran?" und derselben offenen Frage. Irgendwann ist Auflegen freundlicher
    als weiter zu nöleln — die Praxis bekommt eine Notiz."""
    if notiz:
        return ("Ich komme hier gerade nicht weiter. Ich habe alles für die "
                "Praxis notiert, dann melden wir uns bei Ihnen. Auf Wiederhören!")
    return ("Ich komme hier gerade nicht weiter. Rufen Sie uns gern noch "
            "einmal an, wenn es besser passt. Auf Wiederhören!")
