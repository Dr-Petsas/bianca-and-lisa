"""Rueckblick auf den letzten Besuch + PZR-Mitbuchung + behandlerspezifisches
Motiv-Mapping (Chef 30.08.2026) — offline, ohne LLM und ohne Netz.

Bestandspatienten werden EINMAL pro Anruf auf den letzten Besuch angesprochen
(Verlaufs-Frage passend zur damaligen Behandlung); liegt der Besuch >6 Monate
zurueck und ist der neue Termin selbst keine Zahnreinigung, bietet Bianca die
PZR zum Mitbuchen an ("PLUS PZR heute" als Termin-Notiz). Der Besuchsgrund
wird in jedem Anruf frisch gegen den Katalog des ZIEL-Behandlers aufgeloest
(visitMotive.calendarIds).
"""

from datetime import datetime, timedelta

from bianca import besuchsgrund, flow, gehirn
from kern import motive
from kern.tenants import laden

# Kunst-Katalog im Format von masVisitMotives: kalendergebundene Motive
# (calendarIds), ueberall gueltige (leere Liste) und interne (nicht online
# buchbare) Termine wie Video-Kontrollen.
KATALOG = [
    {"id": "imp-b",  "name": "IMP Besprechung",          "calendarIds": ["kal-a"], "allowOnlineBooking": True,  "duration": 30},
    {"id": "imp-op", "name": "IMP OP klein",             "calendarIds": ["kal-a"], "allowOnlineBooking": False, "duration": 120},
    {"id": "kch-k",  "name": "KCH Kontrolluntersuchung", "calendarIds": [],        "allowOnlineBooking": True,  "duration": 15},
    {"id": "vid-k",  "name": "VID OP Kontrolle",         "calendarIds": [],        "allowOnlineBooking": False, "duration": 15},
    {"id": "pzr-60", "name": "PZR 60 Min.",              "calendarIds": ["kal-b"], "allowOnlineBooking": True,  "duration": 60},
    {"id": "endo-k", "name": "KCH Endo klein",           "calendarIds": ["kal-a"], "allowOnlineBooking": True,  "duration": 45},
    {"id": "endo-g", "name": "KCH Endo",                 "calendarIds": ["kal-a"], "allowOnlineBooking": True,  "duration": 60},
]


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


def _vor_tagen(n: int) -> str:
    return (datetime.now().date() - timedelta(days=n)).isoformat()


def _bestand(sit: dict, besuch_vor_tagen: int, letzter_grund: str) -> dict:
    """Sammler eines identifizierten Bestandspatienten mit Historie."""
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": True, "bekannt": True,
        "patientId": "p-1", "vorname": "Peter", "nachname": "Berger",
        "grund": "Kontrolluntersuchung", "grundWortlaut": "einmal alles kontrollieren",
        "motivId": "kch-k", "motivName": "KCH Kontrolluntersuchung",
        "letzterBesuch": _vor_tagen(besuch_vor_tagen), "letzterGrund": letzter_grund,
    })
    return s


# --- Behandlerspezifisches Motiv-Mapping ------------------------------------

def test_motive_kalenderfilter():
    assert motive.erlaubt(KATALOG[0], "kal-a") and not motive.erlaubt(KATALOG[0], "kal-b")
    assert motive.erlaubt(KATALOG[2], "kal-b")  # leere calendarIds = ueberall
    namen = [v["id"] for v in motive.fuer_kalender(KATALOG, "kal-b")]
    assert "pzr-60" in namen and "kch-k" in namen and "imp-b" not in namen


def test_motiv_suchen_nur_im_zielkalender():
    tenant = laden("meddent")
    muster = besuchsgrund.konzept_muster("Ich haette gern einen Termin wegen einem Implantat")
    assert muster
    vm_a = besuchsgrund.motiv_suchen(tenant, muster, katalog=KATALOG, calendar_id="kal-a")
    assert vm_a and vm_a["id"] == "imp-b"  # Besprechung, nie die 120-Minuten-OP
    # Der andere Behandler fuehrt kein Implantat-Motiv: Muster laufen leer.
    assert besuchsgrund.motiv_suchen(tenant, muster, katalog=KATALOG, calendar_id="kal-b") is None


def test_motiv_suchen_online_buchbare_zuerst():
    # "VID OP Kontrolle" (nicht online buchbar) hat den kuerzeren Namen und
    # wuerde ohne die Buchbar-Regel gewinnen — interne Termine gehoeren aber
    # nicht ans Telefon.
    vm = besuchsgrund.motiv_suchen(laden("meddent"), [r"kontroll"], katalog=KATALOG)
    assert vm and vm["id"] == "kch-k"


def test_motiv_suchen_klein_regel():
    vm = besuchsgrund.motiv_suchen(laden("meddent"), [r"endo"], katalog=KATALOG, calendar_id="kal-a")
    assert vm and vm["id"] == "endo-k"  # "klein" schlaegt den kuerzeren Namen


