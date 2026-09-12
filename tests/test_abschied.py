"""W-ABSCHIED (12.09.2026): eindeutige Schlusssätze beenden den Anruf wirklich.

Chef 12.09.2026 (wörtlich): „Bianca soll lernen aufzulegen bei eindeutigen
sätzen die ein gespräch beenden wie thüss auf wieder höhren wiedersehen bis
denn etc."

Live-Befund Session 9395e2ce (11.09.2026): 109 Züge / 23 Minuten — der
Anrufer war längst fertig, bianca/flow sprach zwar „Auf Wiederhören", setzte
aber nie `hangup`; die Leitung blieb offen, bis der Anrufer selbst auflegte.

Offline: kein LLM, kein Netz. Ein LLM-Aufruf in diesen Tests ist ein
Testbruch — die Abschieds-Erkennung ist deterministisch.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bianca import agent as bianca_agent
from bianca import flow, gehirn
from kern import abschied, llm, stille


def _sit() -> dict:
    return {
        "tenant": {"praxisName": "Testpraxis", "mandantId": "meddent"},
        "messages": [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "Guten Tag."},
            {"role": "assistant", "content": "Guten Tag, was kann ich für Sie tun?"},
        ],
    }


def _kein_llm(monkeypatch) -> None:
    def platzt(*a, **k):
        raise AssertionError("Abschied muss ohne LLM entschieden werden")
    monkeypatch.setattr(llm, "chat", platzt)
    monkeypatch.setattr(llm, "chat_stream", platzt)


# ---------------------------------------------------------------------------
# Erkennung
# ---------------------------------------------------------------------------

def test_klare_schlusssaetze():
    for satz in (
        "Auf Wiederhören.",
        "Auf wiederhören!",
        # Live 12.09.2026: das Dock/STT liefert Umlaute teils als oe/ue —
        # „Auf Wiederhoeren!" rutschte durch und das Modell improvisierte
        # „Nein, bitte nicht auflegen!".
        "Auf Wiederhoeren!",
        "Ach wissen Sie was, ich melde mich spaeter nochmal. Auf Wiederhoeren!",
        "Okay, danke, tschuess.",
        "Auf Wiedersehen.",
        "Ja, dann auf Wiederhören.",
        "Okay, danke, tschüss.",
        "Tschüss!",
        "Tschüs.",
        "Tschüssi.",
        "Danke, tschau.",
        "Bis denn.",
        "Dann bis bald.",
        "Ciao.",
        "Schönen Tag noch.",
        "Alles Gute.",
        "Machen Sie es gut.",
    ):
        assert abschied.ist_abschied(satz), satz


def test_kein_abschied_bei_echtem_anliegen():
    for satz in (
        "Ich möchte den Termin verschieben, tschüss soll ich noch sagen?",
        "Bis wann haben Sie denn heute geöffnet?",
        "Kann ich bis Donnerstag warten?",
        "Danke.",
        "Nein, danke.",
        "Ja, gut.",
        "Meine Nummer ist null eins sieben sieben.",
        "Guten Tag.",
        "Alles gute Sachen, aber ich brauche einen Termin am Montag.",
    ):
        assert not abschied.ist_abschied(satz), satz


def test_letzter_satz_entscheidet():
    """Der Abschied steht am ENDE — davor darf Inhalt stehen."""
    assert abschied.ist_abschied(
        "Ja, das passt mir gut. Vielen Dank und auf Wiederhören.")
    assert not abschied.ist_abschied(
        "Tschüss sagt man ja immer, aber ich bräuchte noch einen Termin.")


def test_streng_waehrend_diktat():
    """Ein verhörtes „ciao" darf keine halb erfasste Rufnummer wegwerfen."""
    assert abschied.ist_abschied("Ciao.")
    assert not abschied.ist_abschied("Ciao.", streng=True)
    assert abschied.ist_abschied("Auf Wiederhören.", streng=True), (
        "der unmissverständliche Kern gilt auch beim Diktat")


# ---------------------------------------------------------------------------
# Bianca legt auf
# ---------------------------------------------------------------------------

def test_agent_legt_auf_ohne_llm(monkeypatch):
    _kein_llm(monkeypatch)
    sit = _sit()
    out = bianca_agent.user_turn(sit, "Okay, vielen Dank, auf Wiederhören.")
    assert out.get("hangup") is True, "Bianca beendet den Anruf wirklich"
    assert "Wiederhören" in out["text"]


def test_agent_legt_nicht_mitten_im_nummern_diktat_auf(monkeypatch):
    _kein_llm(monkeypatch)
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "telefon", "nachname": "Meier"})
    out = bianca_agent.user_turn(sit, "Ciao.")
    assert not out.get("hangup"), "Kurzform während des Diktats: kein Auflegen"


