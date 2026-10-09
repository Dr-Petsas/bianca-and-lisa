"""Kalender-Tools: dieselben Cloud Functions wie Lisa, ohne MAS."""

from __future__ import annotations

import json
import hashlib
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from kern.config import CF_BASE, PHONE_CALL_TOKEN, WRITE_LIVE
from kern import notes, patients
from kern import identitaet_merkmale as _im
from kern import phonetik as _phonetik
from kern.slots import (
    FENSTER_TAGE, REGIE_ANGEBOT, parse_slot_wish, pick_slots, spoken_offer,
    spoken_slot, start_iso, such_horizont_tage,
)
from kern.sprech import slot_wort
from kern.tenants import (
    ist_akut_motiv, kalender_von, motiv_von, taugt_als_ersatz,
)

TZ = ZoneInfo("Europe/Berlin")

# W-SUCHFENSTER (14.09.2026): Plattform-Vertrag getFreeTimeSlots — je Aufruf
# hoechstens 20 Zeiten aus 30 Tagen ab startDate (Quelle: appointments.ts,
# maxSlots=20 / firstDaysToSearch=30; ohne Treffer sucht sie selbst 90 Tage
# weiter). Bei offenem Wunsch blaettert `find_slots` bis zu SEITEN_MAX
# weitere Seiten vorwaerts, gedeckelt auf das mandantenscharfe Suchfenster.
SEITE_MAX_SLOTS = 20
try:
    SEITEN_MAX = max(0, int(os.getenv("SLOT_SEITEN", "3") or 3))
except ValueError:
    SEITEN_MAX = 3

NO_CONTEXT = "Ich komme hier gerade nicht an den Kalender. Die Praxis meldet sich zeitnah mit Terminvorschlägen."
NO_CONTEXT_REGIE = "Kein Kalenderkontext in dieser Sitzung. Biete einen Rückruf an, nenne keine erfundenen Zeiten."


def _test_no_write(tenant: dict) -> bool:
    """Sitzungs-lokaler Schreibstopp für Lasttests; WRITE_LIVE bleibt global an."""
    return bool((tenant or {}).get("_testNoWrite"))


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


_CF_CLIENT = httpx.Client(timeout=10.0)

# Schreibende Cloud Functions (buchen/absagen/verschieben) duerfen laenger
# brauchen (SMS-Versand, Reminder). Vorfall 27.08.2026: masBookAppointment
# brauchte >10 s, der Client brach ab, die Buchung LANDETE trotzdem — und die
# Ansage behauptete "Termin ist weg". Timeout-Budget: CF-Limit ist 30 s.
_SCHREIB_TIMEOUT = 25.0
# Buchungs-Write plus unabhängige Rücklese dürfen den Telefonzug nicht
# minutenlang blockieren. Nach Ablauf dieses Gesamtbudgets bleibt der Slot
# gesperrt und der Vorgang geht als "möglicherweise gebucht" in die manuelle
# Prüfung — niemals in einen zweiten Schreibversuch.
try:
    _BOOK_TOTAL_BUDGET_S = max(
        5.0, float(os.getenv("BOOK_TOTAL_BUDGET_S", "30") or 30)
    )
except ValueError:
    _BOOK_TOTAL_BUDGET_S = 30.0
# HTTP-200 ist noch kein Beweis, dass exakt der angeforderte Termin in der
# Kartei steht. Kurze Nachlese-Retries fangen Replikationslatenz ab; der
# Anrufer hört währenddessen bereits den Werkzeug-Füller.
_BOOK_VERIFY_DELAYS = (0.0, 0.2, 0.45)
# Schreibantworten koennen nach einem Timeout trotzdem im Kalender gelandet
# sein. Bei Absage/Verschieben wird dann ueber die punktgenaue Termin-ID
# nachgelesen, statt einen tatsaechlich ausgefuehrten Write als Fehler zu
# melden. Der erste CF-Aufruf wird dabei niemals wiederholt.
_MANAGEMENT_RECOVERY_DELAYS = (0.0, 0.4)
MANAGEMENT_WRITE_RECOVERY = (
    os.getenv("MANAGEMENT_WRITE_RECOVERY", "1") or "1"
).strip().lower() not in {"0", "false", "off", "no"}
# W-BUCHUNG-BEWEIS (15.09.2026): erreicht die namensbasierte Ruecklese die
# richtige Akte nicht, beweist ein zweiter Weg ueber die patientId. 0 =
# byte-identisches Verhalten von vor dem 15.09.2026 (nur Namensliste).
BOOK_VERIFY_AKTE = (os.getenv("BOOK_VERIFY_AKTE", "1") or "1").strip() != "0"
# W-AKTE-HANDY (15.09.2026): sagt die Plattform needs_phone, obwohl Bianca eine
# rueckbestaetigte Handynummer in der Hand hat, wird sie in die Akte geschrieben
# und EINMAL neu gebucht. 0 = Verhalten von vor dem 15.09.2026 (nur nachfragen).
BOOK_FIX_PHONE = (os.getenv("BOOK_FIX_PHONE", "1") or "1").strip() != "0"
# W-ERSATZ-MOTIV (15.09.2026): als Ausweich fuer ein leeres Spezialfenster
# taugt nur ein echter Kontroll-/Vorsorge-Termin. 0 = Verhalten von vor dem
# 15.09.2026 (jedes harmlos klingende Motiv durfte einspringen).
_ERSATZ_STRENG = (os.getenv("MOTIV_ERSATZ_STRENG", "1") or "1").strip() != "0"
# W-VERWALTUNG-TERMIN-ZUERST (16.09.2026): Absagen/Verschieben duerfen einen
# bekannten Bestandstermin nach Datum/Uhrzeit direkt im Standortkalender
# suchen. Der Buchungsweg und die Terminauskunft benutzen diesen Pfad nicht.
VERWALTUNG_TERMIN_DETAILS = (
    os.getenv("VERWALTUNG_TERMIN_DETAILS", "1") or "1"
).strip().lower() not in {"0", "false", "off", "no"}

# W-TOOL-UI (02.09.2026): freie Slots in der Gespraechsansicht nicht
# endlos speichern — erste N reichen zur Diagnose, Rest als total.
_SLOT_CAP = 40


def _cf_post(route: str, body: dict, *, timeout: float | None = None) -> tuple[int, Any]:
    url = f"{CF_BASE}/{route.lstrip('/')}"
    headers = None
    route_name = route.strip("/")
    name_confirm_write = (
        route_name == "agentNameConfirm"
        or (
            route_name in {"masBookAppointment", "createAppointment"}
            and body.get("skipConfirmation") is True
        )
    )
    if name_confirm_write and PHONE_CALL_TOKEN:
        # Jede Reservierungsoperation, die die normale Patientenbestaetigung
        # bewusst ueberspringt, muss als TelefonKI-Maschine authentifiziert
        # sein. Gewoehnliche Kalenderaufrufe erhalten den Secret nie.
        headers = {
            "Authorization": f"Bearer {PHONE_CALL_TOKEN}",
            "x-pickadoc-phone-call-token": PHONE_CALL_TOKEN,
        }
    try:
        r = _CF_CLIENT.post(
            url, json=body, timeout=timeout or 10.0, headers=headers)
        try:
            data = r.json()
        except Exception:
            data = None
        return r.status_code, data
    except httpx.HTTPError as e:
        return 0, {"message": str(e)}


