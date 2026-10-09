"""Bestandstermine am Telefon: ansagen, absagen, verschieben — deterministisch.

Gleiche Bauart wie flow.py: kein LLM auf dem Pflichtpfad. Termine kommen
entweder aus der lesenden Tagesabfrage oder aus agentFindPatientAppointments;
der Storno trifft punktgenau die Termin-ID, das Verschieben läuft über
postpone mit Termin-ID. Ein internes ``None`` wird bei aktiver Absage oder
Verschiebung vom festen Fortsetzungsanker aufgefangen, nie vom freien LLM.

Prozedur Absagen/Verschieben (W-VERWALTUNG-TERMIN-ZUERST 16.09.2026):
1. Einen bekannten Termin zuerst ueber Datum/Uhrzeit, Behandler und die
   bestätigte Rufnummer beziehungsweise patientId eingrenzen. Ein Name
   ist dabei nur Kandidat (mindestens 60 Prozent Aehnlichkeit), nie alleiniger
   Schreibbeweis.
2. Fehlt die Zeit wirklich, wird ueber Rufnummer/Patient, Behandler und Name
   gesucht. Bei einer Terminauskunft ("ich weiss nicht mehr wann") wird
   NIEMALS nach dem vergessenen Datum gefragt.
3. Jeden Kandidaten MIT Termin, Patient und Behandler rueckbestaetigen. Erst
   ein ausdrueckliches Ja gibt die punktgenaue Termin-ID zum Schreiben frei.
4. Meldet die alte Namens-CF MEHRERE Patienten, grenzt der VORNAME ab.
5. Treffer BESTAETIGEN mit Anrede ("… Frau Mueller, ja?") — bei Ja loeschen
   bzw. die Verschiebe-Strecke starten.
6. Mehrere TERMINE des Patienten -> hilfsweise die BEHANDLUNG erfragen,
   danach die Auswahl-Liste.
7. Nicht gefunden -> ehrlich sagen + ECHTE Notiz (praxis_notizen.jsonl,
   Dock-Anzeige): "keine Sorge, ich schreibe eine Notiz, und die wird
   Doktor XY vorgelegt."
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Callable

from bianca import gehirn, hintergrund, telefon
from kern import agentprofil
from kern import calendar as kal
from kern import gespraech, identitaet_merkmale, intent, motive
from kern import notes, observability_manifest
from kern import patients, spur
from kern.config import DATA_DIR
from kern.patients import arzt_sprechname
from kern.sitzung import merke_tool
from kern.slots import (
    WEEKDAYS,
    _weekday_of,
    angebot_engen,
    fragt_nach_frueherem_slot,
    fruehester_slot_antwort,
    parse_slot_wish,
    pick_slots,
    slot_praeferenz_aenderung,
    slot_wunsch_hart,
    slots_mit_abstand,
    spoken_offer,
    spoken_slot,
    will_neu_suchen,
    wunsch_mit_slot_praeferenz,
)

Melde = Callable[[str], None] | None

_MODI = {"absagen", "verschieben", "auskunft"}

# "Keine Ahnung, weiss ich nicht mehr" auf die Wann-/Behandlungs-Frage.
_UNKLAR_RE = re.compile(
    r"keine\s+ahnung|wei(?:ß|ss)\s+(?:ich\s+)?(?:es\s+|das\s+)?"
    r"(?:(?:auch|leider|gerade|aber|gar|wirklich)\s+)*"
    r"(?:nicht(?:\s+mehr)?|nimmer)|nicht\s+mehr\s+genau|"
    r"nicht\s+(?:so\s+)?sicher|vergessen|"
    r"keinen?\s+(?:schimmer|plan)|m(?:ü|ue)sste\s+ich\s+nach(?:schauen|sehen|gucken)",
    re.I,
)

_MONATE_RE = (
    r"januar|februar|märz|maerz|april|mai|juni|juli|august|"
    r"september|oktober|november|dezember"
)
_UHR_COLON_RE = re.compile(r"\b(\d{1,2})\s*:\s*(\d{2})\b")
_UHR_PUNKT_RE = re.compile(
    r"\b(?:(?:um|gegen)\s+)?(\d{1,2})\s*\.\s*(\d{2})\s*uhr\b", re.I)
_UHR_WORT_RE = re.compile(
    r"\b(\d{1,2})\s*uhr(?:\s+(\d{1,2}))?\b", re.I)
_HALB_RE = re.compile(r"\bhalb\s+\w+\b", re.I)
# Ein klares Nein zum automatischen Neubuchungs-Angebot darf nie wegen einer
# zugleich genannten Zeitangabe als BUCHUNGSWUNSCH gewertet werden.
_KEIN_NEUER_TERMIN_RE = re.compile(
    r"\b(?:kein(?:en|em|er)?|nicht\s+(?:noch\s+)?(?:ein(?:en)?\s+)?)"
    r"(?:neuen?\s+)?termin\b|\bkeine\s+neubuchung\b", re.I)
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


def _ablehnte_slots_sperren(sit: dict) -> None:
    """Abgelehntes Angebot nie wieder vorlesen — die nächste Suche startet frisch."""
    alt = [_s(o.get("iso")) for o in sit.get("offered") or [] if _s(o.get("iso"))]
    if not alt:
        return
    gesperrt = list(sit.get("slotGesperrt") or [])
    for iso in alt:
        if iso not in gesperrt:
            gesperrt.append(iso)
    sit["slotGesperrt"] = gesperrt


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
    # Eine Rufnummer darf die Patienten-Suche nur steuern, wenn sie zu
    # DIESEM Patienten gehört und bestätigt ist. Bei Drittterminen ist
    # ``telefon`` regelmäßig die Kontakt-Nummer des Elternteils/Anrufers;
    # sie darf nie auf dessen eigene Akte statt auf die genannte Person
    # umlenken. Eine nur gehörte, noch nicht rückbestätigte Nummer ist
    # ebenfalls kein Identitätsbeweis.
    tel = ""
    if not s.get("fuerWen"):
        if s.get("telefonOk") and s.get("telefon"):
            tel = _s(s["telefon"])
        elif s.get("bekannt") and s.get("aktePhone"):
            tel = _s(s["aktePhone"])
        elif s.get("anruferCheck") == "ja":
            an = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
            tel = _s(an.get("telefon") or sit.get("callerPhone"))
    if tel:
        ctx["phone"] = tel
    else:
        ctx.pop("phone", None)
    dubletten = [
        p for p in (sit.get("patientenDubletten") or [])
        if isinstance(p, dict) and _s(p.get("id"))
    ]
    if len(dubletten) > 1:
        ctx["duplicatePatientIds"] = [_s(p.get("id")) for p in dubletten]
        ctx["duplicatePatientCreatedAt"] = {
            _s(p.get("id")): _s(
                p.get("createdAt") or p.get("created_at") or p.get("created"))
            for p in dubletten
        }
    else:
        ctx.pop("duplicatePatientIds", None)
        ctx.pop("duplicatePatientCreatedAt", None)
    # Nur die Verwaltungs-Lesewege aktivieren den freien 60%-Namensabgleich.
    # Buchungs- und Read-after-write-Vertraege bleiben unveraendert.
    ctx["managementNameMatch"] = True
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


def _obs_quelle(raw: Any, fallback: str = "unknown") -> str:
    quelle = _s(raw)
    return {
        "phone": "telefon",
        "phoneExact": "telefon",
        "patient_id": "patientId",
        "name": "nameExact",
        "nameBestaetigt": "name60",
    }.get(quelle, quelle or fallback)


def _obs(
    sit: dict,
    phase: str,
    *,
    route: str = "none",
    outcome: str = "unknown",
    error: str = "",
    source: str = "none",
    count: int | None = None,
    dispatch: dict | None = None,
) -> None:
    observability_manifest.emit(
        sit,
        "verwaltung",
        phase,
        route_class=route,
        outcome=outcome,
        error_class=error,
        source=_obs_quelle(source, "unknown") if source != "none" else "none",
        candidate_count=count,
        dispatch=dispatch,
    )


def _dispatch_ohne_pii(dispatch: Any) -> dict:
    """Nur Transport-Metadaten; nie URL, Payload, Token oder Fach-IDs."""
    d = dispatch if isinstance(dispatch, dict) else {}
    return {
        key: d.get(key)
        for key in ("route", "method", "httpStatus", "ms")
        if d.get(key) not in (None, "")
    }


def _verwaltungs_lesespur(res: dict) -> dict:
    """Tool-Ledger ohne Namen, Rufnummern oder fremde Patienten-IDs."""
    dispatch = res.get("dispatch") if isinstance(res.get("dispatch"), dict) else {}
    response = dispatch.get("response") if isinstance(dispatch.get("response"), dict) else {}
    sichere_antwort = {
        "status": response.get("status")
    } if response.get("status") not in (None, "") else {}
    sichere_antwort["appointments"] = len(res.get("appointments") or [])
    if res.get("matchSource"):
        sichere_antwort["matchSource"] = _s(res.get("matchSource"))
    return {
        "ok": bool(res.get("ok")),
        "notFound": bool(res.get("notFound")),
        "mehrdeutig": bool(res.get("mehrdeutig")),
        "appointments": [{} for _ in (res.get("appointments") or [])],
        "dispatch": {
            "route": dispatch.get("route") or "",
            "method": dispatch.get("method") or "POST",
            "httpStatus": dispatch.get("httpStatus"),
            "ms": dispatch.get("ms"),
            "response": sichere_antwort,
        },
    }


def _finden(sit: dict, melde: Melde) -> dict:
    """Kommende Termine zum Namen holen — einmal pro Name, dann aus dem Cache."""
    s = gehirn.sammler(sit)
    key = f"{s['vorname']}|{s['nachname']}".lower()
    if sit.get("gefundenKey") == key and isinstance(sit.get("gefunden"), list):
        return {"ok": True, "appointments": sit["gefunden"]}
    if melde:
        melde("list_appointments")
    res = dict(kal.find_patient_appointments(sit["tenant"], _ctx(sit)))
    ausgeschlossene_termine = set(
        sit.get("_verwAusgeschlosseneTermine")
        or sit.get("verwAusgeschlossen")
        or []
    )
    ausgeschlossene_patienten = set(
        sit.get("_verwAusgeschlossenePatienten") or []
    )
    patient = res.get("patient") if isinstance(res.get("patient"), dict) else {}
    patient_id = _s(patient.get("id"))
    if patient_id and patient_id in ausgeschlossene_patienten:
        # Ein ausdrücklich verworfener fuzzy Patient darf über denselben
        # Cloud-Function-Namensweg nicht unmittelbar wieder auftauchen.
        res.update({
            "patient": {},
            "appointments": [],
            "notFound": True,
            "nameMismatch": True,
            "rejectedCandidate": True,
        })
    elif isinstance(res.get("appointments"), list):
        res["appointments"] = [
            a for a in res["appointments"]
            if isinstance(a, dict)
            and _s(a.get("id")) not in ausgeschlossene_termine
            and _s(a.get("patientId")) not in ausgeschlossene_patienten
        ]
    if isinstance(res.get("candidates"), list):
        sit["kandidaten"] = [
            c for c in res["candidates"]
            if isinstance(c, dict) and _s(c.get("id"))
        ]
    count = len(res.get("appointments") or [])
    quelle = _obs_quelle(res.get("matchSource"), "nameExact")
    outcome = (
        "error" if not res.get("ok")
        else "ambiguous" if res.get("mehrdeutig")
        else "not_found" if res.get("notFound")
        else "found" if count
        else "empty"
    )
    _obs(
        sit,
        "read",
        route="patient_appointments_read",
        outcome=outcome,
        source=quelle,
        count=count,
        dispatch=res.get("dispatch"),
    )
    _obs(sit, "identity", outcome=outcome, source=quelle, count=count)
    if count:
        _obs(sit, "found", outcome="found", source=quelle, count=count)
    merke_tool(
        sit,
        "agentFindPatientAppointments",
        _verwaltungs_lesespur(res),
    )
    if res.get("matchSource") == "name60":
        # Ein fuzzy gefundener Name ist nur Kandidat. Das folgende
        # Absage-/Verschiebe-Ja bestätigt erst Termin UND Patient.
        sit["verwDetailQuelle"] = "name60"
    fuzzy = res.get("matchSource") == "name60"
    if res.get("ok") and not res.get("notFound") and not res.get("mehrdeutig"):
        pat = res.get("patient") or {}
        if int(res.get("duplicateCount") or 0) > 1:
            sit["patientenDubletten"] = [
                {
                    "id": patient_id,
                    "firstName": _s(pat.get("firstName")),
                    "lastName": _s(pat.get("lastName")),
                }
                for patient_id in (res.get("duplicatePatientIds") or [])
                if _s(patient_id)
            ]
        if _s(pat.get("id")) and not fuzzy:
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
        patient_name = f"{_s(pat.get('firstName'))} {_s(pat.get('lastName'))}".strip()
        sit["gefunden"] = [
            {
                **a,
                "patientId": _s(a.get("patientId")) or _s(pat.get("id")),
                "patientFirstName": _s(a.get("patientFirstName")) or _s(pat.get("firstName")),
                "patientLastName": _s(a.get("patientLastName")) or _s(pat.get("lastName")),
                "patientName": _s(a.get("patientName")) or patient_name,
            }
            for a in (res.get("appointments") or [])
            if isinstance(a, dict)
        ]
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
    teile = [_s(a.get("spoken")) for a in termine if _s(a.get("spoken"))]
    if len(teile) >= 4:
        labels = ("Erstens", "Zweitens", "Drittens", "Viertens", "Fünftens", "Sechstens")
        sichtbar = teile[:len(labels)]
        text = "; ".join(
            f"{labels[i]}: {gesprochen}" for i, gesprochen in enumerate(sichtbar)
        )
        if len(teile) > len(sichtbar):
            text += f"; außerdem {len(teile) - len(sichtbar)} weitere Termine"
        return text
    if len(teile) > 1:
        return "; ".join(teile[:-1]) + "; und " + teile[-1]
    return teile[0] if teile else ""


def _auswahl_anweisung(termine: list[dict]) -> str:
    """Sprechbare, zur wirklich vorgelesenen Terminmenge passende Auswahlhilfe."""
    formen = ("ersten", "zweiten", "dritten", "vierten", "fünften", "sechsten")
    n = min(
        len([a for a in termine if _s(a.get("spoken"))]),
        len(formen),
    )
    if n <= 0:
        return "Nennen Sie bitte Datum und Uhrzeit."
    if n == 1:
        auswahl = f"den {formen[0]}"
    elif n == 2:
        auswahl = f"den {formen[0]} oder {formen[1]}"
    else:
        auswahl = (
            ", ".join(f"den {f}" for f in formen[:n - 1])
            + f" oder den {formen[n - 1]}"
        )
    return f"Sagen Sie {auswahl} Termin – oder nennen Sie Datum und Uhrzeit."


# --- Hinweis-Sammlung (Chef 29.08.2026: erst Daten, dann suchen) -----------


def _verw_reset(sit: dict) -> None:
    """Sammel-Stand raeumen (neues Anliegen bzw. Anliegen erledigt)."""
    # Ein Folgeanliegen darf niemals Termin-ID, Auswahl oder Slot-Angebote
    # des vorherigen Verwaltungsjobs erben. Besonders kritisch: erst einen
    # von mehreren Terminen absagen, danach einen anderen verschieben.
    sit["gefunden"] = []
    sit["gefundenKey"] = ""
    sit["verwaltenTermin"] = ""
    sit["mehrfachAbsage"] = []
    sit["offered"] = []
    sit["verschiebRichtung"] = ""
    sit.pop("verwAnruferDirekt", None)
    sit.pop("verwNotFound", None)
    sit.pop("verwKorrektur", None)        # W-NAMESKORREKTUR: frische Chance
    sit.pop("verwKorrekturVorname", None)
    sit.pop("verwWann", None)         # Altlast aus W-SAMMELN-Sitzungen
    sit.pop("verwArztGefragt", None)  # (Wann-/Behandler-Vorabfrage ist raus)
    sit.pop("verwDetailArztGefragt", None)
    sit.pop("verwDetailPraefixGesagt", None)
    sit.pop("verwArztNachgefragt", None)
    sit["verwHinweis"] = {}
    sit["verwHinweisText"] = ""
    sit["verwBehandlungGefragt"] = False
    sit["verwBehandlung"] = ""
    sit["verwAktiv"] = False
    sit.pop("verwZeitUnbekannt", None)
    sit.pop("moveFails", None)
    # Die ungesehene Tagesliste kann Daten fremder Patienten enthalten.
    # Nur prozesslokal halten: Session-Sicherung verwirft "_" Felder.
    sit.pop("_verwDetailTag", None)
    sit.pop("_verwDetailTermine", None)
    sit.pop("_verwDetailDispatch", None)
    sit.pop("_verwDetailGeloggtKey", None)
    sit.pop("_verwNameStrukturiert", None)
    sit.pop("_verwNameGehoert", None)
    sit.pop("_verwName60Bestaetigt", None)
    sit.pop("_verwName60Danach", None)
    sit.pop("_obsVerwConfirmed", None)
    sit.pop("_verwAusgeschlosseneTermine", None)
    sit.pop("_verwAusgeschlossenePatienten", None)
    sit.pop("_verwWannTeilGefragt", None)
    # Altlasten aus Entwicklungsstaenden ebenfalls sicher entfernen.
    sit.pop("verwDetailTag", None)
    sit.pop("verwDetailTermine", None)
    sit.pop("verwDetailGeloggtTag", None)
    sit.pop("verwDetailQuelle", None)
    sit.pop("verwKandidat", None)
    sit.pop("verwAusgeschlossen", None)
    sit.pop("verwDrittpersonGeloest", None)
    sit.pop("verwWunschAlt", None)
    sit.pop("verwWunschTextAlt", None)
    sit.pop("verwAbschlussOffen", None)
    sit.pop("verwBestaetigungUnklar", None)


def _hinweis_hat(w: dict | None) -> bool:
    """Traegt der Wunsch-Parse eine brauchbare Zeitangabe?"""
    w = w or {}
    return bool(
        w.get("date") or w.get("weekday") is not None or w.get("hour") is not None
        or w.get("hourMin") is not None or w.get("minDaysAhead")
        or w.get("minuteOfDay") is not None
        or w.get("von") or w.get("bis")  # W-SUCHFENSTER: "mein Termin im Oktober"
    )


def _minute_von_text(text: str, w: dict | None = None) -> int | None:
    """Exakte Bestands-Uhrzeit lesen, ohne den Buchungsparser zu veraendern."""
    t = _s(text)
    m = _UHR_COLON_RE.search(t) or _UHR_PUNKT_RE.search(t) or _UHR_WORT_RE.search(t)
    if m:
        try:
            h = int(m.group(1))
            minute = int(m.group(2) or 0)
        except (TypeError, ValueError):
            return None
        if 0 <= h <= 23 and 0 <= minute <= 59:
            return h * 60 + minute
    if _HALB_RE.search(t) and isinstance(w, dict) and w.get("hour") is not None:
        # parse_slot_wish legt "halb zwei" bereits auf die Praxisstunde 13.
        return int(w["hour"]) * 60 + 30
    return None


def _hinweis_merken(sit: dict, text: str, *, relativ: bool = False) -> bool:
    """Zeitangabe zum BESTANDSTERMIN aus dem Satz ziehen und merken.
    relativ=True nimmt auch heute/morgen/uebermorgen mit (Auskunft: "Habe
    ich morgen einen Termin?")."""
    w = parse_slot_wish(text)
    if relativ and not _hinweis_hat(w):
        w = gehirn._wunsch_deuten(text) or {}
    if not _hinweis_hat(w):
        return False
    minute = _minute_von_text(text, w)
    if minute is not None:
        w["minuteOfDay"] = minute
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
    if w.get("minuteOfDay") is not None:
        minuten = int(iso[11:13]) * 60 + int(iso[14:16])
        # Exakt genannte Uhrzeiten liegen im Kalender meist auf 5-/10-/15-
        # Minuten-Rastern. Zwanzig Minuten fangen STT-/Erinnerungsabweichung,
        # aber nie einen anderen Termin eine Stunde spaeter.
        if abs(minuten - int(w["minuteOfDay"])) > 20:
            return False
    elif w.get("hour") is not None:
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


_VERW_NAME_STOP = {
    "am", "an", "bei", "beim", "der", "den", "die", "einen", "einem",
    "gegen", "im", "ist", "mein", "meine", "meinen", "termin", "termine",
    "uhr", "um", "vom", "war", "wäre", "waere",
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag",
    "sonntag", "heute", "morgen", "übermorgen", "uebermorgen",
    "januar", "februar", "märz", "maerz", "april", "mai", "juni", "juli",
    "august", "september", "oktober", "november", "dezember",
}


def _name_norm(v: Any, *, zeitwoerter: bool = True) -> str:
    """Namensvergleich ohne Zeit-/Termin-Paraphrasen und Umlaut-Schreibweisen."""
    roh = unicodedata.normalize("NFKD", _s(v).casefold())
    roh = "".join(c for c in roh if not unicodedata.combining(c))
    toks = [
        t for t in re.sub(r"[^a-z0-9ß]+", " ", roh).split()
        if (not zeitwoerter or t not in _VERW_NAME_STOP) and not t.isdigit()
    ]
    return "".join(toks).replace("ß", "ss")


def _name_aehnlichkeit(s: dict, termin: dict) -> float:
    """Patientenname gegen Termin-Snapshot; mindestens 0,60 ist Kandidat."""
    gesagt_nach = _name_norm(s.get("nachname"))
    kandidat_nach = _name_norm(termin.get("patientLastName"), zeitwoerter=False)
    if not gesagt_nach or not kandidat_nach:
        return 0.0
    nach = SequenceMatcher(None, gesagt_nach, kandidat_nach).ratio()
    gesagt_vor = _name_norm(s.get("vorname"))
    kandidat_vor = _name_norm(termin.get("patientFirstName"), zeitwoerter=False)
    if not gesagt_vor or not kandidat_vor:
        return nach
    # Sobald beide Teile genannt wurden, zählt der ganze Name. Ein exakt
    # gleicher Nachname darf keinen völlig anderen Vornamen überstimmen
    # (Live: „Larissa Hauck“ wurde als „Meryem Hauck“ übernommen).
    return SequenceMatcher(
        None,
        gesagt_vor + gesagt_nach,
        kandidat_vor + kandidat_nach,
    ).ratio()


def _patienten_identitaet(sit: dict) -> tuple[str, str]:
    """Nur die Identitaet des Patienten, nie die Kontaktperson eines Dritten."""
    s = gehirn.sammler(sit)
    if s.get("fuerWen") or s.get("anruferCheck") == "nein":
        return "", ""
    if s.get("anruferCheck") != "ja" and not s.get("bekannt"):
        # Eine bloß übermittelte Rufnummer ist noch kein Identitätsbeweis.
        # Erst die ausgesprochene Rückversicherung oder eine erfolgreiche
        # Patientensuche darf sie zur Eingrenzung eines Tageskalenders nutzen.
        return "", ""
    an = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
    pid = _s(s.get("patientId") or an.get("patientId"))
    phone = (
        telefon.normaliert(s.get("aktePhone") or "")
        or telefon.normaliert(s.get("telefonBekannt") or "")
        or telefon.normaliert(an.get("telefon") or "")
        or telefon.normaliert(sit.get("callerPhone") or "")
    )
    return pid, phone


def _detail_tag(sit: dict) -> str:
    w = sit.get("verwHinweis") if isinstance(sit.get("verwHinweis"), dict) else {}
    return _s(w.get("date"))[:10]


def _detail_kandidaten(sit: dict, melde: Melde) -> dict | None:
    """Termin-zuerst-Kandidaten fuer Verwaltung, niemals Neubuchung."""
    s = gehirn.sammler(sit)
    if s["modus"] not in _MODI or (
            s["modus"] == "auskunft" and sit.get("verwZeitUnbekannt")):
        return None
    tag = _detail_tag(sit)
    if not tag:
        return None
    if sit.get("_verwDetailTag") == tag and isinstance(sit.get("_verwDetailTermine"), list):
        res = {
            "ok": True,
            "appointments": list(sit["_verwDetailTermine"]),
            "truncated": False,
            "dispatch": sit.get("_verwDetailDispatch"),
        }
    else:
        if melde:
            melde("list_appointments")
        res = kal.find_appointments_by_date(sit["tenant"], tag)
        if not res.get("ok") or res.get("truncated"):
            _obs(
                sit,
                "read",
                route="calendar_day_read",
                outcome="error",
                error="invalid_response" if res.get("truncated") else "",
                source="unknown",
                count=len(res.get("appointments") or []),
                dispatch=res.get("dispatch"),
            )
            return None
        sit["_verwDetailTag"] = tag
        sit["_verwDetailTermine"] = list(res.get("appointments") or [])
        sit["_verwDetailDispatch"] = res.get("dispatch")
    w = sit.get("verwHinweis") or {}
    alle = [
        dict(a) for a in (res.get("appointments") or [])
        if isinstance(a, dict) and _hinweis_passt(a, w)
        and _s(a.get("id")) not in set(
            sit.get("_verwAusgeschlosseneTermine")
            or sit.get("verwAusgeschlossen")
            or []
        )
        and _s(a.get("patientId")) not in set(
            sit.get("_verwAusgeschlossenePatienten") or []
        )
    ]
    cal = _s((s.get("arzt") or {}).get("calendarId"))
    if cal:
        alle = [a for a in alle if _s(a.get("calendarId")) == cal]
    elif _s((s.get("arzt") or {}).get("name")):
        arzt = _name_norm((s.get("arzt") or {}).get("name"))
        alle = [a for a in alle if arzt and (
            arzt in _name_norm(a.get("doctorName"))
            or _name_norm(a.get("doctorName")) in arzt
        )]

    pid, phone = _patienten_identitaet(sit)
    hat_name = bool(_name_norm(s.get("nachname")))
    for a in alle:
        a["_nameScore"] = round(_name_aehnlichkeit(s, a), 3)
    # Ein ausgesprochener Patientenname widerspricht einer bloss per Leitung
    # erkannten Kontaktperson, bis mindestens 60 Prozent Namensnaehe bestehen.
    name_ok = [a for a in alle if float(a.get("_nameScore") or 0) >= 0.60]
    pid_ok = [a for a in alle if pid and _s(a.get("patientId")) == pid]
    phone_ok = [
        a for a in alle
        if phone and telefon.normaliert(a.get("patientPhone") or "") == phone
    ]
    hat_terminkandidaten = bool(alle)
    # Ohne Patientenbezug grenzen die Termindaten nur die Kandidaten ein.
    # Ein einzelner Termin darf seinen Patientennamen nicht an einen Anrufer
    # verraten, der lediglich Datum und Uhrzeit kennt.
    # W-ZWEI-MERKMALE: Tageskandidaten, die ZWEI unabhaengige Merkmale treffen
    # (z. B. starker Name + vom Anrufer genannter Tag). Nur EIN Patient darf
    # so aufgeloest werden — sonst bleibt es mehrdeutig.
    zwei = []
    if identitaet_merkmale.aktiv():
        zwei = [a for a in alle
                if identitaet_merkmale.reicht(identitaet_merkmale.merkmale(sit, a))]
    quelle = "name_required"
    if pid_ok:
        alle = pid_ok
        quelle = "patientId"
    elif phone_ok:
        alle = phone_ok
        quelle = "telefon"
    elif pid or phone:
        # Alte harte Grenze: eine bestätigte Patienten-ID/Rufnummer, die nicht
        # zum Snapshot passt, leerte die Liste. Neu (W-ZWEI-MERKMALE): passt
        # dafür ein Kandidat über ZWEI andere Merkmale (starker Name + Tag),
        # bleibt dieser — nie per bloßer Namensähnlichkeit springen.
        if zwei and len({_s(a.get("patientId")) or _name_norm(
                a.get("patientName"), zeitwoerter=False) for a in zwei}) == 1:
            alle = zwei
            quelle = "zwei_merkmale"
        else:
            alle = []
            quelle = "identitaet_widerspruch" if hat_terminkandidaten else "no_detail"
    elif hat_name:
        if name_ok:
            alle = name_ok
            # Nur ein tatsächlich unscharfer Name braucht die zusätzliche
            # Patienten-Rückversicherung. Ein praktisch identischer Name
            # geht direkt in die ohnehin folgende Terminbestätigung.
            quelle = (
                "nameExact"
                if all(
                    float(a.get("_nameScore") or 0) >= 0.98
                    for a in alle
                )
                else "name60"
            )
        elif zwei and len({_s(a.get("patientId")) or _name_norm(
                a.get("patientName"), zeitwoerter=False) for a in zwei}) == 1:
            # Name allein unter 60 %, aber zwei Merkmale (z. B. starker Name
            # knapp darunter + genannter Tag) lösen eindeutig auf.
            alle = zwei
            quelle = "zwei_merkmale"
        else:
            alle = []
            # Ein leerer Tag beziehungsweise eine abweichend erinnerte Uhrzeit
            # beweist NICHT, dass der Name falsch ist. Dann mit dem Namen in
            # der Patienten-Terminliste suchen; nur vorhandene fremde
            # Tageskandidaten belegen eine Namensabweichung.
            quelle = "name_unter60" if hat_terminkandidaten else "no_detail"

    alle.sort(key=lambda a: (
        -float(a.get("_nameScore") or 0),
        _s(a.get("iso")),
        _s(a.get("id")),
    ))
    dispatch = res.get("dispatch")
    log_key = f"{tag}|{quelle}|{len(alle)}"
    if dispatch and sit.get("_verwDetailGeloggtKey") != log_key:
        werkzeug = {
            "ok": True,
            "source": quelle,
            "candidateCount": len(alle),
            # merke_tool uebernimmt nur die Anzahl; keine Tagesliste und keine
            # fremden Patientendaten gelangen ins Gespraechsmanifest.
            "appointments": [{} for _ in alle],
            "dispatch": _dispatch_ohne_pii(dispatch),
        }
        merke_tool(sit, "find_appointment_by_details", werkzeug)
        outcome = "found" if alle else "empty"
        _obs(
            sit,
            "read",
            route="calendar_day_read",
            outcome=outcome,
            source=quelle,
            count=len(alle),
            dispatch=dispatch,
        )
        _obs(
            sit,
            "identity",
            outcome=outcome,
            source=quelle,
            count=len(alle),
        )
        if alle:
            _obs(
                sit,
                "found",
                outcome="found",
                source=quelle,
                count=len(alle),
            )
        sit["_verwDetailGeloggtKey"] = log_key
    return {
        "appointments": alle,
        "source": quelle,
        "dayCount": len(res.get("appointments") or []),
        "exactTime": w.get("minuteOfDay") is not None,
    }


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


def _schreibweise_zuerst(sit: dict) -> dict:
    """Gesprochener Nachname ohne Tafel: erst buchstabieren, dann suchen."""
    s = gehirn.sammler(sit)
    paar = gehirn._nachname_vor_vorname_absichern(sit, s)
    if not paar:
        paar = gehirn._buchstabier_frage(
            s,
            "Bitte nennen Sie den Nachnamen Buchstabe für Buchstabe. "
            "Wie lautet die genaue Schreibweise?",
        )
    fid, frage = paar
    s["frage"] = fid
    return {"text": frage}


def qwen_name_ausgang_aktiv() -> bool:
    """Notaus `QWEN_NAME_EINMAL=0`: Qwen-Namensfrage wie vor dem 07.10.2026."""
    return os.getenv("QWEN_NAME_EINMAL", "1").strip() != "0"


def _qwen_name_zug(sit: dict, text: str, melde: Melde,
                   neu: set[str] | frozenset = frozenset()) -> dict:
    """Zweite Lesart nur nach Ja in den Nachnamen übernehmen."""
    s = gehirn.sammler(sit)
    vorschlag = _s(sit.get("qwenNameVorschlag"))
    if (
        qwen_name_ausgang_aktiv()
        and ({"name", "nachname", "vorname"} & set(neu or ()))
        and not gehirn.ist_ja(text)
    ):
        # „Nein, ich heiße Erfeld.“ / „Nein, Jürgen.“ (Anrufe 7fbed2d9,
        # 17d53232): die Antwort trägt die Korrektur selbst — mit ihr suchen,
        # nicht den Vorschlag erneut vorlegen.
        sit["qwenNameVerbraucht"] = True
        sit.pop("qwenNameVorschlag", None)
        sit.pop("qwenNameUnklar", None)
        s["frage"] = ""
        spur.merken(sit, "qwen-name", "korrektur-im-nein")
        return _dispatch(sit, melde)
    if gehirn.ist_ja(text) and vorschlag and not gehirn.ist_nein(text):
        s["nachname"] = vorschlag
        s["name"] = f"{s.get('vorname') or ''} {vorschlag}".strip()
        s["buchstabiert"] = True
        s["nachnameCheck"] = "ja"
        s["frage"] = ""
        sit["qwenNameVerbraucht"] = True
        sit.pop("qwenNameVorschlag", None)
        return _dispatch(sit, melde)
    from bianca import buchstaben
    # W-QWEN-NAME-AUSGANG (05.10.2026): live kam auf jede Antwort, die weder
    # Ja noch Nein war, wieder „Ich habe auch … verstanden. Ist das
    # richtig?“ — bis zu sechsmal, einmal mit leerem Vorschlag. Eine neue
    # Buchstabierkette ist die Antwort; die zweite unklare Antwort gilt als
    # Nein.
    buch = buchstaben.deute(text)
    if buch and _s(buch.get("name")):
        name = _s(buch["name"])
        s["nachname"] = name[0].upper() + name[1:]
        s["name"] = f"{s.get('vorname') or ''} {s['nachname']}".strip()
        s["buchstabiert"] = True
        s["nachnameCheck"] = "offen"
        s["frage"] = "nachname_check"
        sit["qwenNameVerbraucht"] = True
        sit.pop("qwenNameVorschlag", None)
        sit.pop("qwenNameUnklar", None)
        return {"text": gehirn.nachname_check_frage(s)}
    unklar = int(sit.get("qwenNameUnklar") or 0)
    if gehirn.ist_nein(text) or not vorschlag or unklar >= 1:
        sit["qwenNameVerbraucht"] = True
        sit.pop("qwenNameVorschlag", None)
        sit.pop("qwenNameUnklar", None)
        from kern import namenslink
        namenslink.fehlversuch(sit)
        aus = namenslink.rettung_starten(sit)
        if aus is not None:
            spur.merken(sit, "namens-sms-rettung", "qwen-name")
            return aus
        return _korrektur_frage(sit)
    sit["qwenNameUnklar"] = unklar + 1
    tafel = buchstaben.vorlesen(vorschlag)
    gelesen = f"{vorschlag}: {tafel}" if tafel else vorschlag
    return {"text": (
        f"Ist {gelesen} richtig? Ein kurzes Ja oder Nein genügt."
    )}


def _schreibweise_gesperrt(sit: dict) -> bool:
    """3b: Ein konkreter Bestandstermin ist bereits gefunden/gewaehlt UND eine
    Akte gebunden — dann ist eine erneute Schreibweise-/Buchstabier-Frage
    sinnlos (Thaler dbc5e2a8: Verhoerer auf termin_ok trieb Bianca zurueck ins
    Buchstabieren, obwohl der Termin laengst feststand)."""
    gebunden = bool(
        _s(sit.get("verwKandidat"))
        or _s(sit.get("verwaltenTermin"))
        or (sit.get("anrufer") and _s(sit.get("anruferCheck")) == "ja")
    )
    if not gebunden:
        return False
    if _gewaehlt(sit):
        return True
    return len(sit.get("gefunden") or []) >= 1


def _korrektur_frage(sit: dict) -> dict:
    """W-NAMESKORREKTUR (Chef 31.08.2026, Zannes-Anruf 10:33: "der gibt zu
    schnell auf"): beim ERSTEN 'Patient nicht gefunden' nicht gleich die
    Notiz schreiben — meist hat STT den Nachnamen verhoert ("Sannes Czannis"
    statt Tzannes). Der Anrufer bekommt EINE Chance, den Nachnamen zu
    korrigieren oder zu buchstabieren; erst der zweite Fehlschlag geht den
    ehrlichen Notiz-Weg."""
    s = gehirn.sammler(sit)
    # 3b: steht der Termin bereits (Akte gebunden), nie zurueck ins
    # Buchstabieren — den gefundenen Termin erneut ansagen.
    if _schreibweise_gesperrt(sit):
        return _ansagen(sit)
    if not sit.get("qwenNameVerbraucht"):
        from kern import qwen_korrektor
        from bianca import buchstaben
        vorschlag = qwen_korrektor.namens_vorschlag(sit, s.get("nachname") or "")
        if vorschlag:
            sit["qwenNameVorschlag"] = vorschlag
            if qwen_name_ausgang_aktiv():
                # Ein Vorschlag wird genau einmal vorgelegt — auch wenn die
                # Antwort einen Weg nimmt, der `_qwen_name_zug` nie erreicht.
                sit["qwenNameVerbraucht"] = True
            s["frage"] = "qwen_name"
            tafel = buchstaben.vorlesen(vorschlag)
            wer = f"{s['vorname']} {s['nachname']}".strip() or "diesem Namen"
            gelesen = f"{vorschlag}: {tafel}" if tafel else vorschlag
            return {"text": (
                f"Unter {wer} finde ich gerade keinen Termin. "
                f"Ich habe auch {gelesen} verstanden. Ist das richtig?"
            )}
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
        # Auch MIT Vornamen noch mehrdeutig: nicht raten, aber NIE als „kein
        # Termin" sprechen (es gibt ja mehrere) — eigener Satz + Notiz (1f).
        return _mehrdeutig_notiz(sit, s["modus"])
    s["frage"] = "vorname"
    namen = []
    gesehen: set[str] = set()
    for c in sit.get("kandidaten") or []:
        if not isinstance(c, dict):
            continue
        vor = _s(c.get("firstName"))
        nach = _s(c.get("lastName")) or _s(s.get("nachname"))
        label = f"{vor} {nach}".strip()
        key = label.casefold()
        if not vor or key in gesehen:
            continue
        gesehen.add(key)
        namen.append(label)
        if len(namen) >= 3:
            break
    if len(namen) >= 2:
        if len(namen) == 2:
            wer = f"{namen[0]} oder {namen[1]}"
        else:
            wer = f"{namen[0]}, {namen[1]} oder {namen[2]}"
        return {"text": (
            f"Da habe ich {wer}. Wie ist denn Ihr Vorname?"
        )}
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
    s["frage"] = "sonst_noch"
    return {"text": _s(
        f"Ich sehe unter {wer or 'Ihrem Namen'} aktuell keinen kommenden Termin. "
        "Kann ich sonst noch etwas für Sie tun?"
    )}


def _mehrdeutig_notiz(sit: dict, modus: str) -> dict:
    """Stufe 1f: Auch MIT Vorname mehrdeutig — NIE als „kein Termin" sprechen.

    Es gibt ja mehrere Patienten, nicht keinen. Bis die Zwei-Merkmale-Abfrage
    (Stufe 2) live ist, kommt ein eigener ehrlicher Satz plus eine echte
    Rückrufnotiz; raten wird hier nie."""
    s = gehirn.sammler(sit)
    notiz_ok = _notiz_schreiben(
        sit,
        anliegen=modus if modus in {"absagen", "verschieben"} else "auskunft",
        status=("Mehrere Patienten mit gleichem Namen — telefonisch nicht "
                "eindeutig zuzuordnen. Bitte Patient prüfen und zurückrufen"),
        dock_text=("Mehrere Patienten mit gleichem Namen. "
                   "Bitte prüfen und zurückrufen."),
    )
    sit["schreibFehlerZug"] = True
    s["phase"] = "fertig"
    s["frage"] = "sonst_noch"
    spur.merken(sit, "mehrdeutig-notiz", "ok" if notiz_ok else "notiz_fehler")
    if notiz_ok:
        return {"text": (
            "Unter diesem Namen gibt es bei uns mehrere Patienten. Damit ich "
            "niemanden verwechsle, lege ich das der Praxis vor — sie meldet "
            "sich bei Ihnen. Kann ich sonst noch etwas für Sie tun?"
        )}
    return {"text": (
        "Unter diesem Namen gibt es bei uns mehrere Patienten. Damit ich "
        "niemanden verwechsle, rufen Sie dafür bitte noch einmal in der "
        "Praxis an."
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
        # Eine Ziffer fuer Ziffer RUECKBESTAETIGTE neunstellige Festnetznummer
        # (kleines Ortsnetz, Replay 53986f42: 07129 5316) ist eine echte
        # Rueckrufnummer — sonst fragt Bianca sie direkt nach dem "Ja, richtig"
        # ein zweites Mal ab.
        if roh == s["telefon"] and s.get("telefonOk") and telefon.plausibel_kurz(d):
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
                     dock_text: str = "", was: str = "") -> bool:
    """ECHTE Notiz statt leerem Versprechen: JSONL fuer die Praxis + Dock.

    ``True`` bedeutet, dass die Zeile wirklich persistent geschrieben wurde.
    Ein In-Memory-Docktext allein ist keine Evidenz fuer eine Rueckrufnotiz.
    """
    if sit.get("testNoWrite"):
        sit["testNotizUnterdrueckt"] = True
        return False
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
    geschrieben = False
    fehler = ""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with (DATA_DIR / "praxis_notizen.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
        geschrieben = True
    except OSError as exc:
        fehler = type(exc).__name__
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
    notiz_text = _s(dock_text or (
        f"{name} wollte einen Termin {s['modus']} — im Kalender nicht gefunden"
        + (f" ({hinweise})" if hinweise else "") + ". Bitte pruefen und zurueckrufen."
    ))
    if dock_text and hinweise:
        notiz_text = _s(f"{dock_text} ({hinweise})")
    vorher_persistiert = bool(sit.get("praxisNotizPersistiert"))
    sit["praxisNotizLetzterVersuchPersistiert"] = geschrieben
    if geschrieben:
        sit["praxisNotizPersistiert"] = True
        sit["praxisNotiz"] = notiz_text
        sit.pop("praxisNotizFehler", None)
    else:
        # Ein spaeter fehlgeschlagener Zusatz darf die Evidenz einer zuvor
        # wirklich persistierten Notiz nicht aus der Sitzung radieren. Der
        # aktuelle Aufrufer erhaelt trotzdem False und darf fuer DIESEN
        # Versuch keinen Erfolg behaupten.
        if not vorher_persistiert:
            sit["praxisNotizPersistiert"] = False
            sit.pop("praxisNotiz", None)
        sit["praxisNotizFehler"] = notiz_text
    merke_tool(sit, "praxis_notiz", {
        "ok": geschrieben,
        "notiert": geschrieben,
        "notiz": notiz_text,
        **({"error": fehler} if fehler else {}),
    })
    return geschrieben


def rueckruf_notiz(sit: dict, *, hinweis: str = "") -> bool:
    """Kein freier Slot im Buchungs-Angebot: 'die Praxis meldet sich' MUSS
    eine echte Spur hinterlassen (Batch s09 29.08.2026 — leeres Versprechen,
    frage klebte auf slotwahl)."""
    s = gehirn.sammler(sit)
    name = f"{s['vorname']} {s['nachname']}".strip() or "unbekannt"
    if hinweis:
        return _notiz_schreiben(
            sit, anliegen="neubuchung",
            status=f"{hinweis} — bitte zurueckrufen",
            dock_text=f"{name} wollte neu buchen — {hinweis}. Bitte zurueckrufen.",
        )
    return _notiz_schreiben(
        sit, anliegen="neubuchung",
        status="Kein freier Termin im Angebot — bitte zurueckrufen",
        dock_text=f"{name} wollte neu buchen — kein freier Termin im Angebot. Bitte zurueckrufen.",
    )


def kalender_fehler_notiz(sit: dict) -> bool:
    """Slotsuche technisch gescheitert (CF-Fehler/Timeout, auch nach dem
    zweiten Wurf): das gesprochene "die Praxis ruft zurueck" MUSS eine Notiz
    mit Wunsch und Nummer hinterlassen (W-KALENDER-FEHLER 17.09.2026 —
    Blessing 15.09.: zehn Anrufe, kein Eintrag, kein Rueckruf moeglich)."""
    s = gehirn.sammler(sit)
    name = f"{s['vorname']} {s['nachname']}".strip() or "unbekannt"
    grund = _s(s.get("grundWortlaut") or s.get("grund")) or "Termin"
    return _notiz_schreiben(
        sit, anliegen="neubuchung",
        status="Terminkalender nicht erreichbar — Termin bitte telefonisch vergeben, zurueckrufen",
        dock_text=(f"{name} wollte einen Termin ({grund}) — der Terminkalender "
                   "antwortete nicht. Bitte zurueckrufen und Termin vergeben."),
    )


def buchung_pruefen_notiz(sit: dict, *, slot_iso: str = "") -> bool:
    """HTTP-200 ohne belastbaren Read-back wird zum echten Prüf-/Rückrufvorgang."""
    s = gehirn.sammler(sit)
    name = f"{s['vorname']} {s['nachname']}".strip() or "unbekannt"
    wann = spoken_slot(slot_iso) if len(_s(slot_iso)) >= 16 else _s(slot_iso)
    return _notiz_schreiben(
        sit,
        anliegen="buchung_pruefen",
        status="Buchungsantwort nicht eindeutig rücklesbar — Termin und SMS prüfen, bitte zurückrufen",
        dock_text=(
            f"{name}: Buchung für {wann or 'den gewünschten Zeitpunkt'} war nach dem "
            "Schreiben nicht eindeutig rücklesbar. Termin und SMS prüfen, bitte zurückrufen."
        ),
    )


def buchung_fehler_notiz(sit: dict, *, slot_iso: str = "", grund_technisch: str = "") -> bool:
    """Eintragen technisch gescheitert (4xx/5xx, kein slotTaken, kein
    needs_phone): das gesprochene "die Praxis ruft Sie dazu zurück" MUSS eine
    Notiz mit dem bestaetigten Wunschtermin hinterlassen (W-BUCHUNG-TECHNIK
    17.09.2026 — Replay 53986f42: Versprechen ohne Zeile, und der naechste Zug
    lief ueber buchIntent+slotIso erneut in dieselbe Fehlermeldung)."""
    s = gehirn.sammler(sit)
    name = f"{s['vorname']} {s['nachname']}".strip() or "unbekannt"
    wann = spoken_slot(slot_iso) if len(_s(slot_iso)) >= 16 else _s(slot_iso)
    grund = _s(s.get("grundWortlaut") or s.get("grund")) or "Termin"
    technik = f" ({_s(grund_technisch)})" if _s(grund_technisch) else ""
    return _notiz_schreiben(
        sit,
        anliegen="buchung_fehler",
        status=("Eintragen technisch gescheitert — Termin bitte manuell eintragen "
                f"und zurueckrufen{technik}"),
        dock_text=(
            f"{name} hat den Termin {wann or 'zum gewünschten Zeitpunkt'} ({grund}) "
            "am Telefon bestätigt — das Eintragen ist technisch gescheitert. "
            "Bitte manuell eintragen und zurückrufen."
        ),
    )


def abgeben_notiz(sit: dict, *, was: str = "") -> bool:
    """ABGEBEN-Anliegen (W-HIRN 03.09.2026): Rueckruf-/Nachricht-Notiz OHNE
    Termin-Bezug — frueher gab es die Spur nur, wenn zufaellig keine Slots
    frei waren. Jetzt ist 'die Praxis kuemmert sich' eine eigene Loesung."""
    s = gehirn.sammler(sit)
    name = f"{s['vorname']} {s['nachname']}".strip() or "unbekannt"
    anliegen_text = _s(was) or "Rueckruf erbeten"
    return _notiz_schreiben(
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
    notiz_ok = _notiz_schreiben(sit)
    s["phase"] = "fertig"
    # Ein gescheiterter Verwaltungsweg darf nicht automatisch in BUCHEN
    # kippen. Ein neuer Termin beginnt nur auf ausdruecklichen Wunsch.
    s["frage"] = "sonst_noch"
    sit["verwAktiv"] = False
    # Marker fuer einen NEUEN Anlauf: die Suche scheiterte — haeufigste
    # Ursache ist ein verhoerter Name (live 29.08.: "Peter Möbel" statt
    # Müller). Beim Neustart wird der Name dann frisch erfragt.
    sit["verwNotFound"] = True
    if notiz_ok:
        return {"text": (
            f"Da bin ich ehrlich: Ich finde unter {wer} gerade keinen passenden Termin. "
            f"Aber keine Sorge — ich schreibe eine Notiz, und die wird {behandler} vorgelegt. "
            "Kann ich sonst noch etwas für Sie tun?"
        )}
    return {"text": (
        f"Da bin ich ehrlich: Ich finde unter {wer} gerade keinen passenden Termin. "
        "Die Rückrufnotiz konnte ich technisch nicht speichern. Bitte rufen Sie die "
        "Praxis noch einmal an."
    )}


def _termin_patient(termin: dict) -> str:
    name = _s(termin.get("patientName"))
    return f" für {name}" if name else ""


def _kandidat_patient_uebernehmen(sit: dict, termin: dict) -> None:
    """Erst NACH Rueckbestaetigung Termin-Snapshot an den Patienten binden."""
    s = gehirn.sammler(sit)
    quelle = _obs_quelle(
        sit.get("verwDetailQuelle"),
        "patientId" if _s(termin.get("patientId")) else "nameExact",
    )
    fingerprint = f"{quelle}|{_s(termin.get('id'))}"
    if sit.get("_obsVerwConfirmed") != fingerprint:
        _obs(sit, "confirmed", outcome="confirmed", source=quelle, count=1)
        sit["_obsVerwConfirmed"] = fingerprint
    if _s(termin.get("patientId")):
        s["patientId"] = _s(termin.get("patientId"))
        s["bekannt"] = True
        s["warSchonMal"] = True
    if _s(termin.get("patientLastName")):
        s["nachname"] = _s(termin.get("patientLastName"))
    if _s(termin.get("patientFirstName")):
        s["vorname"] = _s(termin.get("patientFirstName"))
        s["vornameQuelle"] = "akte"
    if _s(termin.get("patientPhone")) and not s.get("fuerWen"):
        s["aktePhone"] = _s(termin.get("patientPhone"))


def _absage_frage(sit: dict, termin: dict) -> dict:
    """Treffer bestaetigen MIT Anrede (Chef: '… Herr/Frau XY, ja?')."""
    schon = _absage_schon_versucht(sit, _s(termin.get("id")))
    if schon is not None:
        return schon
    s = gehirn.sammler(sit)
    sit["verwaltenTermin"] = _s(termin.get("id"))
    s["phase"] = "absage_bestaetigen"
    s["frage"] = "absage_ok"
    if sit.get("verwAnruferDirekt"):
        wer = gehirn.anrufer_anrede(sit)
        vorsatz = f"{wer}, " if wer else ""
        return {"text": (
            f"{vorsatz}ich habe Ihren Termin {termin.get('spoken')} gefunden. "
            "Soll ich ihn wirklich absagen?"
        )}
    wer = "" if s.get("anruferCheck") == "ja" else gehirn.anrede(s)
    zusatz = f", {wer}" if wer else ""
    return {"text": (
        f"Gefunden — {termin.get('spoken')}{_termin_patient(termin)}. "
        f"Soll ich den Termin wirklich absagen{zusatz}?"
    )}


def _verwaltung_mit_abschlussfrage_schliessen(sit: dict) -> None:
    """Fachmodus schließen, eine einzige deterministische Abschlussfrage halten."""
    s = gehirn.sammler(sit)
    s["modus"] = ""
    s["phase"] = "fertig"
    s["frage"] = "sonst_noch"
    sit["verwAbschlussOffen"] = True


# W-ABSAGE-EINMAL (07.10.2026, Blessing-Anruf 9fc1f105): die Plattform lehnte
# die Absage mit „not confirmed or already processed“ ab, Bianca versuchte
# denselben Termin dreimal und sagte dreimal „Die Praxis kümmert sich darum.“
_ABSAGE_UNBESTAETIGT = (
    "Diesen Termin kann ich hier nicht selbst absagen. Ich habe Ihre Absage "
    "für die Praxis notiert — sie trägt sie ein."
)
_ABSAGE_SCHON_NOTIERT = (
    "Ihre Absage zu diesem Termin habe ich bereits für die Praxis notiert — "
    "sie trägt sie ein."
)
# Stufe 1e: Lehnt die Plattform das Verschieben ab (400 „cannot be postponed" —
# Termin nicht bestätigt / bereits bearbeitet), ist das KEIN belegter Slot.
# Kein Alternativ-Kreisel, sondern ehrlich an die Praxis notieren.
_VERSCHIEBEN_GESPERRT = (
    "Diesen Termin kann ich hier nicht selbst verschieben. Ich habe es für die "
    "Praxis notiert — sie kümmert sich darum."
)
_VERSCHIEBEN_GESPERRT_FAIL = (
    "Diesen Termin kann ich hier nicht selbst verschieben, und auch die "
    "Rückrufnotiz konnte ich technisch nicht speichern. Bitte rufen Sie die "
    "Praxis dafür noch einmal an."
)
_ABSAGE_NICHT_MOEGLICH = (
    "Diesen Termin kann ich gerade nicht absagen. Bitte rufen Sie die Praxis "
    "dafür noch einmal an."
)


def _absage_einmal_aktiv() -> bool:
    return os.environ.get("ABSAGE_EINMAL", "1").strip() != "0"


def _absage_gescheitert(sit: dict) -> dict:
    """Termin-ID -> war die Rückrufnotiz erfolgreich? Leer bei Notaus."""
    if not _absage_einmal_aktiv():
        return {}
    g = sit.get("absageGescheitert")
    if not isinstance(g, dict):
        g = {}
        sit["absageGescheitert"] = g
    return g


def _absage_schon_versucht(sit: dict, tid: str) -> dict | None:
    """Dieselbe ID nie noch einmal gegen die Plattform — und nicht erneut
    „Soll ich ihn wirklich absagen?“ fragen."""
    gescheitert = _absage_gescheitert(sit)
    if not tid or tid not in gescheitert:
        return None
    sit["schreibFehlerZug"] = True
    _verwaltung_mit_abschlussfrage_schliessen(sit)
    spur.merken(sit, "absage-einmal", "wiederholt")
    return {"text": (
        (_ABSAGE_SCHON_NOTIERT if gescheitert[tid] else _ABSAGE_NICHT_MOEGLICH)
        + " Kann ich sonst noch etwas für Sie tun?"
    )}


def _absage_unbestaetigt(res: dict) -> bool:
    try:
        roh = json.dumps(res, default=str, ensure_ascii=False).lower()
    except Exception:
        roh = str(res).lower()
    return "not confirmed" in roh


def _absagen(sit: dict, melde: Melde) -> dict:
    if sit.get("testNoWrite"):
        s = gehirn.sammler(sit)
        s["phase"] = "fertig"
        s["frage"] = ""
        return {"text": "Der Testlauf ist beendet; der Termin wurde nicht abgesagt."}
    s = gehirn.sammler(sit)
    termin = _gewaehlt(sit)
    _kandidat_patient_uebernehmen(sit, termin)
    ctx = _ctx(sit)
    ctx["appointmentDate"] = _s(
        termin.get("iso") or termin.get("startIso") or termin.get("date"))
    gescheitert = _absage_gescheitert(sit)
    tid = _s(termin.get("id"))
    schon = _absage_schon_versucht(sit, tid)
    if schon is not None:
        return schon
    if melde:
        melde("cancel_appointment")
    res = kal.cancel_by_id(sit["tenant"], ctx, tid)
    merke_tool(sit, "cancel_appointment", res)
    _obs(
        sit,
        "write",
        route="cancel_write",
        outcome="write_ok" if res.get("ok") else "write_error",
        source=_obs_quelle(sit.get("verwDetailQuelle"), "nameExact"),
        count=1,
        dispatch=res.get("dispatch"),
    )
    if res.get("ok"):
        _arzt_uebernehmen(sit, termin)
        sit["gefundenKey"] = ""  # Bestand hat sich geaendert
        sit["gefunden"] = []
        sit["verwaltenTermin"] = ""
        _verw_reset(sit)
        if _s((sit.get("booking") or {}).get("appointmentId")) == _s(termin.get("id")):
            sit["booking"]["appointmentId"] = ""  # der frisch gebuchte ist weg
        _verwaltung_mit_abschlussfrage_schliessen(sit)
        wann = _s(termin.get("spoken")) or "wie besprochen"
        return {
            "text": f"Erledigt — der Termin {wann} ist abgesagt. "
                    "Kann ich sonst noch etwas für Sie tun?",
            "book": {"cancelled": True, "spoken": res.get("spoken") or ""},
        }
    unbestaetigt = _absage_unbestaetigt(res)
    notiz_ok = _notiz_schreiben(
        sit,
        anliegen="absagen",
        status=("Absage gewünscht — Termin noch nicht bestätigt, Plattform lässt "
                "keine Absage zu. Bitte austragen und zurückrufen")
        if unbestaetigt else
        "Absage technisch fehlgeschlagen — bitte prüfen und zurückrufen",
        dock_text="Absage technisch fehlgeschlagen. Bitte prüfen und zurückrufen.",
    )
    if tid and _absage_einmal_aktiv():
        gescheitert[tid] = bool(notiz_ok)
    sit["schreibFehlerZug"] = True
    _verwaltung_mit_abschlussfrage_schliessen(sit)
    if unbestaetigt and notiz_ok and _absage_einmal_aktiv():
        return {"text": _ABSAGE_UNBESTAETIGT + " Kann ich sonst noch etwas für Sie tun?"}
    if not notiz_ok:
        return {"text": (
            "Die Absage hat gerade nicht geklappt, und auch die Rückrufnotiz "
            "konnte ich technisch nicht speichern. Bitte rufen Sie die Praxis "
            "noch einmal an."
        )}
    return {"text": (
        (res.get("spoken") or
         "Die Absage hat gerade nicht geklappt. Die Praxis kümmert sich darum.")
        + " Kann ich sonst noch etwas für Sie tun?"
    )}


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
        return echte if len(echte) == 2 else []
    return []


def _mehrfach_absage_start(sit: dict, auswahl: list[dict]) -> dict:
    """EINE gemeinsame Rueckbestaetigung fuer mehrere Termine (nie still nur
    einen absagen)."""
    s = gehirn.sammler(sit)
    patienten = {
        _s(a.get("patientId"))
        or _name_norm(a.get("patientName"), zeitwoerter=False)
        for a in auswahl
    }
    patienten.discard("")
    if len(patienten) > 1:
        # Eine Sammelaktion über verschiedene Patienten wäre selbst nach
        # „alle“ zu riskant. Erst die Patientenidentität klären.
        sit["mehrfachAbsage"] = []
        s["phase"] = ""
        return _nachname_frage(
            sit,
            "Die Termine gehören zu verschiedenen Patienten. "
            "Für welchen Patienten soll ich absagen?",
        )
    sit["mehrfachAbsage"] = [
        {
            "id": _s(a.get("id")),
            "iso": _s(a.get("iso") or a.get("startIso") or a.get("date")),
            "spoken": _s(a.get("spoken")),
            "patientId": _s(a.get("patientId")),
            "patientName": _s(a.get("patientName")),
        }
        for a in auswahl
    ]
    s["phase"] = "mehrfach_bestaetigen"
    s["frage"] = "mehrfach_ok"
    liste = _liste_sprechbar([
        {
            **a,
            "spoken": (
                f"{_s(a.get('spoken'))}{_termin_patient(a)}"
            ).strip(),
        }
        for a in auswahl
    ])
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
        ctx = _ctx(sit)
        ctx["appointmentDate"] = _s(p.get("iso"))
        res = kal.cancel_by_id(sit["tenant"], ctx, aid)
        merke_tool(sit, "cancel_appointment", res)
        _obs(
            sit,
            "write",
            route="cancel_write",
            outcome="write_ok" if res.get("ok") else "write_error",
            source=_obs_quelle(sit.get("verwDetailQuelle"), "nameExact"),
            count=1,
            dispatch=res.get("dispatch"),
        )
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
    _verwaltung_mit_abschlussfrage_schliessen(sit)
    teile: list[str] = []
    if erfolg:
        teile.append("Erledigt — abgesagt sind: " + _fuegen(erfolg) + ".")
    if fehler:
        fehl_text = _fuegen(fehler)
        notiz_ok = _notiz_schreiben(
            sit,
            anliegen="mehrfach_absagen",
            status="Mindestens eine Absage technisch fehlgeschlagen — bitte prüfen und zurückrufen",
            dock_text=(
                f"Mehrfach-Absage teilweise fehlgeschlagen: {fehl_text}. "
                "Bitte Termine prüfen und zurückrufen."
            ),
        )
        if notiz_ok:
            teile.append(
                f"Bei {fehl_text} hat es gerade nicht geklappt — "
                "ich habe der Praxis dazu eine Rückrufnotiz hinterlassen."
            )
        else:
            teile.append(
                f"Bei {fehl_text} hat es gerade nicht geklappt. "
                "Die Rückrufnotiz konnte ich technisch nicht speichern; "
                "bitte rufen Sie die Praxis noch einmal an."
            )
    if not teile:
        # Sollte nie passieren (Warteschlange war leer): ehrlich bleiben.
        return {"text": "Da ist gerade nichts zum Absagen gewesen. "
                        "Kann ich sonst noch etwas für Sie tun?"}
    teile.append("Kann ich sonst noch etwas für Sie tun?")
    book = {"cancelled": bool(erfolg)}
    if letzter_termin:
        book["spoken"] = _s(letzter_termin.get("spoken"))
    return {"text": " ".join(teile), "book": book}


def _fuegen(teile: list[str]) -> str:
    teile = [_s(x) for x in teile if _s(x)]
    if len(teile) > 1:
        return ", ".join(teile[:-1]) + " und " + teile[-1]
    return teile[0] if teile else ""


def _verschieb_wunsch_frage(
    sit: dict, termin: dict, melde: Melde = None
) -> dict:
    """Ohne Vorab-Verhör direkt den frühestmöglichen neuen Termin anbieten."""
    s = gehirn.sammler(sit)
    sit["verwaltenTermin"] = _s(termin.get("id"))
    s["wunsch"] = {"erstmoeglich": True}
    s["wunschText"] = "frühestmöglich"
    s["phase"] = ""
    s["frage"] = ""
    aus = _verschieb_angebot(sit, melde)
    if _s(aus.get("text")) and s.get("phase") == "verschieb_angebot":
        if sit.get("verwAnruferDirekt"):
            wer = gehirn.anrufer_anrede(sit)
            vorsatz = f"{wer}, " if wer else ""
            gefunden = f"{vorsatz}ich habe Ihren Termin {termin.get('spoken')} gefunden. "
        else:
            gefunden = (
                f"Gefunden — es geht um den Termin {termin.get('spoken')}"
                f"{_termin_patient(termin)}. "
            )
        aus["text"] = gefunden + _s(aus["text"])
    return aus


def _verschieb_angebot(sit: dict, melde: Melde) -> dict:
    """Freie Zeiten im Kalender des Bestandstermins suchen, Wunsch beachten."""
    s = gehirn.sammler(sit)
    if s.get("phase") == "verschieb_angebot":
        _ablehnte_slots_sperren(sit)
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
        sit["offered"] = []
        notiz_ok = _notiz_schreiben(
            sit,
            anliegen="verschieben",
            status="Terminkalender nicht erreichbar — bitte zum Verschieben zurückrufen",
            dock_text="Terminkalender beim Verschieben nicht erreichbar. Bitte zurückrufen.",
        )
        _verwaltung_mit_abschlussfrage_schliessen(sit)
        if not notiz_ok:
            return {"text": (
                "Der Terminkalender antwortet gerade nicht, und die Rückrufnotiz "
                "konnte ich technisch nicht speichern. Bitte rufen Sie die Praxis "
                "noch einmal an."
            )}
        return {"text": (
            "Der Terminkalender antwortet gerade nicht. "
            "Ich habe der Praxis dazu eine Rückrufnotiz hinterlassen. "
            "Kann ich sonst noch etwas für Sie tun?"
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
    if picked["slots"]:
        picked = {**picked, "slots": slots_mit_abstand(picked["slots"])}
    if not picked["slots"] and s["wunsch"] and not slot_wunsch_hart(s["wunsch"]):
        # Wunsch (z. B. konkrete Uhrzeit) passt nirgends: naechstliegende
        # Zeiten zeigen statt in der Wunsch-Schleife zu haengen. Ausdrücklich
        # abgelehnte Tage/Uhrzeiten sind dagegen hart und dürfen im
        # Verschiebe-Fallback nie wieder erscheinen.
        picked = pick_slots(isos)
        if picked["slots"]:
            picked = {**picked, "slots": slots_mit_abstand(picked["slots"])}
            hinweis = hinweis or "Genau zu dieser Zeit ist nichts frei. "
    if not picked["slots"]:
        # W-LEERSUCH-WACHE (01.10.2026, Anruf 4b86b5dd): dieselbe erfolglose
        # Verschiebe-Suche lief fuenfmal mit wortgleicher "nichts Freies"-
        # Ansage — der Anrufer drehte sich im Kreis. Eine identische Leersuche
        # (gleicher Kalender, Motiv, Startdatum, Wunsch, Richtung) wird NICHT
        # wiederholt; nach hoechstens zwei verschiedenen Leersuchen bieten wir
        # einmal ehrlich das Scheitern an und hinterlassen eine echte
        # Rueckrufnotiz. Nur ein wirklich erweiterter Wunsch sucht erneut.
        sig = "|".join([
            such_ctx.get("calendarId", ""),
            such_ctx.get("visitMotiveId", ""),
            _s(gehirn.start_datum(s)),
            json.dumps(s.get("wunsch"), ensure_ascii=False, sort_keys=True)
            if isinstance(s.get("wunsch"), dict) else "",
            _s(sit.get("verschiebRichtung")),
        ])
        voriges = _s(sit.get("verschiebLeerSig"))
        n = int(sit.get("verschiebLeerN") or 0)
        identisch = bool(voriges) and sig == voriges
        if not identisch:
            sit["verschiebLeerSig"] = sig
            sit["verschiebLeerN"] = n + 1
        if identisch or (n + 1) >= 3:
            sit["offered"] = []
            notiz_ok = bool(sit.get("praxisNotizPersistiert"))
            if not sit.get("praxisNotiz"):
                notiz_ok = _notiz_schreiben(
                    sit,
                    anliegen="verschieben",
                    status=("Kein passender Verschiebe-Termin gefunden — bitte "
                            "zum Verschieben zurückrufen"),
                    dock_text=("Verschieben: kein passender Termin frei. "
                               "Bitte zurückrufen."),
                )
            _verwaltung_mit_abschlussfrage_schliessen(sit)
            if not notiz_ok:
                return {"text": (
                    "Zu Ihrem Wunsch finde ich gerade keinen freien Termin, "
                    "und die Rückrufnotiz konnte ich technisch nicht speichern. "
                    "Bitte rufen Sie die Praxis noch einmal an."
                )}
            return {"text": (
                "Zu Ihrem Wunsch finde ich im Moment leider keinen passenden "
                "freien Termin. Ich habe der Praxis eine Rückrufnotiz "
                "hinterlassen, damit man sich bei Ihnen meldet. "
                "Kann ich sonst noch etwas für Sie tun?"
            )}
        s["phase"] = "verschieb_wunsch"
        s["frage"] = "wunsch"
        sit["offered"] = []
        return {"text": (
            "Zu diesem Wunsch finde ich gerade nichts Freies. "
            "Ginge auch ein anderer Tag oder eine andere Tageszeit?"
        )}
    # Erfolgreiche Suche: Leersuch-Zaehler zuruecksetzen.
    sit.pop("verschiebLeerSig", None)
    sit.pop("verschiebLeerN", None)
    kandidaten = list(picked["slots"])
    sichtbar = kandidaten[:1]
    offered = [{"iso": x["iso"], "spoken": spoken_slot(x["iso"])} for x in sichtbar]
    sit["slotAlternativen"] = [
        {"iso": x["iso"], "spoken": spoken_slot(x["iso"])}
        for x in kandidaten[1:]
    ]
    picked = {**picked, "slots": sichtbar}
    zuletzt = [o.get("iso") for o in sit.get("offered") or []] if s["phase"] == "verschieb_angebot" else None
    sit["offered"] = offered
    s["phase"] = "verschieb_angebot"
    s["frage"] = "slotwahl"
    if offered and zuletzt == [o["iso"] for o in offered]:
        # Wiederhol-Wache (wie in flow._angebot): gleiches Ergebnis ehrlich
        # ansagen statt die Liste wortgleich zu wiederholen.
        termin_text = _s(offered[0].get("spoken"))
        return {
            "text": (
                hinweis
                + f"Näher an Ihrem Wunsch habe ich leider nichts — es bleibt bei {termin_text}. "
                "Passt Ihnen dieser Termin?"
            )
        }
    return {"text": hinweis + spoken_offer(picked["slots"], wish_matched=picked["wishMatched"])}


def _verschieb_readback(sit: dict, neu_iso: str) -> dict:
    s = gehirn.sammler(sit)
    termin = _gewaehlt(sit)
    s["slotIso"] = neu_iso
    s["phase"] = "verschieb_bestaetigen"
    s["frage"] = "verschieb_ok"
    return {"text": (
        f"Dann verschiebe ich den Termin {termin.get('spoken')}"
        f"{_termin_patient(termin)} "
        f"auf {spoken_slot(neu_iso)}. Passt das so?"
    )}


def _verschieben(sit: dict, melde: Melde) -> dict:
    if sit.get("testNoWrite"):
        s = gehirn.sammler(sit)
        s["phase"] = "fertig"
        s["frage"] = ""
        return {"text": "Der Testlauf ist beendet; der Termin wurde nicht verschoben."}
    s = gehirn.sammler(sit)
    if int(sit.get("moveFails") or 0) >= 2:
        # Harte Schreibgrenze auch fuer alte/direkte Aufrufer: Nach zwei
        # echten Verschiebeversuchen niemals einen dritten Write senden.
        notiz_ok = bool(sit.get("praxisNotizPersistiert"))
        if not sit.get("praxisNotiz"):
            notiz_ok = _notiz_schreiben(
                sit,
                anliegen="verschieben",
                status=(
                    "Zwei Verschiebeversuche fehlgeschlagen — bitte Termin "
                    "prüfen und zurückrufen"
                ),
                dock_text=(
                    "Verschieben nach zwei Versuchen beendet. "
                    "Bitte prüfen und zurückrufen."
                ),
            )
        _verwaltung_mit_abschlussfrage_schliessen(sit)
        if not notiz_ok:
            return {"text": (
                "Die beiden Verschiebeversuche waren leider nicht zuverlässig. "
                "Die Rückrufnotiz konnte ich technisch nicht speichern; bitte rufen "
                "Sie die Praxis noch einmal an."
            )}
        return {"text": (
            "Die beiden Verschiebeversuche waren leider nicht zuverlässig. "
            "Die Praxis meldet sich bei Ihnen. Kann ich sonst noch etwas für "
            "Sie tun?"
        )}
    termin = _gewaehlt(sit)
    _kandidat_patient_uebernehmen(sit, termin)
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
    _obs(
        sit,
        "write",
        route="move_write",
        outcome="write_ok" if (
            res.get("ok") and (res.get("moved") or res.get("dryRun"))
        ) else "write_error",
        source=_obs_quelle(sit.get("verwDetailQuelle"), "nameExact"),
        count=1,
        dispatch=res.get("dispatch"),
    )
    if res.get("ok") and (res.get("moved") or res.get("dryRun")):
        _arzt_uebernehmen(sit, termin)
        sit["gefundenKey"] = ""
        sit["gefunden"] = []
        sit["verwaltenTermin"] = ""
        _verw_reset(sit)
        # Anliegen ERLEDIGT: Modus schliessen und Angebote verwerfen — sonst
        # bot der Fluss nach "Das war's, danke" WIEDER Zeiten an (live 27.08.
        # 15:22: Re-Dispatch ueber den geleerten Termin-Cache).
        _verwaltung_mit_abschlussfrage_schliessen(sit)
        sit["offered"] = []
        sit["verschiebRichtung"] = ""
        return {
            "text": (res.get("spoken") or "Der Termin ist verschoben.")
                    + " Kann ich sonst noch etwas für Sie tun?",
            "book": {"moved": True, "slotIso": res.get("slotIso") or "", "spoken": res.get("spoken") or ""},
        }
    if res.get("terminGesperrt"):
        # Plattform-Ablehnung (nicht bestätigt / bereits bearbeitet): ehrlich,
        # kein Alternativ-Kreisel. Der Satz kommt nur, wenn die Notiz steht.
        notiz_ok = _notiz_schreiben(
            sit,
            anliegen="verschieben",
            status=("Verschieben gewünscht — Plattform lässt es nicht zu "
                    "(nicht bestätigt / bereits bearbeitet). Bitte prüfen und "
                    "zurückrufen"),
            dock_text=("Verschieben von der Plattform abgelehnt. "
                       "Bitte prüfen und zurückrufen."),
        )
        sit["schreibFehlerZug"] = True
        s["slotIso"] = ""
        sit["slotVorrat"] = []
        sit["offered"] = []
        sit["verschiebRichtung"] = ""
        _verwaltung_mit_abschlussfrage_schliessen(sit)
        spur.merken(sit, "verschieben-gesperrt", "ok" if notiz_ok else "notiz_fehler")
        if notiz_ok:
            return {"text": _VERSCHIEBEN_GESPERRT + " Kann ich sonst noch etwas für Sie tun?"}
        return {"text": _VERSCHIEBEN_GESPERRT_FAIL}
    if res.get("slotTaken"):
        fail_iso = (
            _s(res.get("blockedIso"))
            or _s(res.get("slotIso"))
            or _s(s.get("slotIso"))
        )
        gesperrt = list(sit.get("slotGesperrt") or [])
        if fail_iso and fail_iso not in gesperrt:
            gesperrt.append(fail_iso)
        sit["slotGesperrt"] = gesperrt
        # Alten Vorrat auf beiden Ebenen sofort verwerfen. Die vom Kalender
        # gelieferten Alternativen stammen bereits aus einer frischen Suche.
        sit["slotVorrat"] = []
        sit["offered"] = []
        ctx["slotVorrat"] = []
        ctx["slotGesperrt"] = list(gesperrt)
        write_attempted = res.get("writeAttempted") is not False
        fails = int(sit.get("moveFails") or 0) + (1 if write_attempted else 0)
        sit["moveFails"] = fails
        s["slotIso"] = ""
        if fails >= 2:
            notiert = _notiz_schreiben(
                sit,
                anliegen="verschieben",
                status=(
                    "Zwei Verschiebeversuche durch belegte Zielzeiten fehlgeschlagen "
                    "— bitte Termin prüfen und zurückrufen"
                ),
                dock_text=(
                    "Verschieben nach zwei belegten Zielzeiten beendet. "
                    "Bitte prüfen und zurückrufen."
                ),
            )
            _verwaltung_mit_abschlussfrage_schliessen(sit)
            text = (
                "Die beiden Ausweichtermine sind leider nicht mehr frei. "
                "Ich habe der Praxis eine Rückrufnotiz hinterlassen; sie meldet "
                "sich mit einem neuen Termin bei Ihnen."
                if notiert else
                "Die beiden Ausweichtermine sind leider nicht mehr frei. "
                "Die Rückrufnotiz konnte ich technisch nicht speichern; bitte "
                "rufen Sie die Praxis noch einmal an."
            )
            return {"text": text + " Kann ich sonst noch etwas für Sie tun?"}
    if res.get("slots"):
        sit["offered"] = res["slots"]
        s["phase"] = "verschieb_angebot"
        s["frage"] = "slotwahl"
        return {"text": res.get("spoken") or "Der Platz ist gerade weg — ich habe Alternativen."}
    notiz_ok = _notiz_schreiben(
        sit,
        anliegen="verschieben",
        status="Verschieben technisch fehlgeschlagen — bitte prüfen und zurückrufen",
        dock_text="Verschieben technisch fehlgeschlagen. Bitte prüfen und zurückrufen.",
    )
    _verwaltung_mit_abschlussfrage_schliessen(sit)
    if not notiz_ok:
        return {"text": (
            "Das Verschieben hat gerade nicht geklappt, und auch die Rückrufnotiz "
            "konnte ich technisch nicht speichern. Bitte rufen Sie die Praxis "
            "noch einmal an."
        )}
    return {"text": (
        (res.get("spoken") or
         "Das Verschieben hat gerade nicht geklappt. "
         "Ich habe der Praxis dazu eine Rückrufnotiz hinterlassen.")
        + " Kann ich sonst noch etwas für Sie tun?"
    )}


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
    if termine:
        _obs(
            sit,
            "announced",
            route="appointment_announcement",
            outcome="announced",
            source=_obs_quelle(sit.get("verwDetailQuelle"), "nameExact"),
            count=len(termine),
        )
    if len(termine) == 1:
        _arzt_uebernehmen(sit, termine[0])
        sit["verwaltenTermin"] = _s(termine[0].get("id"))
        # Gespraechsnotiz beim Auflegen an DIESEN Termin haengen.
        sit.setdefault("booking", {})["appointmentId"] = _s(termine[0].get("id"))
        wort = _termin_sprechbar(termine[0])
        anrede = gehirn.anrufer_anrede(sit) if sit.get("verwAnruferDirekt") else ""
        if anrede:
            if vorsatz:
                kern = (f"{vorsatz}{wort}." if vorsatz.endswith(": ")
                        else f"{vorsatz}Ihr nächster Termin: {wort}.")
                kern_text = f"{anrede}, {kern[:1].lower()}{kern[1:]}"
            else:
                kern_text = f"{anrede}, ich habe Ihren Termin gefunden: {wort}."
        else:
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
# 3a: wie oft eine unklare Antwort auf termin_ok die Folgefrage wiederholt,
# bevor der normale Weg (Hirn/Modell) uebernimmt.
_TERMIN_OK_WDH_MAX = 2
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
    r"wiederh[oö]ren|wiedersehen|\btsch[uü]s{0,2}\b|\bciao\b|das\s+(?:war'?s|wars)|"
    r"nichts\s+weiter|sch[oö]nen\s+(?:tag|abend|feierabend)|"
    # 3a (Anruf 5e30be95): breitere Abschiedsformen, damit die termin_ok-Frage
    # nicht endlos wiederholt wird, wenn der Anrufer sich klar verabschiedet.
    r"bis\s+(?:dann|denn|bald|später|spaeter|zum\s+termin)|mach(?:en\s+sie'?s|t'?s|'?s)\s+gut|"
    r"das\s+(?:ist|war)\s+(?:dann\s+)?alles|mehr\s+brauch\w*\s+ich\s+nicht|"
    r"(?:dann\s+)?reicht\s+(?:das|mir)|war\s+alles",
    re.I,
)
# 3a: Erkennung eines BLOSSEN Wochentags ("Montag?", "am Donnerstag") als
# ganze Antwort — dann kommt ein kurzer Filtersatz statt einer neuen Ansage.
_NUR_WOCHENTAG_FUELL_RE = re.compile(
    r"\b(?:ja|nein|am|der|den|ist|war|und|also|äh|ähm|hm|mhm|denn|eigentlich|"
    r"vielleicht|doch|mal|noch|so)\b",
    re.I,
)


def _nur_wochentag(t: str) -> int | None:
    """Antwort ist (abzüglich Füllwörter) nur ein Wochentag -> Index, sonst None."""
    rest = _NUR_WOCHENTAG_FUELL_RE.sub(" ", _s(t).casefold())
    gefunden = None
    for idx, cre in WEEKDAYS:
        for m in cre.finditer(rest):
            if gefunden is not None and gefunden != idx:
                return None
            gefunden = idx
            rest = rest[:m.start()] + " " + rest[m.end():]
    if gefunden is None:
        return None
    if re.sub(r"[^\wäöüß]+", "", rest):
        return None  # noch anderer Inhalt -> kein blosser Wochentag
    return gefunden


# Index-Schema wie kern.slots.WEEKDAYS/_weekday_of: Mo=1 .. Sa=6, So=0.
_WOCHENTAG_NAME = {
    1: "Montag", 2: "Dienstag", 3: "Mittwoch", 4: "Donnerstag",
    5: "Freitag", 6: "Samstag", 0: "Sonntag",
}


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
# 3b (Thaler-Anruf dbc5e2a8): bekannte STT-Verhoerer eines Verschiebe-Wunsches
# ("verscheib...", "verschie..."). Ein "Ja" MIT so einem Stamm ist nie
# Zustimmung zum Bestandstermin, sondern ein (verhoerter) Aenderungswunsch —
# dann wird nachgehakt statt "passt" angenommen.
_VERHOERER_AENDERN_RE = re.compile(r"\bver\s?sch(?:eib|ie)\w*", re.I)
_ABSCHIED_TEXT = "Sehr gerne. Dann wünsche ich Ihnen einen schönen Tag — auf Wiederhören!"

# "Beide/alle absagen" (W-MEHRFACH-ABSAGE 15.09.2026): der Anrufer meint MEHR
# als einen der vorgelesenen Termine. NUR beim Absagen sinnvoll (zwei Termine
# lassen sich nicht auf denselben neuen Slot verschieben).
_ALLE_RE = re.compile(r"\b(?:alle|sämtliche|saemtliche)\b", re.I)
_BEIDE_RE = re.compile(r"\bbeide[nr]?\b|\bboth\b", re.I)
_ERSTEN_ZWEITEN_RE = re.compile(
    r"(?:den\s+)?ersten\s+und\s+(?:den\s+)?zweiten", re.I,
)
_BESTAETIGUNG_WIDERSPRUCH_RE = re.compile(
    r"\b(?:aber|allerdings|doch\s+nicht|nicht|kein\w*|falsch|"
    r"stimmt\s+nicht|ander\w*|korrig\w*|stattdessen|sondern)\b",
    re.I,
)


def _bestaetigung_eindeutig(text: str, frage: str = "absage_ok") -> bool:
    """Nur ein uneingeschränktes Ja darf einen Kalender-Write auslösen.

    ``ist_ja`` erkennt absichtlich auch natürliche Satzanfänge. Bei
    destruktiven Aktionen reicht das nicht: „Ja, aber nicht mein Termin“
    ist ein Widerspruch und muss ohne Write in der Rückfrage bleiben.
    """
    t = _s(text)
    return bool(
        gehirn.ja_nein_entscheidung(t, frage) == "ja"
        and not _BESTAETIGUNG_WIDERSPRUCH_RE.search(t)
    )


def _ablehnung_eindeutig(text: str, frage: str = "absage_ok") -> bool:
    """Natürlich formuliertes Nein im selben getaggten Entscheidungsrahmen."""
    return gehirn.ja_nein_entscheidung(_s(text), frage) == "nein"


def _bestaetigung_unklar_text(aktion: str) -> dict:
    return {"text": (
        "Dann ändere ich noch nichts. "
        f"Soll ich genau {aktion} — passt das so? "
        "Bitte antworten Sie eindeutig mit Ja oder Nein."
    )}


def _bestaetigung_unklar(
    sit: dict,
    aktion: str,
    *,
    schluessel: str,
) -> dict:
    """Destruktive Bestätigungen bleiben endlich und schreiben niemals ohne Ja."""
    stand = sit.get("verwBestaetigungUnklar")
    if not isinstance(stand, dict):
        stand = {}
        sit["verwBestaetigungUnklar"] = stand
    n = int(stand.get(schluessel) or 0) + 1
    stand[schluessel] = n
    if n < 2:
        return _bestaetigung_unklar_text(aktion)

    s = gehirn.sammler(sit)
    s["slotIso"] = ""
    sit["verwaltenTermin"] = ""
    sit["mehrfachAbsage"] = []
    sit["gefunden"] = []
    sit["offered"] = []
    _verw_reset(sit)
    _verwaltung_mit_abschlussfrage_schliessen(sit)
    return {"text": (
        "Ohne ein klares Ja ändere ich keinen Termin. "
        "Der bisherige Termin bleibt unverändert. "
        "Kann ich sonst noch etwas für Sie tun?"
    )}


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
    verwaltung_abgeschlossen = (
        frage == "sonst_noch"
        and s.get("phase") == "fertig"
        and (
            s.get("modus") in _MODI
            or bool(sit.get("verwAbschlussOffen"))
        )
    )

    def verwaltung_schliessen() -> None:
        if verwaltung_abgeschlossen:
            s["modus"] = ""
            sit.pop("verwAbschlussOffen", None)

    # Ein Modus-Wechsel (Hirn/einsammeln: "dann verschieben Sie ihn bitte")
    # laeuft in die bestehende Absage-/Verschiebe-Strecke — Frage schliessen.
    if ((s["modus"] != "auskunft"
         and not (frage == "sonst_noch" and s.get("phase") == "fertig"))
            or "modus" in neu):
        s["frage"] = ""
        return None
    kurz = len(t.split()) <= 4
    aendern = bool(_VERSCHIEB_WUNSCH_RE.search(t) or _ABSAGE_WUNSCH_RE.search(t))
    # 3b: Verhoerer-Stamm ("verscheib") schließt eine "passt"-Deutung aus.
    verhoerer_aendern = bool(_VERHOERER_AENDERN_RE.search(t))
    passt = not aendern and not verhoerer_aendern and _ist_passt(t, sit.get("gefunden") or [])
    nein = gehirn.ist_nein(t) and not passt
    ja = gehirn.ist_ja(t) and not nein and not verhoerer_aendern
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
        if verwaltung_abgeschlossen and {"name", "nachname", "vorname"} & neu:
            # Namenskorrektur nach einer fehlgeschlagenen Suche ist ein neuer
            # Suchbeleg, keine Antwort auf "sonst noch?". Den Absage-Modus
            # deshalb für den bewährten Korrekturpfad offen lassen.
            s["frage"] = ""
            return None
        if _ABSCHIED_RE.search(t) or passt or (nein and kurz):
            s["frage"] = ""
            verwaltung_schliessen()
            return {"text": _ABSCHIED_TEXT, "hangup": abschied.an()}
        if ja and kurz:
            s["frage"] = ""
            verwaltung_schliessen()
            return {"text": "Gerne — was kann ich noch für Sie tun?"}
        aus = _nachfrage_zeitraum()
        if aus is not None:
            return aus
        s["frage"] = ""
        verwaltung_schliessen()
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
    if verhoerer_aendern:
        # 3b: "Ja, verscheiben" (Verhoerer) -> nachhaken, nie als Zustimmung.
        s["frage"] = "termin_aendern"
        return {"text": "Möchten Sie den Termin verschieben oder absagen?"}
    if passt or (ja and kurz):
        # VOR dem Abschied pruefen: "Danke, passt so." ist Zustimmung, kein
        # Auflegen (_ABSCHIED_RE faengt jedes fuehrende "Danke").
        sit.pop("verwTerminOkWdh", None)
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
    # 3a (Anruf 5e30be95): ein BLOSSER Wochentag ("Montag?") ist keine neue
    # Ansage, sondern eine Nachfrage zum gefundenen Termin — kurzer Filtersatz,
    # die Frage bleibt offen.
    wtag = _nur_wochentag(t)
    termine_eins = sit.get("gefunden") or []
    if wtag is not None and len(termine_eins) == 1:
        iso = _s(termine_eins[0].get("iso"))
        name = _WOCHENTAG_NAME.get(wtag, "")
        if len(iso) >= 10 and name:
            wort = _termin_sprechbar(termine_eins[0])
            if _weekday_of(iso[:10]) == wtag:
                return {"text": f"Ja, Ihr Termin ist am {name} — {wort}. Passt der so?"}
            return {"text": (
                f"Nein, am {name} haben Sie keinen Termin. Ihr Termin ist {wort}. "
                f"Passt der so, oder möchten Sie ihn verschieben oder absagen?"
            )}
    aus = _nachfrage_zeitraum()
    if aus is not None:
        return aus
    # 3a: eine unklare Antwort fuehrt NICHT an Fortsetzungsanker/Modell — die
    # Folgefrage wird (umformuliert vom Wiederholungs-Waechter) wiederholt. Nur
    # nach mehreren unklaren Antworten (Deckel) uebernimmt der normale Weg.
    wdh = int(sit.get("verwTerminOkWdh") or 0) + 1
    if wdh <= _TERMIN_OK_WDH_MAX:
        sit["verwTerminOkWdh"] = wdh
        return {"text": "Möchten Sie den Termin so lassen, verschieben oder absagen?"}
    sit.pop("verwTerminOkWdh", None)
    # Neues Anliegen/Zwischenfrage: Hirn bzw. Modell uebernimmt.
    s["frage"] = ""
    return None


def _bestaetigen(sit: dict, termin: dict, melde: Melde) -> dict:
    """DER Termin steht fest: Absage rueckfragen bzw. Verschieben starten."""
    s = gehirn.sammler(sit)
    if sit.get("verwDetailQuelle"):
        sit["verwKandidat"] = _s(termin.get("id"))
    if (
        sit.get("verwDetailQuelle") == "name60"
        and not sit.pop("_verwName60Bestaetigt", False)
    ):
        # 60 Prozent sind bewusst nur ein Kandidat, nie Identitätsbeweis.
        # Vor Ansage, Verschiebesuche oder Absage zuerst Patient UND Termin
        # ausdrücklich rückversichern.
        sit["verwaltenTermin"] = _s(termin.get("id"))
        sit["_verwName60Danach"] = "termin"
        s["phase"] = "verw_patient_bestaetigen"
        s["frage"] = "verw_patient_ok"
        patient = _s(termin.get("patientName")) or _s(
            f"{_s(termin.get('patientFirstName'))} "
            f"{_s(termin.get('patientLastName'))}"
        )
        patient_text = f" für {patient}" if patient else ""
        return {"text": (
            "Der Name passt ähnlich, aber ich möchte nichts verwechseln. "
            f"Ist es der Termin {termin.get('spoken')}{patient_text}?"
        )}
    if s["modus"] == "auskunft":
        return _ansagen(sit)
    if s["modus"] == "absagen":
        return _absage_frage(sit, termin)
    sit["verwaltenTermin"] = _s(termin.get("id"))
    _arzt_uebernehmen(sit, termin, fest=True)
    if s["wunsch"]:
        _verschieb_datum_auf_bestand_beziehen(sit, termin)
        return _verschieb_angebot(sit, melde)
    return _verschieb_wunsch_frage(sit, termin, melde)


def _kandidat_verwerfen(sit: dict, melde: Melde) -> dict:
    """Nein zu einem Detail-Kandidaten: Termin-ID sperren und weiter eingrenzen."""
    s = gehirn.sammler(sit)
    war_name60 = sit.get("verwDetailQuelle") == "name60"
    _obs(
        sit,
        "confirmed",
        outcome="rejected",
        source=_obs_quelle(sit.get("verwDetailQuelle"), "unknown"),
        count=1,
    )
    termin = _gewaehlt(sit)
    aid = _s(sit.pop("verwKandidat", ""))
    if aid:
        ausgeschlossen = list(
            sit.get("_verwAusgeschlosseneTermine")
            or sit.get("verwAusgeschlossen")
            or []
        )
        if aid not in ausgeschlossen:
            ausgeschlossen.append(aid)
        sit["_verwAusgeschlosseneTermine"] = ausgeschlossen
        sit.pop("verwAusgeschlossen", None)
    if war_name60 and _s(termin.get("patientId")):
        patienten = list(sit.get("_verwAusgeschlossenePatienten") or [])
        if _s(termin.get("patientId")) not in patienten:
            patienten.append(_s(termin.get("patientId")))
        sit["_verwAusgeschlossenePatienten"] = patienten
    sit["gefunden"] = []
    sit["gefundenKey"] = ""
    sit["verwaltenTermin"] = ""
    s["phase"] = ""
    s["frage"] = ""
    behandelt, aus = _detail_dispatch(sit, melde)
    if behandelt and aus:
        aus["text"] = _s(f"Okay, dieser Termin ist es nicht. {aus.get('text')}")
        return aus
    if war_name60:
        # Gibt es keinen zweiten Detail-Kandidaten, darf die alte Namenssuche
        # nicht denselben abgelehnten Fuzzy-Treffer erneut anbieten.
        gehoert = f"{s['vorname']} {s['nachname']}".strip()
        if gehoert:
            sit["_verwNameGehoert"] = gehoert
        s["vorname"] = ""
        s["nachname"] = ""
        s["patientId"] = ""
        s["bekannt"] = False
        s["warSchonMal"] = None
        s["vornameQuelle"] = ""
        s["vornameCheck"] = ""
        sit["patient"] = {}
        sit["verwDetailQuelle"] = ""
        return _nachname_frage(
            sit,
            "Okay, dieser Patient ist es nicht. Bitte nennen oder "
            "buchstabieren Sie den Nachnamen noch einmal.",
        )
    if not s["nachname"]:
        return _nachname_frage(
            sit,
            "Okay, dieser Termin ist es nicht. Dann gleiche ich den Patienten ab:",
        )
    aus = _dispatch(sit, melde)
    if aus:
        aus["text"] = _s(f"Okay, dieser Termin ist es nicht. {aus.get('text')}")
        return aus
    return _nachname_frage(sit, "Okay, dieser Termin ist es nicht.")


def _vorsatz_einmal(sit: dict, vorsatz: str) -> str:
    """Ein Erklär-Vorsatz der Namensfrage nur beim ersten Mal (W-VORSATZ-EINMAL
    07.10.2026, Anrufe 5af9635e/4eb8de09/e5066c5e): beim zweiten Durchlauf
    strich der Wiederholungs-Wächter die wortgleiche Frage, übrig blieb nur
    „Zu dieser Zeit sehe ich mehrere Termine.“ — und Bianca schwieg."""
    if os.environ.get("VORSATZ_EINMAL", "1").strip() == "0":
        return vorsatz
    gesagt = sit.get("verwDetailPraefixGesagt")
    gesagt = list(gesagt) if isinstance(gesagt, list) else []
    if vorsatz in gesagt:
        return ""
    sit["verwDetailPraefixGesagt"] = gesagt + [vorsatz]
    return vorsatz


def _nachname_frage(sit: dict, vorsatz: str = "") -> dict:
    s = gehirn.sammler(sit)
    fid, frage = gehirn._nachname_start_frage(sit, "")
    s["frage"] = fid
    return {"text": _s(f"{vorsatz} {frage}")}


def _name_nicht_sicher(sit: dict, vorsatz: str) -> dict:
    """Ein gehörter Name trägt nicht: zählt als gescheiterte Namensrunde.

    Ab der zweiten kommt die Namens-SMS (bzw. die Frage nach einem Handy)
    statt einer weiteren Buchstabierrunde."""
    from kern import namenslink
    namenslink.fehlversuch(sit)
    aus = namenslink.rettung_starten(sit)
    if aus:
        spur.merken(sit, "namens-sms-rettung", "verwaltung")
        return aus
    return _nachname_frage(sit, vorsatz)


_NAMENSFRAGEN_RETTUNG = frozenset({"name", "nachname", "buchstabieren", "nachname_korr"})


def _namensrunde_gescheitert(sit: dict, t: str, neu: set[str]) -> dict | None:
    """Auf die Namensfrage kam kein Name (Anruf 205930f8: „Termin.",
    „Blessing.") — das zählt wie eine verneinte Rücklese.

    Nicht gezählt: Stille, Buchstaben-Fragment, irgendein Namensteil,
    Zwischenfrage, Anliegen-Wechsel. Je Zug höchstens einmal."""
    s = gehirn.sammler(sit)
    if s["frage"] not in _NAMENSFRAGEN_RETTUNG or not t:
        return None
    if _s(s.get("nachname")) or _s(s.get("buchstabenTeil")):
        return None
    if neu & {"name", "nachname", "vorname", "modus", "buchstabenTeil"}:
        return None
    if gehirn.ist_zwischenfrage(t):
        return None
    key = f"{sit.get('_zugNr') or 0}|{t.casefold()[:120]}"
    if sit.get("_verwNameFehlKey") == key:
        return None
    sit["_verwNameFehlKey"] = key
    from kern import namenslink
    namenslink.fehlversuch(sit)
    aus = namenslink.rettung_starten(sit)
    if aus:
        spur.merken(sit, "namens-sms-rettung", "verwaltung-kein-name")
    return aus


def _mehrere_behandler(tenant: dict) -> bool:
    ids = {
        _s(c.get("id")) or _s(c.get("calendarId"))
        for c in (tenant.get("calendars") or [])
        if isinstance(c, dict) and (_s(c.get("id")) or _s(c.get("calendarId")))
    }
    return len(ids) > 1


def _ohne_zeit_eingrenzen(sit: dict) -> dict:
    """Terminzeit unbekannt: Behandler und Patient statt Datum erfragen."""
    s = gehirn.sammler(sit)
    if _mehrere_behandler(sit.get("tenant") or {}) and not _s(
            (s.get("arzt") or {}).get("calendarId")) and not sit.get("verwArztGefragt"):
        sit["verwArztGefragt"] = True
        s["frage"] = "arzt"
        return {"text": (
            "Kein Problem, ich finde den Termin auch so. "
            "Bei welchem Behandler ist der Termin eingetragen?"
        )}
    if not s["nachname"]:
        return _nachname_frage(
            sit,
            "Kein Problem, ich finde den Termin auch über den Namen.",
        )
    return {}


def _detail_dispatch(sit: dict, melde: Melde) -> tuple[bool, dict | None]:
    """Datum/Uhrzeit-Kandidaten aufloesen; (False, None) = alte Namenssuche."""
    s = gehirn.sammler(sit)
    info = _detail_kandidaten(sit, melde)
    if info is None:
        return False, None
    kandidaten = list(info.get("appointments") or [])
    quelle = _s(info.get("source"))
    w = sit.get("verwHinweis") or {}

    belegt = quelle in {"patientId", "telefon", "nameExact", "name60",
                        "zwei_merkmale"}
    if s["modus"] == "auskunft" and kandidaten and belegt:
        patienten = {
            _s(a.get("patientId")) or _name_norm(
                a.get("patientName"), zeitwoerter=False)
            for a in kandidaten
        }
        patienten.discard("")
        if len(patienten) == 1:
            sit["gefunden"] = kandidaten
            sit["gefundenKey"] = f"detail|{_detail_tag(sit)}|{quelle}"
            sit["verwDetailQuelle"] = quelle
            sit["verwKandidat"] = _s(kandidaten[0].get("id"))
            sit["verwaltenTermin"] = _s(kandidaten[0].get("id"))
            if quelle == "name60":
                return True, _bestaetigen(sit, kandidaten[0], melde)
            return True, _ansagen(sit)

    if len(kandidaten) == 1 and belegt:
        termin = kandidaten[0]
        sit["gefunden"] = [termin]
        sit["gefundenKey"] = f"detail|{_s(termin.get('id'))}"
        sit["verwDetailQuelle"] = quelle
        sit["verwKandidat"] = _s(termin.get("id"))
        return True, _bestaetigen(sit, termin, melde)

    if kandidaten:
        if len(kandidaten) == 1:
            return True, _nachname_frage(sit, _vorsatz_einmal(
                sit, "Die Termindaten habe ich. Zum sicheren Patientenabgleich:"))
        patienten = {
            _s(a.get("patientId")) or _name_norm(
                a.get("patientName"), zeitwoerter=False)
            for a in kandidaten
        }
        patienten.discard("")
        # Mehrere Termine derselben belegten Person duerfen als Termine
        # vorgelesen werden; fremde Patientennamen werden nie aufgezählt.
        if len(patienten) == 1 and quelle in {
            "patientId", "telefon", "nameExact", "name60", "zwei_merkmale",
        }:
            sit["gefunden"] = kandidaten
            sit["gefundenKey"] = f"detail|{_detail_tag(sit)}|{quelle}"
            sit["verwDetailQuelle"] = quelle
            if quelle == "name60":
                sit["verwKandidat"] = _s(kandidaten[0].get("id"))
                sit["verwaltenTermin"] = _s(kandidaten[0].get("id"))
                sit["_verwName60Danach"] = "wahl"
                s["phase"] = "verw_patient_bestaetigen"
                s["frage"] = "verw_patient_ok"
                patient = _s(kandidaten[0].get("patientName"))
                patient_frage = (
                    f"Geht es um {patient}?"
                    if patient else "Habe ich den richtigen Patienten?"
                )
                return True, {"text": (
                    "Der Name passt ähnlich, aber ich möchte nichts verwechseln. "
                    f"{patient_frage}"
                )}
            s["phase"] = "wahl"
            s["frage"] = "terminwahl"
            verb = "absagen" if s["modus"] == "absagen" else "verschieben"
            return True, {"text": (
                f"Ich sehe mehrere passende Termine: {_liste_sprechbar(kandidaten)}. "
                f"Welchen möchten Sie {verb}?"
            )}
        if w.get("minuteOfDay") is None and w.get("hour") is None:
            s["frage"] = "wann"
            return True, {"text": (
                "Den Tag habe ich. Um welche Uhrzeit ist der Termin ungefähr?"
            )}
        kalender = {
            _s(a.get("calendarId")) or _name_norm(a.get("doctorName"))
            for a in kandidaten
            if _s(a.get("calendarId")) or _s(a.get("doctorName"))
        }
        if (len(kalender) > 1
                and not _s((s.get("arzt") or {}).get("calendarId"))
                and not sit.get("verwDetailArztGefragt")):
            # Erst nicht-personenbezogene Termindaten ausschöpfen. Bei
            # mehreren parallelen Kalendern grenzt der Behandler sicherer
            # ein als ein früh verhörter Name. Nur EINMAL: „weiß ich nicht"
            # geht weiter zum Namen (Anruf 205930f8: sonst dreimal gefragt).
            sit["verwDetailArztGefragt"] = True
            s["frage"] = "arzt"
            return True, {"text": (
                "Zu dieser Zeit laufen mehrere Termine. "
                "Bei welchem Behandler ist der Termin eingetragen?"
            )}
        if not s["nachname"]:
            return True, _nachname_frage(sit, _vorsatz_einmal(
                sit, "Zu dieser Zeit sehe ich mehrere Termine. Zum sicheren Abgleich:"))
        # Mehrere verschiedene Patienten trotz 60-Prozent-Namensnaehe:
        # Schreibweise klaeren, nie den Bestwert still erraten.
        sit["_verwNameGehoert"] = s["nachname"]
        s["nachname"] = ""
        s["vorname"] = ""
        return True, _name_nicht_sicher(
            sit,
            "Der Name passt zu mehreren Einträgen. Bitte nennen oder "
            "buchstabieren Sie den Nachnamen noch einmal.",
        )

    if quelle == "identitaet_widerspruch":
        # Datum/Uhrzeit zeigen auf einen anderen Patienten als die bereits
        # bestätigte Akte/Rufnummer. Die Identität gewinnt: mit ihrer
        # Patienten-Terminliste weitersuchen, nie erneut nach dem Datum oder
        # Namen fragen und nie zum fremden Tageskandidaten springen.
        return False, None
    if quelle == "name_unter60":
        gehoert = f"{s['vorname']} {s['nachname']}".strip()
        vorher = _s(sit.get("_verwNameGehoert"))
        if s.get("buchstabiert") or (
                vorher and _name_norm(vorher) == _name_norm(gehoert)):
            # Der Name wurde bereits wiederholt/ausbuchstabiert. Dann waren
            # wahrscheinlich die erinnerten Termindaten ungenau; die
            # Namenssuche darf übernehmen, statt dieselbe Schreibfrage in
            # einer Schleife zu stellen.
            sit["verwDetailQuelle"] = ""
            return False, None
        if gehoert:
            sit["_verwNameGehoert"] = gehoert
        s["vorname"] = ""
        s["nachname"] = ""
        return True, _name_nicht_sicher(
            sit,
            "Die Termindaten habe ich, aber der Patientenname passt noch nicht "
            "sicher genug.",
        )
    # Kein Termin exakt zu den erinnerten Daten: mit dem Namen die
    # Patienten-Terminliste holen und den echten Termin rueckfragen.
    if s["nachname"]:
        return False, None
    return True, _nachname_frage(
        sit,
        "Zu den erinnerten Termindaten sehe ich keinen eindeutigen Eintrag. "
        "Ich prüfe deshalb über den Patienten:",
    )


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
        from kern import namenslink
        aus = namenslink.starten(sit)
        if aus is not None:
            return aus
        return _kein_termin(sit, s["modus"])
    if res.get("mehrdeutig"):
        if res.get("vornameVerworfen"):
            s["vorname"] = ""  # der gespeicherte Vorname passte nachweislich nicht
        if s.get("vorname"):
            from kern import namenslink
            aus = namenslink.starten(sit)
            if aus is not None:
                return aus
        return _vorname_frage(sit)
    termine = sit.get("gefunden") or []
    if not termine:
        return _kein_termin(sit, s["modus"])
    if s["modus"] == "auskunft":
        if sit.get("verwDetailQuelle") == "name60":
            return _bestaetigen(sit, termine[0], melde)
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


_VERW_DRITTE_RE = re.compile(
    r"\b(?:mein|meine|meinen|meinem|meiner|meines|"
    r"unser|unsere|unseren|unserem|unserer|unseres)\s+"
    r"(mutter|vater|sohn|tochter|kind|bruder|schwester|ehemann|ehefrau|"
    r"mann|frau|partner|partnerin|freund|freundin|nachbar|nachbarin|"
    r"kollege|kollegin|oma|opa|grossmutter|großmutter|grossvater|großvater)"
    r"(?:es|s|n)?\b",
    re.I,
)
_VERW_NAME_ENDE_RE = re.compile(
    rf"\b(?:der\s+termin|termin\s+(?:ist|war|am|vom)|am\s+\d|vom\s+\d|"
    rf"um\s+\d|gegen\s+\d|hat\b|möchte\b|moechte\b|will\b|braucht\b|"
    rf"(?:{_MONATE_RE})\b)", re.I)
_VERW_NAME_WORT_RE = re.compile(
    r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß'’-]{1,}")
_VERW_NAME_PREFIX_RE = re.compile(
    r"^\s*(?:(?:mein|der)\s+name\s+ist|ich\s+hei(?:ß|ss)e|"
    r"(?:der\s+)?familienname\s+ist|patient(?:in)?\s+(?:ist|heißt))\s+",
    re.I,
)
_VERW_NAME_FUELLER = {
    "bitte", "der", "die", "familienname", "frau", "herr", "heisse",
    "heiße", "ist", "lautet", "mein", "meine", "name", "patient",
    "patientin", "von",
}


def _verw_namewerte(segment: str) -> tuple[str, str]:
    """Strukturierten Namen lesen; Komma erlaubt ``Nachname, Vorname``."""
    roh = _VERW_NAME_PREFIX_RE.sub("", _s(segment)).strip(" ,.;:!?")
    if not roh:
        return "", ""
    # Buchstabierketten bleiben vollständig beim bewährten Parser.
    if len(re.findall(r"\b[A-Za-zÄÖÜ]\b", roh)) >= 2 or re.search(
            r"(?:[A-Za-zÄÖÜ]-){2,}", roh):
        return "", ""

    gruppen = [g.strip() for g in roh.split(",") if g.strip()]

    def woerter(v: str, *, zeitwoerter: bool = True) -> list[str]:
        return [
            w for w in _VERW_NAME_WORT_RE.findall(v)
            if (not zeitwoerter or w.casefold() not in _VERW_NAME_STOP)
            and w.casefold() not in _VERW_NAME_FUELLER
        ]

    if len(gruppen) >= 2:
        # Die Kommas belegen die Namensstruktur. Hier dürfen echte
        # Familiennamen wie „Mai“ nicht als Zeitwort verschwinden.
        links = woerter(gruppen[0], zeitwoerter=False)
        rechts = woerter(gruppen[1], zeitwoerter=False)
        if links and rechts:
            # „Hauck, Larissa Hauck“ bzw. „Brucklacher, Siegfried“.
            if len(rechts) >= 2 and _name_norm(links[-1]) == _name_norm(rechts[-1]):
                return rechts[0], rechts[-1]
            return rechts[0], links[-1]
    alle = woerter(roh)
    if len(alle) >= 2:
        return alle[0], alle[-1]
    if len(alle) == 1:
        return "", alle[0]
    return "", ""


def _verw_detailname_aufnehmen(sit: dict, text: str, neu: set[str]) -> None:
    """Patientennamen aus demselben Satz wie die Bestandstermindaten ernten.

    Der allgemeine Formularparser machte live aus
    „Brucklacher, Siegfried, der Termin ist am 13. Oktober“ den Patienten
    „Brucklacher Oktober“. Hier endet der Name vor der Terminklausel.
    """
    s = gehirn.sammler(sit)
    if s.get("buchstabiert") or sit.get("verwDrittpersonGeloest"):
        return
    kandidat = ""
    # Strukturierte Schreibweise am Satzanfang: „Nachname, Vorname, der
    # Termin …“. Zwei Kommas sind Pflicht. Ein freier Anliegen-Satz wie
    # „Guten Tag, ich möchte meinen Termin absagen“ ist KEIN Name.
    m = re.match(
        r"^\s*(?:(?:guten\s+tag|hallo|hi|grü(?:ß|ss)\s+gott)\s*,\s*)?"
        r"([^,]{2,40})\s*,\s*([^,]{2,40})\s*,\s*"
        r"(?=(?:der\s+)?termin\b|(?:am|um|gegen)\s+\d)",
        text,
        re.I,
    )
    if m:
        kandidat = f"{m.group(1)}, {m.group(2)}"
    if not kandidat:
        # „Mein Name ist …, der Termin …“
        m = re.search(
            r"\b(?:(?:mein|der)\s+name\s+ist|ich\s+hei(?:ß|ss)e|"
            r"(?:der\s+)?familienname\s+ist)\s+(.{2,80})",
            text,
            re.I,
        )
        if m:
            kandidat = re.split(_VERW_NAME_ENDE_RE, m.group(1), maxsplit=1)[0]
    if not kandidat:
        # „Der Termin von/für Elisabeth Päsler am …“
        m = re.search(
            r"\btermin\b.{0,45}?\b(?:für|fuer|von)\s+"
            r"(.{2,60}?)(?=\s+(?:am|um|gegen|bei)\b|[,.!?;]|$)",
            text,
            re.I,
        )
        if m:
            kandidat = m.group(1)
    vor, nach = _verw_namewerte(kandidat)
    if not nach:
        return
    alt = _name_norm(f"{s.get('vorname') or ''} {s.get('nachname') or ''}")
    neu_name = _name_norm(f"{vor} {nach}")
    if s.get("patientId") and alt and neu_name and alt != neu_name:
        # Ein ausdrücklich anderer Patientenname schlägt den bloßen Treffer
        # der Anrufernummer. Sonst würde die Akte des Anrufers gewinnen.
        sit.pop("verwAnruferDirekt", None)
        s["patientId"] = ""
        s["bekannt"] = False
        s["anruferCheck"] = "nein"
        sit["gefunden"] = []
        sit["gefundenKey"] = ""
    s["vorname"] = vor
    s["nachname"] = nach
    s["name"] = f"{vor} {nach}".strip()
    s["buchstabiert"] = False
    sit["_verwNameStrukturiert"] = True
    neu.add("nachname")
    if vor:
        neu.update({"name", "vorname"})


def _verw_drittperson_aufnehmen(sit: dict, text: str, neu: set[str]) -> None:
    """Kontaktperson vom Patienten trennen und einen direkt genannten Namen ernten."""
    s = gehirn.sammler(sit)
    m = _VERW_DRITTE_RE.search(text)
    wen = gehirn.fuer_wen_signal(text)
    if not wen and m:
        wen = gehirn.fuer_wen_signal(f"für meine {m.group(1)}") or "andere"
    if not wen:
        return
    sit.pop("verwAnruferDirekt", None)
    s["fuerWen"] = wen
    if not sit.get("verwDrittpersonGeloest"):
        gehirn.patient_von_kontakt_loesen(sit)
        sit["verwDrittpersonGeloest"] = True
    # "Meine Mutter Elisabeth Päsler, Termin am …": der Name hinter der
    # Rolle gehoert dem Patienten; Datum/Uhrzeit enden das Namenssegment.
    rest = text[m.end():] if m else ""
    rest = re.split(_VERW_NAME_ENDE_RE, rest, maxsplit=1)[0]
    toks = [
        x for x in re.findall(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß'’-]{1,}", rest)
        if x.casefold() not in _VERW_NAME_STOP
    ]
    if len(toks) >= 2:
        s["vorname"], s["nachname"] = toks[0], toks[-1]
        s["buchstabiert"] = False
        sit["_verwNameStrukturiert"] = True
        neu.update({"name", "vorname", "nachname"})
    elif len(toks) == 1:
        s["nachname"] = toks[0]
        s["buchstabiert"] = False
        sit["_verwNameStrukturiert"] = True
        neu.add("nachname")


def _verw_name_zeitmuell_entfernen(sit: dict, text: str, neu: set[str]) -> None:
    """Nur im Verwaltungsweg angehaengte Monate/Uhr-Paraphrasen entfernen."""
    s = gehirn.sammler(sit)
    if sit.pop("_verwNameStrukturiert", False):
        # Ein explizit strukturiert erkannter Name („Nachname, Vorname, der
        # Termin …“ / Drittperson) gewinnt. Auch echte Familiennamen wie
        # Mai dürfen nicht als Monatswort entfernt werden.
        s["name"] = f"{s['vorname']} {s['nachname']}".strip()
        return
    if ("," in text and s.get("vorname") and s.get("nachname")
            and _name_norm(s["vorname"]) == _name_norm(s["nachname"])):
        vor, nach = _verw_namewerte(text)
        if nach:
            s["vorname"], s["nachname"] = vor, nach
            neu.add("nachname")
            if vor:
                neu.update({"name", "vorname"})
    zeitkontext = bool(
        re.search(rf"\b(?:{_MONATE_RE})\b", text, re.I)
        and (re.search(r"\d", text) or re.search(r"\btermin\b|\buhr\b", text, re.I))
    )
    for feld in ("vorname", "nachname"):
        alt = _s(s.get(feld))
        if not alt:
            continue
        teile = re.findall(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß'’-]*", alt)
        sauber = [
            x for x in teile
            if x.casefold() not in _VERW_NAME_STOP
            or (len(teile) == 1 and not zeitkontext)
        ]
        neu_wert = " ".join(sauber)
        if neu_wert != alt:
            s[feld] = neu_wert
            if neu_wert:
                neu.add(feld)
            else:
                neu.discard(feld)
    if s["vorname"] or s["nachname"]:
        s["name"] = f"{s['vorname']} {s['nachname']}".strip()


def _erkannten_anrufer_direkt_binden(sit: dict, text: str = "") -> bool:
    """Eindeutige Caller-ID-Akte ohne vorgeschaltete Erlaubnisfrage binden.

    Der Schnellweg liest nur Termine. Jeder destruktive Schritt bleibt an
    der vorhandenen Absage-/Verschiebe-Bestaetigung. Drittpersonen und ein
    ausdruecklicher Identitaetswiderspruch duerfen die Anruferakte nie erben.
    """
    s = gehirn.sammler(sit)
    if s.get("fuerWen") or s.get("anruferCheck") == "nein":
        return False
    if text and gehirn.ist_anrufer_identitaet_nein(text):
        return False
    a = gehirn.anrufer_bekannt(sit)
    if not _s(a.get("patientId")):
        return False
    if not gehirn.anrufer_daten_uebernehmen(sit):
        return False
    s["frage"] = ""
    sit["verwAnruferDirekt"] = True
    return True


def _sammeln(sit: dict, t: str, neu: set[str], melde: Melde) -> dict | None:
    """Absagen/Verschieben: Terminmerkmale vor Name, Auskunft nie nach Datum."""
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
                if not _hinweis_merken(sit, s["wunschText"] or t, relativ=True):
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
            elif not re.search(r"\b(?:auf|zu|zum|zur)\b", t, re.I):
                # "Den Termin am 13. Oktober verschieben" nennt nur den
                # Bestandstermin. "Auf den 13. Oktober" ist dagegen der
                # NEUE Wunsch und darf nicht als Suchdatum missbraucht werden.
                _hinweis_merken(sit, t, relativ=True)
                s["wunsch"] = None
                s["wunschText"] = ""
    sit["verwAktiv"] = True
    _verw_drittperson_aufnehmen(sit, t, neu)
    _verw_detailname_aufnehmen(sit, t, neu)
    _verw_name_zeitmuell_entfernen(sit, t, neu)
    if (s["modus"] in _MODI and not _detail_tag(sit)
            and _UNKLAR_RE.search(t)
            and re.search(r"\b(?:wann|zeit|datum|termin)\b", t, re.I)):
        sit["verwZeitUnbekannt"] = True

    # Antworten auf offene Fragen auswerten.
    if s["frage"] == "qwen_name":
        return _qwen_name_zug(sit, t, melde)
    if s["frage"] == "wann":
        if _UNKLAR_RE.search(t):
            sit["verwZeitUnbekannt"] = True
            s["frage"] = ""
        elif _hinweis_merken(sit, t, relativ=True):
            s["frage"] = ""
            # Diese Antwort beschreibt den BESTANDSTERMIN. Beim Verschieben
            # darf sie nie zugleich als neuer Wunschzeitpunkt weiterleben.
            s["wunsch"] = None
            s["wunschText"] = ""
        elif {"name", "nachname", "vorname"} & neu:
            # Der Anrufer kennt die Zeit nicht oder ueberspringt sie und
            # nennt direkt den Patienten — das ist ein gueltiger Suchweg.
            sit["verwZeitUnbekannt"] = True
            s["frage"] = ""
        else:
            # Der Anrufer darf die neue Prioritaetsfrage ueberspringen und
            # direkt den Namen nennen/buchstabieren. Dazu denselben bewaehrten
            # Namensparser einmal mit Namenskontext laufen lassen.
            s["frage"] = "nachname"
            extra = gehirn.einsammeln(sit, t)
            _verw_name_zeitmuell_entfernen(sit, t, neu)
            if s["nachname"]:
                neu.update(extra or {"nachname"})
                sit["verwZeitUnbekannt"] = True
                s["frage"] = ""
            else:
                s["frage"] = "wann"
                return {"text": (
                    "Wenn Sie den Zeitpunkt wissen: Welcher Tag und ungefähr "
                    "welche Uhrzeit? Wenn nicht, nennen Sie mir bitte den "
                    "Behandler und den Nachnamen des Patienten."
                )}
    elif s["frage"] == "arzt":
        # Arzt/Behandler wurde von gehirn.einsammeln bereits in s["arzt"]
        # abgelegt. Auch "weiß ich nicht" darf weiter zum Patientennamen —
        # und nach EINER Nachfrage auch eine unklare Antwort.
        if s.get("arzt") or _UNKLAR_RE.search(t) or sit.get("verwArztNachgefragt"):
            s["frage"] = ""
        else:
            sit["verwArztNachgefragt"] = True
            return {"text": "Bei welchem Behandler ist der Termin eingetragen?"}
    elif s["frage"] == "vorname":
        if not neu:
            return None  # Äußerer Flow hält Absage/Verschieben deterministisch offen.
        s["frage"] = ""
    elif s["frage"] == "nachname" and sit.get("verwKorrektur"):
        if not neu:
            if gehirn.ist_zwischenfrage(t) or gespraech.traegt_thema(sit, t):
                return None  # Äußerer Flow hält die Korrektur-Frage offen.
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

    # Eine per Rufnummer eindeutig erkannte Akte darf fuer die rein lesende
    # Terminsuche sofort gebunden werden. Absage/Verschiebung bleiben hinter
    # ihrer eigenen ausdruecklichen Bestaetigung; Drittpersonen gehen nie
    # ueber diesen Schnellweg.
    if not s["nachname"] and not s["anruferCheck"] and not s["fuerWen"]:
        agentprofil.anrufer_warten(sit)
        _erkannten_anrufer_direkt_binden(sit, t)

    # Termin-zuerst: ein konkreter Tag wird direkt im Standortkalender nach
    # Uhrzeit, Behandler und Patient/Rufnummer eingegrenzt. Die alte Namens-CF
    # bleibt sicherer Rueckfall, falls die Erinnerungsdaten abweichen.
    if s["modus"] in {"absagen", "verschieben"} and _detail_tag(sit):
        behandelt, aus = _detail_dispatch(sit, melde)
        if behandelt:
            return aus

    if not s["nachname"]:
        if s["frage"] in {"name", "nachname", "anrufer_check"} and not neu:
            # Live 06.09.2026: return None liess das LLM Name fragen und
            # list_appointments ohne Patient — Identitaet deterministisch halten.
            if s["frage"] == "anrufer_check" and gehirn.anrufer_bekannt(sit):
                return {"text": gehirn.anrufer_check_frage(sit)}
            # Async-Anrufer kam NACH der Nachnamen-Frage: direkt binden und
            # noch in diesem Zug suchen.
            if (s["frage"] in {"name", "nachname"} and not s["anruferCheck"]
                    and not s["fuerWen"] and gehirn.anrufer_bekannt(sit)):
                if _erkannten_anrufer_direkt_binden(sit, t):
                    return _dispatch(sit, melde)
            was = {
                "absagen": "Damit ich den richtigen Termin absage",
                "verschieben": "Damit ich den richtigen Termin finde",
            }.get(s["modus"], "Damit ich den richtigen Termin finde")
            return _nachname_frage(sit, f"{was}:")
        # Die Rufnummer hat einen Kartei-Patienten getroffen: fuer die
        # lesende Verwaltungssuche sofort binden, statt eine ueberfluessige
        # Erlaubnisfrage vorzuschalten.
        agentprofil.anrufer_warten(sit)
        if not s["anruferCheck"] and not s["fuerWen"] and gehirn.anrufer_bekannt(sit):
            if _erkannten_anrufer_direkt_binden(sit, t):
                return _dispatch(sit, melde)
        if s["modus"] == "auskunft" and sit.get("verwZeitUnbekannt"):
            return _ohne_zeit_eingrenzen(sit)
        if s["modus"] in {"absagen", "verschieben"} and not _detail_tag(sit):
            if sit.get("verwZeitUnbekannt"):
                return _ohne_zeit_eingrenzen(sit)
            if _hinweis_hat(sit.get("verwHinweis")):
                if sit.get("_verwWannTeilGefragt"):
                    # Ein zweiter nur teilweiser Zeit-Hinweis darf keine
                    # Wann-Schleife eröffnen. Behandler/Patient übernehmen.
                    sit["verwZeitUnbekannt"] = True
                    return _ohne_zeit_eingrenzen(sit)
                sit["_verwWannTeilGefragt"] = True
                s["frage"] = "wann"
                return {"text": (
                    "Die ungefähre Angabe habe ich. Welches genaue Datum war "
                    "es? Wenn Sie das nicht mehr wissen, grenze ich den Termin "
                    "über Behandler und Nachname des Patienten ein."
                )}
            s["frage"] = "wann"
            return {"text": (
                "An welchem Tag und ungefähr um wie viel Uhr ist der Termin? "
                "Wenn Sie das nicht mehr wissen, grenze ich ihn über Behandler "
                "und Nachname des Patienten ein."
            )}
        was = {
            "absagen": "Damit ich den richtigen Termin absage",
            "verschieben": "Damit ich den richtigen Termin finde",
        }.get(s["modus"], "Damit ich den richtigen Termin finde")
        # Chef 31.08.2026: direkt zum Buchstabieren einladen — der verhoerte
        # Nachname ist die haeufigste Ursache fuer die Fehlsuche (Zannes).
        return _nachname_frage(sit, f"{was}:")

    if not gehirn.name_suche_frei(sit):
        return _schreibweise_zuerst(sit)

    quittung = ""
    if (("name" in neu or "nachname" in neu)
            and "anruferCheck" not in neu and s["nachname"]):
        quittung = gehirn.name_quittung(s)
    aus = _dispatch(sit, melde)
    if aus and quittung and _s(aus.get("text")):
        aus["text"] = quittung + aus["text"]
    return aus


def sicherer_fortsetzungsanker(sit: dict) -> dict | None:
    """Aktive Termin-Verwaltung darf nie in das freie LLM fallen.

    Der Nutzer kann per Intent-Schicht weiterhin ausdrücklich das Anliegen
    wechseln. Solange der Verwaltungsmodus aber aktiv bleibt, wiederholt
    ausschließlich die deterministische Maschine den offenen sicheren
    Schritt und behauptet weder Treffer noch Erfolg.
    """
    s = gehirn.sammler(sit)
    if s.get("modus") not in _MODI:
        return None

    termin = _gewaehlt(sit)
    phase = _s(s.get("phase"))
    frage = _s(s.get("frage"))

    if phase == "verw_patient_bestaetigen" and termin:
        patient = _s(termin.get("patientName"))
        patient_text = f" für {patient}" if patient else ""
        return {"text": (
            "Damit ich nichts verwechsle: "
            f"Ist es der Termin {termin.get('spoken')}{patient_text}?"
        )}
    if phase == "absage_bestaetigen" and termin:
        return _absage_frage(sit, termin)
    if phase == "verschieb_bestaetigen" and termin and s.get("slotIso"):
        return _verschieb_readback(sit, _s(s.get("slotIso")))
    if phase == "mehrfach_bestaetigen":
        posten = list(sit.get("mehrfachAbsage") or [])
        liste = _fuegen([
            _s(
                f"{_s(p.get('spoken'))}"
                f"{' für ' + _s(p.get('patientName')) if _s(p.get('patientName')) else ''}"
            )
            for p in posten
        ])
        return {"text": (
            f"Es geht um diese Termine: {liste}. "
            "Soll ich sie wirklich alle absagen?"
        )}
    if phase == "wahl" and sit.get("gefunden"):
        return {"text": (
            f"Zur Auswahl: {_liste_sprechbar(sit['gefunden'])}. "
            "Welchen Termin meinen Sie?"
        )}
    if phase == "verschieb_angebot" and sit.get("offered"):
        return {"text": spoken_offer(sit["offered"])}
    if phase == "verschieb_wunsch" or frage == "wunsch":
        return {"text": "Wann passt es Ihnen für den neuen Termin besser?"}

    if frage == "anrufer_check" and gehirn.anrufer_bekannt(sit):
        return {"text": gehirn.anrufer_check_frage(sit)}
    if frage in {"name", "nachname", "buchstabieren"}:
        # 3b (Thaler dbc5e2a8): ist der Termin bereits gefunden und die Akte
        # gebunden, wird NIE wieder nach der Schreibweise gefragt — stattdessen
        # den gefundenen Termin erneut ansagen.
        if _schreibweise_gesperrt(sit):
            return _ansagen(sit)
        was = ("Damit ich den richtigen Termin absage:"
               if s["modus"] == "absagen"
               else "Damit ich den richtigen Termin verschiebe:")
        return _nachname_frage(sit, was)
    if frage == "vorname":
        return {"text": "Wie lautet der Vorname des Patienten?"}
    if frage == "arzt":
        return {"text": "Bei welchem Behandler ist der Termin eingetragen?"}
    if frage == "wann":
        if s["modus"] == "auskunft":
            aus = _ohne_zeit_eingrenzen(sit)
            if aus:
                return aus
            if s["nachname"]:
                aus = _dispatch(sit, None)
                if aus:
                    return aus
            return _nachname_frage(
                sit,
                "Kein Problem, ich finde den Termin auch über den Namen.",
            )
        return {"text": (
            "Welches Datum oder welche ungefähre Uhrzeit hat der Termin? "
            "Wenn Sie das nicht wissen, sagen Sie mir bitte den Behandler."
        )}
    if frage == "behandlung":
        return _behandlung_frage(sit, sit.get("gefunden") or [])

    if sit.get("verwZeitUnbekannt"):
        aus = _ohne_zeit_eingrenzen(sit)
        if aus:
            return aus
        if s["nachname"]:
            aus = _dispatch(sit, None)
            if aus:
                return aus
    if s["modus"] == "auskunft":
        if s["nachname"]:
            aus = _dispatch(sit, None)
            if aus:
                return aus
        return _nachname_frage(
            sit,
            "Damit ich Ihren bestehenden Termin sicher im Kalender finde:",
        )
    s["frage"] = "wann"
    aktion = "Absage" if s["modus"] == "absagen" else "Verschiebung"
    return {"text": (
        f"Ich bleibe bei der {aktion}. "
        "Welches Datum oder welche ungefähre Uhrzeit hat der Termin?"
    )}


def zug(sit: dict, gesagt: str, neu: set[str], melde: Melde = None) -> dict | None:
    """Ein Anrufer-Satz durch die Termin-Verwaltung.

    ``None`` bedeutet nur: dieser Teilzustand hat keine Antwort erzeugt.
    Bei aktiver Absage, Verschiebung oder Terminauskunft fängt ``flow.zug``
    das anschließend mit ``sicherer_fortsetzungsanker`` ab; das freie LLM
    übernimmt dort nie.
    """
    from bianca.flow import _slot_wahl  # kein Kreis-Import auf Modulebene

    s = gehirn.sammler(sit)
    t = _s(gesagt)
    if (s["modus"] not in _MODI
            and not (sit.get("verwAbschlussOffen")
                     and s["phase"] == "fertig"
                     and s["frage"] == "sonst_noch")):
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

    if s["frage"] == "namenslink":
        from kern import namenslink
        aus = namenslink.zug(sit, t, neu, melde)
        if aus is not None:
            return aus

    if s["frage"] == "qwen_name" and qwen_name_ausgang_aktiv():
        # W-QWEN-NAME-ALLE-MODI (07.10.2026, Anrufe 17d53232/7fbed2d9/
        # af10c094): die Antwort auf „Ich habe auch X verstanden. Ist das
        # richtig?“ wurde nur im Absage-/Verschiebe-Zweig ausgewertet. Bei
        # der Terminauskunft löste jedes „Nein“ eine neue Suche aus — und
        # dieselbe Frage kam bis zu siebenmal.
        return _qwen_name_zug(sit, t, melde, neu)

    aus = _namensrunde_gescheitert(sit, t, neu)
    if aus is not None:
        return aus

    # Ein nur zu mindestens 60 Prozent passender Name ist noch kein
    # Patientenbeweis. Erst dieses Ja darf die feste Verwaltungsstrecke
    # fortsetzen; Nein startet die Namensaufnahme neu.
    if s["phase"] == "verw_patient_bestaetigen":
        if _bestaetigung_eindeutig(t, "anrufer_check"):
            termin = _gewaehlt(sit)
            if not termin:
                s["phase"] = ""
                s["frage"] = ""
                return _nachname_frage(
                    sit, "Der Kandidat ist nicht mehr eindeutig. Bitte noch einmal:")
            danach = _s(sit.pop("_verwName60Danach", "termin"))
            if danach == "wahl":
                _kandidat_patient_uebernehmen(sit, termin)
                sit["verwDetailQuelle"] = "nameBestaetigt"
                s["phase"] = "wahl"
                s["frage"] = "terminwahl"
                verb = "absagen" if s["modus"] == "absagen" else "verschieben"
                return {"text": (
                    f"Danke. Ich sehe mehrere Termine: "
                    f"{_liste_sprechbar(sit.get('gefunden') or [])}. "
                    f"Welchen möchten Sie {verb}?"
                )}
            sit["_verwName60Bestaetigt"] = True
            _kandidat_patient_uebernehmen(sit, termin)
            s["phase"] = ""
            s["frage"] = ""
            return _bestaetigen(sit, termin, melde)
        if _ablehnung_eindeutig(t, "anrufer_check") or (
                gehirn.ist_ja(t)
                and _BESTAETIGUNG_WIDERSPRUCH_RE.search(t)):
            sit.pop("_verwName60Danach", None)
            if s["modus"] == "auskunft":
                return _kandidat_verwerfen(sit, melde)
            return _kandidat_verwerfen(sit, melde)
        if "?" in t and gehirn.ist_zwischenfrage(t):
            return None
        return _bestaetigung_unklar(
            sit,
            "mit dieser Person fortfahren",
            schluessel="patient",
        )

    # 1) Offene Bestaetigungen zuerst — ein "ja" traegt sonst nichts Neues.
    if s["phase"] == "absage_bestaetigen":
        if "modus" in neu and s["modus"] == "verschieben":
            # "Nicht absagen — verschieben!" mitten in der Rueckfrage.
            termin = _gewaehlt(sit)
            if termin:
                if s["wunsch"]:
                    return _verschieb_angebot(sit, melde)
                return _verschieb_wunsch_frage(sit, termin, melde)
        if _bestaetigung_eindeutig(t):
            return _absagen(sit, melde)
        if _ablehnung_eindeutig(t):
            sit["verwaltenTermin"] = ""
            _verw_reset(sit)
            _verwaltung_mit_abschlussfrage_schliessen(sit)
            return {"text": "Alles klar, der Termin bleibt bestehen. Kann ich sonst noch etwas für Sie tun?"}
        if gehirn.ist_ja(t) and _BESTAETIGUNG_WIDERSPRUCH_RE.search(t):
            return _bestaetigung_unklar(
                sit, "diesen Termin absagen", schluessel="absagen")
        if "?" in t and gehirn.ist_zwischenfrage(t):
            return None
        return _bestaetigung_unklar(
            sit, "diesen Termin absagen", schluessel="absagen")

    if s["phase"] == "verschieb_bestaetigen":
        if "modus" in neu and s["modus"] == "absagen":
            termin = _gewaehlt(sit)
            if termin:
                return _absage_frage(sit, termin)
        if "wunsch" in neu:
            s["slotIso"] = ""
            return _verschieb_angebot(sit, melde)
        if _bestaetigung_eindeutig(t):
            return _verschieben(sit, melde)
        if _ablehnung_eindeutig(t):
            s["slotIso"] = ""
            s["phase"] = "verschieb_wunsch"
            s["frage"] = "wunsch"
            return {"text": "Kein Problem. Wann passt es Ihnen denn besser?"}
        if gehirn.ist_ja(t) and _BESTAETIGUNG_WIDERSPRUCH_RE.search(t):
            return _bestaetigung_unklar(
                sit,
                "den Termin auf die vorgelesene Zeit verschieben",
                schluessel="verschieben",
            )
        if "?" in t and gehirn.ist_zwischenfrage(t):
            return None
        return _bestaetigung_unklar(
            sit,
            "den Termin auf die vorgelesene Zeit verschieben",
            schluessel="verschieben",
        )

    # Mehrfach-Absage rueckbestaetigt? (W-MEHRFACH-ABSAGE)
    if s["phase"] == "mehrfach_bestaetigen":
        if _bestaetigung_eindeutig(t):
            return _mehrfach_absagen(sit, melde)
        if _ablehnung_eindeutig(t):
            sit["mehrfachAbsage"] = []
            s["phase"] = "wahl"
            s["frage"] = "terminwahl"
            return {"text": (
                "Alles klar, es bleibt alles bestehen. Möchten Sie doch einen "
                f"davon absagen? Zur Auswahl: {_liste_sprechbar(sit.get('gefunden') or [])}."
            )}
        if gehirn.ist_ja(t) and _BESTAETIGUNG_WIDERSPRUCH_RE.search(t):
            return _bestaetigung_unklar(
                sit,
                "alle vorgelesenen Termine absagen",
                schluessel="mehrfach-absagen",
            )
        if "?" in t and gehirn.ist_zwischenfrage(t):
            return None
        return _bestaetigung_unklar(
            sit,
            "alle vorgelesenen Termine absagen",
            schluessel="mehrfach-absagen",
        )

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
            # Der äußere Flow antwortet mit dem festen Fortsetzungsanker.
            # Das freie LLM darf in einer Terminwahl nichts erfinden.
            return None
        return {"text": (
            f"Da will ich nichts Falsches erwischen. Zur Auswahl: {_liste_sprechbar(sit['gefunden'])}. "
            + _auswahl_anweisung(sit["gefunden"])
        )}

    # 3) Neuer Zeitpunkt beim Verschieben
    if s["phase"] == "verschieb_angebot" and sit.get("offered"):
        # 3d (Anruf b6c73304): „kein Vormittag“ auf das Verschiebe-Angebot ist
        # eine AUSSCHLUSS-Präferenz, kein Vormittagswunsch. Über
        # slot_praeferenz_aenderung lesen (wie beim Buchen), als harte Grenze
        # in den Wunsch hängen und neu suchen — nie durch parse_slot_wish als
        # Vormittag missdeutet. Nur bei echter Ablehnung/Tageszeit-Korrektur
        # (positive Auswahl bleibt dem Slot-Wähler unten).
        tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
        if tenant.get("slotPraeferenzenFesthalten") is not False:
            offered_isos = [_s(o.get("iso")) for o in sit.get("offered") or [] if _s(o.get("iso"))]
            aenderung = slot_praeferenz_aenderung(t, offered_isos=offered_isos)
            # Nur INHALTLICHE Ausschlüsse (Tageszeit/Wochentag/Datum/Verbund)
            # fangen — NICHT rejectAll/excludeIsos: ein bloßes „Nein.“ bleibt
            # auf dem bewährten Blind-Zähler-Weg weiter unten.
            neg_keys = ("excludeWeekdays", "excludeHourRanges", "excludeHours",
                        "excludeDates", "excludeSpans")
            if aenderung and not _s(aenderung.get("waehle")) and any(
                    aenderung.get(k) for k in neg_keys):
                s["wunsch"] = wunsch_mit_slot_praeferenz(s.get("wunsch"), aenderung)
                sit["verschiebAblehnungBlind"] = 0
                spur.merken(sit, "verschieb-slot-praeferenz",
                            ";".join(k for k in neg_keys if aenderung.get(k)))
                return _verschieb_angebot(sit, melde)
        if fragt_nach_frueherem_slot(t):
            sit["verschiebAblehnungBlind"] = 0
            return {"text": fruehester_slot_antwort(s.get("wunsch"))}
        if will_neu_suchen(t, sit["offered"]):
            sit["verschiebAblehnungBlind"] = 0
            return _verschieb_angebot(sit, melde)
        iso = _slot_wahl(t, sit["offered"])
        if not iso:
            eng = angebot_engen(t, sit["offered"])
            if eng:
                if len(eng) == 1:
                    iso = _s(eng[0].get("iso"))
                else:
                    sit["offered"] = [
                        {"iso": _s(o.get("iso")), "spoken": spoken_slot(_s(o.get("iso")))}
                        for o in eng if _s(o.get("iso"))
                    ]
                    return {"text": spoken_offer(sit["offered"])}
        if iso:
            return _verschieb_readback(sit, iso)
        if "wunsch" in neu:
            sit["verschiebAblehnungBlind"] = 0
            return _verschieb_angebot(sit, melde)
        if gehirn.ist_nein(t):
            blind = int(sit.get("verschiebAblehnungBlind") or 0) + 1
            sit["verschiebAblehnungBlind"] = blind
            if blind < 2:
                return _verschieb_angebot(sit, melde)
            _ablehnte_slots_sperren(sit)
            s["phase"] = "verschieb_wunsch"
            s["frage"] = "wunsch"
            sit["offered"] = []
            return {
                "text": (
                    "Verstanden. Welcher Tag oder welche Tageszeit würde Ihnen besser passen?"
                )
            }
        return None

    if s["phase"] == "verschieb_wunsch":
        if gehirn.ist_nein(t) and sit.get("verwKandidat"):
            return _kandidat_verwerfen(sit, melde)
        if "wunsch" in neu:
            return _verschieb_angebot(sit, melde)
        if not neu:
            return None

    # 4) Kompatibilität für beim Deploy bereits laufende Altsitzungen, die
    # noch die frühere Neubuchungsfrage nach einer Absage offen haben.
    if s["frage"] == "neubuchung":
        if _KEIN_NEUER_TERMIN_RE.search(t):
            s["frage"] = "sonst_noch"
            return {"text": "Alles klar, kein neuer Termin. Kann ich sonst noch etwas für Sie tun?"}
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
        if gehirn.ist_nein(t):
            s["frage"] = "sonst_noch"
            return {"text": "Alles klar, kein neuer Termin. Kann ich sonst noch etwas für Sie tun?"}
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
        if (
            not _hinweis_hat(sit.get("verwHinweis"))
            and (
                intent.ist_bestandsfrage(sit, t)
                or (
                    _UNKLAR_RE.search(t)
                    and re.search(r"\b(?:wann|zeit|datum|termin)\b", t, re.I)
                )
            )
        ):
            # „Wann ist mein Termin?“ trägt naturgemäß gerade KEIN Datum.
            # Nie nach dem vergessenen Wert fragen; Patient/Telefon und bei
            # mehreren Kalendern der Behandler grenzen die Suche ein.
            sit["verwZeitUnbekannt"] = True
    if s["frage"] == "arzt":
        if s.get("arzt") or _UNKLAR_RE.search(t) or sit.get("verwArztNachgefragt"):
            s["frage"] = ""
        else:
            sit["verwArztNachgefragt"] = True
            return {"text": "Bei welchem Behandler ist der Termin eingetragen?"}
    if not s["nachname"] and not s["anruferCheck"] and not s["fuerWen"]:
        agentprofil.anrufer_warten(sit)
        _erkannten_anrufer_direkt_binden(sit, t)
    if not s["nachname"]:
        if s["frage"] in {"name", "nachname", "anrufer_check"} and not neu:
            # Live 06.09.2026 Petsas: LLM fragte "Wie lautet Ihr Name?" und
            # rief list_appointments ohne Patient — hier deterministisch bleiben.
            if s["frage"] == "anrufer_check" and gehirn.anrufer_bekannt(sit):
                return {"text": gehirn.anrufer_check_frage(sit)}
            # Async-Anrufer kam erst NACH der Nachnamen-Frage: direkt binden.
            if (s["frage"] in {"name", "nachname"} and not s["anruferCheck"]
                    and not s["fuerWen"] and gehirn.anrufer_bekannt(sit)):
                if _erkannten_anrufer_direkt_binden(sit, t):
                    return _dispatch(sit, melde)
            return {"text": "Damit ich in den Kalender schauen kann: Wie ist Ihr Nachname?"}
        # Cache-Pfad: Anrufer kommt oft erst async — kurz warten und direkt
        # binden, statt vor der rein lesenden Suche um Erlaubnis zu fragen.
        agentprofil.anrufer_warten(sit)
        if not s["anruferCheck"] and not s["fuerWen"] and gehirn.anrufer_bekannt(sit):
            if _erkannten_anrufer_direkt_binden(sit, t):
                return _dispatch(sit, melde)
        if sit.get("verwZeitUnbekannt"):
            return _ohne_zeit_eingrenzen(sit)
        if _detail_tag(sit):
            behandelt, aus = _detail_dispatch(sit, melde)
            if behandelt:
                return aus
        s["frage"] = "nachname"
        return {"text": "Damit ich in den Kalender schauen kann: Wie ist Ihr Nachname?"}

    if _detail_tag(sit) and not sit.get("verwZeitUnbekannt"):
        behandelt, aus = _detail_dispatch(sit, melde)
        if behandelt:
            return aus

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
            quittung = gehirn.name_quittung(s)
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
