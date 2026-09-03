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


def test_wechselwort_geht_ans_llm(monkeypatch):
    _llm_tot(monkeypatch)  # LLM tot -> Fallback muss greifen
    sit = _sit()
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    sit["sammler"]["frage"] = "telefon"
    d = intent.erkennen(sit, "Moment, eigentlich will ich nur den Doktor sprechen")
    assert d["handlung"] == "ERREICHEN"


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


def test_negation_geht_ans_llm(monkeypatch):
    _llm_tot(monkeypatch)  # Verneinung: nie Schnellstrasse, LLM (hier: Fallback)
    d = intent.erkennen(_sit(), "Ich will den Termin nicht absagen, nur verschieben.")
    assert d["handlung"] == "AENDERN" and d["ersatz"] is True
    assert d["quelle"] == "fallback"


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
