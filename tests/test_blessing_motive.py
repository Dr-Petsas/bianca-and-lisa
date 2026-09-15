"""Blessing: angebotene und dermatologische Gründe sicher weiterführen."""

from __future__ import annotations

import copy

import pytest

from bianca import agent, besuchsgrund, flow, gehirn, session
from kern import hirn
from kern.tenants import laden


def _sit() -> dict:
    sit = session.neu(tenant=laden("blessing"))
    agent.start_reply(sit)
    hirn.anliegen_hinzufuegen(
        sit,
        hirn._anliegen("ANLEGEN", "VORGANG", spiegel="Termin vereinbaren"),
        aktivieren=True,
    )
    gehirn.sammler(sit).update({
        "modus": "buchen",
        "phase": "",
        "frage": "grund",
        "warSchonMal": False,
    })
    return sit


@pytest.fixture(autouse=True)
def _kein_intent_nachzug(monkeypatch):
    monkeypatch.setenv("INTENT_NACHZUG", "0")


def test_c1_schalter_ist_nur_bei_blessing_aktiv():
    assert laden("blessing")["dermaMotivKlarheit"] is True
    assert laden("blessing")["einArztOhneBehandlerfrage"] is True
    for tenant_id in ("meddent", "thaler", "ruether"):
        assert laden(tenant_id).get("dermaMotivKlarheit") is not True
        assert laden(tenant_id).get("einArztOhneBehandlerfrage") is not True


def test_c1_ein_arzt_kostet_bestandspatienten_keine_behandlerfrage():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"warSchonMal": True, "arzt": None})

    fid, frage = gehirn.naechste_frage(sit)

    assert fid == "buchstabieren", (fid, frage)
    assert "behandler" not in frage.lower()
    assert s["arzt"] == {
        "typ": "einzig",
        "calendarId": "8krcWh7AuXEfgWc1blzQ",
        "calendarName": "Doktor Charlotte Blessing",
    }

    # Ohne Blessing-Opt-in bleibt die bisherige Bestandsfrage unverändert.
    alt = copy.deepcopy(laden("blessing"))
    alt.pop("einArztOhneBehandlerfrage")
    andere_sit = session.neu(tenant=alt)
    anderes = gehirn.sammler(andere_sit)
    anderes.update({"modus": "buchen", "warSchonMal": True, "arzt": None})
    fid, frage = gehirn.naechste_frage(andere_sit)
    assert fid == "arzt"
    assert "behandler" in frage.lower()


def test_c1_angebotene_beratung_wird_konkretisiert_statt_abgelehnt(monkeypatch):
    sit = _sit()
    monkeypatch.setattr(
        agent.llm,
        "chat_stream",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Die Beratungsklärung darf nie ans freie LLM")
        ),
    )
    monkeypatch.setattr(
        agent.llm,
        "chat",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Die Beratungsklärung darf nie ans freie LLM")
        ),
    )

    aus = agent.user_turn(sit, "Eine Beratung.")
    s = gehirn.sammler(sit)

    assert "nicht angeboten" not in aus["text"].lower()
    assert "allergie" in aus["text"].lower()
    assert "kosmetik" in aus["text"].lower()
    assert "botox" in aus["text"].lower()
    assert "hautveränderung" in aus["text"].lower()
    assert s["frage"] == "grund"
    assert not s["grund"] and not s["motivId"]


@pytest.mark.parametrize(
    "gesagt",
    [
        "Beratung.",
        "Ich möchte eine Beratung.",
        "Ich hätte gerne eine Beratung.",
        "Das wäre eine Beratung.",
        "Es geht um eine Beratung.",
        "Dann eine Beratung bitte.",
    ],
)
def test_c1_beratung_versteht_natuerliche_auswahlformen(gesagt):
    aus = flow.zug(_sit(), gesagt)
    assert aus and "welche beratung" in aus["text"].lower()
    assert "nicht angeboten" not in aus["text"].lower()


