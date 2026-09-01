"""Stille-Wächter (kern/stille.py, Chef 27.08.2026): nach ~4 s Funkstille
ergreift die Stimme selbst das Wort. W-STUPS-PRESENCE (01.09.2026): der
erste Stups ist nur Presence (phone_agent), der zweite die kurze offene
Frage. Offline, ohne LLM und ohne Netz.
"""

from __future__ import annotations

import os
import sys
import time

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
        {"role": "assistant", "content": "Gern. Und unter welcher Handynummer erreichen wir Sie?"},
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
    assert z1["text"], "erster Kurz-Laut: Presence"
    assert "noch dran" in z1["text"].casefold()
    z2 = bianca_agent.user_turn(sit, "Well.")
    assert z2["text"], "zweiter Kurz-Laut: kurze Frage"
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


def test_nur_fragesaetze_schneidet_begleit():
    assert stille.nur_fragesaetze(
        "Prima. Und unter welcher Handynummer erreichen wir Sie? Die brauche ich für die Bestätigung."
    ).endswith("?")
    assert "brauche" not in stille.nur_fragesaetze(
        "Und unter welcher Handynummer erreichen wir Sie? Die brauche ich."
    ).casefold()


# ---------------------------------------------------------------------------
# Bianca: stille_zug
# ---------------------------------------------------------------------------

def test_erster_stups_nur_presence():
    """W-STUPS-PRESENCE (01.09.2026): phone_agent wiederholte auf Silence nie
    die Pflichtfrage — nur Presence."""
    sit = _buchungs_sit()
    out = bianca_agent.stille_zug(sit)
    t = out["text"]
    assert "noch dran" in t.casefold()
    assert "andynummer" not in t and "ummer erreichen" not in t
    assert "Terminaufnahme" not in t
    assert sit["messages"][-1]["role"] == "assistant"


def test_zweiter_stups_kurze_frage():
    sit = _buchungs_sit()
    t1 = bianca_agent.stille_zug(sit)["text"]
    t2 = bianca_agent.stille_zug(sit)["text"]
    assert t2 and t2 != t1
    assert "andynummer" in t2 or "ummer" in t2, "zweite Stups: offene Frage"
    assert "Terminaufnahme" not in t2, "kein Stand-Sermon auf dem Stups-Pfad"
    assert "Ich bin noch da" in t2 or "noch da" in t2.casefold()


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


def test_denk_cue_unterdrueckt_stups():
    sit = _buchungs_sit()
    out = bianca_agent.user_turn(sit, "Einen Moment bitte.")
    assert out["text"] == ""
    assert sit.get("denkPauseBis", 0) > time.time()
    assert bianca_agent.stille_zug(sit)["text"] == "", "Denk-Pause: kein Stups"


def test_telefon_check_erst_kurz_dann_nummer():
    """W-STUPS-KURZ: die Ziffern kamen Sekunden vorher — der erste Stups
    fragt nur kurz nach, erst der zweite wiederholt die komplette Nummer
    (dann deterministisch, wortgleich richtig)."""
    sit = _buchungs_sit(frage="telefon_check")
    s = sit["sammler"]
    s["telefonOffen"] = "017760011"
    t1 = bianca_agent.stille_zug(sit)["text"]
    assert "null eins" not in t1.casefold(), "kein Ziffern-Readback beim ersten Stups"
    assert "timmt die Nummer" in t1, "die Rueckbestaetigung bleibt eine Frage"
    t2 = bianca_agent.stille_zug(sit)["text"]
    assert "null eins sieben sieben" in t2.casefold(), "zweiter Stups: Nummer deterministisch wiederholt"
    assert "timmt das so" in t2, "die Rueckbestaetigung bleibt eine Frage"


def test_talk_thema_zuerst_dann_frage():
    sit = _buchungs_sit()
    st = gespraech.stand(sit)
    st["floor"] = gespraech.TALK
    st["stack"] = [{"thema": "hochzeit", "zuege": 1}]
    st["gravity"] = {"hochzeit": 2.0}
    t1 = bianca_agent.stille_zug(sit)["text"]
    assert "hochzeit" in t1.casefold(), "erster Stups knuepft am letzten Thema an"
    assert "Terminaufnahme" not in t1, "kein Job-Sermon mitten im Talk"
    t2 = bianca_agent.stille_zug(sit)["text"]
    assert "andynummer" in t2 or "ummer" in t2, "zweiter Stups: Job-Frage"


def test_verwalten_zweiter_stups_mit_flussfrage():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "frage": ""})
    sit["flussFrage"] = "Um welchen Termin geht es denn genau?"
    sit["messages"] = [{"role": "assistant", "content": "Gern. Um welchen Termin geht es denn genau?"}]
    # Erster = Presence
    t1 = bianca_agent.stille_zug(sit)["text"]
    assert "noch dran" in t1.casefold()
    t2 = bianca_agent.stille_zug(sit)["text"]
    assert "welchen Termin" in t2


def test_ohne_offenen_job_freundlich():
    sit = _sit()
    sit["messages"] = [{"role": "assistant", "content": "Gern geschehen."}]
    t = bianca_agent.stille_zug(sit)["text"]
    assert "noch dran" in t.casefold()
    # Zweiter Stups: Fallback-Frage
    t2 = bianca_agent.stille_zug(sit)["text"]
    assert "sonst noch etwas" in t2.casefold()


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
        "auftrag": "Termin",
        "idCheck": identitaet.FRAGE,
        "patient": {"firstName": "Max", "lastName": "Muster"},
        "messages": [{"role": "assistant", "content": "Bin ich mit Max Muster verbunden?"}],
    }
    t = lisa_agent.stille_zug(doc)["text"]
    assert "Meine Frage war" in t or "Max" in t


def test_lisa_cap():
    doc = {
        "tenant": {"praxisName": "Testpraxis"},
        "auftrag": "Termin",
        "idCheck": identitaet.FERTIG,
        "patient": {},
        "messages": [{"role": "assistant", "content": "Passt Ihnen Donnerstag?"}],
    }
    assert lisa_agent.stille_zug(doc)["text"]
    assert lisa_agent.stille_zug(doc)["text"]
    assert lisa_agent.stille_zug(doc)["text"] == "", "Cap gilt auch bei Lisa"
    stille.reset(doc)
    assert lisa_agent.stille_zug(doc)["text"]
