"""Kalender-Tools: dieselben Cloud Functions wie Lisa, ohne MAS."""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from kern.config import CF_BASE, WRITE_LIVE
from kern import notes, patients
from kern.slots import (
    FENSTER_TAGE, REGIE_ANGEBOT, parse_slot_wish, pick_slots, spoken_offer, spoken_slot,
)
from kern.sprech import slot_wort
from kern.tenants import ist_akut_motiv, kalender_von, motiv_von

TZ = ZoneInfo("Europe/Berlin")

# W-SUCHFENSTER (14.09.2026): Plattform-Vertrag getFreeTimeSlots — je Aufruf
# hoechstens 20 Zeiten aus 30 Tagen ab startDate (Quelle: appointments.ts,
# maxSlots=20 / firstDaysToSearch=30; ohne Treffer sucht sie selbst 90 Tage
# weiter). Bei offenem Wunsch blaettert `find_slots` bis zu SEITEN_MAX
# weitere Seiten vorwaerts, gedeckelt auf FENSTER_TAGE (6 Monate).
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
# HTTP-200 ist noch kein Beweis, dass exakt der angeforderte Termin in der
# Kartei steht. Kurze Nachlese-Retries fangen Replikationslatenz ab; der
# Anrufer hört währenddessen bereits den Werkzeug-Füller.
_BOOK_VERIFY_DELAYS = (0.0, 0.2, 0.45)
# W-BUCHUNG-BEWEIS (15.09.2026): erreicht die namensbasierte Ruecklese die
# richtige Akte nicht, beweist ein zweiter Weg ueber die patientId. 0 =
# byte-identisches Verhalten von vor dem 15.09.2026 (nur Namensliste).
BOOK_VERIFY_AKTE = (os.getenv("BOOK_VERIFY_AKTE", "1") or "1").strip() != "0"
# W-AKTE-HANDY (15.09.2026): sagt die Plattform needs_phone, obwohl Bianca eine
# rueckbestaetigte Handynummer in der Hand hat, wird sie in die Akte geschrieben
# und EINMAL neu gebucht. 0 = Verhalten von vor dem 15.09.2026 (nur nachfragen).
BOOK_FIX_PHONE = (os.getenv("BOOK_FIX_PHONE", "1") or "1").strip() != "0"

# W-TOOL-UI (02.09.2026): freie Slots in der Gespraechsansicht nicht
# endlos speichern — erste N reichen zur Diagnose, Rest als total.
_SLOT_CAP = 40


