"""Fix 2 (13.09.2026, Feldtest-Analyse): „Ueberweisung" ist kein Rueckruf-
Automatismus.

Vorher gewann `_FB_RUECKRUF_RE` (rezept|ueberweisung) in der Heuristik gegen
jeden Terminwunsch: „Ich habe eine Ueberweisung vom Hausarzt und brauche
einen Termin" wurde ein ABGEBEN-Vorgang (Rueckruf-Notiz), „Ich bin
ueberwiesen worden" mitten in der Buchung parkte die Buchung. Jetzt gilt:
Ueberweisung HABEN = Buchungsgrund (ANLEGEN); ein echter Dokumentwunsch
(„Ich brauche ein Rezept", „Ueberweisung abholen") bleibt ABGEBEN.

Kein Netz: das Intent-LLM wird gestummt.
"""

import pytest

from kern import hirn, intent
from kern.tenants import laden


@pytest.fixture(autouse=True)
def _kein_llm(monkeypatch):
    monkeypatch.setattr(intent, "_chat", lambda *a, **k: {"ok": False, "error": "stumm"})
    monkeypatch.setenv("INTENT_NACHZUG", "0")


def _sit() -> dict:
    sit = {"stimme": "Bianca", "tenant": laden("meddent"),
           "messages": [{"role": "system", "content": "x"}]}
    hirn.init(sit)
    return sit


# --- Ueberweisung HABEN = Termin ----------------------------------------------

@pytest.mark.parametrize("satz", [
    "Ich habe eine Überweisung vom Hausarzt und brauche einen Termin.",
    "Ich bin von Doktor Grüger überwiesen worden.",
    "Mein Hausarzt hat mich zu Ihnen überwiesen, wann haben Sie Zeit?",
    "Ich habe hier eine Überweisung vom Kieferorthopäden.",
    "Ich komme mit einer Überweisung, ich hätte gern einen Termin.",
])
def test_ueberweisung_haben_ist_anlegen(satz):
    d = intent.erkennen(_sit(), satz)
    assert d["handlung"] == "ANLEGEN", (satz, d)
    assert d["handlung"] != "ABGEBEN"


def test_ueberwiesener_erstsatz_oeffnet_die_buchung():
    sit = _sit()
    hirn.anwenden(sit, intent.erkennen(
        sit, "Ich habe eine Überweisung vom Hausarzt und brauche einen Termin."))
    assert sit["sammler"]["modus"] == "buchen"
    assert not sit.get("hirnAbgeben")


# --- Mitten in der Buchung parkt die Ueberweisung nichts ---------------------

def test_ueberweisung_mitten_in_der_buchung_parkt_nicht():
    sit = _sit()
    hirn.anwenden(sit, intent.erkennen(sit, "Ich hätte gern einen Termin."))
    assert sit["sammler"]["modus"] == "buchen"
    aktiv_vorher = sit["hirn"]["aktiv"]
    d = intent.erkennen(sit, "Ich bin vom Hausarzt überwiesen worden.")
    assert d["handlung"] != "ABGEBEN", d
    hirn.anwenden(sit, d)
    assert sit["sammler"]["modus"] == "buchen"
    assert sit["hirn"]["aktiv"] == aktiv_vorher
    assert not [a for a in sit["hirn"]["anliegen"] if a.get("status") == "geparkt"]


# --- Gegenproben: echter Dokumentwunsch bleibt ABGEBEN ------------------------

@pytest.mark.parametrize("satz", [
    "Ich brauche ein Rezept.",
    "Können Sie mir ein Rezept ausstellen?",
    "Ich brauche eine Überweisung zum Kieferorthopäden.",
    "Ich wollte mein Rezept abholen.",
    "Ich möchte eine Überweisung abholen.",
    "Ich hätte gern ein neues Rezept für mein Schmerzmittel.",
])
def test_dokumentwunsch_bleibt_abgeben(satz):
    d = intent.erkennen(_sit(), satz)
    assert d["handlung"] == "ABGEBEN", (satz, d)


def test_rueckruf_kern_unveraendert():
    d = intent.erkennen(_sit(), "Können Sie mich bitte zurückrufen?")
    assert d["handlung"] == "ABGEBEN"


def test_rezeption_bleibt_kein_dokument():
    """W-REZEPTION bleibt: der Wunsch nach der Anmeldung ist kein Rueckruf."""
    d = intent.erkennen(_sit(), "Ich möchte bitte zur Rezeption.")
    assert d["handlung"] != "ABGEBEN"
