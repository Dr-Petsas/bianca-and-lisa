"""W-FAKTEN-WACHE (09.09.2026): eine Erledigt-Behauptung darf nur raus, wenn
das passende Werkzeug erfolgreich lief (Tool-Ledger = Wahrheit). Shadow loggt
nur, enforce schreibt um. Notaus FAKTEN_WACHE=off. Offline, kein Netz.
"""

from bianca import agent
from kern import fakten_wache, spur
from kern.sitzung import merke_tool
from kern.tenants import laden


def _sit() -> dict:
    return {
        "stimme": "Bianca",
        "tenant": laden("meddent"),
        "sammler": {"modus": "buchen", "phase": "sammeln", "grund": "Kontrolle"},
        "messages": [{"role": "system", "content": "x"}],
    }


# --- reine Erkennung ---------------------------------------------------------

def test_gebucht_ohne_evidenz_ist_unbelegt():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(sit, "Ihr Termin ist gebucht.") == "buchen"


def test_gebucht_mit_evidenz_ist_ok():
    sit = _sit()
    sit["lastBook"] = {"ok": True, "booked": True}
    assert fakten_wache.unbelegte_behauptung(sit, "Ihr Termin ist gebucht.") == ""


def test_abgesagt_ohne_evidenz():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(sit, "Der Termin ist abgesagt.") == "absagen"


def test_verschoben_mit_evidenz_ok():
    sit = _sit()
    sit["lastMove"] = {"ok": True}
    assert fakten_wache.unbelegte_behauptung(sit, "Ich habe den Termin verschoben.") == ""


def test_notiz_ohne_evidenz():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(sit, "Ich habe eine Notiz gemacht.") == "notiz"


def test_notiz_mit_evidenz_ok():
    sit = _sit()
    merke_tool(sit, "note_appointment", {"ok": True})
    assert fakten_wache.unbelegte_behauptung(sit, "Ich habe eine Notiz gemacht.") == ""


def test_praxis_notiz_ist_echte_evidenz():
    sit = _sit()
    merke_tool(sit, "praxis_notiz", {"ok": True, "notiert": True})
    assert sit["noteWritten"] is True
    assert fakten_wache.unbelegte_behauptung(
        sit, "Die Notiz für das Team habe ich geschrieben."
    ) == ""


def test_gescheiterte_notiz_ist_keine_evidenz():
    sit = _sit()
    merke_tool(sit, "note_appointment", {"ok": False})
    assert sit["noteWritten"] is False
    assert fakten_wache.unbelegte_behauptung(
        sit, "Ich habe eine Notiz gemacht."
    ) == "notiz"


def test_kurzes_notiert_ist_nur_gespraechsbestaetigung():
    sit = _sit()
    for text in ("Alles klar, notiert.", "Ich habe Ihre Nummer vermerkt."):
        assert fakten_wache.unbelegte_behauptung(sit, text) == "", text


def test_aufgenommen_ohne_aktenbezug_ist_keine_aktenanlage():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(
        sit, "Vielen Dank, ich habe Ihre Angaben aufgenommen."
    ) == ""


def test_akte_angelegt_ohne_evidenz_ist_unbelegt():
    """Live New York: vier Ziffern dürfen keine erfundene Aktenanlage decken."""
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(
        sit, "Vielen Dank. Ich habe Ihre Akte angelegt."
    ) == "anlegen"


def test_akte_angelegt_mit_create_evidenz_ist_ok():
    sit = _sit()
    sit["lastCreate"] = {"ok": True, "createdPatient": True}
    assert fakten_wache.unbelegte_behauptung(
        sit, "Vielen Dank. Ich habe Ihre Akte angelegt."
    ) == ""


def test_fake_durchstellung_ohne_transfer_ist_unbelegt():
    sit = _sit()
    saetze = (
        "Ich stelle Sie jetzt durch.",
        "Ich leite die Verbindung jetzt ein.",
        "Ich werde Sie jetzt zu Frau Thaler durchstellen.",
    )
    for text in saetze:
        assert fakten_wache.unbelegte_behauptung(sit, text) == "transfer", text


def test_durchstellung_mit_echtem_ziel_ist_belegt():
    sit = _sit()
    sit["weiterleitungZiel"] = {"name": "Frau Thaler", "nummer": "+4987512345"}
    assert fakten_wache.unbelegte_behauptung(
        sit, "Ich werde Sie jetzt zu Frau Thaler durchstellen."
    ) == ""


def test_nicht_moegliche_durchstellung_ist_keine_erledigt_behauptung():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(
        sit, "Ich kann Sie im Moment leider nicht durchstellen."
    ) == ""


def test_frage_ist_keine_behauptung():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(sit, "Soll ich den Termin so eintragen?") == ""


def test_erfundenes_slotangebot_ohne_kalendersuche_ist_unbelegt():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(
        sit, "Ich hätte am Montag um neun etwas frei. Passt Ihnen das?") == "slots"


def test_slotangebot_mit_aktueller_kalenderevidenz_ist_ok():
    sit = _sit()
    sit["offered"] = [{"iso": "2026-09-14T09:00", "spoken": "Montag um neun"}]
    merke_tool(sit, "getFreeTimeSlots", {
        "ok": True,
        "slots": sit["offered"],
    })
    assert fakten_wache.unbelegte_behauptung(
        sit, "Ich hätte am Montag um neun etwas frei. Passt Ihnen das?") == ""


