"""Sprecherdeutlichkeit: Worte verfremden, bevor der Anrufer sie spricht.

Kategorien simulieren undeutliche Aussprache, Dialekt und aehnliche
Konsonanten — der Runner schickt das verfremdete WAV an STT. Ziffern und
Namens-/Nummern-Diktat bleiben unberuehrt.
"""

from __future__ import annotations

import random
import re
from typing import Any

KATEGORIEN = (
    ("hart", "Hart/weich — g↔k, d↔t, b↔p"),
    ("anlaut", "Anlaut — Mitarbeiter → Witarbeiter"),
    ("auslaut", "Auslaut — Ende weich oder weg"),
    ("chsch", "Dialekt — ch↔sch, ich→isch"),
    ("einfuegen", "Buchstaben dazumischen — Grönkenpid"),
    ("vertauschen", "Buchstaben vertauschen"),
    ("vokal", "Ähnlichklang — ei/ai, ä/e, ü/i"),
    ("verschlucken", "Laute verschlucken"),
)

DEMO_SATZ = (
    "Hallo, ich hätte gerne ein Röntgenbild und spreche mit einem Mitarbeiter."
)

_WORT_RE = re.compile(r"[A-Za-zÄÖÜäöüß]+|[^A-Za-zÄÖÜäöüß]+")
_DIGIT = re.compile(r"\d")
_DIKTAT = frozenset({
    "telefon", "telefon_check", "buchstabieren", "name", "vorname", "nachname",
})

_HART = (("g", "k"), ("k", "g"), ("d", "t"), ("t", "d"), ("b", "p"), ("p", "b"))
_ANLAUT = {
    "m": "w", "w": "m", "b": "p", "p": "b", "g": "k", "k": "g",
    "d": "t", "t": "d", "r": "l", "l": "r", "f": "v", "v": "f",
}
_AUSLAUT = {
    "r": "l", "l": "r", "t": "d", "d": "t", "n": "m", "m": "n",
    "k": "g", "g": "k", "b": "p", "p": "b", "s": "sch",
}


def _norm(d: dict | None) -> dict[str, Any]:
    src = d if isinstance(d, dict) else {}
    try:
        staerke = int(src.get("staerke") or 0)
    except (TypeError, ValueError):
        staerke = 0
    staerke = max(0, min(100, staerke))
    erlaubt = {k for k, _ in KATEGORIEN}
    kats = [str(x) for x in (src.get("kategorien") or []) if str(x) in erlaubt]
    if staerke and not kats:
        kats = [k for k, _ in KATEGORIEN]
    return {"staerke": staerke, "kategorien": kats}


def aktiv(d: dict | None) -> bool:
    n = _norm(d)
    return bool(n["staerke"] and n["kategorien"])


def _klein(ch: str) -> str:
    return ch.lower()


def _gross_wie(muster: str, wort: str) -> str:
    if not muster or not wort:
        return wort
    if muster.isupper():
        return wort.upper()
    if muster[0].isupper():
        return wort[0].upper() + wort[1:]
    return wort


def _hart(wort: str, rnd: random.Random) -> str:
    klein = wort.lower()
    paare = [p for p in _HART if p[0] in klein and "ck" not in klein]
    if not paare:
        return wort
    a, b = rnd.choice(paare)
    out = []
    getauscht = False
    for ch in wort:
        if not getauscht and _klein(ch) == a:
            out.append(b.upper() if ch.isupper() else b)
            getauscht = True
        else:
            out.append(ch)
    return "".join(out) if getauscht else wort


def _anlaut(wort: str, rnd: random.Random) -> str:
    if len(wort) < 3:
        return wort
    k = _klein(wort[0])
    neu = _ANLAUT.get(k)
    if not neu:
        neu = rnd.choice(list(_ANLAUT.values()))
    return _gross_wie(wort, neu + wort[1:])


def _auslaut(wort: str, rnd: random.Random) -> str:
    if len(wort) < 5:
        return wort
    if rnd.random() < 0.45:
        return wort[:-1]
    k = _klein(wort[-1])
    neu = _AUSLAUT.get(k)
    if not neu:
        return wort[:-1]
    return wort[:-1] + (neu.upper() if wort[-1].isupper() else neu)


def _chsch(wort: str, rnd: random.Random) -> str:
    k = wort.lower()
    if k == "ich":
        return _gross_wie(wort, "isch")
    if "sch" in k:
        i = k.find("sch")
        return wort[:i] + ("Ch" if wort[i].isupper() else "ch") + wort[i + 3:]
    if "ch" in k:
        i = k.find("ch")
        return wort[:i] + ("Sch" if wort[i].isupper() else "sch") + wort[i + 2:]
    return wort


