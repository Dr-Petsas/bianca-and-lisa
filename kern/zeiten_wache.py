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

# Schließen/Feierabend — trägt keine eigene Uhrzeit, gehört aber zur
# Öffnungs-Auskunft („Danach schließen wir.", live 15.09.2026 als Rest
# stehengeblieben).
_SCHLIESS_RE = re.compile(
    r"(?:\bschlie(?:ß|ss)\w*|\bschluss\b|\bfeierabend\b|\bzu\s+ende\b)",
    re.I,
)

# Rückbezug auf einen VORHERIGEN Satz: solche Sätze sind die Fortsetzung des
# gestrichenen Zeitplans („Danach schließen wir.", „An den anderen Tagen
# nachmittags von 14 bis 18 Uhr.") und wären allein sinnlos oder irreführend.
_RUECKBEZUG_RE = re.compile(
    r"(?:"
    r"\bdanach\b|\bdavor\b|\bdazwischen\b|\banschlie(?:ß|ss)end\b"
    r"|\bansonsten\b|\bau(?:ß|ss)erdem\b|\bzus(?:ä|ae)tzlich\b"
    r"|\ban\s+den\s+(?:anderen|(?:ü|ue)brigen|restlichen)\s+tagen\b"
    r"|\bdie\s+(?:anderen|(?:ü|ue)brigen)\s+tage\b"
    r"|\bsonst\b"
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


def ist_zeit_auskunft(satz: str, streng: bool = False) -> bool:
    """Behauptet dieser Satz eine Praxis-Öffnungszeit?

    ``streng`` gilt, wenn der Anrufer GERADE nach den Zeiten gefragt hat: dann
    ist jeder Satz mit einer Zeitangabe die Antwort darauf, auch ohne
    Öffnungs-Vokabular („Heute von 8 bis 12 Uhr und von 14 bis 16 Uhr.").
    Termin-Sätze bleiben in beiden Fällen unangetastet."""
    s = _s(satz)
    if not s or _NIE_RE.search(s):
        return False
    if not _ZEIT_RE.search(s):
        return False
    return bool(streng or _OEFFNUNG_RE.search(s))


def ist_fortsetzung(satz: str) -> bool:
    """Fortsetzung eines gestrichenen Zeitplans?

    Live blieb „Danach schließen wir." hinter der ehrlichen Auskunft stehen —
    ein Rückbezug auf einen Satz, den es nicht mehr gibt. Solche Sätze fallen
    NUR, wenn in diesem Text/Zug schon eine Zeit-Behauptung gestrichen wurde;
    Termin-Bezug schützt wie immer („Danach hätte ich einen Termin frei")."""
    s = _s(satz)
    if not s or _NIE_RE.search(s):
        return False
    if not _RUECKBEZUG_RE.search(s):
        return False
    return bool(_SCHLIESS_RE.search(s) or _ZEIT_RE.search(s)
                or _OEFFNUNG_RE.search(s))


def saeubern(sit: dict | None, text: str, gefragt: str = "",
             merken: bool = True) -> tuple[str, list[str]]:
    """(neuer Text, gestrichene Zeit-Behauptungen).

    Streicht SATZWEISE (``sprech.tts_saetze`` — nie hinter Abkürzungen).
    Hat der Anrufer NACH den Zeiten gefragt, kommt die ehrliche Auskunft
    VORAN: nach dem Streichen blieb live nur der Folgesatz übrig („Möchten
    Sie sich zur Kontrolle vorstellen?") — eine Rückfrage, die an der
    gestellten Frage vorbeigeht. Ohne Frage (das Modell fing von selbst damit
    an) genügt der Ersatz, wenn nichts übrig bleibt.

    Der Ersatz kommt pro Zug GENAU EINMAL (``_zeitenErsatz``): im P5-Strom
    läuft jeder Satz einzeln durch die Wache, zwei erfundene Zeit-Sätze
    hätten ihn sonst zweimal gesprochen. Ist er verbraucht, bleibt der Rest
    leer — der Zug hat die ehrliche Auskunft dann schon gesagt, und am
    Zugende hängt `_nie_stumm` die offene Pflichtfrage an. Der erfundene Satz
    darf in KEINEM Fall als Rückfall zurückkommen."""
    t = _s(text)
    if not t or not aktiv(sit):
        return text, []
    streng = _ist_zeitenfrage(gefragt)
    # Im P5-Strom kommt jeder Satz EINZELN: der Rueckbezug ("Danach schliessen
    # wir.") steht dann in einem eigenen Aufruf und braucht das Wissen, dass
    # in DIESEM Zug schon ein Zeitplan gefallen ist.
    schon_weg = _marke_gesetzt(sit, "_zeitenWeg", gefragt)
    weg: list[str] = []
    behalten: list[str] = []
    for s in sprech.tts_saetze(t):
        fortsetzung = (weg or schon_weg) and ist_fortsetzung(s)
        if ist_zeit_auskunft(s, streng) or fortsetzung:
            weg.append(s)
        else:
            behalten.append(s)
    if not weg:
        return text, []
    if (ERSATZ not in behalten
            and (streng or not behalten)
            and not _marke_gesetzt(sit, "_zeitenErsatz", gefragt)):
        behalten = [ERSATZ] + behalten
        if merken:
            _marke_setzen(sit, "_zeitenErsatz", gefragt)
    if merken:
        _marke_setzen(sit, "_zeitenWeg", gefragt)
    return " ".join(behalten).strip(), weg


def _ist_zeitenfrage(gefragt: str) -> bool:
    if not _s(gefragt):
        return False
    try:
        from kern import wissen as _wissen
        return "oeffnungszeiten" in _wissen.auskunft_themen(gefragt)
    except Exception:
        return False


def _zug_schluessel(sit: dict | None, gefragt: str) -> list:
    """Schlüssel der Zug-Marken: laufender Zug + gehörter Satz.

    Die Zug-Nummer setzt der Dienst je Zug (W-QWEN-KORREKTOR); fragt der
    Anrufer im nächsten Zug erneut, ist der Schlüssel neu — der Ersatz ist
    dann wieder frei, sonst bliebe die zweite Frage unbeantwortet."""
    zug = 0
    if isinstance(sit, dict):
        try:
            zug = int(sit.get("_zugNr") or 0)
        except Exception:
            zug = 0
    return [zug, _s(gefragt).casefold()[:120]]


def _marke_gesetzt(sit: dict | None, feld: str, gefragt: str) -> bool:
    if not isinstance(sit, dict):
        return False
    return sit.get(feld) == _zug_schluessel(sit, gefragt)


def _marke_setzen(sit: dict | None, feld: str, gefragt: str) -> None:
    if isinstance(sit, dict):
        sit[feld] = _zug_schluessel(sit, gefragt)
