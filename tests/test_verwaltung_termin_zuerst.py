"""W-VERWALTUNG-TERMIN-ZUERST (16.09.2026).

Absage/Verschiebung suchen einen bekannten Termin zuerst ueber Datum,
Uhrzeit, Behandler und Rufnummer/patientId. Namen sind ab 60 Prozent nur
Kandidaten und jeder Treffer wird vor dem Schreiben rueckbestaetigt.
Terminauskunft ("weiss nicht wann") fragt dagegen niemals nach dem Datum.
Der Buchungsweg bleibt unberuehrt.
"""

import copy
import json

import pytest

from bianca import agent, flow, gehirn, verwalten
from kern import calendar
from kern.tenants import laden


def _sit(tenant: str = "meddent") -> dict:
    return {
        "tenant": laden(tenant),
        "messages": [{"role": "system", "content": "x"}],
    }


TERMIN = {
    "id": "apt-1310",
    "iso": "2026-10-13T09:45+02:00",
    "date": "2026-10-13",
    "calendarId": "cal-blessing",
    "doctorName": "Doktor Blessing",
    "motivId": "motiv-kontrolle",
    "motivName": "Kontrolle",
    "spoken": "am Dienstag, den dreizehnten Oktober um neun Uhr fünfundvierzig "
              "bei Doktor Blessing",
    "patientId": "patient-paesler",
    "patientFirstName": "Elisabeth",
    "patientLastName": "Päsler",
    "patientName": "Elisabeth Päsler",
    "patientPhone": "+491701234567",
}


def _details(monkeypatch, termine=None):
    monkeypatch.setattr(
        verwalten.kal,
        "find_appointments_by_date",
        lambda tenant, day: {
            "ok": True,
            "appointments": list(TERMINE if termine is None else termine),
            "dispatch": {
                "route": "firestoreAppointmentsByDate",
                "request": {"date": day},
                "httpStatus": 200,
                "response": {"appointments": len(
                    TERMINE if termine is None else termine)},
            },
        },
    )


TERMINE = [TERMIN]


def test_firestore_tageslese_normalisiert_termin(monkeypatch):
    rows = [{
        "document": {
            "name": "projects/x/databases/(default)/documents/clients/c/"
                    "locations/l/appointments/apt-1310",
            "fields": {
                "start": {"timestampValue": "2026-10-13T07:45:00Z"},
                "status": {"stringValue": "confirmed"},
                "patient": {"mapValue": {"fields": {
                    "id": {"stringValue": "patient-paesler"},
                    "firstName": {"stringValue": "Elisabeth"},
                    "lastName": {"stringValue": "Päsler"},
                    "mobilePhoneNumber": {"stringValue": "+491701234567"},
                }}},
                "calendar": {"mapValue": {"fields": {
                    "id": {"stringValue": "cal-blessing"},
                    "name": {"stringValue": "Doktor Blessing, Zimmer 1"},
                }}},
                "visitMotive": {"mapValue": {"fields": {
                    "id": {"stringValue": "motiv-kontrolle"},
                    "name": {"stringValue": "Kontrolle"},
                }}},
            },
        },
    }]
    monkeypatch.setattr(
        calendar,
        "_firestore_appointments_query",
        lambda tenant, von, bis: (
            200,
            rows,
            {"route": "firestoreAppointmentsByDate", "httpStatus": 200},
        ),
    )
    res = calendar.find_appointments_by_date(
        {"clientId": "c", "locationId": "l"}, "2026-10-13")
    assert res["ok"] is True
    assert len(res["appointments"]) == 1
    a = res["appointments"][0]
    assert a["id"] == "apt-1310"
    assert a["iso"].startswith("2026-10-13T09:45")
    assert a["patientName"] == "Elisabeth Päsler"
    assert a["doctorName"] == "Doktor Blessing"


def test_firestore_tageslese_blendet_virtuelle_und_abgesagte_aus(monkeypatch):
    basis = {
        "document": {
            "name": "projects/x/databases/(default)/documents/clients/c/"
                    "locations/l/appointments/ok",
            "fields": {
                "start": {"timestampValue": "2026-10-13T07:45:00Z"},
                "status": {"stringValue": "confirmed"},
                "patientStatus": {"integerValue": "0"},
                "patient": {"mapValue": {"fields": {
                    "id": {"stringValue": "p1"},
                    "firstName": {"stringValue": "Eva"},
                    "lastName": {"stringValue": "Echt"},
                }}},
                "calendar": {"mapValue": {"fields": {
                    "id": {"stringValue": "c1"},
                    "name": {"stringValue": "Doktor Blessing"},
                }}},
            },
        },
    }
    virtuell = copy.deepcopy(basis)
    virtuell["document"]["name"] = virtuell["document"]["name"].replace("/ok", "/virtuell")
    virtuell["document"]["fields"]["status"] = {"stringValue": "needsConfirmation"}
    abgesagt = copy.deepcopy(basis)
    abgesagt["document"]["name"] = abgesagt["document"]["name"].replace("/ok", "/abgesagt")
    abgesagt["document"]["fields"]["patientStatus"] = {"integerValue": "5"}
    reserviert = copy.deepcopy(basis)
    reserviert["document"]["name"] = reserviert["document"]["name"].replace("/ok", "/reserviert")
    reserviert["document"]["fields"]["status"] = {"stringValue": "reserved"}
    monkeypatch.setattr(
        calendar,
        "_firestore_appointments_query",
        lambda tenant, von, bis: (
            200,
            [basis, virtuell, abgesagt, reserviert],
            {"route": "firestoreAppointmentsByDate", "httpStatus": 200},
        ),
    )
    res = calendar.find_appointments_by_date(
        {"clientId": "c", "locationId": "l"}, "2026-10-13")
    assert [a["id"] for a in res["appointments"]] == ["ok"]


def test_firestore_tageslese_markiert_den_500er_deckel_als_unvollstaendig(
        monkeypatch):
    basis = {
        "document": {
            "name": "projects/x/databases/(default)/documents/clients/c/"
                    "locations/l/appointments/apt-0",
            "fields": {
                "start": {"timestampValue": "2026-10-13T07:45:00Z"},
                "status": {"stringValue": "confirmed"},
                "patient": {"mapValue": {"fields": {
                    "id": {"stringValue": "p1"},
                    "firstName": {"stringValue": "Eva"},
                    "lastName": {"stringValue": "Echt"},
                }}},
                "calendar": {"mapValue": {"fields": {
                    "id": {"stringValue": "c1"},
                    "name": {"stringValue": "Doktor Blessing"},
                }}},
            },
        },
    }
    rows = []
    for i in range(500):
        row = copy.deepcopy(basis)
        row["document"]["name"] = row["document"]["name"].replace(
            "apt-0", f"apt-{i}")
        rows.append(row)
    monkeypatch.setattr(
        calendar,
        "_firestore_appointments_query",
        lambda *_a, **_k: (
            200,
            rows,
            {"route": "firestoreAppointmentsByDate", "httpStatus": 200},
        ),
    )

    res = calendar.find_appointments_by_date(
        {"clientId": "c", "locationId": "l"}, "2026-10-13")
    assert res["ok"] and res["truncated"]
    assert len(res["appointments"]) == 500


