"""Session-Hirn + Intent-Schicht offline (W-HIRN/W-INTENT 03.09.2026).

Kein Netz: das Intent-LLM wird gestummt (monkeypatch auf kern.intent._chat),
geprueft werden Fast-Paths, Fallback-Heuristik, das Anliegen-Mapping in den
Sammler-Modus und die Gates in gehirn/flow/weiterleiten.
"""

import pytest

from bianca import flow, gehirn, weiterleiten
from kern import hirn, intent
from kern.tenants import laden


def _sit() -> dict:
    """Bianca-Sitzung wie im Betrieb: mit Stimme und leerem Hirn."""
    sit = {
        "stimme": "Bianca",
        "tenant": laden("meddent"),
        "messages": [{"role": "system", "content": "x"}],
    }
    hirn.init(sit)
    return sit


def _deutung(handlung: str, gegenstand: str = "VORGANG", *, zug: str = "wechseln",
             ersatz=None, spiegel: str = "") -> dict:
    return {"kanal": "ok", "zug": zug, "handlung": handlung,
            "gegenstand": gegenstand, "fuer": "selbst",
            "ersatz": ersatz, "spiegel": spiegel}


# --- Seed aus dem Chef-Auftrag (Lisa) --------------------------------------

def test_seed_absage_ohne_ersatz():
    a = hirn.seed_von_auftrag("Bitte den Termin am Donnerstag absagen.")
    assert a["handlung"] == "AENDERN" and a["ersatz"] is False


def test_seed_verschieben():
    a = hirn.seed_von_auftrag("Termin von Frau Berger auf naechste Woche verschieben")
    assert a["handlung"] == "AENDERN" and a["ersatz"] is True


def test_seed_recall_ist_anlegen():
    a = hirn.seed_von_auftrag("Kontrolltermin anbieten, Recall 6 Monate")
    assert a["handlung"] == "ANLEGEN"


def test_seed_nachricht_ist_abgeben():
    a = hirn.seed_von_auftrag("Bitte ausrichten, dass die Praxis Freitag zu ist")
    assert a["handlung"] == "ABGEBEN"


# --- Mapping Anliegen -> Maschine ------------------------------------------

def test_anlegen_schaltet_buchen():
    sit = _sit()
    aus = hirn.anwenden(sit, _deutung("ANLEGEN", spiegel="Termin zur Kontrolle"))
    s = sit["sammler"]
    assert aus["zug"] == "erstes"
    assert s["modus"] == "buchen" and sit.get("hirnModusNeu") is True


def test_erreichen_bucht_nicht_und_legt_maschine_still():
    sit = _sit()
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    sit.pop("hirnModusNeu", None)
    hirn.anwenden(sit, _deutung("ERREICHEN", "PERSON", spiegel="Doktor Petsas sprechen"))
    s = sit["sammler"]
    assert s["modus"] == ""  # keine Buchungsfrage mehr
    assert sit.get("hirnVerbinden", {}).get("person")


def test_wechseln_parkt_und_schaltet_absagen():
    sit = _sit()
    hirn.anwenden(sit, _deutung("ANLEGEN", spiegel="neuer Termin"))
    aus = hirn.anwenden(sit, _deutung("AENDERN", ersatz=False, spiegel="Termin absagen"))
    s = sit["sammler"]
    assert aus["zug"] == "wechseln"
    assert s["modus"] == "absagen"
    stati = {a["status"] for a in sit["hirn"]["anliegen"]}
    assert "geparkt" in stati and "aktiv" in stati


def test_zweites_wartet_aktives_laeuft_weiter():
    sit = _sit()
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    aus = hirn.anwenden(sit, _deutung("WISSEN", "SACHE", zug="zweites",
                                      spiegel="ist die Schiene fertig"))
    assert aus["anliegen"]["handlung"] == "ANLEGEN"  # aktiv bleibt
    assert sit["sammler"]["modus"] == "buchen"
    offen = [a for a in sit["hirn"]["anliegen"] if a["status"] == "offen"]
    assert len(offen) == 1 and offen[0]["handlung"] == "WISSEN"


def test_zurueck_reaktiviert_geparktes():
    sit = _sit()
    hirn.anwenden(sit, _deutung("ANLEGEN", spiegel="neuer Termin"))
    hirn.anwenden(sit, _deutung("AENDERN", ersatz=False))
    aus = hirn.anwenden(sit, {"kanal": "ok", "zug": "zurueck"})
    assert aus["anliegen"]["handlung"] == "ANLEGEN"
    assert sit["sammler"]["modus"] == "buchen"


