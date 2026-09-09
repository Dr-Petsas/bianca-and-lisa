"""Biancas Buchungsfluss — deterministisch, ohne LLM auf dem Pflichtpfad.

Jeder Zug: erst Slot-Wahl/Bestätigung prüfen, dann alle Deuter (gehirn),
dann Hintergrund anstoßen (Kartei + Slot-Vorrat), dann die nächste Frage
stellen ODER das Angebot machen. Liefert None, wenn der Satz nichts mit der
Buchung zu tun hat — dann übernimmt das LLM (mit status_zeile im Prompt).
"""

from __future__ import annotations

import re
from typing import Any, Callable

from bianca import besuchsgrund, gehirn, hintergrund, telefon, verwalten, weiterleiten
from kern import anliegen_art
from kern import dossier
from kern import gedaechtnis
from kern import motive
from kern import praxisregeln
from kern import spur
from kern import notes as kern_notes
from kern import calendar as kal
from kern import gespraech
from kern.patients import arzt_sprechname, telefon_aktualisieren, versicherung_aktualisieren
from kern.sitzung import merke_tool
from kern.slots import WEEKDAYS, _weekday_of, parse_slot_wish, pick_slots, spoken_offer, spoken_slot
from kern import pzr_kassen
from kern import tenants as kern_tenants
from kern.tenants import ist_akut_motiv, motiv_von

Melde = Callable[[str], None] | None

# "Welche Nummer? / Sagen Sie das nochmal": bei offener Akten-Nummer-Frage
# wird die Nummer deterministisch ERNEUT vorgelesen (Chef 29.08.2026: "die KI
# muss das mehrmals vorlesen können") — nie ans LLM, das kennt die Ziffern nicht.
_NOCHMAL_RE = re.compile(
    r"noch\s*ein?mal|nochmal|wiederhol|wie\s+bitte|welche\s+nummer|"
    r"nicht\s+verstanden|versteh|langsam(er)?\b|wie\s+war\s+die",
    re.I,
)
_TERMIN_WIEDERHOLEN_RE = re.compile(
    r"\bwiederhol\w*.{0,36}\b(?:termin|termindaten|datum|uhrzeit|zeit)\b|"
    r"\b(?:termin|termindaten|datum|uhrzeit)\b.{0,36}\bwiederhol\w*|"
    r"\bwie\s+war(?:en)?\s+(?:noch\s+einmal\s+)?(?:der\s+)?termin",
    re.I,
)
_TERMIN_ABGLEICH_RE = re.compile(
    r"\b(?:termin|termindaten|datum|uhrzeit|\d{1,2}(?:[:.]\d{1,2})?)\b"
    r".{0,64}\b(?:richtig|stimmt|korrekt)\b|"
    r"\b(?:richtig|stimmt|korrekt)\b.{0,36}\b(?:termin|termindaten|datum|uhrzeit)\b|"
    r"\btermin\b.{0,48}\b(?:noch\s+frei|noch\s+zu\s+haben|noch\s+verfügbar)\b|"
    r"\bdu\s+sagtest\b.{0,64}\btermin\b",
    re.I,
)

_H_WORT = {
    "ein": 1, "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
    "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11,
    "zwölf": 12, "zwoelf": 12, "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15,
    "fuenfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18, "neunzehn": 19,
    "zwanzig": 20,
}
_M_WORT = {
    "fünf": 5, "fuenf": 5, "zehn": 10, "fünfzehn": 15, "fuenfzehn": 15,
    "zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40,
    "fünfundvierzig": 45, "fuenfundvierzig": 45, "fünfzig": 50, "fuenfzig": 50,
}
_M_ZEHNER = {
    "zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40,
    "fünfzig": 50, "fuenfzig": 50,
}


def _minuten_von(wort: str) -> int | None:
    """Minutenwort 1-59 — auch zusammengesetzt ('vierundvierzig').

    Live 27.08.2026: 'neun Uhr vierundvierzig' fiel durch, weil _M_WORT nur
    runde Werte kennt — die Slot-Wahl scheiterte und das Angebot kam wortgleich
    ein zweites Mal.
    """
    w = _s(wort).lower()
    if not w:
        return None
    if w in _M_WORT:
        return _M_WORT[w]
    if w in _H_WORT and _H_WORT[w] <= 20:
        return _H_WORT[w]
    m = re.match(r"^([a-zäöüß]+)und([a-zäöüß]+)$", w)
    if m and m.group(1) in _H_WORT and _H_WORT[m.group(1)] <= 9 and m.group(2) in _M_ZEHNER:
        return _M_ZEHNER[m.group(2)] + _H_WORT[m.group(1)]
    return None
_ABLEHNUNG_RE = re.compile(r"passt nicht|passt mir nicht|keiner davon|nichts davon|geht nicht|geht bei mir nicht|anderer termin|was anderes", re.I)
# W-SCHLEIFE (04.09.2026): nach Nein auf die Readback-Frage sagt der
# Anrufer, WAS falsch ist — nicht nochmal "Soll ich eintragen?".
_AENDERUNG_NAME_RE = re.compile(
    r"\b(?:vor-?\s*und\s*nach)?namen?\b|nachname|vorname|heißt|heisst", re.I)
_AENDERUNG_NUMMER_RE = re.compile(r"nummer|handy|telefon", re.I)
_AENDERUNG_ZEIT_RE = re.compile(
    r"zeitpunkt|uhrzeit|\bzeit\b|datum|\btag\b|vormittag|nachmittag|"
    r"\bslot\b|\buhr\b|montag|dienstag|mittwoch|donnerstag|freitag|"
    r"samstag|sonntag|woche|früher|spaeter|später|anderswann",
    re.I,
)
# Thaler 08.09.2026 Leonid: nach der Buchung „Nachname ändern“ — nicht
# wieder Slots anbieten, sondern den Namen korrigieren und als Notiz schreiben.
_NACHNAME_KORR_RE = re.compile(
    r"(nachname|name).{0,32}(änder|aender|korrig|falsch|umänder|geändert|geaendert)|"
    r"(änder|aender|korrig|umänder|richtigstell).{0,28}(nachname|name)|"
    r"hei(ss|ß)e? jetzt",
    re.I,
)
# Thaler 08.09. Rebrovic: nach Buchung/Notiz „perfekt danke“ / Abschied
# darf keine neue Slot-Liste aufmachen. Nur ein ausdrücklicher
# Zweit-Termin bricht den Riegel.
_ABSCHIED_RE = re.compile(
    r"(?:auf\s+)?wiederh[oö]ren|\btsch[uü]s{0,2}\b|\bciao\b|"
    r"das\s+(?:war'?s|wars)|nichts\s+weiter|"
    r"nein\s*,?\s*danke|"
    r"danke\s*,?\s*(?:ciao|tsch[uü]s{0,2}|ihnen)|"
    r"^\s*(?:(?:okay|ok|alles\s+klar)\s*,?\s*)?"
    r"(?:perfekt|super|prima|danke|vielen\s+dank|vielen\s+lieben\s+dank)"
    r"(?:\s|,|!|\.|$)",
    re.I,
)
# Telefon-STT verhörte „Vielen Dank“ live als „Seid Danke“ und „Dein
# Danke“. Nach einem bereits abgeschlossenen Vorgang ist ein kurzer Satz,
# der auf Danke/Dank endet, eindeutig Höflichkeit — nie ein neues Thema.
_VERHOERTES_DANKE_RE = re.compile(
    r"^\s*(?:[\wäöüß'-]+\s+){0,2}(?:danke|dank)\s*[.!?…]*\s*$",
    re.I,
)
_SCHON_TERMIN_RE = re.compile(
    r"(schon|bereits).{0,24}termin|"
    r"termin.{0,20}(schon|gemacht|gebucht|vereinbart)",
    re.I,
)
_NOCH_EIN_TERMIN_RE = re.compile(
    r"noch\s+ein(?:en)?\s+termin|zweiten\s+termin|weiteren\s+termin|"
    r"neuen\s+termin",
    re.I,
)
# Live Thaler/New York 08.09.2026: Meta-Fragen zur sicheren Namensaufnahme
# gehören in den Formularfluss. Das freie Modell antwortete auf „Soll ich
# meinen Namen buchstabieren?“ ausgerechnet mit „Nein“.
_BUCHSTABIER_META_RE = re.compile(
    r"\b(?:soll|kann|darf)\s+ich\b[^?.!]{0,36}\b(?:namen?|nachnamen?)\b"
    r"[^?.!]{0,24}\bbuchstabier\w*|"
    r"\b(?:soll|kann|darf)\s+ich\b[^?.!]{0,36}\bbuchstabier\w*",
    re.I,
)
# Reiseort auf der offenen Zeitfrage: kurz zur Kenntnis nehmen und nach der
# tatsächlichen Verfügbarkeit fragen. Kein freier Reise-Smalltalk („New York
# ist eine weite Reise …“) mitten in der Buchung.
_REISEORT_RE = re.compile(
    r"\b(?:komme|reise|fliege|fahre)\s+(?:gerade\s+)?(?:aus|von)\s+"
    r"[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'-]+|"
    r"\b(?:aus|von)\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'-]+"
    r"(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'-]+){0,2}",
)

# Thaler 08.09.2026: "Nein, den Besuchsgrund. Zahnersatzbesprechen" — der
# Änderungszweig kannte nur Zeitpunkt/Name/Nummer und blieb in Presence hängen.
_AENDERUNG_GRUND_RE = re.compile(
    r"besuchsgrund|anliegen|\bgrund\b|"
    r"zahnersatz|zahnarztbesprech|besprechung|beratung|"
    r"kontroll|zahnreinigung|prophylaxe|"
    r"keine?\s+akut|nicht\s+akut|kein\s+notfall|keine?\s+notfall",
    re.I,
)
# Dringlichkeit (kanonischer Grund aus gehirn._GRUND_MAP): Notfaelle bekommen
# die naechstmoeglichen Plaetze DICHT angeboten — Streuung gilt dort nicht.
_DRINGEND_RE = re.compile(r"akut|notfall|schmerz", re.I)
# Chef 03.09.2026: mit der Bestaetigungs-SMS geht ein Link raus, ueber den
# der Anrufer die Unterlagen fuer den Termin ausfuellt (Anamnese,
# Datenschutz, Aufklaerung) — Bianca sagt das bei der Buchung dazu.
_SMS_LINK_SATZ = (
    " In der SMS ist auch ein Link — darüber füllen Sie bitte vorab kurz die"
    " Unterlagen für Ihren Termin aus, zum Beispiel Anamnese und Datenschutz."
)
_KUERZEL_RE = re.compile(r"^[A-ZÄÖÜ]{2,4}\s+")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _zeit_von(t: str) -> tuple[int | None, int | None]:
    """Gehörte Uhrzeit: '9 uhr 15', 'um 14:30', 'neun uhr fünfzehn', 'halb zehn'."""
    m = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*uhr\b(?:\s+(\d{1,2})\b)?", t)
    if not m:
        m = re.search(r"\bum\s+(\d{1,2})(?:[:.](\d{2}))?\b", t)
    if m:
        minute = m.group(2) or (m.group(3) if m.lastindex and m.lastindex >= 3 else None)
        return int(m.group(1)), (int(minute) if minute else None)
    m = re.search(r"\bhalb\s+([a-zäöü]+|\d{1,2})\b", t)
    if m:
        w = m.group(1)
        h = int(w) if w.isdigit() else _H_WORT.get(w)
        if h:
            return h - 1, 30
    m = re.search(r"\b([a-zäöü]+)\s+uhr(?:\s+([a-zäöüß]+))?\b", t)
    if m and m.group(1) in _H_WORT:
        return _H_WORT[m.group(1)], _minuten_von(m.group(2) or "")
    m = re.search(r"\bum\s+([a-zäöüß]+)\b", t)
    if m and m.group(1) in _H_WORT:
        # 'Montag um zehn' OHNE das Wort 'Uhr' (live 28.08.2026): die Wahl
        # fiel durch, der Satz wurde als NEUER Wunsch geerntet und das
        # Angebot lief wortgleich in den Wiederholungs-Waechter ('Gut.').
        return _H_WORT[m.group(1)], None
    return None, None


def _slot_wahl(text: str, offered: list[dict]) -> str:
    """Welchen der angebotenen Termine meint der Anrufer? '' wenn unklar."""
    if not offered:
        return ""
    t = f" {_s(text).lower()} "

    wd = next((idx for idx, cre in WEEKDAYS if cre.search(t)), None)
    hour, minute = _zeit_von(t)
    if hour is not None:
        c = [o for o in offered
             if int(o["iso"][11:13]) == hour and (minute is None or int(o["iso"][14:16]) == minute)]
        if not c:
            c = [o for o in offered
                 if int(o["iso"][11:13]) % 12 == hour % 12 and (minute is None or int(o["iso"][14:16]) == minute)]
        if len(c) > 1 and wd is not None:
            # 'Montag um zehn' bei zwei Zehn-Uhr-Slots: Wochentag grenzt ein.
            cw = [o for o in c if _weekday_of(o["iso"][:10]) == wd]
            if cw:
                c = cw
        if len(c) == 1:
            return c[0]["iso"]
        if minute is not None and not c:
            # Konkrete Zielzeit ohne exakten Treffer: auf den NÄCHSTLIEGENDEN
            # angebotenen Slot runden ('neun Uhr vierundvierzig' -> 09:45).
            # Live 27.08.2026 wiederholte Bianca sonst wortgleich das Angebot.
            ziel = hour * 60 + minute

            def _abstand(o: dict) -> int:
                slot = int(o["iso"][11:13]) * 60 + int(o["iso"][14:16])
                slot12 = (int(o["iso"][11:13]) % 12) * 60 + int(o["iso"][14:16])
                return min(abs(slot - ziel), abs(slot12 - (hour % 12) * 60 - minute))

            nah = sorted(offered, key=_abstand)
            if _abstand(nah[0]) <= 20 and (len(nah) == 1 or _abstand(nah[1]) > _abstand(nah[0])):
                return nah[0]["iso"]

    if wd is not None:
        c = [o for o in offered if _weekday_of(o["iso"][:10]) == wd]
        if len(c) > 1 and hour is not None:
            # Zwei Slots am selben Tag: die gehoerte Stunde entscheidet.
            ch = [o for o in c
                  if int(o["iso"][11:13]) % 12 == hour % 12
                  and (minute is None or int(o["iso"][14:16]) == minute)]
            if ch:
                c = ch
        if len(c) == 1:
            return c[0]["iso"]

    dm = re.search(r"\b(\d{1,2})\.\s?(\d{1,2})\.", t)
    if dm:
        jahr = offered[0]["iso"][:4]
        datum = f"{jahr}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}"
        c = [o for o in offered if o["iso"].startswith(datum)]
        if len(c) == 1:
            return c[0]["iso"]

    # Ein Tag allein bezieht sich in einer angebotenen Liste auf deren
    # Monat: „Entschuldigung, den 26.“ darf bei Oktober-Angeboten nicht als
    # neuer Wunsch für den 26. September geparst werden.
    tag = re.search(r"\b(?:am|dem|den|der)?\s*(\d{1,2})\.(?!\s*\d)", t)
    if tag:
        c = [o for o in offered if int(o["iso"][8:10]) == int(tag.group(1))]
        if len(c) == 1:
            return c[0]["iso"]

    rel = gehirn._relatives_datum(t)
    if rel:
        c = [o for o in offered if o["iso"].startswith(rel)]
        if len(c) == 1:
            return c[0]["iso"]

    if "vormittag" in t or "nachmittag" in t:
        früh = "vormittag" in t
        c = [o for o in offered
             if (int(o["iso"][11:13]) < 12) == früh]
        if len(c) == 1:
            return c[0]["iso"]

    if re.search(r"\b(erste[rns]?|ersteren)\b", t):
        return offered[0]["iso"]
    if re.search(r"\b(zweite[rns]?)\b", t) and len(offered) > 1:
        return offered[1]["iso"]
    if re.search(r"\b(dritte[rns]?)\b", t) and len(offered) > 2:
        return offered[2]["iso"]
    if re.search(r"\b(letzte[rns]?)\b", t):
        return offered[-1]["iso"]

    if len(offered) == 1 and (gehirn.ist_ja(t) or re.search(r"nehm|passt|gerne|gut\b", t)):
        return offered[0]["iso"]
    return ""