def test_cf_termintreffer_blendet_inaktive_status_aus(monkeypatch):
    def cf(route, body, timeout=None):
        assert route == "agentFindPatientAppointments"
        appointments = [
            {
                "appointmentId": "aktiv",
                "start": "2026-10-13T09:45:00+02:00",
                "status": "confirmed",
            },
            {
                "appointmentId": "abgesagt",
                "start": "2026-10-14T09:45:00+02:00",
                "status": "cancelled",
            },
            {
                "appointmentId": "virtuell",
                "start": "2026-10-15T09:45:00+02:00",
                "status": "needsConfirmation",
            },
            {
                "appointmentId": "patient-abgesagt",
                "start": "2026-10-16T09:45:00+02:00",
                "patientStatus": 5,
            },
        ]
        return 200, {
            "status": "success",
            "patient": {
                "id": "p1",
                "firstName": "Eva",
                "lastName": "Echt",
            },
            "appointments": appointments,
        }, {"route": route, "request": body, "httpStatus": 200}

    monkeypatch.setattr(calendar, "_cf_call", cf)
    res = calendar.find_patient_appointments(
        {"clientId": "c", "locationId": "l"},
        {
            "firstName": "Eva",
            "lastName": "Echt",
            "managementNameMatch": True,
        },
    )
    assert [a["id"] for a in res["appointments"]] == ["aktiv"]


def test_absage_termindaten_grenzen_ein_aber_verraten_keinen_patienten(monkeypatch):
    _details(monkeypatch)
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    sit["verwAktiv"] = True
    assert verwalten._hinweis_merken(
        sit, "am 13. Oktober 2026 um 9:45 Uhr", relativ=True)

    calls = []
    monkeypatch.setattr(
        verwalten.kal,
        "cancel_by_id",
        lambda tenant, ctx, aid: calls.append(aid) or {
            "ok": True, "cancelled": True, "appointmentId": aid,
            "spoken": "Der Termin ist abgesagt.",
        },
    )
    handled, antwort = verwalten._detail_dispatch(sit, None)
    assert handled and antwort
    assert "Elisabeth Päsler" not in antwort["text"]
    assert "patientenabgleich" in antwort["text"].lower()
    assert s["frage"] == "nachname"
    assert "_verwDetailTermine" in sit
    assert "verwDetailTermine" not in sit
    assert calls == [], "vor der Rueckbestaetigung darf kein Write laufen"

    s["nachname"] = "Päsla"
    handled2, antwort2 = verwalten._detail_dispatch(sit, None)
    assert handled2 and "Elisabeth Päsler" in antwort2["text"]
    assert s["phase"] == "verw_patient_bestaetigen"

    bestaetigung = verwalten.zug(sit, "Ja, genau.", set())
    assert bestaetigung and "wirklich absagen" in bestaetigung["text"].lower()
    assert calls == []

    fertig = verwalten.zug(sit, "Ja, bitte absagen.", set())
    assert calls == ["apt-1310"]
    assert "abgesagt" in fertig["text"].lower()


def test_exakter_name_braucht_nur_die_terminbestaetigung(monkeypatch):
    _details(monkeypatch)
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "nachname": "Päsler"})
    sit["verwAktiv"] = True
    verwalten._hinweis_merken(
        sit, "am 13. Oktober 2026 um 9:45 Uhr", relativ=True)

    handled, antwort = verwalten._detail_dispatch(sit, None)
    assert handled and antwort
    assert sit["verwDetailQuelle"] == "nameExact"
    assert s["phase"] == "absage_bestaetigen"
    assert s["frage"] == "absage_ok"
    assert "wirklich absagen" in antwort["text"].lower()
    assert "nichts verwechseln" not in antwort["text"].lower()


def test_gleiche_uhrzeit_wird_vor_dem_namen_ueber_behandler_eingegrenzt(
    monkeypatch,
):
    termine = [
        {
            **TERMIN,
            "id": "apt-a",
            "patientId": "patient-a",
            "patientFirstName": "Anna",
            "patientLastName": "Berger",
            "patientName": "Anna Berger",
        },
        {
            **TERMIN,
            "id": "apt-b",
            "patientId": "patient-b",
            "patientFirstName": "Beate",
            "patientLastName": "Müller",
            "patientName": "Beate Müller",
            "calendarId": "cal-patrikis",
            "doctorName": "Doktor Patrikis",
            "spoken": "Dienstag, den dreizehnten Oktober um neun Uhr "
                      "fünfundvierzig bei Doktor Patrikis",
        },
    ]
    monkeypatch.setattr(
        calendar,
        "find_appointments_by_date",
        lambda *_a, **_k: {
            "ok": True,
            "appointments": termine,
            "dispatch": {"route": "firestoreAppointmentsByDate",
                         "httpStatus": 200},
        },
    )
    sit = _sit("meddent")
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    sit["verwAktiv"] = True
    verwalten._hinweis_merken(
        sit, "13. Oktober 2026 um 9:45 Uhr", relativ=True)
    handled, antwort = verwalten._detail_dispatch(sit, None)
    assert handled and antwort
    assert s["frage"] == "arzt"
    assert "Behandler" in antwort["text"]
    assert "Nachname" not in antwort["text"]
    s["arzt"] = {
        "calendarId": "cal-patrikis",
        "calendarName": "Doktor Patrikis",
        "typ": "wahl",
    }
    handled2, antwort2 = verwalten._detail_dispatch(sit, None)
    assert handled2 and antwort2
    assert s["frage"] == "nachname"
    assert "Patientenabgleich" in antwort2["text"]


def test_name_ab_sechzig_prozent_ist_nur_rueckversicherter_kandidat(monkeypatch):
    _details(monkeypatch)
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({"modus": "verschieben", "nachname": "Päsla"})
    sit["verwAktiv"] = True
    verwalten._hinweis_merken(sit, "13. Oktober 2026 um 9:45 Uhr", relativ=True)
    handled, antwort = verwalten._detail_dispatch(sit, None)
    assert handled and antwort
    assert sit["verwDetailQuelle"] == "name60"
    assert "Elisabeth Päsler" in antwort["text"]
    assert "nichts verwechseln" in antwort["text"].lower()
    assert s["frage"] == "verw_patient_ok"
    weiter = verwalten.zug(sit, "Ja, das ist mein Termin.", set())
    assert weiter and "wann passt" in weiter["text"].lower()

    sit2 = _sit("blessing")
    s2 = gehirn.sammler(sit2)
    s2.update({"modus": "absagen", "nachname": "Müller"})
    sit2["verwAktiv"] = True
    verwalten._hinweis_merken(sit2, "13. Oktober 2026 um 9:45 Uhr", relativ=True)
    handled2, antwort2 = verwalten._detail_dispatch(sit2, None)
    assert handled2 and antwort2
    assert "passt noch nicht sicher genug" in antwort2["text"]
    assert s2["nachname"] == ""
    assert s2["frage"] == "nachname"