def _response_kappen(data: Any) -> Any:
    """Antwort fuer die Tool-Anzeige schlank halten (Slot-Listen)."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    nutz = out.get("data")
    if not isinstance(nutz, dict):
        return out
    nutz = dict(nutz)
    raw = nutz.get("free_time_slots")
    slots: list | None
    if isinstance(raw, str):
        try:
            slots = json.loads(raw)
        except json.JSONDecodeError:
            slots = None
    elif isinstance(raw, list):
        slots = raw
    else:
        slots = None
    if isinstance(slots, list):
        if len(slots) > _SLOT_CAP:
            nutz["free_time_slots"] = slots[:_SLOT_CAP]
            nutz["free_time_slots_total"] = len(slots)
        else:
            nutz["free_time_slots"] = slots
        out["data"] = nutz
    return out


_DISPATCH_SECRET_KEYS = {
    "authorization", "x-api-key", "x-pickadoc-phone-call-token",
    "nameconfirmtoken", "token", "signature",
}


def _dispatch_saeubern(value: Any, *, key: str = "") -> Any:
    """Secrets aus Diagnose-/Mitschnittdaten entfernen.

    Der Namenslink-Token ist ein Bearer-Link und darf weder im Tool-Ledger
    noch im Gesprächsmitschnitt landen. Die echte Anfrage bleibt davon
    unberührt; nur die Diagnosekopie wird redigiert.
    """
    if key.casefold() in _DISPATCH_SECRET_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(k): _dispatch_saeubern(v, key=str(k))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_dispatch_saeubern(v, key=key) for v in value]
    if isinstance(value, str) and "agentNameConfirm?t=" in value:
        return re.sub(
            r"([?&]t=)[^&#\s]+", r"\1[REDACTED]", value, flags=re.I
        )
    return value


def _updates_von_antwort(data: Any) -> list[dict[str, Any]]:
    """Dynamic-Variable-Updates wie im Portal: gesetzte Antwort-Felder."""
    if not isinstance(data, dict):
        return []
    nutz = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(nutz, dict):
        return []
    aus: list[dict[str, Any]] = []
    for key in (
        "free_time_slots", "doctor_name", "visit_motive_name", "visit_motive_id",
        "request_id", "code_version", "any_doctor_preference", "appointmentId",
    ):
        if key not in nutz:
            continue
        val = nutz.get(key)
        if val in (None, "", [], {}):
            continue
        if key == "free_time_slots" and isinstance(val, list):
            total = nutz.get("free_time_slots_total") or len(val)
            kurz = val[:6]
            aus.append({"key": key, "from": "", "to": kurz, "total": total})
        else:
            aus.append({"key": key, "from": "", "to": val})
    return aus


def _cf_call(route: str, body: dict, *, timeout: float | None = None) -> tuple[int, Any, dict]:
    """Wie _cf_post, plus Dispatch-Meta fuer die Unterhaltungs-Anzeige."""
    url = f"{CF_BASE}/{route.lstrip('/')}"
    t0 = time.perf_counter()
    status, data = _cf_post(route, body, timeout=timeout)
    ms = int(round((time.perf_counter() - t0) * 1000))
    gekappt = _dispatch_saeubern(_response_kappen(data))
    dispatch = {
        "route": route,
        "url": url,
        "method": "POST",
        "request": _dispatch_saeubern(body),
        "httpStatus": status,
        "ms": ms,
        "response": gekappt,
        "updates": _updates_von_antwort(gekappt),
    }
    return status, data, dispatch


def _mit_dispatch(result: dict[str, Any], dispatch: dict | None) -> dict[str, Any]:
    if dispatch:
        result["dispatch"] = dispatch
    return result


def _kontrolle_ersatz(tenant: dict, such: dict) -> dict | None:
    """Ersatz-Suchkontext mit dem Kontroll-Motiv — oder None, wenn es keinen
    sinnvollen Ersatz gibt (kein Kontroll-Motiv, schon Kontrolle, Akut)."""
    vm = motiv_von(tenant, "Kontrolluntersuchung")
    alt_id = _s((vm or {}).get("id"))
    # Nie auf Notfall/Akut ausweichen, nur weil das Spezialfenster leer war
    # (Blessing/Thaler: visitMotives[0] = Akutsprechstunde).
    if not alt_id or alt_id == _s(such.get("visitMotiveId")) or ist_akut_motiv(vm):
        return None
    # W-ERSATZ-MOTIV (15.09.2026): fuehrt die Praxis gar kein Kontroll-Motiv,
    # lieferte motiv_von den ersten harmlos KLINGENDEN Eintrag — bei Ruether
    # "GYN Endometriose Erstberatung" (45 min) fuer eine Krebsvorsorge. Ein
    # Ersatz muss wirklich ein Kontroll-/Vorsorge-Termin sein; sonst gibt es
    # keinen, und der Anrufer hoert ehrlich, dass das telefonisch nicht geht.
    if _ERSATZ_STRENG and not taugt_als_ersatz(vm):
        return None
    alt = dict(such)
    alt["visitMotiveId"] = alt_id
    alt["visitMotiveName"] = _s((vm or {}).get("name")) or "Kontrolluntersuchung"
    return alt


def _nicht_telefonisch(tenant: dict, such: dict) -> str:
    """Name des Wunsch-Motivs, wenn es die Praxis NICHT online vergibt.

    `allowOnlineBooking=false` sperrt in der Plattform auch den Telefon-Agenten
    — die CF liefert dafuer nie Zeiten. Ohne tauglichen Ersatz (W-ERSATZ-MOTIV)
    ist "im Moment leider kein freier Termin" die falsche Auskunft: es wird
    nicht kurzfristig einer frei. Der Anrufer soll den echten Grund hoeren.
    """
    mid = _s(such.get("visitMotiveId"))
    if not mid:
        return ""
    # Der Aufrufer kennt den frischen Sitzungs-Katalog (masVisitMotives) und
    # sagt die Buchbarkeit ausdruecklich — tenant["visitMotives"] fuehrt oft
    # nur einen Ausschnitt (Ruether: 10 von 31).
    if such.get("visitMotiveOnline") is False:
        return _s(such.get("visitMotiveName")) or "diese Terminart"
    vms = tenant.get("visitMotives") if isinstance(tenant.get("visitMotives"), list) else []
    for vm in vms:
        if _s(vm.get("id")) != mid:
            continue
        # NUR ein ausdrueckliches False sperrt. Die lokalen tenants/*.json
        # (MedDent, Thaler) fuehren das Feld gar nicht — ein fehlender Wert
        # darf den Anrufer nie mit "vergebe ich telefonisch nicht" abweisen.
        if vm.get("allowOnlineBooking") is not False:
            return ""
        return _s(vm.get("nameForPatient")) or _s(vm.get("name")) or _s(such.get("visitMotiveName"))
    return ""


def _mit_motiv_fallback(found: dict[str, Any], such: dict) -> dict[str, Any]:
    found["motivFallback"] = "kontrolle"
    found["motivOriginal"] = {
        "id": _s(such.get("visitMotiveId")),
        "name": _s(such.get("visitMotiveName")),
    }
    return found


def find_slots_behandler(tenant: dict, ctx: dict, *, start_date: str = "",
                         source: str = "", motiv_fallback: bool = True,
                         wish: dict | None = None) -> dict[str, Any]:
    """Slots NUR in diesem Kalender. Leeres Motiv-Fenster → Kontrolle.

    Chef 08.09.2026 (Lülf): die Praxis war frei, PAR-AIT-geschlossen lieferte
    []. Gesucht wird am Behandler, unabhängig vom Spezialgrund. Nie andere
    Ärzte, ausser der Anrufer fragt ausdrücklich danach (dann steht deren
    calendarId im ctx).

    W-MOTIV-KONSISTENT (14.09.2026, MedDent-Anruf 06:0x): GEBUCHT wird mit
    dem Motiv, das die Zeiten geliefert hat — nicht mehr mit dem Original.
    masBookAppointment prueft die Verfuegbarkeit je Motiv (isSlotAvailable ->
    getFreeTimeSlots mit visitMotiveId); ein Motiv ohne Fenster/ohne
    allowOnlineBooking liefert dort [] und die Buchung scheitert mit "The
    slot is not available." — genau so lief es live: gesucht mit Kontrolle,
    gebucht mit dem Notfall-Pseudo-Motiv, Anrufer bekam nach "Ja" nur
    "Termin ist gerade weg". Die Antwort traegt deshalb ``motivFallback`` +
    ``motivOriginal``; `gehirn.motiv_fallback_merken` pinnt das Ersatz-Motiv
    im Sammler, der O-Ton landet in der Terminnotiz.
    """
    such = dict(ctx or {})
    found = find_slots(tenant, such, start_date=start_date, egal=False, source=source, wish=wish)
    if not found.get("ok"):
        return found
    slots = _iso_liste(found.get("slots") or [])
    if slots:
        return found
    if not motiv_fallback:
        return found
    alt = _kontrolle_ersatz(tenant, such)
    if not alt:
        gesperrt = _nicht_telefonisch(tenant, such)
        if gesperrt:
            found["motivNichtTelefonisch"] = gesperrt
        return found
    zweit = find_slots(tenant, alt, start_date=start_date, egal=False, source=source, wish=wish)
    if zweit.get("ok") and _iso_liste(zweit.get("slots") or []):
        return _mit_motiv_fallback(zweit, such)
    return found


def find_slots_raeume(tenant: dict, ctx: dict, raeume: list, *,
                      start_date: str = "", source: str = "",
                      motiv_fallback: bool = True,
                      wish: dict | None = None) -> dict[str, Any]:
    """Slots nacheinander in den gegebenen Zimmern — erster Treffer gewinnt.

    Thaler: PZR Zimmer 3 dann 2, Notfall 1, Behandlung 4. Die Antwort
    traegt ``calendar``, damit die Buchung denselben Raum trifft.

    W-SUCHFENSTER (14.09.2026, Anruf da746a65): liefert KEIN Zimmer Zeiten
    fuer das Wunsch-Motiv, laeuft — wie bei `find_slots_behandler` — eine
    zweite Runde mit dem Kontroll-Motiv ueber dieselben Zimmer (Antwort
    traegt ``motivFallback`` + ``motivOriginal``, gebucht wird mit dem
    Ersatz, der O-Ton landet in der Notiz). Vorher endete der Zimmer-Weg
    still in "kein freier Termin" + Rueckruf, waehrend der Behandler-Weg
    laengst Kontrolle angeboten haette.
    """
    letzter: dict[str, Any] = {"ok": False, "slots": []}
    kandidaten = [
        cal for cal in (raeume or [])
        if isinstance(cal, dict) and _s(cal.get("id"))
    ]
    runden: list[tuple[dict, bool]] = [(dict(ctx or {}), False)]
    gesperrt = ""
    if motiv_fallback:
        alt = _kontrolle_ersatz(tenant, dict(ctx or {}))
        if alt:
            runden.append((alt, True))
        else:
            gesperrt = _nicht_telefonisch(tenant, dict(ctx or {}))
    for basis, ersatz in runden:
        for cal in kandidaten:
            such = dict(basis)
            such["calendarId"] = cal["id"]
            such["calendarName"] = _s(cal.get("name"))
            found = find_slots(
                tenant, such, start_date=start_date, egal=False, source=source, wish=wish)
            if found.get("ok") and _iso_liste(found.get("slots") or []):
                found["calendar"] = {
                    "id": cal["id"],
                    "name": _s(cal.get("name")),
                }
                if ersatz:
                    _mit_motiv_fallback(found, dict(ctx or {}))
                return found
            if not ersatz or not letzter.get("ok"):
                letzter = found
    if letzter.get("ok") and not letzter.get("calendar"):
        erster = next(
            (c for c in (raeume or [])
             if isinstance(c, dict) and _s(c.get("id"))),
            None,
        )
        if erster:
            letzter["calendar"] = {
                "id": erster["id"],
                "name": _s(erster.get("name")),
            }
    if gesperrt and not _iso_liste(letzter.get("slots") or []):
        letzter["motivNichtTelefonisch"] = gesperrt
    return letzter


def _wunsch_gedeckt(slots: list, wish: dict | None) -> bool:
    """Deckt der Vorrat den Wunsch (Tag/Zeitraum/Wochentag/Uhrzeit) ab?"""
    isos = _iso_liste(slots or [])
    if not wish:
        return bool(isos)
    if not isos:
        return False
    return bool(pick_slots(isos, wish=wish).get("wishMatched"))


def _tag_plus(iso_tag: str, tage: int) -> str:
    return (date.fromisoformat(iso_tag[:10]) + timedelta(days=tage)).isoformat()


def _naechste_seite(page_start: str, slots: list[str], heute: str) -> str:
    """Startdatum der Folgeseite — oder "" (Plattform-Fenster ausgeschoepft).

    Plattform-Vertrag (getFreeTimeSlots, appointments.ts): eine Seite =
    hoechstens ``SEITE_MAX_SLOTS`` Zeiten aus 30 Tagen ab startDate; ohne
    Treffer sucht sie selbst die 90 Tage danach (Tag 30-120, wieder auf 20
    gekappt). Kommen also 20 Zeiten, ist die Liste am letzten Tag gekappt
    (dort weitermachen, Dubletten filtert der Aufrufer); kommen weniger,
    ist das durchsuchte Fenster komplett — 30 Tage, oder 120 Tage, wenn die
    letzte Zeit schon hinter Tag 30 liegt (dann lief der 90-Tage-Weg);
    kommt nichts, hat die Plattform 120 Tage gesehen — Schluss.
    """
    if not slots:
        basis = (page_start or heute)[:10]
        naechster = _tag_plus(basis, 120)
        return naechster if naechster > basis else ""
    basis = (page_start or heute)[:10]
    letzter = max(str(x)[:10] for x in slots)
    if len(slots) >= SEITE_MAX_SLOTS:
        naechster = letzter if letzter > basis else _tag_plus(basis, 1)
    elif letzter > _tag_plus(basis, 30):
        naechster = _tag_plus(basis, 120)
    else:
        naechster = _tag_plus(basis, 30)
    return naechster if naechster > basis else ""


def find_slots(tenant: dict, ctx: dict, *, start_date: str = "", egal: bool = False,
               source: str = "", wish: dict | None = None) -> dict[str, Any]:
    """Freie Zeiten der Plattform — bei offenem Wunsch seitenweise vorwaerts.

    W-SUCHFENSTER (14.09.2026, Anrufe da746a65/5aa87268): die Plattform
    liefert je Aufruf hoechstens 20 Zeiten aus 30 Tagen — bei vollem
    Kalender endete der Vorrat mitten im laufenden Monat, und "am Donnerstag
    nachmittags" oder "Ende Oktober" hiess "kein freier Termin". Ist ein
    ``wish`` uebergeben, das die erste Seite nicht deckt, holt die Suche bis
    zu ``SEITEN_MAX`` weitere Seiten (Startdatum wandert vor), gedeckelt auf
    das mandantenscharfe Suchfenster ab heute. Auch eine leere erste Seite
    wird weitergeblättert, damit späte Termine nicht unsichtbar bleiben.
    ``dispatch`` traegt die erste Seite plus ``seiten`` (Startdatum und
    Trefferzahl je Seite) fuer die Gespraechsansicht.
    """
    heute = datetime.now(TZ).date().isoformat()
    if start_date and start_date[:10] < heute:
        start_date = heute
    if not start_date and wish:
        auto = start_iso(wish)
        # Relative Abstände dürfen die erste Kalenderseite direkt am
        # gewünschten Vorlauf öffnen. Konkrete Datumswünsche bleiben beim
        # bisherigen Seitenvertrag, damit vorhandene Slots mitkommen.
        if auto and not wish.get("date") and not wish.get("tage") and not wish.get("von"):
            start_date = auto
    erste = _find_slots_seite(tenant, ctx, start_date=start_date, egal=egal, source=source)
    if not erste.get("ok"):
        return erste
    if not wish and _iso_liste(erste.get("slots") or []):
        return erste
    slots = list(erste.get("slots") or [])
    seite_slots = _iso_liste(slots)  # Zeiten der zuletzt geladenen Seite
    seiten = [{"startDate": start_date or heute, "n": len(slots)}]
    horizont = _tag_plus(heute, such_horizont_tage(tenant, wish))
    page_start = start_date or heute
    ctx_seite = dict(ctx or {})
    if egal:
        # "egal": die Plattform hat den schnellsten Arzt gewaehlt (doctor_name)
        # — die Folgeseiten blaettern in DESSEN Kalender, statt neu zu wuerfeln.
        gewinner = kalender_von(tenant, _s(erste.get("doctorName")).split(",")[0].strip())
        if gewinner and _s(gewinner.get("id")):
            ctx_seite["calendarId"] = gewinner["id"]
            ctx_seite["calendarName"] = _s(gewinner.get("name"))
    bekannt = {x[:16] for x in seite_slots}
    while len(seiten) <= SEITEN_MAX and not _wunsch_gedeckt(slots, wish):
        naechster = _naechste_seite(page_start, seite_slots, heute)
        if not naechster or naechster > horizont:
            break
        weitere = _find_slots_seite(
            tenant, ctx_seite, start_date=naechster, egal=False, source=source)
        seite_slots = _iso_liste(weitere.get("slots") or []) if weitere.get("ok") else []
        seiten.append({"startDate": naechster, "n": len(seite_slots)})
        if not seite_slots:
            break
        for x in weitere.get("slots") or []:
            key = str(x).replace(" ", "T")[:16] if isinstance(x, str) else ""
            if not key:
                iso = _iso_liste([x])
                key = iso[0][:16] if iso else ""
            if key and key not in bekannt:
                slots.append(x)
                bekannt.add(key)
        page_start = naechster
    erste["slots"] = slots
    if isinstance(erste.get("dispatch"), dict) and len(seiten) > 1:
        erste["dispatch"]["seiten"] = seiten
    return erste


def _find_slots_seite(tenant: dict, ctx: dict, *, start_date: str = "", egal: bool = False,
               source: str = "") -> dict[str, Any]:
    body = {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "source": _s(source) or "telefonki-lisa",
    }
    cal = None
    if egal:
        # "Arzt egal": KEINEN Kalender mitschicken — die Cloud Function probt
        # dann alle zulaessigen Kalender und nimmt den global fruehesten
        # (anyDoctorPreference). Welcher Arzt gewonnen hat, steht in der
        # Antwort als doctor_name.
        cal = None
    elif _s(ctx.get("calendarId")):
        cal = {"id": ctx["calendarId"], "name": ctx.get("calendarName")}
    else:
        cal = kalender_von(tenant, _s(ctx.get("calendarName") or ctx.get("doctorName")))
    if cal and cal.get("id"):
        body["calendarId"] = cal["id"]
    vm = None
    if _s(ctx.get("visitMotiveId")):
        vm = {"id": ctx["visitMotiveId"], "name": ctx.get("visitMotiveName")}
    else:
        vm = motiv_von(tenant, _s(ctx.get("visitMotiveName")))
    if vm and vm.get("id"):
        body["visitMotiveId"] = vm["id"]
    if _s(ctx.get("visitMotiveName")):
        body["visitMotiveName"] = _s(ctx.get("visitMotiveName"))
    elif vm and vm.get("name"):
        body["visitMotiveName"] = vm["name"]
    # W-FENSTERENDE (17.09.2026, Befund A7): startDate IMMER senden. Ohne
    # startDate rechnet die Plattform (appointmentsService.getFreeTimeSlots)
    # das Fensterende als "jetzt + 30 Tage" MIT Uhrzeit: der Kalkulator
    # erzeugt fuer Tag 30 den GANZEN Tag, geladen sind die Termine aber nur
    # bis zur Anruf-Uhrzeit — alles danach ist ein Phantom, das
    # isSlotAvailable beim Buchen verwirft ("The slot is not available.",
    # 6 von 8 Buchungsfehlern lagen exakt auf Tag 30). Mit startDate rechnet
    # die Plattform ab Berlin-Mitternacht, Tag 30 faellt komplett heraus.
    heute = datetime.now(TZ).date().isoformat()
    # Letzte harte Grenze direkt vor dem Cloud-Function-Aufruf. Aufrufer wie
    # Hintergrund-Vorrat, Wiederangebot und Verschiebe-Alternative dürfen
    # auch mit einem alten Sitzungsstand niemals in der Vergangenheit suchen.
    body["startDate"] = max(_s(start_date)[:10] or heute, heute)
    status, data, dispatch = _cf_call("getFreeTimeSlots", body)
    if status == 200 and isinstance(data, dict) and data.get("status") == "success":
        nutz = data.get("data") or {}
        raw = nutz.get("free_time_slots")
        try:
            slots = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except json.JSONDecodeError:
            slots = []
        return _mit_dispatch({
            "ok": True, "slots": slots, "calendar": cal, "motive": vm,
            # Bei "egal" waehlt der Server den Kalender — der Name des
            # Gewinner-Arztes kommt hier zurueck (fuers Buchen + Ansagen).
            "doctorName": _s(nutz.get("doctor_name")),
        }, dispatch)
    return _mit_dispatch({
        "ok": False,
        "error": (data or {}).get("message") if isinstance(data, dict) else f"http_{status}",
    }, dispatch)


def _iso_liste(raw) -> list[str]:
    out = []
    for x in raw or []:
        if isinstance(x, str) and "T" in x:
            out.append(x.replace(" ", "T"))
        elif isinstance(x, dict):
            iso = _s(x.get("iso") or x.get("start") or x.get("appointmentStartDate"))
            if iso:
                out.append(iso.replace(" ", "T"))
    return out


def vorrat_fuellen(sit: dict) -> list[dict[str, str]]:
    """Freie Plätze vor dem Gespräch laden — offer_slots greift zuerst hierhin."""
    tenant = sit["tenant"]
    ctx = sit.setdefault("booking", {})
    if not _s(ctx.get("visitMotiveId")):
        vm = motiv_von(tenant, _s(ctx.get("visitMotiveName")) or "Kontrolluntersuchung")
        if vm:
            ctx["visitMotiveId"] = _s(vm.get("id"))
            ctx["visitMotiveName"] = _s(vm.get("name")) or ctx.get("visitMotiveName")
    found = find_slots(tenant, ctx)
    isos = _iso_liste(found.get("slots") or [])
    sit["slotVorrat"] = isos
    ctx["slotVorrat"] = isos
    picked = pick_slots(isos)
    offered = [{"iso": x["iso"], "spoken": spoken_slot(x["iso"])} for x in picked["slots"]]
    sit["offered"] = offered
    return offered


def slots_zeile(offered: list | None) -> str:
    if not offered:
        return ""
    teile = [
        f"{_s(x.get('iso'))} = {_s(x.get('spoken'))}"
        for x in offered
        if x.get("iso") and x.get("spoken")
    ]
    if not teile:
        return ""
    return (
        "Schon geladen — sprich nur den Text rechts vom Gleichheitszeichen, "
        "gebucht wird mit dem iso links davon: " + "; ".join(teile)
    )


def offer_slots(tenant: dict, ctx: dict, *, wish_text: str = "", exclude_iso: str = "",
                exclude_isos: list | set | None = None,
                start_date: str = "") -> dict[str, Any]:
    if not _s(ctx.get("patientId")) and not _s(ctx.get("patientName")):
        return {"ok": False, "spoken": NO_CONTEXT, "regie": NO_CONTEXT_REGIE}
    if not _s(ctx.get("visitMotiveId")) and not _s(ctx.get("visitMotiveName")):
        ctx["visitMotiveName"] = "Kontrolluntersuchung"
    wish = parse_slot_wish(wish_text) if wish_text else None
    vorrat = list(ctx.get("slotVorrat") or [])
    gesperrt = list(exclude_isos or []) or list(ctx.get("slotGesperrt") or [])
    # Explizites Startdatum bedeutet: frische Alternativen AB diesem Tag.
    # Ein alter Vorrat aus dem laufenden Gespräch darf das nicht überstimmen.
    nachladen = bool(_s(start_date)) or not vorrat
    if wish and wish.get("date") and vorrat:
        if not any(str(iso).startswith(wish["date"]) for iso in vorrat):
            nachladen = True
    if nachladen:
        start = _s(start_date) or (wish or {}).get("date") or (wish or {}).get("von") or ""
        found = find_slots(tenant, ctx, start_date=start, wish=wish)
        if not found.get("ok") and not vorrat:
            return _mit_dispatch({
                "ok": False,
                "spoken": "Der Kalender antwortet gerade nicht. Die Praxis meldet sich kurzfristig mit Terminvorschlägen.",
                "regie": "Keine Zeiten erfinden. Rückruf anbieten.",
            }, found.get("dispatch") if isinstance(found.get("dispatch"), dict) else None)
        if found.get("ok"):
            vorrat = _iso_liste(found.get("slots") or [])
            ctx["slotVorrat"] = vorrat
            picked = pick_slots(vorrat, wish=wish, exclude_iso=exclude_iso, exclude_isos=gesperrt)
            slots = [{"iso": x["iso"], "spoken": spoken_slot(x["iso"])} for x in picked["slots"]]
            return _mit_dispatch({
                "ok": True,
                "spoken": spoken_offer(picked["slots"], wish_matched=picked["wishMatched"]),
                "regie": REGIE_ANGEBOT,
                "slots": slots,
            }, found.get("dispatch") if isinstance(found.get("dispatch"), dict) else None)
    picked = pick_slots(vorrat, wish=wish, exclude_iso=exclude_iso, exclude_isos=gesperrt)
    slots = [{"iso": x["iso"], "spoken": spoken_slot(x["iso"])} for x in picked["slots"]]
    return {
        "ok": True,
        "spoken": spoken_offer(picked["slots"], wish_matched=picked["wishMatched"]),
        "regie": REGIE_ANGEBOT,
        "slots": slots,
    }


def _slot_key(value: Any) -> str:
    return _s(value).replace(" ", "T")[:16]


def _slot_gesperrt(ctx: dict, iso: str) -> bool:
    key = _slot_key(iso)
    return bool(key and key in {
        _slot_key(value) for value in (ctx.get("slotGesperrt") or [])
        if _slot_key(value)
    })


def _slot_sperren(ctx: dict, iso: str) -> str:
    """Konflikt-Slot sofort sperren und jeden alten Vorrat verwerfen."""
    key = _slot_key(iso)
    gesperrt = list(ctx.get("slotGesperrt") or [])
    if key and key not in {_slot_key(value) for value in gesperrt}:
        gesperrt.append(iso)
    ctx["slotGesperrt"] = gesperrt
    ctx["slotVorrat"] = []
    return key


def _book_deadline() -> float:
    return time.monotonic() + _BOOK_TOTAL_BUDGET_S


def _book_timeout(deadline: float, cap: float = 10.0) -> float:
    return max(0.1, min(cap, deadline - time.monotonic()))


def _book_budget_left(deadline: float, minimum: float = 0.15) -> bool:
    return (deadline - time.monotonic()) >= minimum


def _name_confirm_scoped_id(
    prefix: str, tenant: dict, token: str
) -> str:
    """Derselbe stabile ID-Vertrag wie bookingReservationGuard.ts."""
    scope = "\0".join((
        prefix,
        _s(tenant.get("clientId")),
        _s(tenant.get("locationId")),
        _s(token),
    ))
    digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:40]
    return f"{prefix}_{digest}"


def _booking_uncertain(
    ctx: dict,
    iso: str,
    *,
    dispatch: dict | None = None,
    reason: str = "verification_inconclusive",
) -> dict[str, Any]:
    """Unklaren Write verriegeln — nie denselben oder einen anderen Slot schreiben."""
    ctx["bookingUncertain"] = {
        "iso": iso,
        "reason": reason,
        "at": datetime.now(TZ).isoformat(timespec="seconds"),
    }
    result: dict[str, Any] = {
        "ok": False,
        "booked": False,
        "writeAttempted": True,
        "verificationFailed": True,
        "possiblyBooked": True,
        "slotIso": iso,
        "spoken": (
            "Ich kann gerade nicht sicher bestätigen, ob der Termin "
            "eingetragen wurde. Ich versuche keine zweite Buchung; "
            "die Praxis prüft den Vorgang und meldet sich bei Ihnen."
        ),
        "regie": (
            "Buchungsantwort unklar. Sitzung verriegelt; keinen weiteren "
            "Buchungsversuch senden."
        ),
        "uncertaintyReason": reason,
    }
    return _mit_dispatch(result, dispatch)


def _booking_uncertainty_guard(ctx: dict) -> dict[str, Any] | None:
    pending = ctx.get("bookingUncertain")
    if not isinstance(pending, dict):
        return None
    iso = _s(pending.get("iso"))
    return {
        "ok": False,
        "booked": False,
        "writeAttempted": False,
        "verificationFailed": True,
        "possiblyBooked": True,
        "slotIso": iso,
        "spoken": (
            "Die vorherige Buchung wird bereits von der Praxis geprüft. "
            "Ich starte keinen weiteren Buchungsversuch."
        ),
        "regie": "Sitzung nach unklarer Buchung verriegelt.",
    }


def _booking_uncertainty_clear(ctx: dict) -> None:
    ctx.pop("bookingUncertain", None)


def _frische_konflikt_slots(tenant: dict, ctx: dict, iso: str) -> dict[str, Any]:
    """Alternativen nach einem Konflikt ausschließlich frisch nachladen."""
    _slot_sperren(ctx, iso)
    start = max(
        _slot_key(iso)[:10] if len(_slot_key(iso)) >= 10 else "",
        datetime.now(TZ).date().isoformat(),
    )
    return offer_slots(
        tenant,
        ctx,
        exclude_iso=iso,
        exclude_isos=ctx.get("slotGesperrt") or [],
        start_date=start,
    )


def book_slot(tenant: dict, ctx: dict, *, slot_iso: str = "") -> dict[str, Any]:
    iso = _s(slot_iso) or _s(ctx.get("slotIso"))
    if len(iso) < 16:
        return {
            "ok": False,
            "spoken": "Welcher Termin soll es sein?",
            "regie": "Zeitpunkt fehlt. Erst offer_slots, dann book_slot mit dem unveränderten iso.",
        }
    auftrag = _s(ctx.get("slotIso"))
    if auftrag and iso[:16] != auftrag[:16]:
        if iso[4:16] == auftrag[4:16]:
            iso = auftrag
    uncertainty = _booking_uncertainty_guard(ctx)
    if uncertainty:
        return uncertainty
    if _slot_gesperrt(ctx, iso):
        alt = _frische_konflikt_slots(tenant, ctx, iso)
        return {
            "ok": False,
            "booked": False,
            "slotTaken": True,
            "alreadyBlocked": True,
            "writeAttempted": False,
            "blockedIso": iso,
            "spoken": "Dieser Termin ist bereits vergeben. " + (alt.get("spoken") or ""),
            "regie": REGIE_ANGEBOT,
            "slots": alt.get("slots") or [],
            "alternativeDispatch": alt.get("dispatch"),
        }
    deadline = _book_deadline()
    if not WRITE_LIVE or _test_no_write(tenant):
        when = spoken_slot(iso)
        return {
            "ok": True,
            "booked": False,
            "dryRun": True,
            "slotIso": iso,
            "spoken": (
                f"{when} hätte ich jetzt eingetragen — der Test schreibt den Kalender "
                "noch nicht. Keine Bestätigungs-SMS."
            ),
        }
    patient_id = _s(ctx.get("patientId"))
    created_patient = False
    if ctx.get("skipConfirmation") is True and not patient_id:
        # Eine Link-Reservierung hat absichtlich noch keine belastbaren
        # Patientendaten. Niemals nach dem Platzhalternamen suchen: sonst
        # könnten zwei Anrufer dieselbe "Reservierung SMS"-Akte teilen.
        token = _s(ctx.get("nameConfirmToken"))
        confirmed_phone = _s(ctx.get("phoneConfirmed"))
        if not token:
            return {
                "ok": False,
                "booked": False,
                "writeAttempted": False,
                "spoken": "Der sichere Bestätigungslink fehlt. Ich buche noch nicht.",
                "regie": "Namenslink-Reservierung ohne Token abgebrochen.",
            }
        if not confirmed_phone or not patients.ist_handy_de(confirmed_phone):
            return {
                "ok": False,
                "booked": False,
                "phonePreflightFailed": True,
                "writeAttempted": False,
                "spoken": (
                    "Für die Terminbestätigung brauche ich zuerst eine "
                    "rückbestätigte Handynummer. Wie lautet sie?"
                ),
                "regie": "Namenslink nie ohne bestätigte deutsche Mobilnummer reservieren.",
            }
        ctx["phone"] = confirmed_phone
        first, last = _name_teile(ctx)
        return _buch_und_akte(
            tenant,
            ctx,
            iso,
            first or "Reservierung",
            last or "SMS",
            confirmed_phone,
            deadline=deadline,
        )
    if not patient_id:
        auf = patients.patient_aufloesen(tenant, {
            "name": ctx.get("patientName"),
            "firstName": ctx.get("firstName"),
            "lastName": ctx.get("lastName"),
            "birthDate": ctx.get("birthDate"),
            "phone": ctx.get("phoneConfirmed") or ctx.get("phone"),
        })
        patient_id = _s(auf.get("id"))
        if patient_id:
            _bind_akte(ctx, auf)
    if patient_id and not patients.patient_id_bindung_passt(ctx):
        # Vorfall 10.09.2026: gesprochen/bestätigt war „Killnir“, im
        # Buchungskontext hing noch die patientId von „Kellner“. Nie unter
        # einer alten ID schreiben, auch wenn Slot und Telefonnummer stimmen.
        return {
            "ok": False,
            "booked": False,
            "patientMismatch": True,
            "patientId": patient_id,
            "spoken": (
                "Die Patientendaten passen gerade nicht eindeutig zusammen. "
                "Wie lautet der Vor- und Nachname bitte noch einmal?"
            ),
            "regie": "Name und patientId widersprechen sich. Nicht buchen, Identität neu auflösen.",
        }
    if BOOK_FIX_PHONE and not patient_id:
        # Auch der kombinierte createAppointment-Rückfall ist bereits ein
        # Buchungs-Write. Er darf deshalb ausschließlich die vom Anrufer
        # rückbestätigte deutsche Mobilnummer verwenden. Ohne dieses Tor
        # konnte ein fehlgeschlagenes akte_anlegen() mit einer bloß gehörten
        # oder einer Festnetznummer direkt Akte UND Termin anlegen.
        bestaetigt = _s(ctx.get("phoneConfirmed"))
        if not bestaetigt or not patients.ist_handy_de(bestaetigt):
            return {
                "ok": False,
                "booked": False,
                "phonePreflightFailed": True,
                "writeAttempted": False,
                "spoken": (
                    "Für die Terminbestätigung brauche ich zuerst eine "
                    "rückbestätigte Handynummer. Wie lautet sie?"
                ),
                "regie": "Keine Akte und keinen Termin ohne bestätigte deutsche Mobilnummer schreiben.",
            }
        ctx["phone"] = bestaetigt
    if not patient_id:
        first, last = _name_teile(ctx)
        phone = _s(ctx.get("phone")) or _s((ctx.get("neueAkte") or {}).get("phone"))
        angelegt = patients.akte_anlegen(
            tenant,
            first=first,
            last=last,
            phone=phone,
            birth=_s(ctx.get("birthDate")),
            gender=_s(ctx.get("gender")),
            private_insurance=(ctx.get("privateInsurance")
                               if isinstance(ctx.get("privateInsurance"), bool) else None),
            name=_s(ctx.get("patientName")),
        )
        if angelegt.get("ok") and _s((angelegt.get("patient") or {}).get("id")):
            karte = angelegt["patient"]
            patient_id = _s(karte.get("id"))
            created_patient = bool(angelegt.get("created"))
            ctx["patientId"] = patient_id
            ctx["firstName"] = karte.get("firstName") or first
            ctx["lastName"] = karte.get("lastName") or last
            ctx["patientName"] = karte.get("name") or f"{first} {last}".strip()
            ctx["phone"] = karte.get("phone") or phone
            ctx["phoneInChartKnown"] = True
            ctx["phoneInChart"] = karte.get("phone") or phone
            patients.patient_id_bindung_setzen(
                ctx, patient_id, ctx.get("firstName"), ctx.get("lastName"))
        elif phone and first and last and not patients.ist_testname(first, last):
            gebucht = _buch_und_akte(
                tenant, ctx, iso, first, last, phone, deadline=deadline
            )
            if gebucht.get("ok") or gebucht.get("writeAttempted"):
                return gebucht
        if not patient_id:
            return {
                "ok": False,
                "spoken": angelegt.get("spoken") or (
                    "Ich finde Sie noch nicht in unserer Kartei. "
                    "Wie lautet Ihre Handynummer? Dann lege ich Sie an und buche direkt."
                ),
                "regie": "Keine Akte. Vorname, Nachname und Handy erfragen, dann create_patient, dann book_slot.",
            }
    cal = kalender_von(tenant, _s(ctx.get("calendarName")))
    vm = None
    if _s(ctx.get("visitMotiveId")):
        vm = {"id": ctx["visitMotiveId"]}
    else:
        vm = motiv_von(tenant, _s(ctx.get("visitMotiveName")))
    body = {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "patientId": patient_id,
        "calendarId": _s(ctx.get("calendarId") or (cal or {}).get("id")),
        "visitMotiveId": _s(ctx.get("visitMotiveId") or (vm or {}).get("id")),
        "appointmentStartDate": iso,
    }
    if ctx.get("skipConfirmation") is True:
        session_id = _s(ctx.get("nameConfirmSessionId"))
        if not session_id:
            return {
            "ok": False,
                "booked": False,
                "writeAttempted": False,
            "spoken": (
                    "Die sichere Reservierung ist gerade nicht vollständig. "
                    "Ich trage den Termin noch nicht ein."
                ),
                "regie": "Namenslink-Reservierung ohne Sitzungsbindung abgebrochen.",
            }
        body["skipConfirmation"] = True
        body["nameConfirmToken"] = _s(ctx.get("nameConfirmToken"))
        body["nameConfirmSessionId"] = session_id
        body["createdPatient"] = created_patient
    phone_fix: dict[str, Any] | None = None
    phone_preflight = bool(BOOK_FIX_PHONE and patient_id)
    if phone_preflight:
        akte_phone = _s(ctx.get("phoneInChart"))
        bestaetigt = _s(ctx.get("phoneConfirmed"))
        bestaetigt_ok = bool(bestaetigt and patients.ist_handy_de(bestaetigt))
        akte_ok = bool(akte_phone and patients.ist_handy_de(akte_phone))
        gleich = bool(
            bestaetigt_ok
            and akte_ok
            and patients.handy_e164(akte_phone) == patients.handy_e164(bestaetigt)
        )
        # Ein frueherer Fluss-Schritt darf das Akten-Update bereits versucht
        # haben (telefon_alt). Nach einem Fehlschlag niemals ein zweites Mal
        # schreiben und erst recht nicht trotzdem buchen.
        update_schon_versucht = ctx.get("phoneUpdateAttempted") is True
        update_schon_ok = ctx.get("phoneUpdateOk") is True
        if update_schon_versucht:
            if not update_schon_ok or not gleich:
                phone_fix = {
                    "ok": False,
                    "attemptedEarlier": True,
                    "error": (
                        "phone_update_failed"
                        if not update_schon_ok
                        else "confirmed_mobile_changed_after_update"
                    ),
                }
        elif not bestaetigt_ok:
            phone_fix = {
                "ok": False,
                "attempted": False,
                "error": "missing_confirmed_mobile",
            }
        elif not gleich:
            phone_fix = _handy_nachtragen(tenant, ctx, patient_id=patient_id)
        if phone_fix is not None and not phone_fix.get("ok"):
            return {
                "ok": False,
                "booked": False,
                "phonePreflightFailed": True,
                "writeAttempted": False,
                "spoken": (
                    "Die bestätigte Handynummer konnte ich gerade nicht sicher "
                    "in Ihrer Akte speichern. Deshalb trage ich den Termin noch "
                    "nicht ein; die Praxis meldet sich bei Ihnen."
                ),
                "regie": "Handy-Aktenabgleich fehlgeschlagen. Keinen Buchungsaufruf senden.",
                "dispatch": phone_fix.get("dispatch"),
            }
    status, data, dispatch = _cf_call(
        "masBookAppointment",
        body,
        timeout=_book_timeout(deadline, _SCHREIB_TIMEOUT),
    )
    if isinstance(dispatch, dict) and phone_fix:
        dispatch["phoneFix"] = {
            k: v for k, v in phone_fix.items() if k != "dispatch"
        }
        if isinstance(phone_fix.get("dispatch"), dict):
            dispatch["phoneFixDispatch"] = phone_fix["dispatch"]
    if status == 200 and isinstance(data, dict) and data.get("status") == "success":
        # Read-after-write: Erst eine unabhängige Kalendersuche beweist, dass
        # Patient, Startzeit, Kalender und Termin-ID wirklich zusammengehören.
        # So wird weder eine fremde/recycelte ID notiert noch eine SMS zugesagt.
        aid_cf = _s(data.get("appointmentId"))
        pruefung = _buchung_verifizieren(
            tenant,
            ctx,
            patient_id=patient_id,
            appointment_id=aid_cf,
            iso=iso,
            calendar_id=body["calendarId"],
            deadline=deadline,
        )
        if isinstance(dispatch, dict):
            dispatch["verification"] = {
                k: v for k, v in pruefung.items() if k != "dispatch"
            }
            if isinstance(pruefung.get("dispatch"), dict):
                dispatch["verificationDispatch"] = pruefung["dispatch"]
        if not pruefung.get("ok"):
            ctx.pop("appointmentId", None)
            return _booking_uncertain(
                ctx,
                iso,
                dispatch=dispatch,
                reason="success_readback_inconclusive",
            )
        aid = _s(pruefung.get("appointmentId"))
        _booking_uncertainty_clear(ctx)
        ctx["appointmentId"] = aid
        ctx["appointmentDate"] = iso[:10]
        return _mit_dispatch({
            "ok": True,
            "booked": True,
            "verified": True,
            "idCorrected": bool(pruefung.get("idCorrected")),
            "slotIso": iso,
            "appointmentId": aid,
            "patientId": patient_id,
            "createdPatient": created_patient,
            "spoken": f"Der Termin {spoken_slot(iso)} ist fest eingetragen.",
        }, dispatch)
    if status == 200 and isinstance(data, dict) and data.get("status") == "needs_phone":
        return _mit_dispatch({
            "ok": False,
            # masBookAppointment wurde bereits aufgerufen; der Fluss muss
            # diesen Write beim globalen Zwei-Versuche-Deckel mitzählen.
            "writeAttempted": True,
            "spoken": "In Ihrer Akte fehlt noch eine Handynummer. Wie lautet sie?",
            "regie": "Nummer erfragen, dann erneut buchen.",
        }, dispatch)
    if status == 0 or status >= 500 or 200 <= status < 300:
        # Timeout, Serverfehler oder ein unbekannter 2xx-Vertrag können NACH
        # dem Commit entstanden sein. Erst exakt nachlesen; ohne Beweis die
        # Sitzung verriegeln und niemals einen zweiten Write senden.
        pruefung = _buchung_verifizieren(
            tenant,
            ctx,
            patient_id=patient_id,
            appointment_id="",
            iso=iso,
            calendar_id=body["calendarId"],
            deadline=deadline,
        )
        if isinstance(dispatch, dict):
            dispatch["verification"] = {
                k: v for k, v in pruefung.items() if k != "dispatch"
            }
            if isinstance(pruefung.get("dispatch"), dict):
                dispatch["verificationDispatch"] = pruefung["dispatch"]
        landung = _s(pruefung.get("appointmentId"))
        if pruefung.get("ok") and landung:
            _booking_uncertainty_clear(ctx)
            ctx["appointmentId"] = landung
            ctx["appointmentDate"] = iso[:10]
            return _mit_dispatch({
                "ok": True,
                "booked": True,
                "verified": True,
                "recoveredBy": "calendar_readback",
                "slotIso": iso,
                "appointmentId": landung,
                "patientId": patient_id,
                "createdPatient": created_patient,
                "spoken": f"Der Termin {spoken_slot(iso)} ist fest eingetragen.",
            }, dispatch)
        return _booking_uncertain(
            ctx,
            iso,
            dispatch=dispatch,
            reason=(
                "write_timeout_readback_inconclusive"
                if status == 0
                else "write_response_readback_inconclusive"
            ),
        )
    meldung = _s((data or {}).get("message")) if isinstance(data, dict) else ""
    # Diagnose (W-BOOK-RETRY / Thaler 01.09.2026): calendarId/Motiv/ISO mitloggen,
    # damit "not available" trotz frischem Angebot nachvollziehbar bleibt.
    print(
        f"book_slot fail status={status} message={meldung!r} "
        f"iso={iso!r} calendarId={body.get('calendarId')!r} "
        f"visitMotiveId={body.get('visitMotiveId')!r} patientId={patient_id!r}",
        flush=True,
    )
    if "not available" in meldung.lower():
        # Der Kalender sagt WIRKLICH "belegt": sofort sperren, alten Vorrat
        # verwerfen und Alternativen ausschließlich frisch nachladen.
        alt = _frische_konflikt_slots(tenant, ctx, iso)
        return _mit_dispatch({
            "ok": False,
            "slotTaken": True,
            "writeAttempted": True,
            "blockedIso": iso,
            "spoken": "Der Termin ist gerade weg. " + (alt.get("spoken") or ""),
            "regie": REGIE_ANGEBOT,
            "slots": alt.get("slots") or [],
            "alternativeDispatch": alt.get("dispatch"),
        }, dispatch)
    # Alles andere (Validierung, Patient/Kalender nicht gefunden, 500):
    # ehrlich bleiben statt "Termin ist weg" zu behaupten.
    return _mit_dispatch({
        "ok": False,
        "spoken": "Das hat gerade nicht geklappt. Die Praxis ruft Sie dazu zurück.",
        "regie": f"Buchung fehlgeschlagen ({meldung or status}). Keinen Erfolg behaupten.",
    }, dispatch)


def _handy_nachtragen(tenant: dict, ctx: dict, *, patient_id: str) -> dict[str, Any]:
    """needs_phone: die rueckbestaetigte Handynummer in die Akte schreiben.

    Vorfall Blessing 15.09.2026 (Anruf a8fcbcb4): In der Akte stand nur eine
    Festnetznummer. Die Anruferin nannte ihr Handy und bestaetigte es Ziffer
    fuer Ziffer — die Plattform lehnte die Buchung trotzdem VIERMAL mit
    `needs_phone` ab, weil niemand die Nummer in die Kartei schrieb. Bianca
    sagte am Ende "dann ist alles fuer Sie eingetragen"; im Kalender stand
    nichts.

    Geschrieben wird NUR eine rueckbestaetigte deutsche MOBILnummer
    (`ctx["phoneConfirmed"]`, gesetzt in flow._ctx_bauen aus telefon +
    telefonOk): eine bloss gehoerte Nummer kommt nie in die Kartei, und eine
    Festnetznummer als Handy einzutragen wuerde die SMS erneut ins Leere
    schicken. `ctx["aktePhoneNeu"]`/`aktePhoneAlt` melden den Erfolg an den
    Fluss zurueck, damit der Sammler nachzieht (sonst haengt die Erfolgs-
    Ansage eine "Bitte Akte aktualisieren"-Notiz an einen Termin, dessen
    Nummer gerade korrekt geschrieben wurde)."""
    nummer = _s(ctx.get("phoneConfirmed"))
    if not _s(patient_id) or not nummer or not patients.ist_handy_de(nummer):
        return {"ok": False, "grund": "keine bestaetigte Handynummer"}
    e164 = patients.handy_e164(nummer)
    status, data, dispatch = _cf_call("masUpdatePatientPhone", {
            "clientId": _s(tenant.get("clientId")),
            "locationId": _s(tenant.get("locationId")),
        "patientId": _s(patient_id),
        "mobilePhoneNumber": e164,
    })
    if status == 200 and isinstance(data, dict) and data.get("status") == "success":
        ctx["phone"] = nummer
        ctx["phoneInChartKnown"] = True
        ctx["phoneInChart"] = nummer
        ctx["aktePhoneNeu"] = nummer
        ctx["aktePhoneAlt"] = _s(data.get("previous"))
        return {
            "ok": True,
            "mobilePhoneNumber": _s(data.get("mobilePhoneNumber")) or e164,
            "previous": _s(data.get("previous")),
            "dispatch": dispatch,
        }
    print(
        "book_slot needs_phone: Akten-Update fehlgeschlagen — "
        f"status={status} message={_s((data or {}).get('message'))!r} "
        f"patientId={_s(patient_id)!r}",
        flush=True,
    )
    return {"ok": False, "grund": "update fehlgeschlagen", "dispatch": dispatch}


def _buchung_beweis_ueber_akte(
    tenant: dict,
    *,
    patient_id: str,
    iso: str,
    calendar_id: str,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Zweiter, NAMENSFREIER Beweisweg fuer eine frische Buchung.

    Vorfall Thaler 15.09.2026 (Anruf 831c8b6b): der Termin stand sauber im
    Kalender, die Ruecklese verweigerte ihn trotzdem. Ursache ist der
    Plattform-Vertrag — `agentFindPatientAppointments` loest den Patienten
    ueber Namens-Aehnlichkeit auf und liest eine mitgeschickte `patientId`
    NICHT (functions/src/controllers/agentAppointments.ts). Bei drei Akten
    "Eva Thaler" traf die Ruecklese eine fremde, `found_pid != patient_id`
    schlug zu und die Anruferin hoerte "nicht eindeutig angekommen".

    `masPatientLastDoctor` nimmt die `patientId` — damit ist derselbe
    Vierfach-Beweis (Akte, Startminute, Kalender, echte Termin-ID) ohne
    Namensraten moeglich. Bewusst nur `nextAppointment`: liegt ein
    FRUEHERER Termin der Akte davor, beweist dieser Weg nichts und der
    Termin bleibt unbestaetigt — lieber ehrlich als geraten.
    """
    expected_iso = _s(iso).replace(" ", "T")[:16]
    expected_cal = _s(calendar_id)
    if not _s(patient_id) or not expected_cal or len(expected_iso) < 16:
        return {"ok": False}
    status, data, dispatch = _cf_call(
        "masPatientLastDoctor",
        {
            "clientId": _s(tenant.get("clientId")),
            "locationId": _s(tenant.get("locationId")),
            "patientId": _s(patient_id),
        },
        timeout=timeout,
    )
    if status != 200 or not isinstance(data, dict) or data.get("status") != "success":
        return {"ok": False, "dispatch": dispatch}
    nxt = data.get("nextAppointment")
    if not isinstance(nxt, dict):
        return {"ok": False, "dispatch": dispatch}
    aid = _s(nxt.get("appointmentId"))
    if (not aid
            or _s(nxt.get("startIso")).replace(" ", "T")[:16] != expected_iso
            or _s(nxt.get("calendarId")) != expected_cal):
        return {"ok": False, "dispatch": dispatch}
    return {"ok": True, "appointmentId": aid, "dispatch": dispatch}