def _kalender_strikt(tenant: dict, name: str) -> dict | None:
    """Kalender NUR über den Namen finden — ohne Default-Rückfall.

    kern.tenants.kalender_von fällt auf den Standard-Kalender zurück, wenn
    nichts passt. Beim Binden eines Angebots wäre genau das der Fehler vom
    27.08.2026 (fremder Slot im falschen Kalender) — lieber ehrlich None.
    """
    q = _s(name).lower()
    if not q:
        return None
    cals = tenant.get("calendars") if isinstance(tenant.get("calendars"), list) else []
    for c in cals:
        if _s(c.get("name")).lower() == q:
            return c
    tokens = [t for t in q.replace(".", " ").replace(",", " ").split()
              if t not in {"dr", "doktor", "med", "msc", "m.sc"}]
    best, score = None, 0
    for c in cals:
        n = _s(c.get("name")).lower()
        s = sum(1 for t in tokens if t and t in n)
        if s > score:
            best, score = c, s
    return best


def _ctx_bauen(sit: dict) -> dict:
    """Sammler-Stand in den Buchungskontext spiegeln (den kern.calendar kennt)."""
    s = gehirn.sammler(sit)
    ctx = sit.setdefault("booking", {})
    a = s["arzt"] or {}
    bind = sit.get("angebotKalender") or {}
    if _s(bind.get("calendarId")) or _s(bind.get("calendarName")):
        # Es liegt ein Angebot auf dem Tisch: gebucht wird IMMER in dem
        # Kalender, aus dem die angebotenen Zeiten kamen — auch wenn die
        # Kartei-Recherche den Sammler inzwischen umgestellt hat.
        if _s(bind.get("calendarId")):
            ctx["calendarId"] = bind["calendarId"]
        else:
            ctx.pop("calendarId", None)
        ctx["calendarName"] = _s(bind.get("calendarName"))
    elif a.get("calendarId"):
        ctx["calendarId"] = a["calendarId"]
        ctx["calendarName"] = a.get("calendarName") or ""
    elif _s(sit.get("angebotArzt")):
        # "Egal"-Fall: die Cloud Function hat den schnellsten Arzt gewählt —
        # zum Buchen lösen wir dessen Kalender über den Namen auf.
        ctx.pop("calendarId", None)
        ctx["calendarName"] = sit["angebotArzt"]
    # Besuchsgrund BEHANDLERSPEZIFISCH aufloesen — bei JEDEM Kontext-Bau neu
    # (Chef 30.08.2026): Motive sind kalendergebunden (calendarIds); wechselt
    # der Behandler im Gespraech, muss das Motiv gegen DESSEN Katalog neu
    # gesucht werden. Ohne frischen Katalog bleibt der bisherige Stand.
    if s["motivId"] or s["grund"]:
        ziel_id = _s(ctx.get("calendarId"))
        if not ziel_id and _s(ctx.get("calendarName")):
            ziel_id = _s((_kalender_strikt(sit.get("tenant") or {}, ctx["calendarName"]) or {}).get("id"))
        vm = gehirn.motiv_fuer_kalender(sit, ziel_id)
        if vm and _s(vm.get("id")) != s["motivId"]:
            print(f"bianca-motiv: {s['motivName'] or s['motivId'] or '?'} -> "
                  f"{vm.get('name')} (Kalender {ziel_id or 'alle'})", flush=True)
        if vm:
            s["motivId"] = _s(vm.get("id"))
            s["motivName"] = _s(vm.get("name"))
    if s["motivId"]:
        ctx["visitMotiveId"] = s["motivId"]
        ctx["visitMotiveName"] = s["motivName"]
    elif s["grund"] and not _s(ctx.get("visitMotiveName")):
        ctx["visitMotiveName"] = "Kontrolluntersuchung"
    if s["patientId"]:
        ctx["patientId"] = s["patientId"]
    if s["vorname"]:
        ctx["firstName"] = s["vorname"]
    if s["nachname"]:
        ctx["lastName"] = s["nachname"]
    name = f"{s['vorname']} {s['nachname']}".strip()
    if name:
        ctx["patientName"] = name
    tel = s["telefon"] or s["aktePhone"]
    if tel:
        ctx["phone"] = tel
    # Fuer eine NEUE Akte (book_slot -> akte_anlegen): Geschlecht aus dem
    # Vornamen-Waechter und der erfragte Versichertenstatus (29.08.2026).
    if s["geschlecht"]:
        ctx["gender"] = s["geschlecht"]
    if s["versicherung"]:
        ctx["privateInsurance"] = s["versicherung"] == "privat"
    if sit.get("slotVorrat"):
        ctx["slotVorrat"] = list(sit["slotVorrat"])
    if sit.get("slotGesperrt"):
        ctx["slotGesperrt"] = list(sit["slotGesperrt"])
    return ctx


def _grund_sprechbar(s: dict) -> str:
    roh = s["motivName"] or s["grund"] or "Ihr Termin"
    return _KUERZEL_RE.sub("", roh)


def _quittung(s: dict, neu: set[str]) -> str:
    if "fuerWen" in neu and s.get("fuerWen"):
        # W-FUER-WEN (Chef 03.09.2026): der Termin ist fuer jemand anderen —
        # das SOFORT quittieren, bevor irgendein "Danke, <Anrufername>"
        # den Eindruck erweckt, es gehe weiter um den Anrufer.
        wer = gehirn.fuer_wen_phrase(s, fall="wen")
        if wer:
            return f"Alles klar — der Termin ist für {wer}. "
        return "Alles klar — der Termin ist für jemand anderen. "
    if "nachname" in neu and s["buchstabiert"]:
        return f"Danke — {s['nachname']}, notiert. "
    if "name" in neu:
        # Mit dem VOLLEN Namen quittieren — nie mit einem halben ("Danke,
        # Paul" klingt nach Anrede und war live 27.08.2026 auch noch falsch
        # zugeordnet). Fehlt ein Teil, fragt die nächste Frage ihn nach.
        if s["vorname"] and s["nachname"]:
            return f"Danke, {s['vorname']} {s['nachname']}. "
        return "Danke. "
    if "anruferCheck" in neu and s.get("anruferCheck") == "nein":
        # DB-Treffer verworfen (W-ANRUFER-CHECK): kurz entschuldigen, dann
        # kommt direkt die klassische Frage (schonmal/Name) hinterher.
        return "Entschuldigen Sie bitte — dann nehme ich Ihre Daten frisch auf. "
    if "telefon" in neu:
        return "Prima, die Nummer habe ich. "
    if "telefonAkte" in neu:
        return "Alles klar — dann nehmen wir die Nummer aus Ihrer Akte. "
    if "versicherung" in neu:
        art = "privat" if s.get("versicherung") == "privat" else "gesetzlich"
        return f"Alles klar — {art} versichert, notiert. "
    if "versicherungCheck" in neu:
        return "Prima, dann bleibt alles wie gehabt. "
    if "pzr" in neu:
        if s.get("pzr") == "ja":
            return "Sehr gerne — die Zahnreinigung nehme ich mit auf. "
        return "Alles klar, dann ohne Zahnreinigung. "
    if "bleachingCheck" in neu:
        # Ja zur Aufhellung — naechste_frage stellt jetzt den Zahnersatz-Check.
        return "Sehr gerne. "
    if "bleaching" in neu:
        if s.get("bleaching") == "ja":
            return ("Wunderbar — dann plane ich die Aufhellung mit ein, "
                    "der Termin dauert dann etwa eine Stunde länger. ")
        if s.get("bleaching") == "beratung":
            if s.get("bleachingInfo") == "unverbindlich":
                return (
                    "Okay! Der Doktor entscheidet, ob die Aufhellung bei Ihnen "
                    "möglich ist, besonders wenn Sie im Frontbereich Zahnersatz "
                    "tragen. Ich buche das unverbindlich als Besprechung mit ein. "
                )
            if s.get("bleachingInfo") == "zahnersatz":
                # Chef 03.09.2026: bei Kronen/Bruecken/Veneers/Implantaten in
                # der Front ist die Aufhellung unter Umstaenden nicht moeglich
                # — ausser die eigenen Zaehne sollen an zu helle Kronen
                # angepasst werden. Bianca beraet NICHT selbst.
                return ("Bei Zahnersatz im Frontbereich ist eine Aufhellung "
                        "unter Umständen nicht möglich — es sei denn, die "
                        "eigenen Zähne sollen an hellere Kronen angepasst "
                        "werden. Ich habe mir eine Notiz gemacht: Der Doktor "
                        "schaut sich das beim Termin in Ruhe an und berät Sie. ")
            return ("Kein Problem — ich habe mir eine Notiz gemacht. Der "
                    "Doktor schaut sich das beim Termin in Ruhe an und "
                    "berät Sie. ")
        return "Alles klar — dann nur die Zahnreinigung. "
    if "arzt" in neu and (s.get("arzt") or {}).get("typ") == "unbekannt":
        # W-SCHLEIFE: "Keine Ahnung, wie der Zahnarzt heisst" darf nicht
        # nur eine Plauder-Quittung sein — die nächste Pflichtfrage
        # (Name) kommt im selben Zug hinterher.
        return "Kein Problem, das finden wir schon. "
    if "grund" in neu:
        # Nicht zwischen Hallo und Selbst-Frage schieben (Thaler 08.09.:
        # „Ich bin die Neue! Alles klar. Der Termin ist…“).
        if s.get("frage") == "anrufer_check":
            return ""
        return "Alles klar. "
    if "wunsch" in neu:
        return "Gut. "
    return ""


def _readback(sit: dict) -> dict:
    s = gehirn.sammler(sit)
    a = s["arzt"] or {}
    bind = sit.get("angebotKalender") or {}
    # Gesprochen wird NUR Titel + Nachname ("Doktor Petsas") — englische
    # Vornamen (Michael) liest die Sprachausgabe sonst englisch vor.
    kal_name = bind.get("calendarName") or a.get("calendarName") or sit.get("angebotArzt") or ""
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else None
    funk_bei = kern_tenants.kalender_beim(kal_name) if kal_name else ""
    if funk_bei:
        beim = funk_bei
    else:
        beim = arzt_sprechname(kal_name, tenant)
    # Geschlechts-Anrede (Chef 29.08.2026): "für Frau Müller" / "für Herrn
    # Müller" — ohne Geschlecht bleibt der volle Name.
    wer = gehirn.anrede(s, sit.get("patient"), beugen=True)
    s["phase"] = "bestaetigen"
    s["frage"] = "bestaetigung"
    teile = [_grund_sprechbar(s), spoken_slot(s["slotIso"])]
    if beim:
        teile.append(f"bei {beim}")
    if wer:
        teile.append(f"für {wer}")
    return {"text": f"Dann halte ich fest: {', '.join(teile)}. Soll ich das so eintragen?"}


def _termin_nochmal(sit: dict, gesagt: str = "") -> dict:
    """Ausgewaehlte Termindaten wiederholen, ohne dadurch zu buchen.

    Eine Frage wie „Der Termin ist um 14 Uhr, richtig?“ gleicht nur die
    Daten ab. Auch wiederholte Bitten gelten niemals als Buchungs-Ja.
    """
    s = gehirn.sammler(sit)
    abgleich = bool(_TERMIN_ABGLEICH_RE.search(gesagt))
    abweichend = False
    if abgleich and _s(s.get("slotIso")):
        w = parse_slot_wish(gesagt) or {}
        iso = _s(s["slotIso"])
        if w.get("date") and w["date"] != iso[:10]:
            abweichend = True
        if w.get("hour") is not None and int(w["hour"]) != int(iso[11:13]):
            abweichend = True
    rb = _readback(sit)
    if abgleich and abweichend:
        anfang = "Nein — ausgewählt ist:"
    elif abgleich and re.search(r"noch\s+(?:frei|zu\s+haben|verfügbar)", gesagt, re.I):
        anfang = "Dieser Termin wurde gerade als frei angeboten. Ausgewählt ist:"
    elif abgleich:
        anfang = "Ja — ausgewählt ist:"
    else:
        anfang = "Gerne, ich wiederhole:"
    rb["text"] = rb["text"].replace("Dann halte ich fest:", anfang, 1)
    rb["text"] = rb["text"].replace(
        "Soll ich das so eintragen?", "Soll ich genau diesen Termin eintragen?", 1
    )
    # Der Nutzer hat die Wiederholung ausdrücklich verlangt. Der allgemeine
    # Wiederholungs-Wächter darf die Termindaten daher nicht wieder streichen.
    rb["_wiederholungErlaubt"] = True
    return rb


def _schon_gebucht(sit: dict) -> bool:
    """Echter book_slot in DIESEM Anruf — nicht ein nur gefundener Bestand."""
    if sit.get("nochEinTermin"):
        return False
    b = sit.get("lastBook") or {}
    return bool(b.get("booked") or b.get("dryRun"))


def _abschied_nach_buchung(sit: dict) -> dict:
    sit["flussFrage"] = ""
    sit["offered"] = []
    s = gehirn.sammler(sit)
    s["frage"] = ""
    an = gehirn.anrede(s)
    return {"text": f"Gern geschehen{', ' + an if an else ''}. Auf Wiederhören."}


def _erinner_termin(sit: dict) -> dict:
    sit["flussFrage"] = ""
    sit["offered"] = []
    spoken = _s((sit.get("lastBook") or {}).get("spoken")) or "Der Termin ist für Sie gebucht."
    return {"text": f"Ja, genau — {spoken} Kann ich sonst noch etwas für Sie tun?"}


