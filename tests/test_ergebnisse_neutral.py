"""Ergebnisseite ohne „neutral“ (Chef 09.10.2026): jedes erkannte Anliegen ist
erfolgreich oder nicht erfolgreich, nicht erfolgreiche tragen einen Grund.
Dazu die Reservierungs-SMS als eigene Zeile unter Terminverwaltung."""
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


def _buchung(sid: str, *, slots: bool) -> dict:
    tools = [{"name": "getFreeTimeSlots", "ok": True}] if slots else []
    return {
        "id": sid,
        "_sid": sid,
        "tenant": {"id": "meddent"},
        "startedAt": "2026-10-02T09:00:00+00:00",
        "zuege": [{
            "textIn": "Ich möchte gerne einen Termin vereinbaren.",
            "text": "Gerne. Frei wäre der 14. Januar um neun Uhr.",
        }],
        "tools": tools,
    }


def _mit_reservierung(m: dict, *events: tuple[str, str]) -> dict:
    m["observability"] = {"reservation": [
        {"phase": p, "outcome": o} for p, o in events]}
    return m


def _zeile(anrufe: list[dict], aid: str = "rueckruf") -> dict:
    return next(z for z in ergebnisse._anliegen_zeilen(anrufe)
                if z["id"] == aid)


def test_es_gibt_kein_neutral_mehr():
    zeile = _zeile([_rueckruf("471dd03a5d5441c1b8941b7d4e6a241d")])
    assert "neutral" not in zeile
    assert "neutralGespraeche" not in zeile
    gesamt = ergebnisse._block_von([_rueckruf("x")], [])["gesamt"]
    assert "anliegenNeutral" not in gesamt


def test_live_rueckruf_471dd03a_ist_nicht_erfolgreich_aufgelegt():
    manifest = _rueckruf("471dd03a5d5441c1b8941b7d4e6a241d")
    assert anruf_anliegen.ids_von(manifest) == ["rueckruf"]

    zeile = _zeile([manifest])
    assert (zeile["erkannt"], zeile["erledigt"], zeile["offen"],
            zeile["quote"]) == (1, 0, 1, 0.0)
    assert zeile["gruende"] == {
        "bianca_fehler": 0, "kein_termin": 0, "aufgelegt": 1}
    assert zeile["gespraeche"][0]["stand"] == "offen"
    assert zeile["gespraeche"][0]["grund"] == "aufgelegt"
    assert zeile["offenGespraeche"][0]["sid"] == manifest["id"]


def test_quote_ist_erfolgreich_durch_erkannt():
    offen = _rueckruf("471dd03a5d5441c1b8941b7d4e6a241d")
    erledigt = _rueckruf(
        "7080711b774640c1b43b9106541ea1c8",
        notiz="Rückruf dringend erbeten; Tel: +4915112345678.",
    )
    zeile = _zeile([offen, erledigt])
    assert (zeile["erkannt"], zeile["erledigt"], zeile["offen"],
            zeile["quote"]) == (2, 1, 1, 50.0)

    gesamt = ergebnisse._block_von([offen, erledigt], [])["gesamt"]
    assert gesamt["anliegenErkannt"] == 2
    assert gesamt["anliegenErledigt"] == 1
    assert gesamt["anliegenFail"] == 1
    assert gesamt["anliegenAufgelegt"] == 1
    assert gesamt["anliegenBiancaFehler"] == 0
    assert gesamt["anliegenQuote"] == 50.0


def test_echter_dialogfehler_ist_bianca_fehler():
    manifest = _rueckruf("echter-fehler")
    manifest["zuege"].extend([
        {"textIn": "Hallo?", "text": "Wie lautet Ihr Nachname?"},
        {"textIn": "Das sagte ich schon.", "text": "Wie lautet Ihr Nachname?"},
    ])
    assert anruf_anliegen.anruf_wertung(manifest) == (
        "fehler", ["wiederholungsschleife"])
    zeile = _zeile([manifest])
    assert (zeile["erledigt"], zeile["offen"], zeile["quote"]) == (0, 1, 0.0)
    assert zeile["gespraeche"][0]["grund"] == "bianca_fehler"
    assert ergebnisse.misserfolg_grund(manifest, "rueckruf", "fehler") == "bianca_fehler"


