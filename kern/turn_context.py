"""Deterministischer, JSON-tauglicher Sitzungsprojektor (TurnContextV1).

Der Kontext trennt Fakten nach Herkunft, bevor ein Sprachmodell planen darf:
Praxis/Anbieter aus der Pickadoc-Konfiguration, Patient nur nach bestätigter
Identität, MAS nur nach Inhaltsfilter und Aktionen nur aus dem Werkzeug-Ledger.

Stufe 1 ist beobachtend. Dieses Modul ruft kein Netz und ändert weder Flow noch
Prompt. Der spätere TurnPlan darf ausschließlich diesen Vertrag konsumieren.
"""

from __future__ import annotations

from typing import Any

from kern import fachprofil, gedaechtnis, tenants

VERSION = 1
SCHEMA = "pickadoc.turn-context/v1"


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _tenant(sit: dict[str, Any]) -> dict[str, Any]:
    t = sit.get("tenant")
    return t if isinstance(t, dict) else {}


def _sammler(sit: dict[str, Any]) -> dict[str, Any]:
    s = sit.get("sammler")
    return s if isinstance(s, dict) else {}


def _katalog(sit: dict[str, Any]) -> list[dict[str, Any]]:
    kat = sit.get("motivKatalog")
    if not isinstance(kat, list) or not kat:
        kat = _tenant(sit).get("visitMotives")
    return [x for x in (kat or []) if isinstance(x, dict)]


def _motive_fuer_kalender(katalog: list[dict[str, Any]], calendar_id: str) -> list[str]:
    out: list[str] = []
    for vm in katalog:
        mid = _s(vm.get("id"))
        ids = vm.get("calendarIds") if isinstance(vm.get("calendarIds"), list) else []
        if mid and (not ids or calendar_id in {_s(x) for x in ids}):
            out.append(mid)
    return out


def anbieterregister(sit: dict[str, Any]) -> list[dict[str, Any]]:
    """Alle echten Anbieter und Funktionskalender, explizit typisiert."""
    t = _tenant(sit)
    katalog = _katalog(sit)
    default = tenants.default_kalender(t) or {}
    default_id = _s(default.get("id"))
    out: list[dict[str, Any]] = []
    for cal in t.get("calendars") or []:
        if not isinstance(cal, dict):
            continue
        cid, name = _s(cal.get("id")), _s(cal.get("name"))
        if not cid or not name:
            continue
        funktion = tenants.ist_funktionskalender(cal)
        ort = tenants.kalender_beim(name) if funktion else ""
        sprechform = f"bei {ort}" if ort else name
        out.append({
            "id": cid,
            "name": name,
            "typ": "funktion" if funktion else "person",
            "istBehandler": not funktion,
            "istStandard": cid == default_id,
            "sprechform": sprechform or name,
            "motivIds": _motive_fuer_kalender(katalog, cid),
        })
    return out


def katalogregeln(sit: dict[str, Any]) -> dict[str, Any]:
    """Buchungsrelevante Motive und Routingregeln ohne Freitext-Prompt."""
    t = _tenant(sit)
    katalog = _katalog(sit)
    funktion_ids = [
        _s(c.get("id")) for c in tenants.funktionskalender_alle(t) if _s(c.get("id"))
    ]
    personen_ids = [
        _s(c.get("id")) for c in tenants.behandler_kalender(t) if _s(c.get("id"))
    ]
    motive: list[dict[str, Any]] = []
    pzr_ids: list[str] = []
    akut_ids: list[str] = []
    besprechung_ids: list[str] = []
    for vm in katalog:
        mid = _s(vm.get("id"))
        if not mid:
            continue
        pzr = tenants.ist_pzr_motiv(vm)
        akut = tenants.ist_akut_motiv(vm)
        besprechung = tenants.ist_besprechung_motiv(vm)
        if pzr:
            pzr_ids.append(mid)
        if akut:
            akut_ids.append(mid)
        if besprechung:
            besprechung_ids.append(mid)
        motive.append({
            "id": mid,
            "name": _s(vm.get("name") or vm.get("nameForPatient")),
            "dauerMin": _int(vm.get("duration")),
            "calendarIds": [_s(x) for x in (vm.get("calendarIds") or []) if _s(x)],
            "klassen": [
                k for k, aktiv in (
                    ("pzr", pzr), ("akut", akut), ("besprechung", besprechung)
                ) if aktiv
            ],
        })
    return {
        "motive": motive,
        "personenKalenderIds": personen_ids,
        "funktionsKalenderIds": funktion_ids,
        "pzrMotiveIds": pzr_ids,
        "akutMotiveIds": akut_ids,
        "besprechungMotiveIds": besprechung_ids,
        "hatFunktionsrouting": bool(funktion_ids and personen_ids),
        "personenMotivRegel": (
            "besprechung_oder_akut" if funktion_ids and personen_ids else "katalog"
        ),
        "pzrZielKalenderIds": funktion_ids if pzr_ids else [],
    }


