"""W-FRAGE-GATE + W-JA-NACHGESTELLT — Anruf 1fbda5db (13.09.2026).

Chef woertlich: "es darf keine frage gestellt werden, zu der es bereits einen
wert gibt […] jede frage muss erst im session hirn ueberprueft werden bevor
bianca sie stellt, ob antworten vorhanden sind" und "die frage nach der
zhanreinigung kommt doppelt!!!!! warum ???!!!"

Live geschah beides: das MODELL bot in Zug 8 die Zahnreinigung an (der Sammler
wusste nichts davon), die Maschine fragte in Zug 13 erneut — und das "ja" des
Anrufers ("Hast du doch schon befragt, haben wir doch schon gesagt, ja.")
fiel durch, weil `_JA_RE` auf den Satzanfang verankert ist. Im Session-Hirn
stand danach `pzr="gefragt"`.

Die Gegenproben sind hier der teurere Fehler: das Gate darf der Maschine nie
die eigene Frage nehmen und das nachgestellte Ja nie eine Rueckfrage ("…,
ja?") als Zusage lesen — daran haengt auch das Buchungs-Okay.
"""

from bianca import gehirn
from kern import frage_gate


def _sit(**felder):
    sit = {"tenant": {"praxisName": "Testpraxis"}}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", **felder})
    return sit


# --- W-FRAGE-GATE: Job-Fragen des Modells ---------------------------------

def test_modell_fragt_zahnreinigung_waehrend_die_maschine_den_grund_will():
    # Der Live-Fall: offene Maschinenfrage war NICHT die Zahnreinigung.
    sit = _sit(frage="grund", vorname="Stefan", nachname="Rateike")
    text = ("Alles klar. Möchten Sie eine professionelle Zahnreinigung mit dazu?")
    raus, feld, belegt = frage_gate.saeubern(sit, text)
    assert feld == "pzr"
    assert belegt is False
    assert "Zahnreinigung" not in raus
    assert raus == "Alles klar."


def test_offene_maschinenfrage_bleibt_stehen():
    # Fragt die Maschine GERADE die Zahnreinigung, spricht das Modell nur aus,
    # worauf sie wartet — streichen wuerde ihr die Stimme nehmen.
    sit = _sit(frage="pzr", pzr="gefragt")
    text = "Die machen unsere Zahnärzte selbst. Soll die Zahnreinigung mit auf den Termin?"
    raus, feld, _ = frage_gate.saeubern(sit, text)
    assert feld == ""
    assert raus == text


def test_rueckfrage_gegen_belegten_wert_bleibt():
    # Genau die Form, die der Chef WILL: kurze Bestaetigung statt Frage.
    sit = _sit(frage="", vorname="Maximilian", nachname="Rateike")
    for text in ("Ihr Vorname ist Maximilian, richtig?",
                 "Sie sind gesetzlich versichert, korrekt?",
                 "Ich habe die Nummer null eins sieben sieben. Stimmt das so?"):
        raus, feld, _ = frage_gate.saeubern(sit, text)
        assert feld == "", text
        assert raus == text


def test_modell_fragt_die_zeit_im_nebensatz_waehrend_die_maschine_den_grund_will():
    """Live MedDent 14.09.2026 (Anruf e7191c7e, Zug 7/8): auf STT-Muell
    („Alles gut, wenn man das noch.“) erfand das Modell „also eine
    Routinekontrolle“ und fragte „Haben Sie denn eine Vorstellung, wann es
    Ihnen am besten passt?“ — die Maschine wartete noch auf den GRUND und
    stellte die Zeitfrage einen Zug spaeter selbst. Die Nebensatz-Form fiel
    durch das alte Muster (nur „wann passt/hätten/…“)."""
    sit = _sit(frage="grund", vorname="Michael", nachname="Petsas")
    for text in (
        "Verstehe. Haben Sie denn eine Vorstellung, wann es Ihnen am besten passt?",
        "Alles klar. Wann wäre es Ihnen denn recht?",
        "Gut. Lieber vormittags oder nachmittags?",
        "Verstehe. Wann Ihnen ein Termin am besten passen würde?",
    ):
        raus, feld, belegt = frage_gate.saeubern(sit, text)
        assert feld == "wunsch", text
        assert belegt is False
        assert "?" not in raus, (text, raus)
    # Gegenprobe: eine Rueckblick-Frage ist keine Wunsch-Frage.
    raus, feld, _ = frage_gate.saeubern(
        sit, "Wann waren Sie denn zuletzt bei uns?")
    assert feld == ""
    assert raus == "Wann waren Sie denn zuletzt bei uns?"
    # Und fragt die Maschine GERADE nach dem Wunsch, bleibt die Frage stehen.
    sit_w = _sit(frage="wunsch", grund="Kontrolle")
    text_w = "Gerne. Wann passt es Ihnen am besten — eher vormittags oder nachmittags?"
    raus_w, feld_w, _ = frage_gate.saeubern(sit_w, text_w)
    assert feld_w == "" and raus_w == text_w


