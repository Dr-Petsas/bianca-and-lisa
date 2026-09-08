"""Katalog-Wache: Zahnmedizin nur, wenn der Motivkatalog sie fuehrt.

Blessing (Hautarzt) und leerer Katalog: keine PZR-Frage, keine 120-Euro-
Saetze, kein Zahnarzt-Prompt, keine Dental-Konzepte. MedDent unveraendert.
Nie an eine clientId gebunden — die naechste Derma-Praxis ist automatisch dicht.
"""

from bianca import besuchsgrund, flow, gehirn
from bianca.agent import system_prompt_aktuell
from kern import dossier, motive, wissen
from kern.tenants import laden


KAT_BLESSING = [
    {"id": "haut", "name": "Hautkrebsscreening", "nameForPatient": "Hautkrebs-Vorsorge",
     "duration": 20, "calendarIds": [], "allowOnlineBooking": True},
    {"id": "botox", "name": "Botox-Behandlung", "nameForPatient": "Botox",
     "duration": 30, "calendarIds": [], "allowOnlineBooking": True},
    {"id": "kontr", "name": "Nachkontrolle", "nameForPatient": "",
     "duration": 15, "calendarIds": [], "allowOnlineBooking": True},
]

# Hautkrebs-Prophylaxe darf NICHT als Zahnzaehnen — nacktes „Prophylaxe“
# ist in der Dermatologie ueblich.
KAT_PROPHYLAXE = [
    {"id": "hp", "name": "Hautkrebs-Prophylaxe", "nameForPatient": "Prophylaxe",
     "duration": 20, "calendarIds": [], "allowOnlineBooking": True},
]


def _blessing_sit() -> dict:
    return {
        "tenant": {
            "praxisName": "Hautarztpraxis Doktor Blessing",
            "visitMotives": list(KAT_BLESSING),
            "calendars": [{"id": "cal-b", "name": "Dr. Blessing"}],
            "wissen": {},
        },
        "motivKatalog": list(KAT_BLESSING),
        "messages": [{"role": "system", "content": "x"}],
    }


def _meddent_sit() -> dict:
    t = laden("meddent")
    return {
        "tenant": t,
        "motivKatalog": list(t.get("visitMotives") or []),
        "messages": [{"role": "system", "content": "x"}],
    }


def _bestand(sit: dict) -> dict:
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": True, "bekannt": True,
        "vorname": "Anna", "nachname": "Keller",
        "grund": "Kontrolluntersuchung",
        "grundWortlaut": "einmal zur Kontrolle",
        "motivId": "kontr", "motivName": "Nachkontrolle",
    })
    return s


# --- Katalog-Erkennung -------------------------------------------------------

def test_meddent_ist_zahn_und_fuehrt_pzr():
    sit = _meddent_sit()
    assert motive.ist_zahn(sit)
    assert motive.fuehrt_pzr(sit)


def test_blessing_ist_kein_zahn_und_fuehrt_keine_pzr():
    sit = _blessing_sit()
    assert not motive.ist_zahn(sit)
    assert not motive.fuehrt_pzr(sit)


def test_leerer_katalog_fail_closed():
    assert not motive.ist_zahn([])
    assert not motive.fuehrt_pzr([])
    sit = {"tenant": {"visitMotives": []}, "motivKatalog": []}
    assert not motive.ist_zahn(sit)
    assert not motive.fuehrt_pzr(sit)


def test_hautkrebs_prophylaxe_ist_kein_zahn():
    assert not motive.ist_zahn(KAT_PROPHYLAXE)
    assert not motive.fuehrt_pzr(KAT_PROPHYLAXE)


# --- PZR-Angebot / Ernte / Preis --------------------------------------------

def test_blessing_keine_pzr_frage():
    sit = _blessing_sit()
    s = _bestand(sit)
    assert not gehirn.pzr_faellig(s, sit)
    assert not gehirn.pzr_noch_fragen(s, sit)


def test_meddent_pzr_frage_bleibt():
    sit = _meddent_sit()
    s = _bestand(sit)
    s["motivName"] = "KCH Kontrolluntersuchung"
    assert gehirn.pzr_faellig(s, sit)
    assert gehirn.pzr_noch_fragen(s, sit)