def test_notaus_haelt_die_leitung(monkeypatch):
    """Notaus ABSCHIED_AUFLEGEN=0: Verhalten wie vor dem Patch — gesprochener
    Abschied, aber die Leitung bleibt offen (Zug geht wie früher weiter)."""
    monkeypatch.setenv("ABSCHIED_AUFLEGEN", "0")
    assert abschied.an() is False
    sit = _sit()
    gehirn.sammler(sit).update({"modus": "", "phase": "fertig"})
    out = flow.zug(sit, "Alles klar, vielen Dank.")
    assert out and "Wiederhören" in out["text"]
    assert not out.get("hangup")


def test_fluss_verabschiedet_sich_mit_hangup():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "", "phase": "fertig"})
    out = flow.zug(sit, "Alles klar, vielen Dank.")
    assert out and "Wiederhören" in out["text"]
    assert out.get("hangup") is True, (
        "der Fluss sprach den Abschied, legte aber nie auf")


# ---------------------------------------------------------------------------
# Notleine: zu viele Stupse im ganzen Anruf
# ---------------------------------------------------------------------------

def test_notleine_beendet_endlose_stups_schleife():
    """Live 11.09.2026: „Sind Sie noch dran?" / dieselbe Frage im Wechsel,
    15-mal. `stupse` wird bei jedem Anrufer-Satz genullt — nur der
    Gesamt-Zähler kann diese Schleife sehen."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "phase": "", "frage": "telefon",
              "nachname": "Meier", "testNoWrite": True})
    sit["testNoWrite"] = True
    texte = []
    for _ in range(3):          # drei Stille-Phasen mit je zwei Stupsen
        for _ in range(2):
            texte.append(bianca_agent.stille_zug(sit))
        stille.reset(sit)       # der Anrufer hat dazwischen gesprochen
    assert stille.gesamt(sit) == 6
    letzte = texte[-1]
    assert letzte.get("hangup") is True, "irgendwann ist Auflegen freundlicher"
    assert "Wiederhören" in letzte["text"]
    presence = [t["text"] for t in texte if "noch dran" in t["text"].casefold()]
    assert len(presence) <= 2, (
        "Presence darf nicht bei jeder Stille-Phase neu kommen")


def test_notleine_sagt_ihren_schlusssatz_nur_einmal():
    """Live-Probe 12.09.2026: der Schlusssatz kam zweimal, weil der
    Stups-Pfad das hangup verschluckte. Selbst wenn der Klient das Auflegen
    verpasst, wird derselbe Satz nie wiederholt."""
    sit = _sit()
    gehirn.sammler(sit).update({"modus": "", "phase": "fertig"})
    for _ in range(3):
        for _ in range(2):
            letzte = bianca_agent.stille_zug(sit)
        stille.reset(sit)
    assert letzte.get("hangup") is True
    nochmal = bianca_agent.stille_zug(sit)
    assert not nochmal["text"], "nach dem Abschied wird geschwiegen"


def test_stille_route_reicht_hangup_durch(monkeypatch):
    """Die Notleine nuetzt nichts, wenn /api/stille das Feld nicht meldet:
    Bruecke und Dock legen dann nicht auf (live 12.09.2026)."""
    from bianca import server as bianca_server

    sit = _sit()
    sit["id"] = "probe"
    gehirn.sammler(sit).update({"modus": "", "phase": "fertig"})
    monkeypatch.setattr(bianca_server.session, "holen", lambda sid: sit)
    monkeypatch.setattr(bianca_server.DIENST, "stimme", lambda text: ("api/audio/x.wav", 0.1))
    monkeypatch.setattr(bianca_server.halbsatz, "abholen", lambda s: "")
    body = bianca_server.HangupIn(sessionId="probe")

    gesehen = []
    for _ in range(3):
        for _ in range(2):
            gesehen.append(bianca_server.api_stille(body))
        stille.reset(sit)
    assert gesehen[-1].get("hangup") is True
    assert not any(d.get("hangup") for d in gesehen[:-1])


def test_presence_deckel_laesst_die_frage_durch():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "phase": "", "frage": "telefon",
              "nachname": "Meier"})
    for _ in range(stille.PRESENCE_BIS):
        bianca_agent.stille_zug(sit)
        stille.reset(sit)
    assert stille.presence_erlaubt(sit), "bis PRESENCE_BIS ist Presence in Ordnung"
    t = bianca_agent.stille_zug(sit)["text"]
    assert "noch dran" not in t.casefold()
    assert "?" in t, "statt Presence kommt die echte offene Frage"
