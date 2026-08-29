"""Versichertenstatus + Vornamen-Wächter (Chef 29.08.2026) — offline.

Neupatienten werden nach privat/gesetzlich gefragt (Eintrag in die neue
Kartei), Bestandspatienten nur nach >6 Monaten als Rückfrage — und NUR der
Wechsel privat<->gesetzlich zählt. Der Vornamen-Wächter bestimmt das
Geschlecht für die Anrede; unklare Vornamen: Default weiblich + Notiz.
"""

from datetime import datetime, timedelta

from bianca import flow, gehirn
from kern import vornamen
from kern.tenants import laden
from lisa import greeting


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


def _neu_komplett(sit: dict) -> dict:
    """Sammler eines Neupatienten bis einschließlich Telefon füllen."""
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": False, "grund": "Kontrolluntersuchung",
        "wunsch": {}, "vorname": "Peter", "nachname": "Berger",
        "buchstabiert": True, "telefon": "01776004600", "telefonOk": True,
    })
    return s


# --- Vornamen-Wächter ------------------------------------------------------

def test_vornamen_eindeutig():
    assert vornamen.geschlecht("Peter") == "m"
    assert vornamen.geschlecht("Dimitrios") == "m"
    assert vornamen.geschlecht("ahmet") == "m"
    assert vornamen.geschlecht("Anna") == "f"
    assert vornamen.geschlecht("Ayse") == "f"
    assert vornamen.geschlecht("KÄTHE") == ""  # ungelistet ohne -a: unklar


def test_vornamen_doppelname_erster_teil():
    assert vornamen.geschlecht("Hans-Peter") == "m"
    assert vornamen.geschlecht("Anna Lena") == "f"


def test_vornamen_unklar_und_heuristik():
    assert vornamen.geschlecht("Kim") == ""
    assert vornamen.geschlecht("Sascha") == ""
    assert vornamen.geschlecht("") == ""
    # Endungs-Heuristik nur für ungelistete Namen: -a ist fast immer weiblich.
    assert vornamen.geschlecht("Warlia") == "f"
    # Gelistete Ausnahme bleibt männlich trotz -a.
    assert vornamen.geschlecht("Joshua") == "m"


def test_geschlecht_im_sammler_mit_default_weiblich():
    sit = _sit()
    gehirn.einsammeln(sit, "Hier ist Peter Berger, ich brauche einen Termin")
    s = gehirn.sammler(sit)
    assert s["geschlecht"] == "m" and not s["geschlechtUnklar"]

    sit2 = _sit()
    gehirn.einsammeln(sit2, "Hier ist Kim Berger, ich brauche einen Termin")
    s2 = gehirn.sammler(sit2)
    # Chef: unklarer Vorname -> Default weiblich + Notiz-Flag für die Praxis.
    assert s2["geschlecht"] == "f" and s2["geschlechtUnklar"]


def test_kartei_geschlecht_schlaegt_schaetzung():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["geschlecht"] = "m"
    s["geschlechtQuelle"] = "akte"
    gehirn.einsammeln(sit, "Hier ist Andrea Berger, ich brauche einen Termin")
    assert s["geschlecht"] == "m"  # Akte gewinnt, Schätzung fasst nichts an


def test_anrede_gebeugt_und_readback():
    sit = _sit()
    s = _neu_komplett(sit)
    s["geschlecht"] = "m"
    assert gehirn.anrede(s, beugen=True) == "Herrn Berger"
    assert gehirn.anrede(s) == "Herr Berger"
    s["geschlecht"] = "f"
    assert gehirn.anrede(s, beugen=True) == "Frau Berger"
    s["slotIso"] = "2026-09-07T09:00"
    text = flow._readback(sit)["text"]
    assert "für Frau Berger" in text


