"""Speicherweg Praxis-Layer: veroeffentlichter Vertrag wirkt am Telefon.

Die Gegenproben sind hier der teurere Teil: eine verbogene Ablage-Datei darf
den Kern nie in einen unmoeglichen Zustand bringen, eine fremde Kennung nie
ausserhalb des Ordners schreiben, und ohne Ablage muss sich JEDE Praxis
byte-identisch wie vorher verhalten.
"""

import json

import pytest

from bianca.controller import dialog_policy as dp
from bianca.controller import policy as pol
from kern import policy_ablage, tenants


@pytest.fixture(autouse=True)
def _eigener_ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(policy_ablage, "ORDNER", tmp_path / "dialogpolicy")
    monkeypatch.delenv("DIALOG_POLICY_ABLAGE", raising=False)


def _vertrag(**kw):
    p = dp.sicher_default()
    d = p.as_dict()
    d.update(kw)
    return d


# --------------------------------------------------------------- Schreiben


def test_schreiben_und_lesen_bringt_den_vertrag_zurueck():
    v = _vertrag()
    aus = policy_ablage.schreiben("meddent", v, wer="chef", notiz="Feldtest")
    assert aus["ok"], aus
    gelesen = policy_ablage.policy("meddent")
    assert gelesen == v
    stand = policy_ablage.alle()
    assert [e["tenant"] for e in stand] == ["meddent"]
    assert stand[0]["wer"] == "chef"


def test_leerer_vertrag_wird_nicht_abgelegt():
    assert not policy_ablage.schreiben("meddent", {})["ok"]
    assert policy_ablage.policy("meddent") is None


@pytest.mark.parametrize("kennung", ["../fremd", "a/b", "", "mit leer", "x" * 80])
def test_unzulaessige_kennung_schreibt_nichts(kennung):
    aus = policy_ablage.schreiben(kennung, _vertrag())
    assert not aus["ok"]
    assert policy_ablage.pfad(kennung) is None


def test_notaus_liest_nichts_und_schreibt_nichts(monkeypatch):
    policy_ablage.schreiben("meddent", _vertrag())
    monkeypatch.setenv("DIALOG_POLICY_ABLAGE", "0")
    assert policy_ablage.policy("meddent") is None
    assert not policy_ablage.schreiben("thaler", _vertrag())["ok"]
    assert policy_ablage.alle() == []


def test_zuruecknehmen_raeumt_die_datei():
    policy_ablage.schreiben("meddent", _vertrag())
    assert policy_ablage.loeschen("meddent")["ok"]
    assert policy_ablage.policy("meddent") is None
    # Zweites Loeschen ist kein Fehler.
    assert policy_ablage.loeschen("meddent")["ok"]


# ------------------------------------------------------------ Wirkung live


def test_tenant_laden_traegt_den_veroeffentlichten_vertrag():
    policy_ablage.schreiben("meddent", _vertrag(revision=7))
    t = tenants.laden("meddent")
    assert t["dialogPolicy"]["revision"] == 7
    assert t["_dialogPolicyQuelle"] == "ablage"
    # Und der produktive Reducer-Weg sieht ihn auch.
    assert pol.aus_tenant(t).policy_revision == 7


def test_ohne_ablage_bleibt_der_mandant_unveraendert():
    t = tenants.laden("meddent")
    assert "_dialogPolicyQuelle" not in t
    # meddent traegt selbst keinen Vertrag — Legacy-Projektion wie bisher.
    assert not isinstance(t.get("dialogPolicy"), dict) or not t["dialogPolicy"]


def test_eigener_vertrag_am_mandanten_schlaegt_die_ablage():
    policy_ablage.schreiben("meddent", _vertrag(revision=7))
    t = {"_id": "meddent", "dialogPolicy": _vertrag(revision=99)}
    policy_ablage.anreichern(t)
    assert t["dialogPolicy"]["revision"] == 99
    assert "_dialogPolicyQuelle" not in t


def test_kaputte_ablage_datei_faellt_auf_legacy_zurueck():
    policy_ablage.ORDNER.mkdir(parents=True, exist_ok=True)
    (policy_ablage.ORDNER / "meddent.json").write_text("{kein json", encoding="utf-8")
    assert policy_ablage.policy("meddent") is None
    t = tenants.laden("meddent")
    assert "_dialogPolicyQuelle" not in t


def test_ablage_ohne_policy_feld_gilt_als_leer():
    policy_ablage.ORDNER.mkdir(parents=True, exist_ok=True)
    (policy_ablage.ORDNER / "meddent.json").write_text(
        json.dumps({"tenant": "meddent", "wer": "x"}), encoding="utf-8"
    )
    assert policy_ablage.policy("meddent") is None


def test_verbogener_vertrag_landet_im_sicheren_default():
    # Von Hand in die Datei geschrieben: Pflichtfelder fehlen, Werte absurd.
    policy_ablage.schreiben("meddent", {"schemaVersion": 1, "gespraech": {"max_stupse": 999}})
    t = tenants.laden("meddent")
    p = pol.aus_tenant(t)
    # Der Deckel der Invarianten haelt — keine 999 Stupse am Telefon.
    unten, oben = dp.GRENZEN["max_stupse"]
    assert unten <= p.max_stupse <= oben
