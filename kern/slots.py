"""Wunsch-Parser und Slot-Auswahl — portiert aus MAS lisa/callBooking.js (pure)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from kern.sprech import slot_wort, tag_wort

TZ = ZoneInfo("Europe/Berlin")
WEEKDAYS = [
    (1, re.compile(r"\bmontags?(?=\b|vormittag|nachmittag|abend)")),
    (2, re.compile(r"\bdienstags?(?=\b|vormittag|nachmittag|abend)")),
    (3, re.compile(r"\bmittwochs?(?=\b|vormittag|nachmittag|abend)")),
    (4, re.compile(r"\bdonnerstags?(?=\b|vormittag|nachmittag|abend)")),
    (5, re.compile(r"\bfreitags?(?=\b|vormittag|nachmittag|abend)")),
    (6, re.compile(r"\bsamstags?(?=\b|vormittag|nachmittag|abend)")),
    (0, re.compile(r"\bsonntags?(?=\b|vormittag|nachmittag|abend)")),
]


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


# Zahlwort-Stunden fuer "zwölf Uhr fünfzehn" — live 27.08.2026: die Uhrzeit in
# Worten wurde gar nicht erkannt, der Wunsch "früher, so zwölf Uhr fünfzehn"
# lief als "vormittags" und bot nur andere Tage an.
_STUNDEN_WORT = {
    "ein": 1, "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
    "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11,
    "zwölf": 12, "zwoelf": 12, "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15,
    "fuenfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18,
    "neunzehn": 19, "zwanzig": 20, "einundzwanzig": 21, "zweiundzwanzig": 22,
    "dreiundzwanzig": 23,
}
_UHR_RE = re.compile(
    r"\b(?:(?:um|gegen|auf|ab)\s+)?(\d{1,2}|"
    + "|".join(sorted(_STUNDEN_WORT, key=len, reverse=True))
    + r")(?::(\d{2}))?\s*uhr\b",
    re.I,
)
_UHR_ZIFFER_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
# W-SUCHFENSTER (14.09.2026, Anruf 5aa87268: "heute um halb zwei"): Uhrzeiten
# OHNE das Wort "Uhr". "halb zwei" = 13:30 (Praxiszeit: Stunden unter 7 sind
# nachmittags). "um/gegen zwei" nur, wenn kein Zaehl-Hauptwort folgt ("um zwei
# Wochen", "gegen drei Termine").
_HALB_RE = re.compile(
    r"\bhalb\s+(\d{1,2}|" + "|".join(sorted(_STUNDEN_WORT, key=len, reverse=True)) + r")\b(?!\s*stunde)",
    re.I,
)
_UM_RE = re.compile(
    r"\b(?:um|gegen)\s+(\d{1,2}|" + "|".join(sorted(_STUNDEN_WORT, key=len, reverse=True)) + r")\b"
    r"(?!\s*(?::\d|uhr|tag|woche|monat|termin|stunde|minute|person|patient|jahr|prozent|euro|mal\b|z[äa]hn|kind|kilo|leute|st[üu]ck))",
    re.I,
)


def _praxis_stunde(h: int) -> int:
    """Stunde ohne 'Uhr' auf die Praxiszeit legen: 'um zwei' = 14, 'um neun' = 9."""
    return h + 12 if 0 < h < 7 else h


def _stunde_von(token: str) -> int | None:
    tok = token.strip().lower()
    if tok.isdigit():
        n = int(tok)
        return n if 0 <= n <= 23 else None
    return _STUNDEN_WORT.get(tok)


def parse_slot_wish(text: str) -> dict[str, Any] | None:
    raw = _s(text)
    if not raw:
        return None
    t = f" {raw.lower()} "
    wish: dict[str, Any] = {
        "weekday": None, "hourMin": None, "hourMax": None,
        "hour": None, "minDaysAhead": 0, "date": None, "tage": None,
        "von": None, "bis": None,
    }
    for idx, cre in WEEKDAYS:
        if cre.search(t):
            wish["weekday"] = idx
            break
    # Wortgrenzen: "früher"/"frühestens" ist ein RELATIVER Wunsch (vor dem
    # bestehenden Termin), KEINE Tageszeit — live 27.08.2026 wurde "früher"
    # als "vormittags 7-12" gedeutet und der Nachmittags-Slot fiel weg.
    if re.search(r"vormittag|morgens|\bfrüh\b|\bfrueh\b", t):
        wish["hourMin"], wish["hourMax"] = 7, 12
    elif "nachmittag" in t:
        wish["hourMin"], wish["hourMax"] = 12, 18
    elif re.search(r"abend|\bspaet\b|\bspät\b", t):
        wish["hourMin"], wish["hourMax"] = 16, 21
    if re.search(r"(?:uebernaechste|übernächste|übernaechste)[nrs]?\s+woche", t):
        wish["minDaysAhead"] = 14
    elif re.search(r"n[äa]chste[nrs]?\s+woche|kommende[nrs]?\s+woche", t):
        wish["minDaysAhead"] = 7
    # W-SUCHFENSTER (14.09.2026): "in drei Wochen", "in zwei Monaten",
    # "in vierzehn Tagen" — relativer Abstand statt "irgendwann".
    voraus = _voraus_tage(t)
    if voraus:
        wish["minDaysAhead"] = max(int(wish["minDaysAhead"] or 0), voraus)
    # Uhrzeit: Ziffern ("13:15", "um 9 Uhr") UND Zahlwörter ("zwölf Uhr zwanzig").
    # Bei "statt zwölf Uhr fünfundvierzig bitte zwölf Uhr zwanzig" zählt die
    # ZIEL-Zeit — Nennungen direkt nach "statt" werden übersprungen.
    stunde = None
    for m in _UHR_RE.finditer(t):
        davor = t[max(0, m.start() - 12):m.start()]
        if re.search(r"\bstatt\s*$", davor):
            continue
        h = _stunde_von(m.group(1))
        if h is not None:
            stunde = h
    if stunde is None:
        for m in _UHR_ZIFFER_RE.finditer(t):
            davor = t[max(0, m.start() - 12):m.start()]
            if re.search(r"\bstatt\s*$", davor):
                continue
            h = _stunde_von(m.group(1))
            if h is not None and 0 <= int(m.group(2)) <= 59:
                stunde = h
    if stunde is None:
        # "halb zwei" -> 13 (Slot-Filter arbeitet stundenweise, ±1 h).
        m = _HALB_RE.search(t)
        if m:
            h = _stunde_von(m.group(1))
            if h is not None:
                stunde = _praxis_stunde((h - 1) % 24)
    if stunde is None and not re.search(r"verschieb|umbuch|verleg", t):
        # "um zwei"/"gegen drei" ohne "Uhr" — nicht beim Verschieben (dort
        # gehoert eine nackte Zahl meist zum Bestandstermin, Luelf 08.09.2026).
        for m in _UM_RE.finditer(t):
            davor = t[max(0, m.start() - 12):m.start()]
            if re.search(r"\bstatt\s*$", davor):
                continue
            if _MONAT_WORT_RE.match(t[m.end():].lstrip(". ")):
                continue  # "um 3. Oktober" ist ein Datum, keine Uhrzeit
            h = _stunde_von(m.group(1))
            if h is not None and 0 < h <= 23:
                stunde = _praxis_stunde(h)
    if stunde is not None:
        wish["hour"] = stunde
    # "heute um 14 Uhr einen Termin … verschieben": die Uhr gehört zum
    # BESTANDSTERMIN, nicht zum Neu-Wunsch (Lülf 08.09.2026).
    if _bestand_uhr_im_satz(t) and not re.search(
            r"\b(?:auf|zu|lieber|geht(?:'s|s)?)\s+(?:um\s+)?\d", t):
        wish["hour"] = None
    datum = datum_aus_text(raw)
    tage = tage_aus_text(raw)
    if tage:
        wish["date"] = tage[0]
        if len(tage) > 1:
            wish["tage"] = tage
        wish["weekday"] = None
    elif datum:
        wish["date"] = datum
        wish["weekday"] = None
    else:
        # W-SUCHFENSTER (14.09.2026): "im Oktober", "Anfang November",
        # "nächsten Monat", "ab Dezember" — ein ZEITRAUM (von/bis), kein Tag.
        # Ein Wochentag darin bleibt stehen ("ein Donnerstag im Oktober").
        von, bis = zeitraum_aus_text(raw)
        if von or bis:
            wish["von"], wish["bis"] = von or None, bis or None
    return wish


# --- Harte Korrekturen auf ein bereits gesprochenes Angebot -----------------
# Blessing-Live 15.09.2026 (50563be8): „nicht Donnerstag“ wurde sechs Mal
# verstanden und trotzdem erneut als Donnerstag angeboten; „elf Uhr ist
# Vormittag, bitte Nachmittag“ wurde sogar als Zusage für 11:15 gelesen.
_WOCHENTAG_NAME = {
    1: "Montag", 2: "Dienstag", 3: "Mittwoch", 4: "Donnerstag",
    5: "Freitag", 6: "Samstag", 0: "Sonntag",
}
# W-SLOT-ABLEHNUNG (17.09.2026, A6 aus BEFUND-BIANCA-ALLE-ANRUFE): die Wache
# gilt jetzt fuer ALLE Mandanten (vorher nur Blessing). Die Negation darf
# Fuellwoerter ueberspringen ("nicht am Donnerstag", "geht's leider nicht"),
# aber KEINE beliebigen Woerter: "Donnerstag passt mir gut aber Freitag nicht"
# darf Donnerstag nicht negieren — deshalb Whitelists statt Wildcards.
_NEG_FUELLER = (
    r"(?:am|an|der|den|dem|die|das|diesen|diese|dieser|so|ein|eine|einen|einem|"
    r"um|gegen|auf|zu|zum|zur|bitte|gern|gerne|halt|eben|leider|wirklich|"
    r"unbedingt|den\s+ganzen|die\s+ganze|ganze[nr]?|jeden|jede|immer|generell)"
)
_NEG_VOR_RE = re.compile(
    # "nicht (am) Donnerstag", "kein Donnerstag", "statt Donnerstag", "weder Donnerstag"
    r"(?:\bnicht|\bkein\w*|\bnie|\bohne|\bau(?:ß|ss)er|\bstatt|\banstatt|\bweder)"
    r"(?:\s+" + _NEG_FUELLER + r")*\s*$|"
    # "habe ich keine Zeit am Donnerstag", "bin ich nicht da am Donnerstag",
    # "kann ich nicht am Donnerstag", "geht nicht am Donnerstag"
    r"\b(?:hab\w*|haben)\s+(?:ich\s+|wir\s+)?(?:leider\s+)?keine\s+zeit\s+(?:am\s+|an\s+)?$|"
    r"\b(?:bin|sind)\s+(?:ich|wir)\s+(?:leider\s+)?(?:nicht\s+da|nicht|verhindert|unterwegs|"
    r"im\s+urlaub|weg)\s+(?:am\s+|an\s+)?$|"
    r"\b(?:kann|k(?:ö|oe)nnen|k(?:ö|oe)nnte)\s+(?:ich|wir)\s+(?:leider\s+)?nicht\s+(?:am\s+|an\s+)?$|"
    r"\b(?:geht|passt|klappt)(?:'?s)?\s+(?:mir\s+|leider\s+|bei\s+mir\s+)*nicht\s+(?:am\s+|an\s+)?$",
    re.I,
)
# Positives Signal direkt HINTER dem Tag hebt eine Vor-Negation auf, die
# eigentlich zum vorigen Tag gehoerte: "Donnerstag nicht, Freitag schon".
# Eine Tages-/Zeit-/Ordnungs-Nennung, wie sie einem "nicht" oder "lieber"
# folgen kann ("nicht um elf", "lieber der zweite", "aber nicht Donnerstag").
_NENNUNG_DANACH = (
    r"(?:am\s+|an\s+|um\s+|gegen\s+|der\s+|den\s+|die\s+|das\s+|ein\s+|eine\s+|einen\s+|so\s+)?"
    r"(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|heute|morgen\b|"
    r"(?:ü|ue)bermorgen|erste[rns]?\b|zweite[rns]?\b|dritte[rns]?\b|letzte[rns]?\b|"
    r"\d|halb\b|viertel\b|vormittag|nachmittag|abend|fr(?:ü|ue)h\b|sp(?:ä|ae)t\b|"
    r"n(?:ä|ae)chste|"
    # Zahlwoerter ("lieber um zwei", "besser elf Uhr") zaehlen wie Ziffern.
    r"(?:" + "|".join(sorted(_STUNDEN_WORT, key=len, reverse=True)) + r")\b)"
)
_POS_NACH_RE = re.compile(
    r"^[\s,]*(?:schon|gern(?:e)?|passt|geht|klappt|super|prima|perfekt|ja|okay|ok|gut|"
    # "lieber/besser <andere Nennung>" gehoert zur NAECHSTEN Nennung
    # ("nicht um elf, lieber um zwei" — die elf bleibt negiert).
    r"(?:lieber|besser|am\s+besten)(?!\s+" + _NENNUNG_DANACH + r")|"
    r"w(?:ä|ae)re\s+(?:gut|super|prima|perfekt|ok|okay|besser|toll|sch(?:ö|oe)n)|"
    r"ist\s+(?:gut|super|prima|perfekt|ok|okay|besser|toll|sch(?:ö|oe)n))\b(?!\s+(?:mir\s+|leider\s+|bei\s+mir\s+)*(?:gar\s+)?nicht\b)",
    re.I,
)
# Was hinter einem "nicht" den Tag NICHT ausschliesst: "Donnerstag nicht vor
# zwoelf" / "nicht so frueh" / "nicht nachmittags" meint den Tag sehr wohl —
# nur eine Tageszeit/Uhrzeit daran ist unerwuenscht.
_NICHT_TEIL = (
    r"nicht\b(?!\s+(?:vor|nach|um|ab|bis|erst|so\s+(?:fr(?:ü|ue)h|sp(?:ä|ae)t)|"
    r"zu\s+(?:fr(?:ü|ue)h|sp(?:ä|ae)t)|sp(?:ä|ae)ter|fr(?:ü|ue)her|"
    r"(?:vor|nach)mittags?|morgens|abends|mehr\s+(?:vor|nach|um|ab))\b)"
)
_NACH_FUELLER = (
    r"(?:mir|uns|ich|wir|es|das|da|dann|leider|bei\s+mir|bei\s+uns|eigentlich|"
    r"wirklich|auch|so|halt|eben|irgendwie|(?:ü|ue)berhaupt|ganz|gar|jetzt|noch|"
    r"wohl|eher|generell|grunds(?:ä|ae)tzlich|meistens|immer|ehrlich\s+gesagt|"
    r"wahrscheinlich|vermutlich|definitiv|auf\s+keinen\s+fall|auf\s+gar\s+keinen\s+fall)"
)
_NEG_NACH_RE = re.compile(
    # "geht nicht", "geht's leider nicht", "passt mir überhaupt nicht", "kann ich nicht"
    r"^[\s,?!.]*(?:geht|passt|klappt|funktioniert|kommt|kann\w*|k(?:ö|oe)nnte\w*|"
    r"schaff\w*|w(?:ü|ue)rde|m(?:ö|oe)chte|will|mag)(?:'?s)?"
    r"(?:\s+" + _NACH_FUELLER + r")*\s+(?:gar\s+|leider\s+)*" + _NICHT_TEIL + r"|"
    # "ist schlecht/ungünstig/blöd/schwierig/unmöglich", "wäre ganz falsch"
    r"^[\s,?!.]*(?:ist|w(?:ä|ae)re|geht)(?:\s+(?:ganz|sehr|leider|eher|total|echt|wirklich))*"
    r"\s+(?:falsch|schlecht|ung(?:ü|ue)nstig|bl(?:ö|oe)d|schwierig|unm(?:ö|oe)glich|"
    r"ausgeschlossen|doof|schlimm|ungut|unpassend)\b|"
    # "scheidet aus", "fällt aus/weg/flach"
    r"^[\s,?!.]*(?:scheidet|f(?:ä|ae)llt)(?:\s+leider)?\s+(?:aus|weg|flach)\b|"
    # "bin ich nicht da", "habe ich keine Zeit", "bin ich verhindert/unterwegs/im Urlaub"
    r"^[\s,?!.]*(?:bin|sind|hab\w*|haben)(?:\s+(?:ich|wir|da|dann|leider|noch))*"
    r"\s+(?:nicht\s+da|nicht\b|keine\s+zeit|verhindert|unterwegs|im\s+urlaub|weg|arbeiten|"
    r"beim\s+arzt|in\s+der\s+arbeit|auf\s+der\s+arbeit|nicht\s+in\s+der\s+stadt|"
    r"nicht\s+zu\s+hause|nicht\s+im\s+land)\b|"
    # "Donnerstag nicht", "Donnerstag lieber nicht", "Donnerstag auf keinen
    # Fall", "Donnerstag ungern/schlecht" — OHNE Komma/„aber“ bindet das
    # "nicht" nach hinten ("Donnerstag nicht Freitag" = Donnerstag weg).
    r"^[\s?!.]*(?:(?:leider|bitte|lieber|eher|gar|dann|halt|eben|wirklich|auch)\s+)*"
    r"(?:" + _NICHT_TEIL + r"|auf\s+(?:gar\s+)?keinen\s+fall\b|ungern\b|schlecht\b|"
    r"ung(?:ü|ue)nstig\b|bl(?:ö|oe)d\b|schwierig\b|unm(?:ö|oe)glich\b)|"
    # "Donnerstag, nicht" / "Donnerstag aber nicht" — MIT Komma oder „aber“
    # beginnt ein neuer Teilsatz: folgt dort ein Tag/eine Zeit/eine
    # Ordnungszahl, gehoert das "nicht" ZU DIESER Nennung ("Freitag, aber
    # nicht Donnerstag" sperrt den Donnerstag, nicht den Freitag).
    r"^[\s,?!.]*(?:(?:aber|leider|bitte|lieber|eher|gar|dann|halt|eben|wirklich|auch)\s+)*"
    r"(?:" + _NICHT_TEIL + r"(?!\s+" + _NENNUNG_DANACH + r")"
    r"|auf\s+(?:gar\s+)?keinen\s+fall\b|ungern\b|schlecht\b|"
    r"ung(?:ü|ue)nstig\b|bl(?:ö|oe)d\b|schwierig\b|unm(?:ö|oe)glich\b)|"
    r"^[\s,?!.]*(?:nein|nee|n(?:ö|oe))\b|"
    r"^.{0,42}\b(?:ganztagsschule|ganztagschule|doppelschule|lange\s+schule)\b",
    re.I,
)
# Alles Angebotene abgelehnt: "keiner davon", "passt alles nicht", "die drei
# gehen alle nicht", "weder noch", "nichts davon", "gar keiner".
_ALLE_ABGELEHNT_RE = re.compile(
    r"\b(?:kein(?:er|e|s|en)?|nichts|nix)\s+(?:davon|der\s+(?:drei|zwei|termine|zeiten|"
    r"vorschl(?:ä|ae)ge)|von\s+(?:den|denen|beiden|allen|diesen))\b|"
    r"\b(?:gar\s+|leider\s+|ehrlich\s+gesagt\s+)?kein(?:er|e|s)\s+(?:passt|geht|klappt)\b|"
    r"\b(?:die|alle|beide|die\s+drei|die\s+zwei|alle\s+drei|alle\s+zwei|alles)\s+"
    r"(?:passen|passt|gehen|geht|klappen|klappt)\s+(?:mir\s+|bei\s+mir\s+|leider\s+)*"
    r"(?:alle\s+|beide\s+|alles\s+)?nicht\b|"
    r"\bweder\s+noch\b|\bnichts\s+passt\b|\bpasst\s+(?:mir\s+)?(?:alles|beides)\s+nicht\b|"
    r"\b(?:alle|beide|alle\s+drei)\s+(?:sind\s+)?(?:schlecht|ung(?:ü|ue)nstig|unm(?:ö|oe)glich)\b|"
    r"\b(?:ganz\s+)?andere\s+(?:zeiten|termine|vorschl(?:ä|ae)ge)\b|\b(?:was|etwas)\s+anderes\b",
    re.I,
)
# Das Angebot abgelehnt ("Nein.", "Das passt nicht.", "Geht nicht.") — ohne
# Gegenvorschlag im selben Satz (kein Tag, keine Uhrzeit, keine Ordnungszahl,
# kein "lieber ..."). Bei mehreren Slots heisst das: keiner davon.
_EINZEL_ABGELEHNT_RE = re.compile(
    r"^[\s,]*(?:nein|nee|n(?:ö|oe))\b(?![\s,]*(?:lieber|eher|am|um|der|den|die|das\s+w(?:ä|ae)re|"
    r"ich\s+(?:m(?:ö|oe)chte|h(?:ä|ae)tte|w(?:ü|ue)rde|nehme|will)|dann|doch|\d|halb|viertel|"
    r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|morgen|heute|"
    r"(?:ü|ue)bermorgen|vormittag|nachmittag|abend|fr(?:ü|ue)h|sp(?:ä|ae)t))|"
    r"^[\s,]*(?:nein[\s,]+|nee[\s,]+)?(?:das|der|die|dieser|diese|den|er|sie|es)?\s*"
    r"(?:passt|geht|klappt|ist)(?:'?s)?\s+(?:mir\s+|leider\s+|bei\s+mir\s+|eigentlich\s+)*"
    r"(?:gar\s+|(?:ü|ue)berhaupt\s+)?(?:nicht|schlecht|ung(?:ü|ue)nstig|bl(?:ö|oe)d|"
    r"unm(?:ö|oe)glich|zu\s+(?:fr(?:ü|ue)h|sp(?:ä|ae)t))\b",
    re.I,
)
_ANDERER_TAG_RE = re.compile(
    r"\b(?:ein(?:en)?\s+)?ander(?:er|en|e)\s+(?:tag|wochentag)\b|"
    r"\bnicht\s+diese[rmn]?\s+tag\b|"
    r"\b(?:ein(?:en)?\s+)?ander(?:er|en|e)\s+woche\b",
    re.I,
)
# "morgens" ist eine Tageszeit, "morgen" (ohne "am") ist der TAG danach —
# "morgen geht nicht" darf nie alle Vormittage sperren (A6, 17.09.2026).
_TAGESZEIT_RE = re.compile(
    r"(?:\b|(?<=tag))((?:vormittag\w*|morgens|fr(?:ü|ue)h|nachmittag\w*|abends?|sp(?:ä|ae)t)\b"
    r"|(?<=\bam\s)morgen\b)",
    re.I,
)
# Relativer Tag ("morgen geht nicht", "heute nicht", "übermorgen passt nicht")
# — nicht "am Morgen" (Tageszeit), nicht "Guten Morgen" (Gruss).
_REL_TAG_RE = re.compile(
    r"(?<!am\s)(?<!guten\s)(?<!am\snächsten\s)(?<!am\snaechsten\s)"
    r"\b(heute|(?:ü|ue)bermorgen|morgen)\b(?!s\b)",
    re.I,
)
_ORDINAL_RE = re.compile(
    r"\b(erste[rns]?|ersteren|zweite[rns]?|dritte[rns]?|letzte[rns]?)\b(?:\s+(?:termin|zeit|vorschlag|uhrzeit|option|m(?:ö|oe)glichkeit))?",
    re.I,
)
_ORDINAL_INDEX = {"erst": 0, "zweit": 1, "dritt": 2, "letzt": -1}


def _tageszeit_bereich(wort: str) -> tuple[int, int]:
    low = wort.casefold()
    if "nachmittag" in low:
        return 12, 18
    if "abend" in low or low.startswith(("spät", "spaet")):
        return 16, 21
    return 7, 12


def _negiert(t: str, start: int, end: int, verbraucht: list | None = None) -> bool:
    """Ist die Nennung t[start:end] negiert?

    Reihenfolge: Nach-Negation ("Donnerstag geht nicht") schlaegt alles; ein
    positives Signal dahinter ("Freitag schon") hebt eine Vor-Negation auf;
    sonst zaehlt die Vor-Negation ("nicht am Donnerstag"). Ein "nicht", das
    schon als Nach-Negation des VORIGEN Tags verbraucht wurde, negiert den
    naechsten Tag nicht mehr ("Donnerstag nicht Freitag" = Freitag positiv).
    ``verbraucht`` sammelt diese Spannen ueber alle Nennungen eines Satzes.
    """
    danach = t[end:end + 60]
    m = _NEG_NACH_RE.search(danach)
    if m:
        if verbraucht is not None:
            verbraucht.append((end + m.start(), end + m.end()))
        return True
    if _POS_NACH_RE.match(danach):
        return False
    davor_ab = max(0, start - 44)
    davor = t[davor_ab:start]
    m = _NEG_VOR_RE.search(davor)
    if not m:
        return False
    pos = davor_ab + m.start()
    if verbraucht and any(a <= pos < b for a, b in verbraucht):
        return False
    return True


_VERBUND_ZWISCHEN_RE = re.compile(
    r"^(?:[\s,\-]|nicht|am|nur|so|dann|auch|eher|aber|und|der|den|dem|die|das|"
    r"lieber|bitte|leider|jeweils|immer|meist(?:ens)?|ist|w(?:ä|ae)re|schon)*$",
    re.I,
)


def _im_verbund(t: str, tag_ende: int, zeit_start: int) -> bool:
    """„Donnerstag Nachmittag“ / „morgen früh“: Tag + Tageszeit gehoeren zusammen,
    wenn dazwischen nur Fuellwoerter stehen."""
    if zeit_start < tag_ende or zeit_start - tag_ende > 24:
        return False
    return bool(_VERBUND_ZWISCHEN_RE.match(t[tag_ende:zeit_start]))


def _relativer_tag(wort: str, heute: date | None = None) -> str:
    h = heute or datetime.now(TZ).date()
    low = wort.casefold()
    if low.startswith(("über", "ueber")):
        return (h + timedelta(days=2)).isoformat()
    if low == "morgen":
        return (h + timedelta(days=1)).isoformat()
    return h.isoformat()


def slot_praeferenz_aenderung(
    text: str,
    offered_isos: list[str] | None = None,
    heute: date | None = None,
) -> dict[str, Any] | None:
    """Harte Ablehnung/Präferenz aus einem laufenden Slotangebot lesen.

    Reine Auswahl („Montag“, „der zweite“) bleibt dem vorhandenen Slot-Wähler
    (Rueckgabe None). Diese Funktion greift erst bei Ablehnung, mehreren
    Alternativtagen oder einer ausdrücklichen Tageszeit-Korrektur.

    A6 (17.09.2026, alle Mandanten): versteht zusaetzlich
    - relative Tage: „morgen geht nicht“ -> ``excludeDates`` (nie „morgens“),
    - Tag+Tageszeit im Verbund: „Donnerstag Nachmittag nicht“, „morgen frueh
      geht nicht“ -> ``excludeSpans`` (der Tag selbst bleibt erlaubt),
    - Ordnungszahlen auf das Angebot: „der erste nicht“ -> ``excludeIsos``,
      „der erste nicht, der zweite“ -> zusaetzlich ``waehle`` (ISO),
    - Alles-Ablehnung: „keiner davon“, „passt alles nicht“, „andere Zeiten“
      und — solange ein Angebot offen ist — ein Nein OHNE Gegenvorschlag
      („Nein.“, „Das passt nicht.“, „Geht nicht.“) -> ``rejectAll`` plus
      alle angebotenen ISOs in ``excludeIsos``. „Nein, lieber Donnerstag“
      und „Nein, der zweite“ sind KEINE Alles-Ablehnung.
    """
    raw = _s(text)
    if not raw:
        return None
    t = raw.casefold()
    offered = [str(x) for x in (offered_isos or []) if x]
    verbraucht: list[tuple[int, int]] = []

    # Nennungen in Textreihenfolge, damit ein verbrauchtes "nicht" den
    # naechsten Tag nicht mitnegiert ("Donnerstag nicht Freitag").
    tage_nennungen: list[tuple[int, int, str, Any]] = []  # (start, end, art, wert)
    for idx, cre in WEEKDAYS:
        for m in cre.finditer(t):
            tage_nennungen.append((m.start(), m.end(), "wd", idx))
    for m in _REL_TAG_RE.finditer(t):
        tage_nennungen.append((m.start(), m.end(), "date", _relativer_tag(m.group(1), heute)))
    # Absolute Tage ("nicht am 3. Oktober", "der 10. geht nicht", "am 15.09
    # nicht") laufen durch dieselbe Negations-Logik wie Wochentage.
    for start, end, iso in _datum_nennungen(t, heute):
        if not any(s <= start < e for s, e, _a, _w in tage_nennungen):
            tage_nennungen.append((start, end, "date", iso))
    tage_nennungen.sort(key=lambda x: x[0])

    tage_neg: dict[int, bool] = {}
    for start, end, _art, _wert in tage_nennungen:
        tage_neg[start] = _negiert(t, start, end, verbraucht)

    tageszeiten: list[tuple[int, int, int, int, bool]] = []  # (start, end, lo, hi, neg)
    for m in _TAGESZEIT_RE.finditer(t):
        lo, hi = _tageszeit_bereich(m.group(1))
        tageszeiten.append((m.start(), m.end(), lo, hi, _negiert(t, m.start(), m.end(), verbraucht)))

    # Verbund Tag + Tageszeit: "Donnerstag Nachmittag nicht" sperrt NUR den
    # Donnerstagnachmittag; der Tag zaehlt dann weder positiv noch negativ.
    verbund_tage: set[int] = set()
    verbund_zeiten: set[int] = set()
    spans: list[dict[str, Any]] = []
    for zs, _ze, lo, hi, zneg in tageszeiten:
        partner = None
        for start, end, art, wert in tage_nennungen:
            if end <= zs and _im_verbund(t, end, zs):
                partner = (start, art, wert)
        if partner is None or not zneg:
            continue
        pstart, art, wert = partner
        if tage_neg.get(pstart):
            continue  # "nicht Donnerstag nachmittags" — der ganze Tag ist schon weg
        verbund_tage.add(pstart)
        verbund_zeiten.add(zs)
        spans.append({"weekday" if art == "wd" else "date": wert, "lo": lo, "hi": hi})

    positiv: list[int] = []
    negativ: list[int] = []
    pos_daten: list[str] = []
    neg_daten: list[str] = []
    genannte_wd = {int(w) for _s0, _e0, a, w in tage_nennungen if a == "wd"}
    vorkommen = 0
    for start, _end, art, wert in tage_nennungen:
        if start in verbund_tage:
            continue
        neg = tage_neg.get(start, False)
        if art == "wd":
            vorkommen += 1
            (negativ if neg else positiv).append(int(wert))
        else:
            # "Donnerstag, der 10." ist EIN Tag, nicht zwei Alternativen —
            # sonst wuerde die reine Auswahl eines Angebots als Neusuche gelesen.
            try:
                wd_des_datums = date.fromisoformat(str(wert)).isoweekday()
            except ValueError:
                wd_des_datums = None
            if wd_des_datums not in genannte_wd:
                vorkommen += 1
            (neg_daten if neg else pos_daten).append(str(wert))

    neg_bereiche = [(lo, hi) for zs, _ze, lo, hi, neg in tageszeiten if neg and zs not in verbund_zeiten]
    pos_bereiche = [(zs, lo, hi) for zs, _ze, lo, hi, neg in tageszeiten if not neg]

    ausgeschlossen_stunden: list[int] = []
    # Positive Stunden ("nicht um elf, lieber um zwei" -> 14) wandern als
    # Wunsch-Stunde mit, sonst ginge der Gegenvorschlag in der Neusuche verloren.
    pos_stunden: list[tuple[int, int, int | None]] = []  # (start, stunde, minute)
    uhr_spannen: list[tuple[int, int]] = []
    for m in _UHR_RE.finditer(t):
        h = _stunde_von(m.group(1))
        uhr_spannen.append((m.start(), m.end()))
        if h is None:
            continue
        if _negiert(t, m.start(), m.end(), verbraucht):
            ausgeschlossen_stunden.append(_praxis_stunde(h))
        else:
            pos_stunden.append((m.start(), _praxis_stunde(h), int(m.group(2)) if m.group(2) else None))
    for m in _UHR_ZIFFER_RE.finditer(t):
        h = _stunde_von(m.group(1))
        uhr_spannen.append((m.start(), m.end()))
        if h is None:
            continue
        if _negiert(t, m.start(), m.end(), verbraucht):
            ausgeschlossen_stunden.append(_praxis_stunde(h))
        else:
            pos_stunden.append((m.start(), _praxis_stunde(h), int(m.group(2))))
    # Uhrzeiten OHNE "Uhr" wie im Wunsch-Parser (W-SUCHFENSTER): "aber nicht
    # um elf", "halb zwei geht nicht". Treffer, die schon als "elf Uhr" gezaehlt
    # wurden, nicht doppelt.
    def _schon(a: int, b: int) -> bool:
        return any(a < e and b > s for s, e in uhr_spannen)

    for m in _HALB_RE.finditer(t):
        if _schon(m.start(), m.end()):
            continue
        h = _stunde_von(m.group(1))
        if h is None:
            continue
        if _negiert(t, m.start(), m.end(), verbraucht):
            ausgeschlossen_stunden.append(_praxis_stunde((h - 1) % 24))
        else:
            pos_stunden.append((m.start(), _praxis_stunde((h - 1) % 24), 30))
    for m in _UM_RE.finditer(t):
        if _schon(m.start(), m.end()):
            continue
        if _MONAT_WORT_RE.match(t[m.end():].lstrip(". ")):
            continue  # "um 3. Oktober" ist ein Datum
        h = _stunde_von(m.group(1))
        if h is None or not 0 < h <= 23:
            continue
        if _negiert(t, m.start(), m.end(), verbraucht):
            ausgeschlossen_stunden.append(_praxis_stunde(h))
        else:
            pos_stunden.append((m.start(), _praxis_stunde(h), None))
    pos_stunden = [x for x in pos_stunden if x[1] not in ausgeschlossen_stunden]

    exclude_isos: list[str] = []
    waehle = ""
    if offered:
        for m in _ORDINAL_RE.finditer(t):
            wort = m.group(1).casefold()
            idx = next((i for stamm, i in _ORDINAL_INDEX.items() if wort.startswith(stamm)), None)
            if idx is None:
                continue
            if idx == -1:
                idx = len(offered) - 1
            if idx >= len(offered):
                continue
            if _negiert(t, m.start(), m.end(), verbraucht):
                exclude_isos.append(offered[idx])
            else:
                waehle = offered[idx]

    # Ein Nein OHNE jede Richtung ("Nein.", "Passt nicht.") lehnt die ganze
    # Liste ab. Sobald der Satz etwas Konkretes traegt ("Nein, nicht
    # Donnerstag", "Nein, lieber Freitag", "der erste nicht"), gilt NUR das
    # Konkrete — sonst flöge der Montag-Slot mit, den der Anrufer gar nicht
    # abgelehnt hat.
    spezifisch = bool(
        negativ or neg_daten or neg_bereiche or ausgeschlossen_stunden or spans
        or exclude_isos or positiv or pos_daten or pos_bereiche or waehle
    )
    reject_all = bool(_ALLE_ABGELEHNT_RE.search(t)) or (
        bool(offered) and not spezifisch and bool(_EINZEL_ABGELEHNT_RE.search(t))
    )
    if reject_all and offered:
        exclude_isos.extend(x for x in offered if x not in exclude_isos)

    anderer_tag = bool(_ANDERER_TAG_RE.search(t))
    # „11.15 ist Vormittag, bitte Nachmittag“: kein grammatisches „nicht“,
    # aber die letzte Tageszeit ist die ausdrückliche Korrektur.
    tageszeit_korrektur = len({(lo, hi) for _zs, _ze, lo, hi, _n in tageszeiten}) > 1
    aenderung = bool(
        negativ or neg_bereiche or ausgeschlossen_stunden or anderer_tag
        or vorkommen > 1 or tageszeit_korrektur or neg_daten or spans
        or exclude_isos or reject_all
    )
    if not aenderung:
        return None

    out: dict[str, Any] = {"andererTag": anderer_tag}
    if negativ:
        out["excludeWeekdays"] = sorted(set(negativ))
    erlaubt = sorted(set(positiv) - set(negativ))
    if erlaubt:
        out["weekdays"] = erlaubt
    if pos_daten:
        out["date"] = pos_daten[-1]
    if neg_daten:
        out["excludeDates"] = sorted(set(neg_daten))
    if spans:
        out["excludeSpans"] = spans
    if neg_bereiche:
        out["excludeHourRanges"] = sorted(set(neg_bereiche))
    if ausgeschlossen_stunden:
        out["excludeHours"] = sorted(set(ausgeschlossen_stunden))
    if pos_bereiche:
        _zs, lo, hi = max(pos_bereiche, key=lambda x: x[0])
        out["hourMin"], out["hourMax"] = lo, hi
    if pos_stunden and not pos_bereiche:
        _ps, h, minute = max(pos_stunden, key=lambda x: x[0])
        out["hour"] = h
        if minute is not None:
            out["minute"] = minute
    if exclude_isos:
        out["excludeIsos"] = sorted(set(exclude_isos))
    if waehle and waehle not in exclude_isos:
        out["waehle"] = waehle
    if reject_all:
        out["rejectAll"] = True
    return out


def wunsch_mit_slot_praeferenz(
    alt: dict | None,
    aenderung: dict[str, Any],
) -> dict[str, Any]:
    """Harte Angebot-Korrektur in den Wunsch mischen; Ausschlüsse bleiben."""
    out = dict(alt or {})
    for key in (
        "weekday", "hourMin", "hourMax", "hour", "minDaysAhead", "date",
        "tage", "von", "bis",
    ):
        out.setdefault(key, None if key != "minDaysAhead" else 0)

    ex_tage = set(int(x) for x in (out.get("excludeWeekdays") or []))
    ex_tage.update(int(x) for x in (aenderung.get("excludeWeekdays") or []))
    if aenderung.get("weekdays"):
        out["weekdays"] = sorted(
            set(int(x) for x in aenderung["weekdays"]) - ex_tage
        )
        out["weekday"] = None
    elif out.get("weekday") in ex_tage:
        out["weekday"] = None
    out["excludeWeekdays"] = sorted(ex_tage)

    ex_bereiche = {
        tuple(int(v) for v in x)
        for x in (out.get("excludeHourRanges") or [])
        if isinstance(x, (list, tuple)) and len(x) == 2
    }
    ex_bereiche.update(
        tuple(int(v) for v in x)
        for x in (aenderung.get("excludeHourRanges") or [])
        if isinstance(x, (list, tuple)) and len(x) == 2
    )
    out["excludeHourRanges"] = [list(x) for x in sorted(ex_bereiche)]

    ex_stunden = set(int(x) for x in (out.get("excludeHours") or []))
    ex_stunden.update(int(x) for x in (aenderung.get("excludeHours") or []))
    out["excludeHours"] = sorted(ex_stunden)
    # parse_slot_wish kennt keine Verneinung: "nicht um neun" liegt dort als
    # hour=9, "nicht vormittags" als hourMax=12 — die Ablehnung gewinnt.
    if out.get("hour") is not None and int(out["hour"]) in ex_stunden:
        out["hour"] = None
        out.pop("minutenMin", None)
        out.pop("minutenMax", None)
    if (out.get("hourMin") is not None and out.get("hourMax") is not None
            and (int(out["hourMin"]), int(out["hourMax"])) in ex_bereiche
            and aenderung.get("hourMin") is None):
        out["hourMin"], out["hourMax"] = None, None

    # A6: ganze Tage ("morgen geht nicht"), einzelne Angebote ("der erste
    # nicht", "keiner davon") und Tag+Tageszeit-Verbunde ("Donnerstag
    # Nachmittag nicht") bleiben ueber alle Zuege hart gesperrt.
    ex_daten = set(str(x) for x in (out.get("excludeDates") or []) if x)
    ex_daten.update(str(x) for x in (aenderung.get("excludeDates") or []) if x)
    out["excludeDates"] = sorted(ex_daten)
    if aenderung.get("date"):
        if str(aenderung["date"]) not in ex_daten:
            out["date"] = str(aenderung["date"])
            out["weekday"] = None
            out["weekdays"] = None
            out["tage"] = None
            out["von"], out["bis"] = None, None
    elif out.get("date") in ex_daten:
        out["date"] = None

    ex_isos = set(str(x) for x in (out.get("excludeIsos") or []) if x)
    ex_isos.update(str(x) for x in (aenderung.get("excludeIsos") or []) if x)
    out["excludeIsos"] = sorted(ex_isos)

    spans: list[dict[str, Any]] = []
    gesehen: set[tuple] = set()
    for sp in list(out.get("excludeSpans") or []) + list(aenderung.get("excludeSpans") or []):
        if not isinstance(sp, dict):
            continue
        key = (sp.get("weekday"), sp.get("date"), sp.get("lo"), sp.get("hi"))
        if key in gesehen or (sp.get("weekday") is None and not sp.get("date")):
            continue
        gesehen.add(key)
        spans.append({
            k: v for k, v in sp.items() if k in ("weekday", "date", "lo", "hi") and v is not None
        })
    out["excludeSpans"] = spans

    if aenderung.get("hourMin") is not None:
        out["hourMin"] = int(aenderung["hourMin"])
        out["hourMax"] = int(aenderung["hourMax"])
        out["hour"] = None
        out.pop("minutenMin", None)
        out.pop("minutenMax", None)
    elif aenderung.get("hour") is not None and int(aenderung["hour"]) not in ex_stunden:
        # Gegenvorschlag "lieber um zwei": die Stunde wird der neue Wunsch,
        # eine alte Tageszeit-Grenze weicht ihr (14 Uhr passt nicht zu "vormittags").
        out["hour"] = int(aenderung["hour"])
        out["hourMin"], out["hourMax"] = None, None
        out.pop("minutenMin", None)
        out.pop("minutenMax", None)
    return out


def slot_praeferenz_bestaetigung(aenderung: dict[str, Any]) -> str:
    """Kurze hörbare Bestätigung, bevor das neue Angebot kommt."""
    teile: list[str] = []
    ex = [_WOCHENTAG_NAME.get(int(x), "") for x in aenderung.get("excludeWeekdays") or []]
    ex = [x for x in ex if x]
    if ex:
        teile.append(f"{' und '.join(ex)} scheidet aus")
    ex_daten = [tag_wort(str(x)) for x in aenderung.get("excludeDates") or [] if x]
    ex_daten = [x for x in ex_daten if x]
    if ex_daten:
        teile.append(f"{' und '.join(ex_daten)} scheidet aus")
    for sp in aenderung.get("excludeSpans") or []:
        if not isinstance(sp, dict):
            continue
        tag = ""
        if sp.get("weekday") is not None:
            tag = _WOCHENTAG_NAME.get(int(sp["weekday"]), "")
        elif sp.get("date"):
            tag = tag_wort(str(sp["date"]))
        zeit = "nachmittags" if int(sp.get("lo") or 0) >= 12 else "vormittags"
        if tag:
            teile.append(f"{tag} {zeit} scheidet aus")
    if aenderung.get("rejectAll") and not teile:
        teile.append("diese Zeiten passen nicht")
    elif aenderung.get("excludeIsos") and not teile and not aenderung.get("rejectAll"):
        teile.append("der genannte Termin scheidet aus")
    if aenderung.get("andererTag") and not ex and not ex_daten:
        teile.append("der bisherige Wochentag scheidet aus")
    if aenderung.get("hourMin") == 12:
        teile.append("es soll nachmittags sein")
    elif aenderung.get("hourMax") == 12:
        teile.append("es soll vormittags sein")
    if not teile:
        return "Verstanden, ich ändere die Terminauswahl."
    return "Verstanden, " + "; ".join(teile) + "."


# --- Zeitraum: Monat / Monatsdrittel / relativer Abstand ----------------------
# Chef 14.09.2026: "bianca macht nur im laufenden monat termine ... das fenster
# muss auf 6 monate erweitert werden". Vorher kannte der Parser nur Tage und
# Wochentage — "im Oktober" war KEIN Wunsch, die Suche lief ab heute und der
# Vorrat (20 Slots der Plattform) endete mitten im laufenden Monat.

FENSTER_TAGE = 183  # 6 Monate Suchhorizont

# Nur VOLLE Monatsnamen (plus ae/oe-Schreibungen): die Kuerzel aus _MONAT_NAME
# ("sep", "jun", "mär" ...) gehoeren zu Datumsformen wie "15. Sep" und waeren
# im freien Satz zu leicht getroffen.
_MONAT_VOLL = [
    "januar", "februar", "märz", "maerz", "marz", "april", "mai", "juni",
    "juli", "august", "september", "oktober", "november", "dezember",
]
_MONAT_WORT_RE = re.compile(
    r"\b(?:(anfang|mitte|ende|ab|bis)\s+)?(?:(?:im|in\s+den|noch\s+im|im\s+monat|monat)\s+)?("
    + "|".join(sorted(_MONAT_VOLL, key=len, reverse=True))
    + r")\b",
    re.I,
)
_REL_MONAT_RE = re.compile(
    r"\b(?:(anfang|mitte|ende)\s+)?(?:(?:noch\s+)?(?:im|in(?:\s+den)?)\s+)?"
    r"((?:ueber|über)?n(?:ä|a|ae)chste[nrs]?|kommende[nrs]?|diese[nrsm]?|dieses|laufende[nrs]?)\s+monats?\b",
    re.I,
)
_ZAHL_KLEIN = {
    "ein": 1, "eine": 1, "einer": 1, "einem": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
    "elf": 11, "zwölf": 12, "zwoelf": 12, "vierzehn": 14,
}
_ZAHL_ALT = r"\d{1,2}|" + "|".join(sorted(_ZAHL_KLEIN, key=len, reverse=True))
_IN_WOCHEN_RE = re.compile(r"\bin\s+(?:etwa\s+|ca\.?\s+|circa\s+|rund\s+|so\s+)?(" + _ZAHL_ALT + r")\s+wochen?\b", re.I)
_IN_MONATEN_RE = re.compile(r"\bin\s+(?:etwa\s+|ca\.?\s+|circa\s+|rund\s+|so\s+)?(" + _ZAHL_ALT + r")\s+monat(?:en)?\b", re.I)
_IN_TAGEN_RE = re.compile(r"\bin\s+(?:etwa\s+|ca\.?\s+|circa\s+|rund\s+|so\s+)?(" + _ZAHL_ALT + r")\s+tagen\b", re.I)


def _zahl(tok: str) -> int:
    tok = tok.strip().lower()
    if tok.isdigit():
        return int(tok)
    return int(_ZAHL_KLEIN.get(tok, 0))


def _voraus_tage(t: str) -> int:
    """'in drei Wochen' → 21, 'in zwei Monaten' → 60, 'in vierzehn Tagen' → 14 (gedeckelt)."""
    tage = 0
    m = _IN_WOCHEN_RE.search(t)
    if m:
        tage = max(tage, _zahl(m.group(1)) * 7)
    m = _IN_MONATEN_RE.search(t)
    if m:
        tage = max(tage, _zahl(m.group(1)) * 30)
    m = _IN_TAGEN_RE.search(t)
    if m:
        tage = max(tage, _zahl(m.group(1)))
    return min(tage, FENSTER_TAGE)


def _monat_grenzen(jahr: int, monat: int) -> tuple[date, date]:
    erster = date(jahr, monat, 1)
    if monat == 12:
        letzter = date(jahr + 1, 1, 1) - timedelta(days=1)
    else:
        letzter = date(jahr, monat + 1, 1) - timedelta(days=1)
    return erster, letzter


def _monat_drittel(lage: str, erster: date, letzter: date) -> tuple[date, date]:
    lage = (lage or "").lower()
    if lage == "anfang":
        return erster, erster.replace(day=10)
    if lage == "mitte":
        return erster.replace(day=11), erster.replace(day=20)
    if lage == "ende":
        return erster.replace(day=21), letzter
    return erster, letzter


def zeitraum_aus_text(text: str, heute: date | None = None) -> tuple[str, str]:
    """Monats-/Zeitraumwunsch → (von, bis) als ISO-Tage ('' = offen).

    "im Oktober" → ganzer Monat (vergangener Monat rollt ins nächste Jahr),
    "Anfang/Mitte/Ende Oktober" → Drittel, "ab November" → nur von,
    "bis Oktober" → nur bis, "nächsten Monat"/"übernächsten Monat"/"diesen Monat".
    Ein volles Datum ("am 3. Oktober") gehört NICHT hierher — das ist ein Tag.
    """
    raw = _s(text)
    if not raw:
        return "", ""
    basis = heute or datetime.now(TZ).date()
    t = f" {raw.lower()} "
    m = _MONAT_WORT_RE.search(t)
    if m:
        lage = (m.group(1) or "").lower()
        monat = _MONAT_NAME[m.group(2).lower()]
        jahr = basis.year if monat >= basis.month else basis.year + 1
        erster, letzter = _monat_grenzen(jahr, monat)
        if lage == "ab":
            return erster.isoformat(), ""
        if lage == "bis":
            return "", letzter.isoformat()
        von, bis = _monat_drittel(lage, erster, letzter)
        return von.isoformat(), bis.isoformat()
    m = _REL_MONAT_RE.search(t)
    if m:
        lage = (m.group(1) or "").lower()
        wort = m.group(2).lower()
        if wort.startswith(("über", "ueber")):
            schritt = 2
        elif wort.startswith(("näch", "naech", "nach", "komm")):
            schritt = 1
        else:
            schritt = 0
        monat = basis.month - 1 + schritt
        jahr = basis.year + monat // 12
        monat = monat % 12 + 1
        erster, letzter = _monat_grenzen(jahr, monat)
        von, bis = _monat_drittel(lage, erster, letzter)
        return von.isoformat(), bis.isoformat()
    return "", ""


_BESTAND_UHR_RE = re.compile(
    r"(?:heute|morgen).{0,28}\buhr\b.{0,80}termin|"
    r"termin.{0,48}(?:heute|morgen).{0,28}\buhr|"
    r"habe.{0,24}um\s+\w.{0,24}termin.{0,48}verschieb",
    re.I | re.S,
)


def _bestand_uhr_im_satz(t: str) -> bool:
    return bool(re.search(r"\bverschieb", t) and _BESTAND_UHR_RE.search(t))


_MONAT_NAME = {
    "januar": 1, "jan": 1, "februar": 2, "feb": 2,
    "märz": 3, "maerz": 3, "mär": 3, "marz": 3,
    "april": 4, "apr": 4, "mai": 5, "juni": 6, "jun": 6,
    "juli": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9,
    "oktober": 10, "okt": 10, "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
}
_MONAT_RE = re.compile(
    r"\b(\d{1,2})\.?\s+("
    + "|".join(sorted(_MONAT_NAME, key=len, reverse=True))
    + r")(?:\s+(\d{4}))?\b",
    re.I,
)
# "am 15.09" / "15.09." / "3.9.2026" — der Punkt nach dem Monat ist optional.
# "um 9.15" und "9.15 Uhr" bleiben Uhrzeiten, kein Datum.
_DATUM_ZAHL_RE = re.compile(r"\b(\d{1,2})\.\s*(\d{1,2})(?:\.(\d{4})?)?")

# "Donnerstag der 10." / "dem 21." / "den 29." — Tag ohne Monatsname.
# Nicht "am 3. Oktober" / "am 15.09" (das ist ein volles Datum).
_TAG_ORD_RE = re.compile(
    r"\b(?:am|dem|den|der)\s+(\d{1,2})\.(?!\s*\d)(?!\s*(?:"
    + "|".join(sorted(_MONAT_NAME, key=len, reverse=True))
    + r")\b)",
    re.I,
)
# "10. oder 21." ohne zweiten Artikel.
_TAG_ORD_MEHR_RE = re.compile(
    r"(?:oder|,|/|und)\s+(?:(?:am|dem|den|der)\s+)?(\d{1,2})\.(?!\s*\d)",
    re.I,
)


def _kalendertag(jahr: int, monat: int, tag: int):
    try:
        return datetime(jahr, monat, tag, tzinfo=TZ).date()
    except ValueError:
        return None


def _jahr_rollen(d):
    """Vergangene Kalendertage ohne Jahr → nächstes Jahr (am 15.03. im August)."""
    heute = datetime.now(TZ).date()
    if d < heute:
        try:
            return d.replace(year=d.year + 1)
        except ValueError:
            return d
    return d


def datum_aus_text(text: str) -> str:
    """Deutsches Datum aus dem Satz: 'am 15.09', 'am 3.9.', '15. September'."""
    raw = _s(text)
    if not raw:
        return ""
    t = f" {raw.lower()} "
    m = _MONAT_RE.search(t)
    if m:
        tag, monat = int(m.group(1)), _MONAT_NAME[m.group(2).lower()]
        jahr = int(m.group(3)) if m.group(3) else datetime.now(TZ).year
        d = _kalendertag(jahr, monat, tag)
        if d:
            if not m.group(3):
                d = _jahr_rollen(d)
            return d.isoformat()
    for dm in _DATUM_ZAHL_RE.finditer(t):
        davor = t[max(0, dm.start() - 8):dm.start()]
        danach = t[dm.end():dm.end() + 8]
        if re.search(r"uhr", danach):
            continue
        if re.search(r"\bum\s+$", davor):
            continue
        tag, monat = int(dm.group(1)), int(dm.group(2))
        if not (1 <= monat <= 12 and 1 <= tag <= 31):
            continue
        jahr_roh = dm.group(3)
        jahr = int(jahr_roh) if jahr_roh else datetime.now(TZ).year
        d = _kalendertag(jahr, monat, tag)
        if not d:
            continue
        if not jahr_roh:
            d = _jahr_rollen(d)
        return d.isoformat()
    return ""


def _tag_im_monat(tag: int, heute: date | None = None):
    """Nächster Kalendertag mit dieser Monatszahl (ab heute, sonst nächster Monat)."""
    if not (1 <= tag <= 31):
        return None
    basis = heute or datetime.now(TZ).date()
    d = _kalendertag(basis.year, basis.month, tag)
    if d and d >= basis:
        return d
    if basis.month == 12:
        return _kalendertag(basis.year + 1, 1, tag)
    return _kalendertag(basis.year, basis.month + 1, tag)


def _datum_nennungen(t: str, heute: date | None = None) -> list[tuple[int, int, str]]:
    """Absolute Tages-Nennungen mit Textposition: (start, end, ISO).

    '3. Oktober' / '15.09.' / 'am 10.' — fuer die Ablehnungs-Logik in
    ``slot_praeferenz_aenderung`` (A6). Uhrzeiten ('9.15 Uhr', 'um 9.15')
    zaehlen nicht.
    """
    basis = heute or datetime.now(TZ).date()
    out: list[tuple[int, int, str]] = []
    belegt: list[tuple[int, int]] = []

    def _frei(a: int, b: int) -> bool:
        return not any(a < e and b > s for s, e in belegt)

    for m in _MONAT_RE.finditer(t):
        tag, monat = int(m.group(1)), _MONAT_NAME.get(m.group(2).lower())
        if not monat:
            continue
        jahr = int(m.group(3)) if m.group(3) else basis.year
        d = _kalendertag(jahr, monat, tag)
        if not d:
            continue
        if not m.group(3) and d < basis:
            d = _kalendertag(jahr + 1, monat, tag) or d
        belegt.append((m.start(), m.end()))
        out.append((m.start(), m.end(), d.isoformat()))
    for m in _DATUM_ZAHL_RE.finditer(t):
        if not _frei(m.start(), m.end()):
            continue
        davor = t[max(0, m.start() - 8):m.start()]
        danach = t[m.end():m.end() + 8]
        if re.search(r"uhr", danach) or re.search(r"\b(?:um|gegen)\s+$", davor):
            continue
        tag, monat = int(m.group(1)), int(m.group(2))
        if not (1 <= monat <= 12 and 1 <= tag <= 31):
            continue
        jahr = int(m.group(3)) if m.group(3) else basis.year
        d = _kalendertag(jahr, monat, tag)
        if not d:
            continue
        if not m.group(3) and d < basis:
            d = _kalendertag(jahr + 1, monat, tag) or d
        belegt.append((m.start(), m.end()))
        out.append((m.start(), m.end(), d.isoformat()))
    for m in _TAG_ORD_RE.finditer(t):
        if not _frei(m.start(), m.end()):
            continue
        d = _tag_im_monat(int(m.group(1)), basis)
        if not d:
            continue
        belegt.append((m.start(), m.end()))
        out.append((m.start(), m.end(), d.isoformat()))
    return sorted(out, key=lambda x: x[0])


def tage_aus_text(text: str) -> list[str]:
    """Alle 'der 10.' / 'dem 21.' im Satz → ISO-Tage, aufsteigend, ohne Duplikat."""
    raw = _s(text)
    if not raw:
        return []
    heute = datetime.now(TZ).date()
    gefunden: list[str] = []
    gesehen: set[str] = set()
    t = f" {raw.lower()} "
    zahlen: list[int] = []
    for m in _TAG_ORD_RE.finditer(t):
        zahlen.append(int(m.group(1)))
    for m in _TAG_ORD_MEHR_RE.finditer(t):
        zahlen.append(int(m.group(1)))
    for n in zahlen:
        d = _tag_im_monat(n, heute)
        if not d:
            continue
        iso = d.isoformat()
        if iso in gesehen:
            continue
        gesehen.add(iso)
        gefunden.append(iso)
    return gefunden


def _region_tage(iso_date: str, radius: int = 2) -> list[str]:
    d = date.fromisoformat(iso_date)
    return [(d + timedelta(days=i)).isoformat() for i in range(-radius, radius + 1)]


def spoken_slot(iso: str) -> str:
    """Sprechbar, nicht ablesbar: 'morgen um neun Uhr fünfzehn'."""
    return slot_wort(iso)


def _weekday_of(date_str: str) -> int:
    d = datetime.fromisoformat(f"{date_str}T12:00:00+00:00")
    return int(d.astimezone(TZ).strftime("%w"))  # 0=So


# Nie benachbarte Leer-Slots anbieten (Chef 27.08.2026, live: 12:15/12:45/13:15
# bzw. 09:30/09:45/10:00): am selben Tag mindestens 2,5 Stunden Abstand.
MIN_ABSTAND_MS = 150 * 60000
# Früher/später im ±3-h-Fenster: 30 Minuten reichen, sonst passt nur ein Slot.
SCHUB_ABSTAND_MS = 30 * 60000


def _vertraegt(kand: dict, gewaehlt: list[dict]) -> bool:
    return all(
        g["date"] != kand["date"] or abs(g["ms"] - kand["ms"]) >= MIN_ABSTAND_MS
        for g in gewaehlt
    )


def _streuen(pool: list[dict], parsed: list[dict], wish: dict | None, max_n: int) -> list[dict]:
    """Gestreute Auswahl: Vielfalt vor Dichte, der Wunsch bleibt führend.

    1. Erstes Angebot: bei konkreter Zielzeit ("gegen zehn") der nächstliegende
       Slot, sonst der früheste im Wunschrahmen.
    2. Dann je ein Slot pro WEITEREM Tag (Tag A vormittags + Tag B nachmittags
       schlägt zwei nahe Slots am selben Tag).
    3. Dann derselbe Tag, aber nur mit >= 2,5 h Abstand.
    4. Fallback (< 2 Optionen): lieber EIN Slot des Wunschtags plus Alternativen
       anderer Tage außerhalb des Wunschrahmens.
    5. Allerletzter Ausweg: nahe Slots durchrutschen lassen — besser als nichts.
    """
    if not pool:
        return []
    anker = pool[0]
    if wish and wish.get("hour") is not None:
        ziel = int(wish["hour"]) * 60
        anker = min(pool, key=lambda p: (abs(p["hour"] * 60 + int(p["time"][3:5]) - ziel), p["ms"]))
    gewaehlt = [anker]
    for p in pool:
        if len(gewaehlt) >= max_n:
            break
        if p["date"] not in {g["date"] for g in gewaehlt}:
            gewaehlt.append(p)
    for p in pool:
        if len(gewaehlt) >= max_n:
            break
        if p not in gewaehlt and _vertraegt(p, gewaehlt):
            gewaehlt.append(p)
    if len(gewaehlt) < 2:
        pool_ids = {id(p) for p in pool}
        for p in parsed:
            if len(gewaehlt) >= max_n:
                break
            if id(p) not in pool_ids and p not in gewaehlt and _vertraegt(p, gewaehlt):
                gewaehlt.append(p)
    if len(gewaehlt) < 2:
        for p in pool:
            if len(gewaehlt) >= max_n:
                break
            if p not in gewaehlt:
                gewaehlt.append(p)
    rest = sorted((g for g in gewaehlt if g is not anker), key=lambda p: p["ms"])
    return [anker] + rest


def _schub_dicht(pool: list[dict], max_n: int) -> list[dict]:
    """Nächste freie Plätze im Fenster, 30-Minuten-Abstand — kein Tages-Streu."""
    if not pool:
        return []
    out: list[dict] = []
    for p in pool:
        if all(p["date"] != g["date"] or abs(p["ms"] - g["ms"]) >= SCHUB_ABSTAND_MS for g in out):
            out.append(p)
        if len(out) >= max_n:
            break
    return out


# Felder, die ein Anrufer AUSDRUECKLICH abgelehnt hat — die duerfen nie
# durch Ausweich-/Streu-/Naechstbestes-Auswahl zurueckkommen (A6).
_HART_KEYS = (
    "weekdays", "excludeWeekdays", "excludeHours", "excludeHourRanges",
    "excludeDates", "excludeIsos", "excludeSpans",
)
# Weiche Praeferenzen, die bei leerem Pool STUFENWEISE fallen duerfen —
# harte Ausschluesse bleiben dabei immer bestehen.
_WEICH_STUFEN: tuple[tuple[str, ...], ...] = (
    ("weekdays", "weekday"),
    ("hour", "hourMin", "hourMax", "minutenMin", "minutenMax"),
    ("date", "tage"),
    ("von", "bis", "minDaysAhead"),
)


_AUSSCHLUSS_KEYS = (
    "excludeWeekdays", "excludeHours", "excludeHourRanges",
    "excludeDates", "excludeIsos", "excludeSpans",
)


def wunsch_ausschluesse(wish: dict | None) -> dict[str, Any]:
    """Nur die harten AUSSCHLUESSE eines Wunsches (A6).

    Wer die Richtung eines Wunsches verwirft ("Egal", Eskalation der
    Wunschfrage, "Ändere den Zeitpunkt"), behaelt damit trotzdem, was der
    Anrufer schon ABGELEHNT hat — ein "kein Donnerstag" darf nie durch ein
    spaeteres "egal" wieder im Angebot landen.
    """
    if not isinstance(wish, dict):
        return {}
    return {k: wish[k] for k in _AUSSCHLUSS_KEYS if wish.get(k)}


def hat_ausschluesse(wish: dict | None) -> bool:
    return bool(wunsch_ausschluesse(wish))


_RICHTUNG_KEYS = (
    "date", "tage", "weekday", "weekdays", "hour", "hourMin", "hourMax",
    "minDaysAhead", "von", "bis",
)


def wunsch_hat_richtung(wish: dict | None) -> bool:
    """Traegt der Wunsch eine POSITIVE Angabe (Tag, Zeit, Zeitraum)?

    Ein Wunsch, der nur aus Ausschluessen besteht ("kein Donnerstag"), ist
    fuer die Wunschfrage weiterhin unbeantwortet — "egal" darauf heisst:
    naechste freie Termine, aber ohne die abgelehnten.
    """
    if not isinstance(wish, dict):
        return False
    return any(wish.get(k) not in (None, 0, "", [], {}) for k in _RICHTUNG_KEYS)


def _harte_slotgrenzen(wish: dict | None) -> bool:
    """Ausschlüsse/Mehrfach-Tage dürfen nie durch Ausweichslots verletzt werden."""
    if not wish:
        return False
    return any(wish.get(k) for k in _HART_KEYS)


def _hart_ausweich_stufen(wish: dict) -> list[dict]:
    """Ausweich-Wuensche bei leerem Pool trotz harter Grenzen.

    Erst faellt die Wochentags-PRAEFERENZ ("lieber Freitag"), dann die
    Uhrzeit, dann der konkrete Tag, zuletzt der Zeitraum — die AUSSCHLUESSE
    (kein Donnerstag, nicht der erste, morgen nicht) bleiben in jeder Stufe.
    Nicht-kumulativ zuerst (nur eine Gruppe weg), dann kumulativ, damit
    "Freitag nachmittags" ohne Treffer erst "Freitag" bzw. "nachmittags"
    probiert, bevor alles faellt.
    """
    stufen: list[dict] = []
    gesetzt = [
        keys for keys in _WEICH_STUFEN
        if any(wish.get(k) not in (None, "", [], 0) for k in keys)
    ]
    if not gesetzt:
        return stufen
    for keys in gesetzt:
        w = dict(wish)
        for k in keys:
            w[k] = None
        stufen.append(w)
    if len(gesetzt) > 1:
        w = dict(wish)
        for keys in gesetzt:
            for k in keys:
                w[k] = None
        stufen.append(w)
    return stufen


def _span_gesperrt(p: dict, spans: list) -> bool:
    for sp in spans or []:
        if not isinstance(sp, dict):
            continue
        try:
            lo, hi = int(sp.get("lo", 0)), int(sp.get("hi", 24))
        except (TypeError, ValueError):
            continue
        if not lo <= p["hour"] < hi:
            continue
        if sp.get("date") and str(sp["date"]) == p["date"]:
            return True
        if sp.get("weekday") is not None and _weekday_of(p["date"]) == int(sp["weekday"]):
            return True
    return False


def slot_wunsch_hart(wish: dict | None) -> bool:
    """Öffentlicher Wächter gegen Ausweichslots aus abgelehnten Klassen."""
    return _harte_slotgrenzen(wish)


def pick_slots(iso_slots: list[str], *, wish: dict | None = None, now_ms: int | None = None,
               exclude_iso: str = "", exclude_isos: list | set | None = None,
               max_n: int = 3, dringend: bool = False,
               schub: bool = False) -> dict[str, Any]:
    now = now_ms if now_ms is not None else int(datetime.now(TZ).timestamp() * 1000)
    # Gesperrte ISOs (Buchungs-Fails): per Minuten-Praefix, damit Offset-Formen
    # denselben Slot treffen (W-BOOK-RETRY 01.09.2026).
    gesperrt = {str(x)[:16] for x in (exclude_isos or []) if x}
    if exclude_iso:
        gesperrt.add(str(exclude_iso)[:16])
    parsed = []
    for iso in iso_slots or []:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})", str(iso))
        if not m:
            continue
        try:
            ms = int(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            continue
        if ms < now + 60 * 60000:
            continue
        if str(iso)[:16] in gesperrt:
            continue
        parsed.append({
            "iso": str(iso), "date": m.group(1), "time": f"{m.group(2)}:{m.group(3)}",
            "hour": int(m.group(2)), "ms": ms,
        })
    parsed.sort(key=lambda p: p["ms"])

    def apply(pool: list, w: dict | None = None) -> list:
        w = wish if w is None else w
        if not w:
            return pool
        out = pool
        if w.get("tage"):
            erlaubt = {str(d) for d in w["tage"] if d}
            if erlaubt:
                out = [p for p in out if p["date"] in erlaubt]
        elif w.get("date"):
            out = [p for p in out if p["date"] == w["date"]]
        # W-SUCHFENSTER: Zeitraum ("im Oktober" = von/bis, "ab November" = nur von).
        if w.get("von"):
            out = [p for p in out if p["date"] >= str(w["von"])]
        if w.get("bis"):
            out = [p for p in out if p["date"] <= str(w["bis"])]
        if w.get("weekdays"):
            erlaubt = {int(x) for x in w["weekdays"]}
            out = [p for p in out if _weekday_of(p["date"]) in erlaubt]
        elif w.get("weekday") is not None:
            out = [p for p in out if _weekday_of(p["date"]) == w["weekday"]]
        if w.get("excludeWeekdays"):
            gesperrte_tage = {int(x) for x in w["excludeWeekdays"]}
            out = [p for p in out if _weekday_of(p["date"]) not in gesperrte_tage]
        if w.get("minDaysAhead"):
            # "Nächste Woche" meint den TAG in einer Woche ab Mitternacht —
            # nicht "mindestens 168 Stunden ab jetzt". Sonst fehlen am Zieltag
            # alle Zeiten VOR der aktuellen Uhrzeit (live 27.08.2026: Angebot
            # begann um 10:55 statt 09:55, weil der Anruf um 10:41 lief).
            ziel = datetime.fromtimestamp(now / 1000, TZ) + timedelta(days=w["minDaysAhead"])
            mitternacht = ziel.replace(hour=0, minute=0, second=0, microsecond=0)
            out = [p for p in out if p["ms"] >= int(mitternacht.timestamp() * 1000)]
        if w.get("hour") is not None:
            out = [p for p in out if abs(p["hour"] - w["hour"]) <= 1]
        elif w.get("minutenMin") is not None:
            lo = int(w["minutenMin"])
            hi = int(w.get("minutenMax") if w.get("minutenMax") is not None else 24 * 60)
            out = [p for p in out if lo <= (p["hour"] * 60 + int(p["time"][3:5])) <= hi]
        elif w.get("hourMin") is not None:
            out = [p for p in out if w["hourMin"] <= p["hour"] < w["hourMax"]]
        if w.get("excludeHours"):
            gesperrte_stunden = {int(x) for x in w["excludeHours"]}
            out = [p for p in out if p["hour"] not in gesperrte_stunden]
        for grenze in w.get("excludeHourRanges") or []:
            if isinstance(grenze, (list, tuple)) and len(grenze) == 2:
                lo, hi = int(grenze[0]), int(grenze[1])
                out = [p for p in out if not lo <= p["hour"] < hi]
        # A6: abgelehnte Tage, Angebote und Tag+Tageszeit-Verbunde.
        if w.get("excludeDates"):
            gesperrte_daten = {str(x)[:10] for x in w["excludeDates"] if x}
            out = [p for p in out if p["date"] not in gesperrte_daten]
        if w.get("excludeIsos"):
            gesperrte_isos = {str(x)[:16] for x in w["excludeIsos"] if x}
            out = [p for p in out if p["iso"][:16] not in gesperrte_isos]
        if w.get("excludeSpans"):
            out = [p for p in out if not _span_gesperrt(p, w["excludeSpans"])]
        return out

    pool = apply(parsed)
    matched = not wish or bool(pool)
    hart = _harte_slotgrenzen(wish)
    schieben = bool(schub or (wish and wish.get("schub")))
    if not pool and wish and wish.get("date") and not schieben and not wish.get("tage"):
        # Konkretes Datum ohne Treffer: ±2 Tage in der Region, nicht irgendwo.
        nachbarn = [d for d in _region_tage(str(wish["date"]), 2) if d != wish["date"]]
        w2 = dict(wish)
        w2.pop("date", None)
        w2["tage"] = nachbarn
        pool = apply(parsed, w2)
        if pool:
            ziel = str(wish["date"])

            def _nahe(p: dict) -> tuple:
                return (abs((date.fromisoformat(p["date"]) - date.fromisoformat(ziel)).days), p["ms"])

            pool = sorted(pool, key=_nahe)
    naechstbestes = False
    hart_ausweich = False
    if not pool:
        if hart:
            # „Nicht Donnerstag“ ist keine weiche Präferenz: Donnerstag kommt
            # NIE zurueck. Aber ein leerer Pool heisst nicht "kein Termin" —
            # A6 (17.09.2026): erst fallen die weichen Praeferenzen stufenweise
            # (lieber Freitag / nachmittags / der Tag / der Zeitraum), die
            # Ausschluesse gelten in jeder Stufe. Das Ergebnis zaehlt als
            # "nicht getroffen" (Ansage "Genau dann ist leider nichts frei",
            # find_slots blaettert weiter). Schub/Uhrzeit-Untergrenze bleiben
            # streng (kein Rueckfall auf dieselben Zeiten).
            if not schieben and wish.get("minutenMin") is None:
                for w2 in _hart_ausweich_stufen(wish):
                    pool = apply(parsed, w2)
                    if pool:
                        hart_ausweich = True
                        break
            if not pool:
                return {"slots": [], "wishMatched": False}
        elif schieben or (wish and wish.get("minutenMin") is not None):
            # Schub ohne Treffer: NICHT auf die drei Vormittagsslots
            # zurückfallen (live 30.08.2026: „keine weiteren“ + dieselben 09:45er).
            return {"slots": [], "wishMatched": False}
        elif wish and _zeitanker(wish):
            # W-SUCHFENSTER (14.09.2026, Anruf 5aa87268): "heute um halb zwei"
            # ohne Treffer hiess frueher "kein freier Termin" — bei 20 freien
            # Slots im Vorrat. Jetzt: das NAECHSTBESTE ab dem Wunschzeitpunkt,
            # als solches angesagt ("Genau dann ist leider nichts frei").
            pool = _naechstbestes(parsed, wish)
            naechstbestes = True
        if not pool:
            pool = parsed
    if dringend:
        auswahl = pool[:max_n]
    elif hart_ausweich:
        # Ausweich innerhalb der harten Grenzen: gestreut, aber NIE ausserhalb
        # des gefilterten Pools (kein Rueckgriff auf `parsed`).
        auswahl = _streuen(pool, pool, wish, max_n)
    elif schieben or naechstbestes or (wish and wish.get("date") and not matched):
        # Region um ein leeres Wunschdatum: nur die Nachbartage, kein
        # Streu-Fallback auf Vormittage in drei Wochen.
        auswahl = _schub_dicht(pool, max_n)
    else:
        # Der normale Streu-Fallback darf weiche Wünsche verlassen. Harte
        # Ausschlüsse dagegen gelten auch für zweite/dritte Alternativen.
        auswahl = _streuen(pool, pool if hart else parsed, wish, max_n)
    if naechstbestes:
        auswahl = sorted(auswahl, key=lambda p: p["ms"])
    slots = [{"iso": p["iso"], "date": p["date"], "time": p["time"]} for p in auswahl]
    return {"slots": slots, "wishMatched": matched}


def _zeitanker(wish: dict) -> str:
    """Fruehester Wunschtag (ISO) — Datum, Wunschtage oder Zeitraum-Beginn."""
    if wish.get("tage"):
        tage = sorted(str(d) for d in wish["tage"] if d)
        if tage:
            return tage[0]
    if wish.get("date"):
        return str(wish["date"])
    if wish.get("von"):
        return str(wish["von"])
    if wish.get("bis"):
        return str(wish["bis"])
    return ""


def _naechstbestes(parsed: list[dict], wish: dict) -> list[dict]:
    """Alternativen zu einem leeren Wunschtag/-zeitraum: erst die Zeiten AB dem
    Wunsch (gleiche Tageszeit/Uhrzeit bevorzugt), sonst die letzten davor.

    Ein Wunschtag in der Vergangenheit oder ein Zeitraum, den der Kalender
    noch nicht freigegeben hat, bekommt so trotzdem ein ehrliches Angebot
    statt "kein freier Termin"."""
    anker = _zeitanker(wish)
    if not anker or not parsed:
        return []
    danach = [p for p in parsed if p["date"] >= anker]
    davor = [p for p in parsed if p["date"] < anker]
    zeit_only = {
        k: wish.get(k) for k in ("hour", "hourMin", "hourMax", "weekday", "minutenMin", "minutenMax")
        if wish.get(k) is not None
    }
    if danach and zeit_only:
        # Erst die Tageszeit halten ("heute 14 Uhr" -> morgen 14 Uhr), dann
        # erst die Uhrzeit fallen lassen.
        w2 = dict(zeit_only)
        w2["minDaysAhead"] = 0
        eng = [
            p for p in danach
            if (w2.get("weekday") is None or _weekday_of(p["date"]) == w2["weekday"])
            and (w2.get("hour") is None or abs(p["hour"] - int(w2["hour"])) <= 1)
            and (w2.get("hourMin") is None or w2["hourMin"] <= p["hour"] < w2["hourMax"])
        ]
        if eng:
            return eng
    if danach:
        return danach
    return sorted(davor, key=lambda p: p["ms"], reverse=True)


def spoken_offer(slots: list[dict], *, wish_matched: bool = True) -> str:
    """Nur was der Patient hört — keine Werkzeugnamen, keine Regie."""
    if not slots:
        return (
            "Im Moment habe ich leider keinen freien Termin. "
            "Die Praxis meldet sich kurzfristig bei Ihnen."
        )
    liste = "; oder ".join(spoken_slot(x["iso"]) for x in slots)
    if wish_matched:
        return f"Frei ist {liste}. Welcher passt Ihnen?"
    return f"Genau dann ist leider nichts frei. Frei wäre {liste}. Welcher passt Ihnen?"


REGIE_ANGEBOT = (
    "Nenne die freien Zeiten genau so, wie sie im Feld spoken stehen. "
    "Sobald der Patient einen wählt: sofort book_slot mit dem unveränderten iso."
)
