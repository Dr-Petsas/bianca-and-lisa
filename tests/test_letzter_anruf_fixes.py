"""Fixes aus dem Live-Anruf 09.09.2026 (Nachbar-Schmattke-Buchung) — offline.

Chef-Befund an dem Anruf:
  1. "Der Nachbar heisst Schmattke" -> "Nachbar" landete als Vorname.
  2. "Nehmen Sie meine Nummer" -> bekannte Anrufernummer wurde nicht genutzt.
  3. Der unfreundliche Satz "Ohne eine echte Handynummer lege ich niemanden an."
  4. Nach der Nummern-Rueckfrage kam "Welcher davon passt Ihnen?" DOPPELT,
     obwohl der Slot laengst gewaehlt und bestaetigt war.
  5. Die Termin-Notiz nannte nicht, dass es der Nachbar des Anrufers ist.
"""

from bianca import flow, gehirn
from kern import patients
from kern.tenants import laden

KATALOG = [
    {"id": "kch-k", "name": "KCH Kontrolluntersuchung", "calendarIds": [],
     "allowOnlineBooking": True, "duration": 15},
]


def _sit() -> dict:
    sit = {"tenant": laden("meddent"),
           "messages": [{"role": "system", "content": "x"}],
           "motivKatalog": list(KATALOG)}
    sit["anrufer"] = {
        "vorname": "Michael", "nachname": "Petsas", "patientId": "pat-1",
        "geschlecht": "male", "telefon": "+491776004600",
    }
    return sit


# --- 1. Rollenwort ist kein Vorname ------------------------------------------

def test_nachbar_ist_kein_vorname():
    s = gehirn.sammler(_sit_gehirn())
    s["fuerWen"] = "nachbar"
    s["frage"] = "nachname"
    gehirn._name_aufnehmen(s, "Der Nachbar heißt Schmattke.", erzwungen=True)
    assert s["nachname"] == "Schmattke"
    assert s["vorname"].lower() != "nachbar"


def test_rollenwort_filter_nur_bei_fuer_wen():
    # Ohne Fuer-Wen bleibt ein echter Nachname wie "Mann" unangetastet.
    s = gehirn.sammler(_sit_gehirn())
    s["frage"] = "nachname"
    gehirn._name_aufnehmen(s, "Ich heiße Peter Mann.", erzwungen=True)
    assert s["nachname"] == "Mann"
    assert s["vorname"] == "Peter"


def _sit_gehirn() -> dict:
    return {"tenant": laden("meddent"),
            "messages": [{"role": "system", "content": "x"}]}


# --- 2. "Nehmen Sie meine Nummer" nutzt die bekannte Anrufernummer -----------

def test_meine_nummer_uebernimmt_anrufernummer():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    neu = gehirn.einsammeln(sit, "Nehmen Sie einfach meine Nummer.")
    assert "telefonBekannt" in neu
    assert s["telefonOk"] is False
    # +491776004600 -> normalisiert die volle, korrekte Nummer.
    assert s["telefonBekannt"].endswith("6004600")
    assert s["telefonOffen"] == s["telefonBekannt"]
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "telefon_check"
    assert "Bestätigungs-SMS" in frage


def test_meine_nummer_ohne_bekannte_nummer_beharrt_nicht():
    sit = _sit()
    sit["anrufer"] = {}  # unterdrueckte Nummer / Dock ohne Anrufer-ID
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    neu = gehirn.einsammeln(sit, "Nehmen Sie meine Nummer.")
    assert "telefonAkte" in neu
    assert s["telefonAkte"] is True


# --- 3. Freundlichere Formulierung -------------------------------------------

def test_kein_unfreundlicher_handynummer_satz():
    tenant = laden("meddent")
    res = patients.akte_anlegen(tenant, first="Peter", last="Schmattke", phone="")
    assert not res["ok"]
    assert "lege ich niemanden an" not in res["spoken"]
    assert "Terminbestätigung" in res["spoken"] or "erreichen" in res["spoken"]


# --- 5. Fuer-Wen-Notiz nennt Anrufer + Beziehung -----------------------------

def test_fuer_wen_notiz_nennt_anrufer_und_beziehung():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "fuerWen": "nachbar",
              "vorname": "Peter", "nachname": "Schmattke", "buchstabiert": True,
              "warSchonMal": False, "versicherungOk": True, "telefon": "+491776004600",
              "slotIso": "2026-09-09T12:45:00+02:00",
              "phase": "bestaetigen", "frage": "bestaetigung"})
    notes: list[str] = []
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    flow.kal.book_slot = lambda tenant, ctx, slot_iso="": {
        "ok": True, "booked": True, "slotIso": slot_iso,
        "spoken": "Der Termin ist eingetragen."}
    flow.kal.note_appointment = lambda tenant, ctx, sit2, note="": notes.append(note)
    echt_hg = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda _s: None
    try:
        flow._buchen(sit)
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note
        flow.hintergrund.anstossen = echt_hg
    assert any("Nachbar" in n and "Michael Petsas" in n for n in notes), notes


# --- 4. Keine doppelte Slotwahl nach Nummern-Umweg ---------------------------

def test_buch_intent_nach_nummer_bucht_direkt_ohne_slotwahl():
    # Slot war gewaehlt + Ja gesagt, nur die Nummer fehlte -> buchIntent.
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "slotIso": "2026-09-09T12:45:00+02:00",
              "phase": "bestaetigen"})
    # Buchung scheitert an fehlender Nummer:
    echt_book = flow.kal.book_slot
    echt_hg = flow.hintergrund.anstossen
    flow.kal.book_slot = lambda tenant, ctx, slot_iso="": {
        "ok": False, "booked": False, "slotIso": slot_iso,
        "spoken": "Für die Terminbestätigung brauche ich noch eine Handynummer."}
    flow.hintergrund.anstossen = lambda _s: None
    try:
        flow._buchen(sit)
        assert sit.get("buchIntent") is True
        assert s["frage"] == "telefon"
        assert s["slotIso"]  # Slot bleibt erhalten, wird nicht verworfen
    finally:
        flow.kal.book_slot = echt_book
        flow.hintergrund.anstossen = echt_hg
