"""Talk-Schicht (kern/gespraech.py): Themen, Gravity, Floor, Anker — offline.

Prueft das Zwei-Schichten-Versprechen vom 27.08.2026: Der Job (Zustands-
maschine) bleibt unangetastet, aber Abschweifungen bekommen den Floor,
halten ihn ueber mehrere Zuege und finden ueber EINE Bruecke zurueck —
ohne dass der Frage-Anker jede Antwort wortgleich zutextet.
"""

from __future__ import annotations

import os

from bianca import agent as bianca_agent
from bianca import gehirn
from kern import gespraech


def _sit() -> dict:
    return {"tenant": {"praxisName": "Testpraxis"}, "messages": []}


# ---------------------------------------------------------------------------
# Listener + Floor
# ---------------------------------------------------------------------------

def test_erzaehltes_thema_bekommt_talk_floor():
    sit = _sit()
    r = gespraech.routen(sit, "Meine Tochter heiratet am Wochenende und ich bin so aufgeregt!")
    assert r["floor"] == gespraech.TALK
    assert r["thema"]
    assert sit["talk"]["stack"], "Talk-Faden muss auf dem Stack liegen"


def test_bekloppte_aussage_bekommt_reaktion():
    """Auch das Absurdeste ist ein Thema — nie Leerlauf, nie Floskel."""
    sit = _sit()
    r = gespraech.routen(sit, "Ich bin uebrigens Batman und wohne in einer Hoehle.")
    assert r["floor"] == gespraech.TALK
    assert gespraech.traegt_thema(sit, "Die Hoehle ist wirklich gemuetlich.")


def test_kurze_frage_zieht_den_floor():
    sit = _sit()
    r = gespraech.routen(sit, "Was kostet eigentlich ein Implantat?")
    assert r["floor"] == gespraech.TALK


def test_job_antwort_bleibt_job():
    sit = _sit()
    r = gespraech.routen(sit, "Donnerstag um zehn Uhr passt gut.")
    assert r["floor"] == gespraech.JOB
    assert not sit["talk"]["gravity"], "Job-Stoff darf kein Thema werden"


def test_ernte_zaehlt_als_task():
    """Buchungs-Saetze (Ernte) starten kein Nebenthema."""
    sit = _sit()
    r = gespraech.routen(
        sit, "Wegen der Hochzeit meiner Tochter brauche ich eine Zahnreinigung.",
        ernte=["grund"], job_aktiv=True,
    )
    assert r["floor"] == gespraech.JOB
    assert not sit["talk"]["stack"]


def test_beilaeufige_erwaehnung_wird_blended():
    sit = _sit()
    r = gespraech.routen(sit, "Gruss vom Flughafen!")
    assert r["floor"] == gespraech.BLENDED


def test_wiederholung_zieht_gravity_hoch():
    sit = _sit()
    gespraech.routen(sit, "Gruss vom Flughafen!")           # 0.30 blended
    gespraech.nach_antwort(sit)
    r = gespraech.routen(sit, "Der Flughafen war heute voll.")  # +0.30 -> talk
    assert r["floor"] == gespraech.TALK


def test_fortsetzung_ohne_inhalt_haelt_den_faden():
    sit = _sit()
    gespraech.routen(sit, "Meine Tochter heiratet am Wochenende und ich bin so aufgeregt!")
    gespraech.nach_antwort(sit)
    r = gespraech.routen(sit, "Ja, wirklich!")
    assert r["floor"] == gespraech.TALK
    assert r["thema"]


def test_loslassen_bringt_bruecke_und_dann_job():
    sit = _sit()
    gespraech.routen(sit, "Meine Tochter heiratet am Wochenende und ich bin so aufgeregt!")
    gespraech.nach_antwort(sit)
    r2 = gespraech.routen(sit, "Na gut, alles klar.")
    assert r2["floor"] == gespraech.ZURUECK
    assert r2["thema"], "Die Bruecke braucht das Thema"
    gespraech.nach_antwort(sit)
    r3 = gespraech.routen(sit, "Aehm ja.")
    assert r3["floor"] == gespraech.JOB


