"""Leichter Regel-NLU NUR fuer das isolierte Test-Dock des Dialogkerns.

Das ist AUSDRUECKLICH KEIN Produktions-Verstehen (kein Parakeet/Qwen, keine
Intent-Schicht des Live-Kerns). Es uebersetzt GETIPPTEN deutschen Text in ein
``SemanticEvent``, damit man den reinen Reducer im Browser/CLI gegen sich
sprechen lassen kann — Fragereihenfolge, Schleifenfreiheit, Ruecklesen und die
Familien (buchen/absagen/verschieben/auskunft/verbinden/dokument/rueckruf)
durchspielen, OHNE Telefon, MAS oder Cloud Function.

Der Orchestrator reicht die offene Erwartung des letzten Zugs herein
(``offene_frage``/``erwartet_janein``/``erwartet_wahl``); dadurch landet eine
kurze Antwort ("Mueller", "der erste", "ja") sicher im richtigen Slot.

Power-Eingabe fuer gezielte Tests: ``#slot=wert`` setzt einen Slot direkt,
``#intent=buchen`` erzwingt einen Intent, ``#ja`` / ``#nein`` eine Bestaetigung.
"""

from __future__ import annotations

import re

from bianca.controller import anliegen as _anliegen
from bianca.controller import fuer_wen as _fuer_wen
from bianca.controller import wuensche as _wuensche
from bianca.controller.typen import Intent, Quelle, SemanticEvent, SlotValue

# --------------------------------------------------------------------------- #
# Intent-Schluesselwoerter (nur fuer den AufgabenSTART / -wechsel).
# --------------------------------------------------------------------------- #
_INTENT_WORT: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.NOTFALL, ("notfall", "notdienst", "notarzt", "lebensgefahr",
                      "zahn ausgeschlagen", "zahn rausgefallen")),
    (Intent.ABSCHIED, ("tschüss", "tschuess", "auf wiederhören", "auf wiederhoeren",
                       "wiedersehen", "ciao", "bis dann", "danke", "dankeschön",
                       "dankeschoen", "vielen dank")),
    (Intent.ANMELDUNG, ("anmeldung", "empfang", "rezeption", "rezeptiom",
                        "rezepzion", "rezeptionistin")),
    (Intent.VERSCHIEBEN, ("verschieben", "verlegen", "umbuchen",
                          "auf einen anderen termin", "termin ändern",
                          "termin aendern", "terminverschiebung", "verschiebung")),
    (Intent.ABSAGEN, ("absagen", "stornieren", "canceln", "termin löschen",
                      "termin loeschen", "termin streichen", "nicht kommen",
                      "termin absagen")),
    (Intent.AUSKUNFT, ("wann ist mein termin", "habe ich einen termin",
                       "welchen termin", "termin vergessen")),
    (Intent.VERBINDEN, ("verbinden", "durchstellen", "sprechen mit", "weiterleiten",
                        "mit dem arzt", "zum arzt", "zur ärztin", "zur aerztin",
                        "arzt sprechen", "doktor sprechen")),
    (Intent.DOKUMENT, ("rezept", "überweisung", "ueberweisung", "krankmeldung",
                       "krankschreibung", "attest")),
    (Intent.RUECKRUF, ("rückruf", "rueckruf", "zurückrufen", "zurueckrufen")),
    (Intent.BUCHEN, ("termin", "temin", "termine", "buchen", "vereinbaren", "ausmachen",
                     "brauche einen", "hätte gern", "haette gern", "hätte gerne",
                     "haette gerne", "möchte einen", "moechte einen",
                     "will einen", "brauch einen")),
]

_GRUSS = ("hallo", "guten tag", "guten morgen", "guten abend", "hi", "hey", "servus",
          "hallp", "halo")

