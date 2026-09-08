"""Fachtemplate-/Praxis-/Patient-Layer: generisch und verhaltenskompatibel."""

from datetime import datetime, timedelta

from bianca import session as bianca_session
from kern import dossier, empfehlungen, fachprofil
from kern.sitzung import oeffentlich
from kern.tenants import laden
from lisa import session as lisa_session


KAT_DERMA = [
    {"id": "haut", "name": "Hautkrebsscreening"},
    {"id": "akne", "name": "Akne-Sprechstunde"},
]
KAT_GYN = [
    {"id": "vors", "name": "Gynäkologische Vorsorge"},
    {"id": "spir", "name": "Spiralenkontrolle"},
]
KAT_ORTHO = [
    {"id": "knie", "name": "Orthopädische Kniesprechstunde"},
    {"id": "rueck", "name": "Rückenbeschwerden"},
]


def _alt(n: int = 200) -> str:
    return (datetime.now().date() - timedelta(days=n)).isoformat()


def _sit(tenant: dict, **sammler) -> dict:
    s = {
        "modus": "buchen",
        "phase": "",
        "frage": "",
        "bekannt": True,
        "anruferCheck": "ja",
        "patientId": "pat-1",
        "telefonOk": True,
        "nachname": "Keller",
        "grund": "Kontrolluntersuchung",
        "motivName": "Kontrolluntersuchung",
        "letzterBesuch": _alt(),
        "letzterGrund": "Kontrolluntersuchung",
    }
    s.update(sammler)
    return {"tenant": tenant, "sammler": s, "messages": []}


def test_fachtemplate_kommt_aus_katalog_nicht_clientid():
    med = laden("meddent")
    med["clientId"] = "beliebige-neue-praxis"
    assert fachprofil.fach_id({"tenant": med}) == "zahnmedizin"
    assert fachprofil.fach_id({"tenant": {"visitMotives": KAT_DERMA}}) == "dermatologie"
    assert fachprofil.fach_id({"tenant": {"visitMotives": KAT_GYN}}) == "gynaekologie"
    assert fachprofil.fach_id({"tenant": {"visitMotives": KAT_ORTHO}}) == "orthopaedie"
    assert fachprofil.fach_id({"tenant": {"visitMotives": []}}) == "allgemein"


def test_explizites_fachgebiet_gewinnt_vor_katalog():
    sit = {
        "tenant": {
            "fachgebiet": "Orthopädie",
            "visitMotives": laden("meddent").get("visitMotives") or [],
        },
    }
    assert fachprofil.fach_id(sit) == "orthopaedie"


def test_jedes_template_erbt_kern_sicherheit():
    for kat in ([], KAT_DERMA, KAT_GYN, KAT_ORTHO):
        t = fachprofil.template({"tenant": {"visitMotives": kat}})
        assert "werkzeuge_verifizieren" in t["faehigkeiten"]
        assert "frist_erstton" in t["faehigkeiten"]
        assert any("Werkzeug" in s for s in t["schutz"])


def test_praxis_layer_ist_individuell_ohne_promptinhalt():
    layer = fachprofil.praxis_layer({
        "_quelle": "cf",
        "clientId": "c1",
        "locationId": "l1",
        "praxisName": "Praxis Beispiel",
        "calendars": [{"id": "k1", "name": "Dr. Beispiel"}],
        "visitMotives": KAT_ORTHO,
        "dbPrompt": "Interne Praxisregel mit vertraulichem Text",
    })
    assert layer["clientId"] == "c1" and layer["kalender"] == 1
    assert layer["besuchsgruende"] == 2 and layer["hatDbPrompt"] is True
    assert "Interne Praxisregel" not in str(layer)


def test_patient_layer_gibt_vor_bestaetigung_keine_fakten_frei():
    sit = {
        "anrufer": {"name": "Julia Keller"},
        "sammler": {"letzterBesuch": _alt(), "letzterGrund": "Kontrolle"},
        "gedaechtnis": "Offener Rückruf",
        "gedaechtnisOffen": ["v1"],
    }
    p = fachprofil.patient_layer(sit)
    assert p["identitaet"] == "erkannt_unbestaetigt"
    assert p["hatLetztenBesuch"] is False
    assert p["hatPraxisgedaechtnis"] is False
    assert p["offeneVorgaenge"] == 0


def test_dossier_baut_strukturierte_empfehlungen_bei_gleichen_legacy_takten():
    sit = _sit(laden("meddent"))
    d = dossier.fuellen(sit)
    ids = [x["id"] for x in d["empfehlungen"]]
    assert d["fachtemplate"] == "zahnmedizin"
    assert ids[:2] == ["verlauf", "pzr"]
    assert d["takte"][:2] == ["verlauf", "pzr"]
    assert d["layers"]["reihenfolge"] == ["kern", "fach", "praxis", "patient", "llm"]


def test_fachfremde_praxis_bekommt_keine_dental_empfehlung():
    tenant = {"praxisName": "Hautarztpraxis", "visitMotives": KAT_DERMA}
    sit = _sit(tenant)
    ids = [x["id"] for x in empfehlungen.kandidaten(sit, {
        "letzterBesuch": _alt(),
        "letzterGrund": "Hautkrebsscreening",
        "gesagt": [],
    })]
    assert ids == ["verlauf"]
    assert "pzr" not in ids


def test_mas_vorgang_ist_kontext_keine_spontane_sprachantwort():
    sit = _sit(laden("meddent"))
    sit["gedaechtnisOffen"] = ["vorgang-1"]
    treffer = empfehlungen.kandidaten(sit, {"gesagt": []})
    offen = next(x for x in treffer if x["id"] == "offener_vorgang")
    assert offen["quelle"] == "mas"
    assert offen["legacyTakt"] == ""


def test_beide_stimmen_legen_layer_fuer_neue_sitzungen_an():
    b = bianca_session.neu(tenant_id="meddent")
    l = lisa_session.neu(tenant_id="meddent", auftrag="Rückruf.")
    assert b["layers"]["fach"]["id"] == "zahnmedizin"
    assert l["layers"]["fach"]["id"] == "zahnmedizin"
    assert oeffentlich(b)["fachtemplate"] == "zahnmedizin"
    assert oeffentlich(l)["layerVersion"] == fachprofil.VERSION
