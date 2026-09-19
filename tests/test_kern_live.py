"""Dialogkern am Telefon (enforce, 19.09.2026).

Bis hierhin lief der Kern nur im Schatten: er entschied mit, gesprochen hat
der Legacy-Fluss. Dieser Test nagelt den Schalter fest — und vor allem die
Gegenproben, die teurer sind als ein verpasster Kern-Zug:

* OHNE ``CONTROLLER_ENFORCE`` darf sich NICHTS bewegen (jede Praxis laeuft
  byte-identisch weiter wie vor dem 19.09.2026).
* Ein Kern-Fehler darf nie einen stummen Anruf erzeugen — der Legacy-Pfad
  uebernimmt im selben Zug.
* Fuehrt der Kern die Aufgabe nicht, muessen die schon geernteten Angaben im
  Legacy-Sammler stehen: niemand buchstabiert seinen Namen zweimal.

Laeuft ohne Netz, ohne Modell, ohne Kalender (das Gateway wird gestubbt).
"""

from __future__ import annotations

import pytest

from bianca import agent
from bianca.controller import live
from bianca.controller.typen import Naechste, Phase, Quelle, SlotValue, TaskState
from kern.tenants import laden


def _sit(**extra) -> dict:
    sit = {
        "id": "t-kern-live",
        "stimme": "Bianca",
        "tenant": laden("meddent"),
        "messages": [
            {"role": "system", "content": "x"},
            {"role": "assistant", "content": "Guten Tag, hier ist Bianca."},
        ],
    }
    sit.update(extra)
    return sit


# --------------------------------------------------------------------------- #
# Schalter
# --------------------------------------------------------------------------- #
def test_ohne_schalter_ist_der_kern_stumm(monkeypatch):
    monkeypatch.delenv("CONTROLLER_ENFORCE", raising=False)
    assert live.an(_sit()) is False


def test_schalter_aus_werten(monkeypatch):
    for aus in ("0", "off", "aus", "nein", ""):
        monkeypatch.setenv("CONTROLLER_ENFORCE", aus)
        assert live.an(_sit()) is False, aus


def test_schalter_alle(monkeypatch):
    monkeypatch.setenv("CONTROLLER_ENFORCE", "1")
    assert live.an(_sit()) is True


def test_schalter_nur_eine_testnummer(monkeypatch):
    """Genau EINE Nummer hoert den Kern, jeder Patient den bewaehrten Weg."""
    monkeypatch.setenv("CONTROLLER_ENFORCE", "+491776004600")
    assert live.an(_sit(caller="+491776004600")) is True
    # Dieselbe Nummer in nationaler Schreibweise zaehlt auch.
    assert live.an(_sit(caller="01776004600")) is True
    # Ein anderer Anrufer nicht.
    assert live.an(_sit(caller="+4921154244101")) is False
    assert live.an(_sit()) is False


def test_schalter_mandant(monkeypatch):
    monkeypatch.setenv("CONTROLLER_ENFORCE", "meddent")
    assert live.an(_sit()) is True
    fremd = _sit()
    fremd["tenant"] = laden("blessing")
    assert live.an(fremd) is False


# --------------------------------------------------------------------------- #
# Der Zug
# --------------------------------------------------------------------------- #
class _FakeZa:
    def __init__(self, antwort="", *, uebergeben=False, hangup=False,
                 naechste="fragen", grund="", tool=""):
        self.antwort = antwort
        self.uebergeben = uebergeben
        self.hangup = hangup
        self.naechste = naechste
        self.grund = grund
        self.tool = tool


class _FakeLauf:
    """Minimaler Stand-in fuer TestGespraech (kein Kalender, kein Modell)."""

    def __init__(self, za):
        self._za = za
        self._erw = type("E", (), {"offene_frage": "", "janein": False, "wahl": False})()
        self.state = type("S", (), {"aktiv": staticmethod(lambda: None)})()

    def eingabe(self, text):
        return self._za

    def stille(self):
        return self._za


