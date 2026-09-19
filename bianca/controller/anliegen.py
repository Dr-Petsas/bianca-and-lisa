"""Semantische Anliegen aus echten Anrufen — kein einzelnes Wort rauspicken.

Der Live-Befund (659 gewertete Mitschnitte) und die Dock-Saetze zeigen
immer wieder dieselben Fallen:

- „Terminauskunft“ / nacktes „Auskunft“ ist DOPPELDEUTIG: bestehender
  Termin oder neuer? Wer sofort bucht oder nach dem Nachnamen sucht, liegt
  oft falsch.
- „Einsicht in Behandlungsunterlagen“ / Befunde / Roentgen ist kein Rezept
  und kein Termin.
- „akute Hautbeschwerden“ ist ein Blessing-Motiv, KEIN Notfall.
- „Notfall.“ / „Zahn vorne rausgefallen“ ist ein eigener Sofortweg.
- „Fragen zu einer Hyposensibilisierung“ plus „haut ab!“ ist eine Fachfrage
  (und Frust), kein Haut-Motiv und kein Notfall.

``deute(text)`` liefert Intent + Zusatzslots. Personal/Arzt bleiben
absichtlich draussen — die entscheidet die Live-Prioritaet in ``nlu_test``.
"""

from __future__ import annotations

import re

from bianca.controller.typen import Intent

