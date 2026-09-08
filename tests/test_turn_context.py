"""TurnContextV1: typisierte Fakten statt freier Prompt-Mischung."""

import json

from bianca import session as bianca_session
from kern import turn_context
from kern.sitzung import merke_tool, merke_zug, oeffentlich
from kern.tenants import laden
from lisa import session as lisa_session


THALER = {
    "_quelle": "cf",
    "clientId": "thaler-client",
    "locationId": "thaler-location",
    "praxisName": "Zahnarztpraxis Beispiel",
    "sprache": "de",
    "defaultCalendarId": "eva",
    "calendars": [
        {"id": "eva", "name": "Dr. Eva Thaler"},
        {"id": "pro", "name": "Prophylaxe"},
    ],
    "visitMotives": [
        {"id": "beratung", "name": "Besprechung", "duration": 20,
         "calendarIds": ["eva"]},
        {"id": "fuellung", "name": "Füllung", "duration": 30,
         "calendarIds": ["eva"]},
        {"id": "notfall", "name": "Schmerz/Notfall", "duration": 30,
         "calendarIds": ["eva"]},
        {"id": "pzr", "name": "Professionelle Zahnreinigung", "duration": 45,
         "calendarIds": ["pro"]},
    ],
}


def _sit(tenant=None, **sammler):
    return {
        "id": "abc123",
        "stimme": "Bianca",
        "tenant": tenant or THALER,
        "sammler": sammler,
        "messages": [],
        "tools": [],
        "zuege": [],
    }


def test_anbieterregister_trennt_person_von_funktion():
    ctx = turn_context.projekt(_sit())
    anbieter = {x["id"]: x for x in ctx["praxis"]["anbieter"]}
    assert anbieter["eva"]["typ"] == "person"
    assert anbieter["eva"]["istBehandler"] is True
    assert anbieter["pro"]["typ"] == "funktion"
    assert anbieter["pro"]["istBehandler"] is False
    assert anbieter["pro"]["sprechform"] == "bei der Prophylaxe"
    assert anbieter["eva"]["istStandard"] is True


def test_katalogregeln_beschreiben_thaler_ohne_clientid_sonderfall():
    regeln = turn_context.katalogregeln(_sit())
    assert regeln["hatFunktionsrouting"] is True
    assert regeln["pzrZielKalenderIds"] == ["pro"]
    assert regeln["personenMotivRegel"] == "besprechung_oder_akut"
    assert regeln["pzrMotiveIds"] == ["pzr"]
    assert regeln["akutMotiveIds"] == ["notfall"]
    assert regeln["besprechungMotiveIds"] == ["beratung"]


def test_meddent_bleibt_reines_personenregister():
    ctx = turn_context.projekt(_sit(laden("meddent")))
    assert all(x["typ"] == "person" for x in ctx["praxis"]["anbieter"])
    assert ctx["praxis"]["katalogregeln"]["hatFunktionsrouting"] is False


def test_unbestaetigte_identitaet_gibt_weder_name_noch_mas_fakten_frei():
    sit = _sit()
    sit["anrufer"] = {
        "vorname": "Michael", "nachname": "Petsas", "patientId": "pat-1",
    }
    sit["gedaechtnis"] = (
        "Demo-Interessent (Rechnung). Zollabfertigung AWB Onlinekauf.\n"
        "Termin verschoben auf morgen."
    )
    ctx = turn_context.projekt(sit)
    assert ctx["patient"]["identitaet"] == "erkannt_unbestaetigt"
    assert "name" not in ctx["patient"] and "patientId" not in ctx["patient"]
    assert ctx["mas"]["sichereFakten"] == []
    assert "Demo-Interessent" not in json.dumps(ctx, ensure_ascii=False)


def test_bestaetigter_patient_nutzt_kartei_nicht_mas_als_identitaet():
    sit = _sit(
        anruferCheck="ja",
        bekannt=True,
        vorname="Michael",
        nachname="Petsas",
        patientId="pat-1",
        telefonOk=True,
    )
    sit["gedaechtnis"] = (
        "Demo-Interessent (Rechnung). Zollabfertigung AWB Onlinekauf.\n"
        "- Termin verschoben auf morgen."
    )
    ctx = turn_context.projekt(sit)
    assert ctx["patient"]["name"] == "Michael Petsas"
    assert ctx["patient"]["quelle"] == "sammler_bestaetigt"
    assert ctx["mas"]["sichereFakten"] == ["Termin verschoben auf morgen."]
    assert "Demo-Interessent" not in json.dumps(ctx, ensure_ascii=False)


def test_tool_ledger_erlaubt_erledigt_behauptung_nur_mit_beleg():
    sit = _sit()
    merke_tool(sit, "book_slot", {"ok": False, "booked": False})
    ctx = turn_context.projekt(sit)
    assert ctx["werkzeuge"]["darfBuchungBestaetigen"] is False
    merke_tool(sit, "book_slot", {
        "ok": True,
        "booked": True,
        "slotIso": "2026-09-10T09:00:00+02:00",
        "appointmentId": "apt-1",
    })
    ctx = turn_context.projekt(sit)
    assert ctx["werkzeuge"]["darfBuchungBestaetigen"] is True
    assert ctx["werkzeuge"]["ledger"][-1]["quelle"] == "tool:book_slot"


def test_merke_zug_aktualisiert_snapshot_mit_nutzertext():
    sit = _sit()
    turn_context.aktualisieren(sit)
    merke_zug(sit, art="listen", textIn="Vormittag bitte.", text="Gerne.")
    assert sit["turnContext"]["sitzung"]["letzterNutzertext"] == "Vormittag bitte."


def test_beide_stimmen_starten_mit_turn_context():
    b = bianca_session.neu(tenant=THALER)
    l = lisa_session.neu(tenant=THALER, auftrag="Rückruf.")
    assert b["turnContext"]["schema"] == turn_context.SCHEMA
    assert l["turnContext"]["version"] == turn_context.VERSION
    assert oeffentlich(b)["turnContextVersion"] == turn_context.VERSION
    assert oeffentlich(l)["anbieter"] == 2


def test_turn_context_ist_json_tauglich():
    ctx = turn_context.projekt(_sit(grund="Kontrolle", motivId="beratung"))
    assert json.loads(json.dumps(ctx, ensure_ascii=False))["schema"] == turn_context.SCHEMA