def test_nein_zum_sechzig_prozent_kandidaten_fragt_namen_neu(monkeypatch):
    _details(monkeypatch)
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "nachname": "Päsla"})
    sit["verwAktiv"] = True
    verwalten._hinweis_merken(
        sit, "13. Oktober 2026 um 9:45 Uhr", relativ=True)
    handled, kandidat = verwalten._detail_dispatch(sit, None)
    assert handled and kandidat
    assert s["frage"] == "verw_patient_ok"

    antwort = verwalten.zug(sit, "Nein, das ist nicht mein Termin.", set())
    assert antwort
    assert s["frage"] == "nachname"
    assert s["nachname"] == ""
    assert not s["bekannt"] and not s["patientId"]
    assert "Nachnamen" in antwort["text"]


def test_sechzig_prozent_kandidat_gilt_mandantenuebergreifend(monkeypatch):
    _details(monkeypatch)
    for tenant_id in ("meddent", "thaler", "blessing", "ruether"):
        sit = _sit(tenant_id)
        s = gehirn.sammler(sit)
        s.update({"modus": "absagen", "nachname": "Päsla"})
        sit["verwAktiv"] = True
        verwalten._hinweis_merken(
            sit, "13. Oktober 2026 um 9:45 Uhr", relativ=True)
        handled, antwort = verwalten._detail_dispatch(sit, None)
        assert handled and antwort, tenant_id
        assert sit["verwDetailQuelle"] == "name60", tenant_id
        assert "Elisabeth Päsler" in antwort["text"], tenant_id


def test_auskunft_spricht_sechzig_prozent_kandidaten_erst_nach_ja(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({"modus": "auskunft", "nachname": "Päsla"})
    monkeypatch.setattr(
        verwalten.kal,
        "find_patient_appointments",
        lambda *_a, **_k: {
            "ok": True,
            "matchSource": "name60",
            "patient": {
                "id": "patient-paesler",
                "firstName": "Elisabeth",
                "lastName": "Päsler",
            },
            "appointments": [dict(TERMIN)],
        },
    )

    rueckfrage = verwalten._dispatch(sit, None)
    assert rueckfrage and "nichts verwechseln" in rueckfrage["text"].lower()
    assert s["frage"] == "verw_patient_ok"

    ansage = verwalten.zug(sit, "Ja, das ist richtig.", set())
    assert ansage and "nächster termin" in ansage["text"].lower()
    assert s["frage"] == "termin_ok"
    assert s["bekannt"] and s["patientId"] == "patient-paesler"


def test_auskunft_verwirft_fuzzy_patienten_nach_nein_vollstaendig(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({"modus": "auskunft", "nachname": "Päsla"})
    monkeypatch.setattr(
        verwalten.kal,
        "find_patient_appointments",
        lambda *_a, **_k: {
            "ok": True,
            "matchSource": "name60",
            "patient": {
                "id": "patient-paesler",
                "firstName": "Elisabeth",
                "lastName": "Päsler",
            },
            "appointments": [dict(TERMIN)],
        },
    )

    verwalten._dispatch(sit, None)
    assert not s["bekannt"] and not s["patientId"]
    antwort = verwalten.zug(sit, "Nein, die Person ist es nicht.", set())
    assert antwort and s["frage"] == "nachname"
    assert not s["bekannt"] and not s["patientId"]
    assert sit.get("patient") == {}


def test_unbestaetigte_anrufernummer_ist_kein_tageskalender_beweis(monkeypatch):
    _details(monkeypatch)
    sit = _sit("blessing")
    sit["anrufer"] = {
        "patientId": "patient-paesler",
        "vorname": "Elisabeth",
        "nachname": "Päsler",
        "telefon": "+491701234567",
    }
    sit["callerPhone"] = "+491701234567"
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    verwalten._hinweis_merken(
        sit, "13. Oktober 2026 um 9:45 Uhr", relativ=True)

    handled, antwort = verwalten._detail_dispatch(sit, None)
    assert handled and antwort
    assert "Elisabeth Päsler" not in antwort["text"]
    assert s["frage"] == "nachname"


def test_namenssuche_nutzt_nur_bestaetigte_patientennummer():
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "nachname": "Päsler",
        "telefon": "+491701234567",
        "telefonOk": False,
    })
    assert "phone" not in verwalten._ctx(sit)
    s["telefonOk"] = True
    assert verwalten._ctx(sit)["phone"] == "+491701234567"


def test_dritttermin_nutzt_kontaktnummer_nie_als_patientenbeweis():
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "nachname": "Päsler",
        "fuerWen": "sohn",
        "telefon": "+491701234567",
        "telefonOk": True,
    })
    assert "phone" not in verwalten._ctx(sit)


def test_aktive_absage_gibt_zwischenfrage_nie_ans_freie_llm():
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "phase": "wahl",
        "frage": "terminwahl",
        "vorname": "Elisabeth",
        "nachname": "Päsler",
    })
    sit["gefunden"] = [
        dict(TERMIN),
        {**TERMIN, "id": "apt-2", "iso": "2026-10-14T10:15+02:00",
         "spoken": "am Mittwoch, den vierzehnten Oktober um zehn Uhr fünfzehn"},
    ]

    antwort = flow.zug(sit, "Warum brauchen Sie das denn?", set())
    assert antwort
    assert "zur auswahl" in antwort["text"].lower()
    assert "abgesagt" not in antwort["text"].lower()


def test_agent_ruft_im_aktiven_absage_schritt_keine_llm_auf(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "phase": "wahl",
        "frage": "terminwahl",
        "vorname": "Elisabeth",
        "nachname": "Päsler",
    })
    sit["gefunden"] = [
        dict(TERMIN),
        {**TERMIN, "id": "apt-2", "iso": "2026-10-14T10:15+02:00",
         "spoken": "am Mittwoch, den vierzehnten Oktober um zehn Uhr fünfzehn"},
    ]

    def llm_verboten(*_args, **_kwargs):
        raise AssertionError("Aktive Absage darf das freie LLM nie aufrufen")

    monkeypatch.setattr(agent.llm, "chat", llm_verboten)
    monkeypatch.setattr(agent.llm, "chat_stream", llm_verboten)
    antwort = agent.user_turn(sit, "Das sollten Sie doch wissen.")
    assert antwort and "zur auswahl" in antwort["text"].lower()


def test_agent_ruft_im_aktiven_verschiebeschritt_keine_llm_auf(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "verschieben",
        "phase": "verschieb_bestaetigen",
        "frage": "verschieb_ok",
        "slotIso": "2026-10-20T11:00+02:00",
    })
    sit["verwaltenTermin"] = TERMIN["id"]
    sit["gefunden"] = [dict(TERMIN)]

    def llm_verboten(*_args, **_kwargs):
        raise AssertionError("Aktives Verschieben darf das freie LLM nie aufrufen")

    monkeypatch.setattr(agent.llm, "chat", llm_verboten)
    monkeypatch.setattr(agent.llm, "chat_stream", llm_verboten)
    antwort = agent.user_turn(sit, "Was passiert denn jetzt?")
    assert antwort and "passt das so" in antwort["text"].lower()
    assert s["phase"] == "verschieb_bestaetigen"


