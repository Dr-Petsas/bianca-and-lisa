"""Blessing: Menüantwort und Terminwunsch sind kein Sofort-Kommen.

Ein allein gesagtes „Notfall“ in der Sprechzeit bleibt der Sofort-Satz.
„Akute Hautbeschwerden“, „Hautkontrolle“ und „Beratung“ sind die Antwort
auf Biancas eigene Frage. „Notfalltermin morgen um 12:30“ ist eine Buchung.
„Liegt nicht“ beendet den Sofort-Satz, auch wenn „nicht“ hinter dem Wort steht.
"""

from __future__ import annotations

from functools import lru_cache
import re

from lingua import Language, LanguageDetectorBuilder

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
    r"damn(?:\s+it)?|"
    r"f+u+c+k+(?:\s+(?:it|off|you))?|"
    r"bullshit|shit|"
    r"what\s+the\s+hell|"
    r"queen\s+service|"
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
    "back", "be", "because", "before", "book", "booking", "but", "call",
    "can", "cancel", "cleaning", "correct", "could", "customer", "damn", "day",
    "dental", "dentist", "do", "doctor", "done", "english", "friday",
    "for", "from", "good", "got", "had", "has", "have", "hello", "help",
    "here", "how", "i", "if", "in", "is", "it", "later", "like", "me",
    "morning", "move", "my", "monday", "name", "need", "new", "next", "no",
    "nope", "not", "now", "of", "off", "okay", "on", "or", "please",
    "queen", "question", "right", "saturday", "see", "service", "shit",
    "should", "sorry", "speak", "suck", "sucks", "sunday", "teen", "tell",
    "thank", "thanks", "that", "the", "there", "this", "thursday", "time",
    "to", "tomorrow", "tuesday", "understand", "want", "was", "wednesday",
    "we", "what", "when", "where", "why", "will", "with", "would", "yes",
    "you", "your",
})
_ENGLISH_SINGLE = frozenset({
    "afternoon", "appointment", "book", "booking", "bye", "cancel", "cleaning",
    "correct", "customer", "damn", "dental", "dentist", "doctor", "emergency",
    "english", "evening", "fuck", "goodbye", "hello", "help", "hey", "hi",
    "jep", "later", "morning", "nine", "no", "nope", "okay", "pain", "please",
    "question", "right", "shit", "sorry", "thanks", "today", "tooth",
    "toothache", "stop", "tomorrow", "understand", "what", "when", "where",
    "why", "wrong", "yeah", "yea", "yep", "yes",
})
_GERMAN_STRUCTURE = frozenset({
    "aber", "also", "bitte", "brauche", "danke", "das", "dem", "den",
    "der", "die", "doch", "ein", "eine", "einen", "fertig", "für", "gerne", "habe",
    "haben", "hat", "heute", "ich", "ist", "ja", "kann", "kein", "keine",
    "mein", "meine", "möchte", "morgen", "nein", "nicht", "noch", "oder",
    "sie", "sind", "termin", "uhr", "um", "und", "uns", "was", "wir", "zu",
    "zum", "zur",
})
_DEUTSCHE_KURZBESTAETIGUNG_RE = re.compile(
    r"^\s*(?:ja+|jap+p?|jep|jup+p?|joa?|m+h+m+|mm?-?hmm?|"
    r"ok(?:ay)?)\s*[.!?…]*\s*$",
    re.I,
)


@lru_cache(maxsize=1)
def _de_en_detector():
    """Kleiner, lokaler Sprachentscheid; kein Netz und kein LLM."""

    return LanguageDetectorBuilder.from_languages(
        Language.ENGLISH,
        Language.GERMAN,
    ).build()


def _woerter(text: str) -> list[str]:
    # Apostrophe trennen: "I'm sorry" -> ["i", "m", "sorry"]. Das
    # Kontraktions-"m" wird unten neutral behandelt.
    return re.findall(r"[a-zäöüß]+", _s(text).casefold())