# --------------------------------------------------------------------------- #
# Echte Wortlaute (Chef + Live-textIn). Semantik, keine Einzelwoerter.
# --------------------------------------------------------------------------- #
_AUSKUNFT_UNKLAR_RE = re.compile(
    r"(?:"
    r"termin\s*auskunft|auskunft\s*(?:zum|zu\s+(?:einem|meinem|dem))?\s*termin"
    r"|^(?:eine\s+)?auskunft(?:\s+bitte)?$"
    r"|ich\s+(?:brauche|haette|haette\s+gern|moechte|will)\s+(?:eine\s+)?auskunft"
    r"|auskunft\s+(?:bitte|geben|erhalten)"
    r")",
    re.I,
)
_AUSKUNFT_BESTAND_RE = re.compile(
    r"(?:"
    r"habe\s+ich\s+(?:da\s+|denn\s+|ueberhaupt\s+|bei\s+ihnen\s+)?"
    r"(?:noch\s+)?(?:einen\s+|einen\s+anderen\s+)?termin"
    r"|wann\s+ist\s+(?:denn\s+)?(?:mein|der)\s+(?:andere\s+)?termin"
    r"|welchen\s+termin\s+habe\s+ich"
    r"|termin\s+(?:vergessen|verpennt|verschwitzt)"
    r"|ich\s+habe\s+(?:n(?:ae|ä)chste\s+woche\s+)?einen\s+termin"
    r"|wei(?:ss|ß)\s+(?:ich\s+)?(?:aber\s+)?(?:den\s+)?"
    r"(?:tag|termin)?\s*nicht\s+mehr(?:\s+wann)?"
    r"|nicht\s+mehr\s+wann\s+(?:der|er|mein\s+termin)"
    r"|vergess\w*.{0,32}termin"
    r"|termin.{0,24}vergess"
    r"|ist\s+der\s+termin\s+eingetragen"
    r"|zu\s+mein(?:em|en)\s+termin"
    r"|mein(?:em|en)\s+(?:bestehenden\s+|vorhandenen\s+|alten\s+)?termin"
    r"|wissen\s*wann.{0,40}termin"
    r"|termin.{0,48}erfahr"
    r"|erfahr.{0,32}termin"
    r"|genauen?\s+termin"
    r")",
    re.I,
)
_AUSKUNFT_BESTAND_ANTWORT_RE = re.compile(
    r"\b(?:bestehend|bereits\s+vereinbart|schon\s+(?:gebucht|da)|"
    r"zu\s+mein(?:em|en)|mein(?:em|en)\s+(?:alten\s+|bestehenden\s+)?"
    r"termin|den\s+alten|nachschauen|nachsehen|nachgucken|"
    r"vorhanden(?:en)?\s+termin)\b",
    re.I,
)
_NEU_ANTWORT_RE = re.compile(
    r"\b(?:neu(?:en)?|vereinbaren|buchen|ausmachen|ersttermin|"
    r"neuen\s+termin)\b",
    re.I,
)
_VEREINBAREN_RE = re.compile(
    r"(?:"
    r"termin\s+vereinbaren|vereinbaren\s+(?:eines?\s+)?termin"
    r"|ich\s+(?:wuerde|würde)\s+gern(?:e)?\s+einen\s+termin"
    r"|ich\s+(?:moechte|möchte|haette|hätte|will|brauche)\s+"
    r"(?:gern(?:e)?\s+)?(?:einen\s+)?termin"
    r")",
    re.I,
)
_ABSAGE_RE = re.compile(
    r"(?:"
    r"absag\w*|stornier\w*|cancel\w*|annulier\w*"
    r"|termine?\s+(?:loeschen|löschen|streichen)"
    r"|nicht\s+kommen"
    r")",
    re.I,
)
_VERSCHIEB_RE = re.compile(
    r"(?:"
    r"termin\s*verschieb\w*|verschiebung|verscheib\w*"
    r"|termin\s+(?:verlegen|umbuchen|aendern|ändern)"
    r"|es\s+geht\s+um\s+eine\s+terminverschiebung"
    r")",
    re.I,
)
# Befundbesprechung / Roentgentermin sind Termine, keine Aktenanforderung.
_UNTERLAGEN_TERMIN_RE = re.compile(
    r"befund\w*besprech|r(?:oe|ö|o)ntgen\w*termin",
    re.I,
)
_UNTERLAGEN_RE = re.compile(
    r"(?:"
    r"einsicht"
    r"|behandlungs\w*unterlagen|patientenunterlagen|behnadlungsunterlagen"
    r"|krankenakte|patientenakte"
    r"|\bunterlagen\b"
    r"|\bbefund\w*"
    r"|r(?:oe|ö|o)n?t?gen"
    r"|rötgen|roentgen"
    r"|akte\s+einsehen"
    r"|kopie\s+(?:der|meiner)\s+(?:akte|unterlagen|befunde)"
    r"|(?:befund|unterlagen|bilder|akte).{0,28}(?:e\s?mail|mailen|per\s+mail)"
    r"|(?:e\s?mail|mailen|per\s+mail).{0,28}(?:befund|unterlagen|bilder|akte)"
    r")",
    re.I,
)
_REZEPT_RE = re.compile(r"\brezept(?!ion|iom|zion)\w*", re.I)
_UEBERWEIS_RE = re.compile(r"\bueberweis", re.I)
_KRANK_RE = re.compile(r"\bkrank(?:en)?meldung|\barbeitsunfaeh|\bau\s+beschein", re.I)
_RECHNUNG_RE = re.compile(
    r"\brechnung|\breklamation|\bmahnung|\bhonorar|"
    r"\bbuchhaltung|\binkasso|\babrechnungsfehler",
    re.I,
)
_RUECKRUF_RE = re.compile(
    r"\brueckruf|\bzurueckrufen|\brufen\s+sie\s+(?:mich|uns)\s+zurueck|"
    r"\bsoll\s+(?:die\s+praxis|jemand)\s+(?:mich\s+)?anrufen",
    re.I,
)
# Live-Notfaelle (8 Anrufe): das Wort selbst, Zahn rausgefallen, 112.
# NICHT: akute Hautbeschwerden (Blessing-Motiv).
_NOTFALL_RE = re.compile(
    r"(?:"
    r"\bnotfall\w*"
    r"|\bnotdienst\b"
    r"|\bnotarzt\b"
    r"|\blebensgefahr\b"
    r"|\b112\b"
    r"|zahn\s+\w*\s*rausgefallen"
    r"|zahn\s+ausgeschlagen"
    r")",
    re.I,
)
_AKUT_HAUT_RE = re.compile(r"akute\s+hautbeschwerd", re.I)
_FACHFRAGE_RE = re.compile(
    r"(?:"
    r"hyposensibilis\w*|desensibilis\w*|allergiespritz"
    r"|fragen?\s+zu\s+(?:einer\s+|der\s+|einem\s+)?"
    r"(?:hyposens|therapie|behandlung|impfung|medikament)"
    r")",
    re.I,
)
_FRUST_RE = re.compile(
    r"(?:haut\s+ab|halt\s+die\s+klappe|verpiss|fick\s+dich|blöde\s+kuh|bloede\s+kuh)",
    re.I,
)
_PRAXISINFO_RE = re.compile(
    r"(?:"
    r"oeffnungszeit|sprechzeit|wann\s+(?:habt\s+ihr|haben\s+sie)\s+(?:auf|offen|geoeffnet)"
    r"|haben\s+sie\s+am\s+\w+\s+offen"
    r"|wie\s+(?:komme|komme\s+ich|erreiche)\s+(?:ich\s+)?(?:zur\s+praxis|zu\s+ihnen)"
    r"|anfahrt|wegbeschreibung|parkplatz|wo\s+(?:sind|liegt)\s+(?:ihr|die)\s+"
    r")",
    re.I,
)

