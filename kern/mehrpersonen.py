"""Mehrpersonen-Termine in EINEM Buchungswunsch (Paket 4, 02.10.2026).

Live (Blessing, Replay ``blessing-zweipersonen``): „Ich bräuchte einen Termin
bei Ihnen, für zwei Personen, ich und meine Mutter, Anton Beispiel und Eva
Beispiel." Bianca buchte NUR die erste Person und verlor den zweiten Termin.

Dieses Modul ERKENNT nur — es entscheidet (bewusst konservativ), ob ein Satz
MEHRERE Personen in eine Buchung packt, und liefert die ZUSATZ-Personen
(alle außer der ersten), die als eigene, nacheinander fortgesetzte
Buchungsaufgaben geparkt werden (``bianca/agent`` + ``kern/hirn``). Die
erste Person läuft über den normalen Buchungsfluss weiter.

Fachfrei, mandanten-neutral, kein Netz, kein Modell. Gegenprobe-sicher:
ein einzelner Dritt-Termin („für meine Mutter") bleibt EINE Aufgabe
(W-FUER-WEN) — hier darf nichts anschlagen. Notaus: ``MEHRPERSONEN=0``.
"""
from __future__ import annotations

import os
import re
from typing import Any

# Rollen, die als eigene Person (Patient) zählen. Bewusst eng gehalten; die
# Grammatik/Beugung der Anrede macht bianca/gehirn._ROLLEN — hier zählt nur,
# DASS eine weitere Person gemeint ist.
_ROLLEN: dict[str, str] = {
    "mutter": "mutter", "mama": "mutter", "vater": "vater", "papa": "vater",
    "sohn": "sohn", "tochter": "tochter", "mann": "mann", "frau": "frau",
    "ehemann": "mann", "ehefrau": "frau", "partner": "partner",
    "partnerin": "partner", "bruder": "bruder", "schwester": "schwester",
    "oma": "oma", "großmutter": "oma", "grossmutter": "oma",
    "opa": "opa", "großvater": "opa", "grossvater": "opa",
    "kind": "kind", "tante": "tante", "onkel": "onkel",
    "nachbar": "nachbar", "nachbarin": "nachbar",
    "kollege": "kollege", "kollegin": "kollege",
    "freund": "freund", "freundin": "freund",
    "schwiegermutter": "schwiegermutter", "schwiegervater": "schwiegervater",
    "cousin": "cousin", "cousine": "cousine", "enkel": "enkel",
    "enkelin": "enkel", "enkelkind": "enkel",
}

# Zahlwort -> Anzahl (nur klein, 2..4 reicht für Telefonpraxis).
_ZAHL: dict[str, int] = {
    "zwei": 2, "2": 2, "drei": 3, "3": 3, "vier": 4, "4": 4, "beide": 2,
}

# „für zwei Personen", „zwei Termine", „für uns beide", „wir sind zu zweit".
_ANZAHL_RE = re.compile(
    r"\b(zwei|drei|vier|2|3|4|beide)\b[\w\s]{0,20}?"
    r"\b(person(?:en)?|leute|patient(?:en|innen)?|termine?|mal)\b"
    r"|\bf(?:ü|ue)r\s+uns\s+beide\b"
    r"|\bwir\s+sind\s+zu\s+zweit\b",
    re.I,
)

# Person-als-Patient-Marker (nicht das bloße Subjekt „ich brauche"): nur
# „ich und …", „… und ich", „für mich (und)", „mich und …", „einen für mich".
_SELBST_RE = re.compile(
    r"\bich\s+und\b|\bund\s+ich\b|\bf(?:ü|ue)r\s+mich\b|\bmich\s+und\b",
    re.I,
)

# Possessive Rolle: „meine Mutter", „für meinen Sohn", „unsere Tochter".
_ROLLE_RE = re.compile(
    r"\b(?:mein|unser)(?:e|en|em|er)?\s+(\w{3,})\b", re.I,
)

