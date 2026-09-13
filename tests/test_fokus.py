"""W-FOKUS / W-HALLO-ANTWORT (12.09.2026) — Chef-Vorfall wortgleich.

Chef: „sie fragt manchmal immer noch wie geht es Ihnen, was unklug ist, da
fragen vom job ablenken. […] wenn sie eine frage formuliert kann es sein,
dass der anrufer darauf antwortet und diese antwort ignoriert bianca
komplett. […] bei mehreren turns wenn die gespräche sehr lang sind verliert
sich bianca in stille oder schleifen. […] auch bei live telefonaten verliert
bianca den fokus."

Alles offline: kein LLM, kein Netz, keine Kalender-Werkzeuge.
"""

from __future__ import annotations

import pytest

from bianca import agent as bianca_agent
from bianca import flow, gehirn
from kern import gespraech, hirn, llm, stille, wiederholung


def _sit(**extra) -> dict:
    sit = {
        "id": "fokus-1",
        "tenant": {
            "clientId": "c1",
            "praxisName": "Zahnärzte im Medical Center",
            "booking": {"calendars": [{"id": "k1", "name": "Doktor Petsas"}]},
        },
        # Die Begrüßung ist raus — sonst beantwortet user_turn den ersten
        # Satz mit start_reply.
        "messages": [{
            "role": "assistant",
            "content": "Zahnärzte im Medical Center, guten Tag! Was kann ich für Sie tun?",
        }],
        "sammler": {},
        "callerPhone": "+4915253904756",
        "anrufer": {
            "vorname": "Julia", "nachname": "Berger",
            "geschlecht": "female", "telefon": "+4915253904756",
        },
        "vorigesGespraech": {"ts": 1, "wann": "gestern"},
        "halloVariante": 0,   # die Frage-Variante des Eisbrechers
    }
    sit.update(extra)
    gehirn.sammler(sit)
    hirn.init(sit)
    return sit


@pytest.fixture(autouse=True)
def _kein_hintergrund(monkeypatch):
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda _sit: None)


# ------------------------------------------------- (a) Wohlsein-Frage

def test_wohlsein_frage_nur_ohne_anliegen():
    """Ohne Auftrag darf der Eisbrecher fragen — mit Auftrag nie."""
    frei = _sit()
    assert gehirn.anrufer_hallo_fragt(gehirn.anrufer_hallo(frei)), \
        "Variante 0 ist die Frage-Form (sonst testet der Fall nichts)"
    assert not gehirn.hallo_frage_unpassend(frei, "Guten Tag, Berger hier.")

    laufend = _sit()
    gehirn.sammler(laufend)["modus"] = "buchen"
    assert gehirn.hallo_frage_unpassend(laufend, "Ich hätte gern einen Termin.")


def test_wohlsein_frage_entfaellt_bei_schmerz_und_beschwerde():
    """Wer Schmerzen hat oder sich beschwert, wird nicht nach dem
    Wohlbefinden gefragt — das war live taktlos."""
    for satz in (
        "Ich habe ganz starke Schmerzen, mein Zahn ist gebrochen.",
        "Ich möchte mich beschweren, die Wartezeit war unzumutbar.",
    ):
        sit = _sit()
        assert gehirn.hallo_frage_unpassend(sit, satz), satz
        hallo = gehirn.anrufer_hallo_jetzt(sit, satz)
        assert hallo and "?" not in hallo, f"Feststellung statt Frage: {satz}"
        assert "wie geht es" not in hallo.casefold()


