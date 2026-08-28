"""Vorfall 27.08.2026: Zusage ohne Werkzeug darf nie in den Mund.

Die Wache lebt seit dem Bianca-Ausbau im gemeinsamen Kern (kern.zuege) und
trägt Lisa UND Bianca — getestet wird sie dort.
"""

from kern import zuege

ANGEBOT = [
    {"iso": "2026-08-27T09:15", "spoken": "heute um neun Uhr fünfzehn"},
    {"iso": "2026-08-27T09:30", "spoken": "heute um neun Uhr dreißig"},
]


def test_zusage_wird_erkannt():
    for satz in [
        "Alles klar, dann buche ich Ihnen heute um neun Uhr fünfzehn.",
        "Ich buche das für Sie.",
        "Der Termin ist eingetragen.",
        "Ich reserviere Ihnen den Platz.",
        "Ich trage Sie ein.",
    ]:
        assert zuege.zusage_ohne_werkzeug(satz), satz


def test_frage_ist_keine_zusage():
    for satz in [
        "Soll ich den Termin für Sie buchen?",
        "Buche ich Ihnen den Termin um neun Uhr?",
        "Passt Ihnen heute um neun Uhr fünfzehn?",
        "Ich schaue eben in den Kalender.",
    ]:
        assert not zuege.zusage_ohne_werkzeug(satz), satz


def test_gemeinter_slot_aus_dem_satz():
    iso = zuege.gemeinter_slot(
        "Alles klar, dann buche ich Ihnen heute um neun Uhr dreißig.", ANGEBOT
    )
    assert iso == "2026-08-27T09:30"


def test_einziges_angebot_ist_eindeutig():
    assert zuege.gemeinter_slot("Ich buche das.", ANGEBOT[:1]) == "2026-08-27T09:15"


def test_mehrdeutig_gibt_nichts_zurueck():
    assert zuege.gemeinter_slot("Ich buche das.", ANGEBOT) == ""


def test_gemeinter_slot_erster_und_dieser():
    assert zuege.gemeinter_slot("den ersten bitte", ANGEBOT) == "2026-08-27T09:15"
    assert zuege.gemeinter_slot("der letzte", ANGEBOT) == "2026-08-27T09:30"
    assert zuege.gemeinter_slot("dieser", ANGEBOT) == "2026-08-27T09:30"


def test_wache_fragt_nach_statt_zu_luegen():
    sit = {"offered": ANGEBOT}
    text, book = zuege.buchungs_wache(sit, "Alles klar, ich buche das für Sie.")
    assert book is None
    assert "?" in text
    assert "gebucht" not in text.lower()


def test_wache_laesst_normale_saetze_durch():
    sit = {"offered": ANGEBOT}
    text, book = zuege.buchungs_wache(sit, "Frei ist heute um neun Uhr fünfzehn. Passt das?")
    assert text == ""
    assert book is None


def test_wache_bucht_wirklich_wenn_der_termin_klar_ist():
    gerufen = {}

    def fake_tool(session_doc, name, args):
        gerufen["name"] = name
        gerufen["args"] = args
        return {"ok": True, "booked": True, "slotIso": args["slot_iso"],
                "spoken": "Der Termin heute um neun Uhr fünfzehn ist fest eingetragen."}

    echt_tool, echt_merke = zuege.run_tool, zuege.merke_tool
    zuege.run_tool = fake_tool
    zuege.merke_tool = lambda *a, **k: None
    try:
        sit = {"offered": ANGEBOT}
        text, book = zuege.buchungs_wache(
            sit, "Alles klar, dann buche ich Ihnen heute um neun Uhr fünfzehn."
        )
    finally:
        zuege.run_tool, zuege.merke_tool = echt_tool, echt_merke

    assert gerufen["name"] == "book_slot"
    assert gerufen["args"]["slot_iso"] == "2026-08-27T09:15"
    assert book["booked"] is True
    assert "fest eingetragen" in text
