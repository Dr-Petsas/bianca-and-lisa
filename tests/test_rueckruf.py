"""Rückrufer fragt nach dem Anrufgrund: mitteilen, erledigt, nur noch die Zeit."""

from bianca import flow, gehirn
from kern import gedaechtnis as ged
from kern.tenants import laden


def _sit() -> dict:
    sit = {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}
    sit["tenant"] = dict(sit["tenant"])
    vms = list(sit["tenant"].get("visitMotives") or [])
    vms.append({
        "id": "narval-ein",
        "name": "SLM Narval Eingliederung",
        "duration": 30,
        "allowOnlineBooking": True,
    })
    sit["tenant"]["visitMotives"] = vms
    return sit


def _sit_rueckruf() -> dict:
    sit = _sit()
    sit["anrufer"] = {
        "vorname": "Julia", "nachname": "Berger", "patientId": "pat-7",
        "geschlecht": "female", "telefon": "+4915253904756",
    }
    sit["gedaechtnis"] = (
        "Praxisgedächtnis zu dieser Rufnummer (vermutlich Julia Berger):\n"
        "- 08.09.: Nadine hat am Dienstag Julia Berger angerufen: "
        "Narval-Schiene abholbereit. Nicht erreicht. Bitte Termin zum Abholen. (noch offen)"
    )
    sit["gedaechtnisOffen"] = ["evt-narval-1"]
    sit["anruferKartei"] = {
        "letzterBesuch": "2026-06-01",
        "letzterGrund": "SLM Besprechung",
        "calendarId": "cal-petsas",
        "calendarName": "Dr. Petsas",
        "doctorName": "Dr. Petsas",
    }
    return sit


def test_fragt_anrufgrund_live_saetze():
    ja = [
        "Warum habt ihr angerufen?",
        "Warum haben Sie mich angerufen?",
        "Ich rufe zurück — worum ging es?",
        "Da war ein Anruf von euch.",
        "Sie haben versucht, mich zu erreichen.",
        "Weshalb habt ihr angerufen?",
        "Ich rufe gerade zurück.",
        "Ich hatte einen Anruf von Ihnen.",
        "Ich wollte wissen, warum ich angerufen wurde von Ihnen.",
    ]
    nein = [
        "Können Sie mich zurückrufen?",
        "Bitte rufen Sie mich zurück.",
        "Ich brauche einen Rückruf.",
        "Ich hätte gern einen Termin zur Kontrolle.",
        "Rufen Sie Doktor Petsas an.",
    ]
    for s in ja:
        assert gehirn.fragt_anrufgrund(s), s
    for s in nein:
        assert not gehirn.fragt_anrufgrund(s), s


def test_rueckruf_fragt_grund_mitgeteilt_dann_wunschzeit():
    notes = []
    echt_erledigen = ged.offen_erledigen
    echt_an = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    ged.offen_erledigen = lambda sit, note="": notes.append(note) or sit.update(
        gedaechtnisOffen=[], gedaechtnis=""
    )
    try:
        sit = _sit_rueckruf()
        z = flow.zug(sit, "Warum habt ihr angerufen?")
        assert z and "Narval-Schiene" in z["text"]
        assert "vormittag" in z["text"].lower()
        assert "Eingliederung" in z["text"]
        s = gehirn.sammler(sit)
        assert sit["rueckrufMitgeteilt"] is True
        assert sit["rueckrufBuchung"] is True
        assert s["frage"] == "wunsch"
        assert s["modus"] == "buchen"
        assert s["anruferCheck"] == "ja"
        assert s["vorname"] == "Julia" and s["nachname"] == "Berger"
        assert s["telefonOk"] and s["patientId"] == "pat-7"
        assert (s.get("arzt") or {}).get("calendarId") == "cal-petsas"
        assert "Narval" in s["grund"]
        assert s["motivId"] == "narval-ein"
        assert "Eingliederung" in s["motivName"]
        assert notes and "Mitgeteilt" in notes[0]
        assert sit["gedaechtnisOffen"] == []
        fid, _ = gehirn.naechste_frage(sit)
        assert fid == "wunsch"
    finally:
        ged.offen_erledigen = echt_erledigen
        flow.hintergrund.anstossen = echt_an


def test_rueckruf_ohne_offene_notiz_laesst_llm():
    echt_an = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        sit["gedaechtnis"] = ""
        sit["gedaechtnisOffen"] = []
        assert flow.zug(sit, "Warum habt ihr angerufen?") is None
    finally:
        flow.hintergrund.anstossen = echt_an


