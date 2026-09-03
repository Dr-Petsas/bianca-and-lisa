"""W-FUER-WEN (Chef 03.09.2026) — offline, ohne LLM und ohne Netz.

Chef: "wir haben noch nicht den fall trainiert wo der anrufer nicht für sich
sondern für jemand anderen den termin bucht. 'Der Termin ist für Sie selbst,
richtig?' das fehlt ... korrigiere das rein"

Live-Fall (Anruf 21:43): Der Vater (per Rufnummer erkannt) sagt DREIMAL
"der Termin ist für meinen Sohn" — Bianca buchte trotzdem stur auf den
Vater. Diese Tests decken alle drei Loecher:
  1. "Meinen Sohn braucht einen Termin" (ohne "für") wurde nicht erkannt.
  2. "Ja, aber für meinen Sohn" auf den Anrufer-Check uebernahm die
     Kartei-Identitaet des Vaters als PATIENT und liess sie nie wieder los.
  3. "Nein, der ist für meinen Sohn" auf die Bestaetigungsfrage lief in
     "Was darf ich ändern…" ins Leere.
"""

from bianca import flow, gehirn
from kern.tenants import laden

# Mini-Katalog: kein Live-Abruf im Test.
KATALOG = [
    {"id": "kch-k", "name": "KCH Kontrolluntersuchung", "calendarIds": [],
     "allowOnlineBooking": True, "duration": 15},
]


def _sit() -> dict:
    return {"tenant": laden("meddent"),
            "messages": [{"role": "system", "content": "x"}],
            "motivKatalog": list(KATALOG)}


def _sit_mit_anrufer() -> dict:
    """Sitzung mit Kartei-Treffer zur Anrufernummer (wie live)."""
    sit = _sit()
    sit["anrufer"] = {
        "vorname": "Kiriakos", "nachname": "Tzannis", "patientId": "pat-77",
        "geschlecht": "male", "telefon": "+4915253904756",
    }
    return sit


def _ohne_hintergrund(fn):
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        return fn()
    finally:
        flow.hintergrund.anstossen = echt


# --- 1. Erkennung des Fuer-Wen-Signals ---------------------------------------

def test_signal_auch_ohne_fuer():
    for satz, wen in [
        ("Meinen Sohn braucht einen Termin nächste Woche.", "sohn"),
        ("Mein Sohn braucht einen Termin.", "sohn"),
        ("Ich brauche einen Termin für meinen Sohn.", "sohn"),
        ("Einen Termin für meine Tochter, bitte.", "tochter"),
        ("Meine Frau möchte einen Termin.", "frau"),
        ("Mein Mann hat starke Zahnschmerzen.", "mann"),
        ("Für unsere Oma bitte.", "oma"),
        ("Der Termin ist nicht für mich.", "andere"),
        ("Ich rufe für jemand anderen an.", "andere"),
    ]:
        assert gehirn.fuer_wen_signal(satz) == wen, satz


def test_signal_keine_falschen_treffer():
    for satz in [
        "Meine Tochter heiratet am Wochenende!",
        "Meine Frau hat gesagt, ich soll anrufen.",
        "Ich hätte gern einen Termin für mich.",
        "Kontrolle bitte, am dritten Oktober.",
    ]:
        assert gehirn.fuer_wen_signal(satz) == "", satz


# --- 2. Die Chef-Frage: "Der Termin ist für Sie selbst, richtig?" ------------

def test_buchen_check_fragt_fuer_sie_selbst():
    def lauf():
        sit = _sit_mit_anrufer()
        z1 = flow.zug(sit, "Guten Tag, ich hätte gern einen Termin.")
        assert z1 and "Der Termin ist für Sie selbst, richtig?" in z1["text"], z1
        assert gehirn.sammler(sit)["frage"] == "anrufer_check"
    _ohne_hintergrund(lauf)


