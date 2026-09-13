"""Abwegige Bitten ernst nehmen (W-ABSCHWEIFEN 13.09.2026).

Chef 13.09.2026 zum Live-Anruf 48673eca: „ausserdem bist du nicht auf den
anrufer eingegangen als der verlangte: zähl mal von 1 bis 4 oder
buchstabiere meinen namen Abdullah … die ki muss dann schon gezielter auf
solche abwägigen themen eingehen können. das ist ja unser talk floor
eigentlich … ein abschweifen … das wurde nicht gut genug bearbeitet."

Live lief genau das schief: „Wiederhol mal die Zahlen 1, 2, 3, 4." landete
als Rückruf-Notiz („die Praxis prüft Ihren Wunsch"), „buchstabiere meinen
Namen Abdullah" beantwortete das Modell mit „Danke für Ihren Namen." und
„Das ist eine interessante Idee, danke für den Tipp!".

Solche Bitten sind harmlos, sofort erfüllbar und ein Vertrauensbeweis —
deshalb antwortet die Maschine deterministisch (0 ms, kein Modell) und
hängt die offene Pflichtfrage an. Nichts davon berührt Kalender, Kartei
oder Sammler: es wird NUR gesprochen.

Notaus: ``ABSCHWEIFEN=0`` => ``antwort()`` liefert immer "".
"""

from __future__ import annotations

import os
import re
from typing import Any

from kern import sprech

# Zahlwörter, die als Grenze einer Zähl-Bitte vorkommen ("von eins bis vier").
_WORT_ZAHL: dict[str, int] = {
    "null": 0, "eins": 1, "ein": 1, "eine": 1, "zwei": 2, "drei": 3,
    "vier": 4, "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8,
    "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "zwoelf": 12,
    "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15, "fuenfzehn": 15,
    "sechzehn": 16, "siebzehn": 17, "achtzehn": 18, "neunzehn": 19,
    "zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40,
    "fünfzig": 50, "fuenfzig": 50, "hundert": 100,
}
_ZAHL_TEIL = r"\d{1,3}|" + "|".join(sorted(_WORT_ZAHL, key=len, reverse=True))

# „zähl mal von 1 bis 4", „kannst du bis zehn zählen", „zähle bitte bis 20"
_ZAEHL_VERB_RE = re.compile(r"\b(?:ab)?z(?:ä|ae)hl\w*\b", re.I)
_ZAEHL_VON_BIS_RE = re.compile(
    rf"\bvon\s+(?P<von>{_ZAHL_TEIL})\s+(?:bis|auf)\s+(?P<bis>{_ZAHL_TEIL})\b", re.I)
_ZAEHL_BIS_RE = re.compile(rf"\bbis\s+(?:zur\s+|zum\s+)?(?P<bis>{_ZAHL_TEIL})\b", re.I)

# „wiederhol mal die Zahlen 1, 2, 3, 4", „folgende Ziffern wiederholen, 335"
_ZIFFERN_VERB_RE = re.compile(
    r"\b(?:wiederhol\w*|sag\w*|sprich\w*|nenn\w*|lies\w*|les\w*|vorles\w*)\b", re.I)
_ZIFFERN_WORT_RE = re.compile(
    r"\b(?:zahl(?:en|enfolge)?|ziffer(?:n|nfolge)?)\b", re.I)

# „buchstabiere meinen Namen Abdullah", „kannst du Müller buchstabieren"
_BUCHSTABIER_RE = re.compile(r"\bbuchstabier\w*\b", re.I)
_BUCHSTABIER_NAME_RE = re.compile(
    r"\b(?:namen?|nachnamen?|vornamen?|wort)\b\s+"
    r"(?!buchstabier)(?P<wort>[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß-]{2,})",
    re.I,
)
# Eine echte Buchstabierkette ("A, B, D, U") ist die Antwort des ANRUFERS —
# dann gehoert der Satz der Namens-Ernte, nicht dieser Spielerei.
_KETTE_RE = re.compile(
    r"\b[A-Za-zÄÖÜäöüß]\b(?:[\s,.;-]+\b[A-Za-zÄÖÜäöüß]\b)+")
# Füllwörter, die nach „buchstabiere" stehen können, ohne das Ziel zu sein.
_KEIN_ZIEL = {
    "mal", "mir", "uns", "bitte", "doch", "kurz", "einmal", "nochmal",
    "meinen", "meine", "mein", "deinen", "deine", "dein", "den", "die",
    "das", "ihren", "ihre", "ihr", "namen", "name", "nachnamen", "nachname",
    "vornamen", "vorname", "wort", "es", "du", "sie", "kannst", "können",
    "koennen", "kann", "soll", "sollst", "wie", "kannste", "kanns",
}
_MAX_ZAEHLEN = 20

# Die Bitte muss AN Bianca gerichtet sein: Imperativ am Satzanfang oder eine
# Anrede/Hoeflichkeitsform. "Ich buchstabiere: Tzannis" ist das Gegenteil —
# da diktiert der Anrufer, das gehoert der Namens-Ernte.
_ICH_RE = re.compile(
    r"\bich\s+(?:\w+\s+){0,2}?"
    r"(?:buchstabier\w*|z(?:ä|ae)hl\w*|wiederhol\w*|sag\w*|nenn\w*)\b", re.I)
