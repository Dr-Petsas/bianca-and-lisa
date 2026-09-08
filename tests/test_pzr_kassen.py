"""W-PZR-KASSEN (Chef 08.09.2026): jeder Termin bekommt die PZR-Frage;
Preis ungefähr 120 Euro, Zahnärzte machen die Reinigung selbst;
Zuschuss nur aus der Tabelle, immer mit Einzelfall-Warnung.
"""

from bianca import flow, gehirn
from kern import pzr_kassen, wissen
from kern.tenants import laden


def test_preis_satz_sagt_ungefaehr_nicht_grob():
    satz = pzr_kassen.preis_und_kasse_frage()
    assert "ungefähr" in satz
    assert "grob" not in satz.lower()
    assert "einhundertzwanzig" in satz
    assert "Zahnärzte" in satz
    assert "Prophylaxehelferinnen" in satz
    assert "Krankenkasse" in satz


def test_deute_tk_und_barmer():
    tk = pzr_kassen.deute("Ich bin bei der TK.")
    assert tk["id"] == "tk"
    text = pzr_kassen.auskunft(tk)
    assert "vierzig" in text and "Techniker" in text
    assert pzr_kassen.DISCLAIMER in text
    assert "grob" not in text.lower()
    barmer = pzr_kassen.deute("Barmer")
    b = pzr_kassen.auskunft(barmer)
    assert "Bonus" in b and "nicht automatisch" in b


def test_nackte_aok_wird_nicht_erraten():
    t = pzr_kassen.deute("AOK")
    assert t["id"] == "mehrdeutig"
    assert "fünfunddreißig" in t["satz"] or "sechzig" in t["satz"]
    assert pzr_kassen.deute("AOK Bayern")["id"] == "aok-bayern"


def test_privat_und_weiss_nicht():
    p = pzr_kassen.deute("Ich bin privat versichert.")
    assert p["id"] == "privat" and "Tarif" in p["satz"]
    u = pzr_kassen.deute("Weiß ich nicht.")
    assert u["id"] == "unbekannt"


def test_wissen_block_traegt_tabelle_ohne_grob():
    block = wissen.wissen_block(laden("meddent").get("wissen"))
    assert "Prophylaxehelferinnen" in block
    assert "ungefähr 120" in block or "ungefähr 120 Euro" in block
    assert "BARMER" in block and "Techniker" in block
    assert "grob" not in block.lower()


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


def test_preisfrage_bei_pzr_sagt_ungefaehr_und_fragt_kasse():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "pzr": "gefragt", "frage": "pzr",
        "grund": "Kontrolluntersuchung", "motivName": "KCH Kontrolluntersuchung",
    })
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        r = flow.zug(sit, "Ja, ich will eine Zahnreinigung, was kostet die?")
        assert r and "ungefähr" in r["text"]
        assert "grob" not in r["text"].lower()
        assert "einhundertzwanzig" in r["text"]
        assert "Zahnärzte" in r["text"] and "Prophylaxehelferinnen" in r["text"]
        assert "Krankenkasse" in r["text"]
        assert s["pzr"] == "ja"
        assert s["frage"] == "pzr_kasse"
    finally:
        flow.hintergrund.anstossen = echt


def test_kasse_tk_erklaert_und_warnt():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "pzr": "ja", "frage": "pzr_kasse",
        "pzrKasse": "gefragt", "grund": "professionelle Zahnreinigung",
        "motivName": "PRO professionelle Zahnreinigung",
        "arzt": {"typ": "egal"},
    })
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        r = flow.zug(sit, "Techniker Krankenkasse.")
        assert r and "Techniker" in r["text"]
        assert "vierzig" in r["text"]
        assert "Einzelfall" in r["text"]
        assert s["pzrKasse"] == "tk"
    finally:
        flow.hintergrund.anstossen = echt


def test_nach_ok_fragt_pzr_bevor_notiz():
    """Jeder Termin: PZR-Frage vor dem Eintragen, wenn sie noch fehlt."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "bestaetigen", "frage": "bestaetigung",
        "grund": "Kontrolluntersuchung", "motivName": "KCH Kontrolluntersuchung",
        "vorname": "Julia", "nachname": "Berger", "telefonOk": True,
        "telefon": "01776004600", "slotIso": "2026-09-10T09:00:00+02:00",
        "arzt": {"typ": "egal"},
    })
    sit["offered"] = [{"iso": s["slotIso"], "spoken": "Donnerstag um neun"}]
    r = flow.zug(sit, "Ja.")
    assert r and "Zahnreinigung" in r["text"]
    assert "Euro" not in r["text"]  # Preis nicht ins Haus fallen
    assert s["frage"] == "pzr" and s["pzr"] == "gefragt"


def test_pzr_im_kontext_nicht_bei_fuellung():
    s = {"modus": "buchen", "frage": "grund", "grund": "Füllung", "pzr": ""}
    assert gehirn.ist_pzr_preisfrage("Was kostet die Füllung?")
    assert not gehirn.pzr_im_kontext(s, "Was kostet die Füllung?")


def test_preisfrage_auf_arzt_notiz_sagt_die_ki():
    """Live Thaler Petsas 08.09.: Preis auf die Notiz-Frage — nie ‚Zahnarzt fragen‘."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "bestaetigen", "frage": "arzt_notiz",
        "arztNotizFrage": "gefragt",
        "grund": "professionelle Zahnreinigung",
        "motivName": "PRO Professionelle Zahnreinigung",
        "vorname": "Michael", "nachname": "Petsas",
        "telefonOk": True, "telefon": "01776004600",
        "slotIso": "2026-09-30T11:15:00+02:00",
        "arzt": {"typ": "genannt", "calendarId": "cal-pzr",
                 "calendarName": "Prophylaxe"},
    })
    sit["offered"] = [{"iso": s["slotIso"], "spoken": "Mittwoch um elf Uhr fünfzehn"}]
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        r = flow.zug(
            sit,
            "Ja, was kostet die Zahnreinigung? Bitte vorher mit mir abklärend.",
        )
    finally:
        flow.hintergrund.anstossen = echt
    text = (r or {}).get("text") or ""
    assert "einhundertzwanzig" in text
    assert "ungefähr" in text
    assert "Zahnärzte" in text and "Prophylaxehelferinnen" in text
    assert "Krankenkasse" in text
    assert "besprechen" not in text.lower()
    assert s["arztNotizFrage"] == "nein"
    assert s["frage"] == "pzr_kasse"
