"""Blessing spricht aufgabenbezogen und knapp — heutige Live-Regressionsfälle."""

from __future__ import annotations

import copy

import pytest

from bianca import agent, flow, gehirn, session, verwalten, weiterleiten
from kern import gespraech, hirn, stille
from kern.tenants import laden


KOMPAKT_FLAGS = {
    "gespraechKompakt",
    "halloKompakt",
    "anmeldungKurz",
    "terminNotizNachBuchung",
    "buchungAbschlussKompakt",
    "selbstCheckNurBeiSignal",
    "sonstNochNurNachErfolg",
    "presenceEinmal",
}


def _sit(*, tenant_id: str = "blessing", modus: str = "") -> dict:
    sit = session.neu(tenant=laden(tenant_id))
    agent.start_reply(sit)
    if modus:
        hirn.anliegen_hinzufuegen(
            sit,
            hirn._anliegen("ANLEGEN", "VORGANG", spiegel="Termin vereinbaren"),
            aktivieren=True,
        )
        gehirn.sammler(sit)["modus"] = modus
    return sit


@pytest.fixture(autouse=True)
def _ohne_nachzug(monkeypatch):
    monkeypatch.setenv("INTENT_NACHZUG", "0")


def test_knapp_schalter_sind_ausschliesslich_bei_blessing_aktiv():
    blessing = laden("blessing")
    assert all(blessing.get(flag) is True for flag in KOMPAKT_FLAGS)
    for tenant_id in ("meddent", "thaler", "ruether"):
        tenant = laden(tenant_id)
        assert not any(tenant.get(flag) is True for flag in KOMPAKT_FLAGS)


@pytest.mark.parametrize(
    "gesagt",
    [
        "habt",
        "Die Bitte.",
        "Ja, richtig.",
        "Wie bitte?",
    ],
)
def test_live_unklar_schnipsel_bekommen_genau_eine_kurze_jobfrage(
    gesagt,
    monkeypatch,
):
    sit = _sit()
    monkeypatch.setattr(
        agent.llm,
        "chat",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Blessing-STT-Schnipsel darf nicht ans freie LLM")
        ),
    )
    monkeypatch.setattr(
        agent.llm,
        "chat_stream",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Blessing-STT-Schnipsel darf nicht ans freie LLM")
        ),
    )

    aus = agent.user_turn(sit, gesagt)
    text = aus["text"]

    assert text.count("?") == 1
    assert len(text) < 130
    assert "Was meinen Sie damit" not in text
    assert "Meinen Sie vielleicht" not in text
    assert gesagt.strip(" .?!").casefold() not in text.casefold()


def test_fachwort_statt_unklar_fragt_gezielt_nach_termin(monkeypatch):
    sit = _sit()
    monkeypatch.setattr(
        agent.llm,
        "chat",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Rosacea muss deterministisch bleiben")
        ),
    )

    aus = agent.user_turn(sit, "Rosacea, Weiterbehandlung.")

    assert "termin" in aus["text"].casefold()
    assert "nicht verstanden" not in aus["text"].casefold()
    assert "was meinen sie damit" not in aus["text"].casefold()


def test_hallo_hat_weder_neue_noch_wohlseinsfrage():
    sit = _sit()
    sit["anrufer"] = {
        "vorname": "Anna",
        "nachname": "Muster",
        "geschlecht": "female",
        "telefon": "+491701234567",
    }
    sit["vorigesGespraech"] = {"wann": "gestern"}

    hallo = gehirn.anrufer_hallo(sit)
    assert hallo == "Guten Tag, Frau Muster."
    assert "neue" not in hallo.casefold()
    assert "wie geht es" not in hallo.casefold()
    assert gehirn.anrufer_hallo_jetzt(sit, "Ich brauche einen Termin.") == hallo


def test_reines_hallo_fuehrt_direkt_zur_jobfrage_statt_zum_eisbrecher(monkeypatch):
    sit = _sit()
    monkeypatch.setattr(
        agent.llm,
        "chat",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Blessing-Hallo braucht kein LLM")
        ),
    )

    aus = agent.user_turn(sit, "Hallo.")

    assert "neue" not in aus["text"].casefold()
    assert "wie geht es" not in aus["text"].casefold()
    assert aus["text"].count("?") == 1


def test_bekannter_anrufer_ueberspringt_fuer_wen_ohne_drittsignal():
    sit = _sit(modus="buchen")
    s = gehirn.sammler(sit)
    s.update({
        "anruferCheck": "ja",
        "fuerWenCheck": "",
        "fuerWen": "",
        "warSchonMal": None,
        "frage": "anrufer_check",
    })

    fid, frage = gehirn.naechste_frage(sit)

    assert fid == "schonmal"
    assert "selbst" not in frage.casefold()
    assert s["fuerWenCheck"] == "ja"


def test_ein_arzt_wird_gesetzt_ohne_behandlerfrage():
    sit = _sit(modus="buchen")
    s = gehirn.sammler(sit)
    s.update({"warSchonMal": True, "arzt": None})

    fid, frage = gehirn.naechste_frage(sit)

    assert fid == "buchstabieren"
    assert "behandler" not in frage.casefold()
    assert s["arzt"]["calendarId"] == "8krcWh7AuXEfgWc1blzQ"