def test_lisa_anrede_nutzt_vornamen_waechter():
    assert greeting.anrede({"firstName": "Anna", "lastName": "Möllenberg", "gender": ""}) == "Frau Möllenberg"
    # Mehrdeutig bleibt beim vollen Namen — Lisa rät nie.
    assert greeting.anrede({"firstName": "Kim", "lastName": "Berger", "name": "Kim Berger", "gender": ""}) == "Kim Berger"


# --- Versicherung: Neupatient ----------------------------------------------

def test_neupatient_versicherung_ist_letzte_frage():
    sit = _sit()
    s = _neu_komplett(sit)
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "versicherung"
    assert "privat" in frage and "gesetzlich" in frage
    s["frage"] = fid
    gehirn.einsammeln(sit, "Gesetzlich.")
    assert s["versicherungOk"] and s["versicherung"] == "gesetzlich"
    assert not s["versicherungWechsel"]
    fid2, _ = gehirn.naechste_frage(sit)
    assert fid2 == ""
    ctx = flow._ctx_bauen(sit)
    assert ctx["privateInsurance"] is False


def test_neupatient_privat_und_kassenname():
    sit = _sit()
    s = _neu_komplett(sit)
    s["frage"] = "versicherung"
    gehirn.einsammeln(sit, "Ich bin Privatpatient.")
    assert s["versicherung"] == "privat"
    assert flow._ctx_bauen(sit)["privateInsurance"] is True

    sit2 = _sit()
    s2 = _neu_komplett(sit2)
    s2["frage"] = "versicherung"
    gehirn.einsammeln(sit2, "Ich bin bei der Techniker Krankenkasse.")
    assert s2["versicherung"] == "gesetzlich"


def test_versicherung_spontan_mit_kontext():
    sit = _sit()
    s = gehirn.sammler(sit)
    gehirn.einsammeln(sit, "Übrigens bin ich privat versichert.")
    assert s["versicherung"] == "privat" and s["versicherungOk"]
    # Ohne Kontextwort fasst der Deuter nichts an ("privat" allein im Plausch).
    sit2 = _sit()
    s2 = gehirn.sammler(sit2)
    gehirn.einsammeln(sit2, "Das regle ich privat mit meiner Frau.")
    assert not s2["versicherungOk"]


# --- Versicherung: Bestandspatient -----------------------------------------

def _bestand(sit: dict, *, tage_her: int, akte: str = "gesetzlich") -> dict:
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": True, "arzt": {"typ": "egal"},
        "grund": "Kontrolluntersuchung", "wunsch": {}, "vorname": "Peter",
        "nachname": "Berger", "bekannt": True, "patientId": "p-1",
        "aktePhone": "+491776004600", "versicherungAkte": akte,
        "letzterBesuch": (datetime.now().date() - timedelta(days=tage_her)).isoformat() + "T09:00",
    })
    return s


def test_bestand_rueckfrage_nur_nach_sechs_monaten():
    sit = _sit()
    _bestand(sit, tage_her=250)
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "versicherung_check"
    assert "gesetzlich" in frage

    sit2 = _sit()
    _bestand(sit2, tage_her=60)
    fid2, _ = gehirn.naechste_frage(sit2)
    assert fid2 == ""  # frischer Besuch: keine Rückfrage

    sit3 = _sit()
    s3 = _bestand(sit3, tage_her=250)
    s3["letzterBesuch"] = ""  # kein Datum bekannt: nicht raten, nicht fragen
    fid3, _ = gehirn.naechste_frage(sit3)
    assert fid3 == ""


def test_bestand_unveraendert_und_kassenwechsel_egal():
    sit = _sit()
    s = _bestand(sit, tage_her=250)
    s["frage"] = "versicherung_check"
    gehirn.einsammeln(sit, "Ja, das passt noch so.")
    assert s["versicherungOk"] and not s["versicherungWechsel"]
    assert s["versicherung"] == "gesetzlich"

    # Kassenwechsel INNERHALB gesetzlich (AOK -> TK) ist KEIN Wechsel.
    sit2 = _sit()
    s2 = _bestand(sit2, tage_her=250)
    s2["frage"] = "versicherung_check"
    gehirn.einsammeln(sit2, "Ich bin jetzt bei der TK statt bei der AOK.")
    assert s2["versicherungOk"] and not s2["versicherungWechsel"]
    assert s2["versicherung"] == "gesetzlich"