_ANREDE_RE = re.compile(
    r"\b(?:du|dir|dich|sie|ihnen|mal|bitte|kannst|kannste|k(?:ö|oe)nn\w*|"
    r"soll\w*|w(?:ü|ue)rd\w*|magst|m(?:ö|oe)cht\w*)\b", re.I)


def _an_bianca(text: str, verb: re.Match[str] | None) -> bool:
    if _ICH_RE.search(text):
        return False
    if _ANREDE_RE.search(text):
        return True
    # Imperativ am Satzanfang ("Zähl von eins bis vier.")
    return bool(verb) and not _s(text[: verb.start()]).strip(" ,.;-:!?")


def an() -> bool:
    """Notaus: ABSCHWEIFEN=0 => Verhalten wie vor dem 13.09.2026."""
    return os.environ.get("ABSCHWEIFEN", "1").strip() != "0"


def _s(v: Any) -> str:
    return (v or "").strip() if isinstance(v, str) else ("" if v is None else str(v).strip())


def _zahl(roh: str) -> int | None:
    t = _s(roh).lower()
    if not t:
        return None
    if t.isdigit():
        return int(t)
    return _WORT_ZAHL.get(t)


def _reihe(von: int, bis: int) -> str:
    """„eins, zwei, drei, vier" — gedeckelt, damit niemand bis 100 zuhören muss."""
    schritt = 1 if bis >= von else -1
    zahlen = list(range(von, bis + schritt, schritt))
    gekappt = len(zahlen) > _MAX_ZAEHLEN
    zahlen = zahlen[:_MAX_ZAEHLEN]
    worte = ", ".join(sprech.zahl_wort(n) for n in zahlen)
    return f"{worte} und so weiter" if gekappt else worte


def _zaehlen(text: str) -> str:
    verb = _ZAEHL_VERB_RE.search(text)
    if not verb or not _an_bianca(text, verb):
        return ""
    m = _ZAEHL_VON_BIS_RE.search(text)
    if m:
        von, bis = _zahl(m.group("von")), _zahl(m.group("bis"))
    else:
        m = _ZAEHL_BIS_RE.search(text)
        if not m:
            return ""
        von, bis = 1, _zahl(m.group("bis"))
    if von is None or bis is None or not (0 <= von <= 999 and 0 <= bis <= 999):
        return ""
    return f"Gerne: {_reihe(von, bis)}."


def _ziffern(text: str) -> str:
    verb = _ZIFFERN_VERB_RE.search(text)
    if not verb or not _ZIFFERN_WORT_RE.search(text):
        return ""
    if not _an_bianca(text, verb):
        return ""
    ziffern = re.sub(r"\D", "", text)
    if len(ziffern) < 2 or len(ziffern) > 12:
        return ""
    worte = ", ".join(sprech.zahl_wort(int(z)) for z in ziffern)
    return f"Gerne: {worte}."


def _buchstabier_ziel(text: str) -> str:
    m = _BUCHSTABIER_NAME_RE.search(text)
    if m:
        return m.group("wort")
    # „buchstabiere mal Abdullah" / „Kannst du Müller buchstabieren?" —
    # erstes taugliches Wort nach dem Verb, sonst das letzte davor.
    # Einzelbuchstaben („buchstabiere A B C") scheiden aus: das ist eine
    # Buchstabierung des Anrufers, keine Bitte an Bianca.
    verb = _BUCHSTABIER_RE.search(text)
    if not verb:
        return ""
    for wort in re.findall(r"[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß-]*", text[verb.end():]):
        if wort.lower() not in _KEIN_ZIEL and len(wort) >= 3:
            return wort
    for wort in reversed(
        re.findall(r"[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß-]*", text[:verb.start()])
    ):
        if wort.lower() not in _KEIN_ZIEL and len(wort) >= 3:
            return wort
    return ""


def _buchstabieren(text: str, name: str) -> str:
    verb = _BUCHSTABIER_RE.search(text)
    if not verb or _KETTE_RE.search(text) or not _an_bianca(text, verb):
        return ""
    ziel = _buchstabier_ziel(text) or _s(name)
    if len(ziel) < 3 or not re.fullmatch(r"[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß-]+", ziel):
        return ""
    from bianca import buchstaben  # lokal: kern laedt vor bianca

    tafel = buchstaben.vorlesen(ziel)
    if not tafel:
        return ""
    return f"Gerne: {tafel}."


def antwort(text: str, *, name: str = "") -> str:
    """Die deterministische Antwort auf eine abwegige Bitte — "" wenn keine.

    ``name`` ist ein BELEGTER Name aus dem Sammler (fuer „buchstabiere
    meinen Namen" ohne genanntes Wort). Nie geraten: ohne belegten Namen
    bleibt die Buchstabier-Bitte unbeantwortet und das Gespraech laeuft
    normal weiter.
    """
    t = _s(text)
    if not t or not an():
        return ""
    return _zaehlen(t) or _ziffern(t) or _buchstabieren(t, name)
