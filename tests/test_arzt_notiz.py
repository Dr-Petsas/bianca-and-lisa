"""W-ARZT-NOTIZ (Chef 08.09.2026): vor dem Buchungsabschluss nach einer
Notiz fuer den Doktor fragen. Der Wortlaut landet im Terminpopup.
"""

from bianca import flow, gehirn
from kern.tenants import laden


def _sit() -> dict:
    return {
        "tenant": laden("meddent"),
        "messages": [{"role": "system", "content": "x"}],
        "stimme": "Bianca",
    }


def _bereit(sit: dict) -> dict:
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "bestaetigen", "frage": "bestaetigung",
        "warSchonMal": False, "grund": "Kontrolluntersuchung",
        "pzr": "nein",
        "motivName": "KCH Kontrolluntersuchung", "wunsch": {},
        "vorname": "Julia", "nachname": "Berger", "buchstabiert": True,
        "telefon": "01776004600", "telefonOk": True,
        "slotIso": "2026-09-10T09:00:00+02:00",
        "arzt": {"typ": "genannt", "calendarId": "cal-p", "calendarName": "Petsas"},
    })
    sit["offered"] = [{"iso": s["slotIso"], "spoken": "Donnerstag um neun"}]
    sit["angebotKalender"] = {"calendarId": "cal-p", "calendarName": "Petsas"}
    return s


def _ok_book(tenant, ctx, slot_iso=""):
    return {
        "ok": True, "booked": True, "slotIso": slot_iso,
        "appointmentId": "apt-1",
        "spoken": "Der Termin ist fest eingetragen.",
    }


def test_ja_auf_eintragen_fragt_nach_doktor_notiz():
    sit = _sit()
    _bereit(sit)
    z = flow.zug(sit, "Ja.")
    s = gehirn.sammler(sit)
    assert z and "Notiz" in z["text"] and "Doktor" in z["text"]
    assert s["phase"] == "bestaetigen"
    assert s["frage"] == "arzt_notiz"
    assert s["arztNotizFrage"] == "gefragt"
    assert s["phase"] != "gebucht"


def test_nein_auf_notizfrage_bucht_ohne_notiz():
    sit = _sit()
    _bereit(sit)
    notizen: list[str] = []
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    flow.kal.book_slot = _ok_book
    flow.kal.note_appointment = (
        lambda tenant, ctx, sit2=None, note="": notizen.append(note) or {"ok": True}
    )
    try:
        flow.zug(sit, "Ja.")
        z = flow.zug(sit, "Nein, danke.")
        s = gehirn.sammler(sit)
        assert s["phase"] == "gebucht"
        assert s["arztNotizFrage"] == "nein"
        assert not s["arztNotiz"]
        assert z and "eingetragen" in z["text"].lower()
        assert not any("Anrufer an den Behandler" in n for n in notizen)
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note


def test_ja_dann_diktat_landet_im_terminpopup():
    sit = _sit()
    _bereit(sit)
    notizen: list[str] = []
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    flow.kal.book_slot = _ok_book
    flow.kal.note_appointment = (
        lambda tenant, ctx, sit2=None, note="": notizen.append(note) or {"ok": True}
    )
    try:
        flow.zug(sit, "Ja, bitte eintragen.")
        z1 = flow.zug(sit, "Ja.")
        assert z1 and "mitgeben" in z1["text"].lower()
        assert gehirn.sammler(sit)["frage"] == "arzt_notiz_diktat"
        z2 = flow.zug(sit, "Bitte die Angst vor der Spritze ansprechen.")
        s = gehirn.sammler(sit)
        assert s["phase"] == "gebucht"
        assert "Angst vor der Spritze" in s["arztNotiz"]
        assert z2 and "notiz" in z2["text"].lower()
        assert any("Angst vor der Spritze" in n and "Behandler" in n for n in notizen), notizen
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note


def test_ja_mit_wortlaut_im_selben_satz_bucht_direkt():
    """„Ja, notier Angst vor Spritzen“ — keine Extra-Frage."""
    sit = _sit()
    _bereit(sit)
    notizen: list[str] = []
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    flow.kal.book_slot = _ok_book
    flow.kal.note_appointment = (
        lambda tenant, ctx, sit2=None, note="": notizen.append(note) or {"ok": True}
    )
    try:
        z = flow.zug(sit, "Ja, notier bitte die Angst vor Spritzen.")
        s = gehirn.sammler(sit)
        assert s["phase"] == "gebucht"
        assert "Angst vor Spritzen" in s["arztNotiz"]
        assert "Soll ich für den Termin noch eine Notiz" not in (z.get("text") or "")
        assert any("Angst vor Spritzen" in n for n in notizen), notizen
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note


def test_unklar_zweimal_bucht_ohne_notiz():
    sit = _sit()
    _bereit(sit)
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    flow.kal.book_slot = _ok_book
    flow.kal.note_appointment = lambda *a, **k: {"ok": True}
    try:
        flow.zug(sit, "Ja.")
        z1 = flow.zug(sit, "Äh.")
        assert z1 and "Notiz" in z1["text"]
        z2 = flow.zug(sit, "Hm.")
        s = gehirn.sammler(sit)
        assert s["phase"] == "gebucht"
        assert s["arztNotizFrage"] == "nein"
        assert z2 and "eingetragen" in z2["text"].lower()
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note


def test_arzt_notiz_aus_streift_vorspann():
    assert gehirn.arzt_notiz_aus("Ja, notier bitte die Angst vor Spritzen.") == (
        "die Angst vor Spritzen"
    )
    assert not gehirn.hat_arzt_notiz_inhalt("Ja, bitte.")
    assert gehirn.ist_nichts_notiz("Nein, danke.")
    assert not gehirn.ist_nichts_notiz("Nein, aber sag ihm ich habe Angst vor Spritzen")
