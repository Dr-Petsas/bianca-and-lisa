"""Weiterleitungs-Platzhalter (Kirri/Zaluma): Erkennung, Ablauf, Jingle-Event.

Laeuft ohne Netz: die Akten-Recherche (letzter_behandler) wird gestummt,
der Mandant kommt aus tenants/meddent.json (lokale Datei).
"""

from bianca import flow, gehirn, weiterleiten
from kern.tenants import laden


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


# --- (a) Erkennung ----------------------------------------------------------

def test_erkennung_verbinden_saetze():
    for satz in [
        "Verbinden Sie mich mit einem Mitarbeiter",
        "Kann ich mit einem Menschen sprechen?",
        "Stellen Sie mich durch",
        "Ich möchte jemanden vom Empfang",
        "Gibt es da kein Personal?",
        "Kann ich mit Doktor Petsas sprechen?",
        "Können Sie mich bitte weiterleiten?",
        "Ich will mit einem echten Menschen reden.",
        "Ich möchte mich direkt zu Doktor Petsas verbinden lassen.",
        "Kann ich mit der Buchhaltung sprechen?",
        "Verbinden Sie mich mit der Patientenannahme.",
    ]:
        assert weiterleiten.erkannt(satz), satz


# --- (e) Buchungssaetze loesen den Zweig NICHT aus ---------------------------

def test_buchungssaetze_loesen_nicht_aus():
    for satz in [
        "Ich hätte gern einen Termin",
        "Ich möchte meinen Termin verschieben.",
        "Ich war bei Doktor Patrikis",
        "Eine Kontrolle bitte.",
        "Wann ist mein Termin nochmal?",
        "Ich brauche einen Termin zur ZE Besprechung.",
    ]:
        assert not weiterleiten.erkannt(satz), satz
    # Voller Fluss: normale Buchung landet weiter in der 'schonmal'-Frage.
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        z = flow.zug(sit, "Ich hätte gern einen Termin")
        assert z and "schon" in z["text"].lower()
        assert not (sit.get("weiterleiten") or {})
    finally:
        flow.hintergrund.anstossen = echt_anstossen


# --- (b) Namentlich genannter Arzt: DIREKT verbinden, ohne Ansage ------------

def test_namentlich_genannt_verbindet_direkt_ohne_personalfrei():
    """'Kann ich bitte mit Doktor Patrikis sprechen?' (Chef 27.08., zweite
    Fassung): KEINE Personalfrei-Ansage, KEINE Rueckfrage — Ansage + Jingle
    + Platzhalter, fertig."""
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, "Kann ich bitte mit Doktor Patrikis sprechen?", events.append)
    assert z and "Kirri" in z["text"]  # Platzhalter = verbunden
    assert "personalfrei" not in z["text"] and "KI-geführt" not in z["text"]
    assert z.get("jingle") == weiterleiten.JINGLE_EVENT
    assert weiterleiten.JINGLE_EVENT in events
    # Gesprochene Ansage kommt VOR dem Jingle.
    sag = [e for e in events if e.startswith("sag:")]
    assert sag and "Verbindung" in sag[0] and "Doktor Patrikis" in sag[0]
    assert events.index(sag[0]) < events.index(weiterleiten.JINGLE_EVENT)
    assert not (sit.get("weiterleiten") or {})  # Anliegen bedient
    # Doppelte Fragen verboten: der Behandler zaehlt auch fuer die Buchung.
    s = gehirn.sammler(sit)
    assert (s["arzt"] or {}).get("calendarName") == "Dr. Patrikis"


def test_verbinden_lassen_mit_namen_verbindet_direkt():
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, "Ich möchte mich direkt zu Doktor Petsas verbinden lassen.", events.append)
    assert z and "Kirri" in z["text"]
    assert "personalfrei" not in z["text"]
    assert weiterleiten.JINGLE_EVENT in events
    s = gehirn.sammler(sit)
    assert (s["arzt"] or {}).get("calendarId") == "zex5bmv5jfIHWVW6zHbg"


# --- (b2) Mitarbeiter-/Abteilungs-Anfrage: Wahrheit + Arzt-Angebot ------------