# "rezept" darf "rezeption"/"rezeptiom" nie treffen (W-REZEPTION).
_REZEPT_RE = re.compile(r"\brezept(?!ion|iom|zion)\w*", re.I)
_PREFIX_NEIN = re.compile(r"^\s*(nein|n[oö]e?|nee)\b", re.I)
_PREFIX_JA = re.compile(r"^\s*(ja|genau|richtig|jup|gerne|ok|okay)\b", re.I)
_ANSTAND_SELBER = re.compile(
    r"\bfick\s*dich\b|\bverpiss\b|\barschloch\b|\bhure\b",
    re.I,
)
_ANSTAND_SCHIMPF = re.compile(
    r"bl[oö]de\s+kuh|halt\s+die\s+klappe|schei[sß]+.?ki",
    re.I,
)
_ANDERER_TASK = re.compile(
    r"(?:was\s+ist\s+mit\s+dem|und\s+(?:jetzt\s+)?(?:noch\s+)?"
    r"(?:der|die|das|f(?:ü|ue)r)|der\s+andere|die\s+andere|"
    r"anderen?\s+termin|zweiten?\s+termin|n[aä]chsten\s+termin)",
    re.I,
)
_DANKE_RE = re.compile(r"^\s*(vielen\s+)?dank(?:e|esch[öo]n)?\b", re.I)

# Dieselbe Personal-/Rollenliste wie Live-Bianca (weiterleiten._MENSCH_WORT).
_ANMELDUNG_RE = re.compile(
    r"(?:anmeldung|empfang|rezeption|rezeptiom|rezepzion|rezeptionistin|"
    r"mensch(?:en)?|person(?:en)?|mitarbeiter\w*|angestellte\w*|personal\b|"
    r"sekretariat|sekretär\w*|sekretaer\w*|sprechstundenh(?:ilfe|elfer\w*)|"
    r"kolleg\w*|buchhaltung|patientenannahme|annahme|verwaltung|abrechnung|"
    r"chef\w*|inhaber\w*|praxisleitung|boss|"
    r"(?:zahn)?arzthelfer\w*|praxishelfer\w*|helferin\b|\bmfa\b|\bzfa\b|"
    r"fachangestellte\w*|praxisteam|praxispersonal|praxismanag\w*)",
    re.I,
)
_JEMAND_RE = re.compile(
    r"\bmit\s+jemand\w*\s+(?:[\wäöüß]+\s+){0,3}?(?:sprechen|reden)\b|"
    r"\bjemand\w*\s+(?:persönlich\s+|persoenlich\s+)?(?:sprechen|erreichen)\b|"
    r"\bjemand\w*\s+ans?\s+(?:telefon|apparat)\b",
    re.I,
)
_MENSCH_WUNSCH_RE = re.compile(
    r"(?:nicht|kein)\s+mit\s+(?:der\s+|einer\s+)?(?:ki|künstlichen|kuenstlichen|digitalen)|"
    r"nicht\s+mit\s+(?:einer\s+|der\s+)?ki|"
    r"mit\s+(?:einem\s+)?(?:echten\s+|richtigen\s+)?menschen|"
    r"keinen?\s+(?:roboter|bot)\b|"
    r"mit\s+einem\s+menschen\s+(?:reden|sprechen)",
    re.I,
)
_ANMELD_FUZZY = (
    "anmeldung", "empfang", "rezeption", "mitarbeiter", "rezeptionistin",
)
_KEINER_RE = re.compile(
    r"\b(?:keiner|keine(?:r|s)?\s+davon|keiner\s+passt|passt\s+keiner|"
    r"keinen\s+(?:davon|termin)|nichts\s+davon|keine\s+davon)\b",
    re.I,
)
_ANDERER_TERMIN_RE = re.compile(
    r"noch\s+(?:einen\s+)?anderen|nicht\s+(?:der|dieser|den)\b|"
    r"\bder\s+andere\b|\beinen\s+anderen\b",
    re.I,
)
_UEBERTRAGEN_RE = re.compile(
    r"\b(?:uebertragen|übertragen|umschreiben|ums?schreiben)\b|"
    r"an\s+meiner\s+stelle|anstatt\s+auf\s+mich|statt\s+(?:auf\s+)?mich|"
    r"statt\s+mir|auf\s+meine[n]?\s+\w+\s+uebertrag",
    re.I,
)
_BESTAND_FILTER_RE = re.compile(
    r"habe\s+ich\s+(?:noch\s+)?(?:einen\s+)?(?:termin|anderen)|"
    r"keinen\s+plan\s+um|wei[sß]+\s+ich\s+nicht|"
    r"koennen\s+sie\s+(?:den|ihn)\s+nicht\s+finden|"
    r"sie\s+haben\s+doch\s+meine\s+daten",
    re.I,
)
_VORNAME_NACH_ROLLE = re.compile(
    r"(?:schwester|bruder|tochter|sohn|frau|mann|mutter|vater)\s+"
    r"([a-zäöüß]{2,20})\b",
    re.I,
)

