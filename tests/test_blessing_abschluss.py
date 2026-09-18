"""Blessing-Abschlusswachen aus den Live-Anrufen vom 15.09.2026."""

from __future__ import annotations

import pytest

from bianca import agent, flow, gehirn, verwalten
from kern import hirn, intent
from kern.slots import parse_slot_wish
from kern.tenants import laden


@pytest.fixture(autouse=True)
def _kein_intent_nachzug(monkeypatch):
    """Offline-Regressionen dürfen den gemeinsamen Intent-Pool nicht belegen."""
    monkeypatch.setenv("INTENT_NACHZUG", "0")


LIVE_GESCHEIDLE = [
    "Meinen Termin nächste Woche, wann ist der?",
    (
        "Kscheidle, Sigrid, ich habe einen Termin nächste Woche "
        "und weiss nicht um wie viel Uhr."
    ),
    "Ich habe einen Termin, ich weiss aber den Tag nicht mehr.",
    "Um meinen Termin, ich weiss nicht mehr, wann der ist.",
    "um meinen Termin nächste Woche, wann der ist",
    "Ich habe einen Termin Ende September und weiss nicht mehr wann.",
    "Ich würde gerne wissen, wann mein Charmin ist.",
    "Ist der Termin eingetragen?",
]

NEUBUCHUNG = [
    ("Ich hätte gern nächste Woche einen Termin.", "ANLEGEN"),
    ("Wann kann ich einen Termin bekommen?", "ANLEGEN"),
    ("Haben Sie nächste Woche einen freien Termin?", "ANLEGEN"),
    # Dieser Satz blieb bisher der nachgelagerten Ernte überlassen. B1 darf
    # ihn insbesondere nicht zur Bestandsauskunft umdeuten.
    ("Ich habe nächste Woche Zeit für einen Termin.", "KEINE"),
    ("Der Termin muss noch eingetragen werden.", "KEINE"),
]

GESCHEIDLE_TERMIN = {
    "ok": True,
    "patient": {
        "id": "patient-gescheidle",
        "firstName": "Sigrid",
        "lastName": "Gescheidle",
    },
    "appointments": [{
        "id": "termin-gescheidle",
        "iso": "2026-09-24T09:30",
        "date": "2026-09-24",
        "calendarId": "8krcWh7AuXEfgWc1blzQ",
        "doctorName": "Doktor Blessing",
        "motivId": "UnfQ5DOaMx9FLiTC3L9b",
        "motivName": "Kontrolle",
        "spoken": (
            "am Donnerstag, den vierundzwanzigsten September "
            "um neun Uhr dreißig bei Doktor Blessing"
        ),
    }],
}


def _sit(tenant_id: str = "blessing") -> dict:
    sit = {
        "id": f"bestandsauskunft-{tenant_id}",
        "tenant": laden(tenant_id),
        "messages": [{"role": "system", "content": "test"}],
        "stimme": "bianca",
    }
    hirn.init(sit)
    return sit


def test_b1_schalter_ist_nur_bei_blessing_aktiv():
    assert laden("blessing")["bestandsauskunftErweitert"] is True
    for tenant_id in ("meddent", "thaler", "ruether"):
        assert laden(tenant_id).get("bestandsauskunftErweitert") is not True


@pytest.mark.parametrize("gesagt", LIVE_GESCHEIDLE)
def test_b1_gescheidle_live_saetze_sind_bestandsauskunft(gesagt):
    sit = _sit()

    assert intent.ist_bestandsfrage(sit, gesagt)
    deutung = intent.erkennen(sit, gesagt)

    assert deutung["handlung"] == "WISSEN", (gesagt, deutung)
    assert deutung["gegenstand"] == "VORGANG", (gesagt, deutung)
    assert deutung["zug"] == "wechseln", (gesagt, deutung)


@pytest.mark.parametrize(("gesagt", "erwartet"), NEUBUCHUNG)
def test_b1_neuer_termin_bleibt_neubuchung(gesagt, erwartet):
    sit = _sit()

    assert not intent.ist_bestandsfrage(sit, gesagt)
    deutung = intent.erkennen(sit, gesagt)

    assert deutung["handlung"] == erwartet, (gesagt, deutung)
    if erwartet == "ANLEGEN":
        assert deutung["gegenstand"] == "VORGANG", (gesagt, deutung)


