"""W-ZEITEN-WACHE (15.09.2026): keine erfundenen Öffnungszeiten.

Live-Probe gegen den ECHTEN Prompt der neuen Praxis Rüther (Ben, DID …4160):
Der Agent-Prompt aus dem Portal trägt dort nur generische Regeln (Datum,
Zeitzone, Geschlecht), keine einzige Praxis-Tatsache, und die
Standorteinstellungen stehen auf dem Mo-So-08-18-Default (den ``standort``
zu Recht verwirft). Drei Fragen, drei frei erfundene Antworten:

    „Wann haben Sie geöffnet?"   → „Wir sind heute von 8 bis 12 Uhr und von
                                    14 bis 16 Uhr für Sie da."
    „Wann habt ihr auf?"         → „montags, mittwochs und freitags von 8 bis
                                    12 Uhr, dienstags und donnerstags von 14
                                    bis 18 Uhr"
    „Haben Sie am Freitag offen?" → „Ja, wir sind freitags von 8 bis 12 Uhr
                                     für Sie da."

Eine Patientin, die das glaubt, steht vor verschlossener Tür. Deshalb
dieselbe Regel wie bei allen Fakten (W-FAKTEN-WACHE, W-ANREDE): eine
Zeit-Auskunft darf nur raus, wenn die Zeiten BELEGT sind. Belegt heißt:

- ``tenant["standort"]["text"]`` — gepflegte Standorteinstellungen (W-STANDORT),
- eine ausdrückliche Zeile im Agent-Prompt („Öffnungszeiten: …" bei MedDent,
  der „SPRECHZEITEN"-Block bei Thaler/Blessing),
- lokales ``wissen.oeffnungszeiten`` des Mandanten.

Die Belegt-Seite ist bewusst großzügig (Öffnungs-Vokabular PLUS Zeitangabe
irgendwo im Praxis-Prompt genügt): ein gestrichener legitimer Satz wäre der
teurere Fehler. Ohne Mandant ist die Wache AUS.

Bleibt nach dem Streichen nichts übrig, kommt eine ehrliche Auskunft; der
Frage-Anker (`_nie_stumm`, W-FOKUS) hängt die offene Pflichtfrage an.

NIE angefasst werden Sätze mit Termin-/Buchungs-Bezug: „Ich habe am Montag um
neun Uhr einen Platz frei" ist eine Kalender-Aussage und hat ihre eigene
Wache (W-FAKTEN-WACHE, Slot-Claim).

Stufen/Notaus: ``ZEITEN_WACHE=off|shadow|enforce`` (Default enforce).

Tests: ``tests/test_zeiten_wache.py``
"""

from __future__ import annotations

import os
import re
from typing import Any

from kern import sprech

# Öffnungs-Vokabular — eng gehalten. „offen" nur in der Wendung
# „haben/sind wir … offen": ein blankes „offen" trifft sonst „ich habe noch
# einen Platz offen" (das wäre eine Kalender-Aussage, nicht die Praxiszeit).
_OEFFNUNG_RE = re.compile(
    r"(?:"
    r"\b(?:ö|oe)ffnungszeit\w*"
    r"|\bsprechzeit\w*|\bsprechstunde\w*|\bpraxiszeit\w*"
    r"|\bge(?:ö|oe)ffnet\b|\bgeschlossen\b"
    r"|\bf(?:ü|ue)r\s+Sie\s+da\b"
    r"|\berreichbar\b|\berreichen\s+(?:Sie\s+)?uns\b"
    # „Wir haben dienstags offen" — bis zu drei Wörter dazwischen, aber nie
    # Termin-Vokabular („ich habe noch einen Platz offen" ist Kalender).
    r"|\b(?:haben|hat|habe|sind|ist)\b"
    r"(?:\s+(?!termin|platz|pl(?:ä|ae)tze|slot)\w+){0,3}\s+offen\b"
    r")",
    re.I,
)

# Zeitangabe: Uhrzeit, „Uhr", Wochentags-Adverb oder Tageshälfte.
_ZEIT_RE = re.compile(
    r"(?:"
    r"\b\d{1,2}(?::\d{2})?\s*Uhr\b|\b\d{1,2}:\d{2}\b|\bUhr\b"
    r"|\b(?:montags?|dienstags?|mittwochs?|donnerstags?|freitags?"
    r"|samstags?|sonnabends?|sonntags?|werktags?|wochentags?)\b"
    r"|\bvormittags?\b|\bnachmittags?\b|\babends?\b"
    r")",
    re.I,
)