_JA = {"ja", "jup", "jo", "genau", "richtig", "stimmt", "passt", "gerne", "ok",
       "okay", "korrekt", "jawohl", "klar", "yes"}
_NEIN = {"nein", "ne", "nö", "noe", "nicht", "falsch", "stimmt nicht", "lieber nicht", "no"}

_VERSICHERUNG = {
    "gesetzlich": "gesetzlich", "kasse": "gesetzlich", "gkv": "gesetzlich",
    "aok": "gesetzlich", "tk": "gesetzlich", "barmer": "gesetzlich",
    "privat": "privat", "pkv": "privat", "privatpatient": "privat",
}

# Besuchsgrund-Stichworte -> kanonischer Grund (nur fuers Testgespraech).
_GRUND = _wuensche._GRUND

_ORDINAL = {
    "erste": "1", "ersten": "1", "erster": "1", "eins": "1", "1": "1",
    "zweite": "2", "zweiten": "2", "zweiter": "2", "zwei": "2", "2": "2",
    "dritte": "3", "dritten": "3", "dritter": "3", "drei": "3", "3": "3",
    "letzte": "-1", "letzten": "-1", "frühere": "1", "frueher": "1", "früheste": "1",
}

_WOCHENTAG = ("montag", "dienstag", "mittwoch", "donnerstag", "freitag",
              "samstag", "sonntag")
_ZEIT_WORT = ("morgen", "übermorgen", "uebermorgen", "heute", "nächste woche",
              "naechste woche", "vormittag", "nachmittag", "früh", "frueh", "abend")


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


# --------------------------------------------------------------------------- #
# Power-Overrides (#slot=wert / #intent=... / #ja / #nein).
# --------------------------------------------------------------------------- #
def _overrides(text: str) -> tuple[dict[str, str], Intent | None, bool | None, str]:
    slots: dict[str, str] = {}
    intent: Intent | None = None
    janein: bool | None = None
    rest_teile: list[str] = []
    for tok in text.split():
        if not tok.startswith("#"):
            rest_teile.append(tok)
            continue
        body = tok[1:]
        if body in ("ja", "yes"):
            janein = True
        elif body in ("nein", "no"):
            janein = False
        elif "=" in body:
            k, v = body.split("=", 1)
            k = k.strip()
            v = v.replace("_", " ").strip()
            if k == "intent":
                try:
                    intent = Intent(v)
                except ValueError:
                    intent = None
            elif k:
                slots[k] = v
    return slots, intent, janein, " ".join(rest_teile)


# --------------------------------------------------------------------------- #
# Slot-Extraktion aus freiem Text.
# --------------------------------------------------------------------------- #
_BEHANDLER_STOP = {
    "der", "die", "das", "den", "dem", "einen", "einem", "einer", "ihnen", "uns",
    "doktor", "doktorin", "herrn", "frau", "termin", "sprechen", "reden",
    "verbinden", "durchstellen", "weiterleiten", "bitte", "einmal", "mal",
}


_SCHON_GESAGT_RE = re.compile(
    r"habe ich (?:doch |gerade |eben |schon )*(?:gesagt|genannt)|"
    r"ich habe (?:doch |gerade |eben |schon )*(?:gesagt|genannt)|"
    r"(?:gerade|eben|doch) gesagt|wei(?:ss|ß)t du doch",
    re.I,
)
_EGAL_RE = re.compile(
    r"\b(?:egal|rgal|irgendwen|irgendeinen)\b|"
    r"zu\s+keine[nm]r?|"
    r"keine[nm]r?\s+(?:bestimmten|arzt|behandler)|"
    r"wei(?:ss|ß)\s+nicht",
    re.I,
)


def _ist_egal_behandler(t: str) -> bool:
    if _EGAL_RE.search(t):
        return True
    return _hat(t, ("egal", "rgal"), 1)


def _schon_gesagt(t: str) -> bool:
    return bool(_SCHON_GESAGT_RE.search(t))