# Live-Motive: klarer Buchungswunsch, nicht bloss das Wort „Termin“.
_MOTIV: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bzahnreinigung|\bpzr\b|\bprophylaxe\b", re.I), "Zahnreinigung"),
    (re.compile(r"\bkontrolle\b|\buntersuchung\b|\bvorsorge\b|\bhautscreening\b", re.I), "Kontrolle"),
    (re.compile(r"\bschmerzen\b|\bzahnschmerzen\b|\bweh\b", re.I), "Schmerzen"),
    (re.compile(r"akute\s+hautbeschwerd|\bakne\b|\bhaut\b|\bmuttermal\b|\bwarzen\b|\batherom\b", re.I), "Haut"),
    (re.compile(r"\bimplantat", re.I), "Implantat-Besprechung"),
    (re.compile(r"\bfuellung|\bfüllung", re.I), "Fuellung"),
    (re.compile(r"\bberatung\b|\bbesprechung\b", re.I), "Beratung"),
    (re.compile(r"\bfusspflege|\bfußpflege|\bzeh\b", re.I), "Fusspflege"),
    (re.compile(r"\bblutabnahme|\blabor\b", re.I), "Labor"),
    (re.compile(r"\bschwangerschaft|\bmutterschaft", re.I), "Schwangerschaft"),
    (re.compile(r"\ballergie\b", re.I), "Allergie"),
    (re.compile(r"\bneupatient|\berstuntersuch", re.I), "Neupatient"),
]