def test_motiv_fuer_kalender_wechsel_loest_neu_auf():
    sit = _sit()
    sit["motivKatalog"] = KATALOG
    s = gehirn.sammler(sit)
    s.update({"grund": "Implantat-Beratung", "grundWortlaut": "wegen einem Implantat",
              "motivId": "imp-b", "motivName": "IMP Besprechung"})
    vm = gehirn.motiv_fuer_kalender(sit, "kal-a")
    assert vm and vm["id"] == "imp-b"
    # Behandlerwechsel: kal-b fuehrt kein Implantat-Motiv, das bereits
    # gewaehlte gilt dort nicht -> Zweifelsfall Kontrolle (ueberall gueltig).
    vm_b = gehirn.motiv_fuer_kalender(sit, "kal-b")
    assert vm_b and vm_b["id"] == "kch-k"


# --- Rueckblick: Bausteine ---------------------------------------------------

def test_abstand_worte():
    assert gehirn.abstand_worte(800) == "über zwei Jahre"
    assert gehirn.abstand_worte(1200) == "über drei Jahre"
    assert gehirn.abstand_worte(600) == "über anderthalb Jahre"
    assert gehirn.abstand_worte(400) == "über ein Jahr"
    assert gehirn.abstand_worte(200) == "etwa sieben Monate"
    assert gehirn.abstand_worte(30) == "ein paar Wochen"


def test_grund_sprechbar():
    assert gehirn.grund_sprechbar("KCH akute Beschwerden/Notfall") == "akute Beschwerden"
    assert gehirn.grund_sprechbar("PAR 1 Besprechung") == "Besprechung"
    assert gehirn.grund_sprechbar("Zahnreinigung") == "Zahnreinigung"


def test_verlaufs_frage_kategorien():
    assert "verlaufen" in gehirn.verlaufs_frage("PAR 1 Besprechung")
    assert "verlaufen" in gehirn.verlaufs_frage("KCH Kontrolluntersuchung")
    assert "Schlaflabor" in gehirn.verlaufs_frage("Narval Eingliederung")
    assert "zufrieden" in gehirn.verlaufs_frage("ZE Eingliederung Teleskoparbeit")
    assert "verheilt" in gehirn.verlaufs_frage("IMP OP Implantation")
    assert "verheilt" in gehirn.verlaufs_frage("OS Weisheitszahnentfernung")
    assert "ruhig" in gehirn.verlaufs_frage("KCH Endo klein")


def test_rueckblick_faellig_grenzen():
    sit = _sit()
    s = _bestand(sit, 900, "IMP OP Implantation")
    assert gehirn.rueckblick_faellig(s)
    s["rueckblick"] = "fertig"
    assert not gehirn.rueckblick_faellig(s)
    s["rueckblick"] = ""
    s["bekannt"] = False
    assert not gehirn.rueckblick_faellig(s)
    s["bekannt"] = True
    s["phase"] = "angebot"
    assert not gehirn.rueckblick_faellig(s)
    s["phase"] = ""
    s["grundWortlaut"] = "starke Schmerzen"  # Schmerzpatienten plaudert man nicht voll
    assert not gehirn.rueckblick_faellig(s)
    s["grundWortlaut"] = "einmal alles kontrollieren"
    s["letzterBesuch"] = _vor_tagen(3)  # gerade erst da gewesen
    assert not gehirn.rueckblick_faellig(s)
    s["letzterBesuch"] = _vor_tagen(900)
    s["letzterGrund"] = ""
    assert not gehirn.rueckblick_faellig(s)


def test_rueckblick_text_formen():
    sit = _sit()
    s = _bestand(sit, 900, "IMP OP Implantation")
    text = gehirn.rueckblick_text(s)
    assert "schon über zwei Jahre her" in text
    assert "OP Implantation" in text
    assert "verheilt" in text
    s["letzterBesuch"] = _vor_tagen(200)
    text2 = gehirn.rueckblick_text(s)
    assert "ist etwa sieben Monate her" in text2  # kein falscher Dativ ("vor ... Monate")


# --- PZR: Bausteine ----------------------------------------------------------

def test_pzr_faellig_grenzen():
    sit = _sit()
    s = _bestand(sit, 900, "IMP OP Implantation")
    assert gehirn.pzr_faellig(s)
    s["pzr"] = "nein"
    assert not gehirn.pzr_faellig(s)
    s["pzr"] = ""
    s["motivName"] = "PZR 60 Min."  # der neue Termin IST schon die Reinigung
    assert not gehirn.pzr_faellig(s)
    s["motivName"] = "KCH Kontrolluntersuchung"
    s["grund"] = "akute Beschwerden/Notfall"
    assert not gehirn.pzr_faellig(s)
    s["grund"] = "Kontrolluntersuchung"
    s["letzterBesuch"] = _vor_tagen(60)  # erst zwei Monate her
    assert not gehirn.pzr_faellig(s)


