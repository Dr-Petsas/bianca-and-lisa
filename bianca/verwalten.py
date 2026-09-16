"""Bestandstermine am Telefon: ansagen, absagen, verschieben — deterministisch.

Gleiche Bauart wie flow.py: kein LLM auf dem Pflichtpfad. Die Termine kommen
in EINEM warmen Aufruf (agentFindPatientAppointments: Patient + kommende
Termine inkl. Behandler und Kalender-ID), der Storno trifft punktgenau die
Termin-ID (agentCancelAppointmentById), das Verschieben laeuft ueber
postpone mit Termin-ID. Liefert None, wenn der Satz nichts mit dem Anliegen
zu tun hat — dann uebernimmt das LLM (Status steht im Prompt).

Prozedur Absagen/Verschieben (W-NACHNAME 31.08.2026, phone_agent-Vorbild —
loest die Wann-zuerst-Sammelei von W-SAMMELN ab; Chef: "der soll nur nach
dem nachnamen fragen und dann erstmal sehen ob er einen termin findet"):
1. NUR den NACHNAMEN erfragen — die Cloud Function
   agentFindPatientAppointments braucht nichts weiter (lastName reicht,
   Anrufer-Telefon geht als Bonus mit). Hinweise aus dem Einstiegssatz
   ("Termin am Donnerstag absagen", Behandler-Name) werden weiter geerntet
   und filtern die Treffer — es wird nur nichts mehr VORAB abgefragt.
2. Meldet die CF MEHRERE Patienten mit gleichem Nachnamen (409/ambiguous),
   grenzt der VORNAME ab: einmal nachfragen, mit firstName erneut suchen.
3. Treffer BESTAETIGEN mit Anrede ("… Frau Mueller, ja?") — bei Ja loeschen
   bzw. die Verschiebe-Strecke starten.
4. Mehrere TERMINE des Patienten -> hilfsweise die BEHANDLUNG erfragen,
   danach die Auswahl-Liste.
5. Nicht gefunden -> ehrlich sagen + ECHTE Notiz (praxis_notizen.jsonl,
   Dock-Anzeige): "keine Sorge, ich schreibe eine Notiz, und die wird
   Doktor XY vorgelegt."
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Callable

from bianca import gehirn, hintergrund, telefon
from kern import agentprofil
from kern import calendar as kal
from kern import gespraech, motive, notes
from kern import patients
from kern.config import DATA_DIR
from kern.patients import arzt_sprechname
from kern.sitzung import merke_tool
from kern.slots import (
    WEEKDAYS,
    _weekday_of,
    parse_slot_wish,
    pick_slots,
    slot_wunsch_hart,
    spoken_offer,
    spoken_slot,
)

Melde = Callable[[str], None] | None

_MODI = {"absagen", "verschieben", "auskunft"}

# "Keine Ahnung, weiss ich nicht mehr" auf die Wann-/Behandlungs-Frage.
_UNKLAR_RE = re.compile(
    r"keine\s+ahnung|wei(?:ß|ss)\s+(?:ich\s+)?(?:es\s+|das\s+)?(?:auch\s+|leider\s+|gerade\s+)*"
    r"(?:nicht|nimmer)|nicht\s+mehr\s+genau|nicht\s+(?:so\s+)?sicher|vergessen|"
    r"keinen?\s+(?:schimmer|plan)|m(?:ü|ue)sste\s+ich\s+nach(?:schauen|sehen|gucken)",
    re.I,
)

_MONATE_RE = (
    r"januar|februar|märz|maerz|april|mai|juni|juli|august|"
    r"september|oktober|november|dezember"
)
# Verschieben-Einstieg: "den Termin AM Dienstag (auf Freitag) verschieben" —
# das am/vom-Stueck meint den BESTANDSTERMIN, ein auf/zu-Stueck den Wunsch.
# Der Punkt in "am 21. Oktober" ist KEIN Satzende. Die alte Klasse [.!?;,]
# kappte dort nach "21.", ließ "Oktober" im Zieltext stehen und suchte deshalb
# wieder ab Oktober statt wie verlangt Mitte November (Blessing/Bächle live).
_ALT_REF_RE = re.compile(
    rf"termin\s+(?:vom|am)\s+(.{{2,45}}?)"
    rf"(?=\s+(?:auf|zum|zur|zu)\s|[!?;,]|\.(?!\s*(?:{_MONATE_RE})\b)|$)",
    re.I,
)

# "Früher"/"später" beim Verschieben ist RELATIV zum Bestandstermin — live
# 27.08.2026: "ein bisschen früher, so zwölf Uhr fünfzehn" wurde als
# "vormittags" gedeutet, der freie 12:15-Platz am SELBEN Tag nie angeboten.
_FRUEHER_RE = re.compile(
    r"\bfrüher\b|\bfrueher\b|nach\s+vorne?\b|vorziehen|vorverlegen|vor\s*verlegen",
    re.I,
)
_SPAETER_RE = re.compile(
    r"\bspäter\b|\bspaeter\b|nach\s+hinten\b|weiter\s+hinten|hinten\s*raus",
    re.I,
)
_TAG_OHNE_MONAT_RE = re.compile(
    rf"\b(?:am|dem|den|der)\s+(\d{{1,2}})\."
    rf"(?!\s*\d)(?!\s*(?:{_MONATE_RE})\b)",
    re.I,
)


def _richtung_merken(sit: dict, t: str) -> None:
    """Verschiebe-Richtung ("früher"/"später") aus dem Anrufer-Satz ziehen."""
    s = gehirn.sammler(sit)
    if s["modus"] != "verschieben":
        return
    if _FRUEHER_RE.search(t):
        sit["verschiebRichtung"] = "frueher"
    elif _SPAETER_RE.search(t):
        sit["verschiebRichtung"] = "spaeter"
    if not sit.get("verschiebRichtung"):
        return
    # Nennt der Anrufer einen ANDEREN Tag/eine andere Woche, gilt die
    # Richtung nicht mehr — dann zaehlt der explizite Wunsch.
    termin_iso = _s(_gewaehlt(sit).get("iso"))
    w = s["wunsch"] or {}
    if w.get("date") and len(termin_iso) >= 10 and w["date"] != termin_iso[:10]:
        sit["verschiebRichtung"] = ""
    elif w.get("weekday") is not None or w.get("minDaysAhead"):
        sit["verschiebRichtung"] = ""


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _ctx(sit: dict) -> dict:
    """Minimaler Kontext fuer die Namens-Suche und die Schreib-Aufrufe."""
    s = gehirn.sammler(sit)
    ctx = sit.setdefault("booking", {})
    # Geraeumte Felder auch im Kontext raeumen (W-NAMESKORREKTUR): nach der
    # Namens-Korrektur darf kein verworfener Vorname/Kartei-Treffer aus dem
    # booking-Dict weiter in die Suche kleben.
    if s["vorname"]:
        ctx["firstName"] = s["vorname"]
    else:
        ctx.pop("firstName", None)
    if s["nachname"]:
        ctx["lastName"] = s["nachname"]
    else:
        ctx.pop("lastName", None)
    name = f"{s['vorname']} {s['nachname']}".strip()
    if name:
        ctx["patientName"] = name
    else:
        ctx.pop("patientName", None)
    if s["patientId"]:
        if _s(ctx.get("patientId")) != _s(s["patientId"]):
            patients.patient_id_bindung_setzen(
                ctx, s["patientId"], s["vorname"], s["nachname"])
        ctx["patientId"] = s["patientId"]
    else:
        ctx.pop("patientId", None)
        patients.patient_id_bindung_setzen(ctx, "", "", "")
    tel = s["telefon"] or s["aktePhone"]
    if tel:
        ctx["phone"] = tel
    return ctx


def _gewaehlt(sit: dict) -> dict:
    aid = _s(sit.get("verwaltenTermin"))
    for a in sit.get("gefunden") or []:
        if _s(a.get("id")) == aid:
            return a
    return {}


def _verschieb_datum_auf_bestand_beziehen(sit: dict, termin: dict) -> None:
    """Monatlosen Zieltag relativ zum Bestandstermin aufloesen.

    Bei „Termin am 21. Oktober auf Freitag, den 23.“ ist der 23. Oktober
    gemeint, nicht der naechste 23. ab heute. Der allgemeine Wunschparser
    kennt den Bestandstermin nicht und waehlt sonst im September.
    """
    s = gehirn.sammler(sit)
    text = _s(s.get("wunschText"))
    if not text:
        return
    m = _TAG_OHNE_MONAT_RE.search(text)
    iso = _s(termin.get("iso"))
    if not m or len(iso) < 10 or not isinstance(s.get("wunsch"), dict):
        return
    try:
        basis = datetime.fromisoformat(iso[:10]).date()
    except ValueError:
        return
    tag = int(m.group(1))
    wd = next((idx for idx, cre in WEEKDAYS if cre.search(text.lower())), None)
    kandidaten = []
    for delta in (-1, 0, 1):
        monat0 = basis.month - 1 + delta
        jahr = basis.year + monat0 // 12
        monat = monat0 % 12 + 1
        try:
            d = basis.replace(year=jahr, month=monat, day=tag)
        except ValueError:
            continue
        if d < datetime.now(gehirn.TZ).date():
            continue
        if wd is not None and _weekday_of(d.isoformat()) != wd:
            continue
        kandidaten.append(d)
    if not kandidaten:
        return
    if _FRUEHER_RE.search(text):
        gerichtet = [d for d in kandidaten if d < basis]
    elif _SPAETER_RE.search(text):
        gerichtet = [d for d in kandidaten if d > basis]
    else:
        gerichtet = []
    ziel = min(gerichtet or kandidaten, key=lambda d: abs((d - basis).days))
    w = dict(s["wunsch"])
    w["date"] = ziel.isoformat()
    w["tage"] = None
    w["weekday"] = None
    s["wunsch"] = w


def _finden(sit: dict, melde: Melde) -> dict:
    """Kommende Termine zum Namen holen — einmal pro Name, dann aus dem Cache."""
    s = gehirn.sammler(sit)
    key = f"{s['vorname']}|{s['nachname']}".lower()
    if sit.get("gefundenKey") == key and isinstance(sit.get("gefunden"), list):
        return {"ok": True, "appointments": sit["gefunden"]}
    if melde:
        melde("list_appointments")
    res = kal.find_patient_appointments(sit["tenant"], _ctx(sit))
    merke_tool(sit, "agentFindPatientAppointments", res)
    if res.get("ok") and not res.get("notFound") and not res.get("mehrdeutig"):
        pat = res.get("patient") or {}
        if _s(pat.get("id")):
            s["patientId"] = _s(pat.get("id"))
            s["bekannt"] = True
            s["warSchonMal"] = True
            # Kartei schlaegt Verhoer: hat die Suche den gespeicherten
            # Vornamen verworfen (Treffer kam erst ohne firstName), gilt
            # der Vorname aus der Akte (W-NAMESKORREKTUR).
            if _s(pat.get("firstName")) and (not s["vorname"] or res.get("vornameVerworfen")):
                s["vorname"] = _s(pat.get("firstName"))
                s["vornameQuelle"] = "akte"      # W-HIRN-GATE: einmal bestaetigen
                s["vornameCheck"] = ""
        sit["gefunden"] = res.get("appointments") or []
        sit["gefundenKey"] = f"{s['vorname']}|{s['nachname']}".lower()
    return res


def _arzt_uebernehmen(sit: dict, termin: dict, *, fest: bool = False) -> None:
    """Behandler des Bestandstermins als Vorgabe fuer eine Folge-Buchung.

    fest=True: der gefundene Termin gewinnt — Slots nur bei DIESEM Arzt
    (Chef 08.09.2026), ausser der Anrufer hat ausdrücklich einen anderen
    genannt (typ wahl/genannt mit anderer calendarId)."""
    if not termin.get("calendarId"):
        return
    s = gehirn.sammler(sit)
    alt = s.get("arzt") or {}
    if (not fest and alt.get("calendarId")):
        return
    if (fest and alt.get("typ") in {"wahl", "genannt"}
            and alt.get("calendarId")
            and alt["calendarId"] != termin.get("calendarId")):
        return
    s["arzt"] = {
        "typ": "letzter",
        "calendarId": _s(termin.get("calendarId")),
        "calendarName": _s(termin.get("doctorName")),
    }


def _liste_sprechbar(termine: list[dict]) -> str:
    teile = [_s(a.get("spoken")) for a in termine[:3] if _s(a.get("spoken"))]
    if len(teile) > 1:
        return "; ".join(teile[:-1]) + "; und " + teile[-1]
    return teile[0] if teile else ""


# --- Hinweis-Sammlung (Chef 29.08.2026: erst Daten, dann suchen) -----------


def _verw_reset(sit: dict) -> None:
    """Sammel-Stand raeumen (neues Anliegen bzw. Anliegen erledigt)."""
    sit.pop("verwNotFound", None)
    sit.pop("verwKorrektur", None)        # W-NAMESKORREKTUR: frische Chance
    sit.pop("verwKorrekturVorname", None)
    sit.pop("verwWann", None)         # Altlast aus W-SAMMELN-Sitzungen
    sit.pop("verwArztGefragt", None)  # (Wann-/Behandler-Vorabfrage ist raus)
    sit["verwHinweis"] = {}
    sit["verwHinweisText"] = ""
    sit["verwBehandlungGefragt"] = False
    sit["verwBehandlung"] = ""
    sit["verwAktiv"] = False
    sit.pop("verwWunschAlt", None)
    sit.pop("verwWunschTextAlt", None)


def _hinweis_hat(w: dict | None) -> bool:
    """Traegt der Wunsch-Parse eine brauchbare Zeitangabe?"""
    w = w or {}
    return bool(
        w.get("date") or w.get("weekday") is not None or w.get("hour") is not None
        or w.get("hourMin") is not None or w.get("minDaysAhead")
        or w.get("von") or w.get("bis")  # W-SUCHFENSTER: "mein Termin im Oktober"
    )


def _hinweis_merken(sit: dict, text: str, *, relativ: bool = False) -> bool:
    """Zeitangabe zum BESTANDSTERMIN aus dem Satz ziehen und merken.
    relativ=True nimmt auch heute/morgen/uebermorgen mit (Auskunft: "Habe
    ich morgen einen Termin?")."""
    w = parse_slot_wish(text)
    if relativ and not _hinweis_hat(w):
        w = gehirn._wunsch_deuten(text) or {}
    if not _hinweis_hat(w):
        return False
    sit["verwHinweis"] = w
    sit["verwHinweisText"] = _s(text)
    return True


def _hinweis_passt(a: dict, w: dict) -> bool:
    iso = _s(a.get("iso"))
    if len(iso) < 16:
        return True
    if w.get("date") and iso[:10] != w["date"]:
        return False
    # W-SUCHFENSTER: Zeitraum ("im Oktober" = von/bis, "ab November" = nur von).
    if w.get("von") and iso[:10] < str(w["von"])[:10]:
        return False
    if w.get("bis") and iso[:10] > str(w["bis"])[:10]:
        return False
    if w.get("weekday") is not None and _weekday_of(iso[:10]) != w["weekday"]:
        return False
    if w.get("hour") is not None:
        minuten = int(iso[11:13]) * 60 + int(iso[14:16])
        if abs(minuten - int(w["hour"]) * 60) > 60:
            return False
    elif w.get("hourMin") is not None:
        if not (int(w["hourMin"]) <= int(iso[11:13]) < int(w.get("hourMax") or 24)):
            return False
    if w.get("minDaysAhead"):
        # "Naechste Woche" = ab Mitternacht in N Tagen (wie pick_slots).
        ziel = datetime.now(gehirn.TZ) + timedelta(days=int(w["minDaysAhead"]))
        if iso[:10] < ziel.strftime("%Y-%m-%d"):
            return False
    return True


_BEHANDLUNG_STOP = {"einen", "eine", "einem", "termin", "glaube", "irgendwas",
                    "sowas", "gewesen", "waren", "hatte", "haben", "wegen"}


def _behandlung_passt(a: dict, text: str) -> bool:
    """Hilfsweise Behandlungs-Angabe gegen den Besuchsgrund des Termins."""
    mn = _s(a.get("motivName")).lower()
    if not text or not mn:
        return True
    toks = [t for t in re.sub(r"[^\wäöüß]+", " ", text).split()
            if len(t) >= 4 and t not in _BEHANDLUNG_STOP]
    if not toks:
        return True
    woerter = mn.split()
    return any(t in mn or any(w.startswith(t[:5]) for w in woerter) for t in toks)


def _filtern(sit: dict, termine: list[dict]) -> list[dict]:
    """Gefundene Termine mit den eingesammelten Hinweisen eingrenzen."""
    s = gehirn.sammler(sit)
    out = list(termine)
    # Frisch im selben Anruf gebuchter Termin: "den bitte wieder absagen".
    aid = _s((sit.get("booking") or {}).get("appointmentId"))
    if aid:
        direkt = [a for a in out if _s(a.get("id")) == aid]
        if direkt:
            return direkt
    w = sit.get("verwHinweis") or {}
    if _hinweis_hat(w):
        out = [a for a in out if _hinweis_passt(a, w)]
    cal = _s((s["arzt"] or {}).get("calendarId"))
    if cal:
        out = [a for a in out if _s(a.get("calendarId")) == cal]
    # Behandlung: die gemappte Motiv-Id zaehlt nur, wenn sie WIRKLICH auf
    # einen der Termine passt (fremder Katalog-Treffer sortiert sonst alles
    # aus); sonst der Wortlaut-Abgleich gegen den Besuchsgrund.
    mid = _s(s.get("motivId"))
    if mid and any(_s(a.get("motivId")) == mid for a in out):
        out = [a for a in out if _s(a.get("motivId")) == mid]
    elif sit.get("verwBehandlung"):
        out = [a for a in out if _behandlung_passt(a, _s(sit.get("verwBehandlung")).lower())]
    return out


def _korrektur_frage(sit: dict) -> dict:
    """W-NAMESKORREKTUR (Chef 31.08.2026, Zannes-Anruf 10:33: "der gibt zu
    schnell auf"): beim ERSTEN 'Patient nicht gefunden' nicht gleich die
    Notiz schreiben — meist hat STT den Nachnamen verhoert ("Sannes Czannis"
    statt Tzannes). Der Anrufer bekommt EINE Chance, den Nachnamen zu
    korrigieren oder zu buchstabieren; erst der zweite Fehlschlag geht den
    ehrlichen Notiz-Weg."""
    s = gehirn.sammler(sit)
    sit["verwKorrektur"] = True
    # Schnappschuss: nennt die Korrektur nur den Nachnamen, fliegt ein
    # Vorname aus derselben (verhoerten) Aeusserung mit raus.
    sit["verwKorrekturVorname"] = s["vorname"]
    wer = f"{s['vorname']} {s['nachname']}".strip() or "diesem Namen"
    s["frage"] = "nachname"
    return {"text": (
        f"Unter {wer} finde ich gerade keinen Termin. "
        "Vielleicht habe ich den Nachnamen falsch verstanden — "
        "sagen oder buchstabieren Sie ihn mir bitte noch einmal?"
    )}


def _vorname_frage(sit: dict) -> dict:
    """Die CF meldet MEHRERE Patienten mit gleichem Nachnamen (409/ambiguous):
    der Vorname grenzt ab — wie im alten phone_agent (W-NACHNAME 31.08.2026)."""
    s = gehirn.sammler(sit)
    if s["vorname"]:
        # Auch MIT Vornamen noch mehrdeutig: nicht raten — ehrlich + Notiz.
        return _kein_termin(sit, s["modus"])
    s["frage"] = "vorname"
    wer = f"dem Nachnamen {s['nachname']}" if s["nachname"] else "diesem Nachnamen"
    return {"text": (
        f"Da haben wir mehrere Patienten mit {wer}. "
        "Wie ist denn Ihr Vorname?"
    )}


def _behandlung_beispiele(sit: dict, treffer: list | None = None) -> list[str]:
    """Beispiele NUR aus den gefundenen Terminen bzw. dem Katalog dieser Praxis."""
    namen: list[str] = []
    gesehen: set[str] = set()
    for a in treffer or []:
        name = gehirn.grund_am_telefon(a.get("motivName") or "")
        key = name.casefold()
        if not name or key in gesehen:
            continue
        gesehen.add(key)
        namen.append(name)
        if len(namen) >= 2:
            return namen
    for name in motive.sprech_beispiele(sit, n=2):
        key = name.casefold()
        if key in gesehen:
            continue
        gesehen.add(key)
        namen.append(name)
        if len(namen) >= 2:
            break
    return namen


def _behandlung_frage(sit: dict, treffer: list | None = None) -> dict:
    s = gehirn.sammler(sit)
    sit["verwBehandlungGefragt"] = True
    s["frage"] = "behandlung"
    beispiele = _behandlung_beispiele(sit, treffer)
    if len(beispiele) >= 2:
        extra = f" — zum Beispiel {beispiele[0]} oder {beispiele[1]}?"
    elif beispiele:
        extra = f" — zum Beispiel {beispiele[0]}?"
    else:
        extra = "?"
    return {"text": (
        f"Da finde ich mehrere. Für welche Behandlung war der Termin denn{extra}"
    )}


def _kein_termin(sit: dict, modus: str) -> dict:
    if modus in {"absagen", "verschieben"}:
        return _nicht_gefunden(sit)
    s = gehirn.sammler(sit)
    wer = f"{s['vorname']} {s['nachname']}".strip()
    s["phase"] = "fertig"
    s["frage"] = "neubuchung"
    return {"text": _s(
        f"Ich sehe unter {wer or 'Ihrem Namen'} aktuell keinen kommenden Termin. "
        "Soll ich Ihnen direkt einen neuen Termin anbieten?"
    )}


def rueckruf_nummer(sit: dict) -> str:
    """Nummer, unter der die Praxis den Anrufer erreicht — oder "".

    W-RUECKRUF-NUMMER (14.09.2026, Anrufe da746a65/5aa87268): "die Praxis
    meldet sich" ist ein leeres Versprechen, wenn die Notiz keine Nummer
    traegt. Quellen in dieser Reihenfolge — alles, was die Sitzung SICHER
    weiss: bestaetigte Nummer aus dem Gespraech, Akte, Kontakt-Nummer
    (Dritttermin: der Anrufer), Anrufer-ID aus der Leitung. NIE eine bloss
    gehoerte, unbestaetigte Nummer (telefonOffen) — die wird erst Ziffer
    fuer Ziffer rueckbestaetigt.
    """
    s = gehirn.sammler(sit)
    for roh in (s["telefon"], s["aktePhone"], _s(s.get("kontaktTelefon")),
                gehirn._anrufer_nummer(sit)):
        if not _s(roh):
            continue
        d = telefon.mit_fuehrender_null(roh)
        if telefon.plausibel(d):
            return d
    return ""


def rueckruf_nummer_fehlt(sit: dict) -> bool:
    """True = die Praxis koennte nicht zurueckrufen (keine Nummer bekannt)."""
    return not rueckruf_nummer(sit)


def rueckruf_nummer_nachtragen(sit: dict) -> str:
    """Die eben rueckbestaetigte Nummer in Notiz (zweite JSONL-Zeile) + Dock
    nachtragen. Liefert die Nummer oder "" (nichts zum Nachtragen)."""
    nummer = rueckruf_nummer(sit)
    if not nummer:
        return ""
    s = gehirn.sammler(sit)
    name = f"{s['vorname']} {s['nachname']}".strip() or "unbekannt"
    if not sit.get("testNoWrite"):
        eintrag = {
            "zeit": datetime.now(gehirn.TZ).isoformat(timespec="seconds"),
            "stimme": notes.stimme_von(sit),
            "anliegen": "rueckrufnummer",
            "name": name,
            "telefon": nummer,
            "status": "Rueckrufnummer nachgetragen",
        }
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with (DATA_DIR / "praxis_notizen.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
        except OSError:
            pass
    notiz = _s(sit.get("praxisNotiz"))
    if notiz and "Tel:" not in notiz:
        sit["praxisNotiz"] = _s(f"{notiz} Tel: {nummer}.")
    merke_tool(sit, "praxis_notiz", {"ok": True, "notiert": True,
                                     "notiz": _s(sit.get("praxisNotiz")), "telefon": nummer})
    return nummer


def _notiz_schreiben(sit: dict, *, anliegen: str = "", status: str = "",
                     dock_text: str = "", was: str = "") -> None:
    """ECHTE Notiz statt leerem Versprechen: JSONL fuer die Praxis + Dock."""
    if sit.get("testNoWrite"):
        sit["testNotizUnterdrueckt"] = True
        return
    s = gehirn.sammler(sit)
    name = f"{s['vorname']} {s['nachname']}".strip() or "unbekannt"
    eintrag = {
        "zeit": datetime.now(gehirn.TZ).isoformat(timespec="seconds"),
        "stimme": notes.stimme_von(sit),
        "anliegen": anliegen or s["modus"],
        "name": name,
        # W-RUECKRUF-NUMMER: Kontakt-/Anrufer-Nummer als Rueckfall — die
        # Leitung kennt den Anrufer oft, auch wenn im Gespraech keine Nummer fiel.
        "telefon": s["telefon"] or s["aktePhone"] or rueckruf_nummer(sit),
        "behandler": _s((s["arzt"] or {}).get("calendarName")),
        "wann": _s(sit.get("verwHinweisText")) or _s(s.get("wunschText")),
        "behandlung": _s(sit.get("verwBehandlung")) or _s(s.get("grundWortlaut") or s.get("grund")),
        "status": status or "Termin nicht gefunden — bitte pruefen und zurueckrufen",
    }
    if _s(was):
        # W-RECHNUNG: WORUM es beim Rueckruf geht, gehoert in die Zeile fuer
        # die Praxis — "Rueckruf erbeten" allein sagt nicht, dass es eine
        # Rechnungsreklamation ist.
        eintrag["was"] = _s(was)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with (DATA_DIR / "praxis_notizen.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
    except OSError:
        pass
    hinweise = "; ".join(x for x in (
        f"wann: {eintrag['wann']}" if eintrag["wann"] else "",
        f"Behandler: {eintrag['behandler']}" if eintrag["behandler"] else "",
        f"Behandlung: {eintrag['behandlung']}" if eintrag["behandlung"] else "",
        f"Tel: {eintrag['telefon']}" if eintrag["telefon"] else "",
    ) if x)
    if dock_text and eintrag["telefon"] and "Tel:" not in dock_text:
        # W-RUECKRUF-NUMMER: die Praxis sieht im Dock/Report sofort, WO sie
        # anrufen kann — nicht nur in der JSONL-Zeile.
        dock_text = _s(dock_text) + f" Tel: {eintrag['telefon']}."
    sit["praxisNotiz"] = _s(dock_text or (
        f"{name} wollte einen Termin {s['modus']} — im Kalender nicht gefunden"
        + (f" ({hinweise})" if hinweise else "") + ". Bitte pruefen und zurueckrufen."
    ))
    if dock_text and hinweise:
        sit["praxisNotiz"] = _s(f"{dock_text} ({hinweise})")
    merke_tool(sit, "praxis_notiz", {"ok": True, "notiert": True, "notiz": sit["praxisNotiz"]})


def rueckruf_notiz(sit: dict) -> None:
    """Kein freier Slot im Buchungs-Angebot: 'die Praxis meldet sich' MUSS
    eine echte Spur hinterlassen (Batch s09 29.08.2026 — leeres Versprechen,
    frage klebte auf slotwahl)."""
    s = gehirn.sammler(sit)
    name = f"{s['vorname']} {s['nachname']}".strip() or "unbekannt"
    _notiz_schreiben(
        sit, anliegen="neubuchung",
        status="Kein freier Termin im Angebot — bitte zurueckrufen",
        dock_text=f"{name} wollte neu buchen — kein freier Termin im Angebot. Bitte zurueckrufen.",
    )


def buchung_pruefen_notiz(sit: dict, *, slot_iso: str = "") -> None:
    """HTTP-200 ohne belastbaren Read-back wird zum echten Prüf-/Rückrufvorgang."""
    s = gehirn.sammler(sit)
    name = f"{s['vorname']} {s['nachname']}".strip() or "unbekannt"
    wann = spoken_slot(slot_iso) if len(_s(slot_iso)) >= 16 else _s(slot_iso)
    _notiz_schreiben(
        sit,
        anliegen="buchung_pruefen",
        status="Buchungsantwort nicht eindeutig rücklesbar — Termin und SMS prüfen, bitte zurückrufen",
        dock_text=(
            f"{name}: Buchung für {wann or 'den gewünschten Zeitpunkt'} war nach dem "
            "Schreiben nicht eindeutig rücklesbar. Termin und SMS prüfen, bitte zurückrufen."
        ),
    )


def abgeben_notiz(sit: dict, *, was: str = "") -> None:
    """ABGEBEN-Anliegen (W-HIRN 03.09.2026): Rueckruf-/Nachricht-Notiz OHNE
    Termin-Bezug — frueher gab es die Spur nur, wenn zufaellig keine Slots
    frei waren. Jetzt ist 'die Praxis kuemmert sich' eine eigene Loesung."""
    s = gehirn.sammler(sit)
    name = f"{s['vorname']} {s['nachname']}".strip() or "unbekannt"
    anliegen_text = _s(was) or "Rueckruf erbeten"
    _notiz_schreiben(
        sit, anliegen="rueckruf",
        status="Rueckruf erbeten — bitte melden",
        dock_text=f"{name} bittet um Rueckruf: {anliegen_text}.",
        was=anliegen_text,
    )


def _nicht_gefunden(sit: dict) -> dict:
    """Chef 29.08.2026: ehrlich sagen + 'keine Sorge, ich schreibe eine
    Notiz, und die wird dem Behandler XY vorgelegt.'"""
    s = gehirn.sammler(sit)
    wer = f"{s['vorname']} {s['nachname']}".strip() or "Ihrem Namen"
    behandler = arzt_sprechname(
        _s((s["arzt"] or {}).get("calendarName")),
        sit.get("tenant") if isinstance(sit.get("tenant"), dict) else None,
    ) or "dem Praxisteam"
    _notiz_schreiben(sit)
    s["phase"] = "fertig"
    s["frage"] = "neubuchung"
    sit["verwAktiv"] = False
    # Marker fuer einen NEUEN Anlauf: die Suche scheiterte — haeufigste
    # Ursache ist ein verhoerter Name (live 29.08.: "Peter Möbel" statt
    # Müller). Beim Neustart wird der Name dann frisch erfragt.
    sit["verwNotFound"] = True
    return {"text": (
        f"Da bin ich ehrlich: Ich finde unter {wer} gerade keinen passenden Termin. "
        f"Aber keine Sorge — ich schreibe eine Notiz, und die wird {behandler} vorgelegt. "
        "Möchten Sie stattdessen direkt einen neuen Termin vereinbaren?"
    )}


def _absage_frage(sit: dict, termin: dict) -> dict:
    """Treffer bestaetigen MIT Anrede (Chef: '… Herr/Frau XY, ja?')."""
    s = gehirn.sammler(sit)
    sit["verwaltenTermin"] = _s(termin.get("id"))
    s["phase"] = "absage_bestaetigen"
    s["frage"] = "absage_ok"
    wer = "" if s.get("anruferCheck") == "ja" else gehirn.anrede(s)
    zusatz = f", {wer}" if wer else ""
    return {"text": (
        f"Gefunden — {termin.get('spoken')}. "
        f"Soll ich den Termin wirklich absagen{zusatz}?"
    )}


def _absagen(sit: dict, melde: Melde) -> dict:
    if sit.get("testNoWrite"):
        s = gehirn.sammler(sit)
        s["phase"] = "fertig"
        s["frage"] = ""
        return {"text": "Der Testlauf ist beendet; der Termin wurde nicht abgesagt."}
    s = gehirn.sammler(sit)
    termin = _gewaehlt(sit)
    if melde:
        melde("cancel_appointment")
    res = kal.cancel_by_id(sit["tenant"], _ctx(sit), _s(termin.get("id")))
    merke_tool(sit, "cancel_appointment", res)
    if res.get("ok"):
        _arzt_uebernehmen(sit, termin)
        sit["gefundenKey"] = ""  # Bestand hat sich geaendert
        sit["gefunden"] = []
        sit["verwaltenTermin"] = ""
        _verw_reset(sit)
        if _s((sit.get("booking") or {}).get("appointmentId")) == _s(termin.get("id")):
            sit["booking"]["appointmentId"] = ""  # der frisch gebuchte ist weg
        s["phase"] = "fertig"
        s["frage"] = "neubuchung"
        wann = _s(termin.get("spoken")) or "wie besprochen"
        return {
            "text": f"Erledigt — der Termin {wann} ist abgesagt. "
                    "Möchten Sie direkt einen neuen Termin vereinbaren?",
            "book": {"cancelled": True, "spoken": res.get("spoken") or ""},
        }
    s["phase"] = "fertig"
    s["frage"] = ""
    return {"text": res.get("spoken") or "Die Absage hat gerade nicht geklappt. Die Praxis kümmert sich darum."}


def _mehrfach_auswahl(t: str, termine: list[dict]) -> list[dict]:
    """Welche der vorgelesenen Termine meint 'beide/alle/den ersten und den
    zweiten'? Leere Liste = kein Mehrfach-Wunsch."""
    echte = [a for a in termine if _s(a.get("id"))]
    if len(echte) < 2:
        return []
    if _ALLE_RE.search(t):
        return echte
    if _ERSTEN_ZWEITEN_RE.search(t):
        return echte[:2]
    if _BEIDE_RE.search(t):
        # "beide" meint genau zwei — bei mehr als zweien nicht raten.
        return echte if len(echte) == 2 else echte[:2]
    return []


def _mehrfach_absage_start(sit: dict, auswahl: list[dict]) -> dict:
    """EINE gemeinsame Rueckbestaetigung fuer mehrere Termine (nie still nur
    einen absagen)."""
    s = gehirn.sammler(sit)
    sit["mehrfachAbsage"] = [
        {"id": _s(a.get("id")), "spoken": _s(a.get("spoken"))} for a in auswahl
    ]
    s["phase"] = "mehrfach_bestaetigen"
    s["frage"] = "mehrfach_ok"
    liste = _liste_sprechbar(auswahl)
    return {"text": (
        f"Verstanden — ich sage dann diese Termine ab: {liste}. "
        "Soll ich das wirklich für beide tun?"
    )}


def _mehrfach_absagen(sit: dict, melde: Melde) -> dict:
    """Die rueckbestaetigte Warteschlange nacheinander ueber cancel-by-id
    absagen. Teilfehler werden EHRLICH einzeln ausgewiesen — nie 'beide
    abgesagt', wenn nur ein Werkzeug erfolgreich war (W-FAKTEN-WACHE-Geist)."""
    s = gehirn.sammler(sit)
    posten = list(sit.get("mehrfachAbsage") or [])
    if sit.get("testNoWrite"):
        s["phase"] = "fertig"
        s["frage"] = ""
        sit["mehrfachAbsage"] = []
        return {"text": "Der Testlauf ist beendet; es wurde nichts abgesagt."}
    erfolg: list[str] = []
    fehler: list[str] = []
    letzter_termin: dict = {}
    for p in posten:
        aid = _s(p.get("id"))
        if not aid:
            continue
        if melde:
            melde("cancel_appointment")
        res = kal.cancel_by_id(sit["tenant"], _ctx(sit), aid)
        merke_tool(sit, "cancel_appointment", res)
        wann = _s(p.get("spoken")) or "der Termin"
        if res.get("ok"):
            erfolg.append(wann)
            termin = next((a for a in (sit.get("gefunden") or [])
                           if _s(a.get("id")) == aid), {"id": aid, "spoken": wann})
            letzter_termin = termin
            _arzt_uebernehmen(sit, termin)
            if _s((sit.get("booking") or {}).get("appointmentId")) == aid:
                sit["booking"]["appointmentId"] = ""
        else:
            fehler.append(wann)
    sit["mehrfachAbsage"] = []
    sit["gefundenKey"] = ""  # Bestand hat sich geaendert
    sit["gefunden"] = []
    sit["verwaltenTermin"] = ""
    _verw_reset(sit)
    s["phase"] = "fertig"
    s["frage"] = "neubuchung"
    teile: list[str] = []
    if erfolg:
        teile.append("Erledigt — abgesagt sind: " + _fuegen(erfolg) + ".")
    if fehler:
        teile.append(
            "Bei " + _fuegen(fehler) + " hat es gerade nicht geklappt — "
            "die Praxis kümmert sich darum."
        )
    if not teile:
        # Sollte nie passieren (Warteschlange war leer): ehrlich bleiben.
        s["frage"] = ""
        return {"text": "Da ist gerade nichts zum Absagen gewesen. "
                        "Kann ich sonst noch etwas für Sie tun?"}
    teile.append("Möchten Sie direkt einen neuen Termin vereinbaren?")
    book = {"cancelled": bool(erfolg)}
    if letzter_termin:
        book["spoken"] = _s(letzter_termin.get("spoken"))
    return {"text": " ".join(teile), "book": book}


def _fuegen(teile: list[str]) -> str:
    teile = [_s(x) for x in teile if _s(x)]
    if len(teile) > 1:
        return ", ".join(teile[:-1]) + " und " + teile[-1]
    return teile[0] if teile else ""


def _verschieb_wunsch_frage(sit: dict, termin: dict) -> dict:
    """Gefundenen Termin bestaetigen (mit Anrede), dann den Neu-Wunsch holen."""
    s = gehirn.sammler(sit)
    sit["verwaltenTermin"] = _s(termin.get("id"))
    s["phase"] = "verschieb_wunsch"
    s["frage"] = "wunsch"
    wer = "" if s.get("anruferCheck") == "ja" else gehirn.anrede(s)
    zusatz = f", {wer}" if wer else ""
    return {"text": (
        f"Gefunden — es geht um den Termin {termin.get('spoken')}{zusatz}. "
        "Wann passt es Ihnen denn besser: eher vormittags oder nachmittags?"
    )}


def _verschieb_angebot(sit: dict, melde: Melde) -> dict:
    """Freie Zeiten im Kalender des Bestandstermins suchen, Wunsch beachten."""
    s = gehirn.sammler(sit)
    termin = _gewaehlt(sit)
    if not termin:
        return _kein_termin(sit, "verschieben")
    _arzt_uebernehmen(sit, termin, fest=True)
    if melde:
        melde("offer_slots")
    a = s.get("arzt") or {}
    such_ctx = {
        "calendarId": _s(a.get("calendarId")) or _s(termin.get("calendarId")),
        "calendarName": _s(a.get("calendarName")) or _s(termin.get("doctorName")),
        "visitMotiveId": _s(termin.get("motivId")),
        "visitMotiveName": _s(termin.get("motivName")) or "Kontrolluntersuchung",
    }
    found = kal.find_slots_behandler(
        sit["tenant"], such_ctx,
        start_date=gehirn.start_datum(s),
        source="pickadoc-bianca",
        # Beim Verschieben muss der Bestandstermin mit seiner echten Dauer
        # passen. Ein freier 30-Minuten-Kontrollslot beweist nicht, dass ein
        # 60-Minuten-PZR-Termin dorthin verschoben werden kann.
        motiv_fallback=False,
        # W-SUCHFENSTER: "auf einen Donnerstag im November" blaettert vorwaerts.
        wish=s["wunsch"] if isinstance(s.get("wunsch"), dict) else None,
    )
    merke_tool(sit, "getFreeTimeSlots", found)
    if not found.get("ok"):
        s["phase"] = "fertig"
        s["frage"] = ""
        sit["offered"] = []
        return {"text": (
            "Der Terminkalender antwortet gerade nicht. "
            "Die Praxis ruft Sie zum Verschieben kurzfristig zurück."
        )}
    termin_iso = _s(termin.get("iso"))
    gesperrt = {str(x)[:16] for x in (sit.get("slotGesperrt") or []) if x}
    isos = [
        x for x in kal._iso_liste(found.get("slots") or [])
        if x[:16] != termin_iso[:16] and x[:16] not in gesperrt
    ]

    # "Früher"/"später" heisst: am SELBEN Tag vor/nach dem Bestandstermin —
    # erst wenn dort nichts frei ist, kommen andere Tage dran (ehrlich gesagt).
    hinweis = ""
    richtung = _s(sit.get("verschiebRichtung"))
    if richtung and len(termin_iso) >= 16:
        tag = termin_iso[:10]
        if richtung == "frueher":
            eng = [x for x in isos if x[:10] == tag and x[:16] < termin_iso[:16]]
        else:
            eng = [x for x in isos if x[:10] == tag and x[:16] > termin_iso[:16]]
        if eng:
            isos = eng
        else:
            wort = "vorher" if richtung == "frueher" else "später"
            hinweis = f"Am selben Tag ist {wort} leider nichts mehr frei. "

    picked = pick_slots(isos, wish=s["wunsch"])
    if not picked["slots"] and s["wunsch"] and not slot_wunsch_hart(s["wunsch"]):
        # Wunsch (z. B. konkrete Uhrzeit) passt nirgends: naechstliegende
        # Zeiten zeigen statt in der Wunsch-Schleife zu haengen. Ausdrücklich
        # abgelehnte Tage/Uhrzeiten sind dagegen hart und dürfen im
        # Verschiebe-Fallback nie wieder erscheinen.
        picked = pick_slots(isos)
        if picked["slots"]:
            hinweis = hinweis or "Genau zu dieser Zeit ist nichts frei. "
    if not picked["slots"]:
        s["phase"] = "verschieb_wunsch"
        s["frage"] = "wunsch"
        sit["offered"] = []
        return {"text": (
            "Zu diesem Wunsch finde ich gerade nichts Freies. "
            "Ginge auch ein anderer Tag oder eine andere Tageszeit?"
        )}
    offered = [{"iso": x["iso"], "spoken": spoken_slot(x["iso"])} for x in picked["slots"]]
    zuletzt = [o.get("iso") for o in sit.get("offered") or []] if s["phase"] == "verschieb_angebot" else None
    sit["offered"] = offered
    s["phase"] = "verschieb_angebot"
    s["frage"] = "slotwahl"
    if offered and zuletzt == [o["iso"] for o in offered]:
        # Wiederhol-Wache (wie in flow._angebot): gleiches Ergebnis ehrlich
        # ansagen statt die Liste wortgleich zu wiederholen.
        liste = "; oder ".join(_s(o["spoken"]) for o in offered)
        return {"text": hinweis + f"Näher an Ihrem Wunsch habe ich leider nichts — es bleibt bei {liste}. Passt davon einer?"}
    return {"text": hinweis + spoken_offer(picked["slots"], wish_matched=picked["wishMatched"])}


def _verschieb_readback(sit: dict, neu_iso: str) -> dict:
    s = gehirn.sammler(sit)
    termin = _gewaehlt(sit)
    s["slotIso"] = neu_iso
    s["phase"] = "verschieb_bestaetigen"
    s["frage"] = "verschieb_ok"
    return {"text": (
        f"Dann verschiebe ich den Termin {termin.get('spoken')} "
        f"auf {spoken_slot(neu_iso)}. Passt das so?"
    )}


def _verschieben(sit: dict, melde: Melde) -> dict:
    if sit.get("testNoWrite"):
        s = gehirn.sammler(sit)
        s["phase"] = "fertig"
        s["frage"] = ""
        return {"text": "Der Testlauf ist beendet; der Termin wurde nicht verschoben."}
    s = gehirn.sammler(sit)
    termin = _gewaehlt(sit)
    ctx = _ctx(sit)
    ctx["appointmentId"] = _s(termin.get("id"))
    # Der Alternativpfad in calendar.move_appointment braucht denselben
    # Kalender und Besuchsgrund wie der gefundene Bestandstermin.
    ctx["calendarId"] = _s(termin.get("calendarId"))
    ctx["calendarName"] = _s(termin.get("doctorName"))
    ctx["visitMotiveId"] = _s(termin.get("motivId"))
    ctx["visitMotiveName"] = _s(termin.get("motivName"))
    ctx["slotGesperrt"] = list(sit.get("slotGesperrt") or [])
    if melde:
        melde("move_appointment")
    res = kal.move_appointment(sit["tenant"], ctx, slot_iso=s["slotIso"])
    merke_tool(sit, "move_appointment", res)
    if res.get("ok") and (res.get("moved") or res.get("dryRun")):
        _arzt_uebernehmen(sit, termin)
        sit["gefundenKey"] = ""
        sit["gefunden"] = []
        sit["verwaltenTermin"] = ""
        _verw_reset(sit)
        # Anliegen ERLEDIGT: Modus schliessen und Angebote verwerfen — sonst
        # bot der Fluss nach "Das war's, danke" WIEDER Zeiten an (live 27.08.
        # 15:22: Re-Dispatch ueber den geleerten Termin-Cache).
        s["modus"] = ""
        s["phase"] = "fertig"
        s["frage"] = ""
        sit["offered"] = []
        sit["verschiebRichtung"] = ""
        return {
            "text": (res.get("spoken") or "Der Termin ist verschoben.")
                    + " Kann ich sonst noch etwas für Sie tun?",
            "book": {"moved": True, "slotIso": res.get("slotIso") or "", "spoken": res.get("spoken") or ""},
        }
    if res.get("slotTaken"):
        fail_iso = _s(res.get("slotIso")) or _s(s.get("slotIso"))
        gesperrt = list(sit.get("slotGesperrt") or [])
        if fail_iso and fail_iso not in gesperrt:
            gesperrt.append(fail_iso)
        sit["slotGesperrt"] = gesperrt
    if res.get("slots"):
        sit["offered"] = res["slots"]
        s["phase"] = "verschieb_angebot"
        s["frage"] = "slotwahl"
        s["slotIso"] = ""
        return {"text": res.get("spoken") or "Der Platz ist gerade weg — ich habe Alternativen."}
    s["phase"] = "fertig"
    s["frage"] = ""
    return {"text": res.get("spoken") or "Das Verschieben hat gerade nicht geklappt. Die Praxis ruft Sie dazu zurück."}


_WOCHENTAG_WORT = ["Sonntag", "Montag", "Dienstag", "Mittwoch",
                   "Donnerstag", "Freitag", "Samstag"]  # Index wie %w (0=So)


def _monatsende(iso: str) -> bool:
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d")
        return (d + timedelta(days=1)).month != d.month
    except Exception:
        return False


def _zeitraum_wort(w: dict | None) -> str:
    """Die Zeitangabe des Anrufers als Sprechform: 'Im Oktober', 'Ab November',
    'Am Dienstag', 'Am Montag, den fünften Oktober'. Leer, wenn nichts
    Greifbares (dann sagt die Ansage 'Zu dieser Zeit')."""
    from kern import sprech
    w = w or {}
    von = str(w.get("von") or "")[:10]
    bis = str(w.get("bis") or "")[:10]
    try:
        if von and bis:
            if von[:7] == bis[:7] and von.endswith("-01") and _monatsende(bis):
                return f"Im {sprech._MONAT[int(von[5:7])]}"
            return "In dem genannten Zeitraum"
        if von:
            if von.endswith("-01"):
                return f"Ab {sprech._MONAT[int(von[5:7])]}"
            return "In dem genannten Zeitraum"
        if bis:
            if _monatsende(bis):
                return f"Bis Ende {sprech._MONAT[int(bis[5:7])]}"
            return "In dem genannten Zeitraum"
        if w.get("date"):
            wort = sprech.slot_wort(str(w["date"])[:10])  # 'am Montag, den …' / 'morgen'
            return wort[:1].upper() + wort[1:]
        if w.get("weekday") is not None:
            return f"Am {_WOCHENTAG_WORT[int(w['weekday']) % 7]}"
        if w.get("hour") is not None:
            return f"Um {sprech.zeit_wort(int(w['hour']))}"
    except Exception:
        return ""
    return ""


_MOTIV_NUMMER_RE = re.compile(r"^\s*\d{1,3}[.)]?\s+")
_MOTIV_KLAMMER_RE = re.compile(r"\s*\([^)]{0,12}\)")


def _motiv_sprechbar(termin: dict) -> str:
    """Besuchsgrund des Bestandstermins fuers Vorlesen — ohne Nummerierung
    ('01 Kontrolluntersuchung'), ohne Kuerzel-Klammer ('(PZR)'), '+' als 'und'."""
    name = _s(termin.get("motivName"))
    if not name:
        return ""
    try:
        wort = gehirn.grund_am_telefon(name)
    except Exception:
        wort = name
    wort = _MOTIV_NUMMER_RE.sub("", wort)
    wort = _MOTIV_KLAMMER_RE.sub("", wort)
    wort = _s(wort.replace(" + ", " und ").replace("+", " und "))
    return wort


def _termin_sprechbar(termin: dict) -> str:
    """'am Dienstag um neun Uhr bei Doktor Petsas, eingetragen als Kontrolle'."""
    wort = _s(termin.get("spoken"))
    motiv = _motiv_sprechbar(termin)
    return f"{wort}, eingetragen als {motiv}" if motiv else wort


def _ansagen(sit: dict) -> dict:
    """Gefundene Bestandstermine vorlesen (W-BESTAND-ANSAGE, Anruf 9dd61a59).

    - Hat der Anrufer einen ZEITRAUM genannt ("Habe ich im Oktober einen
      Termin?"), wird ehrlich gesagt, ob DORT etwas liegt; liegt nichts
      dort, kommt der naechste Termin trotzdem ("Im Oktober sehe ich keinen
      Termin für Sie — Ihr nächster Termin: …").
    - Der Besuchsgrund wird mitgesprochen ("eingetragen als Kontrolle").
    - Danach bleibt die Folgefrage OFFEN (frage=termin_ok bzw. sonst_noch):
      "Alles gut" / "passt" / "nein danke" werden deterministisch verstanden,
      statt ans Modell zu fallen — live machte es daraus eine Neubuchung.
    - Liegt ein GEPARKTES Anliegen bereit (die Frage kam mitten in einer
      Buchung), stellt die Ansage KEINE eigene Frage: der Ruecksprung
      (W-HIRN-AUTORESUME) haengt die offene Buchungsfrage an; zwei Fragen
      hintereinander waeren ein Monolog.
    """
    from kern import hirn
    s = gehirn.sammler(sit)
    termine = list(sit.get("gefunden") or [])
    s["phase"] = "fertig"
    s["frage"] = ""
    w = sit.get("verwHinweis") or {}
    vorsatz = ""
    if termine and _hinweis_hat(w):
        drin = [a for a in termine if _hinweis_passt(a, w)]
        zeitraum = _zeitraum_wort(w) or "Zu dieser Zeit"
        if drin:
            termine = drin
            vorsatz = (f"{zeitraum} sehe ich einen Termin für Sie: " if len(drin) == 1
                       else f"{zeitraum} sehe ich {len(drin)} Termine für Sie: ")
        else:
            vorsatz = f"{zeitraum} sehe ich keinen Termin für Sie — "
    geparkt = hirn.hat_geparktes(sit)
    if len(termine) == 1:
        _arzt_uebernehmen(sit, termine[0])
        sit["verwaltenTermin"] = _s(termine[0].get("id"))
        # Gespraechsnotiz beim Auflegen an DIESEN Termin haengen.
        sit.setdefault("booking", {})["appointmentId"] = _s(termine[0].get("id"))
        wort = _termin_sprechbar(termine[0])
        kern_text = (f"{vorsatz}{wort}." if vorsatz.endswith(": ")
                     else f"{vorsatz}Ihr nächster Termin: {wort}.")
        if geparkt:
            return {"text": kern_text}
        s["frage"] = "termin_ok"
        return {"text": f"{kern_text} Passt der so, oder möchten Sie ihn verschieben oder absagen?"}
    liste = "; ".join(_termin_sprechbar(a) for a in termine[:3] if _s(a.get("spoken")))
    kern_text = (f"{vorsatz}{liste}." if vorsatz.endswith(": ")
                 else f"{vorsatz}Sie haben {len(termine)} kommende Termine: {liste}.")
    if geparkt:
        return {"text": kern_text}
    s["frage"] = "sonst_noch"
    return {"text": f"{kern_text} Kann ich sonst noch etwas für Sie tun?"}


# W-BESTAND-ANSAGE: Antworten auf die Folgefragen nach der Ansage.
_ANSAGE_FRAGEN = {"termin_ok", "sonst_noch", "termin_aendern"}
_PASST_KERN = (
    r"alles\s+(?:gut|klar|bestens|in\s+ordnung)|passt(?:\s+(?:so|schon|gut|mir))?|"
    r"in\s+ordnung|bleibt\s+(?:so|dabei|bestehen)|so\s+lassen|lassen\s+wir\s+(?:so|dabei)|"
    r"der\s+(?:passt|bleibt|stimmt)|das\s+(?:passt|stimmt|reicht)|stimmt\s+so|"
    r"dann\s+ist\s+(?:ja\s+)?(?:alles\s+)?gut|(?:ist\s+)?(?:gut|okay|ok|super|prima|perfekt|wunderbar)"
)
_PASST_KERN_RE = re.compile(rf"\b(?:{_PASST_KERN})\b", re.I)
# Woerter, die neben der Zustimmung stehen duerfen, ohne dass der Satz etwas
# ANDERES traegt ("Bis alles gut, alles gut." — live Zug 9, 'Bis' ist ein
# Verhoerer; "Ja, passt so, danke.").
_PASST_FUELL_RE = re.compile(
    r"\b(?:ja|jaja|jawohl|nein|nö|noe|ne|nee|okay|ok|gut|super|prima|perfekt|"
    r"danke|dankeschön|dankeschoen|vielen|lieben|dank|genau|richtig|klar|schön|"
    r"schoen|fein|top|dann|so|bis|also|äh|ähm|hm|mhm|und|es|ist|das|der|die|"
    r"den|alles|mir|mit|dem|termin|wunderbar|natürlich|natuerlich|sicher|"
    r"gerne|gern|doch|ganz|sehr|wirklich|eigentlich|schon|halt|einfach|nur|"
    r"bleibt|bleiben|wir|dabei|lassen|ihn|ihr|ihnen|sie|ich)\b",
    re.I,
)
_PASST_REST_RE = re.compile(r"[^\wäöüß]+", re.I)
_KLAR_ABSCHIED_RE = re.compile(
    r"wiederh[oö]ren|\btsch[uü]s{0,2}\b|\bciao\b|das\s+(?:war'?s|wars)|"
    r"nichts\s+weiter|sch[oö]nen\s+tag",
    re.I,
)


def _ist_passt(t: str, termine: list[dict] | None = None) -> bool:
    """Zustimmung zum vorgelesenen Termin: ein Kern ("alles gut", "passt",
    "in Ordnung", "bleibt so" …) und daneben NICHTS Sachliches — hoechstens
    Fuellwoerter oder die wiederholte Terminangabe ("Alles gut, es ist in
    Ordnung, 21. Dezember." — live Zug 10)."""
    if not t or not _PASST_KERN_RE.search(t):
        return False
    rest = _PASST_FUELL_RE.sub(" ", _PASST_KERN_RE.sub(" ", t))
    rest = _PASST_REST_RE.sub(" ", rest).strip()
    if not rest:
        return True
    # Rest = reine Zeitangabe, die auf einen der vorgelesenen Termine passt?
    w = parse_slot_wish(rest) or {}
    if not _hinweis_hat(w):
        return False
    return any(_hinweis_passt(a, w) for a in (termine or []))


_VERSCHIEB_WUNSCH_RE = re.compile(r"\bverschieb\w*|\bverleg\w*", re.I)
_ABSAGE_WUNSCH_RE = re.compile(r"\babsag\w*|\bstornier\w*|\bcancel\w*", re.I)
_ABSCHIED_TEXT = "Sehr gerne. Dann wünsche ich Ihnen einen schönen Tag — auf Wiederhören!"

# "Beide/alle absagen" (W-MEHRFACH-ABSAGE 15.09.2026): der Anrufer meint MEHR
# als einen der vorgelesenen Termine. NUR beim Absagen sinnvoll (zwei Termine
# lassen sich nicht auf denselben neuen Slot verschieben).
_ALLE_RE = re.compile(r"\b(?:alle|sämtliche|saemtliche)\b", re.I)
_BEIDE_RE = re.compile(r"\bbeide[nr]?\b|\bboth\b", re.I)
_ERSTEN_ZWEITEN_RE = re.compile(
    r"(?:den\s+)?ersten\s+und\s+(?:den\s+)?zweiten", re.I,
)


def _termin_ok_zug(sit: dict, t: str, neu: set[str]) -> dict | None:
    """Antworten auf die Folgefragen der Bestands-Ansage (W-BESTAND-ANSAGE):
    'Passt der so, oder …?' (termin_ok), 'Kann ich sonst noch etwas für Sie
    tun?' (sonst_noch), 'verschieben oder absagen?' (termin_aendern).
    None => normale Kette (Modus-Wechsel, neues Anliegen, Modell)."""
    from bianca.flow import _ABSCHIED_RE  # kein Kreis-Import auf Modulebene
    from kern import abschied
    s = gehirn.sammler(sit)
    frage = s["frage"]
    if frage not in _ANSAGE_FRAGEN:
        return None
    # Ein Modus-Wechsel (Hirn/einsammeln: "dann verschieben Sie ihn bitte")
    # laeuft in die bestehende Absage-/Verschiebe-Strecke — Frage schliessen.
    if s["modus"] != "auskunft" or "modus" in neu:
        s["frage"] = ""
        return None
    kurz = len(t.split()) <= 4
    aendern = bool(_VERSCHIEB_WUNSCH_RE.search(t) or _ABSAGE_WUNSCH_RE.search(t))
    passt = not aendern and _ist_passt(t, sit.get("gefunden") or [])
    nein = gehirn.ist_nein(t) and not passt
    ja = gehirn.ist_ja(t) and not nein
    klar_abschied = bool(_KLAR_ABSCHIED_RE.search(t))
    if (passt or klar_abschied) and "wunsch" in neu:
        # "Alles gut, 21. Dezember." wiederholt den BESTANDSTERMIN — einsammeln
        # hat das Datum eben als Neubuchungs-Wunsch geerntet; das darf keine
        # spaetere Verschiebe-Suche vergiften.
        s["wunsch"] = None
        s["wunschText"] = ""

    def _nachfrage_zeitraum() -> dict | None:
        # "Und im November?" — dieselben Termine, anderer Blick. Die
        # Zeitangabe gehoert zum BESTAND: einsammeln hat sie eben als
        # Neubuchungs-Wunsch geerntet, das nehmen wir zurueck.
        if sit.get("gefunden") and _hinweis_merken(sit, t, relativ=True):
            if "wunsch" in neu:
                s["wunsch"] = None
                s["wunschText"] = ""
            return _ansagen(sit)
        return None

    def _umschalten() -> None:
        # Ohne Hirn (Notaus INTENT_SCHICHT=0) trotzdem deterministisch in
        # die Verschiebe-/Absage-Strecke — mit Hirn hat _schalten das
        # laengst getan und die Frage geraeumt (dann kommen wir nicht her).
        s["modus"] = "verschieben" if _VERSCHIEB_WUNSCH_RE.search(t) else "absagen"
        s["phase"] = ""
        s["frage"] = ""
        neu.add("modus")

    if frage == "sonst_noch":
        if aendern:
            _umschalten()
            return None
        if _ABSCHIED_RE.search(t) or passt or (nein and kurz):
            s["frage"] = ""
            return {"text": _ABSCHIED_TEXT, "hangup": abschied.an()}
        if ja and kurz:
            s["frage"] = ""
            return {"text": "Gerne — was kann ich noch für Sie tun?"}
        aus = _nachfrage_zeitraum()
        if aus is not None:
            return aus
        s["frage"] = ""
        return None

    if frage == "termin_aendern":
        if aendern:
            _umschalten()
            return None
        if klar_abschied:
            s["frage"] = ""
            return {"text": _ABSCHIED_TEXT, "hangup": abschied.an()}
        if passt or (nein and kurz):
            s["frage"] = "sonst_noch"
            return {"text": "Alles klar, der Termin bleibt bestehen. Kann ich sonst noch etwas für Sie tun?"}
        if ja and kurz:
            # "Ja" ist auf "verschieben oder absagen?" keine Antwort — einmal
            # nachhaken, statt das Modell raten zu lassen.
            return {"text": "Verschieben oder absagen — was darf ich für Sie tun?"}
        s["frage"] = ""
        return None

    # frage == "termin_ok": "Passt der so, oder möchten Sie ihn verschieben oder absagen?"
    if aendern:
        _umschalten()
        return None
    if klar_abschied:
        # "Alles gut, Dankeschön, Wiederhören." — der Termin bleibt, Schluss.
        s["frage"] = ""
        return {"text": _ABSCHIED_TEXT, "hangup": abschied.an()}
    if passt or (ja and kurz):
        # VOR dem Abschied pruefen: "Danke, passt so." ist Zustimmung, kein
        # Auflegen (_ABSCHIED_RE faengt jedes fuehrende "Danke").
        s["frage"] = "sonst_noch"
        return {"text": "Schön, dann bleibt es dabei. Kann ich sonst noch etwas für Sie tun?"}
    if nein and kurz:
        if _ABSCHIED_RE.search(t):
            # "Nein danke." auf 'passt der so, oder …?' = nichts aendern.
            s["frage"] = "sonst_noch"
            return {"text": "Alles klar, der Termin bleibt bestehen. Kann ich sonst noch etwas für Sie tun?"}
        s["frage"] = "termin_aendern"
        return {"text": "Möchten Sie den Termin verschieben oder absagen?"}
    if _ABSCHIED_RE.search(t):
        s["frage"] = ""
        return {"text": _ABSCHIED_TEXT, "hangup": abschied.an()}
    aus = _nachfrage_zeitraum()
    if aus is not None:
        return aus
    # Neues Anliegen/Zwischenfrage: Hirn bzw. Modell uebernimmt.
    s["frage"] = ""
    return None


def _bestaetigen(sit: dict, termin: dict, melde: Melde) -> dict:
    """DER Termin steht fest: Absage rueckfragen bzw. Verschieben starten."""
    s = gehirn.sammler(sit)
    if s["modus"] == "absagen":
        return _absage_frage(sit, termin)
    sit["verwaltenTermin"] = _s(termin.get("id"))
    _arzt_uebernehmen(sit, termin, fest=True)
    if s["wunsch"]:
        _verschieb_datum_auf_bestand_beziehen(sit, termin)
        return _verschieb_angebot(sit, melde)
    return _verschieb_wunsch_frage(sit, termin)


def _dispatch(sit: dict, melde: Melde) -> dict | None:
    """Name ist da: Termine holen und je nach Anliegen weitermachen."""
    s = gehirn.sammler(sit)
    res = _finden(sit, melde)
    if not res.get("ok"):
        s["phase"] = "fertig"
        s["frage"] = ""
        return {"text": (
            "Ich komme gerade nicht an den Terminkalender. "
            "Die Praxis ruft Sie dazu zurück — entschuldigen Sie bitte."
        )}
    if res.get("notFound"):
        if not sit.get("verwKorrektur"):
            return _korrektur_frage(sit)
        return _kein_termin(sit, s["modus"])
    if res.get("mehrdeutig"):
        if res.get("vornameVerworfen"):
            s["vorname"] = ""  # der gespeicherte Vorname passte nachweislich nicht
        return _vorname_frage(sit)
    termine = sit.get("gefunden") or []
    if not termine:
        return _kein_termin(sit, s["modus"])
    if s["modus"] == "auskunft":
        return _ansagen(sit)
    treffer = _filtern(sit, termine)
    if not treffer:
        # Hinweise passen auf keinen Termin: ehrlich sagen, was da ist —
        # der Anrufer erinnert sich oft falsch (Chef: nie stur "nein").
        s["phase"] = "wahl"
        s["frage"] = "terminwahl"
        frage = "Meinen Sie den?" if len(termine) == 1 else "Meinen Sie einen davon?"
        return {"text": (
            f"Zu diesen Angaben finde ich nichts — ich sehe unter Ihrem Namen: "
            f"{_liste_sprechbar(termine)}. {frage}"
        )}
    if len(treffer) == 1:
        return _bestaetigen(sit, treffer[0], melde)
    if not sit.get("verwBehandlungGefragt"):
        # Hilfsweise (Chef): die Behandlung grenzt weiter ein — aber nur,
        # wenn die Termine sich darin ueberhaupt unterscheiden.
        motive = {_s(a.get("motivName")).lower() for a in treffer}
        if len(motive) > 1:
            return _behandlung_frage(sit, treffer)
    verb = "absagen" if s["modus"] == "absagen" else "verschieben"
    s["phase"] = "wahl"
    s["frage"] = "terminwahl"
    return {"text": f"Sie haben mehrere Termine: {_liste_sprechbar(treffer)}. Welchen möchten Sie {verb}?"}


def _sammeln(sit: dict, t: str, neu: set[str], melde: Melde) -> dict | None:
    """Absagen/Verschieben (W-NACHNAME 31.08.2026, phone_agent-Vorbild):
    NUR den NACHNAMEN erfragen, dann SUCHEN — die CF braucht nichts weiter.
    Hinweise aus dem Einstiegssatz filtern die Treffer; mehrere Patienten
    mit gleichem Nachnamen (CF ambiguous) grenzt der Vorname ab."""
    s = gehirn.sammler(sit)

    if "modus" in neu and not sit.get("verwAktiv"):
        # Neues Anliegen (kein Korrektur-Wechsel absagen<->verschieben mitten
        # im Sammeln): alten Stand raeumen, Hinweise aus dem Einstiegssatz.
        notfound_davor = bool(sit.pop("verwNotFound", False))
        _verw_reset(sit)
        if notfound_davor and not ({"name", "nachname"} & neu):
            # Der vorige Anlauf scheiterte an der SUCHE — meist ein verhoerter
            # Name ("Peter Möbel"). Stur denselben Namen wieder zu suchen
            # waere dieselbe Sackgasse: Name frisch erfragen. Traegt der Satz
            # den Namen aber schon KORRIGIERT ("… absagen, Peter Müller."),
            # bleibt der frische Name stehen und wird direkt gesucht.
            s["vorname"] = ""
            s["nachname"] = ""
            s["patientId"] = ""
            s["buchstabiert"] = False
            s["buchstabenTeil"] = ""
            s["buchstabierHilfe"] = False
            s["vornameTeil"] = ""
            s["vornameGehoert"] = ""
        if s["modus"] == "absagen":
            # "Ich muss meinen Termin am Dienstag absagen": die Zeitangabe
            # beschreibt den BESTANDSTERMIN — nie ein Neubuchungs-Wunsch.
            if s["wunsch"] and _hinweis_hat(s["wunsch"]):
                sit["verwHinweis"] = dict(s["wunsch"])
                sit["verwHinweisText"] = s["wunschText"] or t
            s["wunsch"] = None
            s["wunschText"] = ""
        else:
            # Verschieben: "Termin AM Dienstag (auf Freitag)" — das am-Stueck
            # ist der alte Termin, der Rest bleibt Neu-Wunsch.
            m = _ALT_REF_RE.search(t)
            if m and _hinweis_merken(sit, m.group(1)):
                rest = f"{t[:m.start(1)]} {t[m.end(1):]}"
                w = parse_slot_wish(rest)
                s["wunsch"] = w if _hinweis_hat(w) else None
                s["wunschText"] = rest if s["wunsch"] else ""
    sit["verwAktiv"] = True

    # Antworten auf offene Fragen auswerten.
    if s["frage"] == "vorname":
        if not neu:
            return None  # Zwischenfrage/Erzaehlung: LLM, die Frage bleibt offen
        s["frage"] = ""
    elif s["frage"] == "nachname" and sit.get("verwKorrektur"):
        if not neu:
            if gehirn.ist_zwischenfrage(t) or gespraech.traegt_thema(sit, t):
                return None  # Zwischenfrage: LLM, die Korrektur-Frage bleibt offen
            # "Der stimmt aber" o. ae.: gleicher Name, die Suche unten laeuft
            # erneut und geht danach den ehrlichen Notiz-Weg.
        else:
            # Nur der Nachname wurde korrigiert: ein Vorname aus derselben
            # verhoerten Aeusserung ("Sannes" zu "Czannis") fliegt mit raus —
            # die Suche laeuft ueber den Nachnamen, die Kartei liefert den
            # richtigen Vornamen zurueck (W-NAMESKORREKTUR).
            alt_vor = _s(sit.pop("verwKorrekturVorname", ""))
            if s["vorname"] and s["vorname"] == alt_vor:
                s["vorname"] = ""
            s["frage"] = ""
    elif s["frage"] == "behandlung":
        if not _UNKLAR_RE.search(t) and not gehirn.ist_ja(t) and not gehirn.ist_nein(t):
            sit["verwBehandlung"] = t if len(t) <= 90 else t[:87] + "…"
        s["frage"] = ""
    elif s["frage"] == "anrufer_check" and s["anruferCheck"]:
        # W-ANRUFER-CHECK beantwortet: Ja hat Name/patientId/Telefon gefuellt
        # (Suche laeuft unten direkt), Nein faellt auf die Nachnamen-Frage.
        s["frage"] = ""

    # Ein schon bestimmter Termin (Auskunft/Wahl davor) braucht kein Sammeln.
    termin = _gewaehlt(sit)
    if termin:
        return _bestaetigen(sit, termin, melde)

    # NUR der NACHNAME — dann direkt suchen (Chef 31.08.2026: "erstmal sehen
    # ob er einen termin findet"; die Wann-/Behandler-Vorabfrage von
    # W-SAMMELN ist ausgebaut, freiwillig genannte Hinweise filtern weiter).
    if not s["nachname"]:
        if s["frage"] in {"name", "nachname", "anrufer_check"} and not neu:
            # Live 06.09.2026: return None liess das LLM Name fragen und
            # list_appointments ohne Patient — Identitaet deterministisch halten.
            if s["frage"] == "anrufer_check" and gehirn.anrufer_bekannt(sit):
                return {"text": gehirn.anrufer_check_frage(sit)}
            # Async-Anrufer kam NACH der Nachnamen-Frage: auf Check upgraden.
            if (s["frage"] in {"name", "nachname"} and not s["anruferCheck"]
                    and not s["fuerWen"] and gehirn.anrufer_bekannt(sit)):
                s["frage"] = "anrufer_check"
                return {"text": gehirn.anrufer_check_frage(sit)}
            was = {
                "absagen": "Damit ich den richtigen Termin absage",
                "verschieben": "Damit ich den richtigen Termin finde",
            }.get(s["modus"], "Damit ich den richtigen Termin finde")
            return {"text": (
                f"{was}: Wie ist Ihr Nachname? "
                "Buchstabieren Sie ihn am besten gleich einmal."
            )}
        # W-ANRUFER-CHECK: die Rufnummer hat einen Kartei-Patienten getroffen
        # — Name + Nummer vorlesen statt den Nachnamen zu erfragen. Ein Ja
        # (einsammeln) fuellt Name/patientId/Telefon, die Suche laeuft dann
        # direkt; ein Nein faellt hierher zurueck auf die Nachnamen-Frage.
        agentprofil.anrufer_warten(sit)
        if not s["anruferCheck"] and not s["fuerWen"] and gehirn.anrufer_bekannt(sit):
            s["frage"] = "anrufer_check"
            return {"text": gehirn.anrufer_check_frage(sit)}
        s["frage"] = "nachname"
        was = {
            "absagen": "Damit ich den richtigen Termin absage",
            "verschieben": "Damit ich den richtigen Termin finde",
        }.get(s["modus"], "Damit ich den richtigen Termin finde")
        # Chef 31.08.2026: direkt zum Buchstabieren einladen — der verhoerte
        # Nachname ist die haeufigste Ursache fuer die Fehlsuche (Zannes).
        return {"text": (
            f"{was}: Wie ist Ihr Nachname? "
            "Buchstabieren Sie ihn am besten gleich einmal."
        )}

    quittung = ""
    if (("name" in neu or "nachname" in neu)
            and "anruferCheck" not in neu and s["nachname"]):
        voll = f"{s['vorname']} {s['nachname']}".strip()
        quittung = f"Danke, {voll}. "
    aus = _dispatch(sit, melde)
    if aus and quittung and _s(aus.get("text")):
        aus["text"] = quittung + aus["text"]
    return aus


def zug(sit: dict, gesagt: str, neu: set[str], melde: Melde = None) -> dict | None:
    """Ein Anrufer-Satz durch die Termin-Verwaltung. None => LLM uebernimmt."""
    from bianca.flow import _slot_wahl  # kein Kreis-Import auf Modulebene

    s = gehirn.sammler(sit)
    t = _s(gesagt)
    if s["modus"] not in _MODI:
        return None
    _richtung_merken(sit, t)

    # 0) Folgefragen der Bestands-Ansage (W-BESTAND-ANSAGE, Anruf 9dd61a59):
    #    "Passt der so, oder …?" / "Kann ich sonst noch etwas tun?" — "alles
    #    gut", Ja, Nein, verschieben/absagen, Abschied deterministisch.
    #    None = Frage geschlossen, normale Kette (Modus-Wechsel, Modell).
    if s["frage"] in _ANSAGE_FRAGEN:
        aus = _termin_ok_zug(sit, t, neu)
        if aus is not None:
            return aus

    # 1) Offene Bestaetigungen zuerst — ein "ja" traegt sonst nichts Neues.
    if s["phase"] == "absage_bestaetigen":
        if gehirn.ist_ja(t):
            return _absagen(sit, melde)
        if gehirn.ist_nein(t):
            s["phase"] = "fertig"
            s["frage"] = ""
            return {"text": "Alles klar, der Termin bleibt bestehen. Kann ich sonst noch etwas für Sie tun?"}
        if "modus" in neu and s["modus"] == "verschieben":
            # "Nicht absagen — verschieben!" mitten in der Rueckfrage.
            termin = _gewaehlt(sit)
            if termin:
                if s["wunsch"]:
                    return _verschieb_angebot(sit, melde)
                return _verschieb_wunsch_frage(sit, termin)
        return None

    if s["phase"] == "verschieb_bestaetigen":
        if gehirn.ist_ja(t):
            return _verschieben(sit, melde)
        if gehirn.ist_nein(t) or "wunsch" in neu:
            s["slotIso"] = ""
            if "wunsch" in neu:
                return _verschieb_angebot(sit, melde)
            s["phase"] = "verschieb_wunsch"
            s["frage"] = "wunsch"
            return {"text": "Kein Problem. Wann passt es Ihnen denn besser?"}
        return None

    # Mehrfach-Absage rueckbestaetigt? (W-MEHRFACH-ABSAGE)
    if s["phase"] == "mehrfach_bestaetigen":
        if gehirn.ist_ja(t):
            return _mehrfach_absagen(sit, melde)
        if gehirn.ist_nein(t):
            sit["mehrfachAbsage"] = []
            s["phase"] = "wahl"
            s["frage"] = "terminwahl"
            return {"text": (
                "Alles klar, es bleibt alles bestehen. Möchten Sie doch einen "
                f"davon absagen? Zur Auswahl: {_liste_sprechbar(sit.get('gefunden') or [])}."
            )}
        return None

    # 2) Auswahl des Bestandstermins ("den am Donnerstag"). Hier NIE ans LLM
    #    abgeben: ein frei erfundenes "dann sage ich den ab" waere fatal.
    if s["phase"] == "wahl" and sit.get("gefunden"):
        # "Beide/alle absagen" VOR der Einzelauswahl (W-MEHRFACH-ABSAGE): der
        # Erste-Treffer-Weg darf nie still nur EINEN Termin greifen.
        if s["modus"] == "absagen":
            auswahl = _mehrfach_auswahl(t, sit["gefunden"])
            if auswahl:
                return _mehrfach_absage_start(sit, auswahl)
        angebote = [{"iso": a.get("iso"), "spoken": a.get("spoken")} for a in sit["gefunden"] if a.get("iso")]
        iso = _slot_wahl(t, angebote)
        if not iso and len(sit["gefunden"]) == 1 and gehirn.ist_ja(t):
            # "Ich sehe nur diesen: … Meinen Sie den?" — "Ja."
            iso = _s(sit["gefunden"][0].get("iso"))
        if iso:
            termin = next((a for a in sit["gefunden"] if _s(a.get("iso")) == iso), {})
            if termin:
                return _bestaetigen(sit, termin, melde)
        if gehirn.ist_nein(t) and s["modus"] in {"absagen", "verschieben"}:
            # Keiner der gezeigten Termine ist gemeint: ehrlich + Notiz.
            return _nicht_gefunden(sit)
        if gehirn.ist_zwischenfrage(t) or gespraech.traegt_thema(sit, t):
            # Abschweifung/Nebenthema: LLM antwortet (Talk-Schicht); Erledigt-
            # Wache + Stand im Prompt verhindern erfundene Absagen und
            # fuehren zur Wahl zurueck.
            return None
        return {"text": (
            f"Da will ich nichts Falsches erwischen. Zur Auswahl: {_liste_sprechbar(sit['gefunden'])}. "
            "Sagen Sie einfach 'den ersten' oder 'den zweiten' — oder nennen Sie die Uhrzeit."
        )}

    # 3) Neuer Zeitpunkt beim Verschieben
    if s["phase"] == "verschieb_angebot" and sit.get("offered"):
        iso = _slot_wahl(t, sit["offered"])
        if iso:
            return _verschieb_readback(sit, iso)
        if "wunsch" in neu:
            return _verschieb_angebot(sit, melde)
        if gehirn.ist_nein(t):
            s["phase"] = "verschieb_wunsch"
            s["frage"] = "wunsch"
            return {"text": "Wann würde es Ihnen denn besser passen — eher vormittags oder nachmittags?"}
        return None

    if s["phase"] == "verschieb_wunsch":
        if "wunsch" in neu:
            return _verschieb_angebot(sit, melde)
        if not neu:
            return None

    # 4) Nach erledigter Absage: direkt neu buchen?
    if s["frage"] == "neubuchung":
        if ("name" in neu or "nachname" in neu) and s["modus"] in {"absagen", "verschieben"} \
                and s["nachname"] and not gehirn.ist_ja(t):
            # "Nein, mein Nachname ist Zannes." nach der Fehlsuche ist eine
            # KORREKTUR, kein blosses Nein (live 31.08.2026: der Nein-Zweig
            # antwortete "Alles klar." und ignorierte den Namen) — mit dem
            # frischen Namen direkt neu suchen (W-NAMESKORREKTUR). Ein "Ja"
            # mit Namen bleibt beim Neubuchungs-Weg darunter.
            sit.pop("verwNotFound", None)
            s["phase"] = ""
            s["frage"] = ""
            return _dispatch(sit, melde)
        if gehirn.ist_ja(t) or "grund" in neu or "wunsch" in neu:
            s["modus"] = "buchen"
            s["phase"] = ""
            s["frage"] = ""
            if s["warSchonMal"] is None:
                s["warSchonMal"] = bool(s["patientId"])
            hintergrund.anstossen(sit)
            fid, frage = gehirn.naechste_frage(sit)
            s["frage"] = fid
            return {"text": frage or "Worum geht es denn — eine Kontrolle, Schmerzen, oder etwas anderes?"}
        if gehirn.ist_nein(t):
            s["frage"] = ""
            return {"text": "Alles klar. Kann ich sonst noch etwas für Sie tun?"}
        return None

    # 5) Absagen/Verschieben: Nachname erfragen und SUCHEN (W-NACHNAME).
    #    Nach ERLEDIGTEM Anliegen (phase fertig) nur mit NEUER Info bzw.
    #    offener Frage wieder los — der geleerte Termin-Cache allein ist
    #    kein Grund (live 27.08. 15:22: "Das war's, danke" loeste sonst
    #    ein frisches Slot-Angebot aus).
    if s["modus"] in {"absagen", "verschieben"}:
        if s["phase"] in {"", "fertig"} and (
            ("name" in neu or "nachname" in neu or "modus" in neu)
            or s["frage"] in {"behandlung", "name", "nachname", "vorname", "anrufer_check"}
            or (s["phase"] == "" and sit.get("gefundenKey") != f"{s['vorname']}|{s['nachname']}".lower())
        ):
            return _sammeln(sit, t, neu, melde)
        return None

    # 6) Auskunft: Nachname reicht — Termine holen und vorlesen.
    if "modus" in neu:
        # Neues Auskunfts-Anliegen: die Zeitangabe im Satz ("Habe ich im
        # Oktober einen Termin?") beschreibt den BESTAND — merken fuer die
        # ehrliche Ansage, und nie als Neubuchungs-Wunsch stehen lassen
        # (einsammeln hat sie eben als Wunsch geerntet; W-BESTAND-ANSAGE).
        sit["verwHinweis"] = {}
        sit["verwHinweisText"] = ""
        if _hinweis_merken(sit, t, relativ=True) and "wunsch" in neu:
            s["wunsch"] = None
            s["wunschText"] = ""
    if not s["nachname"]:
        if s["frage"] in {"name", "nachname", "anrufer_check"} and not neu:
            # Live 06.09.2026 Petsas: LLM fragte "Wie lautet Ihr Name?" und
            # rief list_appointments ohne Patient — hier deterministisch bleiben.
            if s["frage"] == "anrufer_check" and gehirn.anrufer_bekannt(sit):
                return {"text": gehirn.anrufer_check_frage(sit)}
            # Async-Anrufer kam erst NACH der Nachnamen-Frage: upgraden.
            if (s["frage"] in {"name", "nachname"} and not s["anruferCheck"]
                    and not s["fuerWen"] and gehirn.anrufer_bekannt(sit)):
                s["frage"] = "anrufer_check"
                return {"text": gehirn.anrufer_check_frage(sit)}
            return {"text": "Damit ich in den Kalender schauen kann: Wie ist Ihr Nachname?"}
        # W-ANRUFER-CHECK: erkannten Anrufer vorlesen statt erfragen.
        # Cache-Pfad: Anrufer kommt oft erst async — kurz warten (Petsas).
        agentprofil.anrufer_warten(sit)
        if not s["anruferCheck"] and not s["fuerWen"] and gehirn.anrufer_bekannt(sit):
            s["frage"] = "anrufer_check"
            return {"text": gehirn.anrufer_check_frage(sit)}
        s["frage"] = "nachname"
        return {"text": "Damit ich in den Kalender schauen kann: Wie ist Ihr Nachname?"}

    if s["frage"] == "vorname" and not neu:
        return {"text": "Wie ist Ihr Vorname?"}
    if s["frage"] == "vorname" and neu:
        s["frage"] = ""

    if s["phase"] in {"", "fertig"} and (
        ("name" in neu or "nachname" in neu or "modus" in neu)
        or (s["phase"] == "" and sit.get("gefundenKey") != f"{s['vorname']}|{s['nachname']}".lower())
    ):
        quittung = ""
        if (("name" in neu or "nachname" in neu)
                and "anruferCheck" not in neu and s["nachname"]):
            voll = f"{s['vorname']} {s['nachname']}".strip()
            quittung = f"Danke, {voll}. "
        aus = _dispatch(sit, melde)
        if aus and quittung and _s(aus.get("text")):
            aus["text"] = quittung + aus["text"]
        return aus

    return None


def status_zeile(sit: dict) -> str:
    """Kompakter Verwaltungs-Stand fuer den LLM-Prompt, wenn der Fluss abgibt."""
    s = sit.get("sammler") or {}
    if s.get("modus") not in _MODI:
        return ""
    termine = "; ".join(_s(a.get("spoken")) for a in (sit.get("gefunden") or [])[:3])
    teile = [
        f"Anliegen={s.get('modus')}",
        f"Name={_s(s.get('vorname'))} {_s(s.get('nachname'))}".strip(),
        f"Phase={_s(s.get('phase')) or 'sammeln'}",
    ]
    if _s(sit.get("verwHinweisText")):
        teile.append(f"Termin-Hinweis={_s(sit.get('verwHinweisText'))}")
    offen = f" Offene Frage: {s['frage']}." if s.get("frage") else ""
    if termine:
        offen += f" Gefundene Termine: {termine}."
    return (
        "Laufende Termin-Verwaltung (fuehre den Anrufer immer dorthin zurueck): "
        + ", ".join(teile) + "." + offen
    )