def _buchung_verifizieren(
    tenant: dict,
    ctx: dict,
    *,
    patient_id: str,
    appointment_id: str,
    iso: str,
    calendar_id: str,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Liest eine erfolgreiche Buchung unabhängig zurück.

    Ein Termin gilt erst als bestätigt, wenn die Patientenakte stimmt und
    genau ein Listentreffer Startzeit + Kalender trägt. Eine von der
    Schreibantwort abweichende ID wird nur übernommen, wenn dieser exakte
    Termin eindeutig in der Patientenliste steht.
    """
    expected_iso = _s(iso).replace(" ", "T")[:16]
    expected_cal = _s(calendar_id)
    expected_aid = _s(appointment_id)
    if not expected_cal:
        return {
            "ok": False,
            "appointmentId": "",
            "patientId": _s(patient_id),
            "slotIso": expected_iso,
            "calendarId": "",
            "expectedAppointmentId": expected_aid,
            "error": "Kalender-ID für die Rückleseprüfung fehlt",
        }
    verify_ctx = {
        "patientId": _s(patient_id),
        "firstName": _s(ctx.get("firstName")),
        "lastName": _s(ctx.get("lastName")),
        "patientName": _s(ctx.get("patientName")),
        # Die CF sucht den Patienten ueber Namens-Aehnlichkeit; mit Nummer
        # kandidiert sie ZUERST ueber das Telefon und nimmt sie sonst als
        # Stichentscheid (patientsService.findClientLocationPatientUserBy
        # Similarity). Findet die Nummer nichts, faellt sie selbst auf die
        # Namenssuche zurueck — die Angabe kann also nur helfen.
        "phone": _s(ctx.get("phone")),
    }
    letzter_dispatch: dict | None = None
    letzter_fehler = "Termin nach dem Schreiben nicht gefunden"
    # Hat die Namenssuche ueberhaupt die RICHTIGE Akte erreicht? Nur wenn
    # nicht, darf der namensfreie Beweisweg ran (s. unten) — traf sie die
    # Akte und der Termin passte trotzdem nicht, ist das ein echter
    # Widerspruch und bleibt unbestaetigt.
    namenspfad_traf_akte = False
    for delay in _BOOK_VERIFY_DELAYS:
        if deadline is not None and not _book_budget_left(deadline):
            letzter_fehler = "Zeitbudget der Rückleseprüfung ausgeschöpft"
            break
        if delay:
            if deadline is None:
                time.sleep(delay)
            else:
                sleep_for = min(delay, max(0.0, deadline - time.monotonic() - 0.15))
                if sleep_for:
                    time.sleep(sleep_for)
                if not _book_budget_left(deadline):
                    letzter_fehler = "Zeitbudget der Rückleseprüfung ausgeschöpft"
                    break
        found = find_patient_appointments(
            tenant,
            verify_ctx,
            timeout=(
                _book_timeout(deadline)
                if deadline is not None
                else None
            ),
        )
        if isinstance(found.get("dispatch"), dict):
            letzter_dispatch = found["dispatch"]
        if not found.get("ok"):
            letzter_fehler = _s(found.get("error")) or letzter_fehler
            continue
        found_pid = _s((found.get("patient") or {}).get("id"))
        if found_pid != _s(patient_id):
            letzter_fehler = "Rücklese-Patient stimmt nicht"
            continue
        namenspfad_traf_akte = True
        kandidaten = []
        for termin in found.get("appointments") or []:
            if not isinstance(termin, dict):
                continue
            termin_iso = _s(termin.get("iso")).replace(" ", "T")[:16]
            termin_cal = _s(termin.get("calendarId"))
            if termin_iso != expected_iso:
                continue
            # Die CF liefert den Kalender laut Vertrag mit. Fehlt er, ist
            # die verlangte Vierfachprüfung nicht möglich.
            if expected_cal and termin_cal != expected_cal:
                continue
            if not _s(termin.get("id")):
                continue
            kandidaten.append(termin)
        if len(kandidaten) != 1:
            letzter_fehler = (
                "Termin nach dem Schreiben mehrdeutig"
                if len(kandidaten) > 1 else
                "Startzeit oder Kalender nach dem Schreiben abweichend"
            )
            continue
        wirklich = _s(kandidaten[0].get("id"))
        return {
            "ok": True,
            "appointmentId": wirklich,
            "idCorrected": bool(expected_aid and wirklich != expected_aid),
            "patientId": _s(patient_id),
            "slotIso": expected_iso,
            "calendarId": expected_cal,
            "beweis": "namensliste",
            "dispatch": letzter_dispatch,
        }
    if (BOOK_VERIFY_AKTE
            and not namenspfad_traf_akte
            and (deadline is None or _book_budget_left(deadline))):
        # Die Namenssuche hat die Akte nie erreicht (fremder Treffer,
        # notFound, mehrdeutig, CF-Fehler) — also liegt KEIN Gegenbeweis
        # vor, nur fehlende Evidenz. Zweiter Weg ueber die patientId.
        akte = _buchung_beweis_ueber_akte(
            tenant,
            patient_id=patient_id,
            iso=expected_iso,
            calendar_id=expected_cal,
            timeout=(
                _book_timeout(deadline)
                if deadline is not None
                else None
            ),
        )
        if isinstance(akte.get("dispatch"), dict):
            letzter_dispatch = akte["dispatch"]
        if akte.get("ok"):
            wirklich = _s(akte.get("appointmentId"))
            print(f"buchung-beweis akte pid={_s(patient_id)} aid={wirklich} "
                  f"iso={expected_iso} (namensliste: {letzter_fehler})", flush=True)
            return {
                "ok": True,
                "appointmentId": wirklich,
                "idCorrected": bool(expected_aid and wirklich != expected_aid),
                "patientId": _s(patient_id),
                "slotIso": expected_iso,
                "calendarId": expected_cal,
                "beweis": "akte",
                "namenslisteFehler": letzter_fehler,
                "dispatch": letzter_dispatch,
            }
    return {
        "ok": False,
        "appointmentId": "",
        "patientId": _s(patient_id),
        "slotIso": expected_iso,
        "calendarId": expected_cal,
        "expectedAppointmentId": expected_aid,
        "error": letzter_fehler,
        "dispatch": letzter_dispatch,
    }


def _bind_akte(ctx: dict, karte: dict) -> None:
    if not karte:
        return
    ctx["patientId"] = _s(karte.get("id")) or ctx.get("patientId") or ""
    ctx["firstName"] = _s(karte.get("firstName")) or ctx.get("firstName") or ""
    ctx["lastName"] = _s(karte.get("lastName")) or ctx.get("lastName") or ""
    ctx["patientName"] = _s(karte.get("name")) or f"{ctx.get('firstName', '')} {ctx.get('lastName', '')}".strip()
    patients.patient_id_bindung_setzen(
        ctx, ctx.get("patientId"), ctx.get("firstName"), ctx.get("lastName"))
    ctx["phoneInChartKnown"] = True
    ctx["phoneInChart"] = _s(karte.get("phone"))
    if karte.get("phone"):
        ctx["phone"] = karte["phone"]
    if karte.get("birthDate"):
        ctx["birthDate"] = karte["birthDate"]
    duplicate_count = int(karte.get("duplicateCount") or 0)
    if duplicate_count > 1:
        ctx["patientDuplicateCount"] = duplicate_count
        ctx["patientDuplicateIds"] = [
            _s(x) for x in (karte.get("duplicatePatientIds") or []) if _s(x)
        ]
        ctx["patientDuplicateNewestCertain"] = bool(
            karte.get("duplicateNewestCertain"))


def create_patient(
    tenant: dict,
    ctx: dict,
    sit: dict | None = None,
    *,
    first: str = "",
    last: str = "",
    phone: str = "",
    birth: str = "",
    gender: str = "",
) -> dict[str, Any]:
    first = _s(first) or _s(ctx.get("firstName"))
    last = _s(last) or _s(ctx.get("lastName"))
    phone = _s(phone) or _s(ctx.get("phone"))
    birth = _s(birth) or _s(ctx.get("birthDate"))
    gender = _s(gender) or _s(ctx.get("gender"))
    result = patients.akte_anlegen(
        tenant,
        first=first,
        last=last,
        phone=phone,
        birth=birth,
        gender=gender,
        private_insurance=(ctx.get("privateInsurance")
                           if isinstance(ctx.get("privateInsurance"), bool) else None),
        name=_s(ctx.get("patientName")),
    )
    karte = result.get("patient") if isinstance(result.get("patient"), dict) else {}
    if karte:
        _bind_akte(ctx, karte)
        if result.get("staged"):
            ctx["neueAkte"] = karte
        if sit is not None:
            alt = sit.get("patient") or {}
            sit["patient"] = {**alt, **karte}
    return result


def _held_booking_readback(
    tenant: dict,
    *,
    token: str,
    iso: str,
    calendar_id: str,
    visit_motive_id: str,
    deadline: float,
) -> dict[str, Any]:
    """Tokengebundene Reservierung über ihre deterministischen IDs beweisen."""
    patient_id = _name_confirm_scoped_id("ncp", tenant, token)
    appointment_id = _name_confirm_scoped_id("nca", tenant, token)
    error = "held_appointment_not_found"
    # Diagnose ist datensparsam: die scoped IDs sind SHA256-Hashes (nicht auf
    # Token/Telefon rückrechenbar), `scope` benennt NUR das abweichende Feld,
    # NIE dessen Inhalt. Hilft Paket 3, den CF-Vertrag belastbar zu reparieren.
    scope: str = ""
    for delay in _BOOK_VERIFY_DELAYS:
        if not _book_budget_left(deadline):
            error = "booking_deadline_exhausted"
            break
        if delay:
            sleep_for = min(delay, max(0.0, deadline - time.monotonic() - 0.15))
            if sleep_for:
                time.sleep(sleep_for)
            if not _book_budget_left(deadline):
                error = "booking_deadline_exhausted"
                break
        found = _firestore_appointment_by_id(
            tenant,
            appointment_id,
            timeout=_book_timeout(deadline, 2.0),
            expected_name_confirm_token=token,
        )
        if not found.get("ok"):
            error = _s(found.get("error")) or error
            continue
        appointment = found.get("appointment")
        if (
            found.get("missing")
            or found.get("deleted")
            or not isinstance(appointment, dict)
        ):
            error = "held_appointment_missing_or_inactive"
            continue
        # Pro Feld prüfen, damit die Diagnose das abweichende Feld benennt.
        # Das Verhalten bleibt identisch: jeder Treffer = scope_mismatch.
        checks = (
            ("id", _s(appointment.get("id")) == appointment_id),
            ("patientId", _s(appointment.get("patientId")) == patient_id),
            ("iso", _slot_key(appointment.get("iso")) == _slot_key(iso)),
            ("calendarId",
             _s(appointment.get("calendarId")) == _s(calendar_id)),
            ("visitMotiveId",
             _s(appointment.get("visitMotiveId")) == _s(visit_motive_id)),
            ("tokenMatch",
             appointment.get("nameConfirmTokenMatches") is True),
            ("pending", appointment.get("nameConfirmPending") is True),
            ("held", appointment.get("confirmationHeld") is True),
            ("active", _management_appointment_active(appointment)),
        )
        fehler = [feld for feld, ok in checks if not ok]
        if fehler:
            error = "held_appointment_scope_mismatch"
            scope = ",".join(fehler)
            continue
        return {
            "ok": True,
            "appointmentId": appointment_id,
            "patientId": patient_id,
            "beweis": "deterministic_firestore_id",
            "expectedAppointmentId": appointment_id,
            "source": "phone_agent",
        }
    out: dict[str, Any] = {
        "ok": False,
        "appointmentId": "",
        "patientId": patient_id,
        "error": error,
        "expectedAppointmentId": appointment_id,
        "source": "phone_agent",
    }
    if scope:
        out["scope"] = scope
    return out


def _buch_und_akte(
    tenant: dict,
    ctx: dict,
    iso: str,
    first: str,
    last: str,
    phone: str,
    *,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Fallback: createAppointment legt Akte an und bucht in einem Zug."""
    uncertainty = _booking_uncertainty_guard(ctx)
    if uncertainty:
        return uncertainty
    deadline = deadline if deadline is not None else _book_deadline()
    cal = kalender_von(tenant, _s(ctx.get("calendarName")))
    vm = None
    if _s(ctx.get("visitMotiveId")):
        vm = {"id": ctx["visitMotiveId"]}
    else:
        vm = motiv_von(tenant, _s(ctx.get("visitMotiveName")))
    gender = _s(ctx.get("gender")).lower()
    if gender in {"herr", "m", "male"}:
        gender = "m"
    elif gender in {"diverse", "d"}:
        gender = "d"
    else:
        gender = "f"
    body = {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "patientGender": gender,
        "patientFirstName": first,
        "patientLastName": last,
        "patientMobilePhoneNumber": phone,
        "calendarId": _s(ctx.get("calendarId") or (cal or {}).get("id")),
        "visitMotiveId": _s(ctx.get("visitMotiveId") or (vm or {}).get("id")),
        "appointmentStartDate": iso,
        "source": "phone_agent",
    }
    if ctx.get("skipConfirmation") is True:
        session_id = _s(ctx.get("nameConfirmSessionId"))
        if not session_id:
            return {
                "ok": False,
                "booked": False,
                "writeAttempted": False,
                "spoken": (
                    "Die sichere Reservierung ist gerade nicht vollständig. "
                    "Ich trage den Termin noch nicht ein."
                ),
                "regie": "Namenslink-Reservierung ohne Sitzungsbindung abgebrochen.",
            }
        body["skipConfirmation"] = True
        body["nameConfirmToken"] = _s(ctx.get("nameConfirmToken"))
        body["nameConfirmSessionId"] = session_id
    status, data, dispatch = _cf_call(
        "createAppointment",
        body,
        timeout=_book_timeout(deadline, _SCHREIB_TIMEOUT),
    )
    success = (
        status == 200
        and isinstance(data, dict)
        and data.get("status") == "success"
    )
    returned_patient_id = _s(data.get("patientId")) if success else ""
    returned_appointment_id = _s(data.get("appointmentId")) if success else ""
    skip_confirmation = body.get("skipConfirmation") is True
    proof: dict[str, Any]
    if skip_confirmation:
        # Auch bei HTTP 200 ist die Function-Antwort kein Beweis. Die
        # deterministische Dokument-ID erlaubt eine exakte, namensfreie
        # Rücklese — ebenso nach Timeout/5xx.
        proof = _held_booking_readback(
            tenant,
            token=_s(body.get("nameConfirmToken")),
            iso=iso,
            calendar_id=_s(body.get("calendarId")),
            visit_motive_id=_s(body.get("visitMotiveId")),
            deadline=deadline,
        )
    elif success and returned_patient_id and returned_appointment_id:
        proof = _buchung_verifizieren(
            tenant,
            ctx,
            patient_id=returned_patient_id,
            appointment_id=returned_appointment_id,
            iso=iso,
            calendar_id=_s(body.get("calendarId")),
            deadline=deadline,
        )
    else:
        proof = {
            "ok": False,
            "error": (
                "createAppointment_response_missing_ids"
                if success
                else "createAppointment_write_response_unclear"
            ),
        }
    if isinstance(dispatch, dict):
        dispatch["verification"] = {
            k: v for k, v in proof.items() if k != "dispatch"
        }
        if isinstance(proof.get("dispatch"), dict):
            dispatch["verificationDispatch"] = proof["dispatch"]
    if proof.get("ok"):
        patient_id = _s(proof.get("patientId")) or returned_patient_id
        appointment_id = _s(proof.get("appointmentId"))
        auf = {
            "id": patient_id,
            "firstName": first,
            "lastName": last,
            "name": f"{first} {last}".strip(),
            "phone": phone,
        }
        _bind_akte(ctx, auf)
        created_patient = (
            bool(data.get("createdPatient"))
            if success and "createdPatient" in data
            else skip_confirmation
        )
        # createAppointment kennt kein Versicherungs-Feld — den erfragten
        # Status auf einer normalen frisch angelegten Akte nachtragen.
        if (
            not skip_confirmation
            and isinstance(ctx.get("privateInsurance"), bool)
        ):
            patients.versicherung_aktualisieren(
                tenant, patient_id, ctx["privateInsurance"]
            )
        _booking_uncertainty_clear(ctx)
        ctx["appointmentId"] = appointment_id
        ctx["appointmentDate"] = iso[:10]
        return _mit_dispatch({
            "ok": True,
            "booked": True,
            "verified": True,
            "verificationProof": _s(proof.get("beweis")),
            "createdPatient": created_patient,
            "patientId": patient_id,
            "slotIso": iso,
            "appointmentId": appointment_id,
            "spoken": f"Akte und Termin {spoken_slot(iso)} sind fest eingetragen.",
        }, dispatch)
    if success or status == 0 or status >= 500 or 200 <= status < 300:
        return _booking_uncertain(
            ctx,
            iso,
            dispatch=dispatch,
            reason=_s(proof.get("error")) or "direct_create_readback_inconclusive",
        )
    return _mit_dispatch({
        "ok": False,
        "booked": False,
        "writeAttempted": True,
        "spoken": "Das hat gerade nicht geklappt. Die Praxis ruft Sie dazu zurück.",
        "regie": "Akte-und-Termin-Schreibvorgang wurde eindeutig abgelehnt.",
    }, dispatch)


def _name_norm(v: Any) -> str:
    roh = unicodedata.normalize("NFKD", _s(v).casefold())
    roh = "".join(c for c in roh if not unicodedata.combining(c))
    return "".join(c for c in roh if c.isalnum()).replace("ß", "ss")


def _patient_name_score(first: str, last: str, patient: dict) -> float:
    """Gesprochenen Namen gegen eine Kartei bewerten (0..1)."""
    gl, kl = _name_norm(last), _name_norm(patient.get("lastName"))
    if not gl or not kl:
        return 0.0
    if not _s(first):
        return SequenceMatcher(None, gl, kl).ratio()
    gv = _name_norm(first)
    kv = _name_norm(patient.get("firstName"))
    if not gv or not kv:
        return 0.0
    return SequenceMatcher(None, gv + gl, kv + kl).ratio()


def _patient_phone(patient: dict) -> str:
    for key in ("mobilePhoneNumber", "mobilePhone", "phoneNumber", "phone", "telephone"):
        wert = "".join(c for c in _s(patient.get(key)) if c.isdigit())
        if wert:
            return wert.removeprefix("00").removeprefix("49").lstrip("0")
    return ""


def _management_match_source(
    *,
    first: str,
    last: str,
    patient: dict,
    patient_id: str,
    phone: str,
) -> str:
    """Beweisstärke eines Patienten-Treffers für Absage/Verschieben.

    Eine von der Cloud Function gewählte Akte wird nicht allein deshalb zum
    exakten Treffer. Eine bestätigte ID beziehungsweise übereinstimmende
    Rufnummer ist ein Beweis; ein nur ähnlicher Name bleibt ``name60`` und
    muss vor jeder Auskunft oder Änderung rückbestätigt werden.
    """
    if patient_id:
        # Eine bereits bestätigte Akten-ID ist eine harte Grenze. Liefert die
        # Namens-CF eine andere Akte, darf selbst ein identischer Name diese
        # Bindung nie ersetzen.
        return (
            "patientId"
            if _s(patient.get("id")) == _s(patient_id)
            else ""
        )
    tel = "".join(c for c in _s(phone) if c.isdigit())
    tel = tel.removeprefix("00").removeprefix("49").lstrip("0")
    if tel:
        # Dasselbe gilt für eine rückbestätigte Patienten-Rufnummer.
        return "telefon" if _patient_phone(patient) == tel else ""
    score = _patient_name_score(first, last, patient)
    if score >= 0.98:
        return "exact"
    if score >= 0.60:
        return "name60"
    return ""


def _management_appointment_active(appointment: dict) -> bool:
    """Defensive Statuswache für Verwaltungs-Treffer aus Cloud Functions."""
    if appointment.get("isDeleted") is True or appointment.get("deletedAt"):
        return False
    status = re.sub(
        r"[^a-z0-9]+",
        "",
        _s(
            appointment.get("status")
            or appointment.get("appointmentStatus")
        ).casefold(),
    )
    if status in {
        "cancelled", "canceled", "deleted", "declined",
        "needsconfirmation", "reserved",
    }:
        return False
    patient_status = appointment.get("patientStatus")
    if isinstance(patient_status, (int, float)) and int(patient_status) in {4, 5}:
        return False
    if isinstance(patient_status, str):
        ps = re.sub(r"[^a-z0-9]+", "", patient_status.casefold())
        if (ps.isdigit() and int(ps) in {4, 5}) or ps in {
            "cancelled", "canceled", "deleted", "declined",
        }:
            return False
    return True


def _firestore_duplicate_patient_appointments(
    tenant: dict,
    patienten: list[dict],
) -> dict[str, Any]:
    """Alle kommenden Termine mehrerer gleichnamiger Akten lesen.

    Der Namens-Endpunkt wählt bei Patientendubletten nur eine Akte. Dieser
    read-only Firestore-Weg fragt deshalb jede konkrete patient.id ab und
    vereinigt die aktiven Termine. Kein Write, kein Namensraten.
    """
    from kern import anrufaudio, standort
    from kern.config import FIREBASE_CREDENTIALS

    client_id = _s(tenant.get("clientId"))
    location_id = _s(tenant.get("locationId"))
    ids = list(dict.fromkeys(
        _s(p.get("id")) for p in patienten
        if isinstance(p, dict) and _s(p.get("id"))
    ))
    dispatch = {
        "route": "firestoreAppointmentsForDuplicatePatients",
        "method": "POST",
        "request": {"patientRecords": len(ids)},
        "response": {"appointments": 0},
    }
    if not FIREBASE_CREDENTIALS or not client_id or not location_id or len(ids) < 2:
        dispatch["httpStatus"] = 0
        return _mit_dispatch({
            "ok": False,
            "appointments": [],
            "error": "duplicate_firestore_unavailable",
        }, dispatch)
    try:
        token = anrufaudio._access_token(
            "https://www.googleapis.com/auth/datastore")
        projekt = standort._projekt()
        url = (
            "https://firestore.googleapis.com/v1/projects/"
            f"{projekt}/databases/(default)/documents/clients/{client_id}/"
            f"locations/{location_id}:runQuery"
        )
        rows: list[dict] = []
        total_ms = 0
        for patient_id in ids:
            body = {
                "structuredQuery": {
                    "select": {"fields": [
                        {"fieldPath": f} for f in (
                            "start", "status", "patientStatus",
                            "isDeleted", "deletedAt",
                            "patient", "calendar", "visitMotive",
                        )
                    ]},
                    "from": [{"collectionId": "appointments"}],
                    "where": {"fieldFilter": {
                        "field": {"fieldPath": "patient.id"},
                        "op": "EQUAL",
                        "value": {"stringValue": patient_id},
                    }},
                    "limit": 500,
                },
            }
            t0 = time.perf_counter()
            r = httpx.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=body,
                timeout=10.0,
            )
            total_ms += int(round((time.perf_counter() - t0) * 1000))
            if r.status_code != 200:
                dispatch.update({"url": url, "httpStatus": r.status_code, "ms": total_ms})
                return _mit_dispatch({
                    "ok": False,
                    "appointments": [],
                    "error": f"duplicate_firestore_http_{r.status_code}",
                }, dispatch)
            data = r.json()
            if not isinstance(data, list):
                dispatch.update({"url": url, "httpStatus": 200, "ms": total_ms})
                return _mit_dispatch({
                    "ok": False,
                    "appointments": [],
                    "error": "duplicate_firestore_invalid",
                }, dispatch)
            docs = [
                row for row in data
                if isinstance(row, dict) and isinstance(row.get("document"), dict)
            ]
            if len(docs) >= 500:
                dispatch.update({"url": url, "httpStatus": 200, "ms": total_ms})
                return _mit_dispatch({
                    "ok": False,
                    "appointments": [],
                    "error": "duplicate_firestore_truncated",
                }, dispatch)
            rows.extend(docs)
    except Exception as exc:
        dispatch.update({
            "httpStatus": 0,
            "response": {
                "appointments": 0,
                "error": type(exc).__name__,
            },
        })
        return _mit_dispatch({
            "ok": False,
            "appointments": [],
            "error": str(exc),
        }, dispatch)

    jetzt = datetime.now(TZ) - timedelta(minutes=5)
    erlaubt = set(ids)
    termine: list[dict[str, Any]] = []
    for row in rows:
        doc = row.get("document") or {}
        felder = doc.get("fields")
        if not isinstance(felder, dict):
            continue
        f = {k: standort._decode(v) for k, v in felder.items()}
        if not _management_appointment_active(f):
            continue
        patient = f.get("patient") if isinstance(f.get("patient"), dict) else {}
        patient_id = _s(patient.get("id"))
        if patient_id not in erlaubt:
            continue
        roh_start = _s(f.get("start"))
        try:
            lokal = datetime.fromisoformat(
                roh_start.replace("Z", "+00:00")).astimezone(TZ)
        except ValueError:
            continue
        if lokal < jetzt:
            continue
        cal = f.get("calendar") if isinstance(f.get("calendar"), dict) else {}
        vm = f.get("visitMotive") if isinstance(f.get("visitMotive"), dict) else {}
        arzt = _s(cal.get("name")).split(",")[0].strip()
        iso = lokal.isoformat(timespec="minutes")
        gesprochen = spoken_slot(iso)
        if arzt:
            gesprochen += f" bei {arzt}"
        first = _s(patient.get("firstName"))
        last = _s(patient.get("lastName"))
        termine.append({
            "id": _s(doc.get("name")).rsplit("/", 1)[-1],
            "iso": iso,
            "date": iso[:10],
            "calendarId": _s(cal.get("id")),
            "doctorName": arzt,
            "motivId": _s(vm.get("id")),
            "motivName": _s(vm.get("name")),
            "spoken": gesprochen,
            "patientId": patient_id,
            "patientFirstName": first,
            "patientLastName": last,
            "patientName": f"{first} {last}".strip(),
            "patientPhone": _s(
                patient.get("mobilePhoneNumber")
                or patient.get("phoneNumber")
                or patient.get("phone")
            ),
        })
    # Dieselbe Termin-ID darf selbst bei einer unerwartet doppelt
    # gelieferten Query-Antwort nur einmal angeboten werden.
    termine = list({
        (_s(a.get("id")), _s(a.get("patientId"))): a
        for a in termine
        if _s(a.get("id"))
    }.values())
    termine.sort(key=lambda a: (_s(a.get("iso")), _s(a.get("id"))))
    newest, newest_certain = patients.neueste_akte(patienten)
    patient = {
        "id": _s(newest.get("id")),
        "firstName": _s(newest.get("firstName")),
        "lastName": _s(newest.get("lastName")),
    }
    dispatch.update({
        "httpStatus": 200,
        "ms": total_ms,
        "response": {
            "appointments": len(termine),
            "patientRecords": len(ids),
        },
    })
    return _mit_dispatch({
        "ok": True,
        "patient": patient,
        "appointments": termine,
        "matchSource": "duplicates",
        "duplicateCount": len(ids),
        "duplicatePatientIds": ids,
        "duplicateNewestCertain": newest_certain,
    }, dispatch)


