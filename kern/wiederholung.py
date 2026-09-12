"""Wiederholungs-Wächter: dieselbe Frage nie zweimal wortgleich hintereinander.

Chef 27.08.2026: "ich will nie wieder doppelte telefonnummer oder behandler
abfragen hören." Live kam dieselbe Pflichtfrage wortgleich aus drei Rohren:
aus der Maschine (Quittung + kanonische Frage), aus dem Frage-Anker und aus
dem Modell selbst — teils dreimal in Folge.

Dieser Wächter sitzt am ENDE jedes gesprochenen Zuges (Maschine UND LLM,
Bianca UND Lisa) und vergleicht Satz für Satz mit den letzten gesprochenen
Antworten:

- Wiederholt sich die OFFENE Pflichtfrage wortgleich, wird sie durch die
  nächste Formulierungs-VARIANTE ersetzt (bianca/gehirn.FRAGE_VARIANTEN —
  jede Variante trägt die Kern-Wörter, damit Anker und Wachen sie weiter
  erkennen). Die Frage bleibt hörbar, aber nie zweimal im selben Wortlaut.
- Jeder andere wortgleich wiederholte Frage- oder Langsatz wird gestrichen
  (einmal gesagt reicht).

Ausnahmen (werden NIE angefasst):
- Züge der Nummern-Rückbestätigung (frage_id == "telefon_check"): die
  Sicherheitsschleife bleibt deterministisch — nach einer Korrektur DARF
  "Stimmt das so?" erneut kommen.
- Sätze mit Ziffern oder Ziffern-Wort-Gruppen (Nummern-/Zeiten-Readback).
- Kurze Sätze ohne Fragezeichen ("Alles klar."): natürliche Quittungen
  dürfen sich wiederholen.

Kein Netz, kein LLM — reine Textarbeit, JSON-taugliche Zähler in der Sitzung.
"""

from __future__ import annotations

import re
from typing import Any

from kern import spur

_SATZ_ENDE_RE = re.compile(r"(?<=[.!?…])\s+")
# Ziffern ODER drei und mehr Ziffern-Wörter am Stück ("null eins sieben ...").
_ZIFFER_RE = re.compile(
    r"\d|(?:\b(?:null|eins|zwei|drei|vier|f[üu]nf|sechs|sieben|acht|neun|zwo)\b[\s,]*){3,}",
    re.I,
)
LANGSATZ_AB = 60      # Aussagesätze ab dieser Länge gelten als Wiederholungs-Kandidat
FENSTER = 3           # gegen wie viele letzte Bot-Antworten verglichen wird
# W-REPEAT-FENSTER 12.09.2026: so viele gesprochene Sätze bleiben im
# Vergleichs-Gedächtnis. Vorher wuchs `waechterGesagt` über den GANZEN Anruf;
# in einem langen Gespräch (Live 11.09.2026, 109 Züge) war damit irgendwann
# fast jede natürliche Pflichtfrage "schon gesagt" und wurde gestrichen —
# der Wächter gegen Schleifen wurde selbst zur Schleifen-Ursache. Der Zweck
# ("nie zweimal wortgleich HINTEREINANDER") braucht nur ein Fenster.
GEDAECHTNIS_SAETZE = 24


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _norm(satz: str) -> str:
    """Vergleichsform: Kleinbuchstaben, ohne Satzzeichen und Mehrfach-Leerraum."""
    return " ".join(re.sub(r"[^a-zäöüß0-9 ]", " ", _s(satz).casefold()).split())


def _saetze(text: str) -> list[str]:
    return [x for x in _SATZ_ENDE_RE.split(_s(text)) if x]


