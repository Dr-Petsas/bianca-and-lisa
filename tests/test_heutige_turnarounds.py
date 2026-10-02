"""Eng begrenzte Regressionen aus den Originalaudio-Replays vom 02.10.2026."""

from __future__ import annotations

import pytest

from bianca import arzt, flow, gehirn, session
from kern.tenants import laden


@pytest.mark.parametrize(
    "gesagt",
    [
        "Abfrage beziehungsweise Auskunft.",
        "Auskunft.",
        "Ja, Auskunft.",
        "Terminauskunft",
        "Im Oktober.",
    ],
)
def test_menue_und_monat_werden_auf_namensfrage_nicht_zu_nachnamen(gesagt):
    sit = session.neu(tenant=laden("blessing"))
    s = gehirn.sammler(sit)
    s["modus"] = "auskunft"
    s["frage"] = "nachname"

    gehirn.einsammeln(sit, gesagt)

    assert not s.get("nachname")
    assert not s.get("vorname")


def test_echter_nachname_mai_bleibt_moeglich():
    sit = session.neu(tenant=laden("blessing"))
    s = gehirn.sammler(sit)
    s["frage"] = "nachname"

    gehirn.einsammeln(sit, "Mein Nachname ist Mai.")

    assert s.get("nachname") == "Mai"


def test_anrufer_check_metafrage_wird_erklaert_statt_wiederholt():
    sit = session.neu(tenant=laden("blessing"))
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "anrufer_check"
    sit["anrufer"] = {
        "vorname": "Erika",
        "nachname": "Beispiel",
        "telefon": "+4915112345678",
        "patientId": "patient-test",
    }

    aus = flow.zug(sit, "Wie meint sie erkannt?", lambda *_a, **_k: None)

    assert aus is not None
    assert "Rufnummer" in aus.get("text", "")
    assert "Ja oder Nein" in aus.get("text", "")
    assert "Beispiel" not in aus.get("text", "")
    assert s.get("frage") == "anrufer_check"


def _zwei_behandler_tenant() -> dict:
    tenant = dict(laden("blessing"))
    tenant["einArztOhneBehandlerfrage"] = False
    tenant["defaultCalendarId"] = "blessing"
    tenant["calendars"] = [
        {"id": "blessing", "name": "Doktor Charlotte Blessing"},
        {"id": "ralf", "name": "Doktor Ralf Beispiel"},
    ]
    return tenant


def test_behandler_entscheidungshilfe_erklaert_einmal_dann_standard():
    sit = session.neu(tenant=_zwei_behandler_tenant())
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["warSchonMal"] = False
    s["frage"] = "arzt"

    eins = flow.zug(
        sit, "Habe ich ein Problem mit meinen Haaren?", lambda *_a, **_k: None
    )
    assert eins is not None
    assert "medizinisch nicht entscheiden" in eins.get("text", "")
    assert "Doktor Blessing oder Doktor Ralf" not in eins.get("text", "")
    assert not (s.get("arzt") or {}).get("calendarId")

    zwei = flow.zug(sit, "Ist die gleiche oder?", lambda *_a, **_k: None)
    assert zwei is not None
    assert (s.get("arzt") or {}).get("calendarId") == "blessing"
    assert "Standard-Behandler" in zwei.get("text", "")


def test_welchen_doktor_muss_ich_waehlen_bedeutet_keine_praeferenz():
    gedeutet = arzt.deute(
        "Ich habe ein Problem mit Haare. Mit welchem Doktor muss ich machen einen Termin?",
        _zwei_behandler_tenant(),
    )
    assert gedeutet is not None
    assert gedeutet.get("typ") == "egal"


def test_schonmal_erster_leerlauf_nimmt_echte_variante_statt_llm():
    sit = session.neu(tenant=laden("meddent"))
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "schonmal"

    aus = flow.zug(sit, "Vielleicht.", lambda *_a, **_k: None)

    assert aus is not None
    assert "Kurz zur Einordnung" in aus.get("text", "")
    assert "Waren Sie denn schon einmal bei uns in der Praxis?" not in aus.get(
        "text", ""
    )
    assert s.get("frage") == "schonmal"
