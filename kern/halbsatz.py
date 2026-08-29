"""Halbsatz-Wache (W-HALBSATZ 29.08.2026): unfertige Saetze nicht beantworten.

Live 29.08. (Protokoll 09:34): "Hallo, ich habe naechste Woche Dienstag ein" —
das Dock schnitt in der Denkpause (Stille-Schwelle 350-650 ms), Bianca
antwortete auf den halben Satz, der Anrufer musste dreimal ansetzen. Das
Zugende ist ein reines STILLE-Kriterium und hoert nicht, ob der Satz
inhaltlich fertig ist.

Deshalb prueft der Dienst NACH der Transkription und VOR Fluss/LLM: klingt
das Gehoerte unfertig (Komma-Ende, haengende Konjunktion / Artikel /
Praeposition / Hilfsverb), wird NICHT geantwortet. Das Dock bekommt das
Event "warte" (kein Ton, kein Fueller, Watchdog aus) und hoert mit
laengerer Ruhe-Schwelle weiter; der naechste Zug wird serverseitig mit dem
gemerkten Fragment ZUSAMMENGEFUEGT. Kommt nichts mehr (leeres Transkript
oder Stille-Stups), wird das Fragment allein beantwortet — nie verschluckt.

Grenzen (bewusst):
- Ziffern-Zuege (Nummern-Diktat, Readback-Antworten) werden NIE gehalten —
  der Telefon-Pfad hat seine eigene Teil-Logik (telefonTeil).
- Hoechstens 2 Verlaengerungen pro Satz, dann wird beantwortet, was da ist.

Kein Netz, kein LLM — reine Textarbeit, JSON-taugliche Felder in der Sitzung.
Notaus: SATZ_HOLD=0 (Umgebungsvariable) => Verhalten wie vor W-HALBSATZ.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Ruhe-Schwelle (ms) fuer das Weiterhoeren nach einem gehaltenen Fragment:
# grosszuegig, der Anrufer denkt gerade nach — aber unter der 4-s-Grenze
# des Stille-Waechters, der das Fragment notfalls beantwortet.
WARTE_MS = 900
MAX_HALTEN = 2

_SATZ_ENDE = (".", "!", "?", "…")
_HALT_ZEICHEN = (",", ";", ":", "-", "–", "—")

# Ziffern oder zwei und mehr Ziffern-Woerter am Stueck: Nummern-Diktat —
# dort NIE halten (eigene Teil-Nummern-Logik, Schwelle schon bei 650 ms).
_ZIFFRIG_RE = re.compile(
    r"\d|(?:\b(?:null|eins|zwei|drei|vier|f[üu]nf|sechs|sieben|acht|neun|zwo)\b[\s,]*){2,}",
    re.I,
)

# Woerter, nach denen ein deutscher Satz praktisch nie endet: haengt das
# Gehoerte an so einem Wort OHNE Satzzeichen, war die Pause eine Denkpause.
_FORTSETZUNG = {
    # Konjunktionen / Einleitungen
    "und", "oder", "aber", "weil", "denn", "dass", "ob", "wenn", "als",
    "sondern", "sowie", "beziehungsweise", "bzw", "damit", "obwohl",
    "während", "waehrend", "also",
    # Frageworte mitten im Satz ("ich weiss nicht mehr, wann ...")
    "wie", "wo", "wann", "wer", "was", "warum", "wieso", "weshalb",
    "welche", "welcher", "welchen", "welchem", "welches",
    # Artikel / Possessiv
    "ein", "eine", "einen", "einem", "einer", "eines",
    "der", "die", "das", "den", "dem", "des",
    "mein", "meine", "meinen", "meinem", "meiner",
    "unser", "unsere", "unserem", "ihr", "ihre", "ihren", "ihrem",
    "kein", "keine", "keinen", "keinem",
    # Praepositionen
    "mit", "am", "um", "im", "an", "auf", "für", "fuer", "zu", "zur", "zum",
    "bei", "nach", "von", "vor", "seit", "gegen", "ohne", "bis",
    "über", "ueber", "unter", "zwischen", "durch", "ab",
    # Pronomen / Hilfs- und Modalverben mitten im Satz
    "ich", "wir", "er", "es", "man", "sich",
    "hab", "habe", "hätte", "haette", "bin", "ist", "war", "wäre", "waere",
    "wird", "werde", "würde", "wuerde", "möchte", "moechte", "muss", "soll",
    "kann", "könnte", "koennte", "will", "wollte", "brauche", "bräuchte",
    "brauchte",
    # klar weiterfuehrende Adverbien
    "nicht", "mehr", "noch", "sehr", "ganz", "eher", "lieber", "ziemlich",
    "nämlich", "naemlich", "sozusagen", "quasi", "dann",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def enabled() -> bool:
    return os.environ.get("SATZ_HOLD", "1").strip() != "0"


def unfertig(text: str) -> bool:
    """Klingt das Gehoerte nach einem abgeschnittenen Satz?

    Konservativ: bei Satzzeichen am Ende (. ! ? …) gilt der Satz als fertig —
    die STT-Interpunktion sitzt bei klarer Sprechmelodie zuverlaessig. Nur
    Komma-/Gedankenstrich-Enden und haengende Funktionswoerter halten."""
    t = _s(text)
    if not t:
        return False
    if t.endswith(_HALT_ZEICHEN):
        return True
    if t.endswith(_SATZ_ENDE):
        return False
    letztes = re.sub(r"[^a-zäöüß]", "", t.split()[-1].casefold())
    return letztes in _FORTSETZUNG


def mergen(sit: dict, neu: str) -> str:
    """Gemerktes Fragment vor den neuen Zug setzen (und ausbuchen)."""
    alt = _s(sit.pop("halbsatz", ""))
    neu = _s(neu)
    if not alt:
        return neu
    if not neu:
        return alt
    return alt + " " + neu


def halten(sit: dict, text: str) -> bool:
    """Soll dieser Zug NICHT beantwortet, sondern weitergehoert werden?

    True => Fragment ist in der Sitzung gemerkt, der Aufrufer schickt das
    "warte"-Event. False => normal beantworten (Zaehler ist zurueckgesetzt)."""
    t = _s(text)
    if not enabled() or not t or _ZIFFRIG_RE.search(t):
        sit["halbsatzZahl"] = 0
        return False
    zahl = int(sit.get("halbsatzZahl") or 0)
    if zahl >= MAX_HALTEN or not unfertig(t):
        sit["halbsatzZahl"] = 0
        return False
    sit["halbsatz"] = t
    sit["halbsatzZahl"] = zahl + 1
    return True


def abholen(sit: dict) -> str:
    """Gemerktes Fragment entnehmen (Flush): Stille-Stups oder leeres
    Transkript beantworten das Fragment so, wie es ist."""
    sit["halbsatzZahl"] = 0
    return _s(sit.pop("halbsatz", ""))