def _falt(s: str) -> str:
    return (
        (s or "")
        .lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def deute(text: str) -> tuple[Intent | None, dict[str, str]]:
    """Semantisches Anliegen. ``None`` = bitte die Live-Prioritaet weiterlaufen."""
    t = _falt(text)
    if not t.strip():
        return None, {}

    if _NOTFALL_RE.search(t) and not _AKUT_HAUT_RE.search(t):
        return Intent.NOTFALL, {}

    if _UNTERLAGEN_TERMIN_RE.search(t):
        pass
    elif _UNTERLAGEN_RE.search(t):
        return Intent.DOKUMENT, {"dokumentart": "unterlagen"}

    if _REZEPT_RE.search(t):
        return Intent.DOKUMENT, {"dokumentart": "rezept"}
    if _UEBERWEIS_RE.search(t):
        return Intent.DOKUMENT, {"dokumentart": "ueberweisung"}
    if _KRANK_RE.search(t):
        return Intent.DOKUMENT, {"dokumentart": "krankmeldung"}
    if _RECHNUNG_RE.search(t):
        return Intent.DOKUMENT, {"dokumentart": "rechnung"}

    if _FACHFRAGE_RE.search(t):
        thema = "Hyposensibilisierung" if "hyposens" in t or "desensibil" in t else "Behandlung"
        extra = {"thema": thema}
        if _FRUST_RE.search(t):
            extra["ton"] = "frust"
        return Intent.PRAXISINFO, extra

    if _PRAXISINFO_RE.search(t):
        return Intent.PRAXISINFO, {"thema": "Öffnungszeiten"}

    extra = zwei_anliegen_slots(t)
    hat_absage = _ABSAGE_RE.search(t)
    hat_verschieb = _VERSCHIEB_RE.search(t)
    if hat_absage and hat_verschieb:
        # Erstes Verb gewinnt; das zweite liegt in zweit_anliegen.
        a_pos = hat_absage.start()
        v_pos = hat_verschieb.start()
        if v_pos <= a_pos:
            return Intent.VERSCHIEBEN, extra
        return Intent.ABSAGEN, extra
    if hat_absage:
        return Intent.ABSAGEN, extra
    if hat_verschieb:
        return Intent.VERSCHIEBEN, extra

    if _RUECKRUF_RE.search(t):
        return Intent.RUECKRUF, {}

    if _AUSKUNFT_BESTAND_RE.search(t):
        return Intent.AUSKUNFT, {"auskunft_art": "bestand"}

    if _AUSKUNFT_UNKLAR_RE.search(t):
        return Intent.AUSKUNFT, {"auskunft_art": "unklar"}

    if _VEREINBAREN_RE.search(t):
        extra: dict[str, str] = {}
        for pat, grund in _MOTIV:
            if pat.search(t):
                extra["besuchsgrund"] = grund
                break
        return Intent.BUCHEN, extra

    for pat, grund in _MOTIV:
        if pat.search(t):
            return Intent.BUCHEN, {"besuchsgrund": grund}

    return None, {}


_ZWEI_ANLIEGEN_NEU_RE = re.compile(
    r"(?:und|sowie).{0,40}\bneu(?:en|e|er)?\b"
    r"|\bneu(?:en|e|er)?\b.{0,24}(?:termin|machen|vereinbaren|ausmachen)",
    re.I,
)
_TASK_POS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"verschieb\w*|verscheib\w*|verleg\w*|umbuch\w*|terminverschieb", re.I), "verschieben"),
    (re.compile(r"absag\w*|stornier\w*|cancel\w*", re.I), "absagen"),
    (_ZWEI_ANLIEGEN_NEU_RE, "buchen"),
)


def zwei_anliegen_slots(text: str) -> dict[str, str]:
    """Zweites Anliegen + Person: geparkt, gehoert nicht zum ersten Task."""
    found: list[tuple[int, str]] = []
    gesehen: set[str] = set()
    for rx, name in _TASK_POS:
        m = rx.search(text)
        if m and name not in gesehen:
            found.append((m.start(), name))
            gesehen.add(name)
    found.sort()
    if len(found) < 2:
        return {}
    zweit = found[1][1]
    from bianca.controller import fuer_wen as _fw
    und = re.search(r"\bund\b", text, re.I)
    zweite = text[und.start():] if und else text
    rollen = [r for r in _fw.deute_alle(zweite) if r and r != "selbst"]
    if not rollen:
        rollen = [r for r in _fw.deute_alle(text) if r and r != "selbst"]
    if not rollen:
        return {}
    return {"zweit_anliegen": zweit, "zweit_fuer_wen": rollen[0]}


def auskunft_antwort(text: str) -> str:
    """Antwort auf die Klaerung: bestehend | neu | ''."""
    t = _falt(text)
    if _AUSKUNFT_BESTAND_ANTWORT_RE.search(t) or _AUSKUNFT_BESTAND_RE.search(t):
        return "bestand"
    if _NEU_ANTWORT_RE.search(t) or _VEREINBAREN_RE.search(t):
        return "neu"
    return ""


__all__ = ["deute", "auskunft_antwort", "zwei_anliegen_slots"]
