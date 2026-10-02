"""Regression: Anrufer-Abbruch ist auf der Ergebnisseite kein Bianca-Fail."""
from kern import anruf_anliegen, ergebnisse


_RUECKRUF_TEXT = (
    "Camilla Daum ist mein Name, ich bitte dringend einen Rückruf von "
    "meinem Planat. Bitte, es ist dringend. Danke, tschüss."
)


def _rueckruf(sid: str, *, notiz: str = "") -> dict:
    return {
        "id": sid,
        "_sid": sid,
        "tenant": {"id": "meddent"},
        "startedAt": "2026-10-02T08:00:00+00:00",
        "praxisNotiz": notiz,
        "zuege": [{
            "textIn": _RUECKRUF_TEXT,
            "text": "Vielen Dank für Ihren Anruf. Auf Wiederhören!",
        }],
        "tools": [],
    }


def _zeile(anrufe: list[dict]) -> dict:
    return next(z for z in ergebnisse._anliegen_zeilen(anrufe)
                if z["id"] == "rueckruf")


def test_live_rueckruf_471dd03a_ist_neutral_und_nicht_fail():
    manifest = _rueckruf("471dd03a5d5441c1b8941b7d4e6a241d")

    assert anruf_anliegen.ids_von(manifest) == ["rueckruf"]
    assert anruf_anliegen.anruf_wertung(manifest) == ("neutral", [])

    zeile = _zeile([manifest])
    assert (zeile["erkannt"], zeile["erledigt"], zeile["neutral"],
            zeile["offen"], zeile["quote"]) == (1, 0, 1, 0, None)
    assert zeile["gespraeche"][0]["stand"] == "neutral"
    assert zeile["offenGespraeche"] == []
    assert zeile["neutralGespraeche"][0]["sid"] == manifest["id"]


def test_neutraler_rueckruf_verschlechtert_die_erledigt_quote_nicht():
    neutral = _rueckruf("471dd03a5d5441c1b8941b7d4e6a241d")
    erledigt = _rueckruf(
        "7080711b774640c1b43b9106541ea1c8",
        notiz="Rückruf dringend erbeten; Tel: +4915112345678.",
    )

    zeile = _zeile([neutral, erledigt])
    assert (zeile["erkannt"], zeile["erledigt"], zeile["neutral"],
            zeile["offen"], zeile["quote"]) == (2, 1, 1, 0, 100.0)

    gesamt = ergebnisse._block_von([neutral, erledigt], [])["gesamt"]
    assert gesamt["anliegenErkannt"] == 2
    assert gesamt["anliegenErledigt"] == 1
    assert gesamt["anliegenNeutral"] == 1
    assert gesamt["anliegenFail"] == 0
    assert gesamt["anliegenQuote"] == 100.0


def test_echter_dialogfehler_bleibt_fail():
    manifest = _rueckruf("echter-fehler")
    manifest["zuege"].extend([
        {"textIn": "Hallo?", "text": "Wie lautet Ihr Nachname?"},
        {"textIn": "Das sagte ich schon.", "text": "Wie lautet Ihr Nachname?"},
    ])

    assert anruf_anliegen.anruf_wertung(manifest) == (
        "fehler", ["wiederholungsschleife"])
    zeile = _zeile([manifest])
    assert (zeile["erledigt"], zeile["neutral"], zeile["offen"],
            zeile["quote"]) == (0, 0, 1, 0.0)
    assert zeile["offenGespraeche"][0]["stand"] == "offen"