def test_wohlsein_antwort_mit_inhalt_geht_nicht_verloren(monkeypatch):
    """Chef: „diese antwort ignoriert bianca komplett."

    Trägt die Antwort auf die Wohlseinsfrage eigenen Inhalt, muss sie
    zusammen mit dem geparkten Wunsch weiterverarbeitet werden."""
    gesehen: list[str] = []

    def antwort(messages, _tools=None, **_kwargs):
        gesehen.append(messages[-1]["content"])
        return {"ok": True, "text": "Das notiere ich mir.", "tool_calls": []}

    monkeypatch.setattr(bianca_agent.llm, "chat", antwort)
    monkeypatch.setattr(bianca_agent.intent, "enabled", lambda: False)
    monkeypatch.setattr(bianca_agent.tasks, "zug", lambda *_a, **_k: None)
    monkeypatch.setattr(
        bianca_agent.task_router, "braucht_auswahl", lambda _sit: False,
    )

    sit = _sit()
    z1 = bianca_agent.user_turn(
        sit, "Hallo, ich bräuchte ein Röntgenbild.", vorab=lambda _t: None,
    )
    assert "wie geht es" in z1["text"].casefold()
    assert sit.get("anruferHalloFrageOffen")

    bianca_agent.user_turn(
        sit, "Danke, gut. Und meine Adresse hat sich geändert.",
        vorab=lambda _t: None,
    )
    letzte = gesehen[-1]
    assert "Röntgenbild" in letzte, "geparkter Wunsch bleibt erhalten"
    assert "Adresse" in letzte, "die Antwort des Anrufers geht mit"


def test_reine_wohlsein_antwort_bleibt_ohne_ballast():
    """„Ja, gut." ist kein Inhalt — der Satz darf den Auftrag nicht
    verwaschen (sonst landet „gut" in der Besuchsgrund-Ernte)."""
    assert gehirn.ist_nur_wohlsein("Ja, gut.")
    assert gehirn.ist_nur_wohlsein("Danke, mir geht es gut.")
    assert not gehirn.ist_nur_wohlsein("Gut, aber mein Zahn tut weh.")


# ------------------------------------------------- (b) Stille + Schleifen

def test_nie_stumm_wenn_das_modell_nichts_liefert(monkeypatch):
    """Live 11.09.2026 (Session 9395e2ce): sechs Züge ohne einen Ton. Nach
    einem echten Anrufer-Satz holt kein Wächter zurück — er hat ja gerade
    gesprochen. Also muss der Zug selbst etwas sagen."""
    monkeypatch.setattr(
        bianca_agent.llm, "chat",
        lambda *_a, **_k: {"ok": False, "text": "", "tool_calls": []},
    )
    monkeypatch.setattr(bianca_agent.intent, "enabled", lambda: False)
    monkeypatch.setattr(bianca_agent.tasks, "zug", lambda *_a, **_k: None)
    monkeypatch.setattr(
        bianca_agent.task_router, "braucht_auswahl", lambda _sit: False,
    )

    sit = _sit(halloVariante=1)
    sit["anruferHalloGesagt"] = True
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "telefon", "nachname": "Berger"})
    sit["flussFrage"] = "Und unter welcher Handynummer erreichen wir Sie?"

    aus = bianca_agent.user_turn(sit, "Erzählen Sie mal von Ihrer Praxis.")
    assert aus["text"].strip(), "kein stummer Zug"
    assert "?" in aus["text"], "der Anrufer bekommt die offene Frage zurück"


def test_fokus_holt_nach_vier_freien_zuegen_zurueck(monkeypatch):
    """Chef: „auch bei live telefonaten verliert bianca den fokus."

    Nebenthemen dürfen Züge kosten, aber nicht beliebig viele, solange eine
    Pflichtfrage offen ist."""
    monkeypatch.setattr(
        bianca_agent.llm, "chat",
        lambda *_a, **_k: {"ok": True, "text": "Oh, wie schön.", "tool_calls": []},
    )
    monkeypatch.setattr(bianca_agent.intent, "enabled", lambda: False)
    monkeypatch.setattr(bianca_agent.tasks, "zug", lambda *_a, **_k: None)
    monkeypatch.setattr(
        bianca_agent.task_router, "braucht_auswahl", lambda _sit: False,
    )

    sit = _sit(halloVariante=1)
    sit["anruferHalloGesagt"] = True
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "telefon", "nachname": "Berger"})
    sit["flussFrage"] = "Und unter welcher Handynummer erreichen wir Sie?"

    texte = []
    for satz in (
        "Wir waren im Sommer in Italien.",
        "Da gab es den besten Kaffee.",
        "Meine Schwester war auch mit.",
        "Und das Wetter war herrlich.",
    ):
        texte.append(bianca_agent.user_turn(sit, satz)["text"])

    assert all(t.strip() for t in texte)
    assert "ummer" in texte[-1], f"Rückholung fehlt: {texte[-1]}"
    assert gespraech.floor(sit) == gespraech.JOB
    assert not (gespraech.stand(sit).get("stack") or []), "Talk-Stack geräumt"


