"""Kalender-Tools: dieselben Cloud Functions wie Lisa, ohne MAS."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from kern.config import CF_BASE, WRITE_LIVE
from kern import notes, patients
from kern.slots import REGIE_ANGEBOT, parse_slot_wish, pick_slots, spoken_offer, spoken_slot
from kern.sprech import slot_wort
from kern.tenants import kalender_von, motiv_von

NO_CONTEXT = "Ich komme hier gerade nicht an den Kalender. Die Praxis meldet sich zeitnah mit Terminvorschlägen."
NO_CONTEXT_REGIE = "Kein Kalenderkontext in dieser Sitzung. Biete einen Rückruf an, nenne keine erfundenen Zeiten."


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


_CF_CLIENT = httpx.Client(timeout=10.0)

# Schreibende Cloud Functions (buchen/absagen/verschieben) duerfen laenger
# brauchen (SMS-Versand, Reminder). Vorfall 27.08.2026: masBookAppointment
# brauchte >10 s, der Client brach ab, die Buchung LANDETE trotzdem — und die
# Ansage behauptete "Termin ist weg". Timeout-Budget: CF-Limit ist 30 s.
_SCHREIB_TIMEOUT = 25.0

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


def find_slots(tenant: dict, ctx: dict, *, start_date: str = "", egal: bool = False,
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
                exclude_isos: list | set | None = None) -> dict[str, Any]:
    if not _s(ctx.get("patientId")) and not _s(ctx.get("patientName")):
        return {"ok": False, "spoken": NO_CONTEXT, "regie": NO_CONTEXT_REGIE}
    if not _s(ctx.get("visitMotiveId")) and not _s(ctx.get("visitMotiveName")):
        ctx["visitMotiveName"] = "Kontrolluntersuchung"
    wish = parse_slot_wish(wish_text) if wish_text else None
    vorrat = list(ctx.get("slotVorrat") or [])
    gesperrt = list(exclude_isos or []) or list(ctx.get("slotGesperrt") or [])
    nachladen = not vorrat
    if wish and wish.get("date") and vorrat:
        if not any(str(iso).startswith(wish["date"]) for iso in vorrat):
            nachladen = True
    if nachladen:
        start = (wish or {}).get("date") or ""
        found = find_slots(tenant, ctx, start_date=start)
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
            ctx["patientId"] = patient_id
            ctx["firstName"] = auf.get("firstName") or ctx.get("firstName")
            ctx["lastName"] = auf.get("lastName") or ctx.get("lastName")
    if not WRITE_LIVE:
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
    if status == 0:
        # Netzfehler/Timeout: die Buchung kann trotzdem gelandet sein —
        # NACHSCHAUEN statt raten (sonst bucht der Anrufer doppelt).
        landung = _buchung_pruefen(tenant, patient_id, iso)
        if landung:
            ctx["appointmentId"] = landung
            ctx["appointmentDate"] = iso[:10]
            return _mit_dispatch({
                "ok": True,
                "booked": True,
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
        # Termin-ID behalten: daran haengt spaeter die Gespraechsnotiz
        # (masAppointmentNote) und ein evtl. Verschieben im selben Anruf.
        aid = _s(data.get("appointmentId"))
        if aid:
            ctx["appointmentId"] = aid
        ctx["appointmentDate"] = iso[:10]
        return _mit_dispatch({
            "ok": True,
            "booked": True,
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


def _buchung_pruefen(tenant: dict, patient_id: str, iso: str) -> str:
    """Nach einem Netzfehler: Ist die Buchung doch gelandet? -> appointmentId."""
    try:
        status, data = _cf_post("masPatientLastDoctor", {
            "clientId": _s(tenant.get("clientId")),
            "locationId": _s(tenant.get("locationId")),
            "patientId": patient_id,
        })
        if status == 200 and isinstance(data, dict):
            nxt = data.get("nextAppointment") or {}
            if _s(nxt.get("startIso"))[:16] == _s(iso)[:16]:
                return _s(nxt.get("appointmentId"))
    except Exception as e:
        print(f"buchung_pruefen fail {e}", flush=True)
    return ""


def _bind_akte(ctx: dict, karte: dict) -> None:
    if not karte:
        return
    ctx["patientId"] = _s(karte.get("id")) or ctx.get("patientId") or ""
    ctx["firstName"] = _s(karte.get("firstName")) or ctx.get("firstName") or ""
    ctx["lastName"] = _s(karte.get("lastName")) or ctx.get("lastName") or ""
    ctx["patientName"] = _s(karte.get("name")) or f"{ctx.get('firstName', '')} {ctx.get('lastName', '')}".strip()
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
    if not WRITE_LIVE:
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


def list_appointments(tenant: dict, ctx: dict, upcoming: list | None = None, sit: dict | None = None) -> dict[str, Any]:
    if sit is not None:
        # Die Anreicherung beim Start hat die Termine schon geholt — nur bei
        # leerer Sitzung noch einmal fragen (spart einen ganzen Netz-Umlauf).
        if sit.get("upcoming"):
            upcoming = sit["upcoming"]
        else:
            hist = patients.termine_fuer(tenant, sit.get("patient") or {})
            sit["upcoming"] = hist["upcoming"]
            sit["past"] = hist["past"]
            upcoming = hist["upcoming"]
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
    if not WRITE_LIVE:
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
    if not WRITE_LIVE:
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
        alt = offer_slots(tenant, ctx, exclude_iso=iso)
        return _mit_dispatch({
            "ok": False,
            "spoken": "Dieser Platz ist nicht mehr frei. " + (alt.get("spoken") or ""),
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
    wer = notes.stimme_von(sit or {})
    zeile = text if "\n" in text else notes.notiz_anhaengen("", text, herkunft=wer)
    kurz = _s(text.splitlines()[0])
    if not WRITE_LIVE:
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
