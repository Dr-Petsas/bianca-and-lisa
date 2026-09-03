"""W-BLEACHING (Chef 03.09.2026) — offline, ohne LLM und ohne Netz.

Chef: "wenn jemand anruft um eine Zahnreinigung zu buchen kannst du auch
fragen ob die Zähne mit aufgehellt werden sollen.. Die Aufhellung / bleaching
dauert ca 1 Stunde länger und kostet 350 euro zusätzlich. Sie ist unter
Umständen nicht möglich, wenn in der Front Zahnersatz, also Kronen oder
Brücken vorhanden sind, es sei denn die Zähne sollen bei zu hellen kronen
durch bleaching an die zahnkronen angepasst werden. [...] wenn der Patient
sich ungewiss ist [...] sagst du du hast eine notiz gemacht und der Doktor
schaut sich das in Ruhe an und berät sie"
"""

from bianca import flow, gehirn
from kern.tenants import laden

# Kunst-Katalog: die Praxis fuehrt Zahnreinigung UND Aufhellung.
KATALOG = [
    {"id": "pzr-30", "name": "PRO professionelle Zahnreinigung", "calendarIds": [], "allowOnlineBooking": True, "duration": 30},
    {"id": "bl-45",  "name": "PRO Zahnaufhellung",               "calendarIds": [], "allowOnlineBooking": True, "duration": 45},
    {"id": "kch-k",  "name": "KCH Kontrolluntersuchung",         "calendarIds": [], "allowOnlineBooking": True, "duration": 15},
]
KATALOG_OHNE = [v for v in KATALOG if "aufhell" not in v["name"].lower()]


def _sit(katalog=None) -> dict:
    return {
        "tenant": laden("meddent"),
        "messages": [{"role": "system", "content": "x"}],
        "motivKatalog": list(KATALOG if katalog is None else katalog),
    }


def _pzr_sammler(sit: dict) -> dict:
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": True,
        "vorname": "Julia", "nachname": "Berger", "buchstabiert": True,
        "grund": "professionelle Zahnreinigung",
        "grundWortlaut": "einmal Zahnreinigung bitte",
        "motivId": "pzr-30", "motivName": "PRO professionelle Zahnreinigung",
    })
    return s


# --- Wann wird angeboten? ---------------------------------------------------

def test_faellig_bei_pzr_grund_und_katalog():
    sit = _sit()
    _pzr_sammler(sit)
    assert gehirn.bleaching_faellig(sit)


def test_nicht_faellig_ohne_aufhellung_im_katalog():
    """Tenant-Wache: fuehrt die Praxis kein Bleaching, kommt die Frage nie."""
    sit = _sit(KATALOG_OHNE)
    _pzr_sammler(sit)
    assert not gehirn.bleaching_faellig(sit)


def test_nicht_faellig_bei_anderem_grund():
    sit = _sit()
    s = _pzr_sammler(sit)
    s.update({"grund": "Kontrolluntersuchung", "grundWortlaut": "einmal alles kontrollieren",
              "motivId": "kch-k", "motivName": "KCH Kontrolluntersuchung"})
    assert not gehirn.bleaching_faellig(sit)


def test_nicht_faellig_wenn_aufhellung_selbst_der_grund():
    sit = _sit()
    s = _pzr_sammler(sit)
    s["grundWortlaut"] = "Zahnreinigung und einmal aufhellen bitte"
    assert not gehirn.bleaching_faellig(sit)


def test_nur_einmal_pro_anruf():
    sit = _sit()
    s = _pzr_sammler(sit)
    s["bleaching"] = "nein"
    assert not gehirn.bleaching_faellig(sit)


def test_einschub_stellt_die_frage_mit_dauer_ohne_preis():
    # Chef 03.09.2026: "kosten nur bei nachfrage nennen. nicht mit den
    # kosten ins haus fallen" — die Frage nennt die Dauer, NIE den Preis.
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = _pzr_sammler(sit)
        r = flow.zug(sit, "Am liebsten Dienstag vormittags.")
        assert r and "aufhellen" in r["text"].lower(), r
        assert "eine Stunde länger" in r["text"]
        assert "dreihundertfünfzig" not in r["text"]
        assert "350" not in r["text"]
        assert "Euro" not in r["text"]
        assert s["bleaching"] == "gefragt" and s["frage"] == "bleaching"
    finally:
        flow.hintergrund.anstossen = echt


# --- Die Antworten ----------------------------------------------------------

def _gefragt(sit: dict) -> dict:
    s = _pzr_sammler(sit)
    s.update({"bleaching": "gefragt", "frage": "bleaching", "wunsch": {}})
    return s


