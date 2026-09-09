"""Blessing: Notfall-Sofortkommen + Dokumente nur bei Vorsprache (09.09.2026)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from bianca import flow
from kern import praxisregeln


TZ = ZoneInfo("Europe/Berlin")
DB_PROMPT = f"""
# Besondere Features:
- {praxisregeln.DOKUMENT_MARKER}: Rezepte und Überweisungen nur persönlich.

# Standort:
- {praxisregeln.NOTFALL_MARKER}: Akutfälle kommen sofort.
- Sprechzeiten:
Montag 8.30 - 12.30 Uhr und 14:00 bis 17:00 Uhr
Dienstag 8.30 - 12.00 und 14.00 - 19.00 Uhr
Mittwoch 8:30 - 13:00 Uhr
Donnerstag 8:30 - 13:00 und 14:00 - 17:30 Uhr
Freitag 8:30 - 12:00 Uhr
"""


def _tenant() -> dict:
    return {
        "praxisName": "Hautarztpraxis Doktor Blessing",
        "dbPrompt": DB_PROMPT,
        "visitMotives": [{"id": "akut", "name": "Akute Hautbeschwerden"}],
    }


def _sit() -> dict:
    return {
        "tenant": _tenant(),
        "messages": [{"role": "system", "content": "x"}],
    }


def test_notfallmarker_ist_praxisgebunden():
    assert praxisregeln.notfall_sofort_aktiv(_tenant())
    assert not praxisregeln.notfall_sofort_aktiv(
        {"praxisName": "Andere Hautarztpraxis", "dbPrompt": ""})


def test_sprechstunden_aus_db_prompt_werden_gelesen():
    assert praxisregeln.praxis_offen(
        _tenant(), datetime(2026, 9, 7, 9, 0, tzinfo=TZ)) is True
    assert praxisregeln.praxis_offen(
        _tenant(), datetime(2026, 9, 7, 13, 0, tzinfo=TZ)) is False
    assert praxisregeln.praxis_offen(
        _tenant(), datetime(2026, 9, 6, 10, 0, tzinfo=TZ)) is False


def test_akutfall_waehrend_sprechstunde_kommt_sofort():
    text = praxisregeln.notfall_antwort(
        _tenant(),
        "Seit heute habe ich plötzlich einen starken Ausschlag mit Fieber.",
        jetzt=datetime(2026, 9, 7, 9, 0, tzinfo=TZ),
    )
    assert "jetzt direkt" in text
    assert "keine feste Uhrzeit" in text
    assert "Wartezeit" in text
    assert "auf jeden Fall" in text and "versorgt" in text


def test_akutfall_ausserhalb_sprechstunde_nennt_116117():
    text = praxisregeln.notfall_antwort(
        _tenant(),
        "Ich habe eine akute allergische Reaktion der Haut.",
        jetzt=datetime(2026, 9, 7, 20, 0, tzinfo=TZ),
    )
    assert "116 117" in text
    assert "Praxis ist gerade geschlossen" in text


def test_lebensgefahr_hat_112_vorrang():
    text = praxisregeln.notfall_antwort(
        _tenant(),
        "Meine Zunge ist geschwollen und ich habe Atemnot.",
        jetzt=datetime(2026, 9, 7, 9, 0, tzinfo=TZ),
    )
    assert "112" in text
    assert "Praxis" not in text


def test_normale_hautfrage_startet_keinen_notfallpfad():
    assert not praxisregeln.notfall_antwort(
        _tenant(), "Ich möchte ein Muttermal kontrollieren lassen.",
        jetzt=datetime(2026, 9, 7, 9, 0, tzinfo=TZ))
    assert not praxisregeln.notfall_antwort(
        _tenant(), "Es ist kein Notfall, nur eine Kontrolle.",
        jetzt=datetime(2026, 9, 7, 9, 0, tzinfo=TZ))


def test_flow_bietet_bei_notfall_keinen_normalen_termin():
    sit = _sit()
    # Durchgehend geoeffnet, damit der Test unabhaengig von der Uhr laeuft.
    sit["tenant"]["dbPrompt"] = (
        f"{praxisregeln.NOTFALL_MARKER}\n"
        + "\n".join(f"{tag} 0:00 - 23:59"
                    for tag in ("Montag", "Dienstag", "Mittwoch",
                                "Donnerstag", "Freitag", "Samstag", "Sonntag"))
    )
    s = flow.gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "grund"})
    res = flow.zug(sit, "Ich habe eine akute Schwellung im Gesicht.")
    assert res and "jetzt direkt" in res["text"]
    assert "Termin" not in res["text"]
    assert not sit.get("offered")
    assert s["phase"] == "fertig" and s["modus"] == ""


def test_rezept_und_ueberweisung_nur_persoenlich_ohne_datensammelei():
    for wort in ("Rezept", "Überweisung"):
        sit = _sit()
        sit["hirnAbgeben"] = {"offen": True, "was": wort}
        res = flow._abgeben_zug(sit, f"Ich brauche eine {wort}.")
        s = flow.gehirn.sammler(sit)
        assert res and "persönlicher Vorsprache" in res["text"]
        assert "Ärztin" in res["text"]
        assert "Name" not in res["text"] and "Nummer" not in res["text"]
        assert s["phase"] == "fertig"
