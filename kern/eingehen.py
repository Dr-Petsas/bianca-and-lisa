"""W-EINGEHEN: Jeder Zug geht erkennbar auf das Gesagte ein (13.09.2026).

Chef woertlich: "genau dafuer brauchen wir, dass auf das gesagte eingegangen
wird — waere das nicht sinnvoll? weil dann wuerde es endlich ein Gespraech!!!
und kein Monolog. […] es gibt keinen Waechter, der pro Zug erzwingt, dass die
Antwort erkennbar auf den letzten Satz eingeht. Das muss deshalb angepasst
werden…. nur so entsteht KONVERSATION."

Die Maschine quittiert bereits jede ERNTE (`flow._quittung`: "Danke, Herr
Rateike.", "Prima, die Nummer habe ich."). Der Monolog entsteht in den Zuegen
DAZWISCHEN: der Anrufer sagt etwas, das kein Feld fuellt, und die Antwort
besteht aus einer nackten Frage — "Und der Vorname?". Genau das ist das
Muster, das live wie Nicht-Zuhoeren klingt.

Deshalb die Regel: **Eine Antwort, die NUR aus Fragen besteht, bekommt einen
kurzen Bezug voran.** Kein neuer Inhalt, keine erfundene Tatsache — nur das
hoerbare "ich habe dich gehoert", das ein Mensch automatisch gibt.

Bewusst NICHT angetastet:
- Antworten, die schon einen Aussagesatz tragen (Quittung, Readback,
  Slot-Angebot, Absage-Bestaetigung) — die gehen bereits ein.
- Antworten, die bereits mit einem Bezug beginnen ("Gerne, wann passt es?").
- Zuege ohne substanzielle Anrufer-Aeusserung ("Ja.", "Hm.") und die
  Presence-Stupse ("Sind Sie noch dran?").
- Eine FRAGE des Anrufers: ein "Verstehe." davor wuerde eine Antwort
  vortaeuschen, die nicht kommt. Der Fall wird nur protokolliert
  (Spur ``eingehen-frage-offen``) — dort gehoert die Talk-Schicht hin.
"""

from __future__ import annotations

import os
import re
from typing import Any

_SATZ_TRENN_RE = re.compile(r"(?<=[.!?…])\s+")

# Kurzformen ohne Inhalt: darauf muss niemand eingehen, die Quittung bzw. die
# Ja/Nein-Logik hat sie schon beantwortet.
_FUELLER = {
    "ja", "nein", "ok", "okay", "hm", "hmm", "mhm", "mh", "aha", "so",
    "genau", "richtig", "stimmt", "klar", "gut", "danke", "bitte", "doch",
    "gerne", "jawohl", "jo", "joa", "na", "nun", "äh", "ähm", "ah", "oh",
    "hallo", "moin", "tach", "servus", "perfekt", "super", "passt", "eben",
}

# Der Zug ist ein Presence-Stups oder eine Rueckversicherung — kein Ort fuer
# ein "Verstehe." davor.
_PRESENCE_RE = re.compile(
    r"\b(?:noch\s+dran|noch\s+da|h(?:ö|oe)ren\s+sie\s+mich)\b", re.I)

# Die Antwort beginnt schon mit einem Bezug. Liste absichtlich breit: ein
# doppelter Bezug ("Verstehe. Alles klar. …") klingt schlimmer als keiner.
_SCHON_BEZUG_RE = re.compile(
    r"^\s*(?:ja|nein|doch|danke|vielen\s+dank|gerne|sehr\s+gerne|gern|"
    r"alles\s+klar|klar|na\s+klar|verstehe|verstanden|okay|ok|gut|sehr\s+gut|"
    r"prima|perfekt|wunderbar|sch(?:ö|oe)n|sehr\s+sch(?:ö|oe)n|"
    r"entschuldigung|entschuldigen\s+sie|verzeihung|tut\s+mir\s+leid|"
    r"das\s+tut\s+mir\s+leid|kein\s+problem|keine\s+sorge|in\s+ordnung|"
    r"selbstverst(?:ä|ae)ndlich|nat(?:ü|ue)rlich|sicher|ah|aha|oh|hm|hmm|mhm|"
    r"moment|einen\s+moment|kurz|notiert|stimmt|genau|so|dann|"
    r"ich\s+(?:habe|hab|schaue|sehe|pr(?:ü|ue)fe|notiere|verstehe|h(?:ö|oe)re))"
    r"\b", re.I)

# Der Anrufer FRAGT — dann ist ein blosser Bezug die falsche Antwort.
_ANRUFER_FRAGT_RE = re.compile(
    r"[?]|^\s*(?:was|wie|wann|wo|wer|warum|wieso|weshalb|welche[rsn]?|"
    r"wieviel|wie\s+viel|kann\s+ich|k(?:ö|oe)nnen\s+sie|haben\s+sie|"
    r"gibt\s+es|ist\s+das|geht\s+das|darf\s+ich)\b", re.I)

# Ein Wunsch/Auftrag ("ich haette gern…") verdient "Gerne." statt "Verstehe."
# Parakeets Hoerfehler-Formen zaehlen mit: „ich habe gerne einen Termin“
# (live 14.09.2026, Anruf e7191c7e — gemeint war „hätte gerne“).
_WUNSCH_RE = re.compile(
    r"\b(?:ich\s+(?:m(?:ö|oe)chte|will|wollte|w(?:ü|ue)rde|h(?:ä|ae)tte|brauche|"
    r"br(?:ä|ae)uchte|suche|bitte)|w(?:ü|ue)rde\s+gern|h(?:ä|ae|a)(?:tt|b)e?\s+gern|"
    r"machen\s+sie|k(?:ö|oe)nnten\s+sie|bitte\s+um)\b", re.I)