def test_ja_fuehrt_zum_zahnersatz_check():
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = _gefragt(sit)
        r = flow.zug(sit, "Ja, gerne!")
        assert r and "Sehr gerne" in r["text"], r
        assert "Zahnersatz" in r["text"] and "Kronen" in r["text"]
        assert s["bleaching"] == "check" and s["frage"] == "bleaching_check"
    finally:
        flow.hintergrund.anstossen = echt


def test_check_nein_plant_aufhellung_fest_ein():
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = _gefragt(sit)
        s.update({"bleaching": "check", "frage": "bleaching_check"})
        r = flow.zug(sit, "Nein, habe ich nicht.")
        assert r and "Aufhellung mit ein" in r["text"], r
        assert s["bleaching"] == "ja"
    finally:
        flow.hintergrund.anstossen = echt


def test_check_kronen_fuehrt_zur_beratung():
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = _gefragt(sit)
        s.update({"bleaching": "check", "frage": "bleaching_check"})
        r = flow.zug(sit, "Ja, ich habe vorne zwei Kronen.")
        assert r and "unter Umständen nicht möglich" in r["text"], r
        assert "angepasst" in r["text"]  # Ausnahme: Angleichung an helle Kronen
        assert "Notiz" in r["text"] and "berät" in r["text"]
        assert s["bleaching"] == "beratung" and s["bleachingInfo"] == "zahnersatz"
    finally:
        flow.hintergrund.anstossen = echt


def test_kronen_schon_beim_angebot_fuehren_zur_beratung():
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = _gefragt(sit)
        r = flow.zug(sit, "Hm, ich habe aber vorne eine Brücke.")
        assert r and "Notiz" in r["text"], r
        assert s["bleaching"] == "beratung" and s["bleachingInfo"] == "zahnersatz"
    finally:
        flow.hintergrund.anstossen = echt


def test_unsicher_bekommt_notiz_und_doktor_beraet():
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = _gefragt(sit)
        r = flow.zug(sit, "Ich weiß nicht, ob das bei mir überhaupt geht.")
        assert r and "Notiz" in r["text"] and "berät" in r["text"], r
        assert s["bleaching"] == "beratung" and s["bleachingInfo"] == "unsicher"
    finally:
        flow.hintergrund.anstossen = echt


def test_nein_bleibt_bei_der_zahnreinigung():
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = _gefragt(sit)
        r = flow.zug(sit, "Nein danke.")
        assert r and "nur die Zahnreinigung" in r["text"], r
        assert s["bleaching"] == "nein"
    finally:
        flow.hintergrund.anstossen = echt


def test_datum_mit_dritten_ist_kein_zahnersatz():
    """"Ginge auch der dritte Oktober?" bei offener Aufhellungs-Frage darf
    NICHT als Zahnersatz-Erwaehnung gelten (Regex-Wache)."""
    assert not gehirn._ZAHNERSATZ_RE.search("Ginge auch der dritte Oktober?")
    assert gehirn._ZAHNERSATZ_RE.search("Ich trage die Dritten.")


# --- Die Termin-Notizen -----------------------------------------------------

def _buch_bereit(sit: dict) -> dict:
    s = _pzr_sammler(sit)
    s.update({"slotIso": "2026-09-10T09:00", "arzt": {"typ": "egal"},
              "telefon": "015253904756", "telefonOk": True})
    return s


def _buchen_mit(sit: dict) -> list[str]:
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    notes: list[str] = []
    flow.kal.book_slot = lambda tenant, ctx, slot_iso="": {
        "ok": True, "booked": True, "slotIso": slot_iso,
        "spoken": "Der Termin ist eingetragen.",
    }
    flow.kal.note_appointment = lambda tenant, ctx, sit2, note="": notes.append(note)
    try:
        flow._buchen(sit)
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note
    return notes


def test_buchen_traegt_bleaching_notiz():
    sit = _sit()
    s = _buch_bereit(sit)
    s["bleaching"] = "ja"
    notes = _buchen_mit(sit)
    assert any("PLUS Zahnaufhellung" in n and "350 Euro" in n for n in notes), notes


def test_buchen_traegt_beratungs_notiz_zahnersatz():
    sit = _sit()
    s = _buch_bereit(sit)
    s.update({"bleaching": "beratung", "bleachingInfo": "zahnersatz"})
    notes = _buchen_mit(sit)
    assert any("Zahnersatz im Frontbereich" in n and "beraten" in n for n in notes), notes


def test_buchen_traegt_beratungs_notiz_unsicher():
    sit = _sit()
    s = _buch_bereit(sit)
    s.update({"bleaching": "beratung", "bleachingInfo": "unsicher"})
    notes = _buchen_mit(sit)
    assert any("unsicher" in n and "beraten" in n for n in notes), notes