def _angebot(sit: dict, melde: Melde = None) -> dict:
    s = gehirn.sammler(sit)
    # Thaler 08.09. Rebrovic: nach gebuchtem Termin + Notiz rutschte
    # phase auf fertig/angebot und bot erneut Slots an.
    if _schon_gebucht(sit) and s.get("phase") in {"gebucht", "fertig"}:
        return {"text": "Kann ich sonst noch etwas für Sie tun?"}

    # "Weiß nicht, bei wem ich war": erst die Behandler-Recherche abwarten
    # (Füller überbrückt), NICHT sofort global suchen — Chef-Vorgabe.
    a = s["arzt"] or {}
    if a.get("typ") == "unbekannt" and not a.get("calendarId") and hintergrund.kartei_laeuft(sit):
        if melde:
            melde("offer_slots")
        hintergrund.kartei_abwarten(sit, max_s=3.0)
        a = s["arzt"] or {}

    # Chef 03.09.2026: "wenn jemand nicht weiss zu welchem arzt er soll dann
    # immer bei dr. Petsas buchen" — steht bis hier KEIN Kalender fest (egal,
    # Kartei-Recherche erfolglos, Neupatient ohne Wahl), sucht das Angebot im
    # Standard-Behandler-Kalender statt global beim schnellsten Arzt.
    # Praxis mit Funktionskalender: PZR liegt dort, alles andere beim Arzt.
    gehirn.kalender_zu_grund(sit)
    a = s["arzt"] or {}
    if not a.get("calendarId"):
        d = gehirn.arzt_default(sit.get("tenant") or {})
        if d:
            s["arzt"] = d
            a = d

    sit.pop("angebotKalender", None)  # neues Angebot => neue Bindung
    ctx = _ctx_bauen(sit)
    vorrat = list(sit.get("slotVorrat") or [])
    # Gescheiterte Buchungs-ISOs nie wieder anbieten (W-BOOK-RETRY 01.09.2026).
    gesperrt = sit.get("slotGesperrt") or []
    if gesperrt:
        keys = {str(g)[:16] for g in gesperrt}
        vorrat = [v for v in vorrat if str(v)[:16] not in keys]
    wish = s["wunsch"]
    egal = not a.get("calendarId")

    def _laden() -> dict:
        if melde:
            melde("offer_slots")
        from kern import zimmer_map
        raeume = zimmer_map.raeume_am(sit)
        if raeume:
            found = kal.find_slots_raeume(
                sit["tenant"], ctx, raeume,
                start_date=gehirn.start_datum(s),
                source="pickadoc-bianca",
            )
            win = found.get("calendar") if isinstance(found.get("calendar"), dict) else None
            if win and _s(win.get("id")):
                sit["slotKalender"] = win
                a["calendarId"] = win["id"]
                ctx["calendarId"] = win["id"]
                ctx["calendarName"] = _s(a.get("calendarName")) or _s(win.get("name"))
        elif a.get("calendarId"):
            found = kal.find_slots_behandler(
                sit["tenant"], ctx,
                start_date=gehirn.start_datum(s),
                source="pickadoc-bianca",
            )
        else:
            found = kal.find_slots(
                sit["tenant"], ctx,
                start_date=gehirn.start_datum(s),
                egal=egal,
                source="pickadoc-bianca",
            )
        if found.get("ok"):
            frisch = kal._iso_liste(found.get("slots") or [])
            if gesperrt:
                keys = {str(g)[:16] for g in gesperrt}
                frisch = [v for v in frisch if str(v)[:16] not in keys]
            if frisch:
                sit["slotVorrat"] = frisch
                ctx["slotVorrat"] = list(frisch)
                sit["vorratFuer"] = hintergrund.vorrat_schluessel(sit)
                sit["vorratDispatch"] = (
                    found.get("dispatch")
                    if isinstance(found.get("dispatch"), dict) else None
                )
            if egal and _s(found.get("doctorName")):
                sit["angebotArzt"] = _s(found.get("doctorName")).split(",")[0].strip()
        merke_tool(sit, "getFreeTimeSlots", found)
        sit["vorratGemerkt"] = True
        return found

    # W-MOTIV-FENSTER (Chef 03.09.2026): ein vorgeladener Vorrat zaehlt NUR,
    # wenn er fuer GENAU diesen Rahmen (Kalender + Besuchsgrund + Startdatum)
    # geladen wurde — sonst kaemen Zeiten aus fremden Spezialsprechzeiten-
    # Fenstern (z. B. Kontroll-Slots fuer eine Zahnreinigung). Bei Abweichung
    # oder unklarem Rahmen laedt der Zug synchron mit dem richtigen Motiv.
    schluessel = hintergrund.vorrat_schluessel(sit)
    nachladen = (not vorrat or not schluessel
                 or sit.get("vorratFuer") != schluessel)
    if wish and wish.get("date") and vorrat and not any(str(v).startswith(str(wish["date"])) for v in vorrat):
        nachladen = True
    if nachladen:
        found = _laden()
        vorrat = list(sit.get("slotVorrat") or [])
        if gesperrt:
            keys = {str(g)[:16] for g in gesperrt}
            vorrat = [v for v in vorrat if str(v)[:16] not in keys]
        if not found.get("ok") and not vorrat:
            s["phase"] = ""
            return {"text": (
                "Der Terminkalender antwortet gerade nicht. "
                "Die Praxis ruft Sie kurzfristig zurück — Ihre Nummer habe ich ja."
            )}
    elif vorrat and not sit.get("vorratGemerkt"):
        # Hintergrund-Vorrat verbraucht: CF lief schon (bianca-vorrat), die
        # Tool-Karte fehlt sonst am Angebots-Zug (live 02.09. Tzannis).
        disp = sit.get("vorratDispatch") if isinstance(sit.get("vorratDispatch"), dict) else None
        merke_tool(sit, "getFreeTimeSlots", {
            "ok": True,
            "slots": list(vorrat),
            "dispatch": disp,
        })
        sit["vorratGemerkt"] = True

    dringend = bool(_DRINGEND_RE.search(f"{s['grund']} {s['motivName']}"))
    picked = pick_slots(vorrat, wish=wish, dringend=dringend, exclude_isos=gesperrt)
    if wish and not picked["wishMatched"] and not nachladen:
        # Der Vorrat passt nicht zum Wunsch (z. B. "nächste Woche"): einmal
        # gezielt ab Wunschdatum nachladen, bevor wir Ausweichzeiten anbieten.
        _laden()
        vorrat = list(sit.get("slotVorrat") or [])
        if gesperrt:
            keys = {str(g)[:16] for g in gesperrt}
            vorrat = [v for v in vorrat if str(v)[:16] not in keys]
        picked = pick_slots(vorrat, wish=wish, dringend=dringend, exclude_isos=gesperrt)

    # Merken, aus WELCHEM Kalender dieses Angebot kommt: die Buchung bindet
    # sich daran, nicht an spätere Sammler-Umbauten (Vorfall 27.08.2026:
    # Patrikis-Slot wurde in Petsas' Kalender gebucht -> "Termin gerade weg").
    win = sit.pop("slotKalender", None) if isinstance(sit.get("slotKalender"), dict) else None
    if egal:
        name = _s(sit.get("angebotArzt"))
        cal = _kalender_strikt(sit["tenant"], name)
        sit["angebotKalender"] = {
            "calendarId": _s((cal or {}).get("id")),
            "calendarName": name or _s((cal or {}).get("name")),
        }
    elif win and _s(win.get("id")):
        sit["angebotKalender"] = {
            "calendarId": _s(win.get("id")),
            "calendarName": _s(a.get("calendarName")) or _s(win.get("name")),
        }
    else:
        sit["angebotKalender"] = {
            "calendarId": _s(a.get("calendarId")),
            "calendarName": _s(a.get("calendarName")),
        }
    offered = [{"iso": x["iso"], "spoken": spoken_slot(x["iso"])} for x in picked["slots"]]
    zuletzt = sit.pop("angebotZuletzt", None)
    sit["offered"] = offered
    if not offered:
        # KEIN Slot im Angebot: nie in die Slotwahl zwingen — dort haengt
        # sonst jede Folgeaeusserung ohne waehlbare Termine (Batch s09
        # 29.08.2026, LLM erfand "Welcher der genannten Termine?"). Das
        # Versprechen "die Praxis meldet sich" bekommt eine ECHTE Notiz.
        s["phase"] = "fertig"
        s["frage"] = ""
        sit["keinSlotFertig"] = True
        verwalten.rueckruf_notiz(sit)
        return {"text": spoken_offer([], wish_matched=True)
                + " Kann ich sonst noch etwas für Sie tun?"}
    s["phase"] = "angebot"
    s["frage"] = "slotwahl"
    vor = ""
    hinweis = _s(sit.get("arztHinweis"))
    if hinweis and not sit.get("arztHinweisGesagt"):
        sit["arztHinweisGesagt"] = True
        vor = hinweis + " "
    elif egal and _s(sit.get("angebotArzt")) and not sit.get("angebotArztGesagt"):
        sit["angebotArztGesagt"] = True
        vor = (f"Am schnellsten geht es bei "
               f"{arzt_sprechname(sit['angebotArzt'], sit.get('tenant') if isinstance(sit.get('tenant'), dict) else None)}. ")
    if offered and zuletzt == [o["iso"] for o in offered]:
        # Wiederhol-Wache: derselbe Wunsch fuehrt zum SELBEN Ergebnis — das
        # ehrlich sagen statt das Angebot wortgleich herunterzubeten
        # (live 27.08.2026: identische Slot-Liste zweimal hintereinander).
        # Formulierung ROTIERT (live 28.08.2026): eine wortgleiche zweite
        # Ansage strich der Wiederholungs-Waechter komplett — der Anrufer
        # hoerte nur noch 'Gut.' und die Buchung hing in der Luft.
        liste = "; oder ".join(o["spoken"] for o in offered)
        z = int(sit.get("angebotFestgefahren") or 0)
        sit["angebotFestgefahren"] = z + 1
        txt = [
            f"Näher an Ihrem Wunsch habe ich leider nichts — es bleibt bei {liste}. Passt davon einer?",
            f"Ich habe wirklich nur diese Termine: {liste}. Sagen Sie gern einfach 'der erste' oder 'der zweite'.",
            f"Mehr ist dazu gerade nicht frei — noch einmal: {liste}. Welcher soll es sein?",
        ][z % 3]
        return {"text": vor + txt}
    sit.pop("angebotFestgefahren", None)
    return {"text": vor + spoken_offer(picked["slots"], wish_matched=picked["wishMatched"])}


def _telefon_alt_ausfuehren(sit: dict, melde: Melde = None) -> str:
    """Die Entscheidung zur Akten-Nummer umsetzen (Chef 29.08.2026).

    "neu"  => masUpdatePatientPhone schreibt die bestaetigte Nummer in die
              Akte (die Bestaetigungs-SMS der Plattform geht IMMER an die
              Akten-Nummer — erst nach dem Update kommt sie richtig an).
    "akte" => nichts schreiben, SMS geht an die Alt-Nummer.
    Erledigt-Ansage NUR nach echtem Erfolg; scheitert das Update, faellt die
    Entscheidung auf "notiz" zurueck und _buchen haengt die Praxis-Notiz an."""
    s = gehirn.sammler(sit)
    if s["telefonAlt"] == "akte":
        return "Alles klar — die Nummer bleibt in der Akte, und die Bestätigungs-SMS geht an diese Nummer. "
    if s["telefonAlt"] != "neu" or not (s["patientId"] and s["telefon"] and s["telefonOk"]):
        return ""  # in die Akte kommt NUR eine rueckbestaetigte Nummer
    if s["aktePhone"] and telefon.normaliert(s["aktePhone"]) == telefon.normaliert(s["telefon"]):
        return ""  # schon umgetragen (z. B. Sicherheitsnetz lief bereits)
    if melde:
        melde("update_phone")
    res = telefon_aktualisieren(sit["tenant"], s["patientId"], s["telefon"])
    merke_tool(sit, "update_phone", res)
    if res.get("ok"):
        s["aktePhone"] = s["telefon"]
        if res.get("dryRun"):
            return "Die neue Nummer hätte ich jetzt eingetragen — der Test schreibt die Kartei noch nicht. "
        return "Erledigt — die alte Nummer ist gelöscht, Ihre neue steht jetzt in der Akte. "
    s["telefonAlt"] = "notiz"
    print(f"bianca-telefon-alt: Update fehlgeschlagen — {res.get('error')}", flush=True)
    return "Das Umtragen klappt gerade technisch nicht — ich gebe Ihre neue Nummer der Praxis mit. "


def _versicherung_ausfuehren(sit: dict, melde: Melde = None) -> str:
    """Gemeldeten privat<->gesetzlich-Wechsel in die Kartei schreiben (29.08.2026).

    Nur bei BESTANDSAKTE mit erkanntem Wechsel — Neupatienten bekommen den
    Status direkt beim Anlegen (akte_anlegen ueber den Buchungskontext).
    Scheitert das Update, haengt _buchen eine Praxis-Notiz an den Termin."""
    s = gehirn.sammler(sit)
    if not (s["versicherungWechsel"] and s["patientId"] and s["versicherung"]):
        return ""
    if s["versicherungAkte"] == s["versicherung"]:
        return ""  # schon umgetragen (z. B. Sicherheitsnetz lief bereits)
    if melde:
        melde("update_insurance")
    res = versicherung_aktualisieren(sit["tenant"], s["patientId"], s["versicherung"] == "privat")
    merke_tool(sit, "update_insurance", res)
    if res.get("ok"):
        s["versicherungAkte"] = s["versicherung"]
        art = "privat" if s["versicherung"] == "privat" else "gesetzlich"
        if res.get("dryRun"):
            return "Den Versichertenstatus hätte ich jetzt umgetragen — der Test schreibt die Kartei noch nicht. "
        return f"Ich habe das in Ihrer Kartei aktualisiert — Sie sind jetzt als {art} versichert geführt. "
    s["versicherungNotiz"] = True
    print(f"bianca-versicherung: Update fehlgeschlagen — {res.get('error')}", flush=True)
    return "Das Umtragen klappt gerade technisch nicht — ich gebe es der Praxis mit. "


def _arzt_notiz_offen(s: dict) -> bool:
    return _s(s.get("arztNotizFrage")) not in {"ja", "nein"}


def _nach_ok_buchen(sit: dict, t: str, melde: Melde = None) -> dict:
    """Nach Ja aufs Eintragen: PZR-Abfrage (falls noch offen), dann Doktor-Notiz.

    Chef 08.09.2026: jeder vergebene Termin bekommt die PZR-Frage — auch
    wenn der Wunschzeit-Zug sie (W-MEDDENT) nicht stellen durfte. Danach
    die Notiz für den Doktor; der Wortlaut landet im Terminpopup.
    """
    s = gehirn.sammler(sit)
    if gehirn.pzr_noch_fragen(s, sit):
        s["pzr"] = "gefragt"
        s["frage"] = "pzr"
        sit.pop("pzrUnklar", None)
        return {"text": gehirn.pzr_frage(s)}
    if not _arzt_notiz_offen(s):
        return _buchen(sit, melde)
    if gehirn.hat_arzt_notiz_inhalt(t):
        s["arztNotiz"] = gehirn.arzt_notiz_aus(t)
        s["arztNotizFrage"] = "ja"
        s["frage"] = ""
        return _buchen(sit, melde)
    s["arztNotizFrage"] = "gefragt"
    s["frage"] = "arzt_notiz"
    sit.pop("arztNotizUnklar", None)
    return {"text": gehirn.arzt_notiz_frage()}


def _pzr_weiter(sit: dict, vorsatz: str = "", melde: Melde = None) -> dict:
    """Nach PZR-Ja/Nein oder Kassen-Auskunft zurück auf den Buchungsweg."""
    s = gehirn.sammler(sit)
    s["frage"] = ""
    if s.get("phase") == "bestaetigen":
        weiter = _nach_ok_buchen(sit, "", melde)
        if vorsatz and weiter and _s(weiter.get("text")):
            weiter["text"] = vorsatz + weiter["text"]
        return weiter
    hintergrund.anstossen(sit)
    ein = _einschub(sit, vorsatz)
    if ein is not None:
        return ein
    fid, frage = gehirn.naechste_frage(sit)
    s["frage"] = fid
    if fid:
        return {"text": (vorsatz + frage).strip()}
    ang = _angebot(sit, melde)
    if ang and _s(ang.get("text")) and vorsatz:
        ang["text"] = vorsatz + ang["text"]
    return ang


def _pzr_preis_zug(sit: dict, t: str, melde: Melde = None) -> dict:
    """„Was kostet die Zahnreinigung?“ → ungefähr 120, Zahnärzte, dann Kasse."""
    s = gehirn.sammler(sit)
    treffer = pzr_kassen.deute(t)
    if treffer.get("satz"):
        s["pzrKasse"] = treffer["id"]
        text = f"{pzr_kassen.PREIS_SATZ} {pzr_kassen.PRAXIS_SATZ} {pzr_kassen.auskunft(treffer)}"
        if s.get("pzr") == "gefragt":
            s["frage"] = "pzr"
            return {"text": (text + " " + gehirn.pzr_frage(s)).strip()}
        return _pzr_weiter(sit, text + " ", melde)
    s["pzrKasse"] = "gefragt"
    s["frage"] = "pzr_kasse"
    sit.pop("pzrKasseUnklar", None)
    return {"text": pzr_kassen.preis_und_kasse_frage()}


def _pzr_kasse_zug(sit: dict, t: str, melde: Melde = None) -> dict | None:
    """Antwort auf die Kassenfrage — nur Tabelle, nie geschätzt."""
    s = gehirn.sammler(sit)
    treffer = pzr_kassen.deute(t)
    if not treffer:
        if gehirn.ist_zwischenfrage(t) and not pzr_kassen.ist_preisfrage(t):
            return None
        z = int(sit.get("pzrKasseUnklar") or 0) + 1
        sit["pzrKasseUnklar"] = z
        if z <= 1:
            s["frage"] = "pzr_kasse"
            return {"text": pzr_kassen.KASSE_FRAGE}
        s["pzrKasse"] = "offen"
        return _pzr_weiter(sit, pzr_kassen.unbekannt_satz() + " ", melde)
    s["pzrKasse"] = treffer.get("id") or "offen"
    text = pzr_kassen.auskunft(treffer)
    if s.get("pzr") == "gefragt":
        s["frage"] = "pzr"
        return {"text": (text + " " + gehirn.pzr_frage(s)).strip()}
    return _pzr_weiter(sit, text + " ", melde)


