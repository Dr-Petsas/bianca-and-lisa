"""Drittperson im isolierten Dialogkern (W-FUER-WEN, kompakt).

Kein Import aus ``bianca/gehirn.py`` — der Kern bleibt autark. Nur die
Rollen, die am Telefon wirklich vorkommen; unbekannte Woerter nach
„für meine Krone“ sind kein Dritter.
"""

from __future__ import annotations

import re

# rolle -> (wer / Nominativ, wem / Dativ)
_ROLLEN: dict[str, tuple[str, str]] = {
    "sohn": ("Ihr Sohn", "Ihrem Sohn"),
    "tochter": ("Ihre Tochter", "Ihrer Tochter"),
    "kind": ("Ihr Kind", "Ihrem Kind"),
    "mann": ("Ihr Mann", "Ihrem Mann"),
    "frau": ("Ihre Frau", "Ihrer Frau"),
    "mutter": ("Ihre Mutter", "Ihrer Mutter"),
    "mama": ("Ihre Mama", "Ihrer Mama"),
    "vater": ("Ihr Vater", "Ihrem Vater"),
    "papa": ("Ihr Papa", "Ihrem Papa"),
    "oma": ("Ihre Oma", "Ihrer Oma"),
    "opa": ("Ihr Opa", "Ihrem Opa"),
    "enkel": ("Ihr Enkel", "Ihrem Enkel"),
    "enkelin": ("Ihre Enkelin", "Ihrer Enkelin"),
    "schwester": ("Ihre Schwester", "Ihrer Schwester"),
    "bruder": ("Ihr Bruder", "Ihrem Bruder"),
    "nachbar": ("Ihr Nachbar", "Ihrem Nachbarn"),
    "nachbarin": ("Ihre Nachbarin", "Ihrer Nachbarin"),
    "freund": ("Ihr Freund", "Ihrem Freund"),
    "freundin": ("Ihre Freundin", "Ihrer Freundin"),
    "partner": ("Ihr Partner", "Ihrem Partner"),
    "partnerin": ("Ihre Partnerin", "Ihrer Partnerin"),
}

_ALIAS = {
    "sohnes": "sohn", "soehne": "sohn", "jungen": "sohn", "junge": "sohn",
    "toechter": "tochter", "töchter": "tochter",
    "kinder": "kind", "kindes": "kind",
    "ehemann": "mann", "ehemanns": "mann", "ehefrau": "frau",
    "ehemannes": "mann",
    "mutti": "mutter", "vati": "vater",
    "nachbarn": "nachbar",
    "maedchen": "tochter", "mädchen": "tochter",
}

_STOP = {
    "mich", "uns", "sie", "selbst", "termin", "termine", "kontrolle",
    "schmerzen", "zahn", "zaehne", "zähne", "woche", "monat", "tag",
    "doktor", "arzt", "behandler", "grund", "prothese", "krone",
    "fuellung", "füllung", "implantat",
}

_ALTER = re.compile(
    r"^\d+$|jaehrig|jährig|jaehrigen|jährigen|jahrigen|jahre",
    re.I,
)
_NICHT_MICH = re.compile(
    r"nicht\s+f(?:ü|ue)r\s+mich|f(?:ü|ue)r\s+jemand(?:en)?\s+ander",
    re.I,
)
_FUER_MICH = re.compile(r"f(?:ü|ue)r\s+mich\b", re.I)
_FUER_MEIN = re.compile(
    r"f(?:ü|ue)r\s+(?:mein|unser|ein)(?:e|en|em)?\s+(.+)",
    re.I,
)
_MEIN_ROLLE = re.compile(
    r"\b(?:mein|unser)(?:e|en|em|er)?\s+(\w{3,})",
    re.I,
)
_SEIN_ROLLE = re.compile(
    r"\b(?:sein|ihr)(?:e|en|em|er)?\s+(\w{3,})",
    re.I,
)


def _norm_rolle(wort: str) -> str:
    w = (
        str(wort or "").lower()
        .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    )
    if not w or w in _STOP:
        return ""
    if w in _ROLLEN:
        return w
    return _ALIAS.get(w, "")


def deute_alle(text: str) -> list[str]:
    """Alle genannten Rollen in Reihenfolge — nie nur die letzte."""
    t = " ".join(str(text or "").lower().split())
    if not t:
        return []
    found: list[str] = []

    def add(rolle: str) -> None:
        if rolle and rolle not in found:
            found.append(rolle)

    if _FUER_MICH.search(t) and not _NICHT_MICH.search(t) and not _MEIN_ROLLE.search(t):
        return ["selbst"]
    for m in _MEIN_ROLLE.finditer(t):
        add(_norm_rolle(m.group(1)))
    for m in _SEIN_ROLLE.finditer(t):
        add(_norm_rolle(m.group(1)))
    m = _FUER_MEIN.search(t)
    if m:
        for w in re.findall(r"[a-zäöüß0-9]+", m.group(1)):
            if _ALTER.search(w):
                continue
            add(_norm_rolle(w))
    if re.search(r"\behemann", t):
        add("mann")
    if re.search(r"\behefrau", t):
        add("frau")
    if not found and _NICHT_MICH.search(t):
        return ["andere"]
    return found


def kanon(wert: str) -> str:
    """Einzelwort oder Phrase -> Rollen-Schluessel."""
    w = str(wert or "").strip()
    if not w:
        return ""
    n = _norm_rolle(w)
    if n:
        return n
    return deute(w)


def deute(text: str) -> str:
    """Rolle des Dritten — '' wenn der Termin fuer den Anrufer selbst ist."""
    alle = deute_alle(text)
    return alle[0] if alle else ""


def phrase(rolle: str, fall: str = "wer") -> str:
    """'Ihr Sohn' (wer), 'Ihren Sohn' (wen), 'Ihrem Sohn' (wem)."""
    r = str(rolle or "").lower()
    if r in ("", "selbst"):
        return ""
    if r == "andere":
        if fall == "wem":
            return "ihm oder ihr"
        if fall == "wen":
            return "ihn oder sie"
        return "er oder sie"
    paar = _ROLLEN.get(r)
    if not paar:
        return ""
    if fall == "wem":
        return paar[1]
    nom = paar[0]
    if fall == "wen" and nom.startswith("Ihr ") and not nom.startswith("Ihre "):
        return "Ihren " + nom[4:]
    return nom


__all__ = ["deute", "deute_alle", "kanon", "phrase"]
