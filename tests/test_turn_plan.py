"""TurnPlanV1: LLM darf planen, aber keine Fakten oder Aktionen erfinden."""

import json

from kern import turn_context, turn_plan

from tests.test_turn_context import THALER, _sit


def _raw(**updates):
    plan = {
        "intent": {
            "id": "buchen",
            "confidence": 0.94,
            "evidence": ["Ich brauche einen Termin zur Kontrolle."],
        },
        "conversation": {
            "mode": "job",
            "acknowledgement": "kurz",
            "next": "werkzeug",
            "questionSlot": "",
            "returnTask": "",
        },
        "actions": [{
            "name": "offer_slots",
            "arguments": {"wish": "vormittags"},
            "bindings": {"calendarId": "eva", "visitMotiveId": "beratung"},
            "gate": "fakten_bereit",
            "reason": "Grund und Behandler sind bekannt.",
        }],
        "factsUsed": [
            {"path": "anliegen.grund", "source": "sammler"},
            {"path": "praxis.defaultCalendarId", "source": "pickadoc_konfiguration"},
        ],
        "uncertainties": [],
    }
    plan.update(updates)
    return plan


def _ctx(*, bestaetigt=False):
    sammler = {
        "modus": "buchen",
        "grund": "Kontrolle",
        "motivId": "beratung",
        "motivName": "Besprechung",
        "arzt": {"calendarId": "eva", "calendarName": "Dr. Eva Thaler"},
    }
    if bestaetigt:
        sammler.update({
            "anruferCheck": "ja",
            "bekannt": True,
            "vorname": "Anna",
            "nachname": "Keller",
            "patientId": "pat-1",
            "telefonOk": True,
        })
    return turn_context.projekt(_sit(THALER, **sammler))


def test_gueltiger_plan_verweist_nur_auf_registrierte_fakten():
    plan = turn_plan.validieren(_raw(), _ctx())
    assert plan["valid"] is True
    assert plan["intent"]["id"] == "buchen"
    assert plan["actions"][0]["mode"] == "read"
    assert plan["observeOnly"] is True


def test_erfundener_kalender_oder_besuchsgrund_faellt_durch():
    raw = _raw(actions=[{
        "name": "offer_slots",
        "arguments": {},
        "bindings": {"calendarId": "dr-erfunden", "visitMotiveId": "m-falsch"},
        "gate": "fakten_bereit",
    }])
    plan = turn_plan.validieren(raw, _ctx())
    assert plan["valid"] is False
    assert any("calendarId_nicht_im_register" in x for x in plan["errors"])
    assert plan["actions"] == []


def test_werkzeugargumente_muessen_zum_vertrag_passen():
    raw = _raw(actions=[{
        "name": "offer_slots",
        "arguments": {"patientName": "Erfunden"},
        "bindings": {"calendarId": "eva", "visitMotiveId": "beratung"},
        "gate": "fakten_bereit",
    }])
    plan = turn_plan.validieren(raw, _ctx())
    assert not plan["valid"]
    assert "argument_unbekannt:offer_slots:patientName" in plan["errors"]


def test_schreibwerkzeug_braucht_explizite_anruferbestaetigung():
    raw = _raw(actions=[{
        "name": "cancel_appointment",
        "arguments": {},
        "gate": "fakten_bereit",
    }])
    plan = turn_plan.validieren(raw, _ctx(bestaetigt=True))
    assert not plan["valid"]
    assert "schreibwerkzeug_ohne_bestaetigung:cancel_appointment" in plan["errors"]


def test_book_slot_muss_aus_dem_angebot_stammen():
    ctx = _ctx(bestaetigt=True)
    raw = _raw(actions=[{
        "name": "book_slot",
        "arguments": {"slot_iso": "2026-09-10T09:00:00+02:00"},
        "gate": "anrufer_bestaetigt",
    }])
    assert "book_slot_nicht_angeboten" in turn_plan.validieren(raw, ctx)["errors"]
    ctx["angebot"] = [{
        "iso": "2026-09-10T09:00:00+02:00",
        "gesprochen": "Donnerstag um neun Uhr",
    }]
    plan = turn_plan.validieren(raw, ctx)
    assert plan["valid"] is True
    assert plan["actions"][0]["name"] == "book_slot"


def test_unbestaetigte_patientenfakten_sind_als_beleg_unzulaessig():
    raw = _raw(factsUsed=[{
        "path": "patient.name",
        "source": "bestaetigte_identitaet",
    }])
    plan = turn_plan.validieren(raw, _ctx())
    assert not plan["valid"]
    assert "fakt_unbelegt:patient.name" in plan["errors"]


def test_bestaetigter_naechster_termin_ist_typisierter_kalenderfakt():
    sit = _sit(
        THALER,
        anruferCheck="ja",
        bekannt=True,
        vorname="Anna",
        nachname="Keller",
        patientId="pat-1",
        telefonOk=True,
    )
    sit["upcoming"] = [{
        "id": "apt-1",
        "iso": "2026-09-10T09:00:00+02:00",
        "calendarId": "eva",
        "doctorName": "Dr. Eva Thaler",
        "motivName": "Besprechung",
    }]
    ctx = turn_context.projekt(sit)
    assert ctx["patient"]["kommendeTermine"][0]["id"] == "apt-1"
    raw = _raw(factsUsed=[{
        "path": "patient.kommendeTermine",
        "source": "bestaetigte_identitaet",
    }])
    assert turn_plan.validieren(raw, ctx)["valid"] is True


def test_planer_ist_nur_expliziter_offline_call_und_fuehrt_nichts_aus():
    ctx = _ctx()
    calls = []

    def fake_llm(messages):
        calls.append(messages)
        return {"text": json.dumps(_raw(), ensure_ascii=False)}

    plan = turn_plan.planen(ctx, llm_call=fake_llm)
    assert plan["valid"] is True and len(calls) == 1
    assert ctx["werkzeuge"]["ledger"] == []
    assert all("Antworttext" not in str(a) for a in plan["actions"])


def test_codeblock_json_wird_akzeptiert():
    raw = "```json\n" + json.dumps(_raw(), ensure_ascii=False) + "\n```"
    assert turn_plan.validieren(raw, _ctx())["valid"] is True


def test_falscher_context_und_unbekannter_intent_sind_ungueltig():
    assert turn_plan.validieren(_raw(), {})["errors"] == ["falscher_turn_context"]
    plan = turn_plan.validieren(_raw(intent={"id": "zaubern"}), _ctx())
    assert not plan["valid"] and "intent_unbekannt" in plan["errors"]
