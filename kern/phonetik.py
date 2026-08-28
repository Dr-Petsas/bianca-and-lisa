"""Kölner Phonetik für Nachnamen am Telefon (28.08.2026).

Meier / Mayer / Maier / Meyer landen auf demselben Code. Bianca buchstabiert
trotzdem nach, wenn der Treffer nicht eindeutig ist — vorher wird nicht mehr
blind geraten.
"""

from __future__ import annotations

import re
from typing import Any

# Häufige deutsche Namens-Homophone, falls die Cloud-Suche den gehörten
# Buchstabenstand nicht findet. Jede Gruppe wird nur als Nachzieh-Suche
# benutzt, nie als Bindung ohne Phonetik-Filter.
_HOMOPHONE: tuple[frozenset[str], ...] = (
    frozenset({"meier", "meyer", "mayer", "maier", "mayr"}),
    frozenset({"schmidt", "schmitt", "schmid"}),
    frozenset({"hoffmann", "hofmann"}),
    frozenset({"schulz", "schulze", "schultz"}),
    frozenset({"schaefer", "schäfer", "schafer"}),
    frozenset({"schroeder", "schröder", "schroder"}),
    frozenset({"krueger", "krüger", "kruger"}),
    frozenset({"koehler", "köhler", "kohler"}),
    frozenset({"koenig", "könig", "konig"}),
    frozenset({"wolf", "wolff"}),
    frozenset({"mueller", "müller", "muller"}),
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _buchstaben(name: str) -> str:
    t = _s(name).upper()
    t = t.replace("Ä", "A").replace("Ö", "O").replace("Ü", "U").replace("ß", "SS")
    return re.sub(r"[^A-Z]", "", t)


def koelner(name: str) -> str:
    """Kölner Phonetik (DIN-nah): Meier/Mayer/Maier/Meyer → 67."""
    w = _buchstaben(name)
    if not w:
        return ""
    codes: list[str] = []
    n = len(w)
    for i, c in enumerate(w):
        nxt = w[i + 1] if i + 1 < n else ""
        prev = w[i - 1] if i else ""
        if c in "AEIOUJY":
            code = "0"
        elif c == "H":
            code = ""
        elif c == "B":
            code = "1"
        elif c == "P":
            code = "3" if nxt == "H" else "1"
        elif c == "D" or c == "T":
            code = "8" if nxt in "CSZ" else "2"
        elif c in "FVW":
            code = "3"
        elif c in "GKQ":
            code = "4"
        elif c == "C":
            if i == 0:
                code = "4" if nxt in "AHKLOQRUX" else "8"
            elif prev in "SZ":
                code = "8"
            else:
                code = "4" if nxt in "AHKOQUX" else "8"
        elif c == "X":
            code = "8" if prev in "CKQ" else "48"
        elif c == "L":
            code = "5"
        elif c in "MN":
            code = "6"
        elif c == "R":
            code = "7"
        elif c in "SZ":
            code = "8"
        else:
            code = ""
        for ch in code:
            if not codes or codes[-1] != ch:
                codes.append(ch)
    # Vokale (0) fallen, außer ganz am Anfang.
    if not codes:
        return ""
    kopf, rest = codes[0], codes[1:]
    return kopf + "".join(ch for ch in rest if ch != "0")


def gleiche_phonetik(a: str, b: str) -> bool:
    ca, cb = koelner(a), koelner(b)
    return bool(ca and cb and ca == cb)


def such_varianten(nachname: str) -> list[str]:
    """Gehörter Nachname plus Homophon-Gruppe — begrenzt, keine Erfindung."""
    raw = _s(nachname)
    if len(raw) < 3:
        return []
    out = [raw]
    low = raw.casefold()
    for gruppe in _HOMOPHONE:
        if low in gruppe:
            for alt in sorted(gruppe):
                if alt != low and alt.capitalize() not in out:
                    out.append(alt.capitalize() if alt.islower() else alt)
            break
    return out[:5]


def phonetik_treffer(kandidaten: list[dict], *, vorname: str = "", nachname: str) -> dict[str, Any]:
    """Genau EIN phonetisch passender Treffer — sonst {}."""
    last = _s(nachname)
    code = koelner(last)
    if not code or len(last) < 3:
        return {}
    first = _s(vorname)
    fcode = koelner(first) if first else ""
    treffer = []
    for p in kandidaten or []:
        if not isinstance(p, dict):
            continue
        k_last = _s(p.get("lastName"))
        if not k_last or koelner(k_last) != code:
            continue
        k_first = _s(p.get("firstName"))
        if fcode and k_first and koelner(k_first) != fcode:
            continue
        treffer.append(p)
    if len(treffer) != 1:
        return {}
    return treffer[0]