def gesagt_merken(sit: dict, text: str) -> None:
    """Gesprochene Sätze merken — auch Vorab, der nie in messages landet.

    Live 08.09.2026: „Ah, Herr Petsas…“ ging als Vorab raus, der Wächter
    sah nur die LLM-Antwort und ließ den Hallo jeden Zug erneut durch."""
    bag = sit.setdefault("waechterGesagt", [])
    if not isinstance(bag, list):
        bag = []
        sit["waechterGesagt"] = bag
    for satz in _saetze(text):
        n = _norm(satz)
        if not n:
            continue
        if n in bag:
            # Erneut gesagt: nach hinten holen, damit das Fenster die
            # Aktualität abbildet (nicht das erste Vorkommen von vor 20 Zügen).
            bag.remove(n)
        bag.append(n)
    if len(bag) > GEDAECHTNIS_SAETZE:
        del bag[:-GEDAECHTNIS_SAETZE]


def letzte_antworten(msgs: list[dict], n: int = FENSTER, *, ohne_letzte: bool = False) -> list[str]:
    """Die letzten n Assistenten-Antworten — ohne_letzte=True überspringt die
    jüngste (das ist auf dem LLM-Pfad der gerade geprüfte Text selbst)."""
    out: list[str] = []
    letzte_uebersprungen = not ohne_letzte
    for m in reversed(msgs or []):
        if m.get("role") != "assistant":
            continue
        if not letzte_uebersprungen:
            letzte_uebersprungen = True
            continue
        inhalt = _s(m.get("content"))
        if inhalt:
            out.append(inhalt)
        if len(out) >= n:
            break
    return out


def _variante(sit: dict, fid: str, varianten: dict, verbraucht: set[str]) -> str:
    """Nächste noch nicht gehörte Formulierung der offenen Frage — '' wenn
    alle Formen verbrannt sind (dann greift die Eskalation des Flusses)."""
    formen = list((varianten or {}).get(fid) or ())
    if not formen:
        return ""
    zaehler = sit.setdefault("frageForm", {})
    start = int(zaehler.get(fid) or 0)
    for i in range(len(formen)):
        idx = (start + i) % len(formen)
        if _norm(formen[idx]) not in verbraucht:
            zaehler[fid] = idx + 1
            return formen[idx]
    return ""


def pruefen(sit: dict, text: str, *, frueher: list[str], frage_id: str = "",
            frage_kern: str = "", varianten: dict | None = None,
            auch_kurz: bool = False) -> str:
    """Einen sprechfertigen Zug gegen die letzten Antworten entdoppeln.

    Liefert den (ggf. umformulierten/gekürzten) Text — oder '', wenn alles
    Wiederholung war und keine Variante mehr frei ist. Der Aufrufer
    entscheidet dann über einen Rückfall (nie stumm bleiben).
    """
    t = _s(text)
    if not t:
        return t
    if frage_id == "telefon_check":
        return t
    if not frueher and not (sit.get("waechterGesagt") or []):
        return t
    gehoert: set[str] = set()
    for n in (sit.get("waechterGesagt") or []):
        if n:
            gehoert.add(str(n))
    for antwort in frueher:
        for satz in _saetze(antwort):
            n = _norm(satz)
            if n:
                gehoert.add(n)
    if not gehoert:
        return t

    behalten: list[str] = []
    getauscht = False
    for satz in _saetze(t):
        n = _norm(satz)
        frage_satz = satz.rstrip().endswith("?")
        kandidat = frage_satz or len(satz) >= LANGSATZ_AB or auch_kurz
        if not n or not kandidat or _ZIFFER_RE.search(satz) or n not in gehoert:
            behalten.append(satz)
            continue
        # Wortgleiche Wiederholung erkannt.
        if (frage_satz and not getauscht and frage_id and frage_kern
                and re.search(frage_kern, satz, re.I)):
            ersatz = _variante(sit, frage_id, varianten or {}, gehoert)
            if ersatz:
                behalten.append(ersatz)
                getauscht = True
                spur.merken(sit, "wiederholung-variante", frage_id)
                continue
        # gestrichen — einmal gesagt reicht.
        spur.merken(sit, "wiederholung-gestrichen", satz)
    return " ".join(behalten).strip()
