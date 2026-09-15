"""Blessing-Abschlusswachen aus den Live-Anrufen vom 15.09.2026."""

from __future__ import annotations

import pytest

from bianca import agent, flow, gehirn
from kern import hirn, intent
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
