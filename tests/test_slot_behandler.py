"""W-SLOT-BEHANDLER (08.09.2026, Lülf): nur dieser Arzt, Motiv-Fallback.

Roman Lülf: PAR-AIT-geschlossen lieferte [] bei Patrikis, Kontrolle war frei.
Wunsch „Donnerstag der 10. oder Montag der 21.“ plus „heute um 14 Uhr …
verschieben“ darf nicht als Montag 14 Uhr gelesen werden.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bianca import gehirn, hintergrund, verwalten
from kern import calendar as kal
from kern.slots import parse_slot_wish, pick_slots, tage_aus_text, _tag_im_monat
from kern.tenants import laden

TZ = ZoneInfo("Europe/Berlin")
PATRIKIS = "RHYdoQFD7oAhqIepLzC2"
PETSAS = "zex5bmv5jfIHWVW6zHbg"


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


def _iso(tage: int, h: int, m: int = 0) -> str:
    d = datetime.now(TZ).replace(
        hour=h, minute=m, second=0, microsecond=0) + timedelta(days=tage)
    return d.isoformat(timespec="seconds")


# --- Wunsch-Parser (Lülf-Satz) ---------------------------------------------

_LUELF = (
    "Ich habe heute um 14 Uhr einen Termin bei Doktor Patrikis "
    "und den würde ich gerne verschieben, entweder auf den "
    "Donnerstag der 10. oder Montag der 21."
)


def test_luelf_satz_zwei_tage_keine_bestand_uhr():
    w = parse_slot_wish(_LUELF)
    assert w
    d10 = _tag_im_monat(10).isoformat()
    d21 = _tag_im_monat(21).isoformat()
    assert w.get("tage") == [d10, d21]
    assert w.get("date") == d10
    assert w.get("weekday") is None
    assert w.get("hour") is None


def test_der_zehnte_oder_einundzwanzigste_ohne_wochentag():
    w = parse_slot_wish("Geht der 10. oder der 21.?")
    assert w and w.get("tage") == [
        _tag_im_monat(10).isoformat(),
        _tag_im_monat(21).isoformat(),
    ]


def test_am_dritten_oktober_ist_kein_tagesordinal():
    w = parse_slot_wish("Geht am 3. Oktober?")
    assert w
    assert not w.get("tage")
    assert (w.get("date") or "").endswith("-10-03")


def test_nur_wochentag_bleibt_wochentag():
    w = parse_slot_wish("Lieber am Freitag nachmittags.")
    assert w
    assert w.get("weekday") == 5
    assert not w.get("tage")
    assert w.get("hourMin") == 12


def test_tage_aus_text_oder_ohne_artikel():
    tage = tage_aus_text("der 10. oder 21.")
    assert tage == [_tag_im_monat(10).isoformat(), _tag_im_monat(21).isoformat()]


def test_start_datum_nimmt_fruehesten_wunschtag():
    s = gehirn.sammler(_sit())
    d10 = _tag_im_monat(10).isoformat()
    d21 = _tag_im_monat(21).isoformat()
    s["wunsch"] = {"date": d10, "tage": [d10, d21], "weekday": None}
    assert gehirn.start_datum(s) == d10


def test_pick_slots_filtert_auf_wunschtage():
    d10 = _tag_im_monat(10)
    d11 = d10 + timedelta(days=1)
    d21 = _tag_im_monat(21)
    slots = [
        f"{d10.isoformat()}T09:00:00+02:00",
        f"{d11.isoformat()}T09:00:00+02:00",
        f"{d21.isoformat()}T11:00:00+02:00",
    ]
    picked = pick_slots(slots, wish={"tage": [d10.isoformat(), d21.isoformat()]})
    daten = {x["date"] for x in picked["slots"]}
    assert daten <= {d10.isoformat(), d21.isoformat()}
    assert d11.isoformat() not in daten


# --- Kalender: nur dieser Arzt, Kontrolle-Fallback -------------------------

def test_find_slots_behandler_kontrolle_wenn_spezial_leer():
    aufrufe: list[dict] = []
    echt = kal.find_slots
    echt_motiv = kal.motiv_von

    def fake_find(tenant, ctx, **kw):
        aufrufe.append({
            "cal": ctx.get("calendarId"),
            "motiv": ctx.get("visitMotiveId"),
            "egal": kw.get("egal"),
        })
        if ctx.get("visitMotiveId") == "par-ait":
            return {"ok": True, "slots": []}
        return {"ok": True, "slots": ["2026-09-10T09:00:00+02:00"]}

    kal.find_slots = fake_find
    kal.motiv_von = lambda tenant, name: {
        "id": "kontrolle", "name": "Kontrolluntersuchung"}
    try:
        found = kal.find_slots_behandler(
            {"clientId": "c", "locationId": "l"},
            {"calendarId": PATRIKIS, "calendarName": "Dr. Patrikis",
             "visitMotiveId": "par-ait", "visitMotiveName": "PAR AIT"},
            start_date="2026-09-08",
        )
        assert found.get("motivFallback") == "kontrolle"
        assert found.get("slots")
        assert all(a["cal"] == PATRIKIS for a in aufrufe)
        assert all(a["egal"] is False for a in aufrufe)
        assert [a["motiv"] for a in aufrufe] == ["par-ait", "kontrolle"]
    finally:
        kal.find_slots = echt
        kal.motiv_von = echt_motiv


def test_find_slots_behandler_kein_fallback_wenn_kalender_tot():
    n = {"n": 0}
    echt = kal.find_slots

    def fake_find(tenant, ctx, **kw):
        n["n"] += 1
        return {"ok": False, "error": "down"}

    kal.find_slots = fake_find
    try:
        found = kal.find_slots_behandler(
            {"clientId": "c"},
            {"calendarId": PATRIKIS, "visitMotiveId": "par-ait"},
        )
        assert found.get("ok") is False
        assert n["n"] == 1
    finally:
        kal.find_slots = echt


def test_arzt_uebernehmen_fest_bindet_bestand_nicht_fremden_wunsch():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["arzt"] = {"typ": "default", "calendarId": PETSAS, "calendarName": "Dr. Petsas"}
    verwalten._arzt_uebernehmen(sit, {
        "calendarId": PATRIKIS, "doctorName": "Dr. Patrikis",
    }, fest=True)
    assert s["arzt"]["calendarId"] == PATRIKIS
    assert s["arzt"]["typ"] == "letzter"


def test_arzt_uebernehmen_laesst_ausdruecklich_anderen_arzt():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["arzt"] = {"typ": "genannt", "calendarId": PETSAS, "calendarName": "Dr. Petsas"}
    verwalten._arzt_uebernehmen(sit, {
        "calendarId": PATRIKIS, "doctorName": "Dr. Patrikis",
    }, fest=True)
    assert s["arzt"]["calendarId"] == PETSAS


def test_verschieb_angebot_sucht_nur_bestandskalender():
    sit = _sit()
    s = gehirn.sammler(sit)
    d10 = _tag_im_monat(10)
    s.update({
        "modus": "verschieben",
        "wunsch": {"tage": [d10.isoformat()], "date": d10.isoformat()},
        "arzt": {"typ": "default", "calendarId": PETSAS, "calendarName": "Dr. Petsas"},
    })
    sit["gefunden"] = [{
        "id": "t1",
        "iso": datetime.now(TZ).replace(
            hour=14, minute=0, second=0, microsecond=0).isoformat(timespec="seconds"),
        "calendarId": PATRIKIS, "doctorName": "Dr. Patrikis",
        "motivId": "par-ait", "motivName": "PAR AIT",
    }]
    sit["verwaltenTermin"] = "t1"
    gesehen: list[str] = []
    echt = verwalten.kal.find_slots_behandler

    def fake_behandler(tenant, ctx, **kw):
        gesehen.append(ctx.get("calendarId"))
        return {"ok": True, "slots": [
            f"{d10.isoformat()}T09:00:00+02:00",
            f"{d10.isoformat()}T10:30:00+02:00",
        ]}

    verwalten.kal.find_slots_behandler = fake_behandler
    try:
        aus = verwalten._verschieb_angebot(sit, None)
        assert gesehen == [PATRIKIS]
        assert sit.get("offered"), aus
        assert s["arzt"]["calendarId"] == PATRIKIS
    finally:
        verwalten.kal.find_slots_behandler = echt


def test_verschieb_zieltag_ohne_monat_erbt_monat_des_bestandstermins():
    """Live Donaubauer 09.09.: 21. Oktober + „Freitag, den 23.“ muss
    23. Oktober ergeben, nicht den naechsten 23. ab heute (September)."""
    sit = _sit()
    s = gehirn.sammler(sit)
    wortlaut = (
        "Richtig. Meinen Termin am 21. Oktober möchte ich um zwei Tage "
        "auf Freitag, den 23. verschieben."
    )
    s.update({
        "modus": "verschieben",
        "wunsch": parse_slot_wish(wortlaut),
        "wunschText": wortlaut,
    })
    termin = {
        "id": "apt-oct",
        "iso": "2026-10-21T11:00:00+02:00",
        "calendarId": PATRIKIS,
        "doctorName": "Dr. Patrikis",
        "motivId": "pzr-plus-kontrolle",
        "motivName": "Professionelle Zahnreinigung plus Kontrolle",
        "spoken": "am Mittwoch, den einundzwanzigsten Oktober um elf Uhr",
    }
    sit["gefunden"] = [termin]
    gesehen: dict = {}
    echt = verwalten.kal.find_slots_behandler

    def fake(tenant, ctx, **kw):
        gesehen.update(kw)
        return {"ok": True, "slots": [
            "2026-10-23T09:00:00+02:00",
            "2026-10-23T13:00:00+02:00",
        ]}

    verwalten.kal.find_slots_behandler = fake
    try:
        aus = verwalten._bestaetigen(sit, termin, None)
    finally:
        verwalten.kal.find_slots_behandler = echt
    assert aus and sit.get("offered")
    assert s["wunsch"]["date"] == "2026-10-23"
    assert gesehen.get("start_date") == "2026-10-23"
    assert gesehen.get("motiv_fallback") is False
    assert all(o["iso"].startswith("2026-10-23") for o in sit["offered"])


def test_verschieb_suche_faellt_nicht_auf_kuerzeres_kontrollmotiv():
    """Ein 30-Minuten-Fallback darf keinen angeblich freien Platz fuer einen
    60-Minuten-Bestandstermin erzeugen."""
    aufrufe: list[str] = []
    echt_find = kal.find_slots
    echt_motiv = kal.motiv_von

    def fake_find(tenant, ctx, **kw):
        aufrufe.append(ctx.get("visitMotiveId"))
        if ctx.get("visitMotiveId") == "pzr-60":
            return {"ok": True, "slots": []}
        return {"ok": True, "slots": ["2026-10-26T13:00:00+01:00"]}

    kal.find_slots = fake_find
    kal.motiv_von = lambda *a, **k: {"id": "kontrolle-30", "name": "Kontrolle"}
    try:
        found = kal.find_slots_behandler(
            {"clientId": "c"},
            {"calendarId": "cal", "visitMotiveId": "pzr-60"},
            start_date="2026-10-23",
            motiv_fallback=False,
        )
    finally:
        kal.find_slots = echt_find
        kal.motiv_von = echt_motiv
    assert found.get("slots") == []
    assert aufrufe == ["pzr-60"]


def test_move_slot_taken_bietet_nur_ab_zieldatum_an():
    """Der CF-Rueckfall darf nach einem belegten Oktober-Slot nicht wieder
    September-Termine anbieten."""
    gesehen: dict = {}
    echt_update = kal._cf_update
    echt_offer = kal.offer_slots
    echt_live = kal.WRITE_LIVE
    kal.WRITE_LIVE = True
    kal._cf_update = lambda action, body: (
        400,
        {"status": "error", "message": "The slot is not available."},
        {"route": "updateOrCancelAppointment"},
    )

    def fake_offer(tenant, ctx, **kw):
        gesehen["ctx"] = dict(ctx)
        gesehen.update(kw)
        return {
            "ok": True,
            "spoken": "Frei ist am Dienstag, den siebenundzwanzigsten Oktober.",
            "slots": [{"iso": "2026-10-27T09:30:00+01:00", "spoken": "am Dienstag"}],
        }

    kal.offer_slots = fake_offer
    try:
        res = kal.move_appointment(
            {"clientId": "c", "locationId": "l"},
            {
                "appointmentId": "apt",
                "patientName": "Quirin Donaubauer",
                "calendarId": "cal-pzr",
                "visitMotiveId": "pzr-60",
            },
            slot_iso="2026-10-26T13:00:00+01:00",
        )
    finally:
        kal._cf_update = echt_update
        kal.offer_slots = echt_offer
        kal.WRITE_LIVE = echt_live
    assert res.get("slotTaken") is True
    assert res.get("slots", [])[0]["iso"].startswith("2026-10-27")
    assert gesehen.get("start_date") == "2026-10-26"
    assert gesehen.get("exclude_iso", "").startswith("2026-10-26T13:00")


def test_verschieb_fail_bleibt_deterministisch_in_der_slotwahl():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "verschieben",
        "phase": "verschieb_bestaetigen",
        "frage": "verschieb_ok",
        "vorname": "Quirin",
        "nachname": "Donaubauer",
        "slotIso": "2026-10-26T13:00:00+01:00",
    })
    termin = {
        "id": "apt",
        "iso": "2026-10-21T11:00:00+02:00",
        "calendarId": "cal-pzr",
        "doctorName": "Franziska Schmidt",
        "motivId": "pzr-60",
        "motivName": "Professionelle Zahnreinigung plus Kontrolle",
    }
    sit["gefunden"] = [termin]
    sit["verwaltenTermin"] = "apt"
    gesehen: dict = {}
    echt = verwalten.kal.move_appointment

    def fake_move(tenant, ctx, **kw):
        gesehen.update(ctx)
        return {
            "ok": False,
            "slotTaken": True,
            "slotIso": kw["slot_iso"],
            "spoken": "Dieser Platz ist nicht mehr frei. Frei ist am Dienstag.",
            "slots": [{"iso": "2026-10-27T09:30:00+01:00", "spoken": "am Dienstag"}],
        }

    verwalten.kal.move_appointment = fake_move
    try:
        aus = verwalten._verschieben(sit, None)
    finally:
        verwalten.kal.move_appointment = echt
    assert aus and "nicht mehr frei" in aus["text"]
    assert gesehen["calendarId"] == "cal-pzr"
    assert gesehen["visitMotiveId"] == "pzr-60"
    assert s["phase"] == "verschieb_angebot" and s["frage"] == "slotwahl"
    assert sit["offered"][0]["iso"].startswith("2026-10-27")
    assert "2026-10-26T13:00:00+01:00" in sit.get("slotGesperrt", [])


def test_hintergrund_vorrat_geht_ueber_behandler_suche():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": True,
        "motivId": "par-ait", "motivName": "PAR AIT",
        "arzt": {"typ": "letzter", "calendarId": PATRIKIS,
                 "calendarName": "Dr. Patrikis"},
    })
    pfade: list[str] = []
    echt_b = hintergrund.calendar.find_slots_behandler
    echt_f = hintergrund.calendar.find_slots

    def fake_beh(*a, **k):
        pfade.append("behandler")
        return {"ok": True, "slots": [_iso(2, 9)]}

    def boom(*a, **k):
        raise AssertionError("globale Suche verboten bei gebundenem Kalender")

    hintergrund.calendar.find_slots_behandler = fake_beh
    hintergrund.calendar.find_slots = boom
    try:
        hintergrund.vorrat_anstossen(sit)
        for _ in range(40):
            if pfade:
                break
            time.sleep(0.05)
        assert pfade == ["behandler"]
    finally:
        hintergrund.calendar.find_slots_behandler = echt_b
        hintergrund.calendar.find_slots = echt_f
