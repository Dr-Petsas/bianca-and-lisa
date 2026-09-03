"""W-ANSTAND: Beschimpfungen und Fluchen — Bianca bleibt charmant.

Chef 03.09.2026 (woertlich): "wenn dich jemand beschimpft oder flucht sagst
du nur.... boah... das war nicht nett... ich gebe mir echt muehe oder 4-5
Alternativen in dieser Art. eine lustige nehmen wir auf wenn jemand sagt
ach fick dich oder aehnliches.. sagst du..... aehhhm selber!! sonst noch was?"

Deterministisch (0 ms, kein LLM). agent.user_turn fragt diese Schicht NUR,
wenn flow.zug None geliefert hat — ein Satz mit echtem Anliegen drin
("Verbinden Sie mich, Sie bloede Kuh!") gewinnt also immer den Fach-Weg,
und der Konter faellt weg. Nie zurueckschimpfen, nie beleidigt auflegen:
ein kurzer Konter, danach laeuft das Gespraech normal weiter (der
Frage-Anker holt eine offene Pflichtfrage im naechsten Zug zurueck).
"""

from __future__ import annotations

import re

# "fick dich oder aehnliches" — die lustige Antwort. Reflexive Verwuenschungen
# und harte Titulierungen, bei denen "selber!" als Konter sitzt.
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

ANTWORT_SELBER = "Ähm — selber! Sonst noch was?"

# 4-5 Alternativen "in dieser Art" — Rotation pro Sitzung, nie wortgleich
# hintereinander (anstandZaehler zaehlt hoch).
ANTWORTEN = [
    "Boah… das war jetzt nicht nett. Ich gebe mir hier echt Mühe.",
    "Huch — das war unfreundlich. Dabei versuche ich wirklich, Ihnen zu helfen.",
    "Also… das sagt man doch nicht. Ich gebe mein Bestes, versprochen.",
    "Oha. Das war jetzt nicht die feine Art — ich bemühe mich hier nach Kräften.",
    "Das war nicht besonders freundlich, wissen Sie? Ich gebe mir echt Mühe.",
]


def _s(v) -> str:
    return " ".join(str(v or "").split()).strip()


def zug(sit: dict, text: str) -> dict | None:
    """Konter auf Beschimpfung/Fluchen — None, wenn der Satz sauber ist."""
    t = _s(text)
    if not t:
        return None
    if _SELBER_RE.search(t):
        return {"text": ANTWORT_SELBER}
    if _SCHIMPF_RE.search(t) or (
            _FLUCH_RE.search(t) and len(t.split()) <= _FLUCH_MAX_WORTE):
        i = int(sit.get("anstandZaehler") or 0)
        sit["anstandZaehler"] = i + 1
        return {"text": ANTWORTEN[i % len(ANTWORTEN)]}
    return None
