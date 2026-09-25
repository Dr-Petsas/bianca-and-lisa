"""Kölner Phonetik für verhörte Nachnamen.

Gleicht einen gehörten Namen mit der Kartei ab, wenn die exakte Schreibung
danebenliegt (Dermos/Thermos, Mueller/Müller). Ändert keine Frage.
"""

from __future__ import annotations

import re
import unicodedata


def _flach(text: str) -> str:
    s = str(text or "").replace("ß", "ss")
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    s = s.replace("Ä", "ae").replace("Ö", "oe").replace("Ü", "ue")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z]", "", s.lower())


def koeln(word: str) -> str:
    """Ein Namensteil als Kölner-Phonetik-Code. Leer bei keinem Buchstaben."""
    w = _flach(word)
    if not w:
        return ""
    n = len(w)

    def code_at(i: int) -> str:
        c = w[i]
        nxt = w[i + 1] if i + 1 < n else ""
        prev = w[i - 1] if i > 0 else ""
        if c in "aeijouy":
            return "0"
        if c == "h":
            return ""
        if c == "b":
            return "1"
        if c == "p":
            return "3" if nxt == "h" else "1"
        if c in "dt":
            return "8" if nxt in "csz" else "2"
        if c in "fvw":
            return "3"
        if c in "gkq":
            return "4"
        if c == "c":
            if i == 0:
                return "4" if nxt in "ahkloqrux" else "8"
            if prev in "sz":
                return "8"
            return "4" if nxt in "ahkoqux" else "8"
        if c == "x":
            return "8" if prev in "ckq" else "48"
        if c == "l":
            return "5"
        if c in "mn":
            return "6"
        if c == "r":
            return "7"
        if c in "sz":
            return "8"
        return ""

    raw = "".join(code_at(i) for i in range(n))
    collapsed = ""
    for ch in raw:
        if ch != collapsed[-1:]:
            collapsed += ch
    if not collapsed:
        return ""
    return collapsed[0] + collapsed[1:].replace("0", "")


def waehlen(patients: list, last: str, first: str = "") -> list[dict]:
    """Patienten, deren Nachname klanggleich zum gehörten Namen ist.

    Mit Vornamen werden Treffer bevorzugt, deren Vorname ebenfalls klingt.
    Mehr als acht Treffer gelten als unscharf und kommen nicht zurück.
    """
    ziel = koeln(last)
    if len(_flach(last)) < 3 or len(ziel) < 2:
        return []
    erste = koeln(first) if len(_flach(first)) >= 3 else ""
    stark: list[dict] = []
    for p in patients or []:
        if not isinstance(p, dict) or not str(p.get("id") or "").strip():
            continue
        if koeln(str(p.get("lastName") or "")) != ziel:
            continue
        stark.append(p)
    if erste:
        mit_vorn = [p for p in stark if koeln(str(p.get("firstName") or "")) == erste]
        if len(mit_vorn) == 1:
            return mit_vorn
    if len(stark) > 8:
        return []
    return stark
