"""Anruf e9dd56bf (MedDent, 09.10.2026, Patient Ihon): Rezept HABEN ist ein
Terminwunsch, kein Rezeptwunsch.

Live: „Ich habe ein Rezept für eine Schiene erhalten, würde gerne einen Termin
vereinbaren.“ — `erhalt\\w*` in der Anforderungs-Regex machte daraus einen
Dokumentwunsch (ABGEBEN): „Rezept und Überweisung kann ich am Telefon nicht
ausstellen … Wie ist Ihr Name?“. Zwei Widersprüche des Anrufers („Ich möchte
kein Rezept …“, „Sie sollen kein Rezept ausstellen“) wurden überhört, am Ende
stand eine Rückruf-Notiz statt eines Termins.

Kein Netz: das Intent-LLM wird gestummt.
"""

import pytest

from bianca import flow, gehirn
from kern import hirn, intent, praxisregeln
from kern.tenants import laden

Z1 = "Ich habe ein Rezept für eine Schiene erhalten, würde gerne einen Termin vereinbaren."
Z2 = ("Ich möchte kein Rezept oder eine Überweisung haben. Ich habe vom Schlaflabor "
      "ein Rezept bekommen, mit dem soll ich mich bei Ihnen vorstellen.")
Z4 = ("Ich wollte nur mal sagen, Sie sollen kein Rezept ausstellen, ich habe einen "
      "Vorliegen von dem Schlaflabor, und darum geht es.")


@pytest.fixture(autouse=True)
def _kein_llm(monkeypatch):
    monkeypatch.setattr(intent, "_chat", lambda *a, **k: {"ok": False, "error": "stumm"})
    monkeypatch.setenv("INTENT_NACHZUG", "0")


def _sit() -> dict:
    sit = {"stimme": "Bianca", "tenant": laden("meddent"),
           "messages": [{"role": "system", "content": "x"}]}
    hirn.init(sit)
    return sit


def _zug(sit: dict, satz: str) -> dict:
    hirn.anwenden(sit, intent.erkennen(sit, satz))
    return flow.zug(sit, satz) or {}


# --- Erkennung -----------------------------------------------------------------

@pytest.mark.parametrize("satz", [
    Z1,
    "Ich habe vom Schlaflabor ein Rezept bekommen, mit dem soll ich mich bei Ihnen vorstellen.",
    "Mir wurde ein Rezept für eine Schnarchschiene ausgestellt.",
    "Ich habe ein Rezept vom Kieferorthopäden, wann haben Sie Zeit?",
    "Ich hab eine Verordnung bekommen und bräuchte einen Termin.",
])
def test_rezept_haben_ist_anlegen(satz):
    assert praxisregeln.hat_dokument(satz), satz
    assert not praxisregeln.dokument_anforderung(satz), satz
    d = intent.erkennen(_sit(), satz)
    assert d["handlung"] == "ANLEGEN", (satz, d)


@pytest.mark.parametrize("satz", [
    "Ich brauche ein Rezept.",
    "Können Sie mir ein Rezept ausstellen?",
    "Ich habe mein Rezept noch nicht bekommen.",
    "Ich habe ein Rezept bekommen, das ist abgelaufen, ich brauche ein neues.",
    "Ich hätte gern ein Rezept vom Doktor.",
    "Haben Sie mein Rezept schon ausgestellt?",
    "Hat der Doktor mein Rezept schon verschrieben?",
])
def test_rezeptwunsch_bleibt_abgeben(satz):
    assert praxisregeln.dokument_anforderung(satz) or not praxisregeln.hat_dokument(satz), satz
    d = intent.erkennen(_sit(), satz)
    assert d["handlung"] == "ABGEBEN", (satz, d)


# --- Live-Verlauf ----------------------------------------------------------------

def test_live_erstsatz_oeffnet_die_buchung():
    sit = _sit()
    res = _zug(sit, Z1)
    text = res.get("text", "")
    assert "kann ich am Telefon nicht ausstellen" not in text
    assert gehirn.sammler(sit)["modus"] == "buchen"
    assert not (sit.get("hirnAbgeben") or {}).get("offen")


@pytest.mark.parametrize("widerspruch", [Z2, Z4])
def test_widerspruch_im_rezeptzweig_fuehrt_zur_buchung(widerspruch):
    sit = _sit()
    _zug(sit, "Ich brauche ein Rezept.")
    assert (sit.get("hirnAbgeben") or {}).get("offen")
    res = _zug(sit, widerspruch)
    text = res.get("text", "")
    assert "kann ich am Telefon nicht ausstellen" not in text
    assert "Alles notiert" not in text
    assert gehirn.sammler(sit)["modus"] == "buchen"
    assert not (sit.get("hirnAbgeben") or {}).get("offen")
    assert not sit.get("praxisNotiz")


def test_echter_rezeptwunsch_bleibt_im_notizzweig():
    sit = _sit()
    _zug(sit, "Ich brauche ein Rezept.")
    res = _zug(sit, "Ich brauche das Rezept für mein Schmerzmittel.")
    assert (sit.get("hirnAbgeben") or {}).get("offen")
    assert gehirn.sammler(sit)["modus"] != "buchen"
    assert "Termin" not in res.get("text", "")