@pytest.mark.parametrize(
    "gesagt",
    [
        "Meinen Termin nächste Woche, wann ist der?",
        "Ich habe einen Termin, ich weiss aber den Tag nicht mehr.",
        "Ist der Termin eingetragen?",
    ],
)
def test_b1_andere_mandanten_behalten_die_bisherige_deutung(gesagt):
    for tenant_id in ("meddent", "thaler", "ruether"):
        sit = _sit(tenant_id)

        assert not intent.ist_bestandsfrage(sit, gesagt)
        deutung = intent.erkennen(sit, gesagt)

        assert deutung["handlung"] == "KEINE", (tenant_id, gesagt, deutung)
        assert deutung["zug"] == "halten", (tenant_id, gesagt, deutung)


def test_b1_statusfrage_im_noch_offenen_buchungsschritt_startet_keine_auskunft():
    sit = _sit()
    hirn.anliegen_hinzufuegen(
        sit,
        hirn._anliegen("ANLEGEN", "VORGANG", spiegel="Termin nächste Woche"),
        aktivieren=True,
    )
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "bestaetigen",
        "frage": "bestaetigung",
        "slotIso": "2026-09-22T09:00",
    })

    assert not intent.ist_bestandsfrage(sit, "Ist der Termin eingetragen?")
    deutung = intent.erkennen(sit, "Ist der Termin eingetragen?")

    assert deutung["handlung"] == "KEINE"
    assert deutung["zug"] in {"halten", "verfeinern"}


def test_b1_gescheidle_korrigiert_angelaufene_neubuchung_zur_auskunft():
    sit = _sit()
    hirn.anliegen_hinzufuegen(
        sit,
        hirn._anliegen("ANLEGEN", "VORGANG", spiegel="neuen Termin"),
        aktivieren=True,
    )
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "",
        "frage": "fuer_wen_check",
    })
    gesagt = "Ich habe einen Termin Ende September und weiss nicht mehr wann."

    deutung = intent.erkennen(sit, gesagt)
    assert deutung["handlung"] == "WISSEN"
    assert deutung["gegenstand"] == "VORGANG"
    assert deutung["zug"] == "wechseln"

    hirn.anwenden(sit, deutung)
    assert s["modus"] == "auskunft"
    assert sit.get("hirnModusNeu") is True
    anliegen = sit["hirn"]["anliegen"]
    assert any(
        a["handlung"] == "ANLEGEN" and a["status"] == "geparkt"
        for a in anliegen
    )
    assert any(
        a["handlung"] == "WISSEN" and a["status"] == "aktiv"
        for a in anliegen
    )


def test_b1_regex_rueckfall_ist_ebenfalls_mandantenscharf():
    gesagt = "Meinen Termin nächste Woche, wann ist der?"

    blessing = {"tenant": laden("blessing")}
    gehirn.einsammeln(blessing, gesagt)
    assert gehirn.sammler(blessing)["modus"] == "auskunft"

    for tenant_id in ("meddent", "thaler", "ruether"):
        sit = {"tenant": laden(tenant_id)}
        gehirn.einsammeln(sit, gesagt)
        assert gehirn.sammler(sit)["modus"] == "buchen"


def test_b1_agent_startet_ohne_llm_den_kalenderpfad(monkeypatch):
    def _kein_llm(*_args, **_kwargs):
        raise AssertionError("Die Gescheidle-Auskunft darf nie ans freie LLM")

    monkeypatch.setattr(agent.llm, "chat", _kein_llm)
    monkeypatch.setattr(agent.llm, "chat_stream", _kein_llm)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda _sit: None)

    sit = _sit()
    sit["anrufer"] = {
        "vorname": "Sigrid",
        "nachname": "Gescheidle",
        "patientId": "patient-gescheidle",
        "geschlecht": "female",
        "telefon": "+491701234567",
    }

    aus = agent.user_turn(sit, "Meinen Termin nächste Woche, wann ist der?")
    s = gehirn.sammler(sit)

    assert aus is not None
    assert s["modus"] == "auskunft"
    assert s["frage"] == "anrufer_check"
    assert "Frau Gescheidle" in aus["text"]
    assert "richtig erkannt" in aus["text"]
    assert "versichert" not in aus["text"].lower()
    assert "hautkontrolle" not in aus["text"].lower()


