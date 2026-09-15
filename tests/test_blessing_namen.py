"""Blessing: Namensaufnahme bleibt im Formular statt in der Unklar-Schleife."""

from __future__ import annotations

import pytest

from bianca import agent, buchstaben, gehirn
from kern import agentprofil, hirn
from kern.tenants import laden


def _sit(tenant_id: str = "blessing", *, frage: str = "buchstabieren") -> dict:
    sit = {
        "id": f"blessing-name-{frage}",
        "stimme": "Bianca",
        "tenant": laden(tenant_id),
        "messages": [
            {"role": "system", "content": "test"},
            {
                "role": "assistant",
                "content": "Wie lautet der Nachname? Bitte sprechen Sie ihn langsam aus.",
            },
        ],
        "booking": {},
        "tools": [],
        "zuege": [],
    }
    hirn.init(sit)
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "",
        "frage": frage,
        "warSchonMal": True,
        "arzt": {
            "typ": "genannt",
            "calendarId": "blessing-cal",
            "calendarName": "Doktor Charlotte Blessing",
        },
        "grund": "Kontrolle",
        "grundWortlaut": "Kontrolle",
        "motivId": "blessing-motiv",
        "motivName": "Kontrolle",
        "wunsch": {},
        "vorname": "",
        "nachname": "",
        "buchstabiert": False,
    })
    if frage in {"vorname", "vorname_check"}:
        s.update({
            "nachname": "Muster",
            "buchstabiert": True,
            "vorname": "" if frage == "vorname" else "Manuela",
            "vornameQuelle": "" if frage == "vorname" else "akte",
            "vornameCheck": "",
        })
    return sit


def _kein_llm(*_args, **_kwargs):
    raise AssertionError("Eine offene Namensfrage darf kein LLM brauchen")


def test_blessing_namensschutz_ist_explizit_und_mandantenscharf():
    assert laden("blessing")["namensUnklarOhneEcho"] is True
    assert laden("blessing")["buchstabierSegmenteTrennen"] is True
    assert "namensUnklarOhneEcho" not in laden("meddent")
    assert "buchstabierSegmenteTrennen" not in laden("meddent")
    assert "namensUnklarOhneEcho" not in laden("thaler")
    assert "buchstabierSegmenteTrennen" not in laden("thaler")
    assert "namensUnklarOhneEcho" not in laden("ruether")
    assert "buchstabierSegmenteTrennen" not in laden("ruether")
    # Live kommt Blessing aus der Cloud Function und wird auf die lokale
    # Fachbasis gemerged. Der Opt-in muss auch auf genau diesem Weg ankommen.
    live_tenant = agentprofil.tenant_von_pre({
        "enabled": True,
        "clientId": "UUJnPzoYPa4yYyzcaGlm",
        "locationId": "blessing-location",
        "agent": {
            "clientId": "UUJnPzoYPa4yYyzcaGlm",
            "locationId": "blessing-location",
            "firstMessage": "Hautarztpraxis Doktor Blessing.",
        },
    }, did="+4921154244120")
    assert live_tenant and live_tenant["namensUnklarOhneEcho"] is True
    assert live_tenant["buchstabierSegmenteTrennen"] is True


def test_blessing_aqu_bleibt_bei_der_namensfrage_statt_unklar_doppelsatz(
    monkeypatch,
):
    """Live-Klasse 1bbc12fe: „Aqu.“ nach „Wie lautet der Nachname?“."""
    sit = _sit()
    monkeypatch.setenv("INTENT_NACHZUG", "0")
    monkeypatch.setattr(agent.flow.hintergrund, "anstossen", lambda _sit: None)
    monkeypatch.setattr(agent.llm, "chat", _kein_llm)
    monkeypatch.setattr(agent.llm, "chat_stream", _kein_llm)

    aus = agent.user_turn(sit, "Aqu.")

    assert "Nachnamen" in aus["text"]
    assert "Aqu" not in aus["text"], "unsicheren STT-Text nicht zurückspiegeln"
    assert "Was meinen Sie damit" not in aus["text"]
    assert "Meinen Sie vielleicht etwas anderes" not in aus["text"]
    assert sit["sammler"]["frage"] == "buchstabieren"
    assert not sit.get("unklarFolge")


