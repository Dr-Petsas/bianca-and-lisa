"""Schaden im Satz wird dringend: heute suchen, einmal sagen, Praxis entscheidet."""

from __future__ import annotations

import pytest

from bianca import agent, besuchsgrund, flow, gehirn, session
from kern import dringlichkeit, eilig, intent
from kern.tenants import laden


def _sit(name: str) -> dict:
    return session.neu(tenant=laden(name))


def test_cluster_und_gegenbeispiele():
    zahn = "zahnmedizin"
    assert dringlichkeit.bewerten("Mir ist die Brücke lose.", zahn)["cluster"] == "ze"
    assert dringlichkeit.bewerten("Prothese kaput.", zahn)["kern"] == "Reparatur Zahnersatz"
    assert dringlichkeit.bewerten("zahn a bgebrochen", zahn)["cluster"] == "zahn"
    assert dringlichkeit.bewerten("Ich möchte eine neue Brücke.", zahn)["stufe"] == 0
    assert dringlichkeit.bewerten("Die Prothese soll nur angepasst werden.", zahn)["stufe"] == 0
    assert dringlichkeit.bewerten(
        "Ich brauche dringend einen Termin zur Kontrolle.", zahn)["stufe"] == 0
    assert dringlichkeit.bewerten("nichts Akutes, nur Kontrolle.", zahn)["stufe"] == 0
    assert not eilig.erkannt(
        "Ich brauche dringend einen Termin zur Kontrolle.", laden("meddent"))

    haut = dringlichkeit.bewerten("Ich brauche eine Melanomuntersuchung.", "dermatologie")
    assert haut["cluster"] == "melanom"
    assert dringlichkeit.bewerten("Hautscreening bitte.", "dermatologie")["stufe"] == 0
    haut_abszess = dringlichkeit.bewerten(
        "Abszess in der Schwangerschaft im Intimbereich.", "dermatologie")
    assert haut_abszess["cluster"] == "haut"
    assert haut_abszess["kern"] == "akute Beschwerden/Notfall"

    gyn = dringlichkeit.bewerten(
        "Abszess in der Schwangerschaft im Intimbereich.", "gynaekologie")
    assert gyn["stufe"] == 2 and gyn["cluster"] == "gyn"
    assert dringlichkeit.bewerten("Schwangerschaftsvorsorge.", "gynaekologie")["stufe"] == 0

    fremd = dringlichkeit.bewerten(
        "Abszess in der Schwangerschaft im Intimbereich.", zahn)
    assert fremd["cluster"] == "fremd" and fremd["kern"] == ""
    assert dringlichkeit.bewerten("Mir ist die Brücke lose.", "dermatologie")["stufe"] == 0


def test_fenster_klebt_und_entwarnung_setzt_zurueck():
    sit = {"tenant": {"fachgebiet": "zahnmedizin"}, "messages": [
        {"role": "user", "content": "Mir ist die Brücke."},
    ]}
    karte = dringlichkeit.merken(sit, "Sie ist lose.")
    assert karte["stufe"] == 2 and karte["cluster"] == "ze"
    dringlichkeit.merken(sit, "Ja.")
    assert dringlichkeit.stufe(sit) == 2
    dringlichkeit.merken(sit, "Nein, nichts Akutes, nur Kontrolle.")
    assert dringlichkeit.stufe(sit) == 0


def test_meddent_bruecke_sucht_ab_heute():
    sit = _sit("meddent")
    gehirn.einsammeln(sit, "Mir ist die Brücke lose.")
    s = gehirn.sammler(sit)
    assert s["grund"] == "Reparatur Zahnersatz"
    assert s["wunsch"]["date"] == eilig.heute_iso()
    assert dringlichkeit.stufe(sit) == 2
    text = dringlichkeit.voranstellen(sit, "Wann passt es Ihnen?")
    assert text.startswith(dringlichkeit.SATZ_HEUTE)
    assert dringlichkeit.voranstellen(sit, "Und der Name?") == "Und der Name?"


def test_neue_bruecke_bleibt_beratung():
    sit = _sit("meddent")
    gehirn.einsammeln(sit, "Ich möchte eine neue Brücke.")
    s = gehirn.sammler(sit)
    assert dringlichkeit.stufe(sit) == 0
    assert s.get("grund") != "Reparatur Zahnersatz"


def test_thaler_behaelt_besprechung_sucht_aber_heute():
    sit = _sit("thaler")
    gehirn.einsammeln(sit, "Mir ist die Brücke lose.")
    s = gehirn.sammler(sit)
    assert dringlichkeit.stufe(sit) == 2
    assert s["wunsch"]["date"] == eilig.heute_iso()
    assert s["grund"] != "Reparatur Zahnersatz"
    assert "zahnersatz" in (s.get("grund") or "").lower()


def test_blessing_abszess_in_der_schwangerschaft_kommt_sofort():
    sit = _sit("blessing")
    rep = flow.zug(sit, "Abszess in der Schwangerschaft im Intimbereich.")
    assert rep and rep.get("hangup") is True
    low = (rep.get("text") or "").lower()
    assert "jetzt" in low
    assert "ärztliche untersuchung" not in low
    assert "schwangerschaftsvorsorge" not in low
    assert gehirn.sammler(sit).get("grund") != "Schwangerschaftsvorsorge"


def test_blessing_melanom_haengt_nicht_doppelt():
    sit = _sit("blessing")
    sit["eiligKomme"] = True
    sit["dringlichkeit"] = {"stufe": 2, "cluster": "melanom", "kern": "x", "muster": []}
    text = eilig.KOMMEN_SATZ
    assert dringlichkeit.voranstellen(sit, text) == text
    assert dringlichkeit.sofort_text(sit, "Melanomuntersuchung.") == ""


def test_intent_oeffnet_schaden_absage_bleibt():
    med = {"tenant": laden("meddent")}
    deutung = intent._fallback(med, "Mir ist die Brücke lose.")
    assert deutung["handlung"] == "ANLEGEN"
    absage = intent._fallback(med, "Ich möchte meinen Termin absagen.")
    assert absage["handlung"] == "AENDERN"


def test_zahnarzt_bucht_den_intimabszess_nicht_als_reparatur():
    sit = _sit("meddent")
    gehirn.einsammeln(sit, "Abszess in der Schwangerschaft im Intimbereich.")
    assert gehirn.sammler(sit).get("grund") != "Reparatur Zahnersatz"
    assert not dringlichkeit.oeffnet_buchung(
        "Abszess in der Schwangerschaft im Intimbereich.", laden("meddent"))


def test_notaus(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DRINGLICHKEIT", "0")
    assert dringlichkeit.bewerten("Brücke lose", "zahnmedizin")["stufe"] == 0
    assert not dringlichkeit.oeffnet_buchung("Brücke lose", laden("meddent"))
    sit = {"dringlichkeit": {"stufe": 2, "cluster": "ze"}}
    assert dringlichkeit.voranstellen(sit, "Frage?") == "Frage?"


def test_maschinenantwort_stellt_satz_vor():
    sit = _sit("meddent")
    gehirn.einsammeln(sit, "Mir ist die Brücke lose.")
    msgs = [{"role": "user", "content": "Mir ist die Brücke lose."}]
    aus = agent._maschinen_antwort(sit, {"text": "Wie ist Ihr Nachname?"}, msgs)
    assert aus["text"].startswith(dringlichkeit.SATZ_HEUTE)
    assert aus["text"].rstrip().endswith("?")