def test_b2_bekannter_gescheidle_anrufer_bekommt_den_termin_angesagt(monkeypatch):
    def _kein_llm(*_args, **_kwargs):
        raise AssertionError("Die Bestandsansage darf nie ans freie LLM")

    monkeypatch.setattr(agent.llm, "chat", _kein_llm)
    monkeypatch.setattr(agent.llm, "chat_stream", _kein_llm)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda _sit: None)
    monkeypatch.setattr(verwalten.hintergrund, "anstossen", lambda _sit: None)
    monkeypatch.setattr(
        verwalten.kal,
        "find_patient_appointments",
        lambda _tenant, _ctx: dict(GESCHEIDLE_TERMIN),
    )

    sit = _sit()
    sit["anrufer"] = {
        "vorname": "Sigrid",
        "nachname": "Gescheidle",
        "patientId": "patient-gescheidle",
        "geschlecht": "female",
        "telefon": "+491701234567",
    }

    aus1 = agent.user_turn(
        sit,
        "Ich habe einen Termin Ende September und weiss nicht mehr wann.",
    )
    assert "richtig erkannt" in aus1["text"]

    aus2 = agent.user_turn(sit, "Ja, richtig.")
    s = gehirn.sammler(sit)

    assert "vierundzwanzigsten September" in aus2["text"]
    assert "neun Uhr dreißig" in aus2["text"]
    assert "Kontrolle" in aus2["text"]
    assert "Doktor Blessing" in aus2["text"]
    assert "neuen Termin" not in aus2["text"]
    assert "Hautkontrolle" not in aus2["text"]
    assert s["modus"] == "auskunft"
    assert s["frage"] == "termin_ok"


def test_b2_buchstabierter_name_fuehrt_nach_readback_zur_ansage(monkeypatch):
    def _kein_llm(*_args, **_kwargs):
        raise AssertionError("Name und Terminauskunft bleiben deterministisch")

    gesucht = []

    def _finden(_tenant, ctx):
        gesucht.append(dict(ctx))
        return dict(GESCHEIDLE_TERMIN)

    monkeypatch.setattr(agent.llm, "chat", _kein_llm)
    monkeypatch.setattr(agent.llm, "chat_stream", _kein_llm)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda _sit: None)
    monkeypatch.setattr(verwalten.hintergrund, "anstossen", lambda _sit: None)
    monkeypatch.setattr(verwalten.kal, "find_patient_appointments", _finden)

    sit = _sit()
    aus1 = agent.user_turn(sit, "Meinen Termin nächste Woche, wann ist der?")
    assert "Nachname" in aus1["text"]
    assert gesucht == []

    aus2 = agent.user_turn(sit, "G-E-S-C-H-E-I-D-L-E, fertig.")
    s = gehirn.sammler(sit)
    assert "Gescheidle" in aus2["text"]
    assert "Ist das richtig" in aus2["text"]
    assert s["frage"] == "nachname_check"
    assert gesucht == [], "vor dem Namens-Readback darf keine Suche laufen"

    aus3 = agent.user_turn(sit, "Ja, richtig.")

    assert gesucht and gesucht[-1]["lastName"] == "Gescheidle"
    assert "vierundzwanzigsten September" in aus3["text"]
    assert "neun Uhr dreißig" in aus3["text"]
    assert "neuen Termin" not in aus3["text"]
    assert gehirn.sammler(sit)["frage"] == "termin_ok"