def test_mensch_wunsch_bekommt_einen_kurzen_satz():
    sit = _sit()

    aus = weiterleiten.zug(sit, "Ich möchte mit einem Menschen sprechen.")
    text = aus["text"]

    assert text.count("?") == 1
    assert len(text.split()) <= 22
    assert "medizinische Versorgung" not in text
    assert "verbessere mich" not in text


def test_doktor_nachricht_bleibt_ein_eigener_kurzer_schritt(monkeypatch):
    sit = _sit(modus="buchen")
    s = gehirn.sammler(sit)
    s.update({"pzr": "nein", "arztNotizFrage": "", "frage": "bestaetigung"})
    monkeypatch.setattr(gehirn, "pzr_noch_fragen", lambda *a, **k: False)
    monkeypatch.setattr(
        flow,
        "_buchen",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Nachricht muss vor dem Buchen geklärt werden")
        ),
    )

    aus = flow._nach_ok_buchen(sit, "Ja.")

    assert aus["text"].count("?") == 1
    assert "Ärztin" in aus["text"]
    assert "Vorbereitung" in aus["text"]
    assert s["arztNotizFrage"] == "gefragt"
    assert s["frage"] == "arzt_notiz"


def test_freies_llm_geschwaetz_wird_durch_jobfrage_ersetzt(monkeypatch):
    sit = _sit()
    monkeypatch.setattr(
        agent.llm,
        "chat",
        lambda *a, **k: {
            "ok": True,
            "text": (
                "Das klingt wirklich sehr interessant, und ich kann gut "
                "verstehen, dass Sie darüber ausführlich sprechen möchten."
            ),
            "tool_calls": [],
        },
    )

    aus = agent.user_turn(sit, "Das ist ja eine interessante Geschichte.")

    assert aus["text"].count("?") == 1
    assert "interessant" not in aus["text"].casefold()
    assert "termin" in aus["text"].casefold()


def _angebot_sit() -> dict:
    sit = _sit(modus="buchen")
    sit["anrufer"] = {
        "vorname": "Anna",
        "nachname": "Muster",
        "telefon": "+491701234567",
    }
    s = gehirn.sammler(sit)
    s.update({
        "warSchonMal": True,
        "arzt": {
            "typ": "einzig",
            "calendarId": "8krcWh7AuXEfgWc1blzQ",
            "calendarName": "Doktor Charlotte Blessing",
        },
        "grund": "Kontrolle",
        "grundWortlaut": "Kontrolle",
        "motivId": "UnfQ5DOaMx9FLiTC3L9b",
        "motivName": "Kontrolle",
        "vorname": "Anna",
        "nachname": "Muster",
        "buchstabiert": True,
        "versicherung": "gesetzlich",
        "wunsch": {
            "weekday": None,
            "hourMin": None,
            "hourMax": None,
            "hour": None,
            "minDaysAhead": 0,
            "date": None,
            "tage": None,
            "von": None,
            "bis": None,
        },
    })
    return sit


def test_rueckrufnotiz_endet_ohne_sonst_noch_schleife(tmp_path, monkeypatch):
    sit = _angebot_sit()
    monkeypatch.setattr(verwalten, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        flow.kal,
        "_find_slots_seite",
        lambda *a, **k: {"ok": True, "slots": [], "dispatch": {}},
    )
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda *a, **k: None)

    aus = flow._angebot(sit)

    assert "praxis meldet sich" in aus["text"].casefold()
    assert "sonst noch" not in aus["text"].casefold()
    assert aus.get("hangup") is True
    assert gehirn.sammler(sit)["frage"] == ""


def test_presence_einmal_dann_jobfrage_dann_sauber_auflegen():
    sit = _sit(modus="buchen")
    gehirn.sammler(sit)["frage"] = ""
    sit["flussFrage"] = "Wie lautet Ihr Nachname?"

    eins = agent.stille_zug(sit)
    zwei = agent.stille_zug(sit)
    stille.reset(sit)
    drei = agent.stille_zug(sit)

    assert "Sind Sie noch dran" in eins["text"]
    assert "noch da" not in zwei["text"]
    assert "Nachname" in zwei["text"]
    assert "Auf Wiederhören" in drei["text"]
    assert drei.get("hangup") is True


def test_meddent_bleibt_bei_altem_hallo_sermon_und_notizfrage(monkeypatch):
    sit = _sit(tenant_id="meddent")
    sit["anrufer"] = {
        "vorname": "Michael",
        "nachname": "Petsas",
        "geschlecht": "male",
        "telefon": "+491701234567",
    }
    assert "Ich bin die Neue!" in gehirn.anrufer_hallo(sit)
    assert (
        weiterleiten.zug(sit, "Ich möchte mit einem Menschen sprechen.")["text"]
        == weiterleiten.ENTLASTUNG
    )

    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "pzr": "nein", "arztNotizFrage": ""})
    monkeypatch.setattr(gehirn, "pzr_noch_fragen", lambda *a, **k: False)
    aus = flow._nach_ok_buchen(sit, "Ja.")
    assert "Notiz für den Doktor" in aus["text"]


def test_flag_entfernen_stellt_altes_hallo_byte_identisch_her():
    tenant = copy.deepcopy(laden("blessing"))
    tenant.pop("halloKompakt")
    sit = session.neu(tenant=tenant)
    sit["halloVariante"] = 0

    assert gehirn.anrufer_hallo(sit) == gehirn.HALLO_NEU[0]