def _behandler(t: str) -> str:
    # Honorativ-/Praeposition-Kette ueberspringen: 'bei doktor petsas' -> Petsas.
    # Sprech-Verben sind KEINE Namen ('arzt sprechen' != Behandler 'Sprechen').
    if _ist_egal_behandler(t):
        return "egal"
    m = re.search(
        r"\b(?:dr\.?|doktor|bei|zu|arzt|ärztin|aerztin|herr|frau)"
        r"(?:\s+(?:dr\.?|doktor|doktorin|herr|frau))*"
        r"\s+([a-zäöüß]{3,})",
        t,
    )
    if m:
        wort = m.group(1)
        if wort not in _BEHANDLER_STOP and not _token_ist(wort, _SPRECH_VERB, 2):
            return wort.capitalize()
    return ""


def _besuchsgrund(t: str) -> str:
    return _wuensche.besuchsgrund(t)


def _wunschzeit(t: str) -> str:
    return _wuensche.wunschzeit(t)


def _telefon(t: str) -> str:
    ziffern = re.sub(r"[^\d]", "", t)
    return ziffern if len(ziffern) >= 6 else ""


def _versicherung(t: str) -> str:
    for wort, kanon in _VERSICHERUNG.items():
        if re.search(rf"\b{re.escape(wort)}\b", t):
            return kanon
    return ""


def _wahl(t: str) -> str:
    if re.search(
        r"\b(?:alle|beide|s(?:ae|ä)mtliche)\b",
        t,
    ) and (
        re.search(r"absag|stornier|cancel|termine?", t)
        or re.fullmatch(r"\s*(?:bitte\s+)?(?:alle|beide)\s*[.!]?\s*", t)
    ):
        return "alle"
    for wort, idx in _ORDINAL.items():
        if re.search(rf"\b{re.escape(wort)}\b", t):
            return idx
    return ""


def _korrektur_feld(t: str) -> str:
    if re.search(r"\b(nein|falsch|nicht|aendern|ändern|statt|sondern)\b", t):
        if re.search(r"\b(nachname|heiße|heisse|name)\b", t):
            return "nachname"
        if re.search(r"\bvorname\b", t):
            return "vorname"
        if re.search(r"\b(nummer|telefon|handy)\b", t):
            return "telefon"
        if re.search(r"\b(behandler|arzt|doktor|dr\.?)\b", t):
            return "behandler"
        if re.search(r"\b(grund|besuchsgrund|wegen)\b", t):
            return "besuchsgrund"
        if re.search(r"\b(versicher|kasse|privat|gesetzlich)\b", t):
            return "versicherung"
        gefunden = _wuensche.feld_name(t)
        if gefunden:
            return gefunden
    return _wuensche.feld_allein(t)


def _wort_drin(nadel: str, heu: str) -> bool:
    """Einzelwort an der Wortgrenze, Mehrwort-Phrase als Teilstring."""
    if " " in nadel:
        return nadel in heu
    return bool(re.search(rf"(?<!\w){re.escape(nadel)}(?!\w)", heu))


def _falt(s: str) -> str:
    return (
        s.lower()
        .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    )


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 2:
        return 99
    vor = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        jetzt = [i]
        for j, cb in enumerate(b, 1):
            jetzt.append(min(vor[j] + 1, jetzt[j - 1] + 1, vor[j - 1] + (ca != cb)))
        vor = jetzt
    return vor[-1]


_SPRECH_VERB = ("sprechen", "reden", "verbinden", "durchstellen", "weiterleiten")
_ARZT_WORT = ("arzt", "aerztin", "doktor", "doktorin", "dr")
_NOTFALL_WORT = (
    "notfall", "notdienst", "notarzt", "lebensgefahr",
)
_HILFE_WORT = ("hilfe", "help", "helfen")
_GRUSS_WORT = ("hallo", "hi", "hey", "servus", "moin")


def _token_ist(wort: str, kandidaten: tuple[str, ...], dist: int) -> bool:
    w = _falt(wort)
    if w in kandidaten:
        return True
    if len(w) < 4:
        return False
    return any(_lev(w, k) <= dist for k in kandidaten if abs(len(w) - len(k)) <= dist)


def _toks(t: str) -> list[str]:
    return re.findall(r"[a-zäöüß]+", t)