def _pzr_zug(sit: dict, t: str, melde: Melde = None) -> dict | None:
    """Ja/Nein auf die Mitbuch-Frage — oder Preis/Kasse dazwischen."""
    s = gehirn.sammler(sit)
    if gehirn.ist_pzr_preisfrage(t) and gehirn.pzr_im_kontext(s, t, sit):
        if gehirn.ist_ja(t) and not gehirn.ist_nein(t):
            s["pzr"] = "ja"
        return _pzr_preis_zug(sit, t, melde)
    if gehirn.ist_zwischenfrage(t) and not gehirn.ist_ja(t) and not gehirn.ist_nein(t):
        return None
    if gehirn.ist_pzr_zusage(t):
        s["pzr"] = "ja"
        dossier.markiere(sit, "pzr")
        gedaechtnis.fakt_senden(sit, "Zahnreinigung zum Termin dazugebucht.")
        return _pzr_weiter(sit, "Sehr gerne, die Zahnreinigung nehme ich mit auf. ", melde)
    if gehirn.ist_nein(t):
        s["pzr"] = "nein"
        return _pzr_weiter(sit, "Alles klar, dann ohne Zahnreinigung. ", melde)
    z = int(sit.get("pzrUnklar") or 0) + 1
    sit["pzrUnklar"] = z
    if z <= 1:
        s["frage"] = "pzr"
        return {"text": gehirn.pzr_frage(s)}
    s["pzr"] = "nein"
    return _pzr_weiter(sit, "Alles gut — dann erst einmal ohne Zahnreinigung. ", melde)


def _arzt_notiz_schliessen(sit: dict, *, notiz: str = "") -> None:
    s = gehirn.sammler(sit)
    s["arztNotiz"] = _s(notiz)
    s["arztNotizFrage"] = "ja" if s["arztNotiz"] else "nein"
    s["frage"] = ""
    sit.pop("arztNotizUnklar", None)


def _arzt_notiz_zug(sit: dict, t: str, melde: Melde = None) -> dict:
    """Antwort auf die Doktor-Notiz — einmal fragen, dann ernten oder buchen.

    Live Petsas 08.09.: Zwischenfrage ging ans LLM (`return None`), danach
    kam die Doktor-Frage immer wieder. Nie mehr ans Modell: Preis sagt die
    KI selbst, alles andere IST die Notiz. Ein nacktes Ja → ein Diktat;
    der nächste Satz landet im Popup. Keine zweite „Was soll ich mitgeben?“.
    """
    s = gehirn.sammler(sit)
    if gehirn.ist_pzr_preisfrage(t) and gehirn.pzr_im_kontext(s, t, sit):
        _arzt_notiz_schliessen(sit)
        return _pzr_preis_zug(sit, t, melde)
    if s["frage"] == "arzt_notiz":
        if gehirn.ist_nichts_notiz(t):
            _arzt_notiz_schliessen(sit)
            return _buchen(sit, melde)
        if gehirn.ist_ja(t) and not gehirn.hat_arzt_notiz_inhalt(t):
            s["arztNotizFrage"] = "diktat"
            s["frage"] = "arzt_notiz_diktat"
            sit.pop("arztNotizUnklar", None)
            return {"text": gehirn.arzt_notiz_diktat_frage()}
        if gehirn.hat_arzt_notiz_inhalt(t):
            _arzt_notiz_schliessen(sit, notiz=gehirn.arzt_notiz_aus(t))
            return _buchen(sit, melde)
        _arzt_notiz_schliessen(sit)
        return _buchen(sit, melde)
    if gehirn.ist_nichts_notiz(t):
        _arzt_notiz_schliessen(sit)
        return _buchen(sit, melde)
    if gehirn.hat_arzt_notiz_inhalt(t):
        _arzt_notiz_schliessen(sit, notiz=gehirn.arzt_notiz_aus(t))
        return _buchen(sit, melde)
    _arzt_notiz_schliessen(sit)
    return _buchen(sit, melde)


def _buchen(sit: dict, melde: Melde = None) -> dict:
    s = gehirn.sammler(sit)
    if (s["telefonAlt"] == "neu" and s["patientId"] and s["telefon"] and s["aktePhone"]
            and telefon.normaliert(s["telefon"]) != telefon.normaliert(s["aktePhone"])):
        # Sicherheitsnetz (Eskalations-/Renn-Fall): Entscheidung "neue Nummer"
        # steht, aber das Update lief noch nicht — JETZT nachholen, BEVOR die
        # Buchung die Bestaetigungs-SMS an die Akten-Nummer schickt.
        _telefon_alt_ausfuehren(sit, melde)
    if (s["versicherungWechsel"] and s["patientId"] and s["versicherung"]
            and s["versicherungAkte"] != s["versicherung"]):
        # Sicherheitsnetz: privat<->gesetzlich-Wechsel gemeldet, aber noch
        # nicht in der Kartei — vor der Buchung nachholen, damit der
        # Termin-Schnappschuss den richtigen Status traegt.
        _versicherung_ausfuehren(sit, melde)
    if melde:
        melde("book_slot")
    ctx = _ctx_bauen(sit)
    res = kal.book_slot(sit["tenant"], ctx, slot_iso=s["slotIso"])
    merke_tool(sit, "book_slot", res)
    book = {
        "booked": bool(res.get("booked")),
        "dryRun": bool(res.get("dryRun")),
        "slotIso": res.get("slotIso") or "",
        "spoken": res.get("spoken") or "",
    }
    if res.get("ok") and (res.get("booked") or res.get("dryRun")):
        s["phase"] = "gebucht"
        s["frage"] = ""
        sit.pop("buchIntent", None)
        sit.pop("bookFails", None)
        sit["flussFrage"] = ""
        sit["offered"] = []
        # Frischer Termin muss in Folge-Auskunft/Absage neu geladen werden.
        sit["upcoming"] = []
        sit["gefundenKey"] = ""
        text = res.get("spoken") or "Der Termin ist eingetragen."
        if res.get("booked"):
            neu = telefon.normaliert(s["telefon"]) if s["telefon"] else ""
            akte = telefon.normaliert(s["aktePhone"]) if s["aktePhone"] else ""
            if neu and akte and neu != akte:
                # Bestandsakte traegt eine ANDERE Nummer als die gerade
                # rueckbestaetigte — die Bestaetigungs-SMS der Plattform geht
                # an die AKTEN-Nummer (live 29.08.2026: Alt-Akte mit
                # 0123456789, die SMS lief ins Leere, der Anrufer wartete).
                # Regulaer ist der Konflikt hier schon GEKLAERT (telefon_alt-
                # Frage + masUpdatePatientPhone); dieser Zweig ist der Rest:
                # Entscheidung "SMS an die alte", ungeklaert oder Update kaputt.
                if s["telefonAlt"] == "akte":
                    text += (" Die Bestätigung kommt gleich per SMS an die Nummer aus"
                             " Ihrer Akte." + _SMS_LINK_SATZ)
                else:
                    if melde:
                        melde("note_appointment")
                    kal.note_appointment(
                        sit["tenant"], ctx, sit,
                        note=(
                            f"Anrufer nennt neue Handynummer: {s['telefon']} — "
                            f"Akte trägt {s['aktePhone']}. Bitte Akte aktualisieren."
                        ),
                    )
                    text += " Ihre neue Handynummer gebe ich der Praxis mit."
            elif s["telefon"] or s["aktePhone"]:
                text += " Die Bestätigung kommt gleich per SMS." + _SMS_LINK_SATZ
            # Praxis-Notizen ans Terminpopup (29.08.2026): unklares Geschlecht
            # (Default weiblich) und ein nicht geschriebener Versicherungs-
            # Wechsel gehoeren sichtbar in den Termin.
            hinweise = []
            if s["pzr"] == "ja":
                # Chef 30.08.2026, exakter Wortlaut fuers Notizfeld: die
                # Zahnreinigung wird nicht als zweiter Slot gebucht, sondern
                # der Praxis am Termin sichtbar gemacht.
                hinweise.append("PLUS PZR heute")
                text += " Die professionelle Zahnreinigung habe ich mit dazu vermerkt."
            # W-BLEACHING (Chef 03.09.2026): die Aufhellung wird nicht als
            # zweiter Slot gebucht — die Praxis sieht sie am Termin und
            # verlaengert selbst (ca. +1 Std., 350 Euro zusaetzlich).
            if s["bleaching"] == "ja":
                hinweise.append(
                    "PLUS Zahnaufhellung/Bleaching zur Zahnreinigung "
                    "(ca. +1 Std., 350 Euro zusätzlich) — bitte Terminlänge anpassen."
                )
                text += " Die Zahnaufhellung habe ich mit dazu vermerkt."
            elif s["bleaching"] == "beratung":
                if s["bleachingInfo"] == "unverbindlich":
                    hinweise.append(
                        "Zahnaufhellung unverbindlich mitbesprechen: Bitte prüfen, "
                        "ob sie möglich ist, besonders bei Zahnersatz im "
                        "Frontbereich, und den Patienten beraten."
                    )
                elif s["bleachingInfo"] == "zahnersatz":
                    hinweise.append(
                        "Anrufer interessiert sich für Zahnaufhellung, hat aber "
                        "Zahnersatz im Frontbereich (Kronen/Brücken/Veneers/"
                        "Implantate) — bitte prüfen, ob/wie möglich (ggf. eigene "
                        "Zähne an helle Kronen angleichen), und beim Termin beraten."
                    )
                else:
                    hinweise.append(
                        "Anrufer interessiert sich für Zahnaufhellung, ist aber "
                        "unsicher, ob sie bei ihm geht/sinnvoll ist — bitte beim "
                        "Termin ansehen und beraten."
                    )
            if s["versicherungNotiz"]:
                if s["versicherung"]:
                    hinweise.append(
                        f"Versichertenstatus am Telefon: jetzt {s['versicherung']} — "
                        "Akte konnte nicht aktualisiert werden, bitte nachtragen."
                    )
                else:
                    hinweise.append(
                        "Versichertenstatus (privat/gesetzlich) am Telefon nicht geklärt — bitte nachfragen."
                    )
            if s["geschlechtUnklar"]:
                hinweise.append(
                    "Bitte Geschlecht aktualisieren — Vorname unklar, vorläufig weiblich eingetragen."
                )
            # W-FUER-WEN (Chef 03.09.2026): Termin von einem Angehörigen
            # gebucht — die Praxis sieht am Termin, WER angerufen hat und
            # dass die Kontakt-Nummer dem Anrufer gehört, nicht dem Patienten.
            if s["fuerWen"]:
                # Wer hat angerufen? Erst der beim Fuer-Wen-Wechsel gemerkte
                # Kontaktname, sonst der erkannte Anrufer (Anrufer-ID/CF-pre)
                # — live 09.09.2026 fehlte im Termin, dass es der Nachbar von
                # Michael Petsas ist.
                kontakt = _s(s.get("kontaktName")) or gehirn.anrufer_name(sit)
                rolle_wort = gehirn.rolle_wort(s["fuerWen"])
                if rolle_wort and kontakt:
                    kern = f"Patient ist {rolle_wort} des Anrufers {kontakt}."
                elif rolle_wort:
                    kern = f"Patient ist {rolle_wort} des Anrufers."
                elif kontakt:
                    kern = f"Termin telefonisch gebucht vom Anrufer {kontakt}."
                else:
                    kern = "Termin telefonisch von einem Angehörigen gebucht."
                if s.get("telefon"):
                    kern += f" Kontakt-Nummer {s['telefon']} gehört dem Anrufer."
                hinweise.append(kern)
            # W-MOTIV-KATALOG (Chef 03.09.2026): "entsprechende kurznotizen
            # bitte nicht vergessen" — deckt der gebuchte Besuchsgrund den
            # O-Ton des Anrufers nicht wörtlich ab (Fallback- oder Fuzzy-
            # Mapping), bekommt die Praxis den Wortlaut ans Terminpopup.
            o_ton = kern_notes.grund_kurz(sit)
            if (o_ton and s["motivName"]
                    and not besuchsgrund.deckt_ab(f"{s['motivName']} {s['grund']}", o_ton)):
                hinweise.append(
                    f"Anrufer wörtlich: „{o_ton}“ — gebucht als {s['motivName']}."
                )
            antwort = _s(s.get("rueckblickAntwort"))
            if antwort:
                grund = gehirn.grund_sprechbar(s.get("letzterGrund") or "") or "letzter Besuch"
                hinweise.append(f"Zum letzten Besuch ({grund}): {antwort}")
            if _s(s.get("arztNotiz")):
                hinweise.append(
                    f"Anrufer an den Behandler: „{_s(s['arztNotiz'])}“ — "
                    "bitte beim Termin eingehen."
                )
                text += " Die Notiz für den Doktor habe ich zum Termin geschrieben."
            if hinweise:
                if melde:
                    melde("note_appointment")
                kal.note_appointment(sit["tenant"], ctx, sit, note=" ".join(hinweise))
            text += " Kann ich sonst noch etwas für Sie tun?"
        return {"text": text, "book": book}
    if res.get("slotTaken"):
        # W-BOOK-RETRY 01.09.2026: phone_agent-Deckel — max. 2 slotTaken,
        # gescheiterte ISOs sperren, Intent merken (kein zweites Confirm).
        fail_iso = _s(s.get("slotIso")) or _s(res.get("slotIso"))
        gesperrt = list(sit.get("slotGesperrt") or [])
        if fail_iso and fail_iso not in gesperrt:
            gesperrt.append(fail_iso)
        sit["slotGesperrt"] = gesperrt
        keys = {str(g)[:16] for g in gesperrt}
        sit["slotVorrat"] = [
            v for v in (sit.get("slotVorrat") or []) if str(v)[:16] not in keys
        ]
        fails = int(sit.get("bookFails") or 0) + 1
        sit["bookFails"] = fails
        sit["buchIntent"] = True  # Anrufer hat schon Ja gesagt
        s["slotIso"] = ""
        if fails >= 2:
            s["phase"] = "fertig"
            s["frage"] = ""
            sit["offered"] = []
            sit["keinSlotFertig"] = True
            verwalten.rueckruf_notiz(sit)
            return {
                "text": (
                    "Der Termin ist leider gerade nicht mehr frei, und die Alternativen "
                    "klappen auch nicht zuverlässig. Keine Sorge — ich schreibe eine Notiz, "
                    "und die Praxis meldet sich gleich bei Ihnen mit einem Termin. "
                    "Kann ich sonst noch etwas für Sie tun?"
                ),
                "book": book,
            }
        # Frisches Angebot OHNE die gesperrten ISOs.
        ang = _angebot(sit, melde)
        txt = _s(ang.get("text"))
        if txt and not txt.lower().startswith("der termin ist gerade weg"):
            txt = "Der Termin ist gerade weg. " + txt
        return {"text": txt or (res.get("spoken") or "Der Termin ist gerade weg."), "book": book}
    s["phase"] = ""
    gesagt = _s(res.get("spoken"))
    if "nummer" in gesagt.lower() or "handy" in gesagt.lower():
        s["frage"] = "telefon"
        s["telefonOk"] = False
        # Slot war schon gewaehlt und bestaetigt, nur die Handynummer fehlte.
        # Intent merken, damit die Buchung nach der Nummer DIREKT laeuft und
        # nicht erneut Slots anbietet (live 09.09.2026: "Welcher davon passt
        # Ihnen?" doppelt, nachdem 12:45 laengst gewaehlt war).
        if s.get("slotIso"):
            sit["buchIntent"] = True
    return {"text": gesagt or "Das hat gerade nicht geklappt. Die Praxis ruft Sie dazu zurück.", "book": book}


