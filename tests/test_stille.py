"""Stille-Wächter (kern/stille.py, Chef 27.08.2026): nach ~4 s Funkstille
ergreift die Stimme selbst das Wort — zurück auf die Job-Spur oder das
letzte Thema, mit Stand-Ansage (Auftrag, was schon da ist, was fehlt)
statt bei null anzufangen. Offline, ohne LLM und ohne Netz.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bianca import agent as bianca_agent
from bianca import gehirn
from kern import gespraech, stille
from lisa import agent as lisa_agent
from lisa import identitaet


def _sit() -> dict:
    return {"tenant": {"praxisName": "Testpraxis"}, "messages": []}


def _buchungs_sit(frage: str = "telefon") -> dict:
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "", "frage": frage,
        "warSchonMal": False, "grund": "Kontrolle", "wunsch": {},
        "vorname": "Anna", "nachname": "Meier", "buchstabiert": True,
    })
    sit["messages"] = [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "Ich haette gern einen Termin."},
        {"role": "assistant", "content": "Gern."},
    ]
    return sit


# ---------------------------------------------------------------------------
# kern/stille: Bausteine
# ---------------------------------------------------------------------------

def test_zaehler_cap_und_reset():
    sit = _sit()
    assert stille.stups_zaehlen(sit) == 1
    assert stille.stups_zaehlen(sit) == 2
    assert stille.stups_zaehlen(sit) == 3, "Zaehler laeuft weiter — Cap prueft der Aufrufer"
    stille.reset(sit)
    assert stille.stups_zaehlen(sit) == 1, "nach echtem Gehoertem beginnt es von vorn"


def test_kurzlaut_stupst_statt_llm():
    """Live 29.08.2026: 'Hm.' und 'Well.' (STT-Artefakt) gingen als volle
    Zuege ans LLM und ergaben zwei fast identische ~4-s-Meta-Reden. Kurz-Laute
    laufen jetzt als Stille-Stups — gedeckelt, offline, nie durchs LLM."""
    sit = _buchungs_sit(frage="telefon")
    z1 = bianca_agent.user_turn(sit, "Hm.")
    assert z1["text"], "erster Kurz-Laut: Stups mit Stand und offener Frage"
    z2 = bianca_agent.user_turn(sit, "Well.")
    assert z2["text"], "zweiter Kurz-Laut: kurzer Frage-Stups"
    z3 = bianca_agent.user_turn(sit, "Ähm...")
    assert z3["text"] == "", "nach MAX_STUPSE Stupsen ist Schweigen"
    # Echte Kurz-Antworten bleiben unberuehrt (kein Match).
    for echt in ("Ja.", "Nein.", "Okay.", "Stopp."):
        assert not bianca_agent._NUR_LAUT_RE.match(echt), echt


def test_letzte_frage_nur_aus_juengster_antwort():
    msgs = [
        {"role": "assistant", "content": "Wie ist Ihr Name?"},
        {"role": "user", "content": "Moment."},
        {"role": "assistant", "content": "Kein Problem. Welche Handynummer darf ich eintragen?"},
    ]
    assert "Handynummer" in stille.letzte_frage(msgs)
    msgs.append({"role": "assistant", "content": "Alles klar, erledigt."})
    assert stille.letzte_frage(msgs) == "", "aeltere Fragen sind bedient — nicht ausgraben"


def test_anhaengen_verlaengert_letzte_antwort():
    sit = {"messages": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "Gern."},
    ]}
    stille.anhaengen(sit, "Sind Sie noch dran?")
    assert len(sit["messages"]) == 2, "kein neuer Eintrag — ans letzte Assistant angehaengt"
    assert sit["messages"][-1]["content"] == "Gern. Sind Sie noch dran?"


# ---------------------------------------------------------------------------
# Bianca: stille_zug
# ---------------------------------------------------------------------------

def test_stups_nennt_stand_und_offene_frage():
    sit = _buchungs_sit()
    out = bianca_agent.stille_zug(sit)
    t = out["text"]
    assert "noch dran" in t.casefold()
    assert "Terminaufnahme" in t, "Auftrag ansagen — nicht bei null anfangen"
    assert "Kontrolle" in t, "der Grund gehoert zum Stand"
    assert "Namen habe ich schon" in t, "was schon da ist, wird genannt"
    assert "andynummer" in t, "die offene Frage bleibt hoerbar"
    assert sit["messages"][-1]["role"] == "assistant"
    assert t.split()[-1] in sit["messages"][-1]["content"].split(), "Stups steht im Protokoll"


def test_zweiter_stups_kurz_und_nie_wortgleich():
    sit = _buchungs_sit()
    t1 = bianca_agent.stille_zug(sit)["text"]
    t2 = bianca_agent.stille_zug(sit)["text"]
    assert t2 and t2 != t1
    assert "Terminaufnahme" not in t2, "der Sermon kommt nicht zweimal"
    assert "andynummer" in t2 or "ummer" in t2, "aber die offene Frage bleibt hoerbar"
    saetze1 = {x.strip().casefold() for x in t1.split("?") if x.strip()}
    saetze2 = {x.strip().casefold() for x in t2.split("?") if x.strip()}
    assert not (saetze1 & saetze2), "kein Satz wortgleich doppelt"


def test_dritter_stups_schweigt():
    sit = _buchungs_sit()
    bianca_agent.stille_zug(sit)
    bianca_agent.stille_zug(sit)
    assert bianca_agent.stille_zug(sit)["text"] == "", "nach zwei Stupsen: warten, nicht noelen"


def test_nach_reset_wieder_stups():
    sit = _buchungs_sit()
    bianca_agent.stille_zug(sit)
    bianca_agent.stille_zug(sit)
    stille.reset(sit)  # user_turn macht das bei jedem echten Gehoerten
    assert bianca_agent.stille_zug(sit)["text"], "neues Gehoertes = neues Stups-Budget"


def test_telefon_check_wiederholt_die_nummer():
    sit = _buchungs_sit(frage="telefon_check")
    s = sit["sammler"]
    s["telefonOffen"] = "017760011"
    t = bianca_agent.stille_zug(sit)["text"]
    assert "null eins sieben sieben" in t, "die Nummer wird deterministisch wiederholt"
    assert "timmt das so" in t, "die Rueckbestaetigung bleibt eine Frage"


def test_talk_thema_zuerst_dann_jobspur():
    sit = _buchungs_sit()
    st = gespraech.stand(sit)
    st["floor"] = gespraech.TALK
    st["stack"] = [{"thema": "hochzeit", "zuege": 1}]
    st["gravity"] = {"hochzeit": 2.0}
    t1 = bianca_agent.stille_zug(sit)["text"]
    assert "hochzeit" in t1.casefold(), "erster Stups knuepft am letzten Thema an"
    assert "Terminaufnahme" not in t1, "kein Job-Sermon mitten im Talk"
    t2 = bianca_agent.stille_zug(sit)["text"]
    assert "Terminaufnahme" in t2, "zweiter Stups holt auf die Job-Spur"
    assert "andynummer" in t2 or "ummer" in t2


def test_verwalten_stand_mit_flussfrage():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "frage": ""})
    sit["flussFrage"] = "Um welchen Termin geht es denn genau?"
    sit["messages"] = [{"role": "assistant", "content": "Gern."}]
    t = bianca_agent.stille_zug(sit)["text"]
    assert "abzusagen" in t, "Auftrag ansagen: wir waren beim Absagen"
    assert "welchen Termin" in t, "die offene Fluss-Frage kommt mit"


def test_ohne_offenen_job_freundlich():
    sit = _sit()
    sit["messages"] = [{"role": "assistant", "content": "Gern geschehen."}]
    t = bianca_agent.stille_zug(sit)["text"]
    assert "noch dran" in t.casefold()
    assert "sonst noch etwas" in t.casefold()


# ---------------------------------------------------------------------------
# Lisa: stille_zug
# ---------------------------------------------------------------------------

def test_lisa_stups_nennt_auftrag_und_letzte_frage():
    doc = {
        "tenant": {"praxisName": "Testpraxis"},
        "auftrag": "Kontrolltermin am Donnerstag bestätigen",
        "idCheck": identitaet.FERTIG,
        "patient": {"firstName": "Max", "lastName": "Muster"},
        "messages": [
            {"role": "assistant", "content": "Passt Ihnen der Donnerstag um zehn Uhr?"},
        ],
    }
    t = lisa_agent.stille_zug(doc)["text"]
    assert "noch dran" in t.casefold()
    assert "Kontrolltermin" in t, "der Auftrag wird angesagt — Gehirn an"
    assert "Meine Frage war" in t and "Donnerstag" in t, "die offene Frage kommt mit Praefix"


def test_lisa_identitaetsphase_wiederholt_die_frage():
    doc = {
        "tenant": {"praxisName": "Testpraxis"},
        "auftrag": "Termin bestätigen",
        "idCheck": identitaet.FRAGE,
        "patient": {"firstName": "Max", "lastName": "Muster"},
        "messages": [{"role": "assistant", "content": "Spreche ich mit Max Muster?"}],
    }
    t = lisa_agent.stille_zug(doc)["text"]
    assert "Meine Frage war" in t
    assert "Muster" in t, "die Identitaetsfrage bleibt hoerbar"


def test_lisa_cap_und_reset():
    doc = {
        "tenant": {"praxisName": "Testpraxis"},
        "auftrag": "Termin bestätigen",
        "idCheck": identitaet.FERTIG,
        "patient": {},
        "messages": [{"role": "assistant", "content": "Passt das so?"}],
    }
    assert lisa_agent.stille_zug(doc)["text"]
    assert lisa_agent.stille_zug(doc)["text"]
    assert lisa_agent.stille_zug(doc)["text"] == "", "Cap gilt auch bei Lisa"
    stille.reset(doc)
    assert lisa_agent.stille_zug(doc)["text"]


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_stille: alle gruen")