def test_job_antwort_laesst_faden_verhungern():
    """Nach einer Job-Antwort der Maschine faellt der Faden, Bruecke wird faellig."""
    sit = _sit()
    gespraech.routen(sit, "Meine Tochter heiratet am Wochenende und ich bin so aufgeregt!")
    gespraech.nach_antwort(sit)
    r = gespraech.routen(sit, "Meine Nummer ist null eins sieben sieben.", job_gesprochen=True)
    assert r["floor"] == gespraech.JOB
    gespraech.nach_antwort(sit)
    assert sit["talk"]["bruecke"], "Kalter Faden muss die Bruecke setzen"
    r2 = gespraech.routen(sit, "Hm.")
    assert r2["floor"] == gespraech.ZURUECK


def test_dringend_reisst_alles_zurueck():
    sit = _sit()
    gespraech.routen(sit, "Meine Tochter heiratet am Wochenende und ich bin so aufgeregt!")
    gespraech.nach_antwort(sit)
    r = gespraech.routen(sit, "Au, ich habe ploetzlich furchtbare Schmerzen!")
    assert r["floor"] == gespraech.JOB
    assert r["dringend"] is True
    assert not sit["talk"]["stack"]


def test_idempotenz_stt_doppel():
    sit = _sit()
    satz = "Meine Tochter heiratet am Wochenende und ich bin so aufgeregt!"
    gespraech.routen(sit, satz)
    g1 = dict(sit["talk"]["gravity"])
    gespraech.routen(sit, satz)
    assert sit["talk"]["gravity"] == g1, "STT-Doppel darf die Gravity nicht doppelt ziehen"


def test_traegt_thema_schuetzt_vor_leerlauf():
    sit = _sit()
    gespraech.routen(sit, "Meine Tochter heiratet am Wochenende und ich bin so aufgeregt!")
    assert gespraech.traegt_thema(sit, "Die Hochzeit wird riesig gefeiert.")
    assert not gespraech.traegt_thema(sit, "aehm ja gut okay")
    assert not gespraech.traegt_thema(_sit(), "Donnerstag um zehn Uhr bitte.")


# ---------------------------------------------------------------------------
# Planner + Budget
# ---------------------------------------------------------------------------

def test_plan_block_talk_verbietet_terminfrage():
    plan = gespraech.plan_block({"floor": gespraech.TALK, "thema": "hochzeit"})
    assert "hochzeit" in plan
    assert "KEINE Terminfrage" in plan
    assert "Diagnosen" in plan


def test_plan_block_zurueck_nennt_die_offene_frage():
    plan = gespraech.plan_block(
        {"floor": gespraech.ZURUECK, "thema": "hochzeit"},
        offene_frage="Und unter welcher Handynummer erreichen wir Sie?",
    )
    assert "Handynummer" in plan and "Halbsatz" in plan


def test_plan_block_lisa_haelt_den_auftrag():
    plan = gespraech.plan_block({"floor": gespraech.TALK, "thema": "urlaub"}, stimme="lisa")
    assert "Auftrag" in plan


def test_plan_block_job_ist_leer():
    assert gespraech.plan_block({"floor": gespraech.JOB, "thema": ""}) == ""


def test_budget_talk_groesser_als_job():
    b = gespraech.budget(gespraech.TALK)
    assert b["max_tokens"] > 90 and b["temperature"] > 0.3
    assert gespraech.budget(gespraech.JOB) == {}


def test_notaus_schaltet_alles_ab():
    os.environ["TALK_SCHICHT"] = "0"
    try:
        sit = _sit()
        r = gespraech.routen(sit, "Meine Tochter heiratet am Wochenende und ich bin so aufgeregt!")
        assert r["floor"] == gespraech.JOB
        assert not gespraech.traegt_thema(sit, "Die Hochzeit wird riesig.")
        assert gespraech.budget(gespraech.TALK) == {}
    finally:
        os.environ.pop("TALK_SCHICHT", None)