def test_verwalten_check_bleibt_stimmt_das_so():
    # Absage/Auskunft: reine Identitaets-Frage, kein "für Sie selbst".
    sit = _sit_mit_anrufer()
    frage = gehirn.anrufer_check_frage(sit)
    assert "Stimmt das so?" in frage and "selbst" not in frage


# --- 3. "Ja, aber für meinen Sohn" — Identitaet loest sich vom Patienten -----

def test_ja_aber_fuer_sohn_loest_identitaet():
    def lauf():
        sit = _sit_mit_anrufer()
        flow.zug(sit, "Guten Tag, ich hätte gern einen Termin.")
        z2 = flow.zug(sit, "Ja, aber ich brauche einen Termin für meinen Sohn.")
        s = gehirn.sammler(sit)
        assert s["fuerWen"] == "sohn"
        assert s["kontaktName"] == "Kiriakos Tzannis"
        # Patient ist NICHT mehr der Vater:
        assert not s["nachname"] and not s["vorname"] and not s["patientId"]
        assert not s["bekannt"] and not s["buchstabiert"]
        assert s["warSchonMal"] is None
        assert sit.get("patient") is None
        # Aber: die Nummer des Anrufers bleibt als Kontakt (SMS).
        assert s["telefonOk"] and s["telefon"] == "015253904756"
        # Quittung + naechste Frage drehen sich um den Sohn:
        assert z2 and "für Ihren Sohn" in z2["text"], z2
        assert "War Ihr Sohn schon einmal bei uns" in z2["text"], z2
    _ohne_hintergrund(lauf)


def test_nein_ohne_rolle_fragt_fuer_wen():
    def lauf():
        sit = _sit_mit_anrufer()
        flow.zug(sit, "Ich möchte einen Termin buchen.")
        z2 = flow.zug(sit, "Nein.")
        s = gehirn.sammler(sit)
        assert s["anruferCheck"] == "nein" and s["fuerWen"] == "andere"
        assert not s["nachname"] and not s["patientId"]  # nichts uebernommen
        assert z2 and "für jemand anderen" in z2["text"], z2
    _ohne_hintergrund(lauf)


def test_nein_das_bin_ich_nicht_bleibt_identitaets_fall():
    def lauf():
        sit = _sit_mit_anrufer()
        flow.zug(sit, "Ich möchte einen Termin buchen.")
        z2 = flow.zug(sit, "Nein, das bin ich nicht.")
        s = gehirn.sammler(sit)
        assert s["anruferCheck"] == "nein" and not s["fuerWen"]
        assert z2 and "frisch auf" in z2["text"], z2
    _ohne_hintergrund(lauf)


# --- 4. Spaete Korrektur an der Bestaetigungsfrage ---------------------------

def _bis_bestaetigen(sit: dict) -> dict:
    """Sammler wie im Live-Fall: Vater-Identitaet uebernommen, Slot gewaehlt."""
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "anruferCheck": "ja", "warSchonMal": True,
        "vorname": "Kiriakos", "nachname": "Tzannis", "buchstabiert": True,
        "bekannt": True, "patientId": "pat-77",
        "telefon": "015253904756", "telefonOk": True,
        "arzt": {"typ": "egal", "calendarId": "zex5bmv5jfIHWVW6zHbg",
                 "calendarName": "Doktor Michael Petsas"},
        "grund": "Kontrolluntersuchung", "motivId": "kch-k",
        "motivName": "KCH Kontrolluntersuchung", "wunsch": {},
        "slotIso": "2099-09-10T11:30:00+02:00",
        "phase": "bestaetigen", "frage": "bestaetigung",
    })
    return s


