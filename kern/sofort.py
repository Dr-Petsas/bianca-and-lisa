"""Blessing: Menüantwort und Terminwunsch sind kein Sofort-Kommen.

Ein allein gesagtes „Notfall“ in der Sprechzeit bleibt der Sofort-Satz.
„Akute Hautbeschwerden“, „Hautkontrolle“ und „Beratung“ sind die Antwort
auf Biancas eigene Frage. „Notfalltermin morgen um 12:30“ ist eine Buchung.
„Liegt nicht“ beendet den Sofort-Satz, auch wenn „nicht“ hinter dem Wort steht.
"""

from __future__ import annotations

import re

_NOTFALL_VERNEINT_RE = re.compile(
    r"\b(?:kein|keine|keinen)\s+(?:haut)?notfall\w*\b|"
    r"\b(?:haut)?notfall\w*\b[^.!?]{0,48}\bnicht\b|"
    r"\bnicht\b[^.!?]{0,24}\b(?:haut)?notfall\w*\b|"
    r"\bakut\w*\b[^.!?]{0,40}\bnicht\b",
    re.I,
)
_MENU_GRUND_RE = re.compile(
    r"\bakute\s+hautbeschwerden\b|\bhautkontrolle\b",
    re.I,
)
_BERATUNG_RE = re.compile(
    r"^(?:ich\s+(?:hätte|haette|möchte|moechte|brauche|will)\s+(?:gerne\s+)?)?"
    r"(?:eine\s+)?beratung[.!]?\s*$|"
    r"^\s*etwas\s+anderes[.!]?\s*$",
    re.I,
)
_NOTFALLTERMIN_RE = re.compile(r"\b(?:haut)?notfalltermin\w*\b", re.I)
_TERMINZEIT_RE = re.compile(
    r"\b(?:morgen|übermorgen|uebermorgen|uhr|montag|dienstag|mittwoch|"
    r"donnerstag|freitag|samstag|sonntag)\b|\d{1,2}[:.]\d{2}",
    re.I,
)
_STARK_RE = re.compile(
    r"\bstarke?\s+schmerz|\bblut|\batemnot|\bbewusstlos",
    re.I,
)
_VERBINDEN_RE = re.compile(r"verbind|durchstell|weiterleit", re.I)
_TERMIN_RE = re.compile(r"\btermin\b", re.I)
_DRITTE_RE = re.compile(
    r"f(?:ü|ue)r\s+(?:mein|unser|ein)(?:e|en|em)?\s+"
    r"(?:tochter|sohn|nachbar(?:in)?|kind|mann|mutter|vater|enkel\w*)\b",
    re.I,
)


def _s(v: object) -> str:
    return " ".join(str(v or "").split()).strip()


def unterdruecken(text: str) -> bool:
    """True: diesen Satz nicht als Sofort-Kommen / 116 117 sprechen."""
    t = _s(text)
    if not t:
        return False
    try:
        from kern import praxisregeln
        if praxisregeln.lebensgefahr(t):
            return False
    except Exception:
        pass
    if _NOTFALL_VERNEINT_RE.search(t):
        return True
    if _NOTFALLTERMIN_RE.search(t) and _TERMINZEIT_RE.search(t):
        return True
    if (_MENU_GRUND_RE.search(t) or _BERATUNG_RE.search(t)) and not _STARK_RE.search(t):
        if not re.search(r"\bnotfall\b", t, re.I):
            return True
    return False


_STILLE_HALLU_RE = re.compile(
    r"^\s*(?:"
    r"thank(?:s|\s+you)(?:\s+for\s+watching)?|"
    r"thanks(?:\s+for\s+watching)?|"
    r"come\s+on|"
    r"wow|whoa|"
    r"bye+|goodbye|"
    r"subscribe"
    r")\s*[.!?]*\s*$",
    re.I,
)


def ist_stille_halluzination(text: str) -> bool:
    """Parakeet auf Ruhe/Echo: kein Anrufer-Satz, keine nächste Frage."""
    return bool(_STILLE_HALLU_RE.match(_s(text)))


def transfer_ueberspringen(text: str) -> bool:
    """Termin oder Dritter schlägt einen verhörten Arztnamen.

    „Verbinden Sie mich“ bleibt eine Weiterleitung.
    """
    t = _s(text)
    if not t or _VERBINDEN_RE.search(t):
        return False
    if _TERMIN_RE.search(t) or _DRITTE_RE.search(t):
        return True
    return False