def _hat(t: str, kandidaten: tuple[str, ...], dist: int = 1) -> bool:
    return any(_token_ist(w, kandidaten, dist) for w in _toks(t))


def _verbinden_arzt(t: str) -> bool:
    """Arzt + Sprech-/Verbinde-Verb, auch Tippfehler ('arzt sorechen')."""
    toks = _toks(t)
    hat_arzt = any(_token_ist(w, _ARZT_WORT, 1) or _falt(w).startswith("doktor") for w in toks)
    hat_sprech = any(_token_ist(w, _SPRECH_VERB, 2) for w in toks)
    return bool(hat_arzt and hat_sprech)


def _ist_notfall(t: str) -> bool:
    if "akute haut" in t:
        return False
    if _hat(t, _NOTFALL_WORT, 1):
        return True
    if "zahn ausgeschlagen" in t or "zahn rausgefallen" in t or "zahn vorne rausgefallen" in t:
        return True
    if re.search(r"\b112\b", t):
        return True
    return False


def _anmeldung_text(t: str) -> bool:
    if _ANMELDUNG_RE.search(t) or _JEMAND_RE.search(t) or _MENSCH_WUNSCH_RE.search(t):
        return True
    return any(_token_ist(w, _ANMELD_FUZZY, 2) for w in _toks(t) if len(w) >= 6)


def _intent_aus_text(t: str) -> Intent | None:
    """Prioritaet wie Live: Notfall > Personal > Arzt > Aufgabe > Gruss/Hilfe."""
    if _ist_notfall(t):
        return Intent.NOTFALL
    if _anmeldung_text(t):
        return Intent.ANMELDUNG
    if _verbinden_arzt(t) or _hat(t, ("verbinden", "durchstellen", "weiterleiten"), 2):
        return Intent.VERBINDEN
    if re.search(r"\babsag\w*|\bstornier\w*|\bcancel\w*", t) and not re.search(
        r"verschieb|verleg|umbuch", t
    ):
        return Intent.ABSAGEN
    for intent, woerter in _INTENT_WORT:
        if intent in (Intent.ANMELDUNG, Intent.NOTFALL, Intent.VERBINDEN, Intent.ABSAGEN):
            continue
        for w in woerter:
            if intent == Intent.DOKUMENT and w == "rezept":
                if _REZEPT_RE.search(t):
                    return Intent.DOKUMENT
                continue
            if _wort_drin(w, t):
                return intent
            if intent == Intent.BUCHEN and w == "termin" and _hat(t, ("termin",), 1):
                return intent
    toks = _toks(t)
    if _hat(t, _HILFE_WORT, 1):
        return Intent.SMALLTALK
    if len(toks) <= 4 and any(_wort_drin(g, t) for g in _GRUSS):
        return Intent.SMALLTALK
    if len(toks) <= 2 and _hat(t, _GRUSS_WORT, 1):
        return Intent.SMALLTALK
    return None


def _schonmal(t: str) -> str:
    """Live W-SCHONMAL: Bestand vs. Neu, inkl. doppelter Verneinung."""
    if re.search(r"nicht\s+(?:das|zum|mein)\s+erste", t) or "kein neupatient" in t:
        return "ja"
    if re.search(r"(?:noch\s+nie|erste(?:s|n)?\s+mal|neupatient|bin neu|noch nicht da)", t):
        return "nein"
    if re.search(r"schon\s+(?:ein)?mal|bereits\s+(?:da|patient)|war schon", t):
        return "ja"
    return ""