_MANAGEMENT_UNCERTAIN_KEY = "managementUncertain"


def _management_uncertain_result(
    *,
    operation: str,
    appointment_id: str,
    slot_iso: str = "",
    write_attempted: bool,
    error: str,
    dispatch: dict | None = None,
    spoken: str = "",
    regie: str = "",
) -> dict[str, Any]:
    """Einheitlicher Fail-closed-Vertrag für unklare Verwaltungs-Writes."""
    result: dict[str, Any] = {
        "ok": False,
        "appointmentId": _s(appointment_id),
        "writeAttempted": bool(write_attempted),
        "verificationFailed": True,
        "possiblyChanged": True,
        "manualCheckRequired": True,
        "error": _s(error),
    }
    if operation == "cancel":
        result["cancelled"] = False
    else:
        result["moved"] = False
    if _s(slot_iso):
        result["slotIso"] = _s(slot_iso)
    if isinstance(dispatch, dict):
        result["dispatch"] = dispatch
    if _s(spoken):
        result["spoken"] = _s(spoken)
    if _s(regie):
        result["regie"] = _s(regie)
    return result


def _management_uncertain_mark(
    ctx: dict,
    *,
    operation: str,
    appointment_id: str,
    slot_iso: str = "",
    reason: str,
    dispatch: dict | None = None,
    spoken: str = "",
    regie: str = "",
) -> dict[str, Any]:
    """Write wurde gesendet, sein Endzustand ist aber nicht beweisbar."""
    ctx[_MANAGEMENT_UNCERTAIN_KEY] = {
        "operation": _s(operation),
        "appointmentId": _s(appointment_id),
        "slotIso": _s(slot_iso),
        "reason": _s(reason),
        "writeAttempted": True,
        "verificationFailed": True,
        "possiblyChanged": True,
        "manualCheckRequired": True,
    }
    return _management_uncertain_result(
        operation=operation,
        appointment_id=appointment_id,
        slot_iso=slot_iso,
        write_attempted=True,
        error=f"{operation}_verification_inconclusive",
        dispatch=dispatch,
        spoken=spoken,
        regie=regie,
    )