def test_b2_fertig_ist_nur_im_abgesicherten_namensdiktat_eine_formularantwort():
    gesagt = "G-E-S-C-H-E-I-D-L-E, fertig."

    blessing = _sit()
    hirn.anliegen_hinzufuegen(
        blessing,
        hirn._anliegen("WISSEN", "VORGANG", spiegel="bestehender Termin"),
        aktivieren=True,
    )
    gehirn.sammler(blessing).update({
        "modus": "auskunft",
        "frage": "nachname",
    })
    deutung = intent.erkennen(blessing, gesagt)
    assert deutung["handlung"] == "KEINE"
    assert deutung["zug"] == "verfeinern"
    assert deutung["quelle"] == "fastpath"

    # Kein Namensformular: „fertig“ behält seine bisherige allgemeine
    # Intent-Bedeutung und darf nicht als Buchstabierung getarnt werden.
    ohne_namensfrage = _sit()
    deutung = intent.erkennen(ohne_namensfrage, gesagt)
    assert deutung["handlung"] == "WISSEN"
    assert deutung["gegenstand"] == "REGEL"

    # Rüther verlangt seit 16.09. ebenfalls die ausdrückliche Buchstabierung.
    # Dort muss „fertig“ deshalb genauso im Namensformular bleiben.
    ruether = _sit("ruether")
    hirn.anliegen_hinzufuegen(
        ruether,
        hirn._anliegen("WISSEN", "VORGANG", spiegel="bestehender Termin"),
        aktivieren=True,
    )
    gehirn.sammler(ruether).update({
        "modus": "auskunft",
        "frage": "nachname",
    })
    deutung = intent.erkennen(ruether, gesagt)
    assert deutung["handlung"] == "KEINE"
    assert deutung["zug"] == "verfeinern"

    # W-FERTIG-DIKTAT (17.09.2026): das Schlusswort "fertig" im OFFENEN
    # Namensdiktat ist bei JEDEM Mandanten die Formularantwort — Bianca sagt
    # es dem Anrufer selbst so vor. Bis dahin las MedDent/Thaler daraus
    # WISSEN x REGEL ("Ist mein Befund fertig?"), das Hirn parkte das Anliegen
    # und leerte den Modus (Anruf 53986f42: 15 Zuege freies Modell).
    for tenant_id in ("meddent", "thaler"):
        sit = _sit(tenant_id)
        hirn.anliegen_hinzufuegen(
            sit,
            hirn._anliegen("WISSEN", "VORGANG", spiegel="bestehender Termin"),
            aktivieren=True,
        )
        gehirn.sammler(sit).update({
            "modus": "auskunft",
            "frage": "nachname",
        })
        deutung = intent.erkennen(sit, gesagt)
        assert deutung["handlung"] == "KEINE", (tenant_id, deutung)
        assert deutung["zug"] == "verfeinern", (tenant_id, deutung)
        # Ohne offene Namensfrage bleibt "fertig" auch dort das alte
        # Auskunftswort.
        frei = _sit(tenant_id)
        deutung_frei = intent.erkennen(frei, gesagt)
        assert deutung_frei["handlung"] == "WISSEN", (tenant_id, deutung_frei)


def test_b2_gesprochener_name_mit_fertig_erreicht_den_readback(monkeypatch):
    sit = _sit()
    hirn.anliegen_hinzufuegen(
        sit,
        hirn._anliegen("WISSEN", "VORGANG", spiegel="bestehender Termin"),
        aktivieren=True,
    )
    gehirn.sammler(sit).update({
        "modus": "auskunft",
        "frage": "buchstabieren",
    })

    def _kein_llm(*_args, **_kwargs):
        raise AssertionError("Ein Namensabschluss darf nicht ans freie LLM")

    monkeypatch.setattr(agent.llm, "chat", _kein_llm)
    monkeypatch.setattr(agent.llm, "chat_stream", _kein_llm)

    aus = agent.user_turn(sit, "Gavranides, fertig.")

    assert gehirn.sammler(sit)["nachname"] == "Gavranides"
    assert gehirn.sammler(sit)["frage"] == "nachname_check"
    assert "G wie Gustav" in aus["text"]
    assert "richtig" in aus["text"].lower()


BACHLE_MOVE = (
    "Ich habe bei Ihnen einen Termin am 21. Oktober, "
    "und den möchte ich gerne bis Mitte November enthalten."
)


def test_b3_baechle_verhoerer_ist_blessing_verschiebewunsch():
    sit = _sit()

    deutung = intent.erkennen(sit, BACHLE_MOVE)

    assert deutung["handlung"] == "AENDERN"
    assert deutung["gegenstand"] == "VORGANG"
    assert deutung["ersatz"] is True
    assert deutung["zug"] == "wechseln"


def test_b3_baechle_verhoerer_bleibt_mandantenscharf():
    for tenant_id in ("meddent", "thaler", "ruether"):
        sit = _sit(tenant_id)
        deutung = intent.erkennen(sit, BACHLE_MOVE)
        assert deutung["handlung"] == "KEINE", (tenant_id, deutung)


