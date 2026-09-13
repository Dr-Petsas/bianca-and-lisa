"""W-ANSTAND: Beschimpfungen und Fluchen — Bianca deeskaliert freundlich.

Deterministisch (0 ms, kein LLM). agent.user_turn fragt diese Schicht NUR,
wenn flow.zug None geliefert hat — ein Satz mit echtem Anliegen drin
("Verbinden Sie mich, Sie bloede Kuh!") gewinnt also immer den Fach-Weg.
Nie zurückschimpfen, nie beleidigt auflegen: eine kurze Entschuldigung,
danach läuft das Gespräch normal weiter (der
Frage-Anker holt eine offene Pflichtfrage im naechsten Zug zurueck).
"""

from __future__ import annotations

import re

# Derbe Verwünschungen und harte Titulierungen werden erkannt, aber genauso
# freundlich behandelt wie andere Beschimpfungen — kein Gegenkonter.
_SELBER_RE = re.compile(
    r"\bfick|verpiss dich|leck mich|arschloch|wichser|hurensohn|fotze|"
    r"missgeburt|drecksau|du sau\b|bastard",
    re.I,
)

# Beschimpfungen Richtung Bianca: Titulierungen und Abkanzler.
# (\bspasti?\b faengt "Spast/Spasti", aber NICHT "Spastik" — Medizin-Kontext.)
_SCHIMPF_RE = re.compile(
    r"(bl(ö|oe)de|dumme|d(ä|ae)mliche|bekloppte|behinderte) "
    r"(kuh|ziege|schlampe|maschine|ki\b|tussi|schnalle)|"
    r"\bidiot(in)?\b|\bvollpfosten\b|\bdepp\b|\bspasti?\b|\bschlampe\b|"
    r"schei(ß|ss)[\s-]?(ki|maschine|teil|ding|roboter)\b|"
    r"drecks[\s-]?(ki|maschine|teil|ding|roboter)\b|"
    r"halt die klappe|halt.?s maul|halt dein maul|schnauze halten|"
    r"\bdu nervst\b|bist du (bl(ö|oe)d|dumm|behindert|zu doof)|"
    r"(du|sie) (bl(ö|oe)des|dummes) (ding|etwas)|zu bl(ö|oe)d f(ü|ue)r",
    re.I,
)

# Fluchen ohne klares Ziel ("So ein Scheiss!"): nur kontern, wenn der Satz
# im Kern NUR der Fluch ist — Frust ueber die eigene Lage ("Scheisse, ich
# hab den Termin verpennt") gehoert dem normalen Gespraech.
_FLUCH_RE = re.compile(
    r"verdammte schei(ß|ss)e|so ein schei(ß|ss)(dreck)?\b|zum kotzen|"
    r"verfluchte? (mist|schei(ß|ss)e)|schei(ß|ss) (telefon|anruf|automat)",
    re.I,
)
_FLUCH_MAX_WORTE = 6

# Einzelwort-Pruefung fuer Nebenthemen: kern/gespraech legt Themen als
# einzelne Inhaltswoerter ab. Live 11.09.2026 lud der Stille-Waechter
# minutenlang zum „Thema arsch" ein — ein Thema aus einer Beschimpfung darf
# Bianca nie von sich aus zurueckholen.
_UNFEIN_RE = re.compile(
    r"^(?:arsch\w*|schei(?:ß|ss)\w*|fick\w*|kack\w*|fotze\w*|wichser\w*|"
    r"hurensohn\w*|schlampe\w*|nutte\w*|piss\w*|verarsch\w*|bl(?:ö|oe)d\w*|"
    r"dumm\w*|idiot\w*|spast\w*|depp\w*|vollpfosten\w*|klappe|maul|sau|"
    r"drecksau\w*|missgeburt\w*|bastard\w*|kotzen|anschleck\w*|schwanz\w*|"
    r"titten\w*|sex\w*|nerv\w*)$",
    re.I,
)

# Freundliche Varianten — Rotation pro Sitzung, nie wortgleich
# hintereinander (anstandZaehler zaehlt hoch).
ANTWORTEN = [
    "Puhhh, ich will Sie nicht verärgern. Entschuldigung, ich versuche, Sie besser zu verstehen.",
    "Es tut mir leid, dass wir uns gerade nicht gut verstehen. Ich versuche es noch einmal in Ruhe.",
    "Entschuldigung, ich möchte Ihnen wirklich helfen. Lassen Sie es uns noch einmal versuchen.",
    "Ich merke, dass das gerade schwierig ist. Entschuldigung, ich bemühe mich, Sie besser zu verstehen.",
]
ANTWORT_SELBER = ANTWORTEN[0]  # alter Importname, bewusst kein Gegenkonter


def _s(v) -> str:
    return " ".join(str(v or "").split()).strip()


def unfein(wort: str) -> bool:
    """Taugt dieses Thema-Wort NICHT zum Zurueckholen ins Gespraech?"""
    return bool(_UNFEIN_RE.match(_s(wort)))


def zug(sit: dict, text: str) -> dict | None:
    """Freundliche Deeskalation — None, wenn der Satz sauber ist."""
    t = _s(text)
    if not t:
        return None
    # Reiner STT-Schnipsel ohne Schimpfwort-Treffer-Kontext: kein Konter.
    # (Agent ueberspringt anstand bei wirkt_unklar sowieso — hier als Netz.)
    if len(t.split()) <= 2 and not (_SELBER_RE.search(t) or _SCHIMPF_RE.search(t)):
        return None
    if _SELBER_RE.search(t) or _SCHIMPF_RE.search(t) or (
            _FLUCH_RE.search(t) and len(t.split()) <= _FLUCH_MAX_WORTE):
        i = int(sit.get("anstandZaehler") or 0)
        sit["anstandZaehler"] = i + 1
        return {"text": ANTWORTEN[i % len(ANTWORTEN)]}
    return None