def test_blessing_nach_ok_fragt_keine_pzr():
    sit = _blessing_sit()
    s = _bestand(sit)
    s.update({
        "phase": "bestaetigen", "frage": "bestaetigung",
        "telefonOk": True, "telefon": "01776004600",
        "slotIso": "2026-09-10T09:00:00+02:00",
        "arzt": {"typ": "egal"},
        "arztNotizFrage": "nein",
    })
    sit["offered"] = [{"iso": s["slotIso"], "spoken": "Donnerstag um neun"}]
    r = flow.zug(sit, "Ja.")
    text = (r or {}).get("text") or ""
    assert "Zahnreinigung" not in text
    assert s.get("pzr") in {"", None}
    assert s.get("frage") != "pzr"


def test_blessing_erntet_keine_pzr_dazu():
    sit = _blessing_sit()
    s = _bestand(sit)
    gehirn.einsammeln(sit, "Machen Sie doch gleich noch eine Zahnreinigung mit dazu.")
    assert s["pzr"] == ""


def test_meddent_erntet_pzr_dazu_weiter():
    sit = _meddent_sit()
    s = _bestand(sit)
    s["motivName"] = "KCH Kontrolluntersuchung"
    gehirn.einsammeln(sit, "Machen Sie doch gleich noch eine Zahnreinigung mit dazu.")
    assert s["pzr"] == "ja"


def test_blessing_kein_pzr_preis():
    sit = _blessing_sit()
    s = _bestand(sit)
    s["frage"] = "grund"
    assert gehirn.ist_pzr_preisfrage("Was kostet die Zahnreinigung?")
    assert not gehirn.pzr_im_kontext(s, "Was kostet die Zahnreinigung?", sit)


def test_blessing_preiszug_spricht_keine_120_euro():
    sit = _blessing_sit()
    s = _bestand(sit)
    s["frage"] = "grund"
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        r = flow.zug(sit, "Was kostet die Zahnreinigung?")
    finally:
        flow.hintergrund.anstossen = echt
    text = ((r or {}).get("text") or "").lower()
    assert "einhundertzwanzig" not in text
    assert "prophylaxehelferinnen" not in text
    assert "zahnärzte" not in text and "zahnaerzte" not in text


# --- Mapping / Prompt / Dossier ---------------------------------------------

def test_blessing_deute_zahnreinigung_kein_dental_kern():
    tenant = {"visitMotives": KAT_BLESSING}
    kern, vm = besuchsgrund.deute(tenant, "Ich brauche eine Zahnreinigung.",
                                  katalog=KAT_BLESSING)
    assert kern != "professionelle Zahnreinigung"
    if vm:
        assert "zahn" not in (vm.get("name") or "").lower()


def test_blessing_deute_hautkrebs_bleibt():
    tenant = {"visitMotives": KAT_BLESSING}
    kern, vm = besuchsgrund.deute(tenant, "Ich brauche ein Hautkrebsscreening.",
                                  katalog=KAT_BLESSING)
    assert vm and vm["id"] == "haut"


def test_wissen_block_blessing_ohne_zahnarzt():
    sit = _blessing_sit()
    block = wissen.wissen_block({}, sit=sit)
    assert "ZAHNMEDIZIN" not in block
    assert "Zahnarzt" not in block
    assert "Zahnreinigung" not in block or "bietest du NICHT" in block
    assert "einhundertzwanzig" not in block
    assert wissen.VERWEIS_PRAXIS in block
    assert wissen.VERWEIS_SATZ not in block


def test_prompt_blessing_ohne_zahnmedizin():
    sit = _blessing_sit()
    p = system_prompt_aktuell(sit)
    assert "ZAHNMEDIZIN UND PREISE" not in p
    assert "mit Ihrem Zahnarzt" not in p
    assert "Prophylaxehelferinnen" not in p
    from lisa.prompt import system_prompt as lisa_prompt
    lp = lisa_prompt(praxis="Hautarztpraxis Doktor Blessing", behandler="",
                     auftrag="Rückruf.", patient="Frau Keller", sit=sit)
    assert "Zahnarztpraxis" not in lp


def test_dossier_blessing_kein_pzr_takt():
    sit = _blessing_sit()
    s = _bestand(sit)
    s["bekannt"] = True
    sit["sammler"] = s
    dossier.fuellen(sit)
    assert "pzr" not in (sit.get("dossier") or {}).get("takte", [])
    assert dossier.naechster_takt(sit) != "pzr"


def test_sprech_beispiele_kommen_aus_dem_katalog():
    sit = _blessing_sit()
    bsp = motive.sprech_beispiele(sit, n=2)
    assert not any("krebs" in x.lower() for x in bsp)
    assert not any("zahn" in x.lower() for x in bsp)
    assert any("kontroll" in x.lower() or "botox" in x.lower() for x in bsp)
    med = motive.sprech_beispiele(_meddent_sit(), n=8)
    assert any("zahnreinigung" in x.lower() or "kontroll" in x.lower()
               or "besprechung" in x.lower() for x in med)


