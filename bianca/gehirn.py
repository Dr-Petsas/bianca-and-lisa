"""Biancas Session-Gehirn: mehrturniger Sammler für die Terminbuchung.

Jeder Anrufer-Satz läuft durch ALLE Deuter (Arzt, Grund, Wunschzeit, Name,
Buchstabierung, Telefon, Ja/Nein) — egal, was gerade gefragt war. Wer alles
in einem Satz sagt ("Müller hier, ich brauche nächste Woche vormittags eine
Kontrolle"), überspringt die Fragen. Was fehlt, wird in fester Reihenfolge
nachgefragt: erst "Waren Sie schon bei uns — und bei wem?", dann Grund,
Wunschzeit, Name (buchstabiert), Handynummer (rückbestätigt).

Rein und ohne Netz: die Kartei-Suche und die Slot-Suche stößt flow/hintergrund
an — hier wird nur Zustand gehalten und die nächste Frage bestimmt.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bianca import arzt as arztmod
from bianca import besuchsgrund, buchstaben, telefon
from kern.slots import parse_slot_wish

TZ = ZoneInfo("Europe/Berlin")

_JA_RE = re.compile(
    r"^\s*(ja|jaja|jap|jep|jup|jupp|jopp|jo|joa|jou|jau|yep|yes|jawohl|jawoll|genau|richtig|korrekt|stimmt|passt|klar|gerne|okay|ok|sicher|natürlich|natuerlich)\b",
    re.I,
)
_NEIN_RE = re.compile(r"^\s*(nein|nee|nö|noe|falsch|stimmt nicht|nicht ganz|leider nicht)\b", re.I)
# Kurz-Verneinungen als GANZE Aeusserung: "Noch nicht." auf "Waren Sie schon
# mal bei uns?" ist ein Nein (live 27.08. 14:53: fiel durch, Frage kam doppelt).
_NEIN_KURZ_RE = re.compile(
    r"^\s*(noch\s+nicht|noch\s+nie|bisher\s+nicht|bis\s+jetzt\s+nicht|"
    r"eigentlich\s+nicht|eher\s+nicht|leider\s+nein)\s*[.!…]*\s*$",
    re.I,
)
# Kurz-Zustimmungen als GANZE Aeusserung ("Stark.", "Super!", "Sehr gut") —
# bewusst nur als Voll-Treffer: "Gut, aber ..." ist KEINE glatte Zustimmung.
_JA_KURZ_RE = re.compile(
    r"^\s*(stark|super|perfekt|prima|top|klasse|wunderbar|bestens|schön|schoen|"
    r"sehr\s+gut|gut|in\s+ordnung|einverstanden|von\s+mir\s+aus|meinetwegen|gebongt)\s*[.!…]*\s*$",
    re.I,
)
# Zwischenfrage/Abschweifung des Anrufers ("Was kostet das?", "Wo parke ich?"):
# geht ans LLM und zaehlt NIE als Leerlauf Richtung Eskalation (Chef 27.08.:
# "Abschweifungen muessen erlaubt sein"). Nackte Fragewoerter zaehlen NUR am
# Satzanfang — "B wie Berta" (Buchstabieren) und "wie gesagt" sind KEINE Fragen.
_ZWISCHENFRAGE_START_RE = re.compile(
    r"^\s*(?:(?:und|aber|ach|ja|sag(?:en)?\s+(?:sie\s+)?mal|mal\s+(?:eine|ne)\s+frage|"
    r"eine\s+frage|kurze\s+frage|noch\s+(?:eine|ne)\s+frage)\b[\s,:—-]*)*"
    r"(?:was|wie(?!\s+(?:gesagt|besprochen|immer|vorhin|üblich|ueblich|abgemacht))|"
    r"wann(?!\s+(?:sie|es|ihr|du)\b)|wo|wohin|woher|wer|warum|wieso|weshalb|wozu|"
    r"welche[rsnm]?|wieviel|wie\s+viele?)\b",
    re.I,
)
_ZWISCHENFRAGE_KERN_RE = re.compile(
    r"\?|"
    r"\b(kostet|kosten|preis|preise|gebühr|gebuehr|gibt\s+es|gibts|"
    r"haben\s+sie|habt\s+ihr|kann\s+ich|könnte\s+ich|koennte\s+ich|darf\s+ich|"
    r"muss\s+ich|müsste\s+ich|muesste\s+ich|sollte?\s+ich|wie\s+lange|dauert|"
    r"parken|parkplatz|parkplätze|parkplaetze|barrierefrei|rollstuhl|aufzug|"
    r"versicherung|krankenkasse|privatpatient|selbstzahler|"
    r"betäubung|betaeubung|nüchtern|nuechtern|mitbringen|unterlagen)\b",
    re.I,
)
# "Äh, nein." / "Also ja" / "Hm, nee" — Füllwörter vor dem Ja/Nein abstreifen
# (live 27.08.2026: "Äh, nein" wurde NICHT als Nein erkannt, die Zustands-
# maschine blieb auf der Frage hängen und das LLM übernahm mit Fantasie).
# "hier"/"naja" gehören dazu: "Äh, hier nein" fiel live (27.08. 18:10) durch
# und die Schonmal-Frage kam doppelt.
_ANLAUF_RE = re.compile(
    r"^\s*(?:(?:äh+m*|aeh+m*|hm+|mh+m*|also|na|naja|nun|tja|ach|och|oh|boah|puh|hier|ähm|öhm)\b[\s,.!—-]*)+",
    re.I,
)

_TERMIN_RE = re.compile(
    r"termin|vorbeikommen|ausmachen|vereinbaren|buchen|kontroll|schmerz|zahnweh|"
    r"zahnreinigung|prophylaxe|reinigung|wurzel|implantat|krone|füllung|fuellung|"
    r"abgebrochen|vorsorge|untersuchung",
    re.I,
)
_ABSAGE_RE = re.compile(
    r"absagen|abzusagen|stornieren|storniert|abbestellen|canceln|"
    r"nicht\s+(kommen|wahrnehmen|schaffen|einhalten)|"
    # Trennbares Verb: "ich sage den Termin ab" / "sag ihn bitte ab" — aber
    # NICHT "können Sie mir sagen, ab wann ..." (Auskunftsfrage).
    r"\bsag\w*\s+(?:ich\s+|wir\s+|sie\s+)?(?:den\s+|meinen\s+|diesen\s+|ihn\s+|sie\s+|bitte\s+|doch\s+|wieder\s+|einfach\s+|lieber\s+|gerne\s+|gleich\s+|sofort\s+)*(?:termin\s+)?(?:doch\s+|wieder\s+|bitte\s+|einfach\s+|lieber\s+|gerne\s+|gleich\s+|sofort\s+)*ab\b(?!\s*(?:wann|wie|welch))",
    re.I,
)
_VERSCHIEBEN_RE = re.compile(
    r"verschieben|verschoben|umbuchen|umzubuchen|verlegen|umlegen|vorverlegen|"
    r"nach\s+hinten\s+schieben|anderen\s+tag\s+.{0,16}(statt|als)\b",
    re.I,
)
_AUSKUNFT_RE = re.compile(
    r"wann\s+(ist|war|wäre|waere|hab(e)?\s+ich)\b.{0,30}termin|"
    r"hab(e)?\s+ich\s+(überhaupt\s+|ueberhaupt\s+)?(noch\s+)?(irgend)?einen\s+termin|"
    r"welche[nr]?\s+termin(e)?\s+(hab|steht|stehen)|"
    r"termin\s+(nochmal|noch\s+mal|nochmals)\s*(sagen|nennen|durchgeben)?|"
    r"wann\s+(muss|soll|darf)\s+ich\s+(kommen|da\s+sein|vorbeikommen)|"
    r"wann\s+bin\s+ich\s+(dran|eingetragen)",
    re.I,
)
_SCHONMAL_JA_RE = re.compile(
    r"(war|bin|waren)\s+(schon|bereits|öfter|oefter|mal|einmal|früher|frueher)[^.]{0,40}(bei\s+(ihnen|euch)|da|dort|in\s+der\s+praxis)|"
    r"bin\s+(schon\s+)?patient|bin\s+bei\s+ihnen\s+in\s+behandlung",
    re.I,
)
# "bin neu" braucht die Wortgrenze und darf Fuellwoerter tragen: ohne \b traf
# der Ausdruck auch "bin NEUmann" (echter Nachname!), und "bin GANZ neu bei
# euch" fiel durch (live 27.08.2026: "Ich bin neu bei Ihnen" -> "Danke, Neu
# Ihnen").
_SCHONMAL_NEIN_RE = re.compile(
    r"noch\s+nie|zum\s+ersten\s+mal|das\s+erste\s+mal|"
    r"bin\s+(?:ganz\s+|völlig\s+|voellig\s+|hier\s+|noch\s+)*neu\b|"
    r"noch\s+kein\s+patient|noch\s+nicht\s+bei\s+(ihnen|euch)",
    re.I,
)
_ARZT_KONTEXT_RE = re.compile(r"arzt|ärztin|aerztin|behandler|doktor|dr\.|bei\s+wem|zu\s+wem", re.I)
_FUER_WEN_RE = re.compile(
    r"für\s+mein(?:e|en)?\s+(tochter|sohn|mann|frau|mutter|vater|kind|oma|opa)", re.I
)
_NAME_LEADIN_RE = re.compile(
    r"(?:mein\s+name\s+ist|ich\s+heiße|ich\s+heisse|hier\s+(?:ist|spricht)|ich\s+bin)\s+([A-Za-zÄÖÜäöüß' -]{2,60})",
    re.I,
)
_NAME_STOP = {
    "und", "der", "die", "das", "ein", "eine", "herr", "frau", "doktor", "dr",
    "mein", "name", "ist", "hier", "spricht", "ich", "bin", "heiße", "heisse",
    "guten", "tag", "morgen", "hallo", "von", "aus", "am", "apparat",
    # "Auch Paul" (Antwort auf die Vornamens-Frage) darf keinen Vornamen
    # "Auch" erzeugen (live 27.08.2026) — dito weitere Füllwörter.
    "auch", "ebenfalls", "genau", "also", "wieder", "nochmal", "eben",
    "ähm", "äh", "aeh", "aehm", "halt", "wie", "gesagt",
    # Korrektur-Einstiege sind NIE Namen: "Nee, der Vorname ist Paul" wurde
    # live (27.08.2026) als "Nee Paul" geerntet.
    "nee", "nein", "nö", "noe", "ne", "doch", "falsch", "moment", "sekunde",
    "vorname", "nachname", "familienname", "lautet",
}
# Gängige Vornamen (nur zur Zuordnung "ein einzelnes Wort = eher Vorname?").
# Live 27.08.2026: die Antwort "Paul?" auf die Namensfrage wurde als NACHNAME
# geführt und der Anrufer als "Herr Paul" angesprochen.
_VORNAMEN = {
    "alexander", "andreas", "anna", "anne", "anja", "antje", "barbara", "bernd",
    "birgit", "brigitte", "carsten", "christian", "christina", "christine",
    "claudia", "daniel", "daniela", "david", "dennis", "dieter", "dirk",
    "dominik", "doris", "elena", "elias", "elke", "emil", "emma", "erik",
    "eva", "felix", "finn", "florian", "frank", "franz", "frieda", "gabriele",
    "georg", "gerhard", "gisela", "hanna", "hannah", "hans", "heike", "heinz",
    "helga", "henry", "holger", "ingrid", "jan", "jana", "jens", "joachim",
    "johann", "johanna", "johannes", "jonas", "julia", "julian", "jürgen",
    "juergen", "kai", "karin", "karl", "katharina", "kathrin", "katja",
    "kerstin", "kevin", "klaus", "kurt", "lara", "laura", "lea", "lena",
    "leon", "leonie", "lisa", "luca", "luis", "luise", "lukas", "manfred",
    "manuela", "marc", "marcel", "marco", "maria", "marie", "mario", "marion",
    "markus", "martin", "martina", "mathias", "matthias", "max", "maximilian",
    "melanie", "mia", "michael", "michaela", "mila", "monika", "moritz",
    "nadine", "nicole", "niklas", "nina", "noah", "nora", "olaf", "oliver",
    "otto", "patrick", "paul", "paula", "peter", "petra", "philipp", "ralf",
    "regina", "renate", "richard", "robert", "rolf", "rudolf", "sabine",
    "sandra", "sara", "sarah", "sebastian", "silke", "simon", "simone",
    "sofia", "sophie", "stefan", "stefanie", "steffen", "susanne", "sven",
    "tanja", "theo", "thomas", "thorsten", "tim", "tobias", "tom", "torsten",
    "ulrich", "ulrike", "ursula", "uwe", "vanessa", "verena", "walter",
    "werner", "wolfgang", "yvonne",
}
# Explizite Zuweisungen schlagen alles: "der Vorname ist Paul", "Panzer ist
# der Nachname". Erfasst wird genau EIN Wort — sonst frisst der Ausdruck
# "Paul und der Nachname ist Panzer" komplett (live 27.08.2026: "Nee Paul").
_TEIL_VOR_RE = re.compile(
    r"(?:der\s+|mein\s+)?vorname\s+(?:ist|lautet|wäre|waere)\s+([A-Za-zÄÖÜäöüß'-]{2,})", re.I)
_TEIL_NACH_RE = re.compile(
    r"(?:der\s+|mein\s+)?(?:nachname|familienname|zuname)\s+(?:ist|lautet|wäre|waere)\s+([A-Za-zÄÖÜäöüß'-]{2,})", re.I)
_TEIL_VOR_UMGEKEHRT_RE = re.compile(
    r"([A-Za-zÄÖÜäöüß'-]{2,})\s+(?:ist|wäre|waere)\s+(?:der\s+|mein\s+)?vorname", re.I)
_TEIL_NACH_UMGEKEHRT_RE = re.compile(
    r"([A-Za-zÄÖÜäöüß'-]{2,})\s+(?:ist|wäre|waere)\s+(?:der\s+|mein\s+)?(?:nachname|familienname|zuname)", re.I)
# Korrekturen ÜBERSCHREIBEN sofort (Chef 27.08.2026: "das war falsch, ich
# heiße Meier nicht Müller" -> Gedächtnis augenblicklich aktualisieren,
# NIE noch einmal fragen). Neu = das Bejahte, Alt = das Verneinte.
_NAME_FALSCH_RE = re.compile(
    r"(?:heiße|heisse|heißen|heissen|schreibt\s+sich|name\s+ist|richtig\s+ist|richtig\s+wäre|richtig\s+waere)\s+"
    r"([A-Za-zÄÖÜäöüß'-]{2,})\s*[,.]?\s*(?:und\s+)?nicht\s+([A-Za-zÄÖÜäöüß'-]{2,})", re.I)
_NAME_SONDERN_RE = re.compile(
    r"nicht\s+([A-Za-zÄÖÜäöüß'-]{2,})\s*[,.]?\s*sondern\s+([A-Za-zÄÖÜäöüß'-]{2,})", re.I)
_KORREKTUR_KONTEXT_RE = re.compile(
    r"falsch|vertan|verhört|verhoert|versprochen|verwechselt|korrigier|irrtum|stimmt\s+nicht|meinte", re.I)
_TEL_FALSCH_RE = re.compile(
    r"(?:nummer|handy|telefon)[^.!?]{0,40}(?:falsch|stimmt\s+nicht|nicht\s+richtig|verkehrt)|"
    r"falsche\s+(?:nummer|handynummer|telefonnummer)", re.I)
# Neupatient-/Schonmal-Floskeln und ZUSTAENDE sind KEINE Namen: "Ich bin neu
# bei Ihnen" wurde live als Name geerntet ("Danke, Neu Ihnen" — 27.08.2026),
# "ich bin ganz aufgeregt" als "Ganz Aufgeregt" (Talk-Probe 27.08.2026). Der
# ganze Floskel-Teilsatz fliegt VOR der Namens-Ernte raus; ein echter Name im
# selben Satz ("..., mein Name ist Paul Neumann") bleibt erhalten, ebenso
# "Ich bin Paul Neumann" und der Nachname "Neu" (Wortgrenze nach "neu").
# Zustandswoerter, die auch Nachnamen sein koennen (Sauer, Krank, Froh),
# stehen BEWUSST nicht in der Liste.
_KEIN_NAME_RE = re.compile(
    r"(?:ich\s+|wir\s+)?(?:bin|war(?:en)?)\s+"
    r"(?:auch\s+|übrigens\s+|uebrigens\s+|leider\s+|ja\s+|gerade\s+|heute\s+)*"
    r"(?:ganz\s+|völlig\s+|voellig\s+|hier\s+|noch\s+|sehr\s+|so\s+|total\s+|"
    r"richtig\s+|echt\s+|etwas\s+|schon\s+|wirklich\s+)*"
    r"(?:neu\b|noch\s+nie\b|zum\s+ersten\s+mal\b|das\s+erste\s+mal\b|"
    r"aufgeregt|nervös|nervoes|gespannt|begeistert|erleichtert|verzweifelt|"
    r"durcheinander|erkältet|erkaeltet|müde|muede|erschöpft|erschoepft|"
    r"gestresst|genervt|verwirrt|unterwegs|beschäftigt|beschaeftigt|"
    r"spät\b|spaet\b|zufrieden|unzufrieden|glücklich|gluecklich|traurig|"
    r"wütend|wuetend|verheiratet|geschieden|schwanger|aufgeschmissen)[^,.!?]*",
    re.I,
)
_AKTE_NUMMER_RE = re.compile(
    r"(nummer|handy|telefon)[^.]{0,50}(akte|hinterlegt|haben\s+sie\s+(ja|doch|schon|bereits))|"
    r"steht\s+(ja\s+|doch\s+)?in\s+der\s+akte|"
    r"(gleiche|selbe|alte)\s+nummer|nummer\s+wie\s+immer",
    re.I,
)

# Frei Gesprochenes -> Besuchsgrund aus der Behandler-Liste: bianca/besuchsgrund.py
# (Konzept-Erkennung + Motiv-Suche mit "klein"-Präferenz, Chef 27.08.2026).

FELDER_START = {
    "modus": "",
    "phase": "",
    "frage": "",
    "warSchonMal": None,
    "arzt": None,
    "grund": "",
    "motivId": "",
    "motivName": "",
    "wunsch": None,
    "wunschText": "",
    "vorname": "",
    "nachname": "",
    "buchstabiert": False,
    "grundWortlaut": "",
    "telefon": "",
    "telefonOffen": "",
    "telefonTeil": "",
    "telefonOk": False,
    "telefonAkte": False,
    "patientId": "",
    "bekannt": False,
    "aktePhone": "",
    "gesucht": "",
    "fuerWen": "",
    "slotIso": "",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def sammler(sit: dict) -> dict:
    s = sit.setdefault("sammler", {})
    for k, v in FELDER_START.items():
        s.setdefault(k, v)
    return s


def _ohne_anlauf(text: str) -> str:
    return _ANLAUF_RE.sub("", _s(text))


def ist_ja(text: str) -> bool:
    k = _ohne_anlauf(text)
    return bool(_JA_RE.search(k) or _JA_KURZ_RE.match(k))


def ist_nein(text: str) -> bool:
    k = _ohne_anlauf(text)
    if _NEIN_RE.search(k) or _NEIN_KURZ_RE.match(k):
        return True
    # Kurze Äußerung mit klarem Nein-Wort irgendwo ("glaube nein", "hier nein"):
    # bei <= 3 Wörtern gibt es keinen Kontext, der das Nein umdrehen könnte.
    toks = re.sub(r"[.,!?…]+", " ", k.lower()).split()
    return len(toks) <= 3 and any(t in {"nein", "nee", "nö", "noe"} for t in toks)


def ist_zwischenfrage(text: str) -> bool:
    """Stellt der Anrufer selbst eine Frage / schweift er ab?"""
    k = _ohne_anlauf(text)
    return bool(_ZWISCHENFRAGE_KERN_RE.search(k) or _ZWISCHENFRAGE_START_RE.match(k))


def _relatives_datum(t: str) -> str:
    heute = datetime.now(TZ).date()
    if re.search(r"\bübermorgen|uebermorgen\b", t):
        return (heute + timedelta(days=2)).isoformat()
    if re.search(r"\bmorgen\b", t):
        return (heute + timedelta(days=1)).isoformat()
    if re.search(r"\bheute\b", t):
        return heute.isoformat()
    return ""


def _wunsch_deuten(text: str) -> dict | None:
    """parse_slot_wish plus relative Tage — None, wenn der Satz nichts Zeitliches hat."""
    wish = parse_slot_wish(text) or {}
    rel = _relatives_datum(f" {_s(text).lower()} ")
    if rel and not wish.get("date"):
        wish["date"] = rel
    gehaltvoll = any([
        wish.get("date"), wish.get("weekday") is not None, wish.get("hour") is not None,
        wish.get("hourMin") is not None, wish.get("minDaysAhead"),
    ])
    return wish if gehaltvoll else None


def _wunsch_mischen(alt: dict | None, neu: dict) -> dict:
    """Mehrturnig: 'nächste Woche' + später 'vormittags' ergibt EINEN Wunsch."""
    out = dict(alt or {})
    for k, v in neu.items():
        if v not in (None, 0, ""):
            out[k] = v
    for k in ("weekday", "hourMin", "hourMax", "hour", "minDaysAhead", "date"):
        out.setdefault(k, None if k not in ("minDaysAhead",) else 0)
    return out


def _grund_deuten(tenant: dict, text: str) -> tuple[str, dict | None]:
    return besuchsgrund.deute(tenant, text)


def _name_tokens(text: str) -> list[str]:
    raw = re.sub(r"[^\wäöüßÄÖÜ' -]+", " ", _s(text))
    return [t for t in raw.split() if t.lower() not in _NAME_STOP and len(t) >= 2 and not t.isdigit()]


_NACHSPRECH_STOP = _NAME_STOP | {
    "mal", "kurz", "warte", "warten", "augenblick", "bitte", "langsam",
    "buchstabieren", "gerne", "okay", "gleich", "sofort", "was", "wieso",
}


def _nachgesprochen(text: str) -> str:
    """Auf die Buchstabier-Frage den Namen NOCHMAL gesprochen statt buchstabiert.

    STT zerlegt lange Namen gern in Silbenblöcke ("MATTA VATTA" statt
    Mattavatta, live 27.08.2026). Ein bis zwei reine Wort-Tokens ohne
    Füllwörter werden als Nachname übernommen — alles andere bleibt beim
    LLM bzw. der Eskalation.
    """
    if ist_ja(text) or ist_nein(text) or ist_zwischenfrage(text):
        return ""
    raw = re.sub(r"[^\wäöüßÄÖÜ-]+", " ", _s(text))
    toks = [t for t in raw.split() if t]
    if not 1 <= len(toks) <= 2:
        return ""
    if any(t.lower() in _NACHSPRECH_STOP or t.isdigit() or len(t) < (3 if len(toks) == 2 else 4) for t in toks):
        return ""
    zusammen = "".join(toks)
    if not zusammen.isalpha() or not 4 <= len(zusammen) <= 20:
        return ""
    return zusammen.capitalize()


def _kartei_zuruecksetzen(s: dict) -> None:
    """Nach einer Namens-Korrektur ist der Kartei-Treffer hinfällig —
    die Hintergrund-Suche läuft mit dem richtigen Namen neu an."""
    s["patientId"] = ""
    s["bekannt"] = False
    s["aktePhone"] = ""
    s["gesucht"] = ""


def _name_korrektur(s: dict, text: str) -> bool:
    """"Ich heiße Meier, nicht Müller" / "nicht Müller, sondern Meier":
    sofort übernehmen — auch wenn der Name längst gespeichert ist."""
    neu_wert, alt_wert = "", ""
    m = _NAME_FALSCH_RE.search(text)
    if m:
        neu_wert, alt_wert = m.group(1), m.group(2)
    else:
        m = _NAME_SONDERN_RE.search(text)
        if m:
            alt_wert, neu_wert = m.group(1), m.group(2)
            # "nicht Patrikis, sondern Petsas" meint den ARZT: nur als
            # Patientenname werten, wenn das Verneinte wirklich einer der
            # gespeicherten Namensteile ist oder es klar um den Namen geht.
            if _ARZT_KONTEXT_RE.search(text):
                gespeichert = {s["vorname"].lower(), s["nachname"].lower()} - {""}
                if alt_wert.lower() not in gespeichert:
                    return False
    if not m or not neu_wert:
        # "Das war falsch — ich heiße Paul Meier": Korrektur-Kontext plus
        # normale Namensnennung überschreibt ebenfalls.
        if _KORREKTUR_KONTEXT_RE.search(text):
            lead = _NAME_LEADIN_RE.search(text)
            toks = _name_tokens(lead.group(1)) if lead else []
            if toks:
                if len(toks) >= 2:
                    s["vorname"] = toks[0].capitalize()
                    alt_nach = s["nachname"]
                    s["nachname"] = toks[-1].capitalize()
                else:
                    alt_nach = s["nachname"]
                    s["nachname"] = toks[0].capitalize()
                if s["nachname"] != alt_nach:
                    s["buchstabiert"] = False
                    _kartei_zuruecksetzen(s)
                return True
        return False
    if neu_wert.lower() in _NAME_STOP or alt_wert.lower() in _NAME_STOP:
        return False
    neu_name = neu_wert.capitalize()
    alt = alt_wert.lower()
    if alt == s["vorname"].lower() and s["vorname"]:
        s["vorname"] = neu_name
        if s["patientId"] or s["bekannt"]:
            _kartei_zuruecksetzen(s)
        return True
    # Standard: der Nachname wird korrigiert (auch wenn "alt" nur ähnlich
    # klingt wie das Gespeicherte — STT hatte ja gerade falsch gehört).
    if s["nachname"] and neu_name != s["nachname"]:
        s["buchstabiert"] = False
        _kartei_zuruecksetzen(s)
    s["nachname"] = neu_name
    return True


def _name_aufnehmen(s: dict, text: str, *, erzwungen: bool) -> bool:
    """Vor-/Nachname aus dem Satz ziehen. erzwungen=True: die Frage war der Name."""
    text = _s(_KEIN_NAME_RE.sub(" ", text))
    if not text:
        return False

    # Explizite Zuweisung gewinnt IMMER und darf Falsches überschreiben:
    # "Nee, der Vorname ist Paul und der Nachname ist Panzer" (live 27.08.2026
    # als "Nee Paul" verbucht). Ein neuer Nachname macht die alte
    # Buchstabierung ungültig.
    getroffen = False
    mv = _TEIL_VOR_RE.search(text) or _TEIL_VOR_UMGEKEHRT_RE.search(text)
    if mv and mv.group(1).lower() not in _NAME_STOP:
        s["vorname"] = mv.group(1).capitalize()
        getroffen = True
    mn = _TEIL_NACH_RE.search(text) or _TEIL_NACH_UMGEKEHRT_RE.search(text)
    if mn and mn.group(1).lower() not in _NAME_STOP:
        neu_nach = mn.group(1).capitalize()
        if s["nachname"] and neu_nach != s["nachname"]:
            s["buchstabiert"] = False
            _kartei_zuruecksetzen(s)
        elif neu_nach != s["nachname"]:
            s["buchstabiert"] = False
        s["nachname"] = neu_nach
        getroffen = True
    if getroffen:
        return True

    m = _NAME_LEADIN_RE.search(text)
    kandidat = m.group(1) if m else (text if erzwungen else "")
    toks = _name_tokens(kandidat)
    if not toks:
        return False
    if m is None and erzwungen and len(toks) > 3:
        # Ganze-Satz-Rueckfall NUR fuer namensartige Antworten: Wer auf die
        # Namensfrage eine Geschichte erzaehlt ("Ach, wissen Sie — meine
        # Tochter heiratet naemlich!"), nennt keinen Namen — das gehoert der
        # Talk-Schicht, nicht der Kartei (Talk-Probe 27.08.2026).
        return False
    if s["frage"] == "vorname" and erzwungen:
        s["vorname"] = toks[0].capitalize()
        return True
    if s["frage"] == "nachname" and erzwungen:
        s["nachname"] = toks[-1].capitalize()
        s["buchstabiert"] = False
        return True
    if len(toks) >= 2:
        s["vorname"] = toks[0].capitalize()
        s["nachname"] = toks[-1].capitalize()
        return True
    if erzwungen:
        # Nur EIN Wort auf die Namensfrage: gängige Vornamen (Paul, Anna …)
        # sind der VORNAME — alles andere führen wir als Nachnamen. Live
        # 27.08.2026 wurde "Paul?" als Nachname geführt ("Herr Paul").
        if toks[0].lower() in _VORNAMEN and not s["vorname"]:
            s["vorname"] = toks[0].capitalize()
        else:
            s["nachname"] = toks[0].capitalize()
        return True
    return False


def einsammeln(sit: dict, text: str) -> set[str]:
    """Alle Deuter über den Satz laufen lassen; liefert die neu gefüllten Felder."""
    s = sammler(sit)
    t = _s(text)
    tl = f" {t.lower()} "
    neu: set[str] = set()
    if not t:
        return neu

    # Anliegen-Modus: absagen/verschieben/auskunft VOR der Buchungs-Erkennung
    # prüfen — "Ich möchte meinen Termin absagen" enthält auch "Termin".
    # Läuft schon ein Angebot im Buchungsfluss, bezieht sich "absagen"/
    # "verschieben" auf das Angebot, nicht auf einen Bestandstermin.
    im_angebot = s["modus"] == "buchen" and s["phase"] in {"angebot", "bestaetigen"}
    if not im_angebot:
        if _VERSCHIEBEN_RE.search(t):
            if s["modus"] != "verschieben":
                s["modus"] = "verschieben"
                s["phase"] = ""
                s["frage"] = ""
                neu.add("modus")
        elif _ABSAGE_RE.search(t):
            if s["modus"] != "absagen":
                s["modus"] = "absagen"
                s["phase"] = ""
                s["frage"] = ""
                neu.add("modus")
        elif _AUSKUNFT_RE.search(t):
            if s["modus"] in {"", "buchen"} and s["phase"] in {"", "gebucht", "fertig"}:
                s["modus"] = "auskunft"
                s["phase"] = ""
                s["frage"] = ""
                neu.add("modus")
        elif _TERMIN_RE.search(t):
            # Neu buchen: aus dem Leeren — oder nach abgeschlossener
            # Verwaltung ("fertig": Storno erledigt, Auskunft gegeben).
            if s["modus"] == "" or (s["modus"] != "buchen" and s["phase"] == "fertig"):
                s["modus"] = "buchen"
                s["phase"] = ""
                s["frage"] = ""
                neu.add("modus")

    # Schon mal da gewesen?
    if _SCHONMAL_NEIN_RE.search(t):
        if s["warSchonMal"] is not False:
            s["warSchonMal"] = False
            neu.add("warSchonMal")
    elif _SCHONMAL_JA_RE.search(t):
        if s["warSchonMal"] is not True:
            s["warSchonMal"] = True
            neu.add("warSchonMal")
    elif s["frage"] == "schonmal":
        if ist_ja(t):
            s["warSchonMal"] = True
            neu.add("warSchonMal")
        elif ist_nein(t):
            s["warSchonMal"] = False
            neu.add("warSchonMal")

    # Behandler: ein Name zählt immer; "egal"/"weiß nicht" nur im Arzt-Kontext.
    tenant = sit.get("tenant") or {}
    gedeutet = arztmod.deute(t, tenant)
    if gedeutet:
        im_kontext = s["frage"] == "arzt" or _ARZT_KONTEXT_RE.search(t)
        if gedeutet["typ"] == "genannt":
            s["arzt"] = gedeutet
            s["warSchonMal"] = True if s["warSchonMal"] is None and _SCHONMAL_JA_RE.search(t) else s["warSchonMal"]
            neu.add("arzt")
        elif im_kontext and not (s["arzt"] or {}).get("calendarId"):
            s["arzt"] = gedeutet
            neu.add("arzt")

    # Für wen ist der Termin?
    fm = _FUER_WEN_RE.search(t)
    if fm and not s["fuerWen"]:
        s["fuerWen"] = fm.group(1).lower()
        neu.add("fuerWen")

    # Besuchsgrund: auf die Besuchsgrund-Liste des Behandlers mappen; der
    # WORTLAUT des Patienten bleibt für die Terminnotiz erhalten (Chef 27.08.).
    if not s["grund"]:
        kern_name, vm = _grund_deuten(tenant, t)
        if kern_name:
            s["grund"] = kern_name
            s["grundWortlaut"] = t if len(t) <= 120 else t[:117] + "…"
            if vm:
                s["motivId"] = _s(vm.get("id"))
                s["motivName"] = _s(vm.get("name"))
            neu.add("grund")
        elif s["frage"] == "grund" and len(t) >= 3 and not ist_ja(t) and not ist_nein(t):
            # Frei formulierter Grund ("Holzbein absägen"): Wortlaut behalten,
            # gebucht wird der Zweifelsfall-Grund (Kontrolle/Besprechung).
            s["grund"] = t if len(t) <= 90 else t[:87] + "…"
            s["grundWortlaut"] = s["grund"]
            vm = besuchsgrund.fallback_motiv(tenant)
            if vm:
                s["motivId"] = _s(vm.get("id"))
                s["motivName"] = _s(vm.get("name"))
            neu.add("grund")

    # Wunschzeit (mehrturnig gemischt)
    wish = _wunsch_deuten(t)
    if wish:
        s["wunsch"] = _wunsch_mischen(s["wunsch"], wish)
        s["wunschText"] = _s(f"{s['wunschText']} {t}") if s["wunschText"] else t
        neu.add("wunsch")

    # Buchstabierung schlägt den frei gehörten Nachnamen — auch wenn sie ihm
    # WIDERSPRICHT: wer buchstabiert, korrigiert gerade (live 27.08.2026:
    # "MATTA VATTA" gegen gespeichertes "Pidoq" — Bianca beharrte auf Pidoq).
    if _name_korrektur(s, t):
        neu.add("name")
    buch = buchstaben.deute(t)
    if "name" in neu:
        pass  # Korrektur hat Vorrang — nichts erneut ernten.
    elif buch and (s["frage"] in {"buchstabieren", "name", "nachname"} or not s["nachname"]):
        s["nachname"] = buch["name"]
        s["buchstabiert"] = True
        s["bekannt"] = False if s["frage"] == "buchstabieren" and not s["patientId"] else s["bekannt"]
        neu.add("nachname")
        # Im selben Satz kann der Vorname stecken: "… P-A-N-Z-E-R. Der
        # Vorname ist Paul" — nicht verschlucken (live 27.08.2026).
        mv = _TEIL_VOR_RE.search(t) or _TEIL_VOR_UMGEKEHRT_RE.search(t)
        if mv and mv.group(1).lower() not in _NAME_STOP:
            s["vorname"] = mv.group(1).capitalize()
    elif s["frage"] == "buchstabieren":
        nach = _nachgesprochen(t)
        if nach:
            # Statt zu buchstabieren hat der Anrufer den Namen (ggf. in
            # Silben: "MATTA VATTA") noch einmal gesprochen: übernehmen.
            if nach != s["nachname"]:
                s["bekannt"] = False if not s["patientId"] else s["bekannt"]
            s["nachname"] = nach
            s["buchstabiert"] = True
            neu.add("nachname")
        elif _name_aufnehmen(s, t, erzwungen=False):
            # "Der Nachname ist Panzer. P-A-N-Z-E-R. Der Vorname ist Paul":
            # explizite Zuweisungen zählen auch auf die Buchstabier-Frage.
            neu.add("name")
    elif s["frage"] in {"name", "vorname", "nachname"}:
        if _name_aufnehmen(s, t, erzwungen=True):
            neu.add("name")
    elif not s["nachname"] and _name_aufnehmen(s, t, erzwungen=False):
        neu.add("name")

    # Telefonnummer: gehört -> erst rückbestätigen, dann fest.
    if s["frage"] == "telefon_check":
        if ist_ja(t) and s["telefonOffen"]:
            s["telefon"] = s["telefonOffen"]
            s["telefonOk"] = True
            s["telefonOffen"] = ""
            neu.add("telefon")
        elif ist_nein(t):
            s["telefonOffen"] = ""
            neu.add("telefonKorrektur")
    d = telefon.aus_satz(t)
    if d and d != s["telefon"]:
        s["telefonOffen"] = d
        s["telefonTeil"] = ""
        s["telefonOk"] = False
        neu.add("telefonOffen")
    elif not d and s["frage"] in {"telefon", "telefon_check"} and not s["telefonOk"]:
        # Stückweise diktierte Nummer ("null eins sieben sieben" … Pause …
        # "sechshundert …"): Fragmente sammeln, bis die Kette plausibel ist.
        stueck = telefon.ziffern(t).replace("+", "")
        if 2 <= len(stueck) <= 13:
            if stueck.startswith("0") and len(stueck) >= 4:
                # Neue Nummer beginnt — der Anrufer setzt neu an.
                zusammen = stueck
            else:
                zusammen = (s["telefonTeil"] + stueck)[:16]
            if telefon.plausibel(zusammen):
                s["telefonOffen"] = telefon.normaliert(zusammen)
                s["telefonTeil"] = ""
                s["telefonOk"] = False
                neu.add("telefonOffen")
            else:
                s["telefonTeil"] = zusammen
                neu.add("telefonTeil")
    if not d and (s["telefon"] or s["telefonOffen"]) and _TEL_FALSCH_RE.search(t):
        # "Die Nummer war falsch": sofort verwerfen und neu erfragen —
        # ohne dass der Anrufer erst durch eine Rückbestätigung muss.
        s["telefon"] = ""
        s["telefonOk"] = False
        s["telefonOffen"] = ""
        s["telefonTeil"] = ""
        neu.add("telefonKorrektur")
    if not d and not s["telefonOk"] and not s["telefonAkte"] and _AKTE_NUMMER_RE.search(t):
        # "Meine Nummer haben Sie ja in der Akte" — nicht darauf beharren,
        # die Akten-Nummer (oder die Praxis-Nachpflege) übernimmt das.
        s["telefonAkte"] = True
        neu.add("telefonAkte")

    return neu


# Formulierungs-Varianten je Pflichtfrage für den Wiederholungs-Wächter
# (kern/wiederholung.py): muss dieselbe Frage erneut gestellt werden, kommt
# die nächste Form — nie zweimal derselbe Wortlaut (Chef 27.08.2026: "nie
# wieder doppelte telefonnummer oder behandler abfragen"). JEDE Variante
# trägt die Kern-Wörter aus agent._FRAGE_KERN, damit Anker/Wachen sie
# weiter als die offene Frage erkennen. telefon_check hat BEWUSST keine
# Varianten — die Rückbestätigung bleibt deterministisch.
FRAGE_VARIANTEN: dict[str, tuple[str, ...]] = {
    "schonmal": (
        "Waren Sie schon einmal bei uns?",
        "Kurz zur Einordnung: Waren Sie schon mal in unserer Praxis?",
    ),
    "arzt": (
        "Bei welchem Behandler waren Sie zuletzt?",
        "Wissen Sie den Namen Ihres Behandlers noch?",
    ),
    "name": (
        "Sagen Sie mir bitte noch Ihren Namen — Vor- und Nachname?",
        "Auf welchen Namen darf ich das aufnehmen?",
    ),
    "vorname": (
        "Wie ist Ihr Vorname?",
        "Welchen Vornamen darf ich notieren?",
    ),
    "nachname": (
        "Wie lautet der Nachname?",
        "Welchen Nachnamen darf ich eintragen?",
    ),
    "grund": (
        "Was ist denn der Grund für Ihren Besuch?",
        "Um welches Anliegen geht es denn?",
    ),
    "wunsch": (
        "Wann würde es Ihnen denn gut passen — eher vormittags oder nachmittags?",
        "Ab welchem Tag passt es Ihnen — und lieber vormittags oder nachmittags?",
    ),
    "buchstabieren": (
        "Buchstabieren Sie mir den Nachnamen bitte einmal?",
        "Mögen Sie den Nachnamen kurz buchstabieren?",
    ),
    "telefon": (
        "Welche Handynummer darf ich eintragen?",
        "Sagen Sie mir bitte noch Ihre Handynummer?",
    ),
    "slotwahl": (
        "Welcher davon passt Ihnen?",
        "Welcher der Termine passt Ihnen am besten?",
    ),
    "bestaetigung": (
        "Darf ich den Termin so eintragen?",
        "Soll ich es so festhalten?",
    ),
}


def feste_saetze() -> list[str]:
    """Alle festen Maschinen-Sätze für den TTS-Platten-Cache (28.08.2026).

    Die Buchungs-Maschine spricht diese Fragen wörtlich (naechste_frage
    unten, plus die Wiederholungs-Varianten). Sie tragen NIE Patientendaten
    und dürfen deshalb wie Füller und Begrüßung dauerhaft gecacht werden —
    aus dem Cache antwortet die Maschine in ~0,2 s statt einer vollen
    lokalen Synthese (~1,2 s). Bei Textänderungen in naechste_frage HIER
    mitziehen (test_feste_saetze prüft das per Quelltext-Abgleich); ein
    vergessener Satz ist nur langsamer, nie falsch.
    """
    erstformen = [
        "Waren Sie denn schon einmal bei uns in der Praxis?",
        "Wissen Sie noch, bei welchem Behandler Sie zuletzt waren?",
        "Und der Nachname, bitte?",
        "Damit ich Sie in der Kartei finde: Wie ist Ihr Vor- und Nachname?",
        "Dann nehme ich Sie einmal auf: Wie ist Ihr Vor- und Nachname?",
        "Und der Vorname?",
        "Worum geht es denn — eine Kontrolle, Schmerzen, oder etwas anderes?",
        "Wann passt es Ihnen am besten — eher vormittags oder nachmittags? Und ab welchem Tag?",
        "Ich will nichts falsch schreiben: Buchstabieren Sie mir den Nachnamen bitte einmal kurz?",
        "Damit ich nichts falsch schreibe: Buchstabieren Sie den Nachnamen bitte einmal kurz?",
        "Da fehlt noch ein Stück von der Nummer — sagen Sie sie bitte einmal komplett, Ziffer für Ziffer.",
        "Und unter welcher Handynummer erreichen wir Sie?",
        "Und unter welcher Handynummer erreichen wir Sie? Die brauche ich für die Terminbestätigung.",
    ]
    out = list(erstformen)
    for varianten in FRAGE_VARIANTEN.values():
        for v in varianten:
            if v not in out:
                out.append(v)
    return out


def naechste_frage(sit: dict) -> tuple[str, str]:
    """Welches Pflichtfeld fehlt als nächstes — und wie fragt Bianca danach?"""
    s = sammler(sit)

    # Eine gehörte Nummer wird IMMER erst rückbestätigt (Chef: sicher aufnehmen).
    if s["telefonOffen"] and not s["telefonOk"]:
        return "telefon_check", f"Ich wiederhole die Nummer: {telefon.sprechbar(s['telefonOffen'])}. Stimmt das so?"

    if s["warSchonMal"] is None:
        return "schonmal", "Waren Sie denn schon einmal bei uns in der Praxis?"

    if s["warSchonMal"]:
        if not s["arzt"]:
            return "arzt", "Wissen Sie noch, bei welchem Behandler Sie zuletzt waren?"
        # Name früh: dann läuft die Kartei-Suche im Hintergrund, während wir
        # Grund und Wunschzeit klären — genau das macht das Tempo.
        if not s["nachname"]:
            if s["vorname"]:
                return "nachname", "Und der Nachname, bitte?"
            wen = f"Wie heißt {'Ihr' if s['fuerWen'] in {'sohn', 'mann', 'vater', 'opa'} else 'Ihre'} {s['fuerWen']}?" if s["fuerWen"] else "Damit ich Sie in der Kartei finde: Wie ist Ihr Vor- und Nachname?"
            return "name", wen
        if not s["vorname"]:
            return "vorname", "Und der Vorname?"
        if not s["grund"]:
            return "grund", "Worum geht es denn — eine Kontrolle, Schmerzen, oder etwas anderes?"
        if s["wunsch"] is None:
            return "wunsch", "Wann passt es Ihnen am besten — eher vormittags oder nachmittags? Und ab welchem Tag?"
        if not s["bekannt"] and not s["buchstabiert"]:
            return "buchstabieren", "Ich will nichts falsch schreiben: Buchstabieren Sie mir den Nachnamen bitte einmal kurz?"
        if not s["telefonOk"] and not s["telefonAkte"] and not (s["bekannt"] and s["aktePhone"]):
            if s["telefonTeil"]:
                return "telefon", "Da fehlt noch ein Stück von der Nummer — sagen Sie sie bitte einmal komplett, Ziffer für Ziffer."
            return "telefon", "Und unter welcher Handynummer erreichen wir Sie?"
        return "", ""

    # Neu bei uns: erst Anliegen und Zeit, dann sauber aufnehmen.
    if not s["grund"]:
        return "grund", "Worum geht es denn — eine Kontrolle, Schmerzen, oder etwas anderes?"
    if s["wunsch"] is None:
        return "wunsch", "Wann passt es Ihnen am besten — eher vormittags oder nachmittags? Und ab welchem Tag?"
    if not s["nachname"]:
        if s["vorname"]:
            return "nachname", "Und der Nachname, bitte?"
        wen = f"Wie heißt {'Ihr' if s['fuerWen'] in {'sohn', 'mann', 'vater', 'opa'} else 'Ihre'} {s['fuerWen']}?" if s["fuerWen"] else "Dann nehme ich Sie einmal auf: Wie ist Ihr Vor- und Nachname?"
        return "name", wen
    if not s["vorname"]:
        return "vorname", "Und der Vorname?"
    if not s["buchstabiert"] and not s["bekannt"]:
        return "buchstabieren", "Damit ich nichts falsch schreibe: Buchstabieren Sie den Nachnamen bitte einmal kurz?"
    if not s["telefonOk"] and not s["telefonAkte"]:
        if s["telefonTeil"]:
            return "telefon", "Da fehlt noch ein Stück von der Nummer — sagen Sie sie bitte einmal komplett, Ziffer für Ziffer."
        return "telefon", "Und unter welcher Handynummer erreichen wir Sie? Die brauche ich für die Terminbestätigung."
    return "", ""


def start_datum(s: dict) -> str:
    """Ab wann suchen? Wunschdatum > 'nächste Woche' > sofort."""
    w = s.get("wunsch") or {}
    if w.get("date"):
        return str(w["date"])
    tage = int(w.get("minDaysAhead") or 0)
    if tage:
        return (datetime.now(TZ).date() + timedelta(days=tage)).isoformat()
    return ""