def _folge_weiter(sit: dict, vorsatz: str = "", melde: Melde = None) -> dict:
    hintergrund.anstossen(sit)
    ein = _einschub(sit, vorsatz)
    if ein is not None:
        return ein
    fid, frage = gehirn.naechste_frage(sit)
    s = gehirn.sammler(sit)
    s["frage"] = fid
    if fid:
        return {"text": (vorsatz + frage).strip()}
    ang = _angebot(sit, melde)
    if ang and _s(ang.get("text")) and vorsatz:
        ang["text"] = vorsatz + ang["text"]
    return ang or {"text": vorsatz.strip()}


def _folge_zug(sit: dict, t: str, neu: set, melde: Melde = None) -> dict | None:
    """Nicht-Zahn: letzter Besuch → noch darum? → Kontrolle buchen?"""
    s = gehirn.sammler(sit)
    if gehirn.ist_zwischenfrage(t) and not gehirn.ist_ja(t) and not gehirn.ist_nein(t):
        return None
    if not gehirn.ist_zwischenfrage(t):
        s["rueckblickAntwort"] = _s(t)[:160]
        gedaechtnis.fakt_senden(sit, f"Verlauf letzter Besuch: {s['rueckblickAntwort']}")
    s["rueckblick"] = "fertig"
    dossier.markiere(sit, "verlauf")
    if gehirn.ist_ja(t) and not gehirn.ist_nein(t):
        s["folge"] = "ja"
        if "grund" not in neu:
            gehirn.kontroll_setzen(sit)
        s["frage"] = "folge_kontrolle"
        sit.pop("folgeUnklar", None)
        return {"text": gehirn.folge_kontrolle_frage()}
    if gehirn.ist_nein(t):
        s["folge"] = "nein"
        s["frage"] = "grund"
        return {"text": "Worum geht es denn diesmal?"}
    if neu:
        s["frage"] = ""
        return _folge_weiter(sit, "", melde)
    z = int(sit.get("folgeUnklar") or 0) + 1
    sit["folgeUnklar"] = z
    if z <= 1:
        s["rueckblick"] = "gefragt"
        s["frage"] = "rueckblick"
        return {"text": gehirn.rueckblick_text(s, sit)}
    s["folge"] = "ja"
    gehirn.kontroll_setzen(sit)
    s["frage"] = "folge_kontrolle"
    return {"text": gehirn.folge_kontrolle_frage()}


def _folge_kontrolle_zug(sit: dict, t: str, neu: set, melde: Melde = None) -> dict | None:
    s = gehirn.sammler(sit)
    if gehirn.ist_zwischenfrage(t) and not gehirn.ist_ja(t) and not gehirn.ist_nein(t):
        return None
    if gehirn.ist_ja(t) and not gehirn.ist_nein(t):
        s["folgeKontroll"] = "ja"
        gehirn.kontroll_setzen(sit)
        s["frage"] = ""
        return _folge_weiter(sit, "Gerne, eine Kontrolle. ", melde)
    if gehirn.ist_nein(t):
        s["folgeKontroll"] = "nein"
        s["frage"] = "grund"
        return {"text": "Worum geht es denn diesmal?"}
    if neu:
        s["folgeKontroll"] = "nein"
        s["frage"] = ""
        return _folge_weiter(sit, "", melde)
    z = int(sit.get("folgeKontrollUnklar") or 0) + 1
    sit["folgeKontrollUnklar"] = z
    if z <= 1:
        s["frage"] = "folge_kontrolle"
        return {"text": gehirn.folge_kontrolle_frage()}
    s["folgeKontroll"] = "ja"
    gehirn.kontroll_setzen(sit)
    s["frage"] = ""
    return _folge_weiter(sit, "Ich trage eine Kontrolle ein. ", melde)


def _einschub(sit: dict, vorsatz: str = "") -> dict | None:
    """Rueckblick-/PZR-Einschub, wenn einer faellig ist — sonst None.

    Chef 30.08.2026: Bestandspatienten werden auf den letzten Besuch
    angesprochen (Verlaufs-Frage als Plauder-Einstieg, das LLM uebernimmt
    das sich entwickelnde Gespraech), und bei laengerer Pause wird eine
    Zahnreinigung zum Mitbuchen angeboten — beides EINMAL pro Anruf,
    der Rueckblick zuerst. Die offene Pflichtfrage verschiebt sich nur um
    einen Zug; naechste_frage stellt sie danach von selbst wieder."""
    s = gehirn.sammler(sit)
    if sit.get("rueckrufBuchung"):
        return None
    if gehirn.rueckblick_faellig(s):
        s["rueckblick"] = "gefragt"
        s["frage"] = "rueckblick"
        dossier.markiere(sit, "verlauf")
        return {"text": (vorsatz + gehirn.rueckblick_text(s, sit)).strip()}
    # W-ANLIEGEN-ART (09.09.2026): kein Zusatzangebot (PZR/Bleaching), während
    # sich jemand beschwert oder einen Notfall hat — das wäre taktlos.
    upsell_ok = not anliegen_art.upsell_gesperrt(sit)
    art_modus = anliegen_art.modus()
    if gehirn.pzr_faellig(s, sit):
        if not upsell_ok:
            spur.merken(sit, "anliegen-art", "pzr-gesperrt")
        else:
            if art_modus == "shadow" and anliegen_art.aktiv(sit):
                spur.merken(sit, "anliegen-art-shadow", "pzr")
            s["pzr"] = "gefragt"
            s["frage"] = "pzr"
            dossier.markiere(sit, "pzr")
            return {"text": (vorsatz + gehirn.pzr_frage(s)).strip()}
    # W-BLEACHING (Chef 03.09.2026): "wenn jemand anruft um eine
    # Zahnreinigung zu buchen kannst du auch fragen ob die Zähne mit
    # aufgehellt werden sollen" — einmal pro Anruf, nur wenn die Praxis
    # eine Aufhellung im Katalog fuehrt.
    if gehirn.bleaching_faellig(sit):
        if not upsell_ok:
            spur.merken(sit, "anliegen-art", "bleaching-gesperrt")
        else:
            if art_modus == "shadow" and anliegen_art.aktiv(sit):
                spur.merken(sit, "anliegen-art-shadow", "bleaching")
            s["bleaching"] = "gefragt"
            s["frage"] = "bleaching"
            return {"text": (vorsatz + gehirn.BLEACHING_FRAGE).strip()}
    return None


def _eskalieren(sit: dict, fid: str) -> str:
    """Zweimal keine verwertbare Antwort auf dieselbe Pflichtfrage: Standard
    setzen und weitergehen statt im Kreis zu fragen (Chef 27.08.2026:
    'bianca hängt in Schleifen fest')."""
    s = gehirn.sammler(sit)
    if fid == "schonmal":
        s["warSchonMal"] = False
        return "Kein Problem — dann nehme ich Sie einfach neu auf. "
    if fid == "arzt_check":
        s["arztCheck"] = "nein"
        return "Kein Problem, dann schauen wir neu. "
    if fid == "arzt":
        # Chef 03.09.2026: wer nicht weiss, zu welchem Arzt — immer der
        # Standard-Behandler (Meddent: Dr. Petsas), keine globale Suche.
        d = gehirn.arzt_default(sit.get("tenant") or {})
        s["arzt"] = d or {"typ": "egal"}
        beim = arzt_sprechname(
            _s((d or {}).get("calendarName")),
            sit.get("tenant") if isinstance(sit.get("tenant"), dict) else None,
        )
        if beim:
            return f"Machen wir es einfach: Ich schaue bei {beim} nach freien Terminen. "
        return "Machen wir es einfach: Ich schaue, wo es am schnellsten geht. "
    if fid == "grund":
        s["grund"] = "Kontrolluntersuchung"
        s["grundWortlaut"] = s.get("grundWortlaut") or "Kontrolle"
        vm = (besuchsgrund.fallback_motiv(sit.get("tenant") or {},
                                         katalog=motive.katalog(sit))
              or motiv_von(sit.get("tenant") or {}, "Kontrolluntersuchung"))
        if vm and not ist_akut_motiv(vm):
            s["motivId"] = _s(vm.get("id"))
            s["motivName"] = _s(vm.get("name"))
        else:
            s["motivId"] = ""
            s["motivName"] = ""
        return "Ich trage es erst einmal als Kontrolle ein — die Praxis passt das bei Bedarf an. "
    if fid == "wunsch":
        s["wunsch"] = {}
        return "Dann schaue ich einfach nach den nächsten freien Terminen. "
    if fid == "buchstabieren":
        s["buchstabiert"] = True
        return ""
    if fid == "rueckblick" and gehirn.nicht_zahn(sit):
        s["rueckblick"] = "fertig"
        s["folge"] = "ja"
        gehirn.kontroll_setzen(sit)
        return "Alles klar. "
    if fid == "folge_kontrolle":
        s["folgeKontroll"] = "ja"
        gehirn.kontroll_setzen(sit)
        return "Ich trage eine Kontrolle ein. "
    if fid == "pzr":
        s["pzr"] = "nein"
        return "Alles gut — dann erst einmal ohne Zahnreinigung. "
    if fid == "pzr_kasse":
        s["pzrKasse"] = "offen"
        return ("Kein Problem, den Zuschuss klären wir beim Termin. "
                "Im Einzelfall kann das abweichen. ")
    if fid == "bleaching":
        # Keine klare Antwort auf das Aufhellungs-Angebot: nicht nerven,
        # erstmal ohne — der Anrufer kann es jederzeit wieder ansprechen.
        s["bleaching"] = "nein"
        return "Alles gut — dann erst einmal ohne Aufhellung. "
    if fid == "bleaching_check":
        # Zahnersatz-Frage bleibt unklar: Notiz, der Doktor beraet (Chef
        # 03.09.2026: bei Ungewissheit schaut sich das der Doktor in Ruhe an).
        s["bleaching"] = "beratung"
        s["bleachingInfo"] = "unsicher"
        return ("Ich habe mir eine Notiz gemacht — der Doktor schaut sich das "
                "beim Termin in Ruhe an und berät Sie. ")
    if fid == "anrufer_check":
        # Zweimal keine klare Antwort auf das vorgelesene Name+Nummer-Paar:
        # NICHTS uebernehmen (Sicherheit vor Tempo — falsche Identitaet waere
        # fatal), klassisch nach Name und Nummer fragen (W-ANRUFER-CHECK).
        s["anruferCheck"] = "nein"
        return "Dann gehen wir auf Nummer sicher und nehmen Ihre Daten einfach frisch auf. "
    if fid == "telefon_check" and s["telefonOffen"]:
        # Zweimal keine klare Antwort auf die Rückbestätigung, aber auch kein
        # Nein: die vorgelesene Nummer gilt — nicht zum dritten Mal fragen
        # (Chef 27.08.2026: Nummer wurde mehrfach abgefragt und bestätigt).
        s["telefon"] = s["telefonOffen"]
        s["telefonOk"] = True
        s["telefonOffen"] = ""
        s["telefonTeil"] = ""
        return "Dann nehme ich die Nummer so auf. "
    if fid in {"telefon", "telefon_check"}:
        s["telefonAkte"] = True
        s["telefonOffen"] = ""
        s["telefonTeil"] = ""
        return "Die Nummer gleichen wir später in Ruhe ab. "
    if fid == "telefon_alt":
        # Zweimal keine klare Wahl: die gerade Ziffer fuer Ziffer bestaetigte
        # Nummer gilt — dafuer hat der Anrufer sie genannt. Das Umtragen holt
        # _buchen als Sicherheitsnetz nach (vor der SMS).
        s["telefonAlt"] = "neu"
        return "Dann nehme ich einfach Ihre neue Nummer. "
    if fid == "versicherung":
        # Keine klare Antwort: nicht blockieren und nichts raten — die Praxis
        # bekommt eine Notiz an den Termin (versicherungNotiz in _buchen).
        s["versicherungOk"] = True
        s["versicherungNotiz"] = True
        return "Das klären wir dann in der Praxis — ich vermerke es. "
    if fid == "versicherung_check":
        # Keine klare Antwort auf die Rueckfrage: Kartei-Stand bleibt.
        s["versicherungOk"] = True
        s["versicherung"] = s["versicherungAkte"]
        return "Dann lasse ich es wie gehabt eingetragen. "
    return "Entschuldigung, das habe ich nicht mitbekommen. "


# LLM hat nach frischer Buchung selbst nach Storno gefragt ("Soll ich … stornieren?") —
# auf Ja muss cancel_appointment laufen, nicht eine erfundene Bestaetigung
# (live 02.09. Tzannis: "Der Termin ist storniert" ohne Tool).
_STORNO_FRAGE_RE = re.compile(
    r"soll\s+ich[^.!?]{0,80}?(?:stornier\w*|absag\w*)|"
    r"(?:stornier\w*|absag\w*)[^.!?]{0,40}?(?:für\s+sie|fuer\s+sie|\?)",
    re.I,
)


def _frisch_termin(sit: dict) -> dict:
    """Termin, der in DIESEM Anruf gerade gebucht wurde (appointmentId)."""
    aid = _s((sit.get("booking") or {}).get("appointmentId")) or _s(
        (sit.get("lastBook") or {}).get("appointmentId")
    )
    if not aid:
        return {}
    s = gehirn.sammler(sit)
    iso = _s(s.get("slotIso")) or _s((sit.get("lastBook") or {}).get("slotIso"))
    a = s.get("arzt") or {}
    return {
        "id": aid,
        "iso": iso,
        "spoken": spoken_slot(iso) if iso else "wie gerade vereinbart",
        "calendarId": _s(a.get("calendarId")),
        "doctorName": _s(a.get("calendarName")),
        "motivId": _s(s.get("motivId")),
        "motivName": _s(s.get("motivName")),
    }


def _letzte_fragte_storno(sit: dict) -> bool:
    for m in reversed(sit.get("messages") or []):
        if (m or {}).get("role") == "assistant":
            return bool(_STORNO_FRAGE_RE.search(_s(m.get("content"))))
    return False


def _frisch_verschieben(sit: dict, t: str, melde: Melde = None) -> dict:
    """Frisch gebuchten Termin verschieben — ohne Nachnamen-Suche.

    Live Thaler Petsas 08.09.: „Können wir den verlegen … nach vorne?“
    landete im Talk, der Slots erfand und nie agentMoveAppointment rief.
    """
    s = gehirn.sammler(sit)
    frisch = _frisch_termin(sit)
    s["modus"] = "verschieben"
    if not frisch.get("id"):
        return verwalten.zug(sit, t, {"modus"}, melde)
    sit["gefunden"] = [frisch]
    sit["gefundenKey"] = f"{s.get('vorname')}|{s.get('nachname')}".lower()
    sit["verwaltenTermin"] = frisch["id"]
    sit.setdefault("booking", {})["appointmentId"] = frisch["id"]
    verwalten._richtung_merken(sit, t)
    if sit.get("verschiebRichtung") or s.get("wunsch"):
        return verwalten._verschieb_angebot(sit, melde)
    return verwalten._verschieb_wunsch_frage(sit, frisch)


def _frisch_absagen(sit: dict, melde: Melde = None) -> dict:
    """Frisch gebuchten Termin wirklich per CF stornieren."""
    termin = _frisch_termin(sit)
    if not termin:
        return {"text": "Welchen Termin soll ich absagen?"}
    sit["verwaltenTermin"] = termin["id"]
    sit["gefunden"] = [termin]
    gehirn.sammler(sit)["modus"] = "absagen"
    return verwalten._absagen(sit, melde)


_DOKUMENT_RE = re.compile(
    r"\brezept\w*|\b(?:ü|ue)berweisung\w*|(?:ü|ue)berweisen",
    re.I,
)