@pytest.mark.parametrize(
    ("frage", "erwartet"),
    [
        ("name", "Namen"),
        ("nachname", "Nachnamen"),
        ("buchstabieren", "Nachnamen"),
        ("nachname_korr", "Nachnamen"),
        ("vorname", "Vornamen"),
        ("vorname_check", "Vorname"),
    ],
)
def test_blessing_alle_namensfragen_fallen_ohne_echo_zurueck(
    monkeypatch, frage, erwartet,
):
    sit = _sit(frage=frage)
    monkeypatch.setenv("INTENT_SCHICHT", "0")
    monkeypatch.setenv("INTENT_NACHZUG", "0")
    monkeypatch.setattr(agent.tasks, "zug", lambda *_a, **_k: None)
    monkeypatch.setattr(agent.llm, "chat", _kein_llm)
    monkeypatch.setattr(agent.llm, "chat_stream", _kein_llm)

    aus = agent.user_turn(sit, "What?")

    assert erwartet in aus["text"]
    assert "What" not in aus["text"]
    assert "Was meinen Sie damit" not in aus["text"]


def test_meddent_unklar_verhalten_bleibt_byte_identisch(monkeypatch):
    """Gegenprobe: ohne Tenant-Schalter bleibt der bisherige Doppelsatz."""
    sit = _sit("meddent")
    monkeypatch.setenv("INTENT_NACHZUG", "0")
    monkeypatch.setattr(agent.flow.hintergrund, "anstossen", lambda _sit: None)

    aus = agent.user_turn(sit, "Aqu.")

    assert "Aqu" in aus["text"]
    assert "Was meinen Sie damit?" in aus["text"]
    assert "Meinen Sie vielleicht etwas anderes?" in aus["text"]


def test_blessing_gueltiger_nachname_wird_weiter_normal_geerntet(monkeypatch):
    sit = _sit()
    monkeypatch.setenv("INTENT_NACHZUG", "0")
    monkeypatch.setattr(agent.flow.hintergrund, "anstossen", lambda _sit: None)

    aus = agent.user_turn(sit, "Mülhausen.")

    assert sit["sammler"]["nachname"] == "Mülhausen"
    assert "Vorname" in aus["text"]
    assert "Was meinen Sie damit" not in aus["text"]


@pytest.mark.parametrize(
    ("gesagt", "erwartet"),
    [
        # Anruf a97bc81a: „C wie Cäsar“ kam im Haupt-Ohr als B/V-C-S-A an.
        ("L-O-U-R-E-N-C-B-C-S-A-O.", "Lourenco"),
        ("Lorenzo, L-O-U, R-EN-C-O.", "Lourenco"),
        # „neues Wort“ ist eine Wortgrenze und darf nicht verschwinden.
        (
            "Diogo D-I-O-G-O, neues Wort, L-O-U-R-E-N-C-O.",
            "Diogo Lourenco",
        ),
        (
            "D-E, neues Wort S-O-U-S-A, neues Wort B-O-T-E-L-H-O, "
            "neues Wort L-O-U-R-E-N-C-V-C-S-A-O.",
            "De Sousa Botelho Lourenco",
        ),
        # Anruf c7470b98: Das Zweit-Ohr hörte „Hallwachs. Tamia. T-A-M-I-A“.
        # Gefragt war der Nachname der Anruferin; der Kindesname gehört nicht
        # an die erste vollständige Buchstabierkette.
        ("H-A-L-L-W-A-C-H-S, T-Mia, T-A-M-I-A.", "Hallwachs"),
    ],
)
def test_blessing_live_buchstabierketten_bleiben_beim_richtigen_feld(
    gesagt, erwartet,
):
    sit = _sit(frage="nachname")

    neu = gehirn.einsammeln(sit, gesagt)

    assert "nachname" in neu
    assert sit["sammler"]["nachname"] == erwartet
    assert sit["sammler"]["buchstabiert"] is True


def test_blessing_schlusswort_fertig_wird_nie_teil_des_nachnamens():
    """Live-Klasse Gavranides: „Granedis fertig“ ist Name plus Diktat-Ende."""
    sit = _sit(frage="buchstabieren")

    neu = gehirn.einsammeln(sit, "Gavranides, fertig.")

    assert "nachname" in neu
    assert sit["sammler"]["nachname"] == "Gavranides"
    assert "fertig" not in sit["sammler"]["nachname"].lower()


def test_standard_parser_und_meddent_bleiben_byte_identisch():
    """Ohne Blessing-Opt-in bleibt die bestehende Parser-Wirkung unverändert."""
    live = "H-A-L-L-W-A-C-H-S, T-Mia, T-A-M-I-A."
    assert buchstaben.deute(live) == {
        "name": "Hallwachstmiatamia",
        "sicher": False,
    }
    sit = _sit("meddent", frage="nachname")

    gehirn.einsammeln(sit, live)

    assert sit["sammler"]["nachname"] == "Hallwachstmiatamia"
