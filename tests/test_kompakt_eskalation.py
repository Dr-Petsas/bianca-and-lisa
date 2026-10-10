"""W-KOMPAKT-ESKALATION: Blessing stellt dieselbe Frage nicht endlos.

Live 3be31043 (Behandlerfrage zehnmal), 5ebb53b8 („Es ist sogar nicht
wichtig.“ -> wieder die Behandlerfrage), 92e777c3 (Fragen auf die
Handynummer-Frage -> leere Antworten). Die Kurzform zählt Fehlversuche und
lässt die bewährte Eskalation greifen; echte Zwischenfragen werden
beantwortet, danach kommt die offene Frage.
"""

from __future__ import annotations

import copy

import pytest

from bianca import agent, gehirn, session
from kern import hirn
from kern.tenants import laden

ZWEITER = {"id": "zweiterKalender01", "name": "Doktor Ralf Hartmann"}


def _tenant(tenant_id: str = "blessing", zwei: bool = True) -> dict:
    t = copy.deepcopy(laden(tenant_id))
    if zwei and tenant_id == "blessing":
        t["calendars"] = list(t.get("calendars") or []) + [dict(ZWEITER)]
    return t


def _sit(tenant_id: str = "blessing", *, frage: str = "arzt") -> dict:
    sit = session.neu(tenant=_tenant(tenant_id))
    agent.start_reply(sit)
    hirn.anliegen_hinzufuegen(
        sit,
        hirn._anliegen("ANLEGEN", "VORGANG", spiegel="Termin vereinbaren"),
        aktivieren=True,
    )
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["warSchonMal"] = False
    s["grund"] = "Kontrolle"
    s["frage"] = frage
    return sit


def _sit_behandlerfrage_gestellt(tenant_id: str = "blessing") -> dict:
    """Die Maschine stellt die Behandlerfrage selbst (wie live)."""
    sit = _sit(tenant_id, frage="schonmal")
    gehirn.sammler(sit)["warSchonMal"] = None
    aus = agent.user_turn(sit, "Nein, ich war noch nie bei Ihnen.")
    assert gehirn.sammler(sit)["frage"] == "arzt", aus
    return sit


def _llm(monkeypatch, text: str = "Sie suchen sich einfach eine unserer Ärztinnen aus."):
    aufrufe = []

    def chat(*a, **k):
        aufrufe.append(1)
        return {"ok": True, "text": text, "tool_calls": []}

    monkeypatch.setattr(agent.llm, "chat", chat)
    monkeypatch.setattr(agent.llm, "chat_stream", lambda *a, **k: chat())
    return aufrufe


@pytest.fixture(autouse=True)
def _umgebung(monkeypatch):
    monkeypatch.setenv("INTENT_NACHZUG", "0")
    monkeypatch.delenv("KOMPAKT_ESKALATION", raising=False)


# --- „nicht wichtig“ auf die Behandlerfrage ---------------------------------

@pytest.mark.parametrize("gesagt", [
    "Es ist sogar nicht wichtig.",   # 5ebb53b8 wortgleich
    "Unwichtig.",
    "Nicht so wichtig.",
])
def test_nicht_wichtig_auf_behandlerfrage_nimmt_standard_behandler(gesagt):
    sit = _sit()
    gehirn.einsammeln(sit, gesagt)
    arzt = gehirn.sammler(sit)["arzt"] or {}
    assert arzt.get("calendarId") == sit["tenant"]["defaultCalendarId"]


def test_5ebb53b8_nicht_wichtig_im_gespraech_fragt_nicht_erneut(monkeypatch):
    _llm(monkeypatch)
    sit = _sit_behandlerfrage_gestellt()
    aus = agent.user_turn(sit, "Es ist sogar nicht wichtig.")
    assert "Zu welchem unserer Behandler" not in aus["text"]
    assert gehirn.sammler(sit)["frage"] != "arzt"


def test_nicht_unwichtig_ist_kein_egal():
    sit = _sit()
    gehirn.einsammeln(sit, "Das ist mir nicht unwichtig.")
    assert not (gehirn.sammler(sit)["arzt"] or {}).get("calendarId")