def _patient(sit: dict[str, Any]) -> dict[str, Any]:
    """Patientenfakten erst nach bestätigter Identität freigeben."""
    s = _sammler(sit)
    layer = fachprofil.patient_layer(sit)
    status = _s(layer.get("identitaet")) or "anonym"
    out: dict[str, Any] = {
        "identitaet": status,
        "hatKartei": bool(layer.get("hatKartei")),
        "quelle": "keine",
    }
    if status != "bestaetigt":
        return out
    pat = sit.get("patient") if isinstance(sit.get("patient"), dict) else {}
    anrufer = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
    name = (
        f"{_s(s.get('vorname'))} {_s(s.get('nachname'))}".strip()
        or _s(pat.get("name"))
        or f"{_s(anrufer.get('vorname'))} {_s(anrufer.get('nachname'))}".strip()
    )
    patient_id = _s(s.get("patientId") or pat.get("id") or anrufer.get("patientId"))
    out.update({
        "name": name,
        "vorname": _s(s.get("vorname") or pat.get("firstName") or anrufer.get("vorname")),
        "nachname": _s(s.get("nachname") or pat.get("lastName") or anrufer.get("nachname")),
        "patientId": patient_id,
        "telefon": _s(
            s.get("telefon") or s.get("aktePhone")
            or pat.get("phone") or anrufer.get("telefon")
        ),
        "geschlecht": _s(s.get("geschlecht") or pat.get("gender") or anrufer.get("geschlecht")),
        "geburtsdatum": _s(pat.get("birthDate") or anrufer.get("geburtsdatum")),
        "versicherung": _s(s.get("versicherung") or s.get("versicherungAkte")),
        "quelle": (
            "sammler_bestaetigt" if _s(s.get("nachname"))
            else "patientenkartei" if pat
            else "anrufer_cf"
        ),
        "letzterBesuch": _s(s.get("letzterBesuch")),
        "letzterGrund": _s(s.get("letzterGrund")),
        "letzterArzt": _s(
            (s.get("arzt") or {}).get("calendarName")
            if isinstance(s.get("arzt"), dict)
            else ""
        ) or _s(
            (sit.get("anruferKartei") or {}).get("doctorName")
            if isinstance(sit.get("anruferKartei"), dict)
            else ""
        ),
        "kommendeTermine": _termine(sit.get("upcoming")),
        "vergangeneTermine": _termine(sit.get("past"), limit=3),
    })
    return out


def _termine(raw: Any, *, limit: int = 5) -> list[dict[str, str]]:
    """Nur planungsrelevante Kalenderfakten, keine eingebetteten Patientendaten."""
    out: list[dict[str, str]] = []
    for termin in raw or []:
        if not isinstance(termin, dict):
            continue
        row = {
            "id": _s(termin.get("id") or termin.get("appointmentId")),
            "iso": _s(termin.get("iso") or termin.get("slotIso") or termin.get("date")),
            "calendarId": _s(termin.get("calendarId")),
            "behandler": _s(termin.get("doctorName") or termin.get("calendarName")),
            "motivId": _s(termin.get("motivId") or termin.get("visitMotiveId")),
            "motiv": _s(termin.get("motivName") or termin.get("visitMotiveName")),
            "quelle": "kalender",
        }
        if any(v for k, v in row.items() if k != "quelle"):
            out.append(row)
        if len(out) >= limit:
            break
    return out


def _sichere_mas_fakten(sit: dict[str, Any], patient: dict[str, Any]) -> list[str]:
    if patient.get("identitaet") != "bestaetigt":
        return []
    out: list[str] = []
    for roh in str(sit.get("gedaechtnis") or "").splitlines():
        zeile = _s(roh).lstrip("-").strip()
        if (
            zeile.casefold().startswith("praxisgedächtnis zu")
            or zeile.casefold().startswith("nutze das aktiv")
        ):
            continue
        if gedaechtnis.zeile_inhaltlich(zeile) and zeile not in out:
            out.append(zeile[:400])
        if len(out) >= 3:
            break
    return out