def test_keine_freien_slots_braucht_echte_leersuche():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(
        sit, "Leider ist diese Woche kein freier Termin verfügbar.") == "slots"
    merke_tool(sit, "getFreeTimeSlots", {"ok": True, "slots": []})
    assert fakten_wache.unbelegte_behauptung(
        sit, "Leider ist diese Woche kein freier Termin verfügbar.") == ""


def test_bestandstermin_darf_ohne_suche_nicht_verneint_werden():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(
        sit, "Sie haben aktuell keinen kommenden Termin.") == "bestand"
    merke_tool(sit, "agentFindPatientAppointments", {
        "ok": True,
        "appointments": [],
        "patient": {"id": "p1"},
    })
    assert fakten_wache.unbelegte_behauptung(
        sit, "Sie haben aktuell keinen kommenden Termin.") == ""


def test_sms_und_rueckruf_brauchen_evidenz():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(
        sit, "Die Bestätigungs-SMS kommt gleich.") == "sms"
    assert fakten_wache.unbelegte_behauptung(
        sit, "Die Praxis ruft Sie zurück.") == "rueckruf"

    sit["lastBook"] = {"ok": True, "booked": True, "verified": True}
    assert fakten_wache.unbelegte_behauptung(
        sit, "Die Bestätigungs-SMS kommt gleich.") == ""
    merke_tool(sit, "praxis_notiz", {"ok": True, "notiert": True})
    assert fakten_wache.unbelegte_behauptung(
        sit, "Die Praxis ruft Sie zurück.") == ""


def test_transfer_braucht_auch_einen_aktuellen_nutzerwunsch():
    sit = _sit()
    sit["weiterleitungZiel"] = {"name": "Frau Thaler", "nummer": "+4987512345"}
    assert fakten_wache.unbelegte_behauptung(
        sit,
        "Ich stelle Sie jetzt zu Frau Thaler durch.",
        nutzertext="Wie sind Ihre Öffnungszeiten?",
    ) == "transfer"
    assert fakten_wache.unbelegte_behauptung(
        sit,
        "Ich stelle Sie jetzt zu Frau Thaler durch.",
        nutzertext="Ich möchte nur kurz über meine Behandlung sprechen.",
    ) == "transfer"
    assert fakten_wache.unbelegte_behauptung(
        sit,
        "Ich stelle Sie jetzt zu Frau Thaler durch.",
        nutzertext="Verbinden Sie mich bitte mit Frau Thaler.",
    ) == ""


def test_angehaengte_frage_entschaerft_keine_erledigt_luege():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(
        sit, "Ich habe den Termin reserviert, passt das?") == "buchen"


# --- Agent-Umgang: off / shadow / enforce -----------------------------------

def test_off_laesst_text_stehen(monkeypatch):
    monkeypatch.setenv("FAKTEN_WACHE", "off")
    sit = _sit()
    aus = agent._fakten_wache_anwenden(sit, "Ihr Termin ist gebucht.")
    assert aus == "Ihr Termin ist gebucht."
    assert not sit.get("_spur")


def test_shadow_loggt_ohne_umschreiben(monkeypatch):
    monkeypatch.setenv("FAKTEN_WACHE", "shadow")
    sit = _sit()
    aus = agent._fakten_wache_anwenden(sit, "Ihr Termin ist gebucht.")
    assert aus == "Ihr Termin ist gebucht."
    spuren = [e["w"] for e in spur.abholen(sit)]
    assert "fakten-wache-shadow" in spuren


def test_enforce_schreibt_unbelegte_behauptung_um(monkeypatch):
    monkeypatch.setenv("FAKTEN_WACHE", "enforce")
    sit = _sit()
    aus = agent._fakten_wache_anwenden(sit, "Ihr Termin ist gebucht.")
    assert "gebucht" not in aus.lower()
    assert "nicht falsch machen" in aus.lower() or "noch nicht erledigt" in aus.lower()
    spuren = [e["w"] for e in spur.abholen(sit)]
    assert "fakten-wache" in spuren


def test_enforce_laesst_belegte_behauptung_stehen(monkeypatch):
    monkeypatch.setenv("FAKTEN_WACHE", "enforce")
    sit = _sit()
    sit["lastBook"] = {"ok": True, "booked": True}
    aus = agent._fakten_wache_anwenden(sit, "Ihr Termin ist gebucht.")
    assert aus == "Ihr Termin ist gebucht."


def test_enforce_entfernt_den_ganzen_erfundenen_slot_satz(monkeypatch):
    monkeypatch.setenv("FAKTEN_WACHE", "enforce")
    sit = _sit()
    sit["sammler"]["modus"] = ""
    aus = agent._fakten_wache_anwenden(
        sit,
        "Am Montag um neun ist noch etwas frei. Die SMS kommt danach sofort.",
        nutzertext="Ist heute noch ein Termin frei?",
    )
    assert "montag" not in aus.lower()
    assert "sms kommt" not in aus.lower()
    assert "kalendersuche" in aus.lower()
