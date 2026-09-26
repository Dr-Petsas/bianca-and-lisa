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
    r"i(?:['’]m|\s+am)\s+sorry|im\s+sorry|sorry|"
    r"thank(?:s|\s+you)(?:\s+for\s+watching)?|"
    r"thanks(?:\s+for\s+watching)?|"
    r"thanks?\s+for\s+(?:listening|joining)|"
    r"see\s+you(?:\s+next\s+time)?|"
    r"good\s+(?:morning|afternoon|evening|night)|"
    r"come\s+on|"
    r"wow|whoa|"
    r"bye+|goodbye|"
    r"subscribe|"
    r"please\s+subscribe|"
    r"(?:music|applause|inaudible)|"
    r"subtitles?\s+by.*|"
    r"captions?\s+by.*"
    r")\s*[.!?]*\s*$",
    re.I,
)

_ENGLISH_WORDS = frozenset({
    "a", "about", "all", "am", "an", "and", "appointment", "are", "at",
    "back", "be", "because", "but", "call", "can", "could", "day", "do",
    "friday",
    "for", "from", "good", "got", "had", "has", "have", "hello", "help",
    "here", "i", "if", "in", "is", "it", "like", "me", "morning", "my",
    "monday",
    "name", "need", "not", "of", "on", "or", "please", "question", "sorry",
    "saturday", "suck", "sucks", "sunday", "teen", "thank", "thanks", "that",
    "the", "there", "this", "thursday", "time", "to", "tuesday", "want",
    "was", "wednesday", "we", "what", "when", "with", "would", "you", "your",
})
_GERMAN_STRUCTURE = frozenset({
    "aber", "also", "bitte", "brauche", "danke", "das", "dem", "den",
    "der", "die", "doch", "ein", "eine", "einen", "für", "gerne", "habe",
    "haben", "hat", "heute", "ich", "ist", "ja", "kann", "kein", "keine",
    "mein", "meine", "möchte", "morgen", "nein", "nicht", "noch", "oder",
    "sie", "sind", "termin", "uhr", "um", "und", "uns", "was", "wir", "zu",
    "zum", "zur",
})


def _woerter(text: str) -> list[str]:
    # Apostrophe trennen: "I'm sorry" -> ["i", "m", "sorry"]. Das
    # Kontraktions-"m" wird unten neutral behandelt.
    return re.findall(r"[a-zäöüß]+", _s(text).casefold())


def ist_stille_halluzination(text: str) -> bool:
    """Parakeet auf Ruhe/Echo oder reines Englisch: kein Anrufer-Satz.

    Die Telefon-KI führt deutsche Gespräche. Reine englische Sätze ohne
    einen einzigen deutschen Strukturanker sind bei Parakeet/Qwen auf
    Stille und Leitungsrauschen ein wiederkehrendes Halluzinationsmuster.
    Gemischte deutsche Sätze ("Sorry, ich brauche einen Termin") und
    Eigennamen bleiben bewusst erhalten.
    """
    t = _s(text)
    if not t:
        return False
    if _STILLE_HALLU_RE.match(t):
        return True
    if any(ch.isdigit() for ch in t):
        return False
    woerter = _woerter(t)
    if not woerter or any(w in _GERMAN_STRUCTURE for w in woerter):
        return False
    relevant = [w for w in woerter if w not in {"m", "s", "re", "ve", "ll", "d"}]
    if len(relevant) < 2:
        return False
    englisch = sum(w in _ENGLISH_WORDS for w in relevant)
    englischer_anfang = relevant[0] in {
        "i", "we", "you", "my", "your", "the", "good",
    }
    return englisch >= 2 and (
        englisch / len(relevant) >= 0.75 or englischer_anfang
    )


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