def _tool_ledger(sit: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in (sit.get("tools") or [])[-12:]:
        if not isinstance(tool, dict):
            continue
        name = _s(tool.get("name"))
        if not name:
            continue
        ok = bool(tool.get("ok"))
        action = {
            "name": name,
            "ok": ok,
            "ergebnis": (
                "dry_run" if tool.get("dryRun")
                else "erfolgreich" if ok
                else "fehlgeschlagen"
            ),
            "belegt": bool(
                ok and (
                    tool.get("booked")
                    or tool.get("appointmentId")
                    or tool.get("createdPatient")
                    or name in {
                        "offer_slots", "list_appointments", "note_appointment",
                        "cancel_appointment", "move_appointment",
                    }
                )
            ),
            "quelle": f"tool:{_s(tool.get('cf')) or name}",
        }
        if _s(tool.get("slotIso")):
            action["slotIso"] = _s(tool.get("slotIso"))
        if _s(tool.get("appointmentId")):
            action["appointmentId"] = _s(tool.get("appointmentId"))
        out.append(action)
    return out


def _letzter_nutzertext(sit: dict[str, Any], text_in: str = "") -> str:
    if _s(text_in):
        return _s(text_in)
    for zug in reversed(sit.get("zuege") or []):
        if isinstance(zug, dict) and _s(zug.get("textIn")):
            return _s(zug.get("textIn"))
    for msg in reversed(sit.get("messages") or []):
        if isinstance(msg, dict) and msg.get("role") == "user" and _s(msg.get("content")):
            return _s(msg.get("content"))
    return ""


def projekt(sit: dict[str, Any], *, text_in: str = "") -> dict[str, Any]:
    """Aktuellen Sitzungsstand ohne Seiteneffekte projizieren."""
    t = _tenant(sit)
    s = _sammler(sit)
    patient = _patient(sit)
    ledger = _tool_ledger(sit)
    arzt = s.get("arzt") if isinstance(s.get("arzt"), dict) else {}
    fach = fachprofil.template(sit)
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "sitzung": {
            "id": _s(sit.get("id")),
            "stimme": _s(sit.get("stimme")) or "Bianca",
            "sprache": _s(t.get("sprache")) or "de",
            "letzterNutzertext": _letzter_nutzertext(sit, text_in),
        },
        "fachtemplate": {"id": fach["id"], "schutz": list(fach.get("schutz") or [])},
        "praxis": {
            "quelle": _s(t.get("_quelle")) or "datei",
            "clientId": _s(t.get("clientId")),
            "locationId": _s(t.get("locationId")),
            "name": _s(t.get("praxisName")),
            "defaultCalendarId": _s((tenants.default_kalender(t) or {}).get("id")),
            "anbieter": anbieterregister(sit),
            "katalogregeln": katalogregeln(sit),
        },
        "patient": patient,
        "anliegen": {
            "modus": _s(s.get("modus")),
            "phase": _s(s.get("phase")),
            "offeneFrage": _s(s.get("frage")),
            "grund": _s(s.get("grund")),
            "motivId": _s(s.get("motivId")),
            "motivName": _s(s.get("motivName")),
            "calendarId": _s(arzt.get("calendarId")),
            "calendarName": _s(arzt.get("calendarName")),
            "wunsch": _s(s.get("wunsch")),
            "quelle": "sammler",
        },
        "angebot": [
            {"iso": _s(x.get("iso")), "gesprochen": _s(x.get("spoken"))}
            for x in (sit.get("offered") or [])
            if isinstance(x, dict) and _s(x.get("iso"))
        ],
        "mas": {
            "verfuegbar": bool(sit.get("gedaechtnis")),
            "offeneVorgaenge": len(sit.get("gedaechtnisOffen") or []),
            "sichereFakten": _sichere_mas_fakten(sit, patient),
            "quelle": "mas",
        },
        "werkzeuge": {
            "ledger": ledger,
            "darfBuchungBestaetigen": any(
                x["name"] == "book_slot" and x["belegt"] for x in ledger
            ),
            "darfStornoBestaetigen": any(
                x["name"] == "cancel_appointment" and x["belegt"] for x in ledger
            ),
            "darfVerschiebungBestaetigen": any(
                x["name"] == "move_appointment" and x["belegt"] for x in ledger
            ),
        },
    }


def aktualisieren(sit: dict[str, Any], *, text_in: str = "") -> dict[str, Any]:
    """Snapshot für Beobachtung/Persistenz in der Sitzung ablegen."""
    ctx = projekt(sit, text_in=text_in)
    sit["turnContext"] = ctx
    return ctx