# Zwei aufeinanderfolgende großgeschriebene Wörter = ein voller Name.
# STT liefert Eigennamen i. d. R. großgeschrieben; Satzanfänge filtert der
# Aufrufer über den Kontext (aktive Buchung + Opener-Zug).
_NAME_RE = re.compile(r"\b([A-ZÄÖÜ][a-zäöüß]{1,})\s+([A-ZÄÖÜ][a-zäöüß]{1,})\b")

# Großgeschriebene Wörter, die KEINE Namen sind (Satzanfänge/Höflichkeit).
_KEIN_NAME = frozenset({
    "Ich", "Wir", "Sie", "Der", "Die", "Das", "Ein", "Eine", "Einen",
    "Herr", "Frau", "Doktor", "Guten", "Hallo", "Danke", "Termin", "Termine",
    "Person", "Personen", "Mutter", "Vater", "Sohn", "Tochter", "Meine",
    "Mein", "Unsere", "Unser", "Und", "Beide", "Praxis", "Zahnarzt",
})


def aktiv() -> bool:
    return (os.getenv("MEHRPERSONEN", "1") or "1").strip().lower() not in {
        "0", "false", "off", "no",
    }


def _rolle(wort: str) -> str:
    return _ROLLEN.get((wort or "").strip().lower(), "")


def _namen(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for vn, nn in _NAME_RE.findall(text or ""):
        if vn in _KEIN_NAME or nn in _KEIN_NAME:
            continue
        out.append((vn, nn))
    return out


def erkenne(text: str) -> list[dict[str, Any]]:
    """ZUSATZ-Personen (alle außer der ersten) oder [] wenn kein sicherer
    Mehrpersonen-Buchungswunsch.

    Jeder Eintrag: ``{"rolle": <key|"andere">, "vorname": str, "nachname": str}``
    — Name-Felder können leer sein (dann erfragt der Buchungsfluss sie).
    """
    if not aktiv():
        return []
    t = (text or "").strip()
    if not t:
        return []

    anzahl = 0
    m = _ANZAHL_RE.search(t)
    if m:
        g = (m.group(1) or "").lower()
        anzahl = _ZAHL.get(g, 2)

    selbst = bool(_SELBST_RE.search(t))
    rollen: list[str] = []
    for w in _ROLLE_RE.findall(t):
        r = _rolle(w)
        if r:
            rollen.append(r)

    namen = _namen(t)

    # Personen-Sequenz in Nennreihenfolge: self zuerst (wenn genannt),
    # danach die Rollen. Namen werden der Reihe nach zugeordnet.
    personen: list[dict[str, Any]] = []
    if selbst:
        personen.append({"rolle": "selbst"})
    for r in rollen:
        personen.append({"rolle": r})

    # Zahl der tatsächlich gemeinten Personen.
    gemeint = max(anzahl, len(personen), len(namen))
    if gemeint < 2:
        return []
    # Ohne jedes Mehrpersonen-Signal (nur „beide" o. Ä. ohne Kontext)
    # NICHT anschlagen: es braucht entweder einen Zähler ODER >= 2 klare
    # Personenreferenzen (self/Rolle/Name).
    if anzahl < 2 and (len(personen) + (1 if len(namen) >= 2 else 0)) < 2:
        return []

    # Personenliste auf die gemeinte Anzahl auffüllen (unbekannte Rolle).
    while len(personen) < gemeint:
        personen.append({"rolle": "andere"})

    # Namen der Reihe nach zuordnen.
    for i, nm in enumerate(namen):
        if i < len(personen):
            personen[i]["vorname"], personen[i]["nachname"] = nm

    # Die erste Person läuft im normalen Fluss; der Rest wird geparkt.
    zusatz = personen[1:gemeint]
    # Nur echte Zusatzpersonen zurückgeben.
    out: list[dict[str, Any]] = []
    for p in zusatz:
        rolle = p.get("rolle") or "andere"
        if rolle == "selbst":
            rolle = "andere"
        out.append({
            "rolle": rolle,
            "vorname": p.get("vorname", ""),
            "nachname": p.get("nachname", ""),
        })
    return out
