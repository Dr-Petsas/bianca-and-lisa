"""V5.6: anrufweites Feldfrage- und Stagnationsbudget.

Offline, ohne LLM, Kalender oder echte Praxisnotiz.
"""

from __future__ import annotations

from bianca import agent, gehirn, verwalten
from kern import frage_budget


def _sit(frage: str = "telefon") -> dict:
    sit = {
        "tenant": {"praxisName": "Testpraxis"},
        "messages": [
            {"role": "system", "content": "x"},
            {"role": "user", "content": "Ich brauche einen Termin."},
        ],
        "testNoWrite": True,
    }
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "",
        "frage": frage,
        "grund": "Kontrolle",
        "grundWortlaut": "Kontrolle",
        "vorname": "Anna",
        "nachname": "Meier",
    })
    return sit


def _frage(sit: dict, text: str = "Unter welcher Handynummer erreichen wir Sie?") -> dict:
    return agent._maschinen_antwort(
        sit,
        {"text": text, "book": None},
        list(sit.get("messages") or []),
    )


def test_eine_frage_plus_zwei_wiederholungen_dann_abschluss(monkeypatch):
    sit = _sit()
    notizen: list[str] = []

    def _notiz(_sit, *, was=""):
        notizen.append(was)
        _sit["praxisNotizPersistiert"] = True
        _sit["praxisNotiz"] = "Rueckruf"

    monkeypatch.setattr(verwalten, "abgeben_notiz", _notiz)

    for _ in range(3):
        aus = _frage(sit)
        assert not aus.get("hangup")
        assert "nummer" in aus["text"].casefold()

    aus = _frage(sit)
    assert aus.get("hangup") is True
    assert "notiert" in aus["text"].casefold()
    assert sit["frageBudgetDone"] is True
    assert sit["sammler"]["phase"] == "fertig"
    assert sit["sammler"]["frage"] == ""
    assert sit["sammler"]["grund"] == "Kontrolle"
    assert sit["sammler"]["nachname"] == "Meier"
    assert len(notizen) == 1


def test_ausstieg_ohne_brauchbaren_kontext_erfindet_keine_notiz(monkeypatch):
    sit = _sit()
    sit["sammler"].update({
        "modus": "",
        "grund": "",
        "grundWortlaut": "",
        "vorname": "",
        "nachname": "",
    })
    aufrufe: list[str] = []
    monkeypatch.setattr(
        verwalten,
        "abgeben_notiz",
        lambda *_a, **_k: aufrufe.append("unerwartet"),
    )

    for _ in range(3):
        assert frage_budget.vor_mund(sit, "telefon", zaehlt=True) == "ok"
    aus = agent._frage_budget_ausstieg(sit, fid="telefon")

    assert aus.get("hangup") is True
    assert "notiert" not in aus["text"].casefold()
    assert not aufrufe


def test_feldwechsel_beginnt_neues_budget():
    sit = _sit("nachname")
    for _ in range(3):
        assert frage_budget.vor_mund(sit, "nachname", zaehlt=True) == "ok"
    assert frage_budget.vor_mund(sit, "nachname", zaehlt=True) == "erschoepft"

    assert frage_budget.vor_mund(sit, "vorname", zaehlt=True) == "ok"
    assert sit["frageBudget"]["fid"] == "vorname"
    assert sit["frageBudget"]["versuche"] == 1


def test_erster_presence_stups_zaehlt_nicht_als_feldfrage():
    sit = _sit()
    aus = agent.stille_zug(sit)
    assert "noch dran" in aus["text"].casefold()
    assert int((sit.get("frageBudget") or {}).get("versuche") or 0) == 0

    aus = agent.stille_zug(sit)
    assert "nummer" in aus["text"].casefold()
    assert sit["frageBudget"]["versuche"] == 1


def test_presence_und_unklar_teilen_globalen_deckel():
    sit = _sit()
    sit["frageBudget"] = {"fid": "telefon", "versuche": 0, "unklar": 7}
    aus = agent.stille_zug(sit)

    assert aus.get("hangup") is True
    assert sit["frageBudgetDone"] is True
    assert frage_budget.stall_gesamt(sit) == 8


def test_ruecklese_und_bestaetigung_bleiben_ausgenommen():
    sit = _sit("telefon_check")
    for _ in range(10):
        assert frage_budget.vor_mund(
            sit, "telefon_check", zaehlt=True,
        ) == "ok"
    assert int((sit.get("frageBudget") or {}).get("versuche") or 0) == 0


def test_explizit_verlangte_wiederholung_verbraucht_kein_budget():
    sit = _sit()
    for _ in range(5):
        aus = agent._maschinen_antwort(
            sit,
            {
                "text": "Unter welcher Handynummer erreichen wir Sie?",
                "book": None,
                "_wiederholungErlaubt": True,
            },
            list(sit.get("messages") or []),
        )
        assert not aus.get("hangup")
    assert int((sit.get("frageBudget") or {}).get("versuche") or 0) == 0