def test_sync_erledigt_und_naechstes_rueckt_nach():
    sit = _sit()
    hirn.anwenden(sit, _deutung("AENDERN", ersatz=False, spiegel="Termin absagen"))
    hirn.anwenden(sit, _deutung("ANLEGEN", zug="zweites", spiegel="neuer Termin"))
    sit["sammler"]["phase"] = "fertig"  # Maschine hat den Storno abgeschlossen
    hirn.sync_nach_zug(sit)
    a = hirn.aktiv(sit)
    assert a is not None and a["handlung"] == "ANLEGEN"
    assert sit["sammler"]["modus"] == "buchen"


def test_kanal_tot_aendert_nichts():
    sit = _sit()
    hirn.anwenden(sit, {"kanal": "tot", "zug": "wechseln", "handlung": "ANLEGEN"})
    assert hirn.aktiv(sit) is None
    assert (sit.get("sammler") or {}).get("modus", "") == ""


# --- Gate: die Regex oeffnet den Modus nicht mehr, wenn das Hirn regiert ---

def test_einsammeln_setzt_keinen_modus_mit_hirn():
    sit = _sit()
    gehirn.einsammeln(sit, "Ich haette gern naechste Woche einen Termin zur Kontrolle")
    s = gehirn.sammler(sit)
    assert s["modus"] == ""  # nur das Hirn schaltet
    assert s["grund"]  # Ernte laeuft weiter


def test_einsammeln_altverhalten_ohne_hirn():
    sit = {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}
    gehirn.einsammeln(sit, "Ich moechte meinen Termin absagen")
    assert gehirn.sammler(sit)["modus"] == "absagen"


def test_notaus_intent_schicht_0(monkeypatch):
    monkeypatch.setenv("INTENT_SCHICHT", "0")
    sit = _sit()
    gehirn.einsammeln(sit, "Ich moechte meinen Termin absagen")
    assert gehirn.sammler(sit)["modus"] == "absagen"


# --- Intent: Fast-Path, Fallback, Parser ------------------------------------

def _llm_verboten(monkeypatch):
    def kaputt(*a, **k):
        raise AssertionError("LLM-Call verboten (Fast-Path erwartet)")
    monkeypatch.setattr(intent, "_chat", kaputt)


def _llm_tot(monkeypatch):
    monkeypatch.setattr(intent, "_chat", lambda *a, **k: {"ok": False, "error": "test"})


def test_fastpath_ziffern_kein_llm(monkeypatch):
    _llm_verboten(monkeypatch)
    sit = _sit()
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    sit["sammler"]["frage"] = "telefon"
    d = intent.erkennen(sit, "0176 448 39 51")
    assert d["zug"] == "verfeinern" and d["quelle"] == "fastpath"


def test_fastpath_ja_kein_llm(monkeypatch):
    _llm_verboten(monkeypatch)
    sit = _sit()
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    d = intent.erkennen(sit, "Ja, genau.")
    assert d["zug"] == "verfeinern"


def test_fastpath_slotwahl_kein_llm(monkeypatch):
    _llm_verboten(monkeypatch)
    sit = _sit()
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    sit["sammler"]["phase"] = "angebot"
    d = intent.erkennen(sit, "Der erste, um 10 Uhr.")
    assert d["zug"] == "verfeinern"


def test_wechselwort_heuristik_sofort(monkeypatch):
    _llm_tot(monkeypatch)  # synchron entscheidet IMMER die Heuristik (0 ms)
    sit = _sit()
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    sit["sammler"]["frage"] = "telefon"
    d = intent.erkennen(sit, "Moment, eigentlich will ich nur den Doktor sprechen")
    assert d["handlung"] == "ERREICHEN" and d["quelle"] == "heuristik"


def test_schnellstrasse_erreichen_ohne_llm(monkeypatch):
    _llm_verboten(monkeypatch)  # eindeutiger Erstsatz: 0 ms, kein LLM
    d = intent.erkennen(_sit(), "Kann ich bitte mit Doktor Petsas sprechen?")
    assert d["handlung"] == "ERREICHEN" and d["quelle"] == "schnell"


def test_schnellstrasse_terminwunsch_ohne_llm(monkeypatch):
    _llm_verboten(monkeypatch)
    d = intent.erkennen(_sit(), "Guten Tag, ich haette gern einen Termin zur Kontrolle.")
    assert d["handlung"] == "ANLEGEN" and d["quelle"] == "schnell"