def _freie_slots(t: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, fn in (
        ("behandler", _behandler),
        ("besuchsgrund", _besuchsgrund),
        ("wunschzeit", _wunschzeit),
        ("versicherung", _versicherung),
        ("telefon", _telefon),
        ("schonmal", _schonmal),
    ):
        v = fn(t)
        if v:
            out[name] = v
    rollen = _fuer_wen.deute_alle(t)
    if rollen:
        out["fuer_wen"] = rollen[0]
        if len(rollen) > 1:
            out["fuer_wen_mehr"] = ",".join(rollen[1:])
    if _KEINER_RE.search(t):
        out["angebot_nein"] = "1"
    if _UEBERTRAGEN_RE.search(t):
        out["uebertragen"] = "ja"
        m = _VORNAME_NACH_ROLLE.search(t)
        if m and "vorname" not in out:
            out["vorname"] = m.group(1).capitalize()
    if re.search(r"\b(?:umgezogen|umzug|wohnortwechsel|weggezogen)\b", t):
        out["absage_grund"] = "umzug"
        out.pop("besuchsgrund", None)
    if re.search(r"\b(?:alle|beide|s(?:ae|ä)mtliche)\b", t) and (
        re.search(r"absag|stornier|cancel|termine?", t)
        or re.fullmatch(r"\s*(?:bitte\s+)?(?:alle|beide)\s*[.!]?\s*", t)
    ):
        out["terminwahl"] = "alle"
        out.pop("suche_weiter", None)
    elif _ANDERER_TERMIN_RE.search(t) or _BESTAND_FILTER_RE.search(t):
        out["suche_weiter"] = "ja"
    return out


# --------------------------------------------------------------------------- #
# Haupteinstieg.
# --------------------------------------------------------------------------- #
def deuten(
    text: str,
    *,
    offene_frage: str = "",
    erwartet_janein: bool = False,
    erwartet_wahl: bool = False,
) -> SemanticEvent:
    """Getippten Text -> ``SemanticEvent`` (fuer das Test-Dock)."""
    roh = str(text or "")
    ov_slots, ov_intent, ov_janein, rest = _overrides(roh)
    t = _norm(rest)

    slots: dict[str, str] = {}
    bestaetigung: bool | None = ov_janein
    korrektur_feld = ""
    intent: Intent = Intent.UNKLAR

    # 1) Semantik aus echten Anrufen, dann Live-Prioritaet.
    sem_intent, sem_slots = _anliegen.deute(t)
    if sem_intent is not None:
        intent = sem_intent
        slots.update(sem_slots)
    else:
        text_intent = _intent_aus_text(t)
        if text_intent is not None:
            intent = text_intent

    # 2) Korrektur (W-EINWAND): "nein, ... heisst ...".
    kf = _korrektur_feld(t)
    dritter = _fuer_wen.deute(t)
    if kf and intent in (Intent.UNKLAR,) and not dritter:
        intent = Intent.KORREKTUR
        korrektur_feld = kf

    # 3) Ja/Nein — Drittperson ist kein Nein, AUSSER der Satz beginnt mit Ja/Nein
    # ("nein, und einen Termin für meinen Sohn").
    if bestaetigung is None:
        if _PREFIX_NEIN.search(t):
            bestaetigung = False
        elif dritter and _PREFIX_JA.search(t):
            bestaetigung = True
        elif not dritter:
            worte = set(t.split())
            if erwartet_janein or (worte and worte <= (_JA | _NEIN)):
                if t in _JA or worte & _JA and not (worte & _NEIN):
                    bestaetigung = True
                elif t in _NEIN or worte & _NEIN:
                    bestaetigung = False

    # Offene Schonmal-Frage: Ja/Nein landet im Slot (auch vor einem Personenwechsel).
    if offene_frage == "schonmal" and "schonmal" not in slots:
        if bestaetigung is True and not (dritter and not _PREFIX_JA.search(t)):
            slots["schonmal"] = "ja"
        elif bestaetigung is False:
            slots["schonmal"] = "nein"

    if _ANDERER_TASK.search(t) and intent == Intent.VERSCHIEBEN:
        if not re.search(r"verschieb|verleg|umbuch", t):
            intent = Intent.UNKLAR
            slots["weiterer_task"] = "1"
    elif _ANDERER_TASK.search(t) and intent in (Intent.UNKLAR, Intent.SMALLTALK):
        slots["weiterer_task"] = "1"

    if _DANKE_RE.search(t) and intent == Intent.UNKLAR:
        intent = Intent.ABSCHIED

    # 4) Terminwahl im Angebot.
    if erwartet_wahl:
        w = _wahl(t)
        if w:
            slots["terminwahl"] = w

    # 4b) Bestandstermin beschreiben ist kein Aufgabenwechsel.
    if intent == Intent.BUCHEN and (
        _UEBERTRAGEN_RE.search(t) or _ANDERER_TERMIN_RE.search(t)
        or _BESTAND_FILTER_RE.search(t)
    ):
        if not re.search(r"neu(?:en)?\s+termin|vereinbar|haette\s+gern|hätte\s+gern", t):
            intent = Intent.UNKLAR
    if _UEBERTRAGEN_RE.search(t) and intent in (Intent.UNKLAR, Intent.SMALLTALK, Intent.BUCHEN):
        intent = Intent.UNKLAR
    if _ANDERER_TERMIN_RE.search(t) and bestaetigung is None:
        bestaetigung = False

    # 5) Freie Slot-Extraktion.
    slots.update(_freie_slots(t))
    if "zweit_anliegen" not in slots:
        slots.update(_anliegen.zwei_anliegen_slots(t))
    if slots.get("zweit_anliegen"):
        slots.pop("fuer_wen", None)
    if _ANSTAND_SELBER.search(t):
        slots["anstand"] = "selber"
    elif _ANSTAND_SCHIMPF.search(t):
        slots["anstand"] = "schimpf"

    # 6) Kurzantwort auf die offene Frage dem passenden Slot zuordnen.
    if offene_frage == "auskunft_klar":
        if intent in (Intent.DOKUMENT, Intent.ABSAGEN, Intent.VERSCHIEBEN,
                      Intent.RUECKRUF, Intent.ANMELDUNG, Intent.PRAXISINFO):
            pass
        else:
            art = _anliegen.auskunft_antwort(t)
            if art == "bestand":
                intent = Intent.AUSKUNFT
                slots["auskunft_art"] = "bestand"
            elif art == "neu":
                intent = Intent.BUCHEN
                slots["auskunft_art"] = "neu"
    if offene_frage == "anrufer_check":
        art = _anliegen.auskunft_antwort(t)
        if art == "bestand":
            intent = Intent.AUSKUNFT
            slots["auskunft_art"] = "bestand"
        elif art == "neu":
            intent = Intent.BUCHEN
            slots["auskunft_art"] = "neu"
    if offene_frage == "fach_weiter":
        if intent in (Intent.ABSAGEN, Intent.VERSCHIEBEN, Intent.AUSKUNFT, Intent.ANMELDUNG):
            pass
        elif bestaetigung is True or "rueckruf" in t:
            intent = Intent.RUECKRUF
        elif re.search(r"\btermin\b", t) and not re.search(r"verschieb|absag", t):
            intent = Intent.BUCHEN
    if offene_frage == "behandler" and _ist_egal_behandler(t):
        slots["behandler"] = "egal"
    if offene_frage == "termin_hinweis":
        w = _wunschzeit(t)
        if w:
            slots["termin_hinweis"] = w
        elif t and not bestaetigung and not dritter:
            slots["termin_hinweis"] = rest.strip()
    if offene_frage == "aenderung":
        kf = kf or _wuensche.feld_name(t) or _wuensche.feld_allein(t)
        if kf and intent in (Intent.UNKLAR, Intent.SMALLTALK, Intent.KORREKTUR):
            intent = Intent.KORREKTUR
            korrektur_feld = kf
    if offene_frage and offene_frage not in (
        "auswahl", "rueckruf_ja", "aenderung", "anmeldung_rueckruf",
        "anrufer_check", "auskunft_klar", "fach_weiter", "termin_hinweis",
        "arzt_notiz",
    ):
        if dritter:
            pass
        elif offene_frage not in slots and not bestaetigung and t and not korrektur_feld:
            if slots.get("anstand"):
                pass
            elif _schon_gesagt(t) and offene_frage in ("nachname", "vorname", "telefon"):
                pass
            elif offene_frage in ("nachname", "vorname", "ziel"):
                slots[offene_frage] = rest.strip().split(",")[0].title()
            elif offene_frage == "telefon":
                tel = _telefon(t)
                if tel:
                    slots[offene_frage] = tel
            elif offene_frage not in slots:
                slots.setdefault(offene_frage, rest.strip())

    # 7) Overrides gewinnen immer (Power-Testeingabe).
    if ov_intent is not None:
        intent = ov_intent
    slots.update(ov_slots)

    sv = {k: SlotValue(wert=v, quelle=Quelle.GESAGT) for k, v in slots.items() if v}
    return SemanticEvent(
        intent=intent,
        slots=sv,
        bestaetigung=bestaetigung,
        korrektur_feld=korrektur_feld,
        roh=roh[:120],
    )


__all__ = ["deuten"]
