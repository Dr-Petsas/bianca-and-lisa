"""W-LISA-BUCHUNG (09.10.2026): Lisa bucht mit Biancas Buchungsmaschine.

Anruf bb329162: Lisa sollte einen freigewordenen OP-Termin am 4.11. anbieten.
Ihr freies Modell erfand „4.11. um 11 Uhr“, kannte das Motiv nicht (gebucht
haette es eine Kontrolle) und fragte nach jedem Ja „welchen Termin darf ich
fest eintragen?“. Lisa hatte sieben eigene Werkzeuge, aber keinen der Wege,
die Bianca seit Wochen live sicher macht: Motiv je Kalender, Slotsuche ab
Wunschtag, Rücklese, Handy-Tor, Buchungsbeweis.

Ab jetzt gilt für einen Termin-Buchungsauftrag des Chefs: Sobald feststeht,
dass die richtige Person am Telefon ist, füllt `vorbereiten` Biancas Sammler
aus Akte und Auftrag vor (Patient, Behandler, Motiv, Wunschtag, Nummer) und
jeder weitere Satz läuft durch `bianca.flow.zug`. Das freie Modell spricht
nur noch Nebenthemen und bucht nie.

Das Motiv kommt vom Arzt (Chef 09.10.2026: „wenn im prompt eine terminart
ohne freigabe steht wird trotzdem diese terminart gebucht. sie kommt ja vom
doktor die anweisung“). Deshalb trägt der Buchungskontext `arztAuftrag` —
die Slotsuche weicht nie auf Kontrolle aus, und die Cloud Function erhält
`doctorOrder` (nur mit Maschinen-Token wirksam).

Notaus: `LISA_BUCHUNG=0` => Lisa spricht wie vorher frei mit ihren Werkzeugen.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from bianca import telefon
from kern import motive, spur, stille
from kern.slots import parse_slot_wish

_BUCHEN_RE = re.compile(
    r"\b(vereinbar\w*|ausmach\w*|ausgemacht|buch\w*|anbiet\w*|anbieten|"
    r"frei\s*geworden|freigeworden|einplan\w*|einbestell\w*|eintrag\w*|"
    r"mach\w*\s+(?:den|einen|ihm|ihr)\s+(?:\w+\s+)?termin\w*)\b",
    re.I,
)
# Anruf f9a2ceb2: „Termin machen ab dem 3.11. zur Kontrolle“ trägt keines der
# Verben oben — Lisa fiel auf ihr freies Modell zurück, erfand eine Uhrzeit und
# scheiterte an der Akte. Ein Termin MIT Zeitraum/Grund oder „Termin machen/
# geben/bekommen“ ist ebenso ein Buchungsauftrag.
_BUCHEN_FORM_RE = re.compile(
    r"\btermin\w*\s+(?:machen|geben|bekommen|kriegen|finden|anbieten)\b|"
    r"\bneue[nrs]?\s+termin|"
    r"\btermin\w*\s+(?:ab|zur|zum|für|fuer|im|in|nach|wegen)\b",
    re.I,
)
_AB_DATUM_RE = re.compile(
    r"\b(?:ab|frühestens|fruehestens|nicht\s+vor)\s+(?:dem\s+|den\s+)?\d{1,2}\.", re.I)
_INFO_RE = re.compile(
    r"\b(erinner\w*|bestätig\w*|bestaetig\w*|denk\w*\s+an|nicht\s+vergessen|"
    r"wie\s+es\s+\w+\s+geht|nachfrag\w*)\b",
    re.I,
)
_NICHT_BUCHEN_RE = re.compile(
    r"\b(absag\w*|abgesagt|storn\w*|verschieb\w*|vorverleg\w*|verleg\w*|umbuch\w*)\b",
    re.I,
)
_KEIN_INTERESSE_RE = re.compile(
    r"\b(kein\s+interesse|brauche?\s+(?:ich\s+)?(?:keinen|nicht)|"
    r"will\s+(?:ich\s+)?(?:keinen|nicht)|m[öo]chte\s+(?:ich\s+)?(?:keinen|nicht)|"
    r"passt\s+(?:mir\s+)?(?:gar\s+)?nicht|lieber\s+nicht|nein\s+danke)\b",
    re.I,
)

# Motiv-Kuerzel der Praxis-Kataloge („IMP Implantation OP klein“).
_KUERZEL_RE = re.compile(r"^[A-ZÄÖÜ]{2,4}\d?$")
_OP_RE = re.compile(r"^(op|ops|operation\w*|operier\w*|operativ\w*|eingriff\w*|"
                    r"eingesetzt|einsetzen|einsetzung)$")
_GROESSE = {"klein", "kleine", "kleiner", "gross", "grosse", "grosser"}
_STOP = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "einer", "und", "oder", "mit", "ihm", "ihr", "ihn", "sie", "seine", "seinen",
    "ihre", "ihren", "zur", "zum", "fuer", "bei", "von", "aus", "auf", "an",
    "am", "im", "in", "ist", "sind", "wird", "werden", "kann", "koennte", "soll",
    "bitte", "patient", "patientin", "patienten", "termin", "termine", "ruf",
    "rufe", "anrufen", "mache", "machen", "aus", "bekommen", "freigeworden",
    "frei", "geworden", "vereinbaren", "ausmachen", "noch", "dann", "dort",
    "dem", "diesem", "dieser", "neuen", "neue", "neu",
}
_GENERISCH = {
    "beratung", "behandlung", "beschwerden", "kontrolle", "kontrolluntersuchung",
    "sprechstunde", "termin", "untersuchung",
}
# Anruf 2c42c37c: „Sinuslift und 12 Implantate unter ITN“ ist keine kleine OP
# (Katalog: klein 30 min, groß 120 min). Ohne ausdrückliches „klein“ gilt bei
# solchen Signalen die große Variante.
_GROSS_SIGNAL_RE = re.compile(
    r"\b(sinus\w*|augment\w*|knochenaufbau\w*|itn|intubation\w*|\w*narkose\w*|"
    r"mehrere|beidseit\w*|(?:[2-9]|[1-9]\d|zwei|drei|vier|fünf|fuenf|sechs|sieben|"
    r"acht|neun|zehn|elf|zwölf|zwoelf)\s+implantat\w*)",
    re.I,
)
_KLEIN_RE = re.compile(r"\bklein\w*", re.I)

_ORDINAL = {
    "erst": 1, "zweit": 2, "dritt": 3, "viert": 4, "fünft": 5, "fuenft": 5,
    "sechst": 6, "siebt": 7, "siebent": 7, "acht": 8, "neunt": 9, "zehnt": 10,
    "elft": 11, "zwölft": 12, "zwoelft": 12, "dreizehnt": 13, "vierzehnt": 14,
    "fünfzehnt": 15, "fuenfzehnt": 15, "sechzehnt": 16, "siebzehnt": 17,
    "achtzehnt": 18, "neunzehnt": 19, "zwanzigst": 20, "einundzwanzigst": 21,
    "zweiundzwanzigst": 22, "dreiundzwanzigst": 23, "vierundzwanzigst": 24,
    "fünfundzwanzigst": 25, "fuenfundzwanzigst": 25, "sechsundzwanzigst": 26,
    "siebenundzwanzigst": 27, "achtundzwanzigst": 28, "neunundzwanzigst": 29,
    "dreißigst": 30, "dreissigst": 30, "einunddreißigst": 31, "einunddreissigst": 31,
}
_ORDINAL_RE = re.compile(
    r"\bam\s+(" + "|".join(sorted(_ORDINAL, key=len, reverse=True)) + r")(?:en|e|er)\b",
    re.I,
)


def tag_ordinal(text: str) -> str:
    """„am fünften“ → „am 5.“ (Anruf 2c42c37c: der Parser kennt nur Ziffern)."""
    return _ORDINAL_RE.sub(lambda m: f"am {_ORDINAL[m.group(1).lower()]}.", text)


PROMPT_REGEL = (
    "TERMIN-FLUSS: Termine, Uhrzeiten und das Eintragen übernimmt das System. "
    "Nenne nie selbst ein Datum oder eine Uhrzeit, sage nie, dass etwas "
    "eingetragen oder gebucht ist, und frage nie, wann du eintragen sollst. "
    "Beantworte nur die Nebenfrage in einem kurzen Satz."
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def an() -> bool:
    return os.environ.get("LISA_BUCHUNG", "1").strip().lower() not in {"0", "off", "false", "no"}


def ist_buchungsauftrag(auftrag: str) -> bool:
    """Will der Chef, dass Lisa einen NEUEN Termin vereinbart?"""
    from lisa.mission import ist_termin_auftrag

    t = _s(auftrag)
    termin_wort = ist_termin_auftrag(t) or "termin" in t.lower()
    if not t or not termin_wort or _NICHT_BUCHEN_RE.search(t):
        return False
    if _BUCHEN_RE.search(t):
        return True
    return bool(_BUCHEN_FORM_RE.search(t)) and not _INFO_RE.search(t)


def aktiv(sit: dict) -> bool:
    return an() and bool(sit.get("lisaTermin"))


# --- Motiv aus dem Auftrag -------------------------------------------------

def _norm(text: str) -> str:
    t = _s(text).lower()
    t = t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", " ", t)


def _auftrag_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for w in _norm(text).split():
        if _OP_RE.match(w):
            out.add("op")
        elif len(w) >= 3 and w not in _STOP and not w.isdigit():
            out.add(w)
    return out


def _motiv_tokens(name: str) -> set[str]:
    out: set[str] = set()
    roh = _s(name).split()
    for i, w in enumerate(roh):
        if i == 0 and _KUERZEL_RE.match(w):
            continue
        for n in _norm(w).split():
            if _OP_RE.match(n):
                out.add("op")
            elif n in _GROESSE or n in _STOP or n.isdigit() or len(n) < 2:
                continue
            else:
                out.add(n)
    return out


def _passt(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) < 3 or len(b) < 3:
        return False
    from bianca.besuchsgrund import _token_passt

    return _token_passt(a, b)


def motiv_aus_auftrag(auftrag: str, katalog: list[dict], calendar_id: str = "") -> dict | None:
    """Das Motiv, das der Arzt im Auftrag nennt — streng, sonst None.

    Ein Motiv gilt nur, wenn JEDES unterscheidende Wort seines Namens im
    Auftrag steht („Implantation“ + „OP“ für „IMP Implantation OP klein“).
    Ein Treffer nur über allgemeine Wörter (Beratung, Kontrolle) zählt nur,
    wenn das Motiv gar kein anderes Wort trägt. Die Online-Freigabe zählt
    hier nicht — die Anweisung kommt vom Arzt.
    """
    worte = _auftrag_tokens(auftrag)
    if not worte:
        return None
    gross = bool(re.search(r"\bgro(?:ss|ß)\w*", _s(auftrag), re.I)) or (
        bool(_GROSS_SIGNAL_RE.search(_s(auftrag))) and not _KLEIN_RE.search(_s(auftrag)))
    treffer: list[tuple[int, dict]] = []
    for vm in motive.fuer_kalender(katalog or [], calendar_id):
        name = _s(vm.get("name"))
        toks = _motiv_tokens(name)
        if not toks:
            continue
        unterscheidend = toks - _GENERISCH or toks
        if all(any(_passt(a, d) for a in worte) for d in unterscheidend):
            treffer.append((len(unterscheidend), vm))
    if not treffer:
        return None
    top = max(n for n, _ in treffer)
    kandidaten = [vm for n, vm in treffer if n == top]
    groesse = "gross" if gross else "klein"
    passend = [vm for vm in kandidaten
               if groesse in _norm(_s(vm.get("name"))).split()
               or (groesse == "gross" and "grosse" in _norm(_s(vm.get("name"))).split())]
    if passend:
        kandidaten = passend
    online = [vm for vm in kandidaten if vm.get("allowOnlineBooking") is not False]
    return min(online or kandidaten, key=lambda vm: len(_s(vm.get("name"))))


def _motiv_rueckfall(sit: dict, auftrag: str, katalog: list[dict], calendar_id: str) -> dict | None:
    from bianca import besuchsgrund

    tenant = sit.get("tenant") or {}
    muster = besuchsgrund.konzept_muster(auftrag)
    vm = None
    if muster:
        vm = besuchsgrund.motiv_suchen(tenant, muster, katalog=katalog, calendar_id=calendar_id)
    if not vm:
        vm = besuchsgrund.katalog_treffer(auftrag, katalog=katalog, calendar_id=calendar_id)
    return vm


def _katalog(sit: dict, warte_s: float = 4.0) -> list[dict]:
    kat = sit.get("motivKatalog")
    if isinstance(kat, list) and kat:
        return motive.katalog(sit)
    motive.anstossen(sit)
    ende = time.monotonic() + warte_s
    while time.monotonic() < ende:
        kat = sit.get("motivKatalog")
        if isinstance(kat, list) and kat:
            return motive.katalog(sit)
        if not sit.get("motivKatalogLauf"):
            break
        time.sleep(0.1)
    return motive.katalog(sit)


# --- Vorbereitung ----------------------------------------------------------

def _arzt(sit: dict) -> dict | None:
    from bianca import arzt as arzt_mod
    from bianca import gehirn

    tenant = sit.get("tenant") or {}
    for quelle in (_s(sit.get("auftrag")), _s(tenant.get("behandler"))):
        if not quelle:
            continue
        d = arzt_mod.deute(quelle, tenant)
        if d and d.get("typ") == "genannt" and _s(d.get("calendarId")):
            return {"typ": "genannt", "calendarId": _s(d["calendarId"]),
                    "calendarName": _s(d.get("calendarName"))}
    return gehirn.arzt_default(tenant)


def _gewaehlt(sit: dict) -> str:
    uid = _s(sit.get("echtUuid"))
    if uid:
        try:
            from lisa import dock_anruf

            st = dock_anruf.status(uid) or {}
            if _s(st.get("to")):
                return _s(st.get("to"))
        except Exception:
            pass
    return _s(sit.get("gewaehlteNummer"))


def bereit(sit: dict) -> bool:
    from lisa import identitaet

    pat = sit.get("patient") if isinstance(sit.get("patient"), dict) else {}
    return (
        aktiv(sit)
        and _s(sit.get("idCheck")) == identitaet.FERTIG
        and _s(sit.get("idErgebnis")) in {"bestaetigt", "dritter"}
        and bool(_s(pat.get("id")))
    )


def vorbereiten(sit: dict) -> bool:
    """Biancas Sammler aus Akte + Auftrag füllen. True = Buchungsfluss steht."""
    from bianca import gehirn

    if sit.get("lisaTerminBereit"):
        return True
    pat = sit.get("patient") if isinstance(sit.get("patient"), dict) else {}
    auftrag = _s(sit.get("auftrag"))
    s = gehirn.sammler(sit)
    vor = _s(pat.get("firstName"))
    nach = _s(pat.get("lastName"))
    if not (vor or nach):
        teile = _s(pat.get("name")).split()
        vor, nach = (" ".join(teile[:-1]), teile[-1]) if len(teile) >= 2 else ("", " ".join(teile))
    s.update({
        "modus": "buchen", "phase": "", "frage": "",
        "anruferCheck": "ja", "fuerWenCheck": "ja", "warSchonMal": True,
        "vorname": vor, "nachname": nach, "buchstabiert": True, "bekannt": True,
        "vornameQuelle": "check", "vornameCheck": "ja",
        "patientId": _s(pat.get("id")),
        "pzr": "nein", "rueckblick": "fertig", "bleaching": "nein",
        "versicherungOk": True, "arztNotiz": "", "arztNotizFrage": "nein",
    })
    g = _s(pat.get("gender")).lower()
    if g in {"m", "male", "mann", "herr"}:
        s["geschlecht"], s["geschlechtQuelle"] = "m", "akte"
    elif g in {"f", "w", "female", "frau"}:
        s["geschlecht"], s["geschlechtQuelle"] = "f", "akte"

    arzt = _arzt(sit)
    if arzt:
        s["arzt"] = arzt
        s["arztCheck"] = "ja"
    cid = _s((arzt or {}).get("calendarId"))

    kat = _katalog(sit)
    vm = motiv_aus_auftrag(auftrag, kat, cid) if kat else None
    quelle = "auftrag"
    if not vm and kat:
        vm = _motiv_rueckfall(sit, auftrag, kat, cid)
        quelle = "konzept"
    if vm:
        s["motivId"] = _s(vm.get("id"))
        s["motivName"] = _s(vm.get("name"))
        s["motivFest"] = True
        s["grund"] = motive.sprechname_kurz(vm) or s["motivName"]
        s["grundWortlaut"] = s["grund"]
    else:
        quelle = "kontrolle"
        gehirn.grund_als_kontrolle(sit, "Kontrolle")
    w = parse_slot_wish(auftrag)
    if w and w.get("date") and _AB_DATUM_RE.search(auftrag):
        # Anruf c51a20cb: „ab dem 3.11.“ ist frühestens, kein fester Tag —
        # als Datum schlug es „Ich kann nur freitags“ dreimal.
        w["von"], w["date"] = w["date"], None
    if w:
        s["wunsch"] = w
        s["wunschText"] = auftrag[:80]

    nr = telefon.mit_fuehrender_null(_gewaehlt(sit))
    if nr and telefon.ist_handy(nr):
        s["telefon"] = nr
        s["telefonOk"] = True
        s["telefonBekannt"] = nr
        s["kontaktTelefon"] = nr
        akte = telefon.mit_fuehrender_null(_s(pat.get("phone")))
        if akte and akte == nr:
            s["aktePhone"] = nr

    # Buchungskontext frisch: die Startsitzung trug Kontroll-Slots und den
    # naechsten Bestandstermin (slotIso/appointmentId) — nie damit buchen.
    alt = sit.get("booking") if isinstance(sit.get("booking"), dict) else {}
    sit["booking"] = {
        k: alt.get(k) for k in ("patientId", "patientName", "firstName", "lastName", "phone")
        if alt.get(k)
    }
    sit["booking"]["arztAuftrag"] = True
    # Anruf 2c42c37c: ohne Bindung lehnt book_slot die Akten-ID ab („Name und
    # patientId widersprechen sich“) — flow._ctx_bauen bindet nur eine NEUE ID,
    # die Startsitzung trug aber schon dieselbe.
    from kern import patients
    patients.patient_id_bindung_setzen(sit["booking"], s.get("patientId"), vor, nach)
    sit["offered"] = []
    sit["slotVorrat"] = []
    sit.pop("vorratFuer", None)
    sit["arztAuftrag"] = True
    sit["lisaTerminBereit"] = True
    spur.merken(sit, "lisa-buchung",
                f"motiv={s.get('motivName') or '-'} quelle={quelle} "
                f"kalender={(arzt or {}).get('calendarName') or '-'} "
                f"wunsch={'ja' if w else 'nein'} handy={'ja' if s.get('telefonOk') else 'nein'}")
    print(f"lisa-buchung vorbereitet session={sit.get('id')} motiv={s.get('motivName')!r} "
          f"quelle={quelle}", flush=True)
    return True


def _frage_merken(sit: dict, text: str) -> None:
    frage = stille.nur_fragesaetze(text)
    if frage:
        sit["lisaFlussFrage"] = frage


def _zeitwunsch(text: str) -> bool:
    w = parse_slot_wish(text) or {}
    return bool(any(w.get(k) for k in ("weekday", "weekdays", "date", "hour", "hourMin",
                                       "hourMax", "tage", "von", "bis"))
                or (w.get("minDaysAhead") or 0) > 0)


def zug(sit: dict, text: str, melde=None) -> dict | None:
    """Ein Patientensatz im Terminauftrag — None = das Modell spricht."""
    from bianca import flow, gehirn

    if not bereit(sit) or sit.get("lisaTerminAus"):
        return None
    t = tag_ordinal(_s(text))
    if not sit.get("lisaTerminBereit"):
        # „Nee, ich kann nur donnerstags“ lehnt den Tag ab, nicht den Termin.
        if _KEIN_INTERESSE_RE.search(t) or (gehirn.ist_nein(t) and not _zeitwunsch(t)):
            sit["lisaTerminAus"] = True
            spur.merken(sit, "lisa-buchung", "kein-interesse")
            return None
        vorbereiten(sit)
        s = gehirn.sammler(sit)
        w = parse_slot_wish(t)
        if w:
            # Wunsch des Patienten ergänzt den Tag aus dem Auftrag
            # („vormittags“ zum freigewordenen 4.11.), statt ihn zu ersetzen.
            s["wunsch"] = gehirn._wunsch_mischen(s.get("wunsch") or None, w)
            s["wunschText"] = t[:80]
        out = flow._angebot(sit, melde)
    else:
        out = flow.zug(sit, t, melde)
    if not isinstance(out, dict):
        return None
    if _s(out.get("text")):
        _frage_merken(sit, out["text"])
    return out


_SATZ_RE = re.compile(r"(?<=[.!?])\s+")


def nach_modell(sit: dict, text: str, nutzertext: str = "") -> str:
    """Freies Modell im Terminauftrag: keine eigene Zusage, keine erfundene
    Uhrzeit, kein unbelegtes „eingetragen“ — danach die offene Flussfrage."""
    from kern import fakten_wache, zuege

    behalten: list[str] = []
    for satz in _SATZ_RE.split(_s(text)):
        satz = _s(satz)
        if not satz:
            continue
        grund = ""
        if zuege.zusage_ohne_werkzeug(satz):
            grund = "zusage"
        else:
            try:
                grund = fakten_wache.unbelegte_behauptung(sit, satz, nutzertext=nutzertext) or ""
            except Exception:
                grund = ""
        if grund:
            spur.merken(sit, "lisa-buchung", f"modell-gestrichen:{grund}")
            continue
        behalten.append(satz)
    neu = " ".join(behalten)
    frage = _s(sit.get("lisaFlussFrage"))
    if frage and "?" not in neu:
        neu = f"{neu} {frage}".strip()
    return neu
