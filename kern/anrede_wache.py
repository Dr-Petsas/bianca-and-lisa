"""Keine erfundene Anrede (W-ANREDE 13.09.2026 — nicht rückbauen).

Live-Probe 12.09.2026 (tools/_probe_langgespraech.py, unbekannter Anrufer
ohne Rufnummer): Bianca antwortete im ERSTEN Zug „Einen Moment. Gerne, Herr
Meier. Ich buche Ihnen einen Termin zur Kontrolle." — den Namen „Meier" hat
niemand gesagt, das Modell hat ihn erfunden. Bei erkannter Rufnummer fällt
das nicht auf (dann steht der echte Name in der Akte), bei einem fremden
Anrufer ist es grob: er hört den Namen eines anderen Menschen.

Deshalb dieselbe Regel wie bei allen Fakten (W-FAKTEN-WACHE): eine Anrede
mit Namen darf nur raus, wenn der Name BELEGT ist. Belegt heißt:

- der Anrufer hat ihn selbst genannt bzw. er kommt aus der Kartei
  (Sammler: nachname/vorname, Kontaktname bei Dritt-Terminen, erkannter
  Anrufer aus der Cloud-Function),
- oder es ist ein Behandler/Praxisname des Mandanten („Herrn Doktor Petsas
  verbinde ich gern") — die kommen aus dem Tenant, nicht aus dem Modell.

Alles andere wird samt vorausgehendem Komma gestrichen; der Satz bleibt
stehen („Gerne. Ich buche Ihnen einen Termin"). Nur Titel ohne Namen
(„Herr Doktor") sind immer in Ordnung, und ein blosses „Frau"/„Herr" ohne
Name bleibt unberührt.

Stufen wie bei der Fakten-Wache, Umgebungsvariable `ANREDE_WACHE`:
`off` (nichts), `shadow` (nur Wächterspur), `enforce` (streichen).
Default: `enforce` — ein erfundener Name ist nie besser als kein Name.

Tests: `tests/test_anrede_wache.py`
"""

from __future__ import annotations

import os
import re
from typing import Any

# Titel zählen nie als Name — "Herr Doktor" ist eine Anrede ohne Person.
_TITEL = {"doktor", "dr", "professor", "prof", "med", "dent", "kollege",
          "kollegin", "chef", "chefin"}

# Höflichkeits-/Funktionswörter, die hinter "Herr/Frau" stehen können, ohne
# ein Name zu sein.
_KEIN_NAME = {"und", "oder", "aber", "ich", "sie", "wir", "der", "die", "das",
              "den", "dem", "ist", "war", "wenn", "dann", "noch", "bitte",
              "danke", "gerne", "gern", "also", "so", "ja", "nein"}

# „Gerne, Herr Meier." / „Guten Tag Frau Meier," — Anrede samt trennendem
# Komma und Titelkette. Der Name ist die letzte Gross-Gruppe.
_ANREDE_RE = re.compile(
    r"(?P<trenn>\s*[,;]\s*|\s+|^)"
    r"(?P<hoefl>Herrn?|Frau)"
    r"(?P<titel>(?:\s+(?:Dr\.?|Doktor|Prof\.?|Professor|med\.?|dent\.?))*)"
    r"\s+(?P<name>[A-ZÄÖÜ][\wÄÖÜäöüß]*(?:-[A-ZÄÖÜ][\wÄÖÜäöüß]*)?)"
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def modus() -> str:
    m = (os.environ.get("ANREDE_WACHE") or "enforce").strip().lower()
    return m if m in {"off", "shadow", "enforce"} else "enforce"


def _worte(v: Any) -> list[str]:
    return [w for w in re.split(r"[^\wÄÖÜäöüß-]+", _s(v)) if w]


def belegte_namen(sit: dict) -> set[str]:
    """Namen, die Bianca aussprechen DARF — aus Anrufer, Kartei und Mandant.

    Bewusst grosszügig auf der Belegt-Seite: ein legitimer Name darf nie
    gestrichen werden, nur ein frei erfundener."""
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    quellen: list[Any] = [
        s.get("nachname"), s.get("vorname"), s.get("name"),
        s.get("kontaktName"), s.get("akteName"),
        s.get("arztName"), s.get("kalenderName"),
    ]
    anrufer = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
    quellen += [anrufer.get("vorname"), anrufer.get("nachname")]
    patient = sit.get("patient") if isinstance(sit.get("patient"), dict) else {}
    quellen += [patient.get("firstName"), patient.get("lastName"),
                patient.get("fullName")]
    kartei = sit.get("anruferKartei") if isinstance(sit.get("anruferKartei"), dict) else {}
    quellen += [kartei.get("arzt"), kartei.get("behandler")]

    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    if tenant:
        # Behandler und Praxisname kommen aus dem Mandanten (Tenant/DB) —
        # niemals aus dem Modell, also immer belegt.
        try:
            from kern import tenants
            quellen += list(tenants.stt_keywords(tenant) or [])
        except Exception:      # Wache darf nie werfen
            pass
        for c in (tenant.get("calendars") or []):
            if isinstance(c, dict):
                quellen.append(c.get("name"))
        quellen += [tenant.get("praxisName"), tenant.get("behandler")]

    raus: set[str] = set()
    for q in quellen:
        if isinstance(q, (list, tuple, set)):
            for teil in q:
                raus.update(w.casefold() for w in _worte(teil))
            continue
        raus.update(w.casefold() for w in _worte(q))
    return {w for w in raus if len(w) > 1} | _TITEL


def erfundene_anreden(sit: dict, text: str) -> list[str]:
    """Namens-Anreden im Text, die durch nichts belegt sind."""
    t = _s(text)
    if not t:
        return []
    erlaubt = belegte_namen(sit)
    raus: list[str] = []
    for m in _ANREDE_RE.finditer(t):
        name = m.group("name")
        klein = name.casefold()
        if klein in erlaubt or klein in _KEIN_NAME:
            continue
        raus.append(f"{m.group('hoefl')}{m.group('titel')} {name}".strip())
    return raus


def saeubern(sit: dict, text: str) -> tuple[str, list[str]]:
    """Erfundene Anrede streichen. Gibt (Text, gestrichene Anreden) zurück."""
    t = _s(text)
    if not t:
        return t, []
    erlaubt = belegte_namen(sit)
    gestrichen: list[str] = []

    def ersatz(m: re.Match[str]) -> str:
        name = m.group("name")
        klein = name.casefold()
        if klein in erlaubt or klein in _KEIN_NAME:
            return m.group(0)
        gestrichen.append(f"{m.group('hoefl')}{m.group('titel')} {name}".strip())
        # Satzanfang: der Rest des Satzes traegt die Aussage weiter.
        if m.group("trenn").strip() in {",", ";"}:
            return ""
        return "" if m.start() == 0 else " "

    neu = _ANREDE_RE.sub(ersatz, t)
    if not gestrichen:
        return t, []
    # Reste glaetten: doppelte Leerzeichen, Komma vor Satzzeichen, leere Saetze.
    neu = re.sub(r"\s+([,.;!?])", r"\1", neu)
    neu = re.sub(r"([,;])\s*([.!?])", r"\2", neu)
    neu = re.sub(r"\s{2,}", " ", neu).strip(" ,;")
    neu = _s(neu)
    if neu and not t.startswith(neu[:1]):
        # Stand die Anrede am Satzanfang, beginnt der Satz jetzt klein.
        neu = neu[:1].upper() + neu[1:]
    return neu, gestrichen