def test_ernte_im_anliegen_ohne_llm(monkeypatch):
    _llm_verboten(monkeypatch)  # kein Wechsel-Signal -> kein LLM-Aufschlag
    sit = _sit()
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    d = intent.erkennen(sit, "Naechste Woche vormittags waere super, am liebsten Dienstag.")
    assert d["zug"] == "halten" and d["quelle"] == "fastpath-still"


def test_negation_heuristik_und_nachzug(monkeypatch):
    _llm_tot(monkeypatch)  # Verneinung: nie Schnellstrasse -> Heuristik sofort
    d = intent.erkennen(_sit(), "Ich will den Termin nicht absagen, nur verschieben.")
    assert d["handlung"] == "AENDERN" and d["ersatz"] is True
    assert d["quelle"] == "heuristik"


def test_nachzug_korrigiert_im_naechsten_zug(monkeypatch):
    """Heuristik entscheidet sofort, das Hintergrund-LLM lenkt den Zug
    danach um — ohne dass je ein Zug auf das Modell gewartet hat."""
    import time as _time

    antwort = ('{"zug":"wechseln","handlung":"ERREICHEN","gegenstand":"PERSON",'
               '"fuer":"selbst","ersatz":null,"spiegel":"Doktor sprechen"}')
    monkeypatch.setattr(intent, "_chat", lambda *a, **k: {"ok": True, "text": antwort})
    sit = _sit()
    sit["id"] = "test-nachzug"
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    # Mehrdeutiger Satz: Heuristik sagt nichts Klares, LLM laeuft hinterher.
    d = intent.erkennen(sit, "Ja also, der Herr Doktor, wissen Sie...")
    assert d["quelle"] == "heuristik"
    for _ in range(50):  # Hintergrund-Future fertig werden lassen
        spaet = intent.nachzug(sit)
        if spaet is not None:
            break
        _time.sleep(0.02)
    assert spaet is not None and spaet["quelle"] == "nachzug"
    hirn.anwenden(sit, spaet)
    a = hirn.aktiv(sit)
    assert a is not None and a["handlung"] == "ERREICHEN"
    assert sit["sammler"]["modus"] == ""  # Buchungsmaschine still gelegt


def test_zahnschmerzen_starten_buchung(monkeypatch):
    """Chef-Testanruf 03.09.2026 abends: 'Ich glaube, ich habe Zahnschmerzen.'
    muss SOFORT (0 ms) als Terminwunsch erkannt werden — vorher sagte die
    Heuristik KEINE und das Buchen sprang nie an."""
    _llm_verboten(monkeypatch)
    sit = _sit()
    d = intent.erkennen(sit, "Ich glaube, ich habe Zahnschmerzen.")
    assert d["handlung"] == "ANLEGEN" and d["quelle"] == "schnell"
    hirn.anwenden(sit, d)
    assert sit["sammler"]["modus"] == "buchen"


def test_symptom_plus_terminwunsch_bleibt_schnell(monkeypatch):
    _llm_verboten(monkeypatch)
    d = intent.erkennen(_sit(), "Ich habe Zahnschmerzen und brauche einen Termin.")
    assert d["handlung"] == "ANLEGEN" and d["quelle"] == "schnell"


def test_preisfrage_ist_kein_symptom(monkeypatch):
    _llm_verboten(monkeypatch)
    d = intent.erkennen(_sit(), "Was kostet eine Krone bei Ihnen?")
    assert d["handlung"] == "WISSEN"


def test_schmerzen_weg_absage_gewinnt(monkeypatch):
    _llm_tot(monkeypatch)
    d = intent.erkennen(_sit(), "Die Schmerzen sind weg, ich will den Termin absagen.")
    assert d["handlung"] == "AENDERN" and d["ersatz"] is False


def test_symptom_mitten_im_anliegen_wechselt(monkeypatch):
    _llm_tot(monkeypatch)
    sit = _sit()
    hirn.anwenden(sit, _deutung("WISSEN", gegenstand="REGEL"))
    d = intent.erkennen(sit, "Ich habe uebrigens ganz schlimme Zahnschmerzen.")
    assert d["handlung"] == "ANLEGEN"


def test_klare_heuristik_startet_kein_llm(monkeypatch):
    """Hat die Heuristik eine Handlung erkannt, bleibt das vLLM unbelaestigt
    — jeder gesparte Aufruf schont die GPU von TTS/STT (Aussetzer 03.09.)."""
    _llm_verboten(monkeypatch)
    sit = _sit()
    sit["id"] = "test-drossel-klar"
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    d = intent.erkennen(sit, "Moment, eigentlich will ich nur den Doktor sprechen")
    assert d["handlung"] == "ERREICHEN"
    assert "test-drossel-klar" not in intent._NACHZUG  # kein Hintergrund-Auftrag