def _einfuegen(wort: str, rnd: random.Random) -> str:
    """Konsonant dazwischen — Röntgenbild -> Röntkenbild, Grönkenpid-artig."""
    if len(wort) < 5:
        return wort
    extra = rnd.choice(("k", "n", "p", "t", "g"))
    # nach dem ersten Vokalblock
    vokale = set("aeiouäöüAEIOUÄÖÜ")
    i = 0
    while i < len(wort) and wort[i] not in vokale:
        i += 1
    while i < len(wort) and wort[i] in vokale:
        i += 1
    if i <= 0 or i >= len(wort):
        i = max(2, len(wort) // 2)
    return wort[:i] + extra + wort[i:]


def _vertauschen(wort: str, rnd: random.Random) -> str:
    if len(wort) < 6:
        return wort
    i = rnd.randrange(1, len(wort) - 2)
    chars = list(wort)
    chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def _vokal(wort: str, rnd: random.Random) -> str:
    k = wort.lower()
    paare = (("ei", "ai"), ("ai", "ei"), ("eu", "oi"), ("ä", "e"),
             ("ö", "e"), ("ü", "i"), ("ie", "i"))
    treffer = [p for p in paare if p[0] in k]
    if not treffer:
        return wort
    a, b = rnd.choice(treffer)
    i = k.find(a)
    return wort[:i] + b + wort[i + len(a):]


def _verschlucken(wort: str, rnd: random.Random) -> str:
    if len(wort) < 6:
        return wort
    i = rnd.randrange(2, len(wort) - 1)
    return wort[:i] + wort[i + 1:]


_FN = {
    "hart": _hart,
    "anlaut": _anlaut,
    "auslaut": _auslaut,
    "chsch": _chsch,
    "einfuegen": _einfuegen,
    "vertauschen": _vertauschen,
    "vokal": _vokal,
    "verschlucken": _verschlucken,
}


def _wort_anwenden(wort: str, kats: list[str], staerke: int,
                   rnd: random.Random) -> tuple[str, list[str]]:
    if _DIGIT.search(wort):
        return wort, []
    if len(wort) < 3:
        return wort, []
    kurz = wort.lower() == "ich"
    if len(wort) < 4 and not kurz:
        return wort, []
    # Anteil der Woerter, die getroffen werden
    if rnd.randrange(100) >= min(95, 20 + staerke):
        return wort, []
    n = 1 if staerke < 40 else (2 if staerke < 75 else 3)
    pool = list(kats)
    if kurz:
        pool = [k for k in pool if k == "chsch"] or pool
    rnd.shuffle(pool)
    hits: list[str] = []
    out = wort
    for kat in pool[:n]:
        fn = _FN.get(kat)
        if not fn:
            continue
        neu = fn(out, rnd)
        if neu and neu != out:
            out = neu
            hits.append(kat)
    return _gross_wie(wort, out) if out else wort, hits


def verfremden(text: str, einstellung: dict | None, *,
               seed: int = 0, baustein: str = "") -> dict[str, Any]:
    """Satz verfremden. Liefert Original, gesprochenen Text und Treffer."""
    klar = " ".join((text or "").split())
    n = _norm(einstellung)
    if not klar or not aktiv(n) or (baustein.split(":")[0] in _DIKTAT):
        return {"klar": klar, "text": klar, "hits": [], "kategorien": []}
    rnd = random.Random((seed or 0) + 17 * len(klar) + sum(ord(c) for c in klar[:12]))
    teile = _WORT_RE.findall(klar)
    hits: list[dict[str, str]] = []
    kats_genutzt: list[str] = []
    out: list[str] = []
    for teil in teile:
        if not teil or not teil[0].isalpha():
            out.append(teil)
            continue
        neu, welche = _wort_anwenden(teil, n["kategorien"], n["staerke"], rnd)
        out.append(neu)
        if welche:
            hits.append({"von": teil, "nach": neu, "kategorien": ",".join(welche)})
            for k in welche:
                if k not in kats_genutzt:
                    kats_genutzt.append(k)
    gesprochen = "".join(out)
    if gesprochen == klar:
        return {"klar": klar, "text": klar, "hits": [], "kategorien": []}
    return {
        "klar": klar,
        "text": gesprochen,
        "hits": hits,
        "kategorien": kats_genutzt,
    }