def _management_uncertain_guard(
    ctx: dict,
    *,
    operation: str,
    appointment_id: str,
    slot_iso: str = "",
) -> dict[str, Any] | None:
    """Ein offenes Latch sperrt jeden weiteren destruktiven Verwaltungs-Write."""
    latch = ctx.get(_MANAGEMENT_UNCERTAIN_KEY)
    if not isinstance(latch, dict) or not latch.get("manualCheckRequired"):
        return None
    ist_absage = operation == "cancel"
    return _management_uncertain_result(
        operation=operation,
        appointment_id=appointment_id,
        slot_iso=slot_iso,
        write_attempted=False,
        error="management_write_blocked_by_uncertainty",
        spoken=(
            "Die Absage ist bereits zur Prüfung vorgemerkt. "
            "Ich sende keinen zweiten Auftrag."
            if ist_absage
            else
            "Die Verschiebung ist bereits zur Prüfung vorgemerkt. "
            "Ich sende keinen zweiten Auftrag."
        ),
        regie=(
            "Offenes Management-Uncertainty-Latch: kein weiterer "
            "destruktiver Kalender-Write."
        ),
    )


def _patient_appointments_fallback(
    tenant: dict,
    *,
    first: str,
    last: str,
    vorname_verworfen: bool,
    primary_dispatch: dict | None,
    patient_id: str = "",
    phone: str = "",
    birth_date: str = "",
    min_similarity: float = 1.0,
) -> dict[str, Any] | None:
    """False-404-Rettung: Kartei-ID suchen, dann den nächsten Termin laden.

    ``agentFindPatientAppointments`` meldete live für den eindeutig
    vorhandenen Sylvester Stallone ``not_found``. Die beiden älteren,
    voneinander unabhängigen Lesewege fanden dagegen Akte und Termin.
    Eindeutigkeit ist Pflicht: bei mehreren gleichnamigen Patienten wird
    weiter der Vorname erfragt, nie irgendeine Akte gewählt.
    """
    query_first = "" if vorname_verworfen else _s(first)
    query = f"{query_first} {last}".strip()
    status, data, search_dispatch = _cf_call("masSearchPatients", {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "query": query,
    })
    if status != 200 or not isinstance(data, dict) or data.get("status") != "success":
        return None

    roh = [
        p for p in (data.get("patients") or [])
        if isinstance(p, dict) and _s(p.get("id"))
    ]
    pid = _s(patient_id)
    tel = "".join(c for c in _s(phone) if c.isdigit())
    tel = tel.removeprefix("00").removeprefix("49").lstrip("0")
    match_source = "exact"
    kandidaten: list[dict] = []
    # W-ZWEI-MERKMALE: eine gebundene Akten-ID/Rufnummer ohne Treffer leert
    # NICHT mehr sofort (alte harte Grenze). Stattdessen sucht der Namensweg
    # weiter und übernimmt eine FREMDE Akte nur, wenn sie über zwei
    # unabhängige Merkmale (Telefon + starker Name bzw. Geburtsdatum)
    # eindeutig belegt ist. Notaus ``ZWEI_MERKMALE=0`` = alte Grenze.
    gebunden = ""
    if pid:
        kandidaten = [p for p in roh if _s(p.get("id")) == pid]
        if kandidaten:
            match_source = "patientId"
        elif not _im.aktiv():
            return None
        else:
            gebunden = "patientId"
    elif tel:
        kandidaten = [p for p in roh if _patient_phone(p) == tel]
        if kandidaten:
            match_source = "telefon"
        elif not _im.aktiv():
            return None
        else:
            gebunden = "telefon"
    if not kandidaten and min_similarity < 1.0:
        bewertet = sorted(
            ((_patient_name_score(query_first, last, p), p) for p in roh),
            key=lambda x: (-x[0], _s(x[1].get("id"))),
        )
        passend = [(score, p) for score, p in bewertet if score >= min_similarity]
        # Mit Vorname darf ein klar besserer Kandidat zur Rueckversicherung
        # angeboten werden. Ohne Vorname bleiben gleiche Nachnamen mehrdeutig.
        if query_first and passend and (
                len(passend) == 1 or passend[0][0] - passend[1][0] >= 0.10):
            kandidaten = [passend[0][1]]
        else:
            kandidaten = [p for _, p in passend]
        # Ein wirklich identischer Name bleibt ein exakter Treffer. Der
        # 60%-Rückversicherungsweg ist nur für tatsächlich unscharfe Namen
        # gedacht (z. B. Päsla -> Päsler), nicht für Stallone -> Stallone.
        match_source = (
            "exact"
            if len(kandidaten) == 1
            and _patient_name_score(query_first, last, kandidaten[0]) >= 0.98
            else "name60"
        )
    elif not kandidaten:
        kandidaten = [
            p for p in roh
            if _name_norm(p.get("lastName")) == _name_norm(last)
            and (not query_first
                 or _name_norm(p.get("firstName")) == _name_norm(query_first))
        ]
    # W-ZWEI-MERKMALE 2c: Kölner Phonetik (wie 006a6323c, inkl. Stamm-
    # Nachsuche) und vertauschte Vor-/Nachnamen — nur wenn der Namensweg sonst
    # leer bliebe. Gated über ZWEI_MERKMALE (Notaus = alter Weg ohne Phonetik).
    if not kandidaten and _im.aktiv():
        klang = _phonetik.waehlen(roh, last, query_first)
        if len(klang) == 1:
            kandidaten = klang
            match_source = "phonetik"
        elif 1 < len(klang) <= 8 and not gebunden:
            return _mit_dispatch({
                "ok": True, "mehrdeutig": True, "patient": {},
                "appointments": [], "vornameVerworfen": vorname_verworfen,
                "fallbackUsed": True, "phonetic": True,
            }, search_dispatch)
        elif len(_s(last)) >= 5:
            stamm = _s(last)[:4]
            status2, data2, dispatch2 = _cf_call("masSearchPatients", {
                "clientId": _s(tenant.get("clientId")),
                "locationId": _s(tenant.get("locationId")),
                "query": stamm,
            })
            if status2 == 200 and isinstance(data2, dict):
                roh2 = [p for p in (data2.get("patients") or [])
                        if isinstance(p, dict) and _s(p.get("id"))]
                klang = _phonetik.waehlen(roh2, last, query_first)
                if isinstance(dispatch2, dict):
                    search_dispatch = dispatch2
                if len(klang) == 1:
                    kandidaten = klang
                    match_source = "phonetik"
                elif 1 < len(klang) <= 8 and not gebunden:
                    return _mit_dispatch({
                        "ok": True, "mehrdeutig": True, "patient": {},
                        "appointments": [], "vornameVerworfen": vorname_verworfen,
                        "fallbackUsed": True, "phonetic": True,
                    }, search_dispatch)
        if not kandidaten and query_first:
            # Vor- und Nachname vertauscht (zweiter masSearchPatients-Aufruf).
            getauscht = f"{last} {query_first}".strip()
            if _name_norm(getauscht) != _name_norm(query):
                status3, data3, dispatch3 = _cf_call("masSearchPatients", {
                    "clientId": _s(tenant.get("clientId")),
                    "locationId": _s(tenant.get("locationId")),
                    "query": getauscht,
                })
                if status3 == 200 and isinstance(data3, dict):
                    roh3 = [p for p in (data3.get("patients") or [])
                            if isinstance(p, dict) and _s(p.get("id"))]
                    vt = [
                        p for p in roh3
                        if _name_norm(p.get("firstName")) == _name_norm(last)
                        and _name_norm(p.get("lastName")) == _name_norm(query_first)
                    ]
                    if isinstance(dispatch3, dict):
                        search_dispatch = dispatch3
                    if len(vt) == 1:
                        kandidaten = vt
                        match_source = "vertauscht"
    if gebunden and kandidaten:
        # Fremde Akte(n) bei gebundener ID/Rufnummer: nur mit ZWEI
        # unabhängigen Merkmalen übernehmen, sonst nie auf eine andere Akte
        # springen (Rückfall auf die alte harte Grenze).
        def _reicht_fremd(p: dict) -> bool:
            m: set[str] = set()
            if tel and _patient_phone(p) == tel:
                m.add("telefon")
            if _im.starker_name(first, last, p.get("firstName"), p.get("lastName")):
                m.add("name")
            bd = _s(birth_date)[:10]
            pb = _s(p.get("birthDate"))[:10]
            if bd and pb and bd == pb:
                m.add("geburtsdatum")
            return _im.reicht(m)

        kandidaten = [p for p in kandidaten
                      if _s(p.get("id")) != pid and _reicht_fremd(p)]
        if not kandidaten:
            return None
    if len(kandidaten) > 1:
        namen = {
            (
                _name_norm(p.get("firstName")),
                _name_norm(p.get("lastName")),
            )
            for p in kandidaten
        }
        geburtsdaten = {
            _s(p.get("birthDate"))[:10] for p in kandidaten
            if _s(p.get("birthDate"))
        }
        if len(namen) == 1 and all(namen.pop()) and len(geburtsdaten) <= 1:
            resultat = _firestore_duplicate_patient_appointments(
                tenant, kandidaten)
            if isinstance(resultat.get("dispatch"), dict) and primary_dispatch:
                resultat["dispatch"]["fallbackFrom"] = primary_dispatch
            return resultat
        return _mit_dispatch({
            "ok": True,
            "mehrdeutig": True,
            "patient": {},
            "appointments": [],
            "vornameVerworfen": vorname_verworfen,
            "fallbackUsed": True,
        }, search_dispatch)
    if len(kandidaten) != 1:
        return None

    pat = kandidaten[0]
    patient = {
        "id": _s(pat.get("id")),
        "firstName": _s(pat.get("firstName")),
        "lastName": _s(pat.get("lastName")),
    }
    status, data, termin_dispatch = _cf_call("masPatientLastDoctor", {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "patientId": patient["id"],
    })
    if isinstance(termin_dispatch, dict) and primary_dispatch:
        termin_dispatch["fallbackFrom"] = primary_dispatch
    if status != 200 or not isinstance(data, dict) or data.get("status") != "success":
        msg = _s(data.get("message")) if isinstance(data, dict) else f"http_{status}"
        return _mit_dispatch({
            "ok": False,
            "patient": patient,
            "appointments": [],
            "error": msg or f"http_{status}",
            "fallbackUsed": True,
        }, termin_dispatch)

    nxt = data.get("nextAppointment") or {}
    termine: list[dict[str, str]] = []
    if (isinstance(nxt, dict) and _s(nxt.get("appointmentId"))
            and _management_appointment_active(nxt)):
        iso = _s(nxt.get("startIso")).replace(" ", "T")[:16]
        arzt = _s(nxt.get("calendarName") or nxt.get("doctorName")).split(",")[0].strip()
        motiv_name = _s(nxt.get("visitMotiveName"))
        motiv = motiv_von(tenant, motiv_name) if motiv_name else None
        gesprochen = spoken_slot(iso)
        if arzt:
            gesprochen += f" bei {arzt}"
        termine.append({
            "id": _s(nxt.get("appointmentId")),
            "iso": iso,
            "date": iso[:10],
            "calendarId": _s(nxt.get("calendarId")),
            "doctorName": arzt,
            "motivId": _s(nxt.get("visitMotiveId") or (motiv or {}).get("id")),
            "motivName": motiv_name,
            "spoken": gesprochen,
        })
    return _mit_dispatch({
        "ok": True,
        "patient": patient,
        "appointments": termine,
        "notFound": bool(match_source == "name60" and not termine),
        "nameMismatch": bool(match_source == "name60" and not termine),
        "vornameVerworfen": vorname_verworfen,
        "fallbackUsed": True,
        "fuzzyName": min_similarity < 1.0,
        "matchSource": match_source,
    }, termin_dispatch)