# Termin-/Buchungs-Bezug: diese Sätze gehören dem Kalender und werden nie
# angefasst — dort wacht die Fakten-Wache (Slot-Claim).
_NIE_RE = re.compile(
    r"(?:"
    r"\btermin\w*|\bpl(?:a|ä)tz\w*|\bplatz\b|\bslot\w*"
    r"|\bbuch\w*|\beintrag\w*|\beintrage\w*|\bfrei\b"
    r"|\bverschieb\w*|\babsag\w*|\banmeld\w*|\bpasst\b|\bpassen\b"
    r"|\bnotiz\w*|\br(?:ü|ue)ckruf\w*"
    r")",
    re.I,
)

ERSATZ = ("Die genauen Öffnungszeiten habe ich hier leider nicht vorliegen — "
          "einen Termin kann ich Ihnen aber gern direkt geben.")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def modus() -> str:
    """``off`` | ``shadow`` | ``enforce`` (Default enforce)."""
    roh = (os.getenv("ZEITEN_WACHE") or "enforce").strip().lower()
    if roh in {"0", "off", "aus", "false"}:
        return "off"
    if roh in {"shadow", "schatten", "log"}:
        return "shadow"
    return "enforce"


def zeiten_belegt(tenant: dict | None) -> bool:
    """Kennt der Mandant seine Öffnungszeiten aus einer echten Quelle?

    Großzügig: im Zweifel BELEGT, damit eine legitime Auskunft nie fällt."""
    t = tenant if isinstance(tenant, dict) else {}
    if not t:
        return True                      # ohne Mandant keine Wache (fail-safe)
    st = t.get("standort") if isinstance(t.get("standort"), dict) else {}
    if _s(st.get("text")):
        return True
    w = t.get("wissen") if isinstance(t.get("wissen"), dict) else {}
    if _s(w.get("oeffnungszeiten")) or _s(t.get("oeffnungszeiten")):
        return True
    prompt = str(t.get("dbPrompt") or "")
    if not prompt:
        return False
    try:
        from kern import wissen as _wissen
        if _wissen._prompt_oeffnungszeiten(prompt):
            return True
    except Exception:                    # Wache darf nie werfen
        pass
    # Mehrzeilige Zeiten-Blöcke (Thaler „SPRECHZEITEN", Blessing
    # „- Sprechzeiten:") erkennt der Einzeiler-Parser nicht — hier genügt
    # Öffnungs-Vokabular samt Zeitangabe irgendwo im Praxis-Prompt.
    return bool(_OEFFNUNG_RE.search(prompt) and _ZEIT_RE.search(prompt))


def aktiv(sit: dict | None) -> bool:
    """Wache scharf? Nur wenn der Mandant KEINE belegten Zeiten hat."""
    if not isinstance(sit, dict):
        return False
    tenant = sit.get("tenant")
    if not isinstance(tenant, dict) or not tenant:
        return False
    return not zeiten_belegt(tenant)


def ist_zeit_auskunft(satz: str) -> bool:
    """Behauptet dieser Satz eine Praxis-Öffnungszeit?"""
    s = _s(satz)
    if not s or _NIE_RE.search(s):
        return False
    return bool(_OEFFNUNG_RE.search(s) and _ZEIT_RE.search(s))


def saeubern(sit: dict | None, text: str) -> tuple[str, list[str]]:
    """(neuer Text, gestrichene Zeit-Behauptungen).

    Streicht SATZWEISE (``sprech.tts_saetze`` — nie hinter Abkürzungen);
    bleibt nichts übrig, steht die ehrliche Auskunft da."""
    t = _s(text)
    if not t or not aktiv(sit):
        return text, []
    saetze = sprech.tts_saetze(t)
    weg = [s for s in saetze if ist_zeit_auskunft(s)]
    if not weg:
        return text, []
    behalten = [s for s in saetze if not ist_zeit_auskunft(s)]
    neu = " ".join(behalten).strip() or ERSATZ
    return neu, weg