def _abgeben_kontakt(sit: dict) -> None:
    """Name + Nummer fuer die Notiz: Anrufer aus der Leitung, sonst Diktat.

    Live Berger 08.09.: dieselbe 0151… dreimal richtig transkribiert, aber
    die Notiz sah nur s['telefon'] — die Ernte legt die Kette nach
    telefonOffen (Buchungs-Readback). Beim Abgeben gilt die gehoerte
    Nummer sofort; ein bekannter Anrufer wird nicht nochmal ausgefragt.
    """
    s = gehirn.sammler(sit)
    a = gehirn.anrufer_bekannt(sit)
    if a:
        if not s["nachname"]:
            s["vorname"] = _s(a.get("vorname")) or s["vorname"]
            s["nachname"] = _s(a.get("nachname"))
            s["buchstabiert"] = True
            s["bekannt"] = True
            if _s(a.get("patientId")):
                s["patientId"] = _s(a.get("patientId"))
        if not s["telefon"]:
            d = telefon.mit_fuehrender_null(a.get("telefon") or "")
            if telefon.plausibel(d):
                s["telefon"] = d
                s["telefonOk"] = True
    if not s["telefon"] and s.get("telefonOffen"):
        d = telefon.mit_fuehrender_null(s["telefonOffen"])
        if telefon.plausibel(d):
            s["telefon"] = d
            s["telefonOk"] = True
            s["telefonOffen"] = ""


def _abgeben_zug(sit: dict, t: str) -> dict | None:
    """ABGEBEN-Anliegen (W-HIRN 03.09.2026): Rueckruf/Nachricht deterministisch.

    Frueher gab es diesen Weg nur, wenn zufaellig keine Slots frei waren
    (verwalten.rueckruf_notiz) — jetzt ist er eine eigene Loesung: Name und
    Nummer einsammeln, ECHTE Notiz (praxis_notizen.jsonl + Dock), fertig.
    KEIN Termin-Angebot. None => LLM klaert die Zwischenfrage.

    W-MEDDENT (04.09.2026): Rezept/Überweisung nie „ausstellen“ — klar sagen,
    dass die Praxis entscheidet; Notiz + Abholung/Termin.
    """
    from kern import hirn as kern_hirn

    s = gehirn.sammler(sit)
    ab = sit.get("hirnAbgeben") or {}
    dok = bool(_DOKUMENT_RE.search(_s(ab.get("was")) + " " + t))
    if dok and praxisregeln.dokument_vorsprache_aktiv(sit.get("tenant")):
        # Praxisregel (DB): Blessing nimmt am Telefon keinen Rezept-/
        # Ueberweisungsauftrag auf. Persoenliche Vorsprache, ggf. kurze
        # aerztliche Kontrolle — freundlich, ohne Name/Nummer-Sammelei.
        ab["offen"] = False
        sit["hirnAbgeben"] = ab
        s["frage"] = ""
        s["phase"] = "fertig"
        kern_hirn.erledigt(sit)
        return {"text": praxisregeln.dokument_antwort()}
    neu = gehirn.einsammeln(sit, t)
    sit["ernteZuletzt"] = sorted(neu)
    _abgeben_kontakt(sit)
    if not s["nachname"]:
        if s["frage"] == "name" and not neu:
            return None  # Zwischenfrage — LLM antwortet, die Frage bleibt offen
        s["frage"] = "name"
        if dok:
            return {"text": (
                "Rezept und Überweisung kann ich am Telefon nicht ausstellen — "
                "das entscheidet die Praxis. Ich notiere Ihren Wunsch gern. "
                "Wie ist Ihr Name?"
            )}
        return {"text": "Das richte ich gern aus. Für den Rückruf: Wie ist Ihr Name?"}
    tel = s["telefon"] or s["aktePhone"]
    if not tel:
        if s["frage"] == "telefon" and not neu:
            return None
        s["frage"] = "telefon"
        return {"text": "Danke. Und unter welcher Nummer erreichen wir Sie am besten?"}
    was = _s(ab.get("was"))
    if dok and not _DOKUMENT_RE.search(was):
        was = (was + " " + t).strip() or "Rezept/Überweisung"
    verwalten.abgeben_notiz(sit, was=was)
    ab["offen"] = False
    sit["hirnAbgeben"] = ab
    s["frage"] = ""
    s["phase"] = "fertig"
    kern_hirn.erledigt(sit)
    if dok:
        return {"text": (
            f"Alles notiert — die Praxis prüft Ihren Wunsch und meldet sich "
            f"unter der {telefon.sprechbar(tel)}. Ausstellen kann ich selbst "
            f"nicht. Kann ich sonst noch etwas für Sie tun?"
        )}
    return {"text": (
        f"Alles notiert — die Praxis meldet sich bei Ihnen unter der "
        f"{telefon.sprechbar(tel)}. Kann ich sonst noch etwas für Sie tun?"
    )}


def _aenderung_feld(t: str) -> str:
    """Was will der Anrufer an der Readback-Zusammenfassung ändern?"""
    if _AENDERUNG_GRUND_RE.search(t):
        return "grund"
    if _AENDERUNG_NAME_RE.search(t):
        return "name"
    if _AENDERUNG_NUMMER_RE.search(t):
        return "nummer"
    if _AENDERUNG_ZEIT_RE.search(t):
        return "zeit"
    return ""


def _nachname_korr_zug(sit: dict, t: str, melde: Melde = None) -> dict:
    """Nach der Buchung den Nachnamen korrigieren — nie neu slotsuchen."""
    s = gehirn.sammler(sit)
    sit["flussFrage"] = ""
    sit["offered"] = []
    if s["frage"] != "nachname_korr":
        sit["nachnameAlt"] = _s(s.get("nachname"))
        s["nachname"] = ""
        s["buchstabiert"] = False
        s["buchstabenTeil"] = ""
        s["buchstabierHilfe"] = False
        s["vornameTeil"] = ""
        s["vornameGehoert"] = ""
        s["frage"] = "nachname_korr"
        return {"text": (
            "Gerne, dann korrigiere ich den Nachnamen. "
            "Wie lautet er jetzt? Bitte buchstabieren Sie ihn einmal."
        )}
    gehirn.einsammeln(sit, t)
    neu = _s(s.get("nachname"))
    alt = _s(sit.get("nachnameAlt"))
    if neu and (s.get("buchstabiert") or len(neu) >= 3):
        s["frage"] = ""
        sit.pop("nachnameAlt", None)
        note = (
            f"Nachname korrigiert: {alt} → {neu}. Bitte Akte aktualisieren."
            if alt and alt.lower() != neu.lower()
            else f"Nachname bestätigt/korrigiert: {neu}. Bitte Akte prüfen."
        )
        if melde:
            melde("note_appointment")
        try:
            kal.note_appointment(sit.get("tenant") or {}, _ctx_bauen(sit), sit, note=note)
        except Exception as e:
            print(f"bianca-nachname-korr note fail {e}", flush=True)
        an = gehirn.anrede(s) or neu
        return {"text": (
            f"Alles klar, {an} — der Nachname steht so in der Notiz für die Praxis. "
            "Kann ich sonst noch etwas für Sie tun?"
        )}
    return {"text": "Bitte buchstabieren Sie den Nachnamen einmal, damit ich nichts falsch schreibe."}


def _vorrat_leeren(sit: dict) -> None:
    sit["slotVorrat"] = []
    sit["vorratKey"] = ""
    sit["vorratGemerkt"] = False
    sit.pop("vorratDispatch", None)
    sit.pop("vorratFuer", None)
    sit["offered"] = []
    sit.pop("angebotKalender", None)
    sit.pop("buchIntent", None)


def _aenderung_zug(sit: dict, t: str, melde: Melde = None) -> dict | None:
    """Nach 'Nein' auf die Bestätigung: nur das gewählte Feld neu einsammeln.

    Slot/Angebot bleiben stehen, solange nicht die Zeit geändert wird —
    sonst fragt Bianca den ganzen Termin nochmal ab (Live-Schleife
    03.09.2026: viermal 'Soll ich das so eintragen?')."""
    s = gehirn.sammler(sit)
    feld = _aenderung_feld(t)
    if feld == "name":
        gehirn.name_fuer_aenderung_leeren(sit)
        s["frage"] = "name"
        s["phase"] = ""
        neu = gehirn.einsammeln(sit, t)
        sit["ernteZuletzt"] = sorted(neu)
        # "Ändere den Namen auf Levi" — ein einzelnes Rest-Wort ist der
        # Vorname (Live: Levi), nicht der Nachname.
        if s["nachname"] and not s["vorname"] and len(_s(s["nachname"]).split()) == 1:
            s["vorname"] = s["nachname"]
            s["nachname"] = ""
        hintergrund.anstossen(sit)
        fid, frage = gehirn.naechste_frage(sit)
        s["frage"] = fid
        if fid:
            return {"text": (_quittung(s, neu) + frage).strip()}
        if s["slotIso"]:
            return _readback(sit)
        ang = _angebot(sit, melde)
        if ang and _s(ang.get("text")):
            q = _quittung(s, neu)
            if q:
                ang["text"] = q + ang["text"]
        return ang
    if feld == "nummer":
        s["telefon"] = ""
        s["telefonOk"] = False
        s["telefonOffen"] = ""
        s["telefonTeil"] = ""
        s["telefonAkte"] = False
        s["phase"] = ""
        s["frage"] = "telefon"
        return {"text": "Welche Handynummer darf ich eintragen?"}
    if feld == "zeit":
        s["slotIso"] = ""
        s["wunsch"] = None
        sit["offered"] = []
        sit.pop("angebotKalender", None)
        sit.pop("buchIntent", None)
        s["phase"] = ""
        s["frage"] = "wunsch"
        return {"text": "Wann würde es Ihnen denn besser passen — eher vormittags oder nachmittags?"}
    if feld == "grund":
        s["grund"] = ""
        s["grundWortlaut"] = ""
        s["motivId"] = ""
        s["motivName"] = ""
        s["slotIso"] = ""
        s["phase"] = ""
        s["frage"] = "grund"
        _vorrat_leeren(sit)
        neu = gehirn.einsammeln(sit, t)
        sit["ernteZuletzt"] = sorted(neu)
        hintergrund.anstossen(sit)
        if s["grund"]:
            fid, frage = gehirn.naechste_frage(sit)
            s["frage"] = fid
            if fid:
                return {"text": (_quittung(s, neu) + frage).strip()}
            ang = _angebot(sit, melde)
            if ang and _s(ang.get("text")):
                q = _quittung(s, neu)
                if q:
                    ang["text"] = q + ang["text"]
            return ang
        return {"text": (
            "Alles klar, dann der Besuchsgrund. "
            "Worum geht es denn — eine Kontrolle, Schmerzen, oder etwas anderes?"
        )}
    s["frage"] = "aenderung"
    return {"text": "Was darf ich ändern — der Zeitpunkt, der Name, die Nummer oder der Besuchsgrund?"}


def _rueckruf_zug(sit: dict, t: str, melde: Melde = None) -> dict | None:
    """Rückrufer fragt nach dem Grund — mitteilen, als erledigt setzen, Zeit fragen.

    Chef: erledigt in der Sekunde, in der der Angerufene zurückruft und nach
    dem Grund fragt (erledigt weil mitgeteilt). Narval: Name, Nummer, Grund
    und letzter Behandler stehen — nur vormittags/nachmittags fehlt."""
    if sit.get("rueckrufMitgeteilt"):
        return None
    if not gehirn.fragt_anrufgrund(t, sit):
        return None
    if sit.get("gedaechtnis") is None:
        gedaechtnis.kontext_abwarten(sit, 1.5)
    if not gehirn.rueckruf_hat_offen(sit):
        # Herbst 08.09.: erkannt, aber Notiz status=none / MAS weg —
        # nie ans LLM (die erfand "keine Akte" / "Akte angelegt").
        a = gehirn.anrufer_bekannt(sit)
        if not a:
            return None
        nach = _s(a.get("nachname"))
        g = _s(a.get("geschlecht")).lower()
        wer = ""
        if nach:
            if g in {"m", "male", "herr"}:
                wer = "Herr " + nach
            elif g in {"f", "female", "frau"}:
                wer = "Frau " + nach
            else:
                wer = nach
        kopf = f"{wer}, ich habe Sie erkannt. " if wer else "Ich habe Sie erkannt. "
        # Nie Abholung/Narval raten — nur wenn die Notiz das hergibt.
        return {"text": (
            f"{kopf}Den genauen Grund des Anrufs habe ich gerade nicht "
            "in der Notiz. Worum geht es denn?"
        )}
    if sit.get("anruferKartei") is None:
        hintergrund.anrufer_kartei_abwarten(sit, 1.0)
    gehirn.rueckruf_starten(sit)
    sag = gehirn.rueckruf_mitteil_satz(sit)
    sit["rueckrufSag"] = sag
    sit["rueckrufMitgeteilt"] = True
    gedaechtnis.offen_erledigen(sit, "Mitgeteilt — Rückrufer informiert.")
    neu = gehirn.einsammeln(sit, t)
    sit["ernteZuletzt"] = sorted(neu)
    hintergrund.anstossen(sit)
    s = gehirn.sammler(sit)
    fid, frage = gehirn.naechste_frage(sit)
    s["frage"] = fid
    if fid:
        return {"text": f"{sag} {frage}".strip()}
    if s.get("slotIso"):
        return _readback(sit)
    ang = _angebot(sit, melde)
    if ang and _s(ang.get("text")):
        ang["text"] = f"{sag} {ang['text']}".strip()
        return ang
    return {"text": sag}