def test_behandlung_frage_blessing_ohne_zahnreinigung():
    from bianca import verwalten
    sit = _blessing_sit()
    treffer = [
        {"motivName": "Hautkrebsscreening"},
        {"motivName": "Botox-Behandlung"},
    ]
    r = verwalten._behandlung_frage(sit, treffer)
    text = (r or {}).get("text") or ""
    assert "Zahnreinigung" not in text
    assert "Krebs" not in text
    assert "Kontrolle" in text
    assert "Botox" in text


def test_kartei_fueller_hautkrebs_prophylaxe_nicht_zahnreinigung():
    sit = _blessing_sit()
    s = _bestand(sit)
    s.update({
        "bekannt": True, "letzterGrund": "Hautkrebs-Prophylaxe",
        "letzterBesuch": "2026-01-01",
    })
    satz = gehirn.kartei_fueller_satz(s, sit)
    assert "Zahnreinigung" not in satz
    assert "Krebs" not in satz
    sit["sammler"] = s
    sit["hgLaeuft"] = {"vorrat": True}
    dossier.fuellen(sit)
    text = dossier.satz(sit)
    assert "Zahnreinigung" not in (text or "")
    assert "Krebs" not in (text or "")


def test_blessing_rueckblick_fragt_noch_darum_ohne_krebs():
    sit = _blessing_sit()
    s = _bestand(sit)
    s.update({
        "bekannt": True, "letzterGrund": "Hautkrebsscreening",
        "letzterBesuch": "2026-01-01", "rueckblick": "",
    })
    text = gehirn.rueckblick_text(s, sit)
    assert "Krebs" not in text
    assert "Letztes Mal" in text
    assert "immer noch" in text
    assert "Kontrolle" in text
    ein = flow._einschub(sit)
    assert ein and "Krebs" not in ein["text"]
    assert s["frage"] == "rueckblick"


def test_blessing_ja_auf_rueckblick_fragt_kontrolle():
    sit = _blessing_sit()
    s = _bestand(sit)
    s.update({
        "bekannt": True, "letzterGrund": "Hautkrebsscreening",
        "letzterBesuch": "2026-01-01",
        "rueckblick": "gefragt", "frage": "rueckblick",
        "wunsch": {},
    })
    r = flow.zug(sit, "Ja.")
    text = (r or {}).get("text") or ""
    assert "Krebs" not in text
    assert "Kontrolle" in text
    assert s["frage"] == "folge_kontrolle"
    assert s["grund"] == "Kontrolle"
    r2 = flow.zug(sit, "Ja.")
    assert s["folgeKontroll"] == "ja"
    assert "Krebs" not in ((r2 or {}).get("text") or "")


def test_blessing_nein_auf_rueckblick_fragt_diesmal():
    sit = _blessing_sit()
    s = _bestand(sit)
    s.update({
        "bekannt": True, "letzterGrund": "Botox-Behandlung",
        "letzterBesuch": "2026-01-01",
        "rueckblick": "gefragt", "frage": "rueckblick",
    })
    r = flow.zug(sit, "Nein.")
    assert "diesmal" in ((r or {}).get("text") or "").lower()
    assert s["folge"] == "nein"
    assert s["frage"] == "grund"


def test_blessing_nach_ok_fragt_notiz_nicht_pzr():
    sit = _blessing_sit()
    s = _bestand(sit)
    s.update({
        "phase": "bestaetigen", "frage": "bestaetigung",
        "telefonOk": True, "telefon": "01776004600",
        "slotIso": "2026-09-10T09:00:00+02:00",
        "arzt": {"typ": "egal"},
    })
    sit["offered"] = [{"iso": s["slotIso"], "spoken": "Donnerstag um neun"}]
    r = flow.zug(sit, "Ja.")
    text = (r or {}).get("text") or ""
    assert "Zahnreinigung" not in text
    assert "Notiz" in text
    assert s["frage"] == "arzt_notiz"


def test_meddent_rueckblick_bleibt_zahn():
    sit = _meddent_sit()
    s = _bestand(sit)
    s.update({
        "bekannt": True, "letzterGrund": "KCH Füllung klein",
        "letzterBesuch": "2026-01-01",
    })
    text = gehirn.rueckblick_text(s, sit)
    assert "immer noch um" not in text
    assert "verlaufen" in text or "verheilt" in text or "zufrieden" in text
