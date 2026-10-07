"""W-MENUE-DECKEL (07.10.2026): die Blessing-Menüfrage ersetzt keinen klaren Satz.

Live 06.10.2026 (Blessing): „Geht es um einen Termin, eine Absage, eine
Verschiebung oder eine Terminauskunft?“ kam 132-mal in 59 Anrufen — auch auf
„Ich benötige einen Termin.“ (1a6f08af), „Termin für Fusspflege.“
(7fbed2d9), „Nein, den Termin, ich brauche einen neuen Termin.“ (4cd6db61)
und viermal auf „Es geht um das Ergebnis der Operation“ (f6b0d63c).
"""

import pytest

from bianca import agent, flow, gehirn, session
from kern import gespraech, hirn
from kern.tenants import laden


def _sit(tenant_id: str = "blessing") -> dict:
    sit = session.neu(tenant=laden(tenant_id))
    agent.start_reply(sit)
    return sit


def _llm_plaudert(monkeypatch, text: str = "Ach, das klingt gut.") -> list:
    aufrufe: list = []

    def antwort(*_a, **_k):
        aufrufe.append(1)
        return {"ok": True, "text": text, "tool_calls": []}

    monkeypatch.setattr(agent.llm, "chat", antwort)
    monkeypatch.setattr(agent.llm, "chat_stream", antwort)
    return aufrufe


@pytest.fixture(autouse=True)
def _ohne_netz(monkeypatch):
    monkeypatch.setenv("INTENT_NACHZUG", "0")
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)


# --- Erkennung -------------------------------------------------------------

@pytest.mark.parametrize("satz, op", [
    ("Ich benötige einen Termin.", "buchen"),
    ("Termin für Fusspflege.", "buchen"),
    ("Nein, den Termin, ich brauche einen neuen Termin.", "buchen"),
    ("Ich möchte einen Termin, ich habe Schmerzen.", "buchen"),
    ("Ich habe gern einen Termin.", "buchen"),
    ("Ich möchte einen Termin verschieben.", "verschieben"),
    ("Es geht um eine Verschiebung.", "verschieben"),
    ("Den muss ich leider absagen, weil ich, ja.", "absagen"),
    ("Wann ist denn mein Termin?", "terminauskunft"),
    ("Es geht um das Ergebnis der Operation.", "rueckruf"),
])
def test_klarer_satz_hat_genau_eine_operation(satz, op):
    assert agent._menue_klar(satz) == op


@pytest.mark.parametrize("satz", [
    "Ich habe einen Termin bei Ihnen.",            # Bestand ohne Wunsch: Menü
    "Ja, ein Termin.",
    "Hm, äh.",
    "Ich möchte absagen oder verschieben.",       # zwei Familien: nie raten
    "Es geht nicht um eine Absage.",               # Verneinung
    "Haben Sie einen E-Mail-Kontakt?",
    "Ich brauche einen Termin für die Befundbesprechung.",  # Termin, kein Rückruf
])
def test_unklarer_satz_bleibt_beim_menue(satz):
    op = agent._menue_klar(satz)
    assert op in {"", "buchen"}
    if "Befund" in satz:
        assert op == "buchen"
    else:
        assert op == ""


# --- Ende zu Ende ----------------------------------------------------------

@pytest.mark.parametrize("satz", [
    "Ich benötige einen Termin.",
    "Termin für Fusspflege.",
])
def test_live_terminwunsch_startet_die_buchung_statt_menue(satz, monkeypatch):
    _llm_plaudert(monkeypatch)
    sit = _sit()

    aus = agent.user_turn(sit, satz)

    assert gespraech.KOMPAKT_JOBFRAGE not in aus["text"]
    assert gehirn.sammler(sit)["modus"] == "buchen"
    assert any(e.get("operation") == "buchen" and e.get("quelle") == "menue_deckel"
               for e in sit.get("taskRouter") or [])


def test_live_verschieben_startet_die_verwaltung(monkeypatch):
    _llm_plaudert(monkeypatch)
    sit = _sit()

    aus = agent.user_turn(sit, "Ich möchte einen Termin verschieben.")

    assert gespraech.KOMPAKT_JOBFRAGE not in aus["text"]
    assert gehirn.sammler(sit)["modus"] == "verschieben"


def test_sachanliegen_wird_rueckruf_statt_menue(monkeypatch):
    _llm_plaudert(monkeypatch)
    sit = _sit()

    aus = agent.user_turn(sit, "Es geht um das Ergebnis der Operation.")

    assert gespraech.KOMPAKT_JOBFRAGE not in aus["text"]
    assert "Rückruf" in aus["text"]
    assert (sit.get("hirnAbgeben") or {}).get("offen") is True


def test_nach_zwei_menuefragen_kommt_keine_dritte(monkeypatch):
    _llm_plaudert(monkeypatch)
    sit = _sit()
    texte = [agent.user_turn(sit, s)["text"] for s in (
        "Haben Sie einen E-Mail-Kontakt?",
        "Und wie ist die Adresse von der Mail?",
        "Ich will das einfach nur wissen.",
    )]

    assert sum(gespraech.KOMPAKT_JOBFRAGE in t for t in texte) == 2
    assert gespraech.KOMPAKT_JOBFRAGE not in texte[2]
    assert "Rückruf" in texte[2]
    ab = sit.get("hirnAbgeben") or {}
    assert ab.get("offen") is True
    assert "nicht klar geworden" in ab.get("was", "")


def test_einmal_unklar_bleibt_genau_eine_menuefrage(monkeypatch):
    _llm_plaudert(monkeypatch)
    sit = _sit()

    aus = agent.user_turn(sit, "Haben Sie einen E-Mail-Kontakt?")

    assert gespraech.KOMPAKT_JOBFRAGE in aus["text"]
    assert sit["menueFrageN"] == 1


def test_notaus_stellt_alten_weg_her(monkeypatch):
    monkeypatch.setenv("MENUE_DECKEL", "0")
    _llm_plaudert(monkeypatch)
    sit = _sit()

    aus = agent.user_turn(sit, "Ich benötige einen Termin.")

    assert gespraech.KOMPAKT_JOBFRAGE in aus["text"]


@pytest.mark.parametrize("tenant_id", ["meddent", "thaler", "ruether"])
def test_andere_mandanten_beruehrt_der_deckel_nicht(tenant_id, monkeypatch):
    _llm_plaudert(monkeypatch, "Wie schön, dass Sie anrufen.")
    sit = _sit(tenant_id)

    agent.user_turn(sit, "Haben Sie einen E-Mail-Kontakt?")

    assert "menueFrageN" not in sit
    assert not any(e.get("quelle") == "menue_deckel"
                   for e in sit.get("taskRouter") or [])
