"""W-SCHLEIFE (04.09.2026) — die drei Doppelschleifen aus dem Live-Anruf.

Session 55f9b05a…, 03.09. ~22:44 UTC, Flughafen. Bianca fragte doppelt
nach Schon-mal, Behandler und viermal „Soll ich das so eintragen?",
obwohl der Anrufer „Nein" / „Der Name." / „Ändere den Namen auf Levi"
sagte. Offline, ohne LLM und ohne Netz.
"""

from bianca import flow, gehirn
from kern.tenants import laden

KATALOG = [
    {"id": "kch-k", "name": "KCH Kontrolluntersuchung", "calendarIds": [],
     "allowOnlineBooking": True, "duration": 15},
]


def _sit() -> dict:
    return {"tenant": laden("meddent"),
            "messages": [{"role": "system", "content": "x"}],
            "motivKatalog": list(KATALOG)}


def _ohne_hintergrund(fn):
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        return fn()
    finally:
        flow.hintergrund.anstossen = echt


def _bis_bestaetigen(sit: dict) -> dict:
    """Readback-Stand wie live: falscher Name, Slot liegt, Bestätigung offen."""
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "fuerWen": "sohn",
        "kontaktName": "Kiriakos Tzannis",
        "anruferCheck": "ja", "warSchonMal": True,
        "vorname": "Ja", "nachname": "Udrpetter", "buchstabiert": True,
        "bekannt": False, "patientId": "",
        "telefon": "015253904756", "telefonOk": True,
        "arzt": {"typ": "egal", "calendarId": "zex5bmv5jfIHWVW6zHbg",
                 "calendarName": "Doktor Michael Petsas"},
        "grund": "Kontrolluntersuchung", "motivId": "kch-k",
        "motivName": "KCH Kontrolluntersuchung", "wunsch": {},
        "slotIso": "2026-09-08T09:30:00+02:00",
        "phase": "bestaetigen", "frage": "bestaetigung",
    })
    sit["offered"] = [{"iso": s["slotIso"], "spoken": "Dienstag um halb zehn"}]
    return s


# --- 1. Anlauf / Ja ----------------------------------------------------------

def test_uh_ja_ist_ja():
    assert gehirn.ist_ja("Uh ja.")
    assert gehirn.ist_ja("Uh ja")
    assert gehirn.ist_ja("uhm ja")


def test_correct_ist_ja():
    assert gehirn.ist_ja("Correct.")
    assert gehirn.ist_ja("Correct")


def test_schonmal_uh_ja_wird_geerntet():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "schonmal", "fuerWen": "sohn"})
    neu = gehirn.einsammeln(sit, "Uh ja.")
    assert "warSchonMal" in neu
    assert s["warSchonMal"] is True


# --- 2. Dr. Petter ist kein Patientenname ------------------------------------

def test_dr_petter_auf_arztfrage_ist_kein_name():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "arzt", "fuerWen": "sohn",
              "warSchonMal": True})
    gehirn.einsammeln(sit, "Uh Dr. Petter.")
    assert not s["nachname"] and not s["vorname"]


def test_dr_petter_ohne_ich_heisse_ist_kein_name():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "", "warSchonMal": True})
    gehirn.einsammeln(sit, "Uh Dr. Petter.")
    assert not s["nachname"]


def test_ich_heisse_bleibt_erlaubt():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "name"})
    gehirn.einsammeln(sit, "Ich heiße Levi Tzannis.")
    assert s["vorname"] == "Levi" and s["nachname"] == "Tzannis"


# --- 3. Bestätigung Nein → Name, nicht schon wieder eintragen ----------------

def test_nein_dann_der_name_fragt_nach_dem_sohn():
    def lauf():
        sit = _sit()
        s = _bis_bestaetigen(sit)
        z1 = flow.zug(sit, "Nein.")
        assert z1 and "ändern" in z1["text"].lower(), z1
        assert s["frage"] == "aenderung"
        assert s["slotIso"] == "2026-09-08T09:30:00+02:00"
        z2 = flow.zug(sit, "Der Name.")
        assert z2, z2
        assert "eintragen" not in z2["text"].lower()
        assert "heißt" in z2["text"].lower() and "sohn" in z2["text"].lower()
        assert not s["nachname"] and not s["vorname"]
        assert s["frage"] == "name"
        assert s["slotIso"] == "2026-09-08T09:30:00+02:00"
        assert s["telefon"] == "015253904756"
        assert s["kontaktName"] == "Kiriakos Tzannis"
    _ohne_hintergrund(lauf)


def test_aendere_namen_auf_levi_im_selben_satz():
    def lauf():
        sit = _sit()
        s = _bis_bestaetigen(sit)
        flow.zug(sit, "Nein.")
        z = flow.zug(sit, "Ändere den Namen auf Levi.")
        assert z, z
        assert "eintragen" not in z["text"].lower()
        assert s["vorname"] == "Levi"
        assert not s["nachname"]
        assert "nachname" in z["text"].lower() or "nachnamen" in z["text"].lower()
    _ohne_hintergrund(lauf)


def test_der_name_direkt_auf_die_bestaetigung():
    """Auch ohne vorheriges nacktes Nein: 'Der Name.' auf die Readback-Frage."""
    def lauf():
        sit = _sit()
        s = _bis_bestaetigen(sit)
        z = flow.zug(sit, "Der Name.")
        assert z and "eintragen" not in z["text"].lower(), z
        assert "heißt" in z["text"].lower()
        assert not s["nachname"]
        assert s["slotIso"]
    _ohne_hintergrund(lauf)


def test_nummer_aendern_fragt_telefon():
    def lauf():
        sit = _sit()
        s = _bis_bestaetigen(sit)
        flow.zug(sit, "Nein.")
        z = flow.zug(sit, "Die Nummer.")
        assert z and "nummer" in z["text"].lower(), z
        assert s["frage"] == "telefon"
        assert not s["telefonOk"]
        assert s["slotIso"]
    _ohne_hintergrund(lauf)


def test_zeitpunkt_aendern_verwirft_nur_den_slot():
    def lauf():
        sit = _sit()
        s = _bis_bestaetigen(sit)
        flow.zug(sit, "Nein.")
        z = flow.zug(sit, "Der Zeitpunkt.")
        assert z and "vormittag" in z["text"].lower(), z
        assert s["frage"] == "wunsch"
        assert not s["slotIso"]
        assert s["nachname"] == "Udrpetter"
    _ohne_hintergrund(lauf)


# --- 4. Unbekannter Behandler: Quittung + nächste Frage ----------------------

def test_unbekannter_arzt_stellt_namensfrage_im_selben_zug():
    def lauf():
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({
            "modus": "buchen", "fuerWen": "sohn", "frage": "arzt",
            "warSchonMal": True, "grund": "Kontrolluntersuchung",
            "wunsch": {},
        })
        z = flow.zug(sit, "Keine Ahnung, wie der Zahnarzt heisst.")
        assert z, z
        assert "finden wir schon" in z["text"].lower()
        assert "heißt" in z["text"].lower() and "sohn" in z["text"].lower()
        assert "eintragen" not in z["text"].lower()
        assert (s.get("arzt") or {}).get("typ") == "unbekannt"
        assert s["frage"] == "name"
    _ohne_hintergrund(lauf)