def test_frage_nach_belegtem_feld_fliegt_mit_hinweis_belegt():
    sit = _sit(frage="wunsch", telefon="01776004600", telefonOk=True)
    raus, feld, belegt = frage_gate.saeubern(
        sit, "Gerne. Unter welcher Nummer erreichen wir Sie?")
    assert (feld, belegt) == ("telefon", True)
    assert "Nummer" not in raus


def test_ohne_laufende_aufgabe_bleibt_die_eroeffnung_stehen():
    # Kein modus = keine Maschine, die fragen koennte: der Opener bleibt.
    sit = {"tenant": {}}
    gehirn.sammler(sit)
    text = "Guten Tag. Worum geht es denn bei Ihrem Besuch?"
    raus, feld, _ = frage_gate.saeubern(sit, text)
    assert (feld, raus) == ("", text)


def test_sachfrage_ohne_job_feld_bleibt():
    sit = _sit(frage="grund")
    for text in ("Das habe ich nicht verstanden. Was meinen Sie damit?",
                 "Die Reinigung kostet ungefähr 120 Euro. Haben Sie noch Fragen?"):
        raus, feld, _ = frage_gate.saeubern(sit, text)
        assert feld == "", text
        assert raus == text


def test_aussage_ohne_fragezeichen_bleibt():
    sit = _sit(frage="grund", telefonOk=True)
    text = "Ich habe Ihre Nummer notiert und trage den Behandler ein."
    raus, feld, _ = frage_gate.saeubern(sit, text)
    assert (feld, raus) == ("", text)


def test_notaus_off_laesst_alles_stehen(monkeypatch):
    monkeypatch.setenv("FRAGE_GATE", "0")
    sit = _sit(frage="grund")
    text = "Möchten Sie eine professionelle Zahnreinigung mit dazu?"
    assert frage_gate.saeubern(sit, text) == (text, "", False)


def test_shadow_meldet_aber_aendert_nichts(monkeypatch):
    monkeypatch.setenv("FRAGE_GATE", "shadow")
    sit = _sit(frage="grund")
    text = "Möchten Sie eine Zahnreinigung mit dazu?"
    raus, feld, _ = frage_gate.saeubern(sit, text)
    assert feld == "pzr"
    assert raus == text


def test_agent_streicht_die_doppelte_zahnreinigungs_frage():
    from bianca import agent
    sit = _sit(frage="grund", vorname="Stefan", nachname="Rateike",
               warSchonMal=False)
    raus = agent._frage_gate_anwenden(
        sit, "Gut. Möchten Sie eine professionelle Zahnreinigung mit dazu?")
    assert "Zahnreinigung" not in raus
    assert any(x.get("w") == "frage-gate" for x in sit.get("_spur") or [])


# --- W-JA-NACHGESTELLT ----------------------------------------------------

def test_nachgestelltes_ja_zaehlt():
    satz = "Hast du doch schon befragt, haben wir doch schon gesagt, ja."
    assert gehirn.ist_ja(satz) is True
    assert gehirn.ist_nein(satz) is False
    assert gehirn.ist_pzr_zusage(satz) is True


def test_nachgestelltes_ja_landet_im_sammler(monkeypatch):
    from kern import motive
    monkeypatch.setattr(motive, "fuehrt_pzr", lambda sit: True)
    sit = _sit(frage="pzr", pzr="gefragt", grund="Kontrolle")
    neu = gehirn.einsammeln(
        sit, "Hast du doch schon befragt, haben wir doch schon gesagt, ja.")
    assert "pzr" in neu
    assert (sit["sammler"])["pzr"] == "ja"


def test_nachgestelltes_nein_zaehlt():
    assert gehirn.ist_nein("Das brauche ich nicht, nein.") is True
    assert gehirn.ist_ja("Das brauche ich nicht, nein.") is False


def test_rueckfrage_mit_ja_ist_keine_zusage():
    # "…, ja?" ist eine Vergewisserung des Anrufers, kein Okay — daran haengt
    # auch das Buchungs-Okay, deshalb hart ausgeschlossen.
    for satz in ("Das machen wir dann so, ja?", "Sie tragen das ein, ja?"):
        assert gehirn.ist_ja(satz) is False, satz


def test_nein_am_anfang_schlaegt_nachgestelltes_ja():
    satz = "Nein, das habe ich nicht gesagt, ja."
    assert gehirn.ist_nein(satz) is True
    assert gehirn.ist_ja(satz) is False


def test_prosa_mit_ja_in_der_mitte_ist_kein_ja():
    for satz in ("Ja sagen kann ich noch nicht, ich muss erst überlegen.",
                 "Wir haben gesagt, ja das klären wir später."):
        assert gehirn._ja_nachgestellt(gehirn._ohne_anlauf(satz)) is False, satz