def test_pzr_ernte_ja_nein_und_spontan():
    sit = _sit()
    s = _bestand(sit, 900, "IMP OP Implantation")
    s.update({"pzr": "gefragt", "frage": "pzr"})
    gehirn.einsammeln(sit, "Ja, gerne.")
    assert s["pzr"] == "ja"

    sit2 = _sit()
    s2 = _bestand(sit2, 900, "IMP OP Implantation")
    s2.update({"pzr": "gefragt", "frage": "pzr"})
    gehirn.einsammeln(sit2, "Nein, ohne Zahnreinigung bitte.")
    assert s2["pzr"] == "nein"

    # Spontaner Wunsch ohne jede Frage — und der Hauptgrund bleibt stehen.
    sit3 = _sit()
    s3 = _bestand(sit3, 900, "IMP OP Implantation")
    gehirn.einsammeln(sit3, "Machen Sie doch gleich noch eine Zahnreinigung mit dazu.")
    assert s3["pzr"] == "ja" and s3["grund"] == "Kontrolluntersuchung"

    # Ist der Termin selbst die Reinigung, gibt es keine Mitbuch-Ernte.
    sit4 = _sit()
    s4 = _bestand(sit4, 900, "IMP OP Implantation")
    s4.update({"grund": "professionelle Zahnreinigung", "motivName": "PZR 60 Min."})
    gehirn.einsammeln(sit4, "Die Zahnreinigung dazu bitte.")
    assert s4["pzr"] == ""


# --- Gespraechsfluss (flow.zug) ----------------------------------------------

def test_zug_rueckblick_dann_pzr_dann_zwischenfrage():
    sit = _sit()
    _bestand(sit, 900, "IMP OP Implantation")
    s = gehirn.sammler(sit)
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        # Ernte-Zug (Wunsch) -> statt der naechsten Pflichtfrage kommt der
        # Rueckblick auf den letzten Besuch.
        r = flow.zug(sit, "Am liebsten Dienstag vormittag.")
        assert r and "letzter Besuch" in r["text"] and "verheilt" in r["text"]
        assert s["frage"] == "rueckblick" and s["rueckblick"] == "gefragt"

        # Klar positive Kurzantwort -> Mini-Empathie + direkt die PZR-Frage.
        r2 = flow.zug(sit, "Ja, alles bestens verheilt!")
        assert r2 and r2["text"].startswith("Das freut mich")
        assert "Zahnreinigung" in r2["text"]
        assert s["frage"] == "pzr" and s["pzr"] == "gefragt" and s["rueckblick"] == "fertig"

        # Zwischenfrage auf die PZR-Frage: LLM antwortet (None), Frage bleibt offen.
        r3 = flow.zug(sit, "Was kostet denn so eine Zahnreinigung?")
        assert r3 is None and s["frage"] == "pzr"

        # Das Ja danach zaehlt — Quittung + naechste Pflichtfrage.
        r4 = flow.zug(sit, "Ja, machen Sie das gerne.")
        assert r4 and "nehme ich mit auf" in r4["text"]
        assert s["pzr"] == "ja"
    finally:
        flow.hintergrund.anstossen = echt_anstossen


def test_zug_rueckblick_erzaehlung_geht_ans_llm():
    sit = _sit()
    _bestand(sit, 900, "ZE Eingliederung")
    s = gehirn.sammler(sit)
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        r = flow.zug(sit, "Am liebsten Dienstag vormittag.")
        assert r and "zufrieden" in r["text"] and s["frage"] == "rueckblick"
        # Negative/erzaehlende Antwort: kein deterministischer Trost — das LLM
        # uebernimmt (Talk-Schicht), der Rueckblick gilt als besprochen.
        r2 = flow.zug(sit, "Es war leider ziemlich kompliziert damals.")
        assert r2 is None and s["rueckblick"] == "fertig" and s["frage"] == ""
    finally:
        flow.hintergrund.anstossen = echt_anstossen


def test_zug_kein_rueckblick_bei_schmerz():
    sit = _sit()
    s = _bestand(sit, 900, "IMP OP Implantation")
    s.update({"grund": "akute Beschwerden/Notfall", "grundWortlaut": "starke Zahnschmerzen"})
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        r = flow.zug(sit, "Am liebsten Dienstag vormittag.")
        # Kein Plauder-Einschub — die Maschine stellt die naechste Pflichtfrage.
        assert r is None or "letzter Besuch" not in (r.get("text") or "")
        assert s["rueckblick"] == "" and s["pzr"] == ""
    finally:
        flow.hintergrund.anstossen = echt_anstossen


def test_buchen_traegt_plus_pzr_notiz():
    sit = _sit()
    s = _bestand(sit, 900, "IMP OP Implantation")
    s.update({"pzr": "ja", "slotIso": "2026-09-07T09:00", "arzt": {"typ": "egal"}})
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    notes: list[str] = []
    flow.kal.book_slot = lambda tenant, ctx, slot_iso="": {
        "ok": True, "booked": True, "slotIso": slot_iso, "spoken": "Der Termin ist eingetragen.",
    }
    flow.kal.note_appointment = lambda tenant, ctx, sit2, note="": notes.append(note)
    try:
        r = flow._buchen(sit)
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note
    assert any("PLUS PZR heute" in n for n in notes)  # exakter Chef-Wortlaut
    assert "Zahnreinigung habe ich mit dazu vermerkt" in r["text"]
