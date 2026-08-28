"""Telefonnummern sicher hören und rückbestätigen (rein, ohne Netz).

Am Telefon kommen Nummern gemischt an: als Ziffern ("0177 600 4600"), als
Zahlwörter ("null eins sieben sieben ..."), als Paare ("siebenundsiebzig")
oder mit "Doppel" ("Doppel-Null"). Hier wird alles zu einer Ziffernkette
zusammengesetzt; die Rückbestätigung spricht Ziffer für Ziffer in Gruppen,
damit ElevenLabs nichts verschleift.
"""

from __future__ import annotations

import re
from typing import Any

_EINER = {
    "null": 0, "eins": 1, "ein": 1, "eine": 1, "zwei": 2, "zwo": 2, "drei": 3,
    "vier": 4, "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8,
    "neun": 9,
}
_ZEHN_BIS = {
    "zehn": 10, "elf": 11, "zwölf": 12, "zwoelf": 12, "dreizehn": 13,
    "vierzehn": 14, "fünfzehn": 15, "fuenfzehn": 15, "sechzehn": 16,
    "siebzehn": 17, "achtzehn": 18, "neunzehn": 19,
}
_ZEHNER = {
    "zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40,
    "fünfzig": 50, "fuenfzig": 50, "sechzig": 60, "siebzig": 70,
    "achtzig": 80, "neunzig": 90,
}
_WORT_ZIFFER = {"null": "0", "eins": "1", "ein": "1", "zwo": "2", "zwei": "2",
                "drei": "3", "vier": "4", "fünf": "5", "fuenf": "5", "sechs": "6",
                "sieben": "7", "acht": "8", "neun": "9"}

# Die Browser-Spracherkennung rutscht bei Ziffernfolgen ins Englische
# ("sechshundert" kommt als "six hundred" an — live 27.08.2026).
_EN_ZIFFER = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_ZIFFER_WORT = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs",
                "sieben", "acht", "neun"]

_UND_RE = re.compile(r"^([a-zäöüß]+)und([a-zäöüß]+)$")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _token_ziffern(tok: str) -> str:
    """Ein Wort-Token in Ziffern übersetzen ('' wenn keins)."""
    if tok in _EINER:
        return str(_EINER[tok])
    if tok in _ZEHN_BIS:
        return str(_ZEHN_BIS[tok])
    if tok in _ZEHNER:
        return str(_ZEHNER[tok])
    if tok in _EN_ZIFFER:
        return str(_EN_ZIFFER[tok])
    m = _UND_RE.match(tok)
    if m and m.group(1) in _EINER and m.group(2) in _ZEHNER:
        return str(_ZEHNER[m.group(2)] + _EINER[m.group(1)])
    return ""


def ziffern(text: str) -> str:
    """Alle gehörten Ziffern des Satzes, in Sprechreihenfolge."""
    raw = _s(text).lower().replace("-", " ").replace("/", " ")
    raw = re.sub(r"[.,;:!?()]+", " ", raw)
    out: list[str] = []
    toks = raw.split()
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok in {"plus"} and i + 1 < len(toks):
            out.append("+")
            i += 1
            continue
        if tok.startswith("doppel") or tok == "double":
            praefix = "doppel" if tok.startswith("doppel") else "double"
            rest = tok[len(praefix):].lstrip("te").lstrip("s")
            ziel = _token_ziffern(rest) if rest else (
                _token_ziffern(toks[i + 1]) if i + 1 < len(toks) else "")
            if ziel and len(ziel) == 1:
                out.append(ziel * 2)
                i += 1 if rest else 2
                continue
        if tok in {"hundred", "hundert"} and out and out[-1].isdigit() and len(out[-1]) == 1:
            # "six hundred" / "sechs hundert" = Ziffer + zwei Nullen (600).
            out[-1] = out[-1] + "00"
            i += 1
            continue
        if tok in {"thousand", "tausend"} and out and out[-1].isdigit() and len(out[-1]) == 1:
            out[-1] = out[-1] + "000"
            i += 1
            continue
        if tok.endswith("hundert") and tok[: -len("hundert")] in _EINER:
            # "sechshundert" als EIN Wort.
            out.append(str(_EINER[tok[: -len("hundert")]]) + "00")
            i += 1
            continue
        d = "".join(c for c in tok if c.isdigit() or c == "+")
        if d:
            out.append(d)
            i += 1
            continue
        w = _token_ziffern(tok)
        if w:
            out.append(w)
            i += 1
            continue
        i += 1
    return "".join(out)


