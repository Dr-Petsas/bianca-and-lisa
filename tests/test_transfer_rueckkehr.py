"""W-TRANSFER-RUECKKEHR (13.09.2026): nach einem Verbinde-Versuch geht es in
DERSELBEN Sitzung weiter — nie auf null.

Chef (woertlich): "bei nicht erfolgreichem Verbinden darf nicht auf 0
zurueckgefallen werden im Gespraech!!! es muss da weiter gehen wo man
aufgehoert hat."

Offline: kein LLM, kein Netz, kein TTS. Ein LLM-Aufruf in diesen Tests ist
ein Testbruch — die Fortsetzung ist deterministisch.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bianca import agent, gehirn, rueckkehr, session
from kern import gedaechtnis, hirn, llm
from kern.tenants import laden

DID = "+4921154244110"
CALLER = "+4915112345678"
_WL = [{"name": "Dr. Petsas", "nummer": "+49211111111", "hinweis": ""},
       {"name": "Dr. Patrikis", "nummer": "+49211222222", "hinweis": ""}]


def _s(v) -> str:
    return " ".join(str(v or "").split()).strip()


def _kein_llm(monkeypatch) -> None:
    def platzt(*a, **k):
        raise AssertionError("Rueckkehr muss ohne LLM laufen")
    monkeypatch.setattr(llm, "chat", platzt)
    monkeypatch.setattr(llm, "chat_stream", platzt)


def _sit_sip() -> dict:
    t = dict(laden("meddent"))
    t["weiterleitungen"] = [dict(e) for e in _WL]
    t["verbindenErlaubt"] = ["Petsas", "Patrikis"]
    sit = session.neu(tenant=t)
    sit["clientKind"] = "sip"
    sit["did"] = DID
    sit["callerPhone"] = CALLER
    sit["messages"] = [{"role": "system", "content": "x"},
                       {"role": "assistant", "content": "Guten Tag, was kann ich für Sie tun?"}]
    return sit


def _transfer(sit: dict, satz: str = "Verbinden Sie mich bitte mit Doktor Petsas.") -> dict:
    aus = agent.user_turn(sit, satz)
    assert aus.get("transfer", {}).get("nummer") == "+49211111111", aus
    assert aus.get("hangup") is True
    assert sit.get("weiterleitungZiel")
    return aus


# ---------------------------------------------------------------------------
# passt(): nur die eigene Sitzung wird fortgesetzt
# ---------------------------------------------------------------------------

def test_passt_erkennt_die_eigene_sitzung(monkeypatch):
    _kein_llm(monkeypatch)
    sit = _sit_sip()
    _transfer(sit)
    assert rueckkehr.passt(sit, did=DID, caller=CALLER) == ""
    # Bruecke liefert die Nummern in anderer Schreibweise — Normalform zaehlt.
    assert rueckkehr.passt(sit, did="004921154244110", caller="015112345678") == ""


def test_passt_lehnt_fremde_anrufe_ab(monkeypatch):
    _kein_llm(monkeypatch)
    sit = _sit_sip()
    assert rueckkehr.passt(sit, did=DID, caller=CALLER) == "kein-transfer"
    _transfer(sit)
    assert rueckkehr.passt(sit, did="+4921154244120", caller=CALLER) == "did-fremd"
    assert rueckkehr.passt(sit, did=DID, caller="+4917099999999") == "anrufer-fremd"
    assert rueckkehr.passt(None, did=DID, caller=CALLER) == "unbekannt"
    alt = dict(sit)
    alt["startedAt"] = "2020-01-01T00:00:00+00:00"
    assert rueckkehr.passt(alt, did=DID, caller=CALLER) == "zu-alt"


def test_unterdrueckte_nummer_passt_ueber_die_did(monkeypatch):
    """Anonymer Anrufer: die Bruecke kennt keinen Caller — dann entscheidet
    die DID (die UUID der Bruecke ist in dem Fall ohnehin nur DID + Polster)."""
    _kein_llm(monkeypatch)
    sit = _sit_sip()
    sit.pop("callerPhone", None)
    _transfer(sit)
    assert rueckkehr.passt(sit, did=DID, caller="") == ""


def test_notaus_liefert_frischen_anruf(monkeypatch):
    _kein_llm(monkeypatch)
    monkeypatch.setenv("TRANSFER_RUECKKEHR", "0")
    sit = _sit_sip()
    _transfer(sit)
    assert rueckkehr.aufnehmen(sit["id"], did=DID, caller=CALLER) is None


# ---------------------------------------------------------------------------
# Fortsetzung: keine Begruessung, offene Frage kommt zurueck
# ---------------------------------------------------------------------------

def test_rueckkehr_mitten_in_der_buchung_setzt_dort_fort(monkeypatch):
    """Buchung laeuft (Nachname steht, Vorname offen), Anrufer will zu Doktor
    Petsas, Behandler nimmt nicht ab (schnelle Rueckkehr): Bianca begruesst
    NICHT neu, sagt ehrlich, dass die Verbindung nicht zustande kam, und
    stellt die offene Vornamen-Frage — der Nachname bleibt stehen."""
    _kein_llm(monkeypatch)
    sit = _sit_sip()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["nachname"] = "Berger"
    s["warSchonMal"] = True
    s["frage"] = "vorname"
    sit["flussFrage"] = "Und Ihr Vorname?"
    hirn.anwenden(sit, {"zug": "wechseln", "handlung": "ANLEGEN", "gegenstand": "VORGANG",
                        "ersatz": None, "spiegel": "Termin buchen"})
    assert _s((hirn.aktiv(sit) or {}).get("handlung")) == "ANLEGEN"
    _transfer(sit)
    assert _s((hirn.aktiv(sit) or {}).get("handlung")) == "ERREICHEN"

    alt = rueckkehr.aufnehmen(sit["id"], did=DID, caller=CALLER,
                              schnell=True, seit_s=4.2, ziel="Dr. Petsas")
    assert alt is sit
    aus = agent.start_reply(sit)
    text = aus["text"]
    assert text.startswith("Da bin ich wieder")
    assert "nicht zustande gekommen" in text
    assert "Doktor Petsas" in text
    assert "Guten Tag" not in text and "Bianca" not in text.split("—")[0]
    # Die Buchung ist zurueck, der Nachname steht, die Vornamen-Frage kommt.
    assert _s((hirn.aktiv(sit) or {}).get("handlung")) == "ANLEGEN"
    assert gehirn.sammler(sit)["nachname"] == "Berger"
    assert "Vorname" in text
    # Nur einmal gesprochen.
    assert rueckkehr.offen(sit) is None
    assert sit["transferRueckkehrN"] == 1
    assert sit["transferHistorie"][0]["ziel"] == "Dr. Petsas"
    assert sit["transferHistorie"][0]["schnell"] is True
    # Der Verbinde-Zettel ist bedient — kein zweiter Transfer beim naechsten Satz.
    assert sit.get("weiterleiten") == {}
    assert not sit.get("weiterleitungZiel")
    assert not sit.get("hirnVerbinden")


def test_rueckkehr_ohne_offene_aufgabe_oeffnet_die_tuer(monkeypatch):
    """Nur 'verbinden' gewollt, Behandler hat abgenommen und spaeter aufgelegt
    (langsame Rueckkehr): neutral 'Da bin ich wieder.' — keine Behauptung
    ueber die Verbindung, keine Begruessung, offene Tuer."""
    _kein_llm(monkeypatch)
    sit = _sit_sip()
    _transfer(sit)
    alt = rueckkehr.aufnehmen(sit["id"], did=DID, caller=CALLER,
                              schnell=False, seit_s=312.0, ziel="Dr. Petsas")
    assert alt is sit
    text = agent.start_reply(sit)["text"]
    assert text.startswith("Da bin ich wieder.")
    assert "nicht zustande" not in text
    assert "sonst noch etwas" in text
    assert "Guten Tag" not in text
    assert hirn.aktiv(sit) is None


def test_hangup_marken_werden_fuer_das_echte_ende_geloest(monkeypatch):
    _kein_llm(monkeypatch)
    sit = _sit_sip()
    _transfer(sit)
    sit["hangupNotiert"] = True
    sit["gedaechtnisReport"] = {"ok": True}
    sit["unterbrochen"] = {"rest": "alter Rest", "gesprochen": ""}
    sit["halbsatz"] = "Ich haette gern"
    rueckkehr.aufnehmen(sit["id"], did=DID, caller=CALLER, schnell=True)
    for k in ("hangupNotiert", "gedaechtnisReport", "unterbrochen", "halbsatz"):
        assert k not in sit, k


def test_report_der_fortsetzung_bekommt_eigene_event_id(monkeypatch):
    """MAS appendEvent ist auf die Id idempotent: der Report der Fortsetzung
    (Buchung NACH dem Transfer) darf nicht als Duplikat des Transfer-Reports
    verworfen werden. Die Phase, die api_hangup VOR der Nacharbeit festhaelt,
    gewinnt gegen den inzwischen hochgezaehlten Sitzungsstand."""
    _kein_llm(monkeypatch)
    sit = _sit_sip()
    sit["messages"].append({"role": "user", "content": "Verbinden Sie mich mit Doktor Petsas."})
    basis = f"telefonki:bianca_call:{sit['id']}"
    assert gedaechtnis._event(sit)["id"] == basis
    _transfer(sit)
    rueckkehr.aufnehmen(sit["id"], did=DID, caller=CALLER, schnell=True)
    assert gedaechtnis._event(sit)["id"] == basis + ":r1"
    # Der ALTE Hangup-Thread hatte Phase 0 festgehalten — seine Id bleibt.
    assert gedaechtnis._event(sit, phase=0)["id"] == basis


def test_normaler_start_bleibt_unveraendert(monkeypatch):
    """Ohne Rueckkehr-Marke: die gewohnte Begruessung, byte-identisch."""
    _kein_llm(monkeypatch)
    sit = _sit_sip()
    aus = agent.start_reply(sit)
    assert "Da bin ich wieder" not in aus["text"]
    assert aus["text"]