def test_kern_spricht(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTROLLER_ENFORCE", "1")
    monkeypatch.setenv("CONTROLLER_LIVE_DIR", str(tmp_path))
    monkeypatch.setattr(live, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(
        live, "lauf",
        lambda sit: _FakeLauf(_FakeZa("Waren Sie schon einmal bei uns?")),
    )
    aus = live.zug(_sit(), "Ich brauche einen Termin.")
    assert aus is not None
    assert aus["text"] == "Waren Sie schon einmal bei uns?"
    assert "hangup" not in aus


def test_uebergabe_gibt_none_und_spiegelt_die_angaben(monkeypatch, tmp_path):
    """Legacy uebernimmt im selben Zug — mit allem, was der Kern schon weiss."""
    monkeypatch.setenv("CONTROLLER_ENFORCE", "1")
    monkeypatch.setattr(live, "_LOG_DIR", tmp_path)

    task = TaskState(typ="buchen", phase=Phase.SAMMELN)
    task.slots["nachname"] = SlotValue(wert="Petsas", quelle=Quelle.GESAGT)
    task.slots["telefon"] = SlotValue(wert="01776004600", quelle=Quelle.GESAGT)

    class _Lauf(_FakeLauf):
        def __init__(self):
            super().__init__(_FakeZa("", uebergeben=True,
                                     naechste=Naechste.UEBERGEBEN.value))
            self.state = type("S", (), {"aktiv": staticmethod(lambda: task)})()

    monkeypatch.setattr(live, "lauf", lambda sit: _Lauf())
    sit = _sit()
    assert live.zug(sit, "Ich brauche ein Rezept.") is None
    assert sit["sammler"]["nachname"] == "Petsas"
    assert sit["sammler"]["telefon"] == "01776004600"
    assert sit["sammler"]["modus"] == "buchen"


def test_kern_fehler_uebergibt_statt_zu_schweigen(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTROLLER_ENFORCE", "1")
    monkeypatch.setattr(live, "_LOG_DIR", tmp_path)

    def _platzt(sit):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(live, "lauf", _platzt)
    assert live.zug(_sit(), "Hallo?") is None


def test_stummer_kern_zug_uebergibt(monkeypatch, tmp_path):
    """Kein Satz und keine Uebergabe darf nie ein stummer Anruf werden."""
    monkeypatch.setenv("CONTROLLER_ENFORCE", "1")
    monkeypatch.setattr(live, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(live, "lauf",
                        lambda sit: _FakeLauf(_FakeZa("", naechste="fragen")))
    assert live.zug(_sit(), "Hallo?") is None


def test_warten_bleibt_still_ohne_uebergabe(monkeypatch, tmp_path):
    """Diktat-Fragment: Zustand fortgeschrieben, Anrufer spricht weiter."""
    monkeypatch.setenv("CONTROLLER_ENFORCE", "1")
    monkeypatch.setattr(live, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(
        live, "lauf",
        lambda sit: _FakeLauf(_FakeZa("", naechste=Naechste.WARTEN.value)),
    )
    aus = live.zug(_sit(), "P wie Paula")
    assert aus == {"text": "", "book": None, "warte": True, "stilleMs": 1500}


def test_auflegen_wird_durchgereicht(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTROLLER_ENFORCE", "1")
    monkeypatch.setattr(live, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(
        live, "lauf",
        lambda sit: _FakeLauf(_FakeZa("Auf Wiederhören.", hangup=True,
                                      naechste=Naechste.AUFLEGEN.value)),
    )
    aus = live.zug(_sit(), "Tschüss.")
    assert aus["hangup"] is True


# --------------------------------------------------------------------------- #
# Ruhe-Schwelle
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("frage,wahl,janein,soll", [
    ("nachname", False, False, 1500),
    ("telefon", False, False, 1500),
    ("schonmal", False, True, 350),
    ("", True, False, 350),
    ("", False, False, 500),
])
def test_stille_ms_nach_fragetyp(frage, wahl, janein, soll):
    assert live._stille_ms(frage, wahl, janein) == soll


# --------------------------------------------------------------------------- #
# Einbau in user_turn
# --------------------------------------------------------------------------- #
def test_user_turn_laesst_den_kern_sprechen(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTROLLER_ENFORCE", "1")
    monkeypatch.setattr(live, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(
        live, "lauf",
        lambda sit: _FakeLauf(_FakeZa("Waren Sie schon einmal bei uns?")),
    )

    def _kein_llm(*a, **k):  # ein Kern-Zug darf das Modell nie brauchen
        raise AssertionError("LLM lief trotz Kern-Antwort")

    monkeypatch.setattr(agent, "_llm_antwort", _kein_llm, raising=False)
    sit = _sit()
    aus = agent.user_turn(sit, "Ich bräuchte einen Termin.")
    assert aus["text"] == "Waren Sie schon einmal bei uns?"
    assert live.uebernimmt(sit) is True


def test_user_turn_ohne_schalter_geht_den_alten_weg(monkeypatch):
    """Gegenprobe: ohne Schalter wird lauf() nie angefasst."""
    monkeypatch.delenv("CONTROLLER_ENFORCE", raising=False)

    def _nie(sit):
        raise AssertionError("Kern lief ohne Schalter")

    monkeypatch.setattr(live, "lauf", _nie)
    sit = _sit()
    aus = agent.user_turn(sit, "Ich bräuchte einen Termin.")
    assert aus is not None  # der bewaehrte Weg hat geantwortet
