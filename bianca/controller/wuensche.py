"""Wunsch und Korrektur — jeder Zug, nicht nur der Erstsatz.

Mandantenunabhaengig: Wochentag, Tageszeit, Monat/Zeitraum, Besuchsgrund
und Feldnamen. Der Reducer mischt Komponenten (Monat bleibt, wenn nur
ein Wochentag nachkommt). Die Slotsuche filtert das Fenster — ein
verstandener Wunsch darf nie als Default-Woche maskiert werden.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_WOCHENTAG = (
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag",
)
_TAGESZEIT = (
    "vormittag", "nachmittag", "abend", "frueh", "früh",
    "morgen", "uebermorgen", "übermorgen", "heute",
)
_RELATIV = ("naechste woche", "nächste woche")

# Isoliertes Dock-Kalenderjahr (Slots sind 09/10.2026).
HEUTE = date(2026, 9, 19)

_MONAT = {
    "januar": 1, "februar": 2, "maerz": 3, "marz": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}
_MONAT_NAME = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November",
    12: "Dezember",
}
_SPLIT = (
    "uebernaechsten", "uebernaechste", "uebernaechster",
    "naechsten", "naechste", "naechster", "naechstes",
    "diesen", "dieser", "dieses",
    "irgendwann", "monat", "woche",
) + tuple(sorted(_MONAT, key=len, reverse=True))
_SPLIT_RX = re.compile(
    "|".join(re.escape(s) for s in sorted(set(_SPLIT), key=len, reverse=True))
)

_REL_MONAT = re.compile(
    r"\b(diesen|dieser|dieses|naechsten|naechste|naechster|"
    r"uebernaechsten|uebernaechste|uebernaechster)\s+monat\b",
    re.I,
)
_REL_WOCHE = re.compile(
    r"\b(naechsten|naechste|naechster)\s+woche\b",
    re.I,
)
_SLOT_DAT = re.compile(r"(\d{1,2})\.(\d{1,2})\.")

_GRUND = [
    ("schwangerschaft", "Schwangerschaftsvorsorge"),
    ("zahnreinigung", "Zahnreinigung"), ("pzr", "Zahnreinigung"),
    ("prophylaxe", "Prophylaxe"), ("kontrolle", "Kontrolle"),
    ("untersuchung", "Kontrolle"), ("hautscreening", "Kontrolle"),
    ("schmerz", "Schmerzen"), ("akute haut", "Haut"),
    ("weisheitszahn", "Weisheitszahn"), ("implantat", "Implantat-Besprechung"),
    ("krone", "Krone"), ("füllung", "Fuellung"), ("fuellung", "Fuellung"),
    ("beratung", "Beratung"), ("besprechung", "Besprechung"),
    ("bleaching", "Bleaching"), ("vorsorge", "Vorsorge"),
    ("akne", "Haut"), ("muttermal", "Haut"), ("warzen", "Haut"),
    ("atherom", "Haut"), ("fußpflege", "Fusspflege"), ("fusspflege", "Fusspflege"),
    ("blutabnahme", "Labor"), ("allergie", "Allergie"),
]

_FELD = (
    (re.compile(r"\b(?:besuchs)?grund\b", re.I), "besuchsgrund"),
    (re.compile(r"\b(?:wunsch)?zeit\b|\btag(?:e)?\b|\bdatum\b", re.I), "wunschzeit"),
    (re.compile(r"\bbehandler\b|\barzt\b|\baerztin\b|\bärztin\b", re.I), "behandler"),
    (re.compile(r"\bnachname\b|\bname\b", re.I), "nachname"),
    (re.compile(r"\bvorname\b", re.I), "vorname"),
    (re.compile(r"\b(?:handy)?nummer\b|\btelefon\b", re.I), "telefon"),
    (re.compile(r"\bversicherung\b|\bkasse\b", re.I), "versicherung"),
)

_MUELL_WUNSCH = frozenset({
    "ja", "nein", "ok", "okay", "gerne", "genau", "richtig", "passt",
    "den grund", "der grund", "die zeit", "den arzt", "der arzt",
})


def falt(s: str) -> str:
    return (
        str(s or "").lower()
        .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    )


def _aufloesen(text: str) -> str:
    """Geklebte Tippfehler, ein Durchgang, längster Stamm zuerst.

    Nacheinander ersetzen zerlegt »naechsten« zu »naechste n« — dann
    findet »nächsten Monat« kein Fenster mehr.
    """
    t = falt(text)
    t = _SPLIT_RX.sub(lambda m: f" {m.group(0)} ", t)
    return " ".join(t.split())


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


def _token_ist(wort: str, kandidaten: tuple[str, ...], dist: int) -> str:
    """Kanonischen Treffer oder leer."""
    w = falt(wort)
    if w.endswith("s") and len(w) > 4:
        w0 = w[:-1]
    else:
        w0 = w
    for k in kandidaten:
        kk = falt(k)
        if w == kk or w0 == kk:
            return k
        if len(w) >= 4 and abs(len(w) - len(kk)) <= dist and _lev(w, kk) <= dist:
            return k
        if len(w0) >= 4 and abs(len(w0) - len(kk)) <= dist and _lev(w0, kk) <= dist:
            return k
    return ""


def _toks(t: str) -> list[str]:
    return re.findall(r"[a-zäöüß]+", str(t or "").lower())


def wochentag(text: str) -> str:
    for w in _toks(text):
        fw = falt(w)
        if fw == "monat" or fw in _MONAT:
            continue
        treffer = _token_ist(w, _WOCHENTAG, 2)
        if treffer:
            return treffer.capitalize()
    return ""


def tageszeit(text: str) -> str:
    t = falt(text)
    for w in _TAGESZEIT:
        if falt(w) in t:
            return "nachmittag" if w in ("abend",) else (
                "vormittag" if w in ("frueh", "früh") else w.replace("ü", "ue")
            )
    for w in _toks(text):
        treffer = _token_ist(w, ("vormittag", "nachmittag", "abend"), 2)
        if treffer:
            return "nachmittag" if treffer == "abend" else treffer
    return ""


def _monat_jahr(monat: int, heute: date) -> tuple[int, int]:
    jahr = heute.year if monat >= heute.month else heute.year + 1
    return monat, jahr


def _rel_monat(schritt: int, heute: date) -> tuple[int, int]:
    m = heute.month - 1 + schritt
    return m % 12 + 1, heute.year + m // 12


def teile(text: str, heute: date | None = None) -> dict:
    """Zerlegt einen Zeitwunsch in Wochentag, Tageszeit, Monatsfenster."""
    heute = heute or HEUTE
    leer = {
        "wochentag": "", "tageszeit": "", "monat": 0, "jahr": 0,
        "relativ": "", "text": "",
    }
    t = _aufloesen(text)
    if not t or t in _MUELL_WUNSCH:
        return dict(leer)
    tag = wochentag(t)
    tz = tageszeit(t)
    if tz in ("morgen", "uebermorgen", "heute") and not tag:
        # Relatives Tageswort bleibt im Text, kein Monatsfenster.
        pass
    monat = 0
    jahr = 0
    relativ = ""
    m = _REL_MONAT.search(t)
    if m:
        wort = falt(m.group(1))
        if wort.startswith("ueber"):
            schritt = 2
            relativ = "uebernaechster_monat"
        elif wort.startswith("naech") or wort.startswith("komm"):
            schritt = 1
            relativ = "naechster_monat"
        else:
            schritt = 0
            relativ = "dieser_monat"
        monat, jahr = _rel_monat(schritt, heute)
    elif _REL_WOCHE.search(t) or any(p in t for p in _RELATIV):
        relativ = "naechste_woche"
    else:
        for name, nr in _MONAT.items():
            if re.search(rf"\b{name}\b", t):
                monat, jahr = _monat_jahr(nr, heute)
                relativ = "monat"
                break
    uhr = ""
    um = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*uhr", t)
    if um:
        uhr = um.group(0)
    kanon = _kanon(tag, tz, monat, jahr, relativ, uhr)
    if not kanon and tz in ("morgen", "uebermorgen", "heute"):
        kanon = tz
    return {
        "wochentag": tag,
        "tageszeit": tz if tz not in ("morgen", "uebermorgen", "heute") else "",
        "monat": monat,
        "jahr": jahr,
        "relativ": relativ,
        "text": kanon,
    }


def _kanon(tag: str, tz: str, monat: int, jahr: int, relativ: str, uhr: str = "") -> str:
    teile_txt: list[str] = []
    if relativ == "naechster_monat":
        teile_txt.append("nächsten Monat")
    elif relativ == "dieser_monat":
        teile_txt.append("diesen Monat")
    elif relativ == "uebernaechster_monat":
        teile_txt.append("übernächsten Monat")
    elif relativ == "naechste_woche":
        teile_txt.append("nächste Woche")
    elif monat:
        teile_txt.append(_MONAT_NAME.get(monat, ""))
    if tag:
        teile_txt.append(tag)
    if tz and tz not in ("morgen", "uebermorgen", "heute"):
        teile_txt.append(tz)
    if uhr:
        teile_txt.append(uhr)
    return " ".join(x for x in teile_txt if x)


def wunschzeit(text: str, heute: date | None = None) -> str:
    return teile(text, heute=heute)["text"]


def wunsch_mischen(alt: str, neu: str, heute: date | None = None) -> str:
    """Neue Komponente ersetzt die alte gleichen Typs. Monat bleibt bei nur-Wochentag."""
    heute = heute or HEUTE
    a, n = teile(alt, heute), teile(neu, heute)
    if not n["text"]:
        return a["text"]
    if not a["text"]:
        return n["text"]
    tag = n["wochentag"] or a["wochentag"]
    tz = n["tageszeit"] or a["tageszeit"]
    if n["monat"] or n["relativ"] in {
        "naechster_monat", "dieser_monat", "uebernaechster_monat",
    }:
        monat, jahr, relativ = n["monat"], n["jahr"], n["relativ"]
    else:
        monat, jahr, relativ = a["monat"], a["jahr"], a["relativ"]
    return _kanon(tag, tz, monat, jahr, relativ)


def fenster(text: str, heute: date | None = None) -> tuple[date | None, date | None]:
    """Inklusives Datumsfenster oder (None, None)."""
    heute = heute or HEUTE
    d = teile(text, heute)
    if d["relativ"] == "naechste_woche":
        # Nächster Montag bis Sonntag.
        delta = (7 - heute.weekday()) % 7
        if delta == 0:
            delta = 7
        start = heute + timedelta(days=delta)
        return start, start + timedelta(days=6)
    if d["monat"] and d["jahr"]:
        import calendar
        letzter = calendar.monthrange(d["jahr"], d["monat"])[1]
        von = date(d["jahr"], d["monat"], 1)
        bis = date(d["jahr"], d["monat"], letzter)
        if d["relativ"] == "dieser_monat":
            von = max(von, heute)
        return von, bis
    return None, None


def slot_datum(label: str, heute: date | None = None) -> date | None:
    heute = heute or HEUTE
    m = _SLOT_DAT.search(str(label) or "")
    if not m:
        return None
    tag, monat = int(m.group(1)), int(m.group(2))
    try:
        d = date(heute.year, monat, tag)
    except ValueError:
        return None
    if d < heute.replace(day=1) and monat < heute.month:
        try:
            d = date(heute.year + 1, monat, tag)
        except ValueError:
            return None
    return d


def passt_slot(label: str, wish: str, heute: date | None = None) -> bool:
    heute = heute or HEUTE
    d = teile(wish, heute)
    if not d["text"]:
        return True
    lab = falt(label)
    if d["wochentag"] and falt(d["wochentag"]) not in lab:
        return False
    if d["tageszeit"] == "nachmittag":
        if not any(x in lab for x in ("14:", "15:", "16:", "17:", "18:", "19:")):
            return False
    elif d["tageszeit"] == "vormittag":
        if not any(x in lab for x in ("08:", "09:", "10:", "11:", "12:")):
            return False
    von, bis = fenster(wish, heute)
    if von and bis:
        sd = slot_datum(label, heute)
        if sd is None or sd < von or sd > bis:
            return False
    return True


def besuchsgrund(text: str) -> str:
    t = falt(text)
    for stich, kanon in _GRUND:
        if falt(stich) in t:
            return kanon
    for w in _toks(text):
        for stich, kanon in _GRUND:
            if " " in stich:
                continue
            if _token_ist(w, (stich,), 2):
                return kanon
    return ""


def feld_name(text: str) -> str:
    t = str(text or "")
    for rx, feld in _FELD:
        if rx.search(t):
            return feld
    return ""


def feld_allein(text: str) -> str:
    """Nur wenn der Satz im Kern der Feldname ist (»den Grund«)."""
    toks = [w for w in _toks(text) if w not in {
        "den", "der", "die", "das", "ein", "eine",
        "bitte", "doch", "mal", "denn",
    }]
    if len(toks) > 3:
        return ""
    return feld_name(text)


__all__ = [
    "HEUTE", "besuchsgrund", "falt", "feld_allein", "feld_name",
    "fenster", "passt_slot", "slot_datum", "teile",
    "tageszeit", "wochentag", "wunsch_mischen", "wunschzeit",
]