def _sieht_wie_eigenname_aus(text: str, woerter: list[str]) -> bool:
    """Namen wie „Alice Biberci“ nicht wegen englischer Statistik sperren."""

    teile = re.findall(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß'’-]*", _s(text))
    return (
        1 <= len(teile) <= 4
        and len(teile) == len(woerter)
        and all(teil[:1].isupper() for teil in teile)
        and not all(wort in _ENGLISH_WORDS for wort in woerter)
    )


def _sieht_wie_buchstabieren_aus(text: str) -> bool:
    """Deutliche Einzelbuchstaben eines Namens, nicht englische Prosa."""
    t = _s(text)
    einzelne = re.findall(
        r"(?<![A-Za-zÄÖÜäöüß])[A-Za-zÄÖÜäöüß](?![A-Za-zÄÖÜäöüß])",
        t,
    )
    return len(einzelne) >= 3 or (len(einzelne) >= 2 and "-" in t)


def _lingua_ist_englisch(text: str) -> bool:
    werte = {
        wert.language: float(wert.value)
        for wert in _de_en_detector().compute_language_confidence_values(text)
    }
    englisch = werte.get(Language.ENGLISH, 0.0)
    deutsch = werte.get(Language.GERMAN, 0.0)
    # Kurze Telefonzüge brauchen einen klaren Vorsprung. Explizite englische
    # Kurzformen und Phrasen werden bereits vor diesem statistischen Schritt
    # hart verworfen.
    return englisch >= 0.60 and englisch - deutsch >= 0.12


def ist_stille_halluzination(text: str, *, kontext: str = "") -> bool:
    """Parakeet auf Ruhe/Echo oder Englisch: kein Anrufer-Satz.

    Die Telefon-KI führt deutsche Gespräche. Englische STT-Ausgaben werden
    weder normalisiert noch übersetzt oder an Dialog/Qwen-Korrektor
    weitergereicht. Im engen Ja/Nein-Kontext bleiben nur gebraeuchliche
    deutsche Kurzformen erhalten; bei Namensfragen auch klar getrennte
    Einzelbuchstaben. Gemischte Sätze mit eindeutig deutscher Struktur und
    Eigennamen bleiben ebenfalls erhalten.
    """
    t = _s(text)
    if not t:
        return False
    k = _s(kontext).casefold()
    if k == "ja_nein" and _DEUTSCHE_KURZBESTAETIGUNG_RE.match(t):
        return False
    # Auf eine Namens-Rückbestätigung kann der Anrufer statt Ja/Nein direkt
    # mit der korrigierten Buchstabierung antworten. Das starke Buchstaben-
    # Signal bleibt deshalb auch im Ja/Nein-Kontext geschützt.
    if k in {"name", "ja_nein"} and _sieht_wie_buchstabieren_aus(t):
        return False
    if _STILLE_HALLU_RE.match(t):
        return True
    if not any(ch.isalpha() for ch in t):
        return False
    woerter = _woerter(t)
    if not woerter or any(w in _GERMAN_STRUCTURE for w in woerter):
        return False
    relevant = [w for w in woerter if w not in {"m", "s", "re", "ve", "ll", "d"}]
    if len(relevant) == 1 and relevant[0] in _ENGLISH_SINGLE:
        return True
    if len(relevant) < 2:
        return _lingua_ist_englisch(t) and not _sieht_wie_eigenname_aus(
            t, relevant
        )
    englisch = sum(w in _ENGLISH_WORDS for w in relevant)
    englischer_anfang = relevant[0] in {
        "i", "we", "you", "my", "your", "the", "good",
    }
    if englisch >= 2 and (
        englisch / len(relevant) >= 0.75 or englischer_anfang
    ):
        return True
    if _sieht_wie_eigenname_aus(t, relevant):
        return False
    return _lingua_ist_englisch(t)


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