def test_b3_bestandsdatum_wird_vom_november_ziel_getrennt(monkeypatch):
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "verschieben",
        "phase": "",
        "frage": "",
        "vorname": "Sieglinde",
        "nachname": "Bächle",
        "patientId": "patient-baechle",
        "wunsch": parse_slot_wish(BACHLE_MOVE),
        "wunschText": BACHLE_MOVE,
    })
    gesehen = {}

    def _dispatch(_sit, _melde):
        gesehen["wunsch"] = dict(gehirn.sammler(_sit)["wunsch"] or {})
        gesehen["bestand"] = dict(_sit.get("verwHinweis") or {})
        return {"text": "sicherer Testabschluss"}

    monkeypatch.setattr(verwalten, "_dispatch", _dispatch)

    aus = verwalten._sammeln(
        sit,
        BACHLE_MOVE,
        {"modus", "wunsch"},
        None,
    )

    assert aus["text"] == "sicherer Testabschluss"
    assert gesehen["bestand"]["date"] == "2026-10-21"
    assert gesehen["wunsch"]["von"] == "2026-11-11"
    assert gesehen["wunsch"]["bis"] == "2026-11-20"
    assert gesehen["wunsch"].get("date") is None


def _pusch_vor_buchung() -> dict:
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "bestaetigen",
        "frage": "bestaetigung",
        "warSchonMal": False,
        "bekannt": False,
        "vorname": "Jelto",
        "vornameQuelle": "gesagt",
        "nachname": "Pusch",
        "buchstabiert": True,
        "geschlecht": "m",
        "geschlechtQuelle": "gesagt",
        "arzt": {
            "typ": "einzig",
            "calendarId": "8krcWh7AuXEfgWc1blzQ",
            "calendarName": "Doktor Charlotte Blessing",
        },
        "grund": "Kontrolle",
        "grundWortlaut": "Kontrolle",
        "motivId": "UnfQ5DOaMx9FLiTC3L9b",
        "motivName": "Kontrolle",
        "versicherung": "gesetzlich",
        "versicherungOk": True,
        "slotIso": "2026-09-16T09:30:00+02:00",
        "pzr": "nein",
    })
    sit["offered"] = [{
        "iso": "2026-09-16T09:30:00+02:00",
        "spoken": "morgen um neun Uhr dreißig",
    }]
    return sit


def test_c3_nach_slot_ja_kommt_nur_noch_die_handynummer(monkeypatch):
    sit = _pusch_vor_buchung()

    def _kein_write(*_args, **_kwargs):
        raise AssertionError("Vor bestätigter Handynummer darf kein Write laufen")

    monkeypatch.setattr(flow.kal, "book_slot", _kein_write)

    aus = flow._nach_ok_buchen(sit, "Ja, das würde passen.")
    s = gehirn.sammler(sit)

    assert "Handynummer" in aus["text"]
    assert s["frage"] == "telefon"
    assert sit["buchIntent"] is True
    assert "welchen Termin" not in aus["text"]
    assert "Vorname" not in aus["text"]
    assert "Geburtsdatum" not in aus["text"]


def test_c3_bestaetigte_handynummer_bucht_ohne_zweite_sammelei(monkeypatch):
    sit = _pusch_vor_buchung()
    s = gehirn.sammler(sit)
    s.update({
        "telefon": "0151 23456789",
        "telefonBekannt": "0151 23456789",
        "telefonOk": True,
        "smsEmpfaenger": "patient",
    })
    aufrufe = []

    def _book(_tenant, ctx, *, slot_iso):
        aufrufe.append((dict(ctx), slot_iso))
        return {
            "ok": True,
            "booked": True,
            "slotIso": slot_iso,
            "appointmentId": "termin-pusch",
            "spoken": "Der Termin ist fest eingetragen.",
        }

    monkeypatch.setattr(flow.kal, "book_slot", _book)

    aus = flow._nach_ok_buchen(sit, "Ja, das würde passen.")

    assert len(aufrufe) == 1
    assert aufrufe[0][1] == "2026-09-16T09:30:00+02:00"
    assert "fest eingetragen" in aus["text"]
    assert "welchen Termin" not in aus["text"]
    assert "vollständigen Namen" not in aus["text"]
    assert gehirn.sammler(sit)["phase"] == "gebucht"