def test_nein_fuer_sohn_an_der_bestaetigung_schreibt_patienten_um():
    def lauf():
        sit = _sit_mit_anrufer()
        s = _bis_bestaetigen(sit)
        z = flow.zug(sit, "Nein, der Termin ist nicht für mich, der ist für meinen Sohn.")
        assert s["fuerWen"] == "sohn"
        assert s["kontaktName"] == "Kiriakos Tzannis"
        assert not s["nachname"] and not s["patientId"] and not s["bekannt"]
        # Slot und Grund bleiben stehen — nur der Patient wird neu erfragt:
        assert s["slotIso"] == "2099-09-10T11:30:00+02:00"
        assert s["grund"] == "Kontrolluntersuchung"
        assert z and "War Ihr Sohn schon einmal bei uns" in z["text"], z
    _ohne_hintergrund(lauf)


def test_reset_nur_einmal_pro_anruf():
    """Der Sohn heisst auch Tzannis: ein zweites 'für meinen Sohn' darf die
    frisch erfasste Sohn-Identitaet NICHT wieder wegwischen."""
    def lauf():
        sit = _sit_mit_anrufer()
        s = _bis_bestaetigen(sit)
        flow.zug(sit, "Der Termin ist für meinen Sohn.")
        # Sohn-Daten erfasst (gleicher Nachname wie der Vater, Kartei-Treffer):
        s.update({"vorname": "Niko", "nachname": "Tzannis", "bekannt": True,
                  "patientId": "pat-88", "buchstabiert": True,
                  "warSchonMal": True})
        gehirn.einsammeln(sit, "Es ist wirklich für meinen Sohn, ja.")
        assert s["nachname"] == "Tzannis" and s["patientId"] == "pat-88"
        assert s["kontaktName"] == "Kiriakos Tzannis"
    _ohne_hintergrund(lauf)


# --- 5. Fragen drehen sich um den Dritten ------------------------------------

def test_fragen_nennen_den_dritten():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "fuerWen": "tochter"})
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "schonmal" and "Ihre Tochter" in frage, frage
    s["warSchonMal"] = True
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "arzt" and "Ihre Tochter" in frage, frage
    s["arzt"] = {"typ": "egal", "calendarId": "c1", "calendarName": "Dr. P"}
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "name" and "Wie heißt Ihre Tochter?" in frage, frage


def test_versicherungsfrage_fragt_nach_dem_dritten():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "fuerWen": "sohn", "warSchonMal": False,
              "arzt": {"typ": "egal", "calendarId": "c1"},
              "grund": "Kontrolle", "wunsch": {},
              "vorname": "Niko", "nachname": "Tzannis", "buchstabiert": True,
              "telefon": "015253904756", "telefonOk": True})
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "versicherung" and "Ihr Sohn" in frage, frage


def test_doch_fuer_mich_loest_missverstaendnis():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "fuerWen": "andere"})
    gehirn.einsammeln(sit, "Nein nein, der Termin ist für mich selbst.")
    assert s["fuerWen"] == ""


# --- 6. Termin-Notiz fuer die Praxis -----------------------------------------

def test_buchung_traegt_angehoerigen_notiz():
    def lauf():
        sit = _sit_mit_anrufer()
        s = _bis_bestaetigen(sit)
        flow.zug(sit, "Der Termin ist für meinen Sohn.")
        s.update({"vorname": "Niko", "nachname": "Tzannis", "buchstabiert": True,
                  "warSchonMal": False, "versicherungOk": True,
                  "phase": "bestaetigen", "frage": "bestaetigung"})
        notes: list[str] = []
        echt_book = flow.kal.book_slot
        echt_note = flow.kal.note_appointment
        flow.kal.book_slot = lambda tenant, ctx, slot_iso="": {
            "ok": True, "booked": True, "slotIso": slot_iso,
            "spoken": "Der Termin ist eingetragen.",
        }
        flow.kal.note_appointment = (
            lambda tenant, ctx, sit2, note="": notes.append(note))
        try:
            flow._buchen(sit)
        finally:
            flow.kal.book_slot = echt_book
            flow.kal.note_appointment = echt_note
        assert any("Kiriakos Tzannis" in n and "Sohn" in n for n in notes), notes
    _ohne_hintergrund(lauf)
