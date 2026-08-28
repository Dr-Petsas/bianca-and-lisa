"""Text-Schnitt fuer den Chatterbox-Stream: fruehes erstes Stueck, dann Saetze.

Chatterbox kann kein Token-Streaming — es rendert blockierend, gemessen
28.08.2026 auf der 5090: ~0,42 s je Audio-Sekunde plus ~0,25 s Grundkosten
je Aufruf. Der /speak-stream-Endpoint synthetisiert deshalb STUECKWEISE und
schickt jedes fertige PCM sofort raus. Der erste Schnitt ist bewusst frueh
(erste Sinneinheit bis zum Komma), damit der Anrufer nach ~0,8 s etwas
hoert; danach traegt jeder Satz ein eigenes Stueck, Winzlinge kleben am
Nachbarn (gleiche Regel wie kern/dienst.py — bewusste KOPIE: der Container
baut nur aus diesem Ordner, kein Import aus kern/).

Schnitt-Regeln:
- nie nach Ordnungszahl-Punkt ("am 28. August") oder in Ziffern-Gruppen,
- Erst-Stueck: ist der erste Satz laenger als ERSTE_MAX, wird am ersten
  Komma ab ERSTE_MIN geschnitten (Komma bleibt am Kopf — haelt die
  weiterfuehrende Intonation), notfalls an der Wortgrenze vor ERSTE_MAX,
- Folge-Stuecke satzweise ab SATZ_MIN Zeichen.
"""

from __future__ import annotations

import re

ERSTE_MIN = 8         # frueher lohnt kein eigener Aufruf (Grundkosten ~0,25 s)
ERSTE_CUT_AB = 24     # ab hier wird am Komma geschnitten ("Einen Moment," ~0,6 s)
ERSTE_MAX = 60        # Wortgrenzen-Notschnitt: ~3 s Audio im ersten Stueck
ERSTE_KOMMA_MAX = 90  # ein Komma-Schnitt klingt besser und darf spaeter liegen
SATZ_MIN = 25         # Winzlinge kleben am Nachbarn (wie kern/dienst.py)

_SATZ_RE = re.compile(r"(?<=[.!?…])(?<!\d[.!?…])\s+(?=[A-ZÄÖÜ„»(])")
_KOMMA_RE = re.compile(r",\s+")


def _s(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _saetze(text: str) -> list[str]:
    roh = [t.strip() for t in _SATZ_RE.split(_s(text)) if t.strip()]
    teile: list[str] = []
    for t in roh:
        if teile and (len(teile[-1]) < SATZ_MIN or len(t) < SATZ_MIN):
            teile[-1] = f"{teile[-1]} {t}"
        else:
            teile.append(t)
    return teile


def stuecke(text: str) -> list[str]:
    """Sprechfertige Stuecke in Sende-Reihenfolge — [] bei leerem Text."""
    saetze = _saetze(text)
    if not saetze:
        return []
    erster = saetze[0]
    if len(erster) > ERSTE_CUT_AB:
        # Komma-Schnitt so frueh wie sinnvoll: "Einen Moment," oder "Alles
        # klar," ist in ~0,6 s synthetisiert — der Anrufer hoert sofort was,
        # und die Naht liegt an einer natuerlichen Sprechpause.
        for m in _KOMMA_RE.finditer(erster):
            if ERSTE_MIN <= m.start() <= ERSTE_KOMMA_MAX:
                kopf = erster[: m.start() + 1].strip()  # Komma bleibt am Kopf
                rest = erster[m.end():].strip()
                return [t for t in (kopf, rest, *saetze[1:]) if t]
    if len(erster) > ERSTE_MAX:
        schnitt = erster.rfind(" ", ERSTE_MIN, ERSTE_MAX)
        if schnitt > 0:
            kopf, rest = erster[:schnitt].strip(), erster[schnitt:].strip()
            return [t for t in (kopf, rest, *saetze[1:]) if t]
    return saetze