def test_stille_wechselt_nie_endlos_zwischen_presence_und_frage():
    """Live 11.09.2026: „Sind Sie noch dran?" / „Ich bin noch da. Meine Frage
    war: …" im Wechsel, 23 Minuten lang. Ab dem zweiten Stups gehört die
    offene Frage in JEDEN Stups, und irgendwann ist Schluss."""
    sit = _sit(halloVariante=1)
    sit["anruferHalloGesagt"] = True
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "telefon", "nachname": "Berger"})
    sit["flussFrage"] = "Und unter welcher Handynummer erreichen wir Sie?"
    sit["testNotizUnterdrueckt"] = True

    gesagt: list[str] = []
    aufgelegt = False
    for _phase in range(8):                 # acht Stille-Phasen hintereinander
        for _ in range(stille.MAX_STUPSE):
            aus = bianca_agent.stille_zug(sit)
            if not aus["text"].strip():
                continue
            gesagt.append(aus["text"])
            aufgelegt = aufgelegt or bool(aus.get("hangup"))
        stille.reset(sit)                   # echter Anrufer-Satz wäre hier

    nur_presence = [t for t in gesagt if "noch dran" in t.casefold() and "?" == t.strip()[-1] and len(t) < 30]
    assert len(nur_presence) <= 1, f"Presence-Floskel wiederholt sich: {gesagt}"
    assert aufgelegt, "irgendwann beendet die Notleine das tote Gespräch"
    assert all(t.strip() for t in gesagt), "kein stummer Stups"


def test_wiederholungs_gedaechtnis_ist_ein_fenster():
    """Der Entdoppler verglich gegen JEDEN Satz des ganzen Anrufs. In einem
    langen Gespräch war damit fast jede Pflichtfrage „schon gesagt" und
    wurde gestrichen — der Schleifen-Wächter wurde selbst zur Ursache."""
    sit = _sit()
    frage = "Und unter welcher Handynummer erreichen wir Sie?"
    wiederholung.gesagt_merken(sit, frage)
    for i in range(wiederholung.GEDAECHTNIS_SAETZE + 5):
        wiederholung.gesagt_merken(sit, f"Zwischensatz Nummer {i} als Füllung.")
    bag = sit["waechterGesagt"]
    assert len(bag) <= wiederholung.GEDAECHTNIS_SAETZE
    assert wiederholung.pruefen(sit, frage, frueher=[]) == frage, \
        "nach vielen Zügen darf die Frage wieder gestellt werden"


def test_llm_verlauf_wird_gedeckelt():
    """Lange Gespräche schoben den Prompt über das Kontextfenster — das
    Modell antwortete dann leer (Live: sechs stumme Züge)."""
    msgs = [{"role": "system", "content": "SYSTEM"}]
    for i in range(120):
        msgs.append({"role": "user", "content": f"u{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    gekappt = llm._verlauf_kappen(msgs)
    assert gekappt[0]["content"] == "SYSTEM", "System-Prompt bleibt immer"
    assert len(gekappt) <= llm.VERLAUF_MAX + 1
    assert gekappt[-1] == msgs[-1], "die jüngsten Züge bleiben"
    assert gekappt[1]["role"] != "tool", "kein Werkzeug-Ergebnis ohne Aufruf"