def test_c1_beratung_unterart_wird_danach_normal_gemappt():
    sit = _sit()

    erste = flow.zug(sit, "Eine Beratung.")
    zweite = flow.zug(sit, "Wegen einer Allergie.")
    s = gehirn.sammler(sit)

    assert erste and "nicht angeboten" not in erste["text"].lower()
    assert zweite and "nicht angeboten" not in zweite["text"].lower()
    assert s["motivId"] == "0OgCmirb1YYxRa7CJDj5"
    assert s["motivName"] == "Beratung Allergie"


def test_c1_etwas_anderes_ist_eine_offene_option_keine_ablehnung():
    sit = _sit()

    aus = flow.zug(sit, "Etwas anderes.")

    assert aus
    assert "nicht angeboten" not in aus["text"].lower()
    assert "genau" in aus["text"].lower()
    assert gehirn.sammler(sit)["frage"] == "grund"


@pytest.mark.parametrize(
    ("gesagt", "motiv_id"),
    [
        (
            "Rosacea, Weiterbehandlung.",
            "Hr7bt89rKrK3BDK4BnK4",
        ),
        (
            "Weitere Medikamentekontrolle.",
            "UnfQ5DOaMx9FLiTC3L9b",
        ),
        (
            "Weiter Behandlung.",
            "UnfQ5DOaMx9FLiTC3L9b",
        ),
        (
            "Er hat Hautprobleme an den Nägeln und am Fuß, "
            "immer wieder Wunden.",
            "5PuSqKkTtTgYuaYhajm5",
        ),
        (
            "Atterom.",
            "rRCFfJZZjV2mI5WWH6ZE",
        ),
        (
            "Auf meiner linken Backe ist ein Grützbeutel.",
            "rRCFfJZZjV2mI5WWH6ZE",
        ),
    ],
)
def test_c1_live_dermatologiegruende_laufen_nie_auf_notfall_oder_ablehnung(
    gesagt,
    motiv_id,
):
    t = laden("blessing")

    kern, vm = besuchsgrund.deute(t, gesagt, katalog=t["visitMotives"])

    assert kern
    assert vm and vm["id"] == motiv_id, (gesagt, kern, vm)
    assert vm["id"] != "cluzt3EwHYgnTwt3i1z9"


def test_c1_echter_akutfall_bleibt_notfall_aber_blutuntersuchung_nicht():
    t = laden("blessing")

    kern, vm = besuchsgrund.deute(
        t,
        "Die Haut ist stark entzündet, schmerzt und blutet.",
        katalog=t["visitMotives"],
    )
    assert kern == "akute Beschwerden/Notfall"
    assert vm and vm["id"] == "cluzt3EwHYgnTwt3i1z9"

    _kern, vm = besuchsgrund.deute(
        t,
        "Ich brauche eine Blutuntersuchung.",
        katalog=t["visitMotives"],
    )
    assert not vm or vm["id"] != "cluzt3EwHYgnTwt3i1z9"


def test_c1_ohne_blessing_schalter_bleibt_der_alte_mapper_byte_identisch():
    t = copy.deepcopy(laden("blessing"))
    t.pop("dermaMotivKlarheit", None)

    kern, vm = besuchsgrund.deute(
        t,
        "Weitere Medikamentekontrolle.",
        katalog=t["visitMotives"],
    )

    # Gegenbeweis des Opt-ins: der bisherige Mapper trifft wegen „eiter“ in
    # „weiter“ weiterhin sein altes Ergebnis. C1 ändert nur Blessing.
    assert kern == "akute Beschwerden/Notfall"
    assert vm and vm["id"] == "cluzt3EwHYgnTwt3i1z9"


def test_c1_fachfremder_zahnwunsch_bleibt_abgelehnt():
    sit = _sit()

    aus = flow.zug(sit, "Ich möchte eine Zahnreinigung.")

    assert aus and "nicht angeboten" in aus["text"].lower()
    assert not gehirn.sammler(sit)["grund"]