def _cf_post(route: str, body: dict, *, timeout: float | None = None) -> tuple[int, Any]:
    url = f"{CF_BASE}/{route.lstrip('/')}"
    try:
        r = _CF_CLIENT.post(url, json=body, timeout=timeout or 10.0)
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
    gekappt = _response_kappen(data)
    dispatch = {
        "route": route,
        "url": url,
        "method": "POST",
        "request": body,
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
    alt = dict(such)
    alt["visitMotiveId"] = alt_id
    alt["visitMotiveName"] = _s((vm or {}).get("name")) or "Kontrolluntersuchung"
    return alt


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
    if motiv_fallback:
        alt = _kontrolle_ersatz(tenant, dict(ctx or {}))
        if alt:
            runden.append((alt, True))
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
    return letzter


def _wunsch_gedeckt(slots: list, wish: dict | None) -> bool:
    """Deckt der Vorrat den Wunsch (Tag/Zeitraum/Wochentag/Uhrzeit) ab?"""
    if not wish:
        return True
    isos = _iso_liste(slots or [])
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
        return ""
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
    ``FENSTER_TAGE`` (6 Monate) ab heute. Ohne ``wish`` genau EIN Aufruf wie
    bisher. ``dispatch`` traegt die erste Seite plus ``seiten`` (Startdatum
    und Trefferzahl je Seite) fuer die Gespraechsansicht.
    """
    heute = datetime.now(TZ).date().isoformat()
    erste = _find_slots_seite(tenant, ctx, start_date=start_date, egal=egal, source=source)
    if not erste.get("ok") or not wish:
        return erste
    slots = list(erste.get("slots") or [])
    seite_slots = _iso_liste(slots)  # Zeiten der zuletzt geladenen Seite
    seiten = [{"startDate": start_date or heute, "n": len(slots)}]
    horizont = _tag_plus(heute, FENSTER_TAGE)
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
    if start_date:
        body["startDate"] = start_date
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
    patient_id = _s(ctx.get("patientId"))
    created_patient = False
    if not patient_id:
        auf = patients.patient_aufloesen(tenant, {
            "name": ctx.get("patientName"),
            "firstName": ctx.get("firstName"),
            "lastName": ctx.get("lastName"),
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
            patients.patient_id_bindung_setzen(
                ctx, patient_id, ctx.get("firstName"), ctx.get("lastName"))
        elif phone and first and last and not patients.ist_testname(first, last):
            gebucht = _buch_und_akte(tenant, ctx, iso, first, last, phone)
            if gebucht.get("ok"):
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
    status, data, dispatch = _cf_call("masBookAppointment", body, timeout=_SCHREIB_TIMEOUT)
    if (BOOK_FIX_PHONE and status == 200 and isinstance(data, dict)
            and data.get("status") == "needs_phone"):
        heilung = _handy_nachtragen(tenant, ctx, patient_id=patient_id)
        if heilung.get("ok"):
            erster = dispatch
            status, data, dispatch = _cf_call(
                "masBookAppointment", body, timeout=_SCHREIB_TIMEOUT)
            if isinstance(dispatch, dict):
                dispatch["phoneFix"] = {
                    k: v for k, v in heilung.items() if k != "dispatch"
                }
                if isinstance(heilung.get("dispatch"), dict):
                    dispatch["phoneFixDispatch"] = heilung["dispatch"]
                if isinstance(erster, dict):
                    dispatch["needsPhoneVorher"] = erster.get("response")
    if status == 0:
        # Netzfehler/Timeout: die Buchung kann trotzdem gelandet sein —
        # NACHSCHAUEN statt raten (sonst bucht der Anrufer doppelt).
        pruefung = _buchung_verifizieren(
            tenant,
            ctx,
            patient_id=patient_id,
            appointment_id="",
            iso=iso,
            calendar_id=body["calendarId"],
        )
        if isinstance(dispatch, dict):
            dispatch["verification"] = {
                k: v for k, v in pruefung.items() if k != "dispatch"
            }
            if isinstance(pruefung.get("dispatch"), dict):
                dispatch["verificationDispatch"] = pruefung["dispatch"]
        landung = _s(pruefung.get("appointmentId"))
        if pruefung.get("ok") and landung:
            ctx["appointmentId"] = landung
            ctx["appointmentDate"] = iso[:10]
            return _mit_dispatch({
                "ok": True,
                "booked": True,
                "verified": True,
                "slotIso": iso,
                "appointmentId": landung,
                "patientId": patient_id,
                "createdPatient": created_patient,
                "spoken": f"Der Termin {spoken_slot(iso)} ist fest eingetragen.",
            }, dispatch)
        return _mit_dispatch({
            "ok": False,
            "spoken": (
                "Der Kalender antwortet gerade nicht — ich möchte nichts doppelt "
                "eintragen. Die Praxis bestätigt Ihnen den Termin kurzfristig."
            ),
            "regie": "Netzfehler beim Buchen. Keinen anderen Slot anbieten, Rückruf zusagen.",
        }, dispatch)
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
        )
        if isinstance(dispatch, dict):
            dispatch["verification"] = {
                k: v for k, v in pruefung.items() if k != "dispatch"
            }
            if isinstance(pruefung.get("dispatch"), dict):
                dispatch["verificationDispatch"] = pruefung["dispatch"]
        if not pruefung.get("ok"):
            ctx.pop("appointmentId", None)
            return _mit_dispatch({
                "ok": False,
                "booked": False,
                "verificationFailed": True,
                "possiblyBooked": True,
                "slotIso": iso,
                "patientId": patient_id,
                "appointmentId": "",
                "spoken": (
                    "Die Buchungsantwort ist nicht eindeutig im Kalender angekommen. "
                    "Ich bestätige den Termin deshalb noch nicht; die Praxis prüft das "
                    "und meldet sich bei Ihnen."
                ),
                "regie": "Read-after-write fehlgeschlagen. Keine Buchung und keine SMS behaupten.",
            }, dispatch)
        aid = _s(pruefung.get("appointmentId"))
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
            "spoken": "In Ihrer Akte fehlt noch eine Handynummer. Wie lautet sie?",
            "regie": "Nummer erfragen, dann erneut buchen.",
        }, dispatch)
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
        # Der Kalender sagt WIRKLICH "belegt": Alternativen anbieten.
        # slotGesperrt aus dem Kontext (Sitzung) + die gerade gescheiterte ISO.
        alt = offer_slots(
            tenant, ctx, exclude_iso=iso,
            exclude_isos=ctx.get("slotGesperrt") or [],
        )
        return _mit_dispatch({
            "ok": False,
            "slotTaken": True,
            "spoken": "Der Termin ist gerade weg. " + (alt.get("spoken") or ""),
            "regie": REGIE_ANGEBOT,
            "slots": alt.get("slots") or [],
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
    status, data, dispatch = _cf_call("masPatientLastDoctor", {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "patientId": _s(patient_id),
    })
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
        if delay:
            time.sleep(delay)
        found = find_patient_appointments(tenant, verify_ctx)
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
    if BOOK_VERIFY_AKTE and not namenspfad_traf_akte:
        # Die Namenssuche hat die Akte nie erreicht (fremder Treffer,
        # notFound, mehrdeutig, CF-Fehler) — also liegt KEIN Gegenbeweis
        # vor, nur fehlende Evidenz. Zweiter Weg ueber die patientId.
        akte = _buchung_beweis_ueber_akte(
            tenant,
            patient_id=patient_id,
            iso=expected_iso,
            calendar_id=expected_cal,
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
    if karte.get("phone"):
        ctx["phone"] = karte["phone"]
    if karte.get("birthDate"):
        ctx["birthDate"] = karte["birthDate"]


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


def _buch_und_akte(tenant: dict, ctx: dict, iso: str, first: str, last: str, phone: str) -> dict[str, Any]:
    """Fallback: createAppointment legt Akte an und bucht in einem Zug."""
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
    status, data, dispatch = _cf_call("createAppointment", body)
    if status == 200 and isinstance(data, dict) and data.get("status") == "success":
        auf = patients.patient_aufloesen(tenant, {
            "name": f"{first} {last}".strip(),
            "firstName": first,
            "lastName": last,
        })
        if auf.get("id"):
            _bind_akte(ctx, auf)
            # createAppointment kennt kein Versicherungs-Feld — den erfragten
            # Status auf der frisch angelegten Akte nachtragen (29.08.2026).
            if isinstance(ctx.get("privateInsurance"), bool):
                patients.versicherung_aktualisieren(tenant, _s(auf.get("id")), ctx["privateInsurance"])
        # createAppointment liefert keine Termin-ID — fuer die Gespraechsnotiz
        # read-only nachschlagen (kein zweiter Buchungsversuch!).
        aid = _termin_id_suchen(tenant, ctx, iso)
        if aid:
            ctx["appointmentId"] = aid
        ctx["appointmentDate"] = iso[:10]
        return _mit_dispatch({
            "ok": True,
            "booked": True,
            "createdPatient": True,
            "slotIso": iso,
            "appointmentId": aid,
            "spoken": f"Akte und Termin {spoken_slot(iso)} sind fest eingetragen.",
        }, dispatch)
    return _mit_dispatch({"ok": False}, dispatch)


def _patient_appointments_fallback(
    tenant: dict,
    *,
    first: str,
    last: str,
    vorname_verworfen: bool,
    primary_dispatch: dict | None,
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

    def gleich(a: Any, b: Any) -> bool:
        return _s(a).casefold() == _s(b).casefold()

    kandidaten = [
        p for p in (data.get("patients") or [])
        if isinstance(p, dict)
        and _s(p.get("id"))
        and gleich(p.get("lastName"), last)
        and (not query_first or gleich(p.get("firstName"), query_first))
    ]
    if len(kandidaten) > 1:
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
    if isinstance(nxt, dict) and _s(nxt.get("appointmentId")):
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
    print(
        f"find_patient_appointments fallback patientId={patient['id']} "
        f"appointments={len(termine)}",
        flush=True,
    )
    return _mit_dispatch({
        "ok": True,
        "patient": patient,
        "appointments": termine,
        "vornameVerworfen": vorname_verworfen,
        "fallbackUsed": True,
    }, termin_dispatch)


def find_patient_appointments(tenant: dict, ctx: dict) -> dict[str, Any]:
    """Kommende Termine zum NAMEN — ueber die warme Demo-Function
    agentFindPatientAppointments (Patient + Termine in EINEM Aufruf,
    inkl. Behandlername, Kalender-ID und Behandlungsgrund)."""
    first, last = _name_teile(ctx)
    if not last:
        return {"ok": False, "appointments": [], "spoken": "Wie ist Ihr Nachname?"}
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
    status, data, dispatch = _cf_call("agentFindPatientAppointments", body)
    if not isinstance(data, dict):
        data = {}
    vorname_verworfen = False
    if status == 404 and _s(data.get("status")) != "no_upcoming" and body.get("firstName"):
        # W-NAMESKORREKTUR (31.08.2026): der Vorname kann selbst verhoert
        # sein ("Sannes" statt Georgios) und die Suche allein deshalb leer
        # ausgehen — einmal NUR mit dem Nachnamen nachfassen. Meldet die CF
        # dann ambiguous, fragt die Prozedur den Vornamen ohnehin sauber nach.
        body = {k: v for k, v in body.items() if k != "firstName"}
        status, data, dispatch = _cf_call("agentFindPatientAppointments", body)
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
        termine = []
        for a in data.get("appointments") or []:
            if not isinstance(a, dict):
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
        return _mit_dispatch({"ok": True, "patient": patient, "appointments": termine,
                "vornameVerworfen": vorname_verworfen}, dispatch)
    if status == 404 and data.get("status") == "no_upcoming":
        return _mit_dispatch({"ok": True, "patient": patient, "appointments": [],
                "vornameVerworfen": vorname_verworfen}, dispatch)
    if status == 404:
        fallback = _patient_appointments_fallback(
            tenant,
            first=first,
            last=last,
            vorname_verworfen=vorname_verworfen,
            primary_dispatch=dispatch,
        )
        if fallback is not None:
            return fallback
        return _mit_dispatch({"ok": True, "notFound": True, "patient": {}, "appointments": []}, dispatch)
    if status == 409 or _s(data.get("status")).lower() in {"conflict", "ambiguous"}:
        # Mehrere Patienten mit gleichem Nachnamen (W-NACHNAME 31.08.2026,
        # phone_agent-Vorbild): der Anrufer muss den Vornamen nachliefern,
        # dann wird mit firstName erneut gesucht. vornameVerworfen sagt dem
        # Aufrufer: der GESPEICHERTE Vorname passte nicht — leeren und fragen.
        return _mit_dispatch({"ok": True, "mehrdeutig": True, "patient": {}, "appointments": [],
                "vornameVerworfen": vorname_verworfen}, dispatch)
    msg = _s(data.get("message")) or f"http_{status}"
    return _mit_dispatch({"ok": False, "appointments": [], "error": msg}, dispatch)


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
    status, data, dispatch = _cf_call("agentCancelAppointmentById", {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "appointmentId": aid,
        "source": "telefonki-lisa",
    }, timeout=_SCHREIB_TIMEOUT)
    if status == 200 and isinstance(data, dict) and data.get("status") == "success":
        ctx["appointmentId"] = aid
        return _mit_dispatch({
            "ok": True, "cancelled": True, "appointmentId": aid,
            "spoken": "Der Termin ist abgesagt.",
        }, dispatch)
    msg = (data or {}).get("message") if isinstance(data, dict) else f"http_{status}"
    return _mit_dispatch({
        "ok": False,
        "spoken": "Die Absage hat gerade nicht geklappt. Die Praxis kümmert sich darum.",
        "regie": f"Absage fehlgeschlagen: {msg}",
    }, dispatch)


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
                body["startSearchDate"] = parsed["date"]
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
    body = {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "appointmentId": aid,
        "newStartDate": iso.replace("T", " ")[:16],
        "source": "telefonki-lisa",
    }
    status, data, dispatch = _cf_update("postpone", body)
    if status == 200 and isinstance(data, dict) and data.get("success"):
        return _mit_dispatch({
            "ok": True,
            "moved": True,
            "appointmentId": aid,
            "slotIso": iso,
            "spoken": f"Der Termin liegt jetzt {spoken_slot(iso)}.",
        }, dispatch)
    if status == 400:
        # Beim Verschieben muessen Alternativen im GLEICHEN Kalender und mit
        # dem GLEICHEN Besuchsgrund ab dem gewuenschten Tag gesucht werden.
        # Ohne start_date sprang der Rueckfall live (Thaler 09.09.2026) von
        # Oktober zurueck auf September; ohne Motiv im ctx wurden ausserdem
        # unpassende Kontroll-Slots angeboten.
        alt = offer_slots(
            tenant, ctx,
            exclude_iso=iso,
            start_date=iso[:10],
        )
        return _mit_dispatch({
            "ok": False,
            "slotTaken": True,
            "slotIso": iso,
            "spoken": "Dieser Platz ist nicht mehr frei. " + (alt.get("spoken") or ""),
            "slots": alt.get("slots") or [],
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