def zug(sit: dict, gesagt: str, melde: Melde = None) -> dict | None:
    """Ein Anrufer-Satz durch den Buchungsfluss. None => LLM übernimmt."""
    s = gehirn.sammler(sit)
    t = _s(gesagt)
    if not t:
        return None

    # W-ANLIEGEN-ART (09.09.2026): Servicebeschwerde/Notfall festhalten, damit
    # _einschub keine Zusatzangebote macht (Default off => no-op).
    anliegen_art.merken(sit, t)

    akut_text = praxisregeln.notfall_antwort(
        sit.get("tenant"),
        t,
        bereits_akut=bool(sit.get("akutSofort")),
    )
    if akut_text:
        # Praxisregel (DB): kein normaler Termin und keine Slot-Suche. Der
        # Notfallpfad gewinnt auch, wenn die Intent-Schicht bereits "buchen"
        # gesetzt hat.
        sit["akutSofort"] = True
        sit["offered"] = []
        sit.pop("angebotKalender", None)
        s["slotIso"] = ""
        s["frage"] = ""
        s["phase"] = "fertig"
        s["modus"] = ""
        from kern import hirn as kern_hirn
        kern_hirn.erledigt(sit)
        return {"text": akut_text}

    # Weiterleitungs-Wunsch ("Ich möchte einen Menschen sprechen"): eigener
    # deterministischer Zweig VOR allem anderen — Platzhalter fuer Kirris
    # Zaluma-/SIP-Weiterleitung (bianca/weiterleiten.py).
    wl = weiterleiten.zug(sit, t, melde)
    if wl is not None:
        return wl

    rr = _rueckruf_zug(sit, t, melde)
    if rr is not None:
        return rr

    if (s["modus"] == "buchen" and s["frage"] in {
            "name", "nachname", "vorname", "buchstabieren",
        } and _BUCHSTABIER_META_RE.search(t)):
        # Der Anrufer bietet den sicheren Weg selbst an. Bei einer bekannten
        # Akte wäre keine Buchstabierung nötig; andernfalls gezielt beim
        # Nachnamen bleiben, den unser Mehrzug-Sammler robust erfasst.
        if s.get("bekannt") or s.get("patientId"):
            fid, frage = gehirn.naechste_frage(sit)
            s["frage"] = fid
            return {"text": (
                "Nein danke, ich habe Ihre Akte bereits sicher gefunden. "
                + (frage or "Was kann ich sonst für Sie tun?")
            ).strip()}
        s["frage"] = "buchstabieren"
        return {"text": (
            "Ja, bitte. Buchstabieren Sie zuerst Ihren Nachnamen langsam. "
            "Am Ende sagen Sie einfach fertig."
        )}

    # W-HIRN (03.09.2026): die Intent-Schicht hat den Modus evtl. schon vor
    # diesem Zug geschaltet — das Signal wandert in die Ernte-Menge, damit
    # verwalten seinen Einstiegs-Reset faehrt wie frueher bei der Regex.
    hirn_modus_neu = bool(sit.pop("hirnModusNeu", False))
    task_handoff = _s(sit.pop("taskHandoff", ""))

    if (s["phase"] == "fertig" and not s["modus"]
            and (_ABSCHIED_RE.search(t) or _VERHOERTES_DANKE_RE.match(t))):
        # Live MedDent 09.09.: nach erfolgreicher Absage führten zwei
        # verhörte Danke-Sätze erst in „nicht verstanden“, dann in die
        # Schleifenbremse. Der abgeschlossene Job verabschiedet sich sofort.
        return {"text": "Sehr gerne. Auf Wiederhören."}

    # Kein Slot gefunden, echte Rückrufnotiz geschrieben: der Vorgang ist
    # abgeschlossen. Dank/Abschied beendet freundlich; andere Folgesätze
    # bestätigen höchstens die Notiz, starten aber niemals dieselbe leere
    # Slotsuche erneut (Live Andrejevic 09.09.: viermal dieselbe Ansage).
    kein_slot_fertig = (
        bool(sit.get("keinSlotFertig"))
        or "kein freier termin" in _s(sit.get("praxisNotiz")).lower()
    )
    if s["modus"] == "buchen" and s["phase"] == "fertig" and kein_slot_fertig:
        if _NOCH_EIN_TERMIN_RE.search(t):
            sit.pop("keinSlotFertig", None)
            s["phase"] = ""
            s["frage"] = "wunsch"
            s["wunsch"] = None
            s["wunschText"] = ""
            sit["offered"] = []
            return {"text": "Gerne. Wann passt es Ihnen für den weiteren Termin?"}
        if _ABSCHIED_RE.search(t):
            return {"text": "Sehr gerne. Auf Wiederhören."}
        return {"text": (
            "Die Rückrufbitte ist bereits für die Praxis notiert. "
            "Kann ich sonst noch etwas für Sie tun?"
        )}

    # Rueckruf-/Notiz-Anliegen (ABGEBEN): eigener deterministischer Zweig —
    # Name + Nummer einsammeln, echte Notiz schreiben, KEIN Termin-Angebot.
    # Direkt zurueck (auch None => LLM): der Satz ist hier schon geerntet,
    # ein zweites einsammeln unten wuerde Ziffern doppelt zaehlen.
    ab = sit.get("hirnAbgeben")
    if isinstance(ab, dict) and ab.get("offen"):
        return _abgeben_zug(sit, t)

    if s["phase"] == "gebucht" or (
        _schon_gebucht(sit) and s["phase"] in {"gebucht", "fertig"}
    ):
        # Thaler 08.09. Leonid: „Nachname hat sich geändert“ darf nach der
        # Buchung keine Slot-Frage mehr aufmachen (sonst Doppelbuchung).
        if s["frage"] == "nachname_korr" or _NACHNAME_KORR_RE.search(t):
            s["phase"] = "gebucht"
            return _nachname_korr_zug(sit, t, melde)
        if _NOCH_EIN_TERMIN_RE.search(t):
            sit["nochEinTermin"] = True
            s["phase"] = ""
            s["frage"] = ""
        elif _SCHON_TERMIN_RE.search(t):
            s["phase"] = "gebucht"
            return _erinner_termin(sit)
        elif _ABSCHIED_RE.search(t):
            return _abschied_nach_buchung(sit)
        elif s["phase"] == "fertig" and _schon_gebucht(sit):
            # Nachricht/Notiz nach der Buchung: kein Slot-Nachschub.
            return {"text": "Kann ich sonst noch etwas für Sie tun?"}
        elif s["phase"] == "gebucht":
            # Frisch gebucht — aber "sagen Sie ihn doch wieder ab" / "wann war
            # das nochmal?" gehoert in die Termin-Verwaltung, nicht ans LLM.
            neu = gehirn.einsammeln(sit, t)
            if hirn_modus_neu:
                neu.add("modus")
            sit["ernteZuletzt"] = sorted(neu)  # Task-Signal fuer die Talk-Schicht
            frisch = _frisch_termin(sit)

            # Eigene Rueckfrage nach erfundener LLM-Storno-Behauptung (Erledigt-Wache).
            if s["frage"] == "frisch_absage_ok":
                if gehirn.ist_ja(t) and not gehirn.ist_nein(t):
                    return _frisch_absagen(sit, melde)
                if gehirn.ist_nein(t):
                    s["frage"] = ""
                    return {"text": (
                        "Alles klar, der Termin bleibt bestehen. "
                        "Kann ich sonst noch etwas für Sie tun?"
                    )}
                return {"text": "Soll ich den Termin wirklich absagen? Ein kurzes Ja oder Nein genügt."}

            # LLM fragte bereits "Soll ich stornieren?" — Ja => wirklich canceln
            # (W-FRISCH-ABSAGE 02.09.2026).
            if (frisch and _letzte_fragte_storno(sit)
                    and gehirn.ist_ja(t) and not gehirn.ist_nein(t)):
                return _frisch_absagen(sit, melde)

            if s["modus"] in {"absagen", "verschieben", "auskunft"}:
                sit["gefundenKey"] = ""  # Bestand frisch laden, der neue Termin zaehlt mit
                sit["upcoming"] = []  # list_appointments nicht aus Stale-Cache speisen
                # Frische Buchung: Nachnamen-Suche ueberspringen, direkt bestaetigen.
                if s["modus"] == "absagen" and frisch:
                    return verwalten._absage_frage(sit, frisch)
                if s["modus"] == "verschieben" and frisch:
                    return _frisch_verschieben(sit, t, melde)
                return verwalten.zug(sit, t, neu, melde)
            if frisch and gehirn.ist_verschiebewunsch(t):
                return _frisch_verschieben(sit, t, melde)
            return None

    if s["phase"] == "bestaetigen":
        if s["frage"] in {"arzt_notiz", "arzt_notiz_diktat"}:
            return _arzt_notiz_zug(sit, t, melde)
        if s["frage"] == "pzr_kasse":
            return _pzr_kasse_zug(sit, t, melde)
        if s["frage"] == "pzr":
            return _pzr_zug(sit, t, melde)
        # Vor Ja/Nein: „Ja, ist der Termin noch frei?“ ist eine Faktenfrage,
        # kein Buchungs-Ja. „Wiederhole …“ darf auch beim zweiten Mal nie
        # den Schreibaufruf ausloesen.
        if _TERMIN_WIEDERHOLEN_RE.search(t) or _TERMIN_ABGLEICH_RE.search(t):
            sit.pop("bestaetigenUnklar", None)
            return _termin_nochmal(sit, t)
        if gehirn.ist_ja(t):
            sit.pop("bestaetigenUnklar", None)
            return _nach_ok_buchen(sit, t, melde)
        if gehirn.ist_nein(t):
            sit.pop("bestaetigenUnklar", None)
            sit.pop("buchIntent", None)
            # W-FUER-WEN (Chef 03.09.2026): "Nein, der Termin ist nicht für
            # mich, der ist für meinen Sohn" — NICHT den Slot verwerfen,
            # sondern den Patienten umschreiben: einsammeln erntet fuerWen
            # und loest die Kartei-Identitaet des Anrufers vom Patienten
            # (Live-Fall: die Korrektur lief dreimal ins Leere).
            if gehirn.fuer_wen_signal(t):
                neu = gehirn.einsammeln(sit, t)
                sit["ernteZuletzt"] = sorted(neu)
                s["phase"] = ""
                fid2, frage2 = gehirn.naechste_frage(sit)
                s["frage"] = fid2
                if fid2:
                    return {"text": f"Ah, verstehe! {frage2}"}
                return _readback(sit)
            # W-SCHLEIFE: Slot UND Angebot stehen lassen — der Anrufer
            # will oft nur den Namen korrigieren (Live: "Der Name." /
            # "Ändere den Namen auf Levi" landete sonst wieder in der
            # Bestätigung, weil naechste_frage den alten Namen sah).
            s["phase"] = ""
            s["frage"] = "aenderung"
            if _aenderung_feld(t):
                return _aenderung_zug(sit, t, melde)
            return {"text": "Kein Problem. Was darf ich ändern — der Zeitpunkt, der Name, die Nummer oder der Besuchsgrund?"}
        if _aenderung_feld(t):
            sit.pop("bestaetigenUnklar", None)
            sit.pop("buchIntent", None)
            s["phase"] = ""
            s["frage"] = "aenderung"
            return _aenderung_zug(sit, t, melde)

    if s["frage"] == "aenderung" or (
        s["frage"] == "bestaetigung" and s["phase"] != "bestaetigen"
        and _aenderung_feld(t) and not gehirn.ist_ja(t)
    ):
        return _aenderung_zug(sit, t, melde)

    if s["phase"] in {"angebot", "bestaetigen"} and sit.get("offered"):
        iso = _slot_wahl(t, sit["offered"])
        if iso:
            s["slotIso"] = iso
            # Nach Ja + slotTaken: Intent steht — Alternativ-Slot direkt buchen
            # (kein zweites "Dann halte ich fest…", W-BOOK-RETRY 01.09.2026).
            if sit.get("buchIntent"):
                return _buchen(sit, melde)
            return _readback(sit)

    if (s["modus"] == "buchen" and s["frage"] == "wunsch"
            and s["wunsch"] is None and _REISEORT_RE.search(t)
            and gehirn._wunsch_deuten(t) is None):
        return {"text": (
            "Verstanden. An welchen Tagen sind Sie hier, "
            "und passt es eher vormittags oder nachmittags?"
        )}

    neu = gehirn.einsammeln(sit, t)
    if hirn_modus_neu:
        neu.add("modus")
    sit["ernteZuletzt"] = sorted(neu)  # Task-Signal fuer die Talk-Schicht

    if "grundNichtBuchbar" in neu:
        # Thaler: andere Behandlungen nie als Kontrolle/Besprechung tarnen
        # und nie einen dafuer unzulaessigen Termin anbieten. Die sechs
        # freigegebenen Gruppen klar nennen und bei der Grundfrage bleiben.
        from kern import zimmer_map
        s["phase"] = ""
        s["frage"] = "grund"
        return {"text": zimmer_map.buchbare_ansage()}

    # Live 08.09.2026: bei langsamer Buchstabierung/Nummerndiktat beendete
    # die SIP-VAD jeden Pausenabschnitt als eigenen Zug. Die Fragmentlogik
    # speicherte ihn zwar, sprach danach aber jedes Mal „Den Anfang habe
    # ich …“ und fiel dem Anrufer damit fortlaufend ins Wort. Ein verwertetes
    # Teilstück ist noch KEIN Antwortzug: still weiterhören, den Job-Floor
    # halten und erst nach vollständigem Wert bzw. „fertig“ sprechen.
    if {"buchstabenTeil", "vornameTeil", "telefonTeil"} & neu:
        return {
            "text": "",
            "warte": True,
            "stilleMs": gehirn.stille_ms(s),
        }

    if "anruferWohl" in neu:
        # "Gut." auf den Hallo-Satz — Identitaet bleibt offen, nur die
        # echte Ja/Nein-Frage nochmal, ohne den Verspiel-Vorsatz.
        s["frage"] = "anrufer_check"
        selbst = s["modus"] == "buchen"
        return {"text": "Schön! " + gehirn.anrufer_check_schluss(selbst=selbst)}

    # Bestandstermin-Anliegen (absagen/verschieben/ansagen) haben ihren
    # eigenen deterministischen Fluss.
    if s["modus"] in {"absagen", "verschieben", "auskunft"}:
        if "modus" in neu:
            sit["gefundenKey"] = ""
            sit["upcoming"] = []
        return verwalten.zug(sit, t, neu, melde)

    # PZR-Preis/Kasse (Chef 08.09.2026): deterministisch, nie LLM-Zahlen.
    # Nicht in Nummer/Slot/Confirm-Pflichtfragen — dort bleibt der Anker.
    if s["frage"] == "pzr_kasse":
        r_kasse = _pzr_kasse_zug(sit, t, melde)
        if r_kasse is not None:
            return r_kasse
    if (gehirn.ist_pzr_preisfrage(t) and gehirn.pzr_im_kontext(s, t, sit)
            and s["frage"] not in {
                "telefon_check", "telefon", "buchstabieren",
                "slotwahl", "bestaetigung", "arzt_notiz", "arzt_notiz_diktat",
            }):
        return _pzr_preis_zug(sit, t, melde)

    # Nacktes PZR-Wort ("Zahnreinigung"): Motiv merken, nicht sofort
    # buchen — nachfragen, ob ein Termin gewollt ist (Chef 07.09.2026).
    if s["frage"] == "termin_anbieten":
        if gehirn.ist_zwischenfrage(t):
            return None
        if gehirn.ist_nein(t) and not gehirn.ist_ja(t):
            s["frage"] = ""
            s["terminAnbieten"] = "nein"
            return {"text": "Alles klar. Was kann ich sonst für Sie tun?"}
        if gehirn.ist_ja(t) or "wunsch" in neu or gehirn.ist_terminwunsch(t):
            s["terminAnbieten"] = "ja"
            s["frage"] = ""
            if s["modus"] != "buchen":
                s["modus"] = "buchen"
                neu.add("modus")
            # Sofort die erste Pflichtfrage — kein Bleaching-/PZR-Einschub
            # vor Schonmal/Name (sonst kaeme die Aufhellung vor der Buchung).
            hintergrund.anstossen(sit)
            fid2, frage2 = gehirn.naechste_frage(sit)
            s["frage"] = fid2
            if fid2:
                return {"text": frage2}
            return _angebot(sit, melde)
        s["frage"] = "termin_anbieten"
        return {"text": gehirn.termin_anbieten_frage(s)}

    if (not s["modus"] and "modus" not in neu
            and gehirn.ist_nacktes_pzr(t) and gehirn.ist_pzr_grund(s)
            and motive.fuehrt_pzr(sit)):
        s["frage"] = "termin_anbieten"
        s["terminAnbieten"] = "gefragt"
        return {"text": gehirn.termin_anbieten_frage(s)}

    if s["modus"] != "buchen" and "modus" not in neu:
        return None

    if s["frage"] == "folge_kontrolle":
        return _folge_kontrolle_zug(sit, t, neu, melde)

    if s["frage"] == "rueckblick":
        if gehirn.nicht_zahn(sit):
            return _folge_zug(sit, t, neu, melde)
        # Antwort auf die Verlaufs-Frage zum letzten Besuch (30.08.2026).
        # Ernte im Satz -> die Maschine macht normal weiter (faellt durch);
        # klar positive Kurzantwort -> Mini-Empathie + naechster Schritt;
        # alles andere (Erzaehlung, Negatives, Gegenfrage) -> LLM plaudert
        # (Talk-Schicht), der Stand im Prompt fuehrt spaeter zurueck.
        if not gehirn.ist_zwischenfrage(t):
            s["rueckblickAntwort"] = _s(t)[:160]
            gedaechtnis.fakt_senden(sit, f"Verlauf letzter Besuch: {s['rueckblickAntwort']}")
        s["rueckblick"] = "fertig"
        s["frage"] = ""
        dossier.markiere(sit, "verlauf")
        if not neu:
            ton = gehirn.rueckblick_reaktion(t)
            if not ton or gehirn.ist_zwischenfrage(t):
                return None
            hintergrund.anstossen(sit)
            ein = _einschub(sit, ton)  # z. B. direkt die Zahnreinigungs-Frage
            if ein is not None:
                return ein
            fid2, frage2 = gehirn.naechste_frage(sit)
            s["frage"] = fid2
            if fid2:
                return {"text": (ton + frage2).strip()}
            ang = _angebot(sit, melde)
            if ang and _s(ang.get("text")):
                ang["text"] = ton + ang["text"]
            return ang

    if s["phase"] in {"angebot", "bestaetigen"}:
        if {"wunsch", "arzt", "grund"} & neu:
            # Anrufer will etwas anderes (Zeit/Arzt/Grund geändert): neu anbieten.
            # Das alte Angebot merken — kommt dasselbe wieder heraus, sagt die
            # Wiederhol-Wache in _angebot das ehrlich an.
            sit["angebotZuletzt"] = [o["iso"] for o in sit.get("offered") or []]
            s["phase"] = ""
            s["slotIso"] = ""
            sit["offered"] = []
            sit.pop("angebotKalender", None)
            if {"arzt", "grund"} & neu:
                # Anderer Kalender-Rahmen: alter Slot-Vorrat ist wertlos.
                sit["slotVorrat"] = []
                sit["vorratKey"] = ""
                sit["vorratGemerkt"] = False
                sit.pop("vorratDispatch", None)
        elif gehirn.ist_nein(t) or _ABLEHNUNG_RE.search(t):
            s["phase"] = ""
            s["slotIso"] = ""
            sit["offered"] = []
            sit.pop("angebotKalender", None)
            sit.pop("buchIntent", None)
            s["frage"] = "wunsch"
            return {"text": "Wann würde es Ihnen denn besser passen — eher vormittags oder nachmittags?"}
        elif (s["phase"] == "bestaetigen" and not gehirn.ist_zwischenfrage(t)
              and not gespraech.traegt_thema(sit, t)):
            # Unklare Antwort auf "Soll ich das so eintragen?" bleibt
            # DETERMINISTISCH: das LLM erfand hier sonst Erledigt-Meldungen,
            # und der Frage-Anker stellte die Frage danach ERNEUT — genau die
            # Doppelfrage vom 27.08.2026. Beim zweiten unklaren, nicht
            # verneinenden Anlauf wird der Termin erneut vorgelesen. Ohne
            # ausdrueckliches Ja wird NIEMALS geschrieben.
            z = int(sit.get("bestaetigenUnklar") or 0) + 1
            sit["bestaetigenUnklar"] = z
            if z <= 1:
                return {"text": "Entschuldigung, das habe ich akustisch nicht verstanden — soll ich den Termin so eintragen? Ein kurzes Ja genügt."}
            return _termin_nochmal(sit)
        else:
            return None  # Zwischenfrage — LLM antwortet, Status hält die Spur

    # Offene Nummern-Rückfrage + Extra-Info („Termin für heute"): merken,
    # aber bei der Nummer bleiben — nicht die ganze Ansage wiederholen
    # und nicht ins Wunsch/Slot-Thema kippen (Chef 08.09.2026).
    if (s["frage"] == "telefon_check" and s["telefonOffen"] and not s["telefonOk"]
            and neu and "telefonKorrektur" not in neu
            and not gehirn.ist_ja(t) and not gehirn.ist_nein(t)):
        s["frage"] = "telefon_check"
        return {"text": "Gut, das notiere ich. Stimmt die Nummer so? Ein kurzes Ja oder Nein genügt."}

    if "telefonKorrektur" in neu:
        # Nein + andere Nummer im selben Satz: die neue sofort vorlesen.
        # Dieselbe (gesperrte) Kette: nicht nochmal, sondern neu diktieren.
        if s["telefonOffen"]:
            s["frage"] = "telefon_check"
            return {"text": "Entschuldigung! " + gehirn.readback_text(s["telefonOffen"])}
        s["frage"] = "telefon"
        return {"text": "Entschuldigung! Dann bitte noch einmal — ganz in Ruhe, Ziffer für Ziffer."}

    if "telefonAlt" in neu:
        # Entscheidung zur Akten-Nummer ist gefallen: SOFORT umsetzen (bei
        # "neu" schreibt masUpdatePatientPhone die Akte, BEVOR spaeter die
        # Buchung die Bestaetigungs-SMS ausloest), dann normal weiter.
        vor = _telefon_alt_ausfuehren(sit, melde)
        hintergrund.anstossen(sit)
        fid2, frage2 = gehirn.naechste_frage(sit)
        s["frage"] = fid2
        if fid2:
            return {"text": (vor + frage2).strip()}
        ang = _angebot(sit, melde)
        if ang and _s(ang.get("text")):
            ang["text"] = vor + ang["text"]
        return ang

    if "versicherung" in neu and s["versicherungWechsel"] and s["patientId"]:
        # Gemeldeter privat<->gesetzlich-Wechsel einer Bestandsakte: SOFORT
        # in die Kartei schreiben (Erledigt-Ansage nur nach echtem Erfolg),
        # dann normal weiter im Fragenfluss.
        vor = _versicherung_ausfuehren(sit, melde)
        if vor:
            hintergrund.anstossen(sit)
            fid2, frage2 = gehirn.naechste_frage(sit)
            s["frage"] = fid2
            if fid2:
                return {"text": (vor + frage2).strip()}
            ang = _angebot(sit, melde)
            if ang and _s(ang.get("text")):
                ang["text"] = vor + ang["text"]
            return ang

    hintergrund.anstossen(sit)

    fid, frage = gehirn.naechste_frage(sit)

    if (task_handoff == "buchen" or hirn_modus_neu) and fid:
        # Semantischer Router ODER synchrones Intent-Hirn haben denselben Satz
        # gerade als neue Buchung eingeordnet. Jetzt zuerst die sichere
        # Pflichtfrage stellen. Eine formulierte Frage wie „Haben Sie diese
        # Woche noch einen Termin?“ ist damit kein freies LLM-Zwischenthema,
        # das Verfügbarkeit oder Patientennamen erfinden könnte.
        s["frage"] = fid
        return {"text": (_quittung(s, neu) + frage).strip()}

    # Rueckblick auf den letzten Besuch / Zahnreinigungs-Angebot (30.08.2026):
    # als eigener Zug, sobald die Kartei-Daten da sind — aber nie vor einer
    # Nummern-Rueckbestaetigung, nie statt einer Zwischenfragen-Antwort und
    # nie mitten in einem unbeantworteten Pflichtfragen-Faden.
    # W-MEDDENT (04.09.2026): nie direkt nach frischer Wunschzeit — erst
    # Slot anbieten (Detschel-Live: PZR mitten in „Nachmittag 15.09.“).
    if (fid not in {"telefon_check", "telefon_alt", "anrufer_check", "arzt_check", "arzt",
                    "name", "nachname", "vorname", "buchstabieren", "telefon"}
            and not (fid == "arzt" and "arztCheck" in neu)
            and "wunsch" not in neu
            and (neu or not s["frage"])
            and not gehirn.ist_zwischenfrage(t)
            and not gespraech.traegt_thema(sit, t)):
        ein = _einschub(sit, _quittung(s, neu))
        if ein is not None:
            return ein

    if fid:
        if (fid == "telefon_alt" and s["frage"] == "telefon_alt"
                and not neu and _NOCHMAL_RE.search(t)):
            # "Welche Nummer nochmal?" — die Alt-Nummer wortgleich erneut
            # vorlesen, so oft der Anrufer fragt (Chef 29.08.2026). Nie ans
            # LLM: das kennt die Ziffern aus der Akte nicht.
            return {"text": gehirn.telefon_alt_frage(s)}
        if gehirn.ist_zwischenfrage(t) or (
            not neu and fid not in {"telefon_check", "anrufer_check"}
            and gespraech.traegt_thema(sit, t)
        ):
            # Echte Zwischenfrage/Abschweifung ("Was kostet das?") ODER ein
            # erzaehltes Nebenthema OHNE Ernte ("Meine Tochter heiratet!"):
            # das LLM antwortet natürlich (Talk-Schicht), zurueckgefuehrt
            # wird ueber Floor/Anker — zählt NIE als Leerlauf (Chef 27.08.:
            # "Abschweifungen müssen erlaubt sein"). Brachte der Satz Ernte,
            # macht die Maschine normal weiter; die Nummern-Rückbestätigung
            # (telefon_check) bleibt IMMER deterministisch.
            if s["frage"] not in {"pzr", "bleaching", "bleaching_check"}:
                # Eine offene Zahnreinigungs-/Aufhellungs-Frage bleibt offen
                # ("Was kostet die denn?" -> LLM nennt den Preis, das Ja
                # danach zaehlt).
                s["frage"] = fid
            return None
        if not neu and s["frage"] == fid:
            # Dieselbe Frage ist schon offen und der Satz brachte nichts Neues.
            zaehler = sit.setdefault("frageLeer", {})
            zaehler[fid] = int(zaehler.get(fid) or 0) + 1
            if zaehler[fid] <= 1:
                if fid == "telefon_check":
                    # Rückbestätigung bleibt deterministisch: das LLM erfand
                    # hier "die Nummer habe ich notiert" UND der Anker fragte
                    # danach erneut — die Doppelfrage vom 27.08.2026.
                    return {"text": "Entschuldigung, kurz zur Sicherheit: Stimmt die Nummer so? Ein kurzes Ja oder Nein genügt."}
                if fid == "anrufer_check":
                    # Identitaets-Kontrolle bleibt ebenfalls deterministisch —
                    # das LLM darf hier nie "erkannt" erfinden (W-ANRUFER-CHECK).
                    return {"text": "Entschuldigung, kurz zur Kontrolle: Habe ich Sie richtig erkannt? Ein kurzes Ja oder Nein genügt."}
                if fid == "telefon_alt":
                    # Auch die Akten-Nummer-Frage bleibt deterministisch —
                    # mit der Nummer im Ohr faellt die Wahl leichter.
                    return {"text": gehirn.telefon_alt_frage(s)}
                # Erster Leerlauf: das LLM antwortet kurz,
                # der Stand im Prompt führt zur offenen Frage zurück.
                return None
            # Zweiter Leerlauf: Standard setzen und WEITERGEHEN — nie wieder
            # dieselbe Frage im Kreis (Live-Schleife 27.08.2026).
            uebergang = _eskalieren(sit, fid)
            fid2, frage2 = gehirn.naechste_frage(sit)
            if not fid2:
                s["frage"] = ""
                ang = _angebot(sit, melde)
                if uebergang and ang and _s(ang.get("text")):
                    ang["text"] = uebergang + ang["text"]
                return ang
            s["frage"] = fid2
            if fid2 == fid:
                uebergang = uebergang or "Entschuldigung, das habe ich nicht mitbekommen. "
            return {"text": (uebergang + frage2).strip()}
        if s["frage"] != fid:
            (sit.get("frageLeer") or {}).pop(fid, None)
        s["frage"] = fid
        return {"text": (_quittung(s, neu) + frage).strip()}

    if not neu and s["frage"]:
        return None  # nichts Verwertbares gehört — LLM klärt, Status führt zurück

    s["frage"] = ""
    if sit.get("buchIntent") and s.get("slotIso"):
        # Slot war schon gewaehlt und der Anrufer hatte Ja gesagt — nur ein
        # Feld (z. B. die Handynummer) fehlte noch. Jetzt direkt buchen, NICHT
        # erneut Slots anbieten (live 09.09.2026: doppelte Slotwahl-Frage).
        return _buchen(sit, melde)
    ang = _angebot(sit, melde)
    if ang and _s(ang.get("text")):
        q = _quittung(s, neu)
        if q:
            ang["text"] = q + ang["text"]
    return ang