def test_mitarbeiter_mit_bekanntem_arzt_wahrheit_und_angebot():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["arzt"] = {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg", "calendarName": "Dr. Petsas"}
    z = flow.zug(sit, "Verbinden Sie mich bitte mit einem Mitarbeiter.")
    assert z, "Weiterleitungs-Zweig muss deterministisch antworten"
    t = z["text"]
    assert "personalfrei" in t and "KI-geführt" in t
    assert "zu Doktor Petsas" in t and "weiterleiten" in t
    assert "bei wem" not in t.lower()  # NICHT nach dem Behandler fragen


def test_buchhaltung_bekommt_wahrheit_und_arztfrage():
    """Abteilungs-Wunsch (Buchhaltung/Rezeption/Patientenannahme) ohne
    bekannten Arzt: Wahrheit + Angebot, zu einem Arzt zu verbinden."""
    sit = _sit()
    z = flow.zug(sit, "Kann ich mit der Buchhaltung sprechen?")
    assert z and "personalfrei" in z["text"] and "KI-geführt" in z["text"]
    assert "Ärzte" in z["text"] and "durchstellen" in z["text"]
    # Arzt genannt -> direkt verbinden, keine weitere Rueckfrage.
    events: list[str] = []
    z2 = flow.zug(sit, "Dann zu Doktor Patrikis, bitte.", events.append)
    assert z2 and "Kirri" in z2["text"]
    assert weiterleiten.JINGLE_EVENT in events


def test_akte_liefert_letzten_behandler():
    """Kein Arzt im Gespraech, aber Patientenakte da: letzter_behandler
    liefert das Ziel — KEINE Rueckfrage (Chef: doppelte Fragen verboten)."""
    echt = weiterleiten.arztmod.letzter_behandler
    weiterleiten.arztmod.letzter_behandler = lambda t, pid: {
        "ok": True, "calendarId": "GVyoyXqCYof1QrGaNNnG",
        "calendarName": "Dr. Nikolaou", "doctorName": "Dr. Nikolaou", "war": True,
    }
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s["patientId"] = "pat-1"
        z = flow.zug(sit, "Gibt es da kein Personal?")
        assert z and "zu Doktor Nikolaou" in z["text"]
        assert "personalfrei" in z["text"]  # Mitarbeiter-Frage -> Wahrheit
        assert "bei wem" not in z["text"].lower()
    finally:
        weiterleiten.arztmod.letzter_behandler = echt


# --- (c) Verbinde-Wunsch ohne Namen und ohne Mitarbeiter-Wort ------------------

def test_weiterleiten_ohne_namen_fragt_nur_nach_arzt():
    """'Können Sie mich bitte weiterleiten?': kein Mitarbeiter-Wort ->
    KEINE Personalfrei-Ansage, nur die Arzt-Frage."""
    sit = _sit()
    z = flow.zug(sit, "Können Sie mich bitte weiterleiten?")
    assert z and "personalfrei" not in z["text"]
    assert "zu welchem unserer" in z["text"].lower() and "Ärzte" in z["text"]
    # Antwort mit Behandler-Namen (Fuzzy ueber arzt.deute) -> direkt verbinden.
    events: list[str] = []
    z2 = flow.zug(sit, "Bei Doktor Patrikis.", events.append)
    assert z2 and "Kirri" in z2["text"]
    assert weiterleiten.JINGLE_EVENT in events


def test_mensch_ohne_arzt_fragt_nach_arzt():
    sit = _sit()
    z = flow.zug(sit, "Kann ich mit einem Menschen sprechen?")
    assert z and "personalfrei" in z["text"]
    assert "Zu wem darf ich Sie durchstellen?" in z["text"]


# --- (d) Ja -> Jingle-Event + Kirri-Platzhalter-Ansage ------------------------

def test_ja_spielt_jingle_und_kirri_ansage():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["arzt"] = {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg", "calendarName": "Dr. Petsas"}
    events: list[str] = []
    z1 = flow.zug(sit, "Stellen Sie mich durch.", events.append)
    assert z1 and "weiterleiten" in z1["text"]
    # Kein Mitarbeiter-Wort im Satz -> keine Personalfrei-Ansage.
    assert "personalfrei" not in z1["text"]
    z2 = flow.zug(sit, "Ja, bitte.", events.append)
    assert z2 and "Kirri" in z2["text"] and "Zaluma" in z2["text"]
    assert "sonst noch etwas" in z2["text"].lower()  # Gespraech geht weiter
    assert weiterleiten.JINGLE_EVENT in events  # Jingle-Event erzeugt
    assert any(e.startswith("sag:") for e in events)  # Ansage vor dem Jingle
    assert z2.get("jingle") == weiterleiten.JINGLE_EVENT
    assert not (sit.get("weiterleiten") or {})  # Anliegen bedient


def test_nein_bricht_sauber_ab():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["arzt"] = {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg", "calendarName": "Dr. Petsas"}
    flow.zug(sit, "Ich möchte jemanden vom Empfang.")
    z = flow.zug(sit, "Nein, lassen Sie mal.")
    assert z and "sonst noch" in z["text"].lower()
    assert not (sit.get("weiterleiten") or {})


# --- Jingle-Infrastruktur ----------------------------------------------------

def test_jingle_datei_liegt_im_repo():
    from kern.config import BIANCA_WEB_DIR
    p = BIANCA_WEB_DIR / "verbinden.mp3"
    assert p.is_file() and p.stat().st_size > 10_000


def test_dienst_festes_audio():
    from kern.dienst import Dienst
    d = Dienst(name="test", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **k: {})
    blob = b"\xff\xfb\x90\x00daten"
    url = d.audio_fest_legen("verbinden", blob)
    assert url == "/api/audio/verbinden.mp3"
    assert d.audio_fest_url("verbinden") == url
    assert d.audio_holen("verbinden.mp3") == blob


def test_ansage_ueberlebt_sprech_filter():
    """Die Platzhalter-Ansage darf vom Sprech-Filter nicht zerlegt werden."""
    from kern import sprech
    raus = sprech.sanitize(weiterleiten.ANSAGE_PLATZHALTER)
    assert "Kirri" in raus and "Zaluma" in raus and "Petsas" in raus
    wahr = sprech.sanitize(weiterleiten.WAHRHEIT)
    assert "personalfrei" in wahr and "KI-geführt" in wahr