def test_agent_ruft_in_aktiver_terminauskunft_keine_llm_auf(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "auskunft",
        "phase": "wartet_auf_sichere_suche",
        "frage": "",
        "vorname": "Elisabeth",
        "nachname": "Päsler",
    })
    monkeypatch.setattr(
        verwalten.kal,
        "find_patient_appointments",
        lambda *_a, **_k: {
            "ok": True,
            "matchSource": "exact",
            "patient": {
                "id": "patient-paesler",
                "firstName": "Elisabeth",
                "lastName": "Päsler",
            },
            "appointments": [dict(TERMIN)],
        },
    )

    def llm_verboten(*_args, **_kwargs):
        raise AssertionError("Aktive Terminauskunft darf das freie LLM nie aufrufen")

    monkeypatch.setattr(agent.llm, "chat", llm_verboten)
    monkeypatch.setattr(agent.llm, "chat_stream", llm_verboten)
    antwort = agent.user_turn(sit, "Das sollten Sie doch wissen.")
    assert antwort and "ihr nächster termin" in antwort["text"].lower()


def test_unbekannte_zeit_mit_name_liefert_nie_leeren_anker(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "phase": "wartet_auf_sichere_suche",
        "frage": "",
        "vorname": "Elisabeth",
        "nachname": "Päsler",
    })
    sit["verwZeitUnbekannt"] = True
    monkeypatch.setattr(
        verwalten.kal,
        "find_patient_appointments",
        lambda *_a, **_k: {
            "ok": True,
            "matchSource": "exact",
            "patient": {
                "id": "patient-paesler",
                "firstName": "Elisabeth",
                "lastName": "Päsler",
            },
            "appointments": [dict(TERMIN)],
        },
    )

    antwort = flow.zug(sit, "Den Zeitpunkt kenne ich wirklich nicht.", set())
    assert antwort
    assert "wirklich absagen" in antwort["text"].lower()
    assert s["phase"] == "absage_bestaetigen"


def test_unklare_verschiebebestaetigung_bleibt_in_fester_maschine():
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "verschieben",
        "phase": "verschieb_bestaetigen",
        "frage": "verschieb_ok",
        "slotIso": "2026-10-20T11:00+02:00",
    })
    sit["verwaltenTermin"] = TERMIN["id"]
    sit["gefunden"] = [dict(TERMIN)]

    antwort = flow.zug(sit, "Das sollten Sie doch wissen.", set())
    assert antwort
    assert "passt das so" in antwort["text"].lower()
    assert "verschoben" not in antwort["text"].lower()
    assert s["phase"] == "verschieb_bestaetigen"


def test_mehrere_termine_eines_fuzzy_patienten_erst_nach_identitaets_ja(
        monkeypatch):
    zweiter = {
        **TERMIN,
        "id": "apt-2",
        "iso": "2026-10-13T15:30+02:00",
        "spoken": "am Dienstag, den dreizehnten Oktober um fünfzehn Uhr dreißig",
    }
    _details(monkeypatch, [dict(TERMIN), zweiter])
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "nachname": "Päsla"})
    verwalten._hinweis_merken(sit, "am 13. Oktober 2026", relativ=True)

    handled, rueckfrage = verwalten._detail_dispatch(sit, None)
    assert handled and rueckfrage
    assert "Päsler" in rueckfrage["text"]
    assert "neun Uhr" not in rueckfrage["text"]
    assert s["frage"] == "verw_patient_ok"

    auswahl = verwalten.zug(sit, "Ja, das ist richtig.", set())
    assert auswahl and "mehrere termine" in auswahl["text"].lower()
    assert "neun Uhr" in auswahl["text"]
    assert "fünfzehn Uhr" in auswahl["text"]
    assert s["frage"] == "terminwahl"


def test_erfolglose_auskunft_bietet_keine_neubuchung_an(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({"modus": "auskunft", "nachname": "Päsler"})
    monkeypatch.setattr(
        verwalten.kal,
        "find_patient_appointments",
        lambda *_a, **_k: {"ok": True, "patient": {}, "appointments": []},
    )

    antwort = verwalten._dispatch(sit, None)
    assert antwort and "keinen kommenden termin" in antwort["text"].lower()
    assert "neuen termin" not in antwort["text"].lower()
    assert s["frage"] == "sonst_noch"


def test_nein_zur_absage_registriert_sauberen_abschluss():
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "phase": "absage_bestaetigen",
        "frage": "absage_ok",
    })
    sit["verwaltenTermin"] = TERMIN["id"]
    sit["gefunden"] = [dict(TERMIN)]

    bleibt = flow.zug(sit, "Nein, bitte nicht.", set())
    assert bleibt and "bleibt bestehen" in bleibt["text"].lower()
    assert s["frage"] == "sonst_noch"
    assert sit.get("verwAbschlussOffen") is True

    ende = flow.zug(sit, "Nein, danke.", set())
    assert ende and ende.get("hangup")
    assert not sit.get("verwAbschlussOffen")


def test_fehlgeschlagene_absage_erfindet_keinen_erfolg(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "phase": "absage_bestaetigen",
        "frage": "absage_ok",
    })
    sit["verwaltenTermin"] = TERMIN["id"]
    sit["gefunden"] = [dict(TERMIN)]
    notizen = []
    monkeypatch.setattr(
        verwalten.kal,
        "cancel_by_id",
        lambda *_a, **_k: {"ok": False, "spoken": "Die Absage hat nicht geklappt."},
    )
    monkeypatch.setattr(
        verwalten,
        "_notiz_schreiben",
        lambda *_a, **k: notizen.append(k),
    )

    antwort = flow.zug(sit, "Ja, bitte absagen.", set())
    assert antwort and "nicht geklappt" in antwort["text"].lower()
    assert "erledigt" not in antwort["text"].lower()
    assert notizen and s["frage"] == "sonst_noch"


def test_fehlgeschlagenes_verschieben_erfindet_keinen_erfolg(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "verschieben",
        "phase": "verschieb_bestaetigen",
        "frage": "verschieb_ok",
        "slotIso": "2026-10-20T11:00+02:00",
    })
    sit["verwaltenTermin"] = TERMIN["id"]
    sit["gefunden"] = [dict(TERMIN)]
    notizen = []
    monkeypatch.setattr(
        verwalten.kal,
        "move_appointment",
        lambda *_a, **_k: {
            "ok": False,
            "spoken": "Das Verschieben hat nicht geklappt.",
        },
    )
    monkeypatch.setattr(
        verwalten,
        "_notiz_schreiben",
        lambda *_a, **k: notizen.append(k),
    )

    antwort = flow.zug(sit, "Ja, so passt es.", set())
    assert antwort and "nicht geklappt" in antwort["text"].lower()
    assert "verschoben." not in antwort["text"].lower()
    assert notizen and s["frage"] == "sonst_noch"