def test_nachzug_ueberholt_nie(monkeypatch):
    """Pro Sitzung hoechstens EIN Hintergrund-Auftrag: ein laufender wird
    von neuen unklaren Saetzen nicht ueberholt (GPU-Drossel)."""
    import threading
    import time as _time

    bremse = threading.Event()

    def _lahm(*a, **k):
        bremse.wait(timeout=5)
        return {"ok": False, "error": "test-ende"}

    monkeypatch.setattr(intent, "_chat", _lahm)
    sit = _sit()
    sit["id"] = "test-drossel-flug"
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    intent.erkennen(sit, "Ja also, der Herr Doktor, wissen Sie...")
    erster = intent._NACHZUG["test-drossel-flug"][0]
    intent.erkennen(sit, "Hm, tja, der Doktor, also wie soll ich sagen...")
    assert intent._NACHZUG["test-drossel-flug"][0] is erster  # nicht ersetzt
    bremse.set()
    for _ in range(50):
        if erster.done():
            break
        _time.sleep(0.02)
    intent._NACHZUG.pop("test-drossel-flug", None)  # aufraeumen


def test_fallback_absage_ohne_ersatz(monkeypatch):
    _llm_tot(monkeypatch)
    d = intent.erkennen(_sit(), "Ich muss den Termin leider absagen.")
    assert d["handlung"] == "AENDERN" and d["ersatz"] is False


def test_fallback_expliziter_terminwunsch(monkeypatch):
    _llm_tot(monkeypatch)
    d = intent.erkennen(_sit(), "Ich moechte gern einen Termin vereinbaren.")
    assert d["handlung"] == "ANLEGEN"


def test_fallback_floskel_bucht_nie(monkeypatch):
    _llm_tot(monkeypatch)
    d = intent.erkennen(_sit(), "Aeh ja hallo, also, wie soll ich sagen")
    assert d["handlung"] == "KEINE"  # NIE Default-buchen


def test_fallback_absage_im_angebot_ist_verfeinern(monkeypatch):
    _llm_tot(monkeypatch)
    sit = _sit()
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    sit["sammler"]["phase"] = "angebot"
    d = intent.erkennen(sit, "Nein, den koennen Sie absagen, der passt nicht.")
    assert d["zug"] == "verfeinern" and d["handlung"] == "KEINE"


def test_parse_llm_json():
    d = intent._parse('Hier: {"kanal":"ok","zug":"wechseln","handlung":"WISSEN",'
                      '"gegenstand":"SACHE","fuer":"selbst","ersatz":null,'
                      '"spiegel":"ist die Schiene fertig"} fertig')
    assert d and d["handlung"] == "WISSEN" and d["gegenstand"] == "SACHE"


def test_parse_muell_ist_none():
    assert intent._parse("Das ist kein JSON") is None
    assert intent._parse('{"handlung":"QUATSCH"}') is None


# --- Einbau: weiterleiten + ABGEBEN-Zweig -----------------------------------

def test_weiterleiten_mit_hirnzettel():
    sit = _sit()
    sit["hirnVerbinden"] = {"person": "Doktor Petsas sprechen"}
    aus = weiterleiten.zug(sit, "Ich haette gern den Herrn Petsas.")
    assert aus is not None and aus.get("text")
    assert "hirnVerbinden" not in sit  # Zettel verbraucht


def test_abgeben_fragt_name_dann_notiz(tmp_path, monkeypatch):
    import bianca.verwalten as verwalten
    monkeypatch.setattr(verwalten, "DATA_DIR", tmp_path)
    sit = _sit()
    hirn.anwenden(sit, _deutung("ABGEBEN", "SACHE", spiegel="Rueckruf wegen Rechnung"))
    aus = flow.zug(sit, "Rufen Sie mich bitte wegen der Rechnung zurueck.")
    assert aus and "Name" in aus["text"]
    s = gehirn.sammler(sit)
    s["vorname"], s["nachname"] = "Martin", "Berger"
    s["telefon"] = "01764483951"
    aus2 = flow.zug(sit, "Berger, Martin Berger.")
    assert aus2 and "notiert" in aus2["text"]
    assert sit.get("praxisNotiz")
    assert (tmp_path / "praxis_notizen.jsonl").exists()
    a = [x for x in sit["hirn"]["anliegen"] if x["handlung"] == "ABGEBEN"][0]
    assert a["status"] == "erledigt"