def test_nicht_wichtig_ohne_offene_behandlerfrage_setzt_keinen_arzt():
    sit = _sit(frage="wunsch")
    gehirn.einsammeln(sit, "Es ist sogar nicht wichtig.")
    assert not (gehirn.sammler(sit)["arzt"] or {}).get("calendarId")


def test_echter_behandlername_gewinnt_weiter():
    sit = _sit()
    gehirn.einsammeln(sit, "Zu Doktor Hartmann bitte.")
    assert (gehirn.sammler(sit)["arzt"] or {}).get("calendarId") == ZWEITER["id"]


# --- Fehlversuche zählen, Eskalation greift --------------------------------

def test_3be31043_zweite_zwischenfrage_eskaliert_statt_zehnmal_zu_fragen(monkeypatch):
    _llm(monkeypatch)
    sit = _sit_behandlerfrage_gestellt()
    erste = agent.user_turn(sit, "Was muss ich tun?")
    assert "Doktor Hartmann?" in erste["text"]
    zweite = agent.user_turn(sit, "Wann, was meinen Sie jetzt?")
    s = gehirn.sammler(sit)
    assert (s["arzt"] or {}).get("calendarId") == sit["tenant"]["defaultCalendarId"]
    assert s.get("frage") != "arzt"
    assert "Ich schaue bei Doktor Blessing" in zweite["text"]
    assert "Zu welchem unserer Behandler" not in zweite["text"]


def test_zwischenfrage_bekommt_antwort_und_danach_die_offene_frage(monkeypatch):
    aufrufe = _llm(monkeypatch, "Sie suchen sich einfach eine unserer Ärztinnen aus.")
    sit = _sit_behandlerfrage_gestellt()
    aus = agent.user_turn(sit, "Was muss ich tun?")
    text = aus["text"]
    assert aufrufe, "die Frage des Anrufers muss das Modell beantworten"
    assert "Ärztinnen aus" in text
    assert text.rstrip().endswith("?")
    assert text.count("?") == 1


def test_notaus_stellt_alte_kurzform_wieder_her(monkeypatch):
    monkeypatch.setenv("KOMPAKT_ESKALATION", "0")
    _llm(monkeypatch, "Sie suchen sich einfach eine unserer Ärztinnen aus.")
    sit = _sit_behandlerfrage_gestellt()
    aus = agent.user_turn(sit, "Was muss ich tun?")
    assert "Ärztinnen aus" not in aus["text"]
    agent.user_turn(sit, "Wann, was meinen Sie jetzt?")
    assert not (gehirn.sammler(sit)["arzt"] or {}).get("calendarId")


# --- 92e777c3: Fragen auf die Nummernfrage sind kein Diktat ----------------

@pytest.mark.parametrize("gesagt", [
    "Oh, ich habe Ihnen eben eine Nummer genannt, ist die nicht ausreichend?",
    "Brauchen Sie eine E-Mail-Nummer?",
])
def test_92e777c3_frage_auf_nummernfrage_wird_kein_teilstueck(gesagt):
    sit = _sit(frage="telefon")
    gehirn.einsammeln(sit, gesagt)
    assert not gehirn.sammler(sit).get("telefonTeil")


def test_gesprochene_ziffern_mit_fragezeichen_bleiben_teilstueck():
    sit = _sit(frage="telefon")
    gehirn.einsammeln(sit, "null eins fünf sieben?")
    assert gehirn.sammler(sit).get("telefonTeil") == "0157"


# --- Gegenproben: andere Praxen unverändert ---------------------------------

@pytest.mark.parametrize("tenant_id", ["meddent", "thaler", "ruether"])
def test_andere_praxen_haben_keine_kompakt_eskalation(tenant_id, monkeypatch):
    from bianca import flow
    sit = _sit(tenant_id)
    sit["_flowLeerFid"] = "arzt"
    assert agent._kompakt_leerlauf(sit, "Was muss ich tun?", None, []) is None
    assert flow.kompakt_eskalation_an()