def test_widerspruechliches_ja_loest_keine_absage_aus(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "phase": "absage_bestaetigen",
        "frage": "absage_ok",
    })
    sit["verwaltenTermin"] = TERMIN["id"]
    sit["gefunden"] = [dict(TERMIN)]
    monkeypatch.setattr(
        verwalten.kal,
        "cancel_by_id",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("widersprüchliches Ja darf nicht absagen")),
    )

    antwort = verwalten.zug(
        sit, "Ja, aber das ist nicht mein Termin.", set())
    assert antwort and "ändere ich noch nichts" in antwort["text"].lower()
    assert s["phase"] == "absage_bestaetigen"


def test_widerspruechliches_ja_loest_keine_verschiebung_aus(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "verschieben",
        "phase": "verschieb_bestaetigen",
        "frage": "verschieb_ok",
        "slotIso": "2026-10-20T11:00+02:00",
    })
    sit["verwaltenTermin"] = TERMIN["id"]
    sit["gefunden"] = [dict(TERMIN)]
    monkeypatch.setattr(
        verwalten.kal,
        "move_appointment",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("widersprüchliches Ja darf nicht verschieben")),
    )

    antwort = verwalten.zug(
        sit, "Ja, aber diese Uhrzeit ist falsch.", set())
    assert antwort and "ändere ich noch nichts" in antwort["text"].lower()
    assert s["phase"] == "verschieb_bestaetigen"


def test_widerspruechliches_ja_loest_keine_mehrfach_absage_aus(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "phase": "mehrfach_bestaetigen",
        "frage": "mehrfach_ok",
    })
    sit["mehrfachAbsage"] = [
        {"id": "apt-1", "spoken": "am Montag um neun Uhr"},
        {"id": "apt-2", "spoken": "am Dienstag um zehn Uhr"},
    ]
    monkeypatch.setattr(
        verwalten.kal,
        "cancel_by_id",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("widersprüchliches Ja darf nichts absagen")),
    )

    antwort = verwalten.zug(sit, "Ja, aber nicht beide.", set())
    assert antwort and "ändere ich noch nichts" in antwort["text"].lower()
    assert s["phase"] == "mehrfach_bestaetigen"


def test_widerspruechliches_ja_bestaetigt_keinen_fuzzy_patienten():
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "phase": "verw_patient_bestaetigen",
        "frage": "verw_patient_ok",
    })
    sit["verwaltenTermin"] = TERMIN["id"]
    sit["verwKandidat"] = TERMIN["id"]
    sit["verwDetailQuelle"] = "name60"
    sit["gefunden"] = [dict(TERMIN)]

    antwort = verwalten.zug(
        sit, "Ja, aber das ist nicht mein Termin.", set())
    assert antwort and s["frage"] == "nachname"
    assert not s["patientId"] and not s["bekannt"]


def test_nein_zur_absage_ist_keine_suche_nach_dem_naechsten_kandidaten():
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "phase": "absage_bestaetigen",
        "frage": "absage_ok",
    })
    sit["verwaltenTermin"] = TERMIN["id"]
    sit["verwKandidat"] = TERMIN["id"]
    sit["verwDetailQuelle"] = "nameExact"
    sit["gefunden"] = [dict(TERMIN)]

    antwort = verwalten.zug(sit, "Nein, bitte nicht absagen.", set())
    assert antwort and "bleibt bestehen" in antwort["text"].lower()
    assert s["frage"] == "sonst_noch"
    assert not sit.get("_verwAusgeschlosseneTermine")


def test_verworfener_fuzzy_patient_wird_nicht_erneut_angeboten(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "phase": "verw_patient_bestaetigen",
        "frage": "verw_patient_ok",
        "vorname": "Elisabet",
        "nachname": "Päsla",
    })
    sit["verwaltenTermin"] = TERMIN["id"]
    sit["verwKandidat"] = TERMIN["id"]
    sit["verwDetailQuelle"] = "name60"
    sit["gefunden"] = [dict(TERMIN)]

    verworfen = verwalten.zug(sit, "Nein, das ist nicht mein Termin.", set())
    assert verworfen and s["frage"] == "nachname"
    assert "patient-paesler" in sit["_verwAusgeschlossenePatienten"]

    monkeypatch.setattr(
        verwalten.kal,
        "find_patient_appointments",
        lambda *_a, **_k: {
            "ok": True,
            "matchSource": "name60",
            "patient": {
                "id": "patient-paesler",
                "firstName": "Elisabeth",
                "lastName": "Päsler",
            },
            "appointments": [dict(TERMIN)],
        },
    )
    s["vorname"] = "Elisabet"
    s["nachname"] = "Päsla"
    ergebnis = verwalten._finden(sit, None)
    assert ergebnis.get("rejectedCandidate")
    assert ergebnis["appointments"] == []
    assert sit.get("gefunden") == []


def test_namenssuche_schreibt_keine_patientendaten_ins_tool_ledger(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "vorname": "Elisabeth",
        "nachname": "Päsler",
    })
    monkeypatch.setattr(
        verwalten.kal,
        "find_patient_appointments",
        lambda *_a, **_k: {
            "ok": True,
            "matchSource": "exact",
            "patient": {
                "id": "patient-paesler",
                "firstName": "Elisabeth",
                "lastName": "Päsler",
            },
            "appointments": [dict(TERMIN)],
            "dispatch": {
                "route": "agentFindPatientAppointments",
                "request": {
                    "clientId": "client",
                    "locationId": "location",
                    "lastName": "Päsler",
                    "callerPhone": "+491701234567",
                },
                "response": {
                    "patient": {
                        "id": "patient-paesler",
                        "firstName": "Elisabeth",
                        "lastName": "Päsler",
                    },
                    "appointments": [dict(TERMIN)],
                },
                "httpStatus": 200,
            },
        },
    )

    verwalten._finden(sit, None)
    spur = json.dumps(sit["_toolsZug"][-1], ensure_ascii=False)
    assert "Päsler" not in spur
    assert "Elisabeth" not in spur
    assert "+491701234567" not in spur
    assert "patient-paesler" not in spur
    assert '"appointments": 1' in spur


def test_erinnerter_tag_ohne_treffer_wechselt_zum_namen_statt_tagesschleife(
        monkeypatch):
    _details(monkeypatch, [])
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    verwalten._hinweis_merken(sit, "am 13. Oktober 2026", relativ=True)
    handled, antwort = verwalten._detail_dispatch(sit, None)
    assert handled and antwort
    assert s["frage"] == "nachname"
    assert "nachname" in antwort["text"].lower()
    assert "welcher tag" not in antwort["text"].lower()


def test_nur_monat_eroeffnet_keine_wann_schleife():
    sit = _sit("meddent")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "wunsch": {"von": "2026-10-01", "bis": "2026-10-31"},
        "wunschText": "im Oktober",
    })
    z1 = verwalten._sammeln(
        sit, "Ich möchte meinen Termin im Oktober absagen.", {"modus"}, None)
    assert z1
    assert s["frage"] == "wann"
    assert "genaue Datum" in z1["text"]

    z2 = verwalten._sammeln(sit, "Im Oktober.", set(), None)
    assert z2
    assert s["frage"] == "arzt"
    assert "Zeitpunkt müssen Sie nicht wissen" in z2["text"]