def test_buchung_mit_slotsuche_ohne_termin_ist_kein_passender_termin():
    mit = _buchung("b-slots", slots=True)
    ohne = _buchung("b-frueh", slots=False)
    assert ergebnisse.misserfolg_grund(mit, "buchen", "neutral") == "kein_termin"
    assert ergebnisse.misserfolg_grund(ohne, "buchen", "neutral") == "aufgelegt"
    # Rückruf hat keine Slotsuche — auch mit Werkzeug nie „kein Termin“.
    assert ergebnisse.misserfolg_grund(mit, "rueckruf", "neutral") == "aufgelegt"


def test_reservierungs_sms_eigene_zeile_unter_terminverwaltung():
    zeilen = ergebnisse._anliegen_zeilen([])
    ids = [z["id"] for z in zeilen]
    assert "reservierungs_sms" in ids
    assert ids.index("reservierungs_sms") == ids.index("auskunft") + 1
    z = _zeile([], "reservierungs_sms")
    assert z["gruppe"] == "Terminverwaltung"
    assert (z["erkannt"], z["erledigt"], z["offen"], z["quote"]) == (0, 0, 0, None)


def test_reservierungs_sms_versand_zaehlt_als_erfolg():
    ok = _mit_reservierung(_rueckruf("r-ok"), ("create", "ok"), ("bind", "ok"))
    fertig = _mit_reservierung(_rueckruf("r-done"), ("create", "ok"),
                               ("bind", "ok"), ("done", "done"))
    nicht = _mit_reservierung(_rueckruf("r-err"), ("create", "error"))
    bind = _mit_reservierung(_rueckruf("r-bind"), ("create", "ok"),
                             ("bind", "error"))
    ohne = _rueckruf("r-ohne")

    z = _zeile([ok, fertig, nicht, bind, ohne], "reservierungs_sms")
    assert (z["erkannt"], z["erledigt"], z["offen"], z["quote"]) == (4, 2, 2, 50.0)
    assert z["nameEingetragen"] == 1
    assert z["gruende"] == {"SMS nicht verschickt": 1,
                            "Bindung an den Termin gescheitert": 1}
    gruende = {g["sid"]: g["grund"] for g in z["gespraeche"]}
    assert gruende["r-err"] == "SMS nicht verschickt"
    assert gruende["r-bind"] == "Bindung an den Termin gescheitert"


def test_reservierungs_zeile_zaehlt_nicht_in_die_anliegen_summe():
    ok = _mit_reservierung(_rueckruf("r-ok"), ("create", "ok"))
    gesamt = ergebnisse._block_von([ok], [])["gesamt"]
    # Ein Anliegen (Rückruf), die Reservierung ist nur Zusatzspur.
    assert gesamt["anliegenErkannt"] == 1


def test_praxis_quote_zaehlt_wie_die_karten():
    offen = _rueckruf("471dd03a5d5441c1b8941b7d4e6a241d")
    erledigt = _rueckruf("7080711b774640c1b43b9106541ea1c8",
                         notiz="Rückruf dringend erbeten; Tel: +4915112345678.")
    for m in (offen, erledigt):
        m["tenantId"] = "meddent"
    praxis = next(p for p in ergebnisse._fehler_je_praxis([offen, erledigt])
                  if p["id"] == "meddent")
    assert (praxis["erkannt"], praxis["erledigt"], praxis["offen"]) == (2, 1, 1)
    assert praxis["biancaFehler"] == 0
    assert praxis["quote"] == 50.0


def test_praxis_kurve_und_karten_sagen_dasselbe():
    anrufe = [
        _rueckruf("a", notiz="Rückruf erbeten; Tel: +4915112345678."),
        _rueckruf("b"),
        _buchung("c", slots=True),
        _mit_reservierung(_rueckruf("d"), ("create", "ok")),
    ]
    for m in anrufe:
        m["tenantId"] = "meddent"
    gesamt = ergebnisse._block_von(anrufe, [])["gesamt"]
    praxis = next(p for p in ergebnisse._fehler_je_praxis(anrufe)
                  if p["id"] == "meddent")
    assert praxis["erkannt"] == gesamt["anliegenErkannt"]
    assert praxis["erledigt"] == gesamt["anliegenErledigt"]
    assert praxis["quote"] == gesamt["anliegenQuote"]
    gruende = {g["grund"]: g["anzahl"] for g in praxis["gruende"]}
    assert gruende.get("Kein passender Termin") == gesamt["anliegenKeinTermin"]