def normaliert(nummer: str) -> str:
    d = "".join(c for c in _s(nummer) if c.isdigit() or c == "+")
    if d.startswith("+49"):
        d = "0" + d[3:]
    elif d.startswith("0049"):
        d = "0" + d[4:]
    elif d.startswith("49") and len(d) >= 11:
        d = "0" + d[2:]
    return d.replace("+", "")


def plausibel(nummer: str) -> bool:
    d = normaliert(nummer)
    return d.startswith("0") and 10 <= len(d) <= 13


def aus_satz(text: str) -> str:
    """Beste Telefonnummer aus dem Satz — '' wenn nichts Plausibles."""
    kette = ziffern(text)
    d = normaliert(kette)
    if plausibel(d):
        return d
    return ""


def _sieht_aus_wie_neuanfang(n: str) -> bool:
    """Echte deutsche Vorwahl (01xx/02xx…), nicht 00… (international / STT-Müll)."""
    return bool(n) and n.startswith("0") and len(n) >= 4 and not n.startswith("00")


def zusammenfuegen(alt: str, neu: str) -> str:
    """Zwei gehörte Stücke zu einer Kette.

    Live 28.08.2026: STT lieferte 017760046, Bianca bat um die ganze Nummer,
    der Anrufer setzte bei 0177… neu an, STT schnitt wieder ab (01776) —
    der kürzere Neuanfang hat den längeren Stand erschlagen. Nie mehr.
    """
    a = normaliert(alt)
    n = normaliert(neu)
    if not n:
        return a
    if not a:
        return n
    if n == a:
        return a
    if a.startswith(n) and len(a) > len(n):
        return a
    if n.startswith(a):
        return n
    # Fast fertige Handy-Nummer + fehlende End-Nullen ("null null").
    if 8 <= len(a) <= 9 and a.startswith("01") and n in {"0", "00", "000"}:
        return (a + n)[:13]
    for k in range(min(len(a), len(n)), 1, -1):
        if a.endswith(n[:k]):
            return (a + n[k:])[:16]
    # "004" nach einem langen Stamm ist STT-Müll, keine Fortsetzung.
    if n.startswith("0") and len(n) <= 3 and len(a) >= 6:
        return a
    if _sieht_aus_wie_neuanfang(n):
        if len(n) < len(a):
            return a
        if len(n) >= 10:
            return n
        if a[:4] != n[:4]:
            return n
    return (a + n)[:16]


def rest_frage(teil: str) -> str:
    """Was wir schon haben vorlesen — nicht immer 'komplett, Ziffer für Ziffer'."""
    d = normaliert(teil)
    gehoert = sprechbar(d)
    if 8 <= len(d) <= 9 and d.startswith("01"):
        return f"Ich habe bisher {gehoert}. Die letzten Ziffern bitte noch einmal."
    if gehoert:
        return f"Ich habe bisher {gehoert}. Wie geht die Nummer weiter?"
    return (
        "Da fehlt noch ein Stück von der Nummer — "
        "sagen Sie sie bitte einmal komplett, Ziffer für Ziffer."
    )


def _gruppen(d: str) -> list[str]:
    """0177 600 46 00 — Vorwahl zuerst, Rest in Zweier-/Dreiergruppen."""
    if not d:
        return []
    kopf = 4
    if d.startswith("01") and len(d) >= 11:
        kopf = 4
    elif d.startswith("0"):
        kopf = min(4, len(d))
    teile = [d[:kopf]]
    rest = d[kopf:]
    while rest:
        n = 3 if len(rest) % 2 == 1 else 2
        teile.append(rest[:n])
        rest = rest[n:]
    return [t for t in teile if t]


def sprechbar(nummer: str) -> str:
    """Ziffer für Ziffer in Gruppen: 'null eins sieben sieben, sechs null null, ...'"""
    d = normaliert(nummer)
    gruppen = []
    for g in _gruppen(d):
        gruppen.append(" ".join(_ZIFFER_WORT[int(c)] for c in g))
    return ", ".join(gruppen)