def test_telefon_patientid_gewinnt_vor_namensfrage(monkeypatch):
    _details(monkeypatch)
    sit = _sit("blessing")
    sit["anrufer"] = {
        "patientId": "patient-paesler",
        "telefon": "+491701234567",
        "vorname": "Elisabeth",
        "nachname": "Päsler",
    }
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "nachname": "Müller",  # STT-Verhörer darf bestätigte Akte nicht schlagen
        "patientId": "patient-paesler",
        "anruferCheck": "ja",
    })
    sit["verwAktiv"] = True
    verwalten._hinweis_merken(sit, "13. Oktober 2026 um 9:45 Uhr", relativ=True)
    handled, antwort = verwalten._detail_dispatch(sit, None)
    assert handled and antwort
    assert sit["verwDetailQuelle"] == "patientId"
    assert s["frage"] == "absage_ok"


def test_bestaetigte_akte_gewinnt_auch_wenn_erinnerte_zeit_fremd_ist(
    monkeypatch,
):
    _details(monkeypatch)
    gesucht: list[dict] = []
    eigener = {
        **TERMIN,
        "id": "apt-eigen",
        "iso": "2026-11-03T14:00+01:00",
        "spoken": "am Dienstag, den dritten November um vierzehn Uhr "
                  "bei Doktor Blessing",
        "patientId": "patient-berger",
        "patientFirstName": "Peter",
        "patientLastName": "Berger",
        "patientName": "Peter Berger",
    }

    def find(_tenant, ctx):
        gesucht.append(dict(ctx))
        return {
            "ok": True,
            "patient": {
                "id": "patient-berger",
                "firstName": "Peter",
                "lastName": "Berger",
            },
            "appointments": [eigener],
        }

    monkeypatch.setattr(calendar, "find_patient_appointments", find)
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "vorname": "Peter",
        "nachname": "Berger",
        "patientId": "patient-berger",
        "anruferCheck": "ja",
    })
    sit["verwAktiv"] = True
    verwalten._hinweis_merken(
        sit, "13. Oktober 2026 um 9:45 Uhr", relativ=True)
    antwort = verwalten._sammeln(
        sit, "Der Termin war am 13. Oktober um 9:45 Uhr.", set(), None)
    assert antwort
    assert gesucht and gesucht[0]["patientId"] == "patient-berger"
    assert "dritten November" in antwort["text"]
    assert "Elisabeth Päsler" not in antwort["text"]
    assert s["frage"] == "terminwahl"


def test_wiederholter_name_wechselt_auf_patientensuche_statt_schleife(
    monkeypatch,
):
    _details(monkeypatch)
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "nachname": "Müller"})
    sit["verwAktiv"] = True
    verwalten._hinweis_merken(
        sit, "13. Oktober 2026 um 9:45 Uhr", relativ=True)
    handled1, frage = verwalten._detail_dispatch(sit, None)
    assert handled1 and frage
    assert s["frage"] == "nachname"
    assert s["nachname"] == ""

    s["nachname"] = "Müller"
    s["buchstabiert"] = True
    handled2, antwort2 = verwalten._detail_dispatch(sit, None)
    assert handled2 is False
    assert antwort2 is None
    assert s["nachname"] == "Müller"


def test_patientid_springt_im_namensfallback_nie_auf_andere_akte(monkeypatch):
    rufe: list[str] = []

    def cf(route, _body, timeout=None):
        rufe.append(route)
        assert route == "masSearchPatients"
        return 200, {
            "status": "success",
            "patients": [{
                "id": "andere-akte",
                "firstName": "Elisabeth",
                "lastName": "Päsler",
                "mobilePhoneNumber": "+491701234567",
            }],
        }, {"route": route, "httpStatus": 200}

    monkeypatch.setattr(calendar, "_cf_call", cf)
    result = calendar._patient_appointments_fallback(
        _sit("blessing")["tenant"],
        first="Elisabeth",
        last="Päsla",
        vorname_verworfen=False,
        primary_dispatch=None,
        patient_id="bestaetigte-akte",
        phone="+491701234567",
        min_similarity=0.60,
    )
    assert result is None
    assert rufe == ["masSearchPatients"]


def test_cf_namenstreffer_ersetzt_bestaetigte_patientid_nie(monkeypatch):
    rufe: list[str] = []

    def cf(route, body, timeout=None):
        rufe.append(route)
        if route == "agentFindPatientAppointments":
            return 200, {
                "status": "success",
                "patient": {
                    "id": "andere-akte",
                    "firstName": "Peter",
                    "lastName": "Berger",
                },
                "appointments": [{
                    "appointmentId": "apt-fremd",
                    "start": "2026-10-13T09:45:00+02:00",
                }],
            }, {"route": route, "request": body, "httpStatus": 200}
        assert route == "masSearchPatients"
        return 200, {
            "status": "success",
            "patients": [{
                "id": "andere-akte",
                "firstName": "Peter",
                "lastName": "Berger",
            }],
        }, {"route": route, "request": body, "httpStatus": 200}

    monkeypatch.setattr(calendar, "_cf_call", cf)
    result = calendar.find_patient_appointments(
        _sit("blessing")["tenant"],
        {
            "firstName": "Peter",
            "lastName": "Berger",
            "patientId": "bestaetigte-akte",
            "managementNameMatch": True,
        },
    )
    assert result["ok"] and result["notFound"] and result["nameMismatch"]
    assert result["appointments"] == []
    assert rufe == ["agentFindPatientAppointments", "masSearchPatients"]


def test_cf_namenstreffer_ersetzt_bestaetigte_rufnummer_nie(monkeypatch):
    rufe: list[str] = []

    def cf(route, body, timeout=None):
        rufe.append(route)
        if route == "agentFindPatientAppointments":
            return 200, {
                "status": "success",
                "patient": {
                    "id": "andere-akte",
                    "firstName": "Peter",
                    "lastName": "Berger",
                    "mobilePhoneNumber": "+491709999999",
                },
                "appointments": [{
                    "appointmentId": "apt-fremd",
                    "start": "2026-10-13T09:45:00+02:00",
                }],
            }, {"route": route, "request": body, "httpStatus": 200}
        assert route == "masSearchPatients"
        return 200, {
            "status": "success",
            "patients": [{
                "id": "andere-akte",
                "firstName": "Peter",
                "lastName": "Berger",
                "mobilePhoneNumber": "+491709999999",
            }],
        }, {"route": route, "request": body, "httpStatus": 200}

    monkeypatch.setattr(calendar, "_cf_call", cf)
    result = calendar.find_patient_appointments(
        _sit("blessing")["tenant"],
        {
            "firstName": "Peter",
            "lastName": "Berger",
            "phone": "+491701234567",
            "managementNameMatch": True,
        },
    )
    assert result["ok"] and result["notFound"] and result["nameMismatch"]
    assert result["appointments"] == []
    assert rufe == ["agentFindPatientAppointments", "masSearchPatients"]


