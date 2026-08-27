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
        if tok.startswith("doppel"):
            rest = tok[len("doppel"):].lstrip("te").lstrip("s")
            ziel = _token_ziffern(rest) if rest else (
                _token_ziffern(toks[i + 1]) if i + 1 < len(toks) else "")
            if ziel and len(ziel) == 1:
                out.append(ziel * 2)
                i += 1 if rest else 2
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