# ---------------------------------------------------------------------------
# Frage-Anker (_nachbessern): still auf Talk, einmalig sonst
# ---------------------------------------------------------------------------

def _buchungs_sit() -> dict:
    """Sitzung mitten in der Aufnahme: alles da bis auf die Handynummer."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "", "frage": "telefon",
        "warSchonMal": False, "grund": "Kontrolle", "wunsch": {},
        "vorname": "Anna", "nachname": "Meier", "buchstabiert": True,
    })
    return sit


def test_anker_schweigt_auf_talk_floor():
    sit = _buchungs_sit()
    text = "Oh, eine Hochzeit — wie schoen! Da druecke ich fest die Daumen."
    raus = bianca_agent._nachbessern(sit, text, floor=gespraech.TALK)
    assert "Handynummer" not in raus
    assert raus.startswith("Oh, eine Hochzeit")


def test_anker_feuert_auf_job_floor():
    sit = _buchungs_sit()
    raus = bianca_agent._nachbessern(sit, "Alles klar.", floor=gespraech.JOB)
    assert "Handynummer" in raus


def test_anker_wiederholt_sich_nicht_wortgleich():
    sit = _buchungs_sit()
    frage = bianca_agent._kanonische_frage(sit, "telefon")
    assert frage
    sit["messages"] = [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": f"Gern. {frage}"},
        {"role": "user", "content": "Moment, mein Hund bellt gerade."},
        {"role": "assistant", "content": "Kein Problem, ich warte kurz."},
    ]
    raus = bianca_agent._nachbessern(sit, "Kein Problem, ich warte kurz.", floor=gespraech.ZURUECK)
    assert frage not in raus, "Dieselbe Frage nie zweimal in Folge wortgleich"


def test_talk_zug_schneidet_angehaengte_jobfrage_ab():
    """Talk-Probe 27.08.2026: das Modell haengte trotz Plan die Job-Frage an
    ("... alles Liebe. Worum geht es bei Ihrem Besuch?") — im Talk-Zug wird
    sie abgeschnitten, die Rueckkehr gehoert dem zurueck-/blended-Floor."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True, "frage": "grund",
              "arzt": {"typ": "genannt", "calendarId": "x"},
              "vorname": "Anna", "nachname": "Meier"})
    text = ("Das klingt nach einem wunderbaren Anlass! Ich wuensche Ihnen alles Liebe. "
            "Worum geht es denn bei Ihrem Besuch?")
    raus = bianca_agent._nachbessern(sit, text, floor=gespraech.TALK)
    assert "Worum" not in raus
    assert raus.endswith("alles Liebe.")


def test_namensfrage_frisst_keine_geschichte():
    """Talk-Probe 27.08.2026: 'ich bin ganz aufgeregt' wurde als Name
    'Ganz Aufgeregt' geerntet — Zustaende und Erzaehl-Prosa sind keine Namen."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True, "frage": "name",
              "arzt": {"typ": "genannt", "calendarId": "x"}})
    neu = gehirn.einsammeln(sit, "Ach, wissen Sie — meine Tochter heiratet naemlich, ich bin ganz aufgeregt!")
    assert not s["vorname"] and not s["nachname"]
    assert "vorname" not in neu and "nachname" not in neu and "name" not in neu


def test_zustand_ist_kein_name_aber_echter_name_bleibt():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True, "frage": "name",
              "arzt": {"typ": "genannt", "calendarId": "x"}})
    gehirn.einsammeln(sit, "Ich bin ganz aufgeregt!")
    assert not s["vorname"] and not s["nachname"]
    gehirn.einsammeln(sit, "Ich bin Paul Neumann.")
    assert s["vorname"] == "Paul" and s["nachname"] == "Neumann"


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_gespraech: alle gruen")