def test_no_upcoming_der_bestaetigten_akte_wird_nicht_fuzzy_umgebogen(
    monkeypatch,
):
    rufe: list[str] = []

    def cf(route, body, timeout=None):
        rufe.append(route)
        assert route == "agentFindPatientAppointments"
        return 404, {
            "status": "no_upcoming",
            "patient": {
                "id": "bestaetigte-akte",
                "firstName": "Elisabeth",
                "lastName": "Päsler",
            },
        }, {"route": route, "request": body, "httpStatus": 404}

    monkeypatch.setattr(calendar, "_cf_call", cf)
    result = calendar.find_patient_appointments(
        _sit("blessing")["tenant"],
        {
            "firstName": "falsch",
            "lastName": "verhört",
            "patientId": "bestaetigte-akte",
            "managementNameMatch": True,
        },
    )
    assert result["ok"]
    assert result["appointments"] == []
    assert not result.get("nameMismatch")
    assert rufe == ["agentFindPatientAppointments"]


def test_datumstreffer_umgeht_anrufer_identitaetscheck_nie(monkeypatch):
    sit = _sit("blessing")
    sit["anrufer"] = {
        "patientId": "patient-paesler",
        "telefon": "+491701234567",
        "vorname": "Elisabeth",
        "nachname": "Päsler",
    }
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    sit["verwAktiv"] = True
    verwalten._hinweis_merken(sit, "13. Oktober 2026 um 9:45 Uhr", relativ=True)
    monkeypatch.setattr(
        calendar,
        "find_appointments_by_date",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("vor dem Identitäts-Ja keine Tagesliste lesen")),
    )
    antwort = verwalten._sammeln(
        sit, "Der Termin ist am 13. Oktober um 9:45 Uhr.", set(), None)
    assert antwort
    assert s["frage"] == "anrufer_check"
    assert "Päsler" in antwort["text"]


def test_drittperson_verwirft_anruferakte_und_oktober_ist_kein_name():
    sit = _sit("blessing")
    sit["anrufer"] = {
        "patientId": "patient-anrufer",
        "telefon": "+491709999999",
    }
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "vorname": "Michael",
        "nachname": "Petsas",
        "patientId": "patient-anrufer",
        "anruferCheck": "ja",
    })
    neu = set()
    text = "Meine Mutter Elisabeth Päsler hat den Termin am 13. Oktober."
    verwalten._verw_drittperson_aufnehmen(sit, text, neu)
    assert s["fuerWen"] == "mutter"
    assert s["kontaktName"] == "Michael Petsas"
    assert s["patientId"] == ""
    assert s["vorname"] == "Elisabeth"
    assert s["nachname"] == "Päsler"
    verwalten._verw_name_zeitmuell_entfernen(sit, text, neu)

    s["nachname"] = "Brucklacher Oktober"
    verwalten._verw_name_zeitmuell_entfernen(
        sit, "Brucklacher, 13. Oktober um 9 Uhr", neu)
    assert s["nachname"] == "Brucklacher"


def test_live_brucklacher_satz_trennt_name_von_oktober(monkeypatch):
    _details(monkeypatch, [])
    monkeypatch.setattr(
        calendar,
        "find_patient_appointments",
        lambda tenant, ctx: {
            "ok": True,
            "patient": {
                "id": "p-brucklacher",
                "firstName": "Siegfried",
                "lastName": "Brucklacher",
            },
            "appointments": [{
                "id": "apt-brucklacher",
                "iso": "2026-10-13T09:00:00+02:00",
                "spoken": "am Dienstag, den dreizehnten Oktober um neun Uhr",
                "calendarId": "cal-blessing",
                "doctorName": "Doktor Blessing",
                "patientId": "p-brucklacher",
                "patientFirstName": "Siegfried",
                "patientLastName": "Brucklacher",
                "patientName": "Siegfried Brucklacher",
            }],
        },
    )
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({"modus": "verschieben", "frage": "wann"})
    sit["verwAktiv"] = True
    text = "Brucklacher, Siegfried, der Termin ist am 13. Oktober."
    neu = gehirn.einsammeln(sit, text)
    antwort = verwalten._sammeln(sit, text, neu, None)
    assert s["vorname"] == "Siegfried"
    assert s["nachname"] == "Brucklacher"
    assert "Oktober" not in f"{s['vorname']} {s['nachname']}"
    assert antwort and "Siegfried Brucklacher" in antwort["text"]


def test_strukturierter_familienname_mai_bleibt_trotz_termindatum():
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "frage": "wann"})
    text = "Mai, Anna, der Termin ist am 13. Oktober."
    neu: set[str] = set()
    verwalten._verw_detailname_aufnehmen(sit, text, neu)
    verwalten._verw_name_zeitmuell_entfernen(sit, text, neu)
    assert s["vorname"] == "Anna"
    assert s["nachname"] == "Mai"


def test_gruss_vor_strukturiertem_namen_wird_nicht_teil_des_namens():
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    neu: set[str] = set()
    verwalten._verw_detailname_aufnehmen(
        sit,
        "Guten Tag, Brucklacher, Siegfried, der Termin ist am 13. Oktober.",
        neu,
    )
    assert s["vorname"] == "Siegfried"
    assert s["nachname"] == "Brucklacher"


def test_vergessene_terminzeit_fragt_nie_nach_dem_vergessenen_datum():
    # Auskunft: direkt Patient/Behandler, niemals "wann war der Termin?".
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s["modus"] = "auskunft"
    sit["verwAktiv"] = True
    antwort = verwalten._sammeln(
        sit, "Ich weiß nicht mehr, wann mein Termin ist.", set(), None)
    assert antwort and "nachname" in antwort["text"].lower()
    assert "welcher tag" not in antwort["text"].lower()
    assert s["frage"] == "nachname"

    # Absage/Verschiebung mit unbekannter Zeit: in einer Mehrbehandlerpraxis
    # zuerst Behandler, dann Patientenname — ebenfalls kein Datum erfragen.
    sit2 = _sit("meddent")
    s2 = gehirn.sammler(sit2)
    s2["modus"] = "verschieben"
    sit2.update({"verwAktiv": True, "verwZeitUnbekannt": True})
    antwort2 = verwalten._sammeln(
        sit2, "Den Zeitpunkt weiß ich nicht mehr.", set(), None)
    assert antwort2 and "welchem behandler" in antwort2["text"].lower()
    assert "welcher tag" not in antwort2["text"].lower()

    # Auch eine reine Terminauskunft in einer Mehrbehandlerpraxis fragt nicht
    # ausgerechnet nach dem vergessenen Datum.
    sit3 = _sit("meddent")
    s3 = gehirn.sammler(sit3)
    s3["modus"] = "auskunft"
    sit3["verwAktiv"] = True
    antwort3 = verwalten._sammeln(
        sit3, "Ich weiß nicht mehr, wann mein Termin ist.", set(), None)
    assert antwort3 and "welchem behandler" in antwort3["text"].lower()
    assert "welcher tag" not in antwort3["text"].lower()