def test_bestand_wechsel_wird_erkannt():
    sit = _sit()
    s = _bestand(sit, tage_her=250)
    s["frage"] = "versicherung_check"
    gehirn.einsammeln(sit, "Nein, ich bin inzwischen privat versichert.")
    assert s["versicherungOk"] and s["versicherungWechsel"]
    assert s["versicherung"] == "privat"

    # Nacktes "Nein" heißt deterministisch: das Gegenteil des Kartei-Stands.
    sit2 = _sit()
    s2 = _bestand(sit2, tage_her=250, akte="privat")
    s2["frage"] = "versicherung_check"
    gehirn.einsammeln(sit2, "Nein.")
    assert s2["versicherungOk"] and s2["versicherungWechsel"]
    assert s2["versicherung"] == "gesetzlich"

    # "Nicht mehr privat" ohne Nein-Wort: ebenfalls Wechsel zu gesetzlich.
    sit3 = _sit()
    s3 = _bestand(sit3, tage_her=250, akte="privat")
    s3["frage"] = "versicherung_check"
    gehirn.einsammeln(sit3, "Ich bin nicht mehr privat versichert.")
    assert s3["versicherungOk"] and s3["versicherungWechsel"]
    assert s3["versicherung"] == "gesetzlich"


def test_wechsel_schreibt_kartei():
    sit = _sit()
    s = _bestand(sit, tage_her=250)
    s.update({"versicherung": "privat", "versicherungOk": True, "versicherungWechsel": True})
    aufrufe = []
    echt = flow.versicherung_aktualisieren
    flow.versicherung_aktualisieren = lambda tenant, pid, privat: (
        aufrufe.append((pid, privat)) or {"ok": True, "privateInsurance": privat, "previous": False}
    )
    try:
        text = flow._versicherung_ausfuehren(sit)
    finally:
        flow.versicherung_aktualisieren = echt
    assert aufrufe == [("p-1", True)]
    assert s["versicherungAkte"] == "privat"
    assert "aktualisiert" in text
    # Zweiter Lauf: schon umgetragen, kein weiterer Schreibversuch.
    assert flow._versicherung_ausfuehren(sit) == ""


def test_eskalation_versicherung_setzt_notiz():
    sit = _sit()
    s = _neu_komplett(sit)
    text = flow._eskalieren(sit, "versicherung")
    assert s["versicherungOk"] and s["versicherungNotiz"]
    assert text

    sit2 = _sit()
    s2 = _bestand(sit2, tage_her=250, akte="privat")
    flow._eskalieren(sit2, "versicherung_check")
    assert s2["versicherungOk"] and s2["versicherung"] == "privat"


def test_buchen_haengt_geschlecht_notiz_an():
    sit = _sit()
    s = _neu_komplett(sit)
    s.update({"geschlecht": "f", "geschlechtUnklar": True, "versicherung": "gesetzlich",
              "versicherungOk": True, "slotIso": "2026-09-07T09:00", "phase": "bestaetigen"})
    notizen = []
    echt_book = flow.kal.book_slot
    echt_note = flow.kal.note_appointment
    flow.kal.book_slot = lambda tenant, ctx, slot_iso: {
        "ok": True, "booked": True, "slotIso": slot_iso, "spoken": "Der Termin ist eingetragen.",
    }
    flow.kal.note_appointment = lambda tenant, ctx, sit_, note: notizen.append(note) or {"ok": True}
    try:
        res = flow._buchen(sit)
    finally:
        flow.kal.book_slot = echt_book
        flow.kal.note_appointment = echt_note
    assert res["book"]["booked"]
    assert notizen and "Geschlecht aktualisieren" in notizen[0]
