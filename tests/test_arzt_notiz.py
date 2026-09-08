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


def test_unklar_einmal_bucht_ohne_notiz():
    """Einmal fragen — „Äh.“ bucht, statt die Doktor-Frage zu wiederholen."""
    sit = _sit()
    _bereit(sit)
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    flow.kal.book_slot = _ok_book
    flow.kal.note_appointment = lambda *a, **k: {"ok": True}
    try:
        flow.zug(sit, "Ja.")
        z = flow.zug(sit, "Äh.")
        s = gehirn.sammler(sit)
        assert s["phase"] == "gebucht"
        assert s["arztNotizFrage"] == "nein"
        assert z and "eingetragen" in z["text"].lower()
        assert "Notiz" not in (z.get("text") or "")
        assert "mitgeben" not in (z.get("text") or "").lower()
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note


def test_petsas_preis_auf_notiz_geht_nicht_ans_llm():
    """Live Petsas 08.09.: Preisfrage auf die Notiz — KI antwortet, nie LLM."""
    sit = _sit()
    _bereit(sit)
    s = gehirn.sammler(sit)
    s["grund"] = "professionelle Zahnreinigung"
    s["motivName"] = "PRO Professionelle Zahnreinigung"
    s["pzr"] = "ja"
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    flow.kal.book_slot = _ok_book
    flow.kal.note_appointment = lambda *a, **k: {"ok": True}
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        flow.zug(sit, "Ja, bitte.")
        assert s["frage"] == "arzt_notiz"
        z = flow.zug(
            sit,
            "Ja, was kostet die Zahnreinigung? Bitte vorher mit mir abklärend.",
        )
        text = (z or {}).get("text") or ""
        assert z is not None
        assert "einhundertzwanzig" in text
        assert "besprechen" not in text.lower()
        assert "mitgeben" not in text.lower()
        assert "Soll ich für den Termin noch eine Notiz" not in text
        assert s["arztNotizFrage"] == "nein"
        z2 = flow.zug(sit, "Ja, bitte.")
        text2 = (z2 or {}).get("text") or ""
        assert "mitgeben" not in text2.lower()
        assert "Notiz für den Doktor" not in text2
    finally:
        flow.hintergrund.anstossen = echt
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note


def test_zwischenfrage_auf_diktat_ist_die_notiz():
    """Parkfrage aufs Diktat → Notiz, buchen — nie ans LLM, nie nochmal fragen."""
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
        flow.zug(sit, "Ja.")
        assert gehirn.sammler(sit)["frage"] == "arzt_notiz_diktat"
        z = flow.zug(sit, "Wo kann ich parken?")
        s = gehirn.sammler(sit)
        assert z is not None
        assert s["phase"] == "gebucht"
        assert "parken" in s["arztNotiz"].lower()
        assert "mitgeben" not in (z.get("text") or "").lower()
        assert any("parken" in n.lower() for n in notizen), notizen
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note


def test_bitte_auf_diktat_bucht_ohne_zweite_frage():
    sit = _sit()
    _bereit(sit)
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    flow.kal.book_slot = _ok_book
    flow.kal.note_appointment = lambda *a, **k: {"ok": True}
    try:
        flow.zug(sit, "Ja.")
        flow.zug(sit, "Ja.")
        z = flow.zug(sit, "Bitte?")
        s = gehirn.sammler(sit)
        assert s["phase"] == "gebucht"
        assert s["arztNotizFrage"] == "nein"
        assert z and "eingetragen" in z["text"].lower()
        assert "mitgeben" not in z["text"].lower()
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note


def test_arzt_notiz_aus_streift_vorspann():
    assert gehirn.arzt_notiz_aus("Ja, notier bitte die Angst vor Spritzen.") == (
        "die Angst vor Spritzen"
    )
    assert not gehirn.hat_arzt_notiz_inhalt("Ja, bitte.")
    assert gehirn.ist_nichts_notiz("Nein, danke.")
    assert not gehirn.ist_nichts_notiz("Nein, aber sag ihm ich habe Angst vor Spritzen")