def test_vergessene_terminzeit_kompletter_flow_fragt_behandler_nicht_datum(
        monkeypatch):
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    sit = _sit("meddent")
    satz = "Ich weiß nicht mehr, wann mein Termin ist und möchte ihn genannt bekommen."
    assert verwalten._UNKLAR_RE.search(satz)
    antwort = flow.zug(sit, satz)
    s = gehirn.sammler(sit)
    assert s["modus"] == "auskunft"
    assert s["frage"] == "arzt"
    assert antwort and "welchem behandler" in antwort["text"].lower()
    assert "welcher tag" not in antwort["text"].lower()
    antwort2 = flow.zug(sit, "Bei Doktor Petsas.")
    assert s["frage"] == "nachname"
    assert antwort2 and "nachname" in antwort2["text"].lower()
    assert "welcher tag" not in antwort2["text"].lower()


@pytest.mark.parametrize(
    ("satz", "modus"),
    [
        ("Ich möchte meinen Termin absagen, weiß aber nicht mehr wann.", "absagen"),
        ("Ich möchte meinen Termin absagen, weiß aber gar nicht mehr wann.", "absagen"),
        ("Ich möchte meinen Termin verschieben, weiß aber nicht mehr wann.", "verschieben"),
    ],
)
def test_absage_und_verschieben_ohne_zeit_fragen_nicht_nach_wann(
        satz, modus):
    sit = _sit("meddent")
    antwort = flow.zug(sit, satz)
    s = gehirn.sammler(sit)
    assert antwort
    assert s["modus"] == modus
    assert s["frage"] == "arzt"
    assert "behandler" in antwort["text"].casefold()
    assert "welcher tag" not in antwort["text"].casefold()
    assert "welches datum" not in antwort["text"].casefold()


def test_nein_zum_neuen_termin_rutscht_trotz_datumsangabe_nicht_ins_buchen():
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "phase": "fertig",
        "frage": "neubuchung",
        "wunsch": {"date": "2026-10-13"},
    })
    antwort = verwalten.zug(
        sit,
        "Nein, keinen neuen Termin. Der bestehende war am 13. Oktober.",
        {"wunsch"},
    )
    assert antwort and "kein neuer termin" in antwort["text"].lower()
    assert s["modus"] == "absagen"


def test_namensfallback_nimmt_60_prozent_kandidat_statt_falschen_nachnamen(monkeypatch):
    calls = []

    def cf(route, body, **kwargs):
        calls.append((route, dict(body)))
        dispatch = {"route": route, "httpStatus": 200}
        if route == "agentFindPatientAppointments":
            return 404, {"status": "not_found"}, dispatch
        if route == "masSearchPatients":
            return 200, {
                "status": "success",
                "patients": [
                    {"id": "richtig", "firstName": "Larissa", "lastName": "Haug"},
                    {"id": "falsch", "firstName": "Meryem", "lastName": "Hauck"},
                ],
            }, dispatch
        if route == "masPatientLastDoctor":
            assert body["patientId"] == "richtig"
            return 200, {
                "status": "success",
                "nextAppointment": {
                    "appointmentId": "apt-haug",
                    "startIso": "2026-09-17T09:45:00+02:00",
                    "calendarId": "cal-blessing",
                    "calendarName": "Doktor Blessing",
                    "visitMotiveName": "Kontrolle",
                },
            }, dispatch
        raise AssertionError(route)

    monkeypatch.setattr(calendar, "_cf_call", cf)
    res = calendar.find_patient_appointments(_sit("blessing")["tenant"], {
        "firstName": "Larissa",
        "lastName": "Hauck",
        "managementNameMatch": True,
    })
    assert res["ok"] is True
    assert res["patient"]["id"] == "richtig"
    assert res["patient"]["lastName"] == "Haug"
    assert res["matchSource"] == "name60"
    assert res["appointments"][0]["id"] == "apt-haug"
    assert [route for route, _ in calls] == [
        "agentFindPatientAppointments", "masSearchPatients", "masPatientLastDoctor",
    ]


def test_cf_namenstreffer_ab_sechzig_prozent_bleibt_unbestaetigter_kandidat(
        monkeypatch):
    def cf(route, body, **kwargs):
        assert route == "agentFindPatientAppointments"
        return 200, {
            "status": "success",
            "patient": {
                "id": "patient-paesler",
                "firstName": "Elisabeth",
                "lastName": "Päsler",
            },
            "appointments": [{
                "appointmentId": "termin-paesler",
                "start": "2026-10-13T09:00:00+02:00",
                "calendarId": "cal-blessing",
                "doctorName": "Doktor Blessing",
            }],
        }, {"route": route, "httpStatus": 200}

    monkeypatch.setattr(calendar, "_cf_call", cf)
    res = calendar.find_patient_appointments(
        _sit("blessing")["tenant"],
        {
            "firstName": "Elisabet",
            "lastName": "Päsla",
            "managementNameMatch": True,
        },
    )
    assert res["ok"] and res["matchSource"] == "name60"
    assert res["appointments"][0]["id"] == "termin-paesler"


def test_cf_patienten_id_ist_trotz_namensverhoerer_harter_beweis(monkeypatch):
    def cf(route, body, **kwargs):
        assert body["patientId"] == "patient-paesler"
        return 200, {
            "status": "success",
            "patient": {
                "id": "patient-paesler",
                "firstName": "Elisabeth",
                "lastName": "Päsler",
            },
            "appointments": [{
                "appointmentId": "termin-paesler",
                "start": "2026-10-13T09:00:00+02:00",
                "calendarId": "cal-blessing",
                "doctorName": "Doktor Blessing",
            }],
        }, {"route": route, "httpStatus": 200}

    monkeypatch.setattr(calendar, "_cf_call", cf)
    res = calendar.find_patient_appointments(
        _sit("blessing")["tenant"],
        {
            "firstName": "Ganz",
            "lastName": "Anders",
            "patientId": "patient-paesler",
            "managementNameMatch": True,
        },
    )
    assert res["ok"] and res["matchSource"] == "patientId"


def test_ohne_verwaltungsflag_bleibt_alter_vornamen_nachfass_unveraendert(monkeypatch):
    calls = []

    def cf(route, body, **kwargs):
        calls.append(dict(body))
        dispatch = {"route": route, "httpStatus": 200}
        if len(calls) == 1:
            return 404, {"status": "not_found"}, dispatch
        return 200, {
            "status": "success",
            "patient": {"id": "alt", "firstName": "Meryem", "lastName": "Hauck"},
            "appointments": [],
        }, dispatch

    monkeypatch.setattr(calendar, "_cf_call", cf)
    res = calendar.find_patient_appointments(_sit("blessing")["tenant"], {
        "firstName": "Larissa",
        "lastName": "Hauck",
    })
    assert res["ok"] is True
    assert calls[0]["firstName"] == "Larissa"
    assert "firstName" not in calls[1]
    assert res["vornameVerworfen"] is True


def test_buchungsweg_nutzt_die_detail_suche_nie(monkeypatch):
    sit = _sit("blessing")
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    verwalten._hinweis_merken(sit, "13. Oktober 2026 um 9:45 Uhr", relativ=True)
    monkeypatch.setattr(
        verwalten.kal,
        "find_appointments_by_date",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Buchungsweg darf Detail-Suche nicht aufrufen")),
    )
    assert verwalten._detail_kandidaten(sit, None) is None