def test_rueckruf_herbst_frontdesk_notiz_status_none():
    """Live 08.09.: Empfangsnotiz status=none, Satz 'Ich hatte einen Anruf von Ihnen.'"""
    notes = []
    echt_erledigen = ged.offen_erledigen
    echt_an = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    ged.offen_erledigen = lambda sit, note="": notes.append(note) or sit.update(
        gedaechtnisOffen=[], gedaechtnis=""
    )
    try:
        sit = _sit()
        sit["anrufer"] = {
            "vorname": "Patrick", "nachname": "Herbst", "patientId": "u1SB",
            "geschlecht": "male", "telefon": "+491777074403",
        }
        sit["gedaechtnis"] = (
            "Praxisgedächtnis zu dieser Rufnummer (vermutlich Patrick Herbst):\n"
            "- 08.09.: schlaf schiene ist schon abholbreit (noch offen)"
        )
        sit["gedaechtnisOffen"] = ["ce68a0f5"]
        sit["anruferKartei"] = {
            "letzterBesuch": "2026-06-01",
            "letzterGrund": "SLM Besprechung",
            "calendarId": "cal-petsas",
            "calendarName": "Dr. Petsas",
        }
        z = flow.zug(sit, "Ich hatte einen Anruf von Ihnen.")
        assert z and "Narval-Schiene" in z["text"]
        assert "vormittag" in z["text"].lower() or "Eingliederung" in z["text"]
        s = gehirn.sammler(sit)
        assert sit["rueckrufMitgeteilt"] is True
        assert s["nachname"] == "Herbst" and s["anruferCheck"] == "ja"
        assert "Narval" in s["grund"] or "Schiene" in s["grund"]
        assert notes
    finally:
        ged.offen_erledigen = echt_erledigen
        flow.hintergrund.anstossen = echt_an


def test_rueckruf_erkannt_ohne_notiz_fragt_nicht_nochmal_identitaet():
    echt_an = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        sit["anrufer"] = {
            "vorname": "Patrick", "nachname": "Herbst", "patientId": "u1SB",
            "geschlecht": "male", "telefon": "+491777074403",
        }
        sit["gedaechtnis"] = ""
        sit["gedaechtnisOffen"] = []
        z = flow.zug(sit, "Ich wollte wissen, warum ich angerufen wurde von Ihnen.")
        assert z and "erkannt" in z["text"].lower()
        assert "Akte" not in z["text"]
        assert "Herr Herbst" in z["text"]
    finally:
        flow.hintergrund.anstossen = echt_an


def test_fragt_anrufgrund_folge_nach_anruf_satz():
    sit = _sit()
    sit["messages"] = [
        {"role": "user", "content": "Ich hatte einen Anruf von Ihnen."},
        {"role": "assistant", "content": "Ah, Herr Herbst."},
    ]
    assert gehirn.fragt_anrufgrund("Ich wollte mal wissen, um was es geht.", sit)


def test_rueckruf_vormittags_im_selben_satz():
    echt_erledigen = ged.offen_erledigen
    echt_an = flow.hintergrund.anstossen
    echt_ang = flow._angebot
    flow.hintergrund.anstossen = lambda sit: None
    ged.offen_erledigen = lambda sit, note="": None
    flow._angebot = lambda sit, melde=None: {"text": "Passt Ihnen Dienstag um neun?"}
    try:
        sit = _sit_rueckruf()
        z = flow.zug(sit, "Ich rufe zurück, warum habt ihr angerufen — vormittags wäre gut.")
        s = gehirn.sammler(sit)
        assert s.get("wunsch") is not None
        assert s["wunsch"].get("hourMax") and s["wunsch"]["hourMax"] <= 12
        assert z and ("vormittag" in z["text"].lower() or "neun" in z["text"].lower()
                      or "Narval" in z["text"])
    finally:
        ged.offen_erledigen = echt_erledigen
        flow.hintergrund.anstossen = echt_an
        flow._angebot = echt_ang


def test_buchen_setzt_notiz_nicht_mehr_erledigt():
    """Erledigt nur beim Mitteilen, nicht erst nach der Buchung."""
    calls = []
    echt = ged.offen_erledigen
    echt_book = flow.kal.book_slot
    ged.offen_erledigen = lambda sit, note="": calls.append(note)
    flow.kal.book_slot = lambda tenant, ctx, slot_iso="": {
        "ok": True, "booked": True, "slotIso": slot_iso or "2026-09-10T09:00",
        "appointmentId": "a1", "spoken": "Der Termin ist fest eingetragen.",
    }
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s["modus"] = "buchen"
        s["slotIso"] = "2026-09-10T09:00"
        s["vorname"] = "Martin"
        s["nachname"] = "Berger"
        s["telefon"] = "01771234567"
        s["telefonOk"] = True
        s["grund"] = "Kontrolle"
        s["arzt"] = {"calendarId": "c1", "calendarName": "Dr. Petsas"}
        sit["gedaechtnisOffen"] = ["evt-1"]
        flow._buchen(sit)
        assert calls == []
        assert sit["gedaechtnisOffen"] == ["evt-1"]
    finally:
        ged.offen_erledigen = echt
        flow.kal.book_slot = echt_book