# Bewusst KEIN nacktes "Gut." / "Okay.": das sind die ueblichen Quittungen der
# Maschine. Als Vorsatz landen sie im Gedaechtnis des Wiederholungs-Waechters
# und koennten dort eine echte Quittung als "schon gesagt" streichen.
_BEZUG_NEUTRAL = ("Verstehe.", "Alles klar.", "Mhm, verstehe.", "In Ordnung.")
_BEZUG_WUNSCH = ("Gerne.", "Sehr gerne.", "Das mache ich gerne.")
_BEZUG_LEID = ("Das tut mir leid.", "Oh, das tut mir leid.",
               "Verstehe, das ist unangenehm.")
# Fix 5 (13.09.2026): alle Bezuege fuer den TTS-Platten-Cache
# (bianca/gehirn.feste_saetze) — als Vorsatz vor einer gewaermten Frage
# kostet der Bezug sonst eine eigene Synthese (~0,5-1 s) und schiebt die
# Antwort hinter die 2-s-Grenze. Inhaltsfrei, nie Patientendaten.
ALLE_BEZUEGE: tuple[str, ...] = _BEZUG_NEUTRAL + _BEZUG_WUNSCH + _BEZUG_LEID


def modus() -> str:
    """``off`` | ``shadow`` | ``enforce`` (Default enforce).

    Ein fehlender Bezug ist kein Datenfehler, sondern ein Ton-Fehler — und der
    Eingriff ist minimal (ein kurzer Satz voran). Rueckweg: ``EINGEHEN=off``.
    """
    roh = (os.getenv("EINGEHEN") or "enforce").strip().lower()
    if roh in {"0", "off", "aus", "false"}:
        return "off"
    if roh in {"shadow", "schatten", "log"}:
        return "shadow"
    return "enforce"


def _s(x: Any) -> str:
    return (x or "").strip() if isinstance(x, str) else ""


def substanziell(gehoert: str) -> bool:
    """Hat der Anrufer etwas gesagt, auf das man eingehen MUSS?"""
    t = _s(gehoert)
    if not t:
        return False
    kern = re.sub(r"[^\wäöüßÄÖÜ\s]+", " ", t, flags=re.UNICODE).strip().lower()
    if not kern:
        return False
    woerter = [w for w in kern.split() if w]
    if not woerter:
        return False
    if all(w in _FUELLER for w in woerter):
        return False
    if len(woerter) == 1 and len(woerter[0]) < 4 and not any(c.isdigit() for c in t):
        return False
    return True


def nur_frage(antwort: str) -> bool:
    """Besteht die Antwort AUSSCHLIESSLICH aus Fragesaetzen?"""
    t = _s(antwort)
    if not t or "?" not in t:
        return False
    saetze = [x.strip() for x in _SATZ_TRENN_RE.split(t) if x.strip()]
    if not saetze:
        return False
    return all(x.endswith("?") for x in saetze)


def bezug_satz(zaehler: int, *, gehoert: str = "", art: str = "") -> str:
    """Kurzer, inhaltsfreier Bezug — rotierend, damit er nicht zur Masche wird."""
    if art in {"beschwerde", "notfall"}:
        reihe = _BEZUG_LEID
    elif _WUNSCH_RE.search(_s(gehoert)):
        reihe = _BEZUG_WUNSCH
    else:
        reihe = _BEZUG_NEUTRAL
    return reihe[max(0, int(zaehler or 0)) % len(reihe)]


def pruefen(gehoert: str, antwort: str) -> str:
    """``""`` = Zug geht ein. Sonst der Grund (fuer Spur/Test).

    ``frage-offen``: der Anrufer hat gefragt und die Antwort fragt nur zurueck
    — hier darf NICHTS vorangestellt werden (das waere eine Scheinantwort).
    ``nackte-frage``: Bezug fehlt und darf ergaenzt werden.
    """
    text = _s(antwort)
    if not text or not substanziell(gehoert):
        return ""
    if not nur_frage(text):
        return ""
    if _PRESENCE_RE.search(text) or _SCHON_BEZUG_RE.match(text):
        return ""
    if _ANRUFER_FRAGT_RE.search(_s(gehoert)):
        return "frage-offen"
    return "nackte-frage"


def ohne_bezug(antwort: str) -> str:
    """Einen von W-EINGEHEN vorangestellten Bezug wieder abnehmen.

    Gedacht fuer den Fall, dass ein AEUSSERER Vorspann ("Das freut mich.")
    vor die Antwort tritt — sonst hoert der Anrufer zwei Bezuege hintereinander
    ("Das freut mich. Gerne. Habe ich Sie richtig erkannt?"). Entfernt wird
    NUR ein exakter Satz aus ALLE_BEZUEGE, nie eine Quittung der Maschine.
    """
    t = _s(antwort)
    for bezug in ALLE_BEZUEGE:
        if t.startswith(bezug + " ") or t == bezug:
            return t[len(bezug):].strip()
    return t


def anwenden(sit: dict, gehoert: str, antwort: str, *, art: str = "") -> tuple[str, str]:
    """(Text, Spur-Grund). Stellt in ``enforce`` den Bezug voran."""
    text = _s(antwort)
    if modus() == "off":
        return text, ""
    grund = pruefen(gehoert, text)
    if not grund:
        return text, ""
    if grund == "frage-offen":
        return text, "eingehen-frage-offen"
    if modus() == "shadow":
        return text, "eingehen-shadow"
    zaehler = int((sit or {}).get("eingehenZaehler") or 0)
    if isinstance(sit, dict):
        sit["eingehenZaehler"] = zaehler + 1
    bezug = bezug_satz(zaehler, gehoert=gehoert, art=art)
    return (f"{bezug} {text}".strip(), "eingehen")