def find_patient_appointments(
    tenant: dict,
    ctx: dict,
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Kommende Termine zum NAMEN — ueber die warme Demo-Function
    agentFindPatientAppointments (Patient + Termine in EINEM Aufruf,
    inkl. Behandlername, Kalender-ID und Behandlungsgrund)."""
    first, last = _name_teile(ctx)
    if not last:
        return {"ok": False, "appointments": [], "spoken": "Wie ist Ihr Nachname?"}
    duplicate_ids = list(dict.fromkeys(
        _s(x) for x in (ctx.get("duplicatePatientIds") or [])
        if _s(x)
    ))
    duplicate_patients: list[dict] = []
    if len(duplicate_ids) > 1:
        duplicate_patients = [
            {
                "id": patient_id,
                "firstName": first,
                "lastName": last,
                "createdAt": (ctx.get("duplicatePatientCreatedAt") or {}).get(
                    patient_id),
            }
            for patient_id in duplicate_ids
        ]
    if len(duplicate_patients) > 1:
        return _firestore_duplicate_patient_appointments(
            tenant, duplicate_patients)
    body = {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "lastName": last,
        "source": "telefonki-lisa",
    }
    if first:
        body["firstName"] = first
    pid = _s(ctx.get("patientId"))
    if pid:
        body["patientId"] = pid
    phone = _s(ctx.get("phone"))
    if phone:
        body["callerPhone"] = phone
    management_name_match = bool(ctx.get("managementNameMatch"))
    status, data, dispatch = _cf_call(
        "agentFindPatientAppointments", body, timeout=timeout
    )
    if not isinstance(data, dict):
        data = {}
    vorname_verworfen = False
    if (status == 404 and _s(data.get("status")) != "no_upcoming"
            and body.get("firstName") and not management_name_match):
        # W-NAMESKORREKTUR (31.08.2026): der Vorname kann selbst verhoert
        # sein ("Sannes" statt Georgios) und die Suche allein deshalb leer
        # ausgehen — einmal NUR mit dem Nachnamen nachfassen. Meldet die CF
        # dann ambiguous, fragt die Prozedur den Vornamen ohnehin sauber nach.
        body = {k: v for k, v in body.items() if k != "firstName"}
        status, data, dispatch = _cf_call(
            "agentFindPatientAppointments", body, timeout=timeout
        )
        if not isinstance(data, dict):
            data = {}
        vorname_verworfen = True
    pat = data.get("patient") or {}
    patient = {
        "id": _s(pat.get("id")),
        "firstName": _s(pat.get("firstName")),
        "lastName": _s(pat.get("lastName")),
    }
    if status == 200 and data.get("status") == "success":
        match_source = _management_match_source(
            first=first,
            last=last,
            patient=pat,
            patient_id=pid,
            phone=phone,
        ) if management_name_match else ""
        if management_name_match and not match_source:
            fallback = _patient_appointments_fallback(
                tenant,
                first=first,
                last=last,
                vorname_verworfen=False,
                primary_dispatch=dispatch,
                patient_id=pid,
                phone=phone,
                min_similarity=0.60,
            )
            if fallback is not None:
                return fallback
            return _mit_dispatch({
                "ok": True,
                "notFound": True,
                "nameMismatch": True,
                "patient": {},
                "appointments": [],
            }, dispatch)
        termine = []
        for a in data.get("appointments") or []:
            if not isinstance(a, dict) or not _management_appointment_active(a):
                continue
            iso = _s(a.get("start")).replace(" ", "T")[:16]
            if len(iso) < 16:
                iso = f"{_s(a.get('appointmentDate'))}T{_s(a.get('appointmentTime'))}"
            arzt = _s(a.get("doctorName")).split(",")[0].strip()
            vm = a.get("visitMotive") or {}
            gesprochen = spoken_slot(iso)
            if arzt:
                gesprochen += f" bei {arzt}"
            termine.append({
                "id": _s(a.get("appointmentId")),
                "iso": iso,
                "date": iso[:10],
                "calendarId": _s(a.get("calendarId")),
                "doctorName": arzt,
                "motivId": _s(vm.get("id")),
                "motivName": _s(vm.get("name")),
                "spoken": gesprochen,
            })
        return _mit_dispatch({
            "ok": True,
            "patient": patient,
            "appointments": termine,
            "matchSource": match_source,
            "vornameVerworfen": vorname_verworfen,
        }, dispatch)
    if status == 404 and data.get("status") == "no_upcoming":
        match_source = _management_match_source(
            first=first,
            last=last,
            patient=pat,
            patient_id=pid,
            phone=phone,
        ) if management_name_match else ""
        if management_name_match and not match_source:
            fallback = _patient_appointments_fallback(
                tenant,
                first=first,
                last=last,
                vorname_verworfen=False,
                primary_dispatch=dispatch,
                patient_id=pid,
                phone=phone,
                min_similarity=0.60,
            )
            if fallback is not None:
                return fallback
            return _mit_dispatch({
                "ok": True,
                "notFound": True,
                "nameMismatch": True,
                "patient": {},
                "appointments": [],
            }, dispatch)
        fuzzy = match_source == "name60"
        return _mit_dispatch({
            "ok": True,
            "notFound": fuzzy,
            "nameMismatch": fuzzy,
            "patient": patient,
            "appointments": [],
            "matchSource": match_source,
            "vornameVerworfen": vorname_verworfen,
        }, dispatch)
    if status == 404:
        fallback = _patient_appointments_fallback(
            tenant,
            first=first,
            last=last,
            vorname_verworfen=vorname_verworfen,
            primary_dispatch=dispatch,
            patient_id=pid if management_name_match else "",
            phone=phone if management_name_match else "",
            min_similarity=0.60 if management_name_match else 1.0,
        )
        if fallback is not None:
            return fallback
        return _mit_dispatch({"ok": True, "notFound": True, "patient": {}, "appointments": []}, dispatch)
    if status == 409 or _s(data.get("status")).lower() in {"conflict", "ambiguous"}:
        # Mehrere Patienten mit gleichem Nachnamen (W-NACHNAME 31.08.2026,
        # phone_agent-Vorbild): der Anrufer muss den Vornamen nachliefern,
        # dann wird mit firstName erneut gesucht. vornameVerworfen sagt dem
        # Aufrufer: der GESPEICHERTE Vorname passte nicht — leeren und fragen.
        # Sind Vor- UND Nachname bereits identisch, ist eine erneute
        # Vornamenfrage dagegen sinnlos: alle gleichnamigen Dubletten lesen.
        if first:
            fallback = _patient_appointments_fallback(
                tenant,
                first=first,
                last=last,
                vorname_verworfen=False,
                primary_dispatch=dispatch,
                patient_id="",
                phone="",
                min_similarity=1.0,
            )
            if fallback is not None and (
                    fallback.get("duplicateCount")
                    or not fallback.get("mehrdeutig")):
                return fallback
        return _mit_dispatch({"ok": True, "mehrdeutig": True, "patient": {}, "appointments": [],
                "vornameVerworfen": vorname_verworfen}, dispatch)
    msg = _s(data.get("message")) or f"http_{status}"
    return _mit_dispatch({"ok": False, "appointments": [], "error": msg}, dispatch)


def _firestore_appointments_query(
    tenant: dict,
    von_utc: str,
    bis_utc: str,
) -> tuple[int, Any, dict]:
    """Standort-Termine in einem UTC-Fenster lesen; niemals schreiben.

    Der Dispatch enthaelt bewusst nur Datum und Trefferzahl, nicht die
    Patientendaten aller Termine dieses Tages.
    """
    from kern import anrufaudio, standort
    from kern.config import FIREBASE_CREDENTIALS

    client_id = _s(tenant.get("clientId"))
    location_id = _s(tenant.get("locationId"))
    request_meta = {
        "clientId": client_id,
        "locationId": location_id,
        "from": von_utc,
        "to": bis_utc,
    }
    dispatch = {
        "route": "firestoreAppointmentsByDate",
        "method": "POST",
        "request": request_meta,
    }
    if not FIREBASE_CREDENTIALS or not client_id or not location_id:
        dispatch.update({"httpStatus": 0, "response": {"appointments": 0}})
        return 0, {"message": "firestore_unavailable"}, dispatch
    try:
        token = anrufaudio._access_token(
            "https://www.googleapis.com/auth/datastore")
        projekt = standort._projekt()
        url = (
            "https://firestore.googleapis.com/v1/projects/"
            f"{projekt}/databases/(default)/documents/clients/{client_id}/"
            f"locations/{location_id}:runQuery"
        )
        body = {
            "structuredQuery": {
                "select": {"fields": [
                    {"fieldPath": f} for f in (
                        "start", "end", "status", "patientStatus",
                        "isDeleted", "deletedAt",
                        "patient", "calendar", "visitMotive",
                    )
                ]},
                "from": [{"collectionId": "appointments"}],
                "where": {"compositeFilter": {
                    "op": "AND",
                    "filters": [
                        {"fieldFilter": {
                            "field": {"fieldPath": "start"},
                            "op": "GREATER_THAN_OR_EQUAL",
                            "value": {"timestampValue": von_utc},
                        }},
                        {"fieldFilter": {
                            "field": {"fieldPath": "start"},
                            "op": "LESS_THAN",
                            "value": {"timestampValue": bis_utc},
                        }},
                    ],
                }},
                "orderBy": [{
                    "field": {"fieldPath": "start"},
                    "direction": "ASCENDING",
                }],
                # Ein voller Praxistag liegt weit darunter. Wird der Deckel
                # doch erreicht, gilt die Suche als unvollstaendig und darf
                # keinen Termin automatisch bestimmen.
                "limit": 500,
            },
        }
        t0 = time.perf_counter()
        r = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=10.0,
        )
        ms = int(round((time.perf_counter() - t0) * 1000))
        try:
            data = r.json()
        except ValueError:
            data = {"message": r.text[:160]}
        n = sum(
            1 for row in data if isinstance(row, dict) and row.get("document")
        ) if isinstance(data, list) else 0
        dispatch.update({
            "url": url,
            "httpStatus": r.status_code,
            "ms": ms,
            "response": {"appointments": n},
        })
        return r.status_code, data, dispatch
    except Exception as e:
        dispatch.update({
            "httpStatus": 0,
            "response": {"appointments": 0, "error": type(e).__name__},
        })
        return 0, {"message": str(e)}, dispatch


def find_appointments_by_date(tenant: dict, day: str) -> dict[str, Any]:
    """Patiententermine eines Praxistags fuer sichere Verwaltung lesen.

    Dieser Weg ist absichtlich unabhaengig vom Namen: Datum/Uhrzeit,
    Behandler, Rufnummer beziehungsweise patientId und erst danach ein
    mindestens sechzigprozentiger Namensabgleich bestimmen den Kandidaten
    in ``bianca.verwalten``. Schreiben erfolgt weiterhin ausschliesslich
    punktgenau per Termin-ID und erst nach ausdruecklicher Rueckfrage.
    """
    if not VERWALTUNG_TERMIN_DETAILS:
        return {"ok": False, "unavailable": True, "appointments": [],
                "error": "disabled"}
    try:
        d = date.fromisoformat(_s(day)[:10])
    except ValueError:
        return {"ok": False, "appointments": [], "error": "invalid_date"}
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    ende = start + timedelta(days=1)

    def utc_wert(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    status, data, dispatch = _firestore_appointments_query(
        tenant, utc_wert(start), utc_wert(ende))
    if status != 200 or not isinstance(data, list):
        msg = _s(data.get("message")) if isinstance(data, dict) else f"http_{status}"
        return _mit_dispatch({
            "ok": False,
            "unavailable": True,
            "appointments": [],
            "error": msg or f"http_{status}",
        }, dispatch)

    from kern import standort
    termine: list[dict[str, Any]] = []
    roh_dokumente = sum(
        1 for row in data if isinstance(row, dict) and row.get("document"))
    jetzt = datetime.now(TZ)
    for row in data:
        doc = row.get("document") if isinstance(row, dict) else None
        if not isinstance(doc, dict):
            continue
        felder = doc.get("fields")
        if not isinstance(felder, dict):
            continue
        f = {k: standort._decode(v) for k, v in felder.items()}
        if f.get("isDeleted") is True or f.get("deletedAt"):
            continue
        if _s(f.get("status")).casefold() in {
            "cancelled", "canceled", "deleted", "declined",
            "needsconfirmation", "reserved",
        }:
            continue
        if f.get("patientStatus") not in (None, "", 0, "0", "none"):
            continue
        patient = f.get("patient") if isinstance(f.get("patient"), dict) else {}
        patient_id = _s(patient.get("id"))
        first = _s(patient.get("firstName"))
        last = _s(patient.get("lastName"))
        if not patient_id and not last:
            continue
        cal = f.get("calendar") if isinstance(f.get("calendar"), dict) else {}
        vm = f.get("visitMotive") if isinstance(f.get("visitMotive"), dict) else {}
        roh_start = _s(f.get("start"))
        try:
            lokal = datetime.fromisoformat(roh_start.replace("Z", "+00:00")).astimezone(TZ)
        except ValueError:
            continue
        if lokal.date() != d:
            continue
        if lokal < jetzt - timedelta(minutes=5):
            continue
        arzt = _s(cal.get("name")).split(",")[0].strip()
        iso = lokal.isoformat(timespec="minutes")
        gesprochen = spoken_slot(iso)
        if arzt:
            gesprochen += f" bei {arzt}"
        phone = next((
            _s(patient.get(k)) for k in (
                "mobilePhoneNumber", "mobilePhone", "phoneNumber",
                "phone", "telephone",
            ) if _s(patient.get(k))
        ), "")
        termine.append({
            "id": _s(doc.get("name")).rsplit("/", 1)[-1],
            "iso": iso,
            "date": iso[:10],
            "calendarId": _s(cal.get("id")),
            "doctorName": arzt,
            "motivId": _s(vm.get("id")),
            "motivName": _s(vm.get("name")),
            "spoken": gesprochen,
            "patientId": patient_id,
            "patientFirstName": first,
            "patientLastName": last,
            "patientName": f"{first} {last}".strip(),
            "patientPhone": phone,
        })
    termine.sort(key=lambda a: (_s(a.get("iso")), _s(a.get("id"))))
    return _mit_dispatch({
        "ok": True,
        "appointments": termine,
        "truncated": roh_dokumente >= 500,
    }, dispatch)


def cancel_by_id(tenant: dict, ctx: dict, appointment_id: str) -> dict[str, Any]:
    """Punktgenauer Storno ueber agentCancelAppointmentById (warm).

    Anders als updateOrCancelAppointment(action=cancel) trifft das GENAU den
    einen Termin — nicht alle des Tages mit passendem Nachnamen."""
    aid = _s(appointment_id)
    if not aid:
        return {"ok": False, "spoken": "Welchen Termin soll ich absagen?"}
    if not WRITE_LIVE or _test_no_write(tenant):
        return {
            "ok": True, "cancelled": False, "dryRun": True, "appointmentId": aid,
            "spoken": "Den Termin hätte ich jetzt abgesagt.",
            "regie": "Testmodus: der Kalender wurde nicht geändert.",
        }
    blocked = _management_uncertain_guard(
        ctx,
        operation="cancel",
        appointment_id=aid,
    )
    if blocked:
        return blocked
    status, data, dispatch = _cf_call("agentCancelAppointmentById", {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "appointmentId": aid,
        "source": "telefonki-lisa",
    }, timeout=_SCHREIB_TIMEOUT)
    reported_success = (
        status == 200
        and isinstance(data, dict)
        and data.get("status") == "success"
    )
    if reported_success or status == 0 or status >= 500:
        complete, appointment = _management_readback_by_id(
            tenant,
            aid,
            _s(ctx.get("appointmentDate") or ctx.get("slotIso")),
            absent_ok=True,
        )
        if complete and appointment is None:
            ctx["appointmentId"] = aid
            return _mit_dispatch({
                "ok": True,
                "cancelled": True,
                "appointmentId": aid,
                "recoveredBy": "calendar_readback",
                "verified": True,
                "spoken": "Der Termin ist abgesagt.",
            }, dispatch)
        gesprochen = (
            "Die Absage wurde technisch angenommen, ist im Kalender aber "
            "noch nicht eindeutig bestätigt. Die Praxis prüft das."
            if reported_success
            else
            "Ob die Absage durchgeführt wurde, ist im Kalender noch nicht "
            "eindeutig. Die Praxis prüft das."
        )
        return _management_uncertain_mark(
            ctx,
            operation="cancel",
            appointment_id=aid,
            reason=(
                "readback_active"
                if complete and appointment is not None
                else "readback_inconclusive"
            ),
            dispatch=dispatch,
            spoken=gesprochen,
            regie="Kein Erfolgssatz ohne exakte Rücklese der Termin-ID.",
        )
    msg = (data or {}).get("message") if isinstance(data, dict) else f"http_{status}"
    return _mit_dispatch({
        "ok": False,
        "spoken": "Die Absage hat gerade nicht geklappt. Die Praxis kümmert sich darum.",
        "regie": f"Absage fehlgeschlagen: {msg}",
    }, dispatch)


def _firestore_appointment_by_id(
    tenant: dict,
    appointment_id: str,
    *,
    timeout: float = 2.0,
    expected_name_confirm_token: str = "",
) -> dict[str, Any]:
    """Einen Termin ohne Namens-/Tagesfilter direkt und datensparsam lesen."""
    from kern import anrufaudio, standort
    from kern.config import FIREBASE_CREDENTIALS

    client_id = _s(tenant.get("clientId"))
    location_id = _s(tenant.get("locationId"))
    aid = _s(appointment_id)
    if not FIREBASE_CREDENTIALS or not client_id or not location_id or not aid:
        return {"ok": False, "error": "firestore_unavailable"}
    try:
        token = anrufaudio._access_token(
            "https://www.googleapis.com/auth/datastore")
        projekt = standort._projekt()
        url = (
            "https://firestore.googleapis.com/v1/projects/"
            f"{projekt}/databases/(default)/documents/clients/{client_id}/"
            f"locations/{location_id}/appointments/{aid}"
        )
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "mask.fieldPaths": [
                    "start", "status", "patientStatus", "isDeleted",
                    "deletedAt", "patient", "calendar", "resourceId",
                    "visitMotive", "nameConfirmToken",
                    "nameConfirmPending", "confirmationHeld",
                ],
            },
            timeout=timeout,
        )
        if response.status_code == 404:
            # Anders als das Fehlen in einer gefilterten Tagesliste ist das
            # exakte 404 derselben Dokument-ID ein belastbarer Löschbeweis.
            return {"ok": True, "missing": True, "appointmentId": aid}
        if response.status_code != 200:
            return {"ok": False, "error": f"http_{response.status_code}"}
        raw = response.json()
        fields = raw.get("fields") if isinstance(raw, dict) else None
        if not isinstance(fields, dict):
            return {"ok": False, "error": "invalid_document"}
        values = {k: standort._decode(v) for k, v in fields.items()}
        state = _s(values.get("status")).casefold()
        patient_status = values.get("patientStatus")
        try:
            patient_status_num = int(patient_status)
        except (TypeError, ValueError):
            patient_status_num = None
        deleted = bool(
            values.get("isDeleted") is True
            or values.get("deletedAt")
            or state in {"cancelled", "canceled", "deleted", "declined"}
            or patient_status_num in {4, 5}
        )
        start = _s(values.get("start"))
        if start:
            try:
                start = datetime.fromisoformat(
                    start.replace("Z", "+00:00")).astimezone(TZ).isoformat(
                        timespec="minutes")
            except ValueError:
                pass
        patient = values.get("patient")
        calendar = values.get("calendar")
        visit_motive = values.get("visitMotive")
        return {
            "ok": True,
            "deleted": deleted,
            "appointment": {
                "id": aid,
                "iso": start,
                "status": state,
                "patientStatus": patient_status,
                "patientId": (
                    _s(patient.get("id"))
                    if isinstance(patient, dict)
                    else ""
                ),
                "calendarId": (
                    _s(calendar.get("id"))
                    if isinstance(calendar, dict)
                    else _s(values.get("resourceId"))
                ),
                "visitMotiveId": (
                    _s(visit_motive.get("id"))
                    if isinstance(visit_motive, dict)
                    else ""
                ),
                "nameConfirmTokenMatches": (
                    not expected_name_confirm_token
                    or _s(values.get("nameConfirmToken"))
                    == _s(expected_name_confirm_token)
                ),
                "nameConfirmPending": values.get("nameConfirmPending"),
                "confirmationHeld": values.get("confirmationHeld"),
            },
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def _management_readback_by_id(
    tenant: dict,
    appointment_id: str,
    slot_iso: str,
    *,
    absent_ok: bool = False,
    expected_iso: str = "",
) -> tuple[bool, dict[str, Any] | None]:
    """Exakte Termin-ID nach einem unklaren Write direkt nachlesen.

    Eine gefilterte Tagesliste darf eine Absage nie beweisen: sie blendet
    abgesagte/virtuelle Termine aus und kann gekappt sein. Der direkte
    Firestore-GET ist punktgenau und stark konsistent. Erfolg bedeutet hier
    deshalb entweder ein explizit als gelöscht/abgesagt markiertes Dokument
    (beziehungsweise dessen exaktes 404) oder beim Verschieben dieselbe ID
    mit exakt der erwarteten Startminute.
    """
    if (
        not MANAGEMENT_WRITE_RECOVERY
        or not _s(appointment_id)
    ):
        return False, None
    last_complete = False
    last_appointment: dict[str, Any] | None = None
    for delay in _MANAGEMENT_RECOVERY_DELAYS:
        if delay:
            time.sleep(delay)
        found = _firestore_appointment_by_id(
            tenant, _s(appointment_id), timeout=2.0)
        if not found.get("ok"):
            continue
        last_complete = True
        if found.get("missing") or found.get("deleted"):
            appointment = None
        else:
            appointment = found.get("appointment")
        last_appointment = appointment
        if absent_ok and appointment is None:
            return True, None
        if (
            expected_iso
            and appointment is not None
            and _management_appointment_active(appointment)
            and _s(appointment.get("iso")).replace(" ", "T")[:16]
            == _s(expected_iso).replace(" ", "T")[:16]
        ):
            return True, appointment
        # Ein noch aktives exaktes Dokument ist beim ersten Wurf kein
        # Gegenbeweis: der Schreib-Timeout kann dem Commit knapp voraus sein.
    return last_complete, last_appointment


def _termin_id_suchen(tenant: dict, ctx: dict, iso: str) -> str:
    """Read-only: Termin-ID zum gebuchten Slot ueber agentFindPatientAppointments."""
    if len(_s(iso)) < 10:
        return ""
    found = find_patient_appointments(tenant, ctx)
    tag, minute = iso[:10], (iso[11:16] if len(iso) >= 16 else "")
    for a in found.get("appointments") or []:
        if a.get("date") != tag:
            continue
        if minute and len(a.get("iso") or "") >= 16 and a["iso"][11:16] != minute:
            continue
        return _s(a.get("id"))
    return ""


def _name_teile(ctx: dict) -> tuple[str, str]:
    first = _s(ctx.get("firstName"))
    last = _s(ctx.get("lastName"))
    if last:
        return first, last
    teile = _s(ctx.get("patientName")).split()
    if len(teile) >= 2:
        return teile[0], teile[-1]
    return first, teile[0] if teile else ""


def _termin_datum(ctx: dict, date: str = "") -> str:
    raw = _s(date) or _s(ctx.get("appointmentDate")) or _s(ctx.get("slotIso"))
    if len(raw) >= 10 and raw[4] == "-":
        return raw[:10]
    return ""


def _cf_update(action: str, body: dict) -> tuple[int, Any, dict]:
    payload = {**body, "action": action}
    return _cf_call("updateOrCancelAppointment", payload, timeout=_SCHREIB_TIMEOUT)


def _ctx_aus_sitzung(sit: dict, ctx: dict) -> dict:
    """booking-ctx aus Sammler / sit.patient / Anrufer fuellen (Bianca-Live
    06.09.2026: list_appointments sah sonst leeres patient/upcoming und
    behauptete 'keinen Termin', obwohl die CF den Bestand kannte)."""
    out = ctx if isinstance(ctx, dict) else {}
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    pat = sit.get("patient") if isinstance(sit.get("patient"), dict) else {}
    a = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
    # Abgelehnter Rufnummer-Treffer darf die Tool-Suche nicht weiter fuettern.
    if _s(s.get("anruferCheck")) == "nein":
        a = {}
    if not _s(out.get("lastName")):
        out["lastName"] = _s(s.get("nachname")) or _s(pat.get("lastName")) or _s(a.get("nachname"))
    if not _s(out.get("firstName")):
        out["firstName"] = _s(s.get("vorname")) or _s(pat.get("firstName")) or _s(a.get("vorname"))
    if not _s(out.get("patientId")):
        out["patientId"] = _s(s.get("patientId")) or _s(pat.get("id")) or _s(a.get("patientId"))
    if not _s(out.get("phone")):
        out["phone"] = (
            _s(s.get("telefon")) or _s(s.get("aktePhone"))
            or _s(pat.get("phone")) or _s(a.get("telefon"))
        )
    if not _s(out.get("patientName")):
        name = f"{_s(out.get('firstName'))} {_s(out.get('lastName'))}".strip()
        if name:
            out["patientName"] = name
    return out


def _termine_als_upcoming(termine: list | None) -> list[dict[str, str]]:
    """find_patient_appointments-Treffer → upcoming-Labels fuer list_appointments."""
    out: list[dict[str, str]] = []
    for a in termine or []:
        if not isinstance(a, dict):
            continue
        iso = _s(a.get("iso"))
        spoken = _s(a.get("spoken"))
        if not spoken and iso:
            spoken = spoken_slot(iso) if "T" in iso else iso
        if not spoken:
            continue
        # spoken enthaelt oft schon den Behandler — Motiv nur ergaenzen.
        motiv = _s(a.get("motivName"))
        label = spoken
        if motiv and motiv.lower() not in spoken.lower():
            label = f"{spoken} — {motiv}"
        out.append({
            "id": _s(a.get("id")),
            "iso": iso,
            "date": _s(a.get("date")) or (iso[:10] if len(iso) >= 10 else ""),
            "label": label,
        })
    return out


def list_appointments(tenant: dict, ctx: dict, upcoming: list | None = None, sit: dict | None = None) -> dict[str, Any]:
    if sit is not None:
        ctx = _ctx_aus_sitzung(sit, ctx if isinstance(ctx, dict) else {})
        # Spiegel in booking + patient, damit Folge-Tools dieselbe Identitaet sehen.
        booking = sit.setdefault("booking", {})
        if isinstance(booking, dict):
            for k in ("firstName", "lastName", "patientId", "phone", "patientName"):
                if _s(ctx.get(k)) and not _s(booking.get(k)):
                    booking[k] = ctx[k]
        if _s(ctx.get("lastName")) or _s(ctx.get("patientId")):
            alt = sit.get("patient") if isinstance(sit.get("patient"), dict) else {}
            sit["patient"] = {
                **alt,
                "id": _s(ctx.get("patientId")) or _s(alt.get("id")),
                "firstName": _s(ctx.get("firstName")) or _s(alt.get("firstName")),
                "lastName": _s(ctx.get("lastName")) or _s(alt.get("lastName")),
                "name": _s(ctx.get("patientName")) or _s(alt.get("name")),
                "phone": _s(ctx.get("phone")) or _s(alt.get("phone")),
            }
        # Die Anreicherung beim Start hat die Termine schon geholt — nur bei
        # leerer Sitzung noch einmal fragen (spart einen ganzen Netz-Umlauf).
        if sit.get("upcoming"):
            upcoming = sit["upcoming"]
        else:
            hist = patients.termine_fuer(tenant, sit.get("patient") or {})
            upcoming = hist["upcoming"]
            sit["past"] = hist["past"]
            # Fallback: CF-Namenssuche (wie Auskunft/Absage), wenn die Akte
            # am sit.patient keine upcoming trug — typisch Bianca-SIP.
            if not upcoming and _s(ctx.get("lastName")):
                found = find_patient_appointments(tenant, ctx)
                if (found.get("ok") and not found.get("notFound")
                        and not found.get("mehrdeutig")):
                    upcoming = _termine_als_upcoming(found.get("appointments") or [])
                    pat = found.get("patient") or {}
                    if _s(pat.get("id")):
                        cur = sit.get("patient") if isinstance(sit.get("patient"), dict) else {}
                        sit["patient"] = {
                            **cur,
                            "id": _s(pat.get("id")),
                            "firstName": _s(pat.get("firstName")) or cur.get("firstName") or "",
                            "lastName": _s(pat.get("lastName")) or cur.get("lastName") or "",
                            "name": (
                                f"{_s(pat.get('firstName'))} {_s(pat.get('lastName'))}".strip()
                                or cur.get("name") or ""
                            ),
                        }
            sit["upcoming"] = upcoming or []
        nxt = (upcoming or [None])[0] if upcoming else None
        if nxt and isinstance(nxt, dict):
            ctx["appointmentId"] = nxt.get("id") or ctx.get("appointmentId")
            ctx["appointmentDate"] = nxt.get("date") or ctx.get("appointmentDate")
            ctx["slotIso"] = nxt.get("iso") or ctx.get("slotIso")
    items = []
    for a in upcoming or []:
        if isinstance(a, dict) and a.get("label"):
            items.append(a)
    if not items:
        return {"ok": True, "appointments": [], "spoken": "In der Akte sehe ich gerade keinen kommenden Termin."}
    labels = "; ".join(_s(a.get("label")) for a in items[:4])
    return {
        "ok": True,
        "appointments": items,
        "spoken": f"Kommend steht: {labels}.",
    }


def cancel_appointment(tenant: dict, ctx: dict, *, date: str = "") -> dict[str, Any]:
    first, last = _name_teile(ctx)
    day = _termin_datum(ctx, date)
    if not last:
        return {
            "ok": False,
            "spoken": "Wie ist Ihr Nachname?",
            "regie": "Nachname fehlt für die Absage.",
        }
    if not day:
        return {"ok": False, "spoken": "Welchen Termin soll ich absagen?"}
    if not WRITE_LIVE or _test_no_write(tenant):
        return {
            "ok": True,
            "cancelled": False,
            "dryRun": True,
            "appointmentDate": day,
            "spoken": f"Den Termin {slot_wort(day)} hätte ich jetzt abgesagt.",
            "regie": "Testmodus: der Kalender wurde nicht geändert.",
        }
    body = {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "lastName": last,
        "appointmentDate": day,
        "source": "telefonki-lisa",
    }
    if first:
        body["firstName"] = first
    status, data, dispatch = _cf_update("cancel", body)
    if status == 200 and isinstance(data, dict) and data.get("success"):
        return _mit_dispatch({
            "ok": True,
            "cancelled": True,
            "appointmentDate": day,
            "spoken": f"Der Termin {slot_wort(day)} ist abgesagt.",
        }, dispatch)
    if status == 409:
        return _mit_dispatch({
            "ok": False,
            "spoken": "Wie ist Ihr Vorname? Es gibt mehrere Patienten mit diesem Nachnamen.",
        }, dispatch)
    if status == 404:
        return _mit_dispatch({
            "ok": False,
            "spoken": "An diesem Tag finde ich unter Ihrem Namen keinen Termin.",
        }, dispatch)
    msg = (data or {}).get("message") if isinstance(data, dict) else f"http_{status}"
    return _mit_dispatch({
        "ok": False,
        "spoken": "Die Absage hat gerade nicht geklappt. Die Praxis kümmert sich darum.",
        "regie": f"Absage fehlgeschlagen: {msg}",
    }, dispatch)


def offer_move(tenant: dict, ctx: dict, *, date: str = "", wish: str = "") -> dict[str, Any]:
    first, last = _name_teile(ctx)
    day = _termin_datum(ctx, date)
    if last and day:
        body = {
            "clientId": _s(tenant.get("clientId")),
            "locationId": _s(tenant.get("locationId")),
            "lastName": last,
            "appointmentDate": day,
            "source": "telefonki-lisa",
        }
        if first:
            body["firstName"] = first
        if wish:
            parsed = parse_slot_wish(wish)
            if parsed and parsed.get("date"):
                heute = datetime.now(TZ).date().isoformat()
                body["startSearchDate"] = max(_s(parsed["date"])[:10], heute)
        status, data, dispatch = _cf_update("find-for-postpone", body)
        if status == 200 and isinstance(data, dict) and data.get("success"):
            appt = data.get("appointment") or {}
            raw_slots = data.get("freeSlots") or []
            slots = []
            for s in raw_slots[:8]:
                iso = str(s).replace(" ", "T")
                if len(iso) >= 16:
                    slots.append({"iso": iso, "spoken": spoken_slot(iso)})
            aid = _s(appt.get("appointmentId"))
            liste = "; oder ".join(x["spoken"] for x in slots)
            return _mit_dispatch({
                "ok": True,
                "appointmentId": aid,
                "slots": slots,
                "spoken": (
                    f"Frei zum Verschieben: {liste}. Welcher passt?"
                    if slots else
                    "Ich habe den Termin, aber gerade keinen freien Ausweichplatz."
                ),
            }, dispatch)
        if status == 409:
            return _mit_dispatch({
                "ok": False,
                "spoken": "Wie ist Ihr Vorname? Es gibt mehrere Patienten mit diesem Nachnamen.",
            }, dispatch)
    return offer_slots(tenant, ctx, wish_text=wish)


def move_appointment(tenant: dict, ctx: dict, *, slot_iso: str = "", date: str = "", wish: str = "") -> dict[str, Any]:
    iso = _s(slot_iso)
    if len(iso) < 16:
        found = offer_move(tenant, ctx, date=date, wish=wish)
        if found.get("appointmentId"):
            ctx["appointmentId"] = found["appointmentId"]
        return found
    if _slot_gesperrt(ctx, iso):
        alt = _frische_konflikt_slots(tenant, ctx, iso)
        return {
            "ok": False,
            "moved": False,
            "slotTaken": True,
            "alreadyBlocked": True,
            "writeAttempted": False,
            "blockedIso": iso,
            "slotIso": iso,
            "spoken": "Dieser Platz ist bereits vergeben. " + (alt.get("spoken") or ""),
            "slots": alt.get("slots") or [],
            "alternativeDispatch": alt.get("dispatch"),
        }
    aid = _s(ctx.get("appointmentId"))
    if not aid:
        looked = offer_move(tenant, ctx, date=date)
        aid = _s(looked.get("appointmentId"))
        if looked.get("slots") and not aid:
            return looked
    if not aid:
        return {
            "ok": False,
            "spoken": "Welchen Termin möchten Sie verschieben?",
            "regie": "appointmentId fehlt. Erst den bestehenden Termin klären (list_appointments oder Datum erfragen).",
        }
    if not WRITE_LIVE or _test_no_write(tenant):
        return {
            "ok": True,
            "moved": False,
            "dryRun": True,
            "appointmentId": aid,
            "slotIso": iso,
            "spoken": (
                f"Nach {spoken_slot(iso)} hätte ich jetzt verschoben — "
                "der Test ändert den Kalender nicht."
            ),
        }
    blocked = _management_uncertain_guard(
        ctx,
        operation="move",
        appointment_id=aid,
        slot_iso=iso,
    )
    if blocked:
        return blocked
    body = {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "appointmentId": aid,
        "newStartDate": iso.replace("T", " ")[:16],
        "source": "telefonki-lisa",
    }
    status, data, dispatch = _cf_update("postpone", body)
    reported_success = (
        status == 200
        and isinstance(data, dict)
        and data.get("success")
    )
    if reported_success or status == 0 or status >= 500:
        complete, appointment = _management_readback_by_id(
            tenant, aid, iso, expected_iso=iso)
        if (
            complete
            and appointment is not None
            and _management_appointment_active(appointment)
            and _s(appointment.get("iso")).replace(" ", "T")[:16]
            == iso.replace(" ", "T")[:16]
        ):
            return _mit_dispatch({
                "ok": True,
                "moved": True,
                "appointmentId": aid,
                "slotIso": iso,
                "recoveredBy": "calendar_readback",
                "verified": True,
                "spoken": f"Der Termin liegt jetzt {spoken_slot(iso)}.",
            }, dispatch)
        gesprochen = (
            "Die Verschiebung wurde technisch angenommen, ist im Kalender "
            "aber noch nicht eindeutig bestätigt. Die Praxis prüft das."
            if reported_success
            else
            "Ob die Verschiebung durchgeführt wurde, ist im Kalender noch "
            "nicht eindeutig. Die Praxis prüft das."
        )
        return _management_uncertain_mark(
            ctx,
            operation="move",
            appointment_id=aid,
            slot_iso=iso,
            reason=(
                "readback_unexpected_state"
                if complete and appointment is not None
                else "readback_inconclusive"
            ),
            dispatch=dispatch,
            spoken=gesprochen,
            regie="Kein Erfolgssatz ohne exakte Rücklese der Termin-ID.",
        )
    if status == 400:
        msg = _s(data.get("message")) if isinstance(data, dict) else ""
        # Stufe 1e: NUR „The slot is not available." ist ein echter Slot-
        # Konflikt und bleibt slotTaken (dann Alternativen anbieten). Jede
        # andere 400 — insbesondere „cannot be postponed" (Termin nicht
        # bestätigt / bereits bearbeitet) — ist KEIN freier/belegter Platz:
        # kein Alternativ-Kreisel, sondern ehrlich an die Praxis notieren.
        if "slot is not available" in msg.lower():
            # Beim Verschieben muessen Alternativen im GLEICHEN Kalender und mit
            # dem GLEICHEN Besuchsgrund ab dem gewuenschten Tag gesucht werden.
            # Ohne start_date sprang der Rueckfall live (Thaler 09.09.2026) von
            # Oktober zurueck auf September; ohne Motiv im ctx wurden ausserdem
            # unpassende Kontroll-Slots angeboten.
            alt = _frische_konflikt_slots(tenant, ctx, iso)
            return _mit_dispatch({
                "ok": False,
                "slotTaken": True,
                "writeAttempted": True,
                "blockedIso": iso,
                "slotIso": iso,
                "spoken": "Dieser Platz ist nicht mehr frei. " + (alt.get("spoken") or ""),
                "slots": alt.get("slots") or [],
                "alternativeDispatch": alt.get("dispatch"),
            }, dispatch)
        return _mit_dispatch({
            "ok": False,
            "terminGesperrt": True,
            "writeAttempted": True,
            "appointmentId": aid,
            "slotIso": iso,
            "message": msg,
        }, dispatch)
    return _mit_dispatch({"ok": False, "spoken": "Verschieben hat gerade nicht geklappt."}, dispatch)


def _notiz_ziel(tenant: dict, ctx: dict, sit: dict | None) -> str:
    """An welchen Termin gehoert die Notiz? Frisch gebucht > bestehender Termin."""
    aid = _s(ctx.get("appointmentId"))
    if aid:
        return aid
    if sit:
        for a in sit.get("upcoming") or []:
            if isinstance(a, dict) and _s(a.get("id")):
                return _s(a.get("id"))
    iso = _s(ctx.get("slotIso"))
    if iso:
        return _termin_id_suchen(tenant, ctx, iso)
    return ""


def note_appointment(tenant: dict, ctx: dict, sit: dict | None = None, *, note: str = "") -> dict[str, Any]:
    # Mehrzeilige Notizen (Telefonprotokoll) NICHT plattdruecken — nur
    # einzeilige Notizen bekommen den Herkunftsstempel (Lisa/Bianca).
    text = str(note or "").strip()
    if not text and sit:
        text = notes.zusammenfassung(sit)
    if not text:
        return {"ok": False, "spoken": "Es gab nichts Besonderes für die Terminnotiz."}
    if _s(ctx.get("patientId")) and not patients.patient_id_bindung_passt(ctx):
        return {
            "ok": False,
            "patientMismatch": True,
            "spoken": "Die Patientendaten passen nicht eindeutig zur Terminnotiz.",
            "regie": "Name und patientId widersprechen sich. Keine Notiz an einen möglicherweise fremden Termin schreiben.",
        }
    wer = notes.stimme_von(sit or {})
    zeile = text if "\n" in text else notes.notiz_anhaengen("", text, herkunft=wer)
    kurz = _s(text.splitlines()[0])
    if not WRITE_LIVE or _test_no_write(tenant):
        return {
            "ok": True,
            "noted": False,
            "dryRun": True,
            "note": zeile,
            "spoken": f"In die Terminnotiz hätte ich geschrieben: {kurz}",
        }
    aid = _notiz_ziel(tenant, ctx, sit)
    if not aid:
        return {
            "ok": False,
            "spoken": "Ich habe gerade keinen Termin, an den ich die Notiz hängen kann.",
            "regie": "Kein Termin in der Sitzung. Erst buchen oder list_appointments, dann note_appointment.",
        }
    body = {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "appointmentId": aid,
        "note": zeile,
    }
    status, data, dispatch = _cf_call("masAppointmentNote", body)
    if status == 200 and isinstance(data, dict) and data.get("status") == "success":
        return _mit_dispatch({
            "ok": True,
            "noted": True,
            "note": zeile,
            "appointmentId": aid,
            "spoken": "Die Notiz steht im Termin.",
        }, dispatch)
    msg = (data or {}).get("message") if isinstance(data, dict) else f"http_{status}"
    return _mit_dispatch({
        "ok": False,
        "spoken": "Die Notiz ist nicht im Termin gelandet.",
        "regie": f"masAppointmentNote fehlgeschlagen: {msg}",
    }, dispatch)