def status_zeile(sit: dict) -> str:
    """Kompakter Buchungsstand für den LLM-Prompt, wenn der Fluss abgibt."""
    s = sit.get("sammler") or {}
    if s.get("modus") in {"absagen", "verschieben", "auskunft"}:
        return verwalten.status_zeile(sit)
    if not s or s.get("modus") != "buchen":
        return ""
    a = s.get("arzt") or {}
    teile = [
        f"Name={_s(s.get('vorname'))} {_s(s.get('nachname'))}".strip(),
        f"Grund={_s(s.get('grund')) or '?'}",
        f"Arzt={_s(a.get('calendarName')) or a.get('typ') or '?'}",
        f"Telefon={_s(s.get('telefon')) or '?'}",
        f"Phase={_s(s.get('phase')) or 'sammeln'}",
    ]
    if s.get("pzr") == "ja":
        teile.append("Zahnreinigung=kommt mit dazu")
    if s.get("bleaching") == "ja":
        teile.append("Zahnaufhellung=kommt mit dazu (ca. +1 Std., 350 Euro zusätzlich)")
    offen = ""
    if s.get("frage"):
        offen = f" Offene Frage: {s['frage']}."
    if s.get("frage") == "pzr":
        offen += (" (Bianca hat gefragt, ob eine professionelle Zahnreinigung mit dazu soll. "
                  "Preis: ungefähr 120 Euro. Bei uns führen die Zahnärzte die Reinigung "
                  "selbst durch, nicht Prophylaxehelferinnen. Preis NUR auf Nachfrage. "
                  "Kassen-Zuschüsse NUR aus der PZR-Tabelle, immer mit "
                  "„Im Einzelfall kann das abweichen.“)")
    if s.get("frage") == "pzr_kasse":
        offen += (" (Bianca hat Preis und Praxis-Hinweis gesagt und fragt die Krankenkasse. "
                  "Zuschuss NUR aus der PZR-Tabelle, immer warnen: im Einzelfall abweichend. "
                  "Immer „ungefähr“.)")
    if s.get("frage") in {"arzt_notiz", "arzt_notiz_diktat"}:
        offen += (" (Bianca fragt, ob eine Notiz für den Doktor zum Termin "
                  "soll — besondere Frage, auf die er eingehen soll. "
                  "Kein medizinischer Rat; den Wortlaut nur aufnehmen.)")
    if s.get("frage") == "folge_kontrolle":
        offen += (" (Bianca fragt, ob sie eine Kontrolle buchen soll. "
                  "Nie Krebs sagen — immer Kontrolle.)")
    if s.get("frage") in {"bleaching", "bleaching_check"}:
        # W-BLEACHING (Chef 03.09.2026): Faktenwissen fuer freie Nachfragen.
        # Preis NUR auf Nachfrage nennen ("nicht mit den kosten ins haus
        # fallen") — die Angebotsfrage selbst nennt keine Kosten.
        offen += (" (Bianca hat eine Zahnaufhellung/Bleaching zur Zahnreinigung"
                  " angeboten: dauert ca. eine Stunde länger. Preis: 350 Euro"
                  " zusätzlich — den Preis NUR nennen, wenn der Anrufer danach"
                  " fragt. Bei Zahnersatz im Frontbereich — Kronen, Brücken,"
                  " Veneers, Implantaten — ist sie unter Umständen nicht möglich;"
                  " Ausnahme: die eigenen Zähne sollen an zu helle Kronen"
                  " angepasst werden. Ist der Anrufer unsicher, ob das bei ihm"
                  " geht oder sinnvoll ist: Bianca sagt, sie hat eine Notiz"
                  " gemacht und der Doktor schaut es sich in Ruhe an und berät —"
                  " Bianca berät NIE selbst medizinisch.)")
    # Rueckblick-Kontext (30.08.2026): das LLM plaudert ueber den letzten
    # Besuch mit — es muss wissen, wann und weswegen der Anrufer da war.
    if s.get("rueckblick") and s.get("letzterGrund"):
        damals = gehirn.grund_am_telefon(s.get("letzterGrund") or "")
        offen += (f" Kontext: Der Anrufer war zuletzt am {_s(s.get('letzterBesuch'))[:10]} da, "
                  f"Grund damals: {damals}. Sage niemals Krebs — am Telefon heißt das Kontrolle.")
        if s.get("rueckblick") == "gefragt":
            offen += " Bianca hat gerade nach dem Verlauf gefragt — reagiere empathisch auf die Antwort."
    slots = "; ".join(_s(x.get("spoken")) for x in (sit.get("offered") or [])[:3])
    if slots:
        offen += f" Angeboten: {slots}."
    return (
        "Laufende Terminbuchung (führe den Anrufer immer dorthin zurück): "
        + ", ".join(teile) + "." + offen
    )
