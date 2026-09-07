"""W-DOSSIER: Fakten im Hintergrund, Talk nur in der Lücke, Spurwechsel auf Job."""

from datetime import datetime, timedelta

from bianca import gehirn
from kern import dossier
from kern.filler import kartei_satz
from kern.tenants import laden


def _vor(n: int) -> str:
    return (datetime.now().date() - timedelta(days=n)).isoformat()


def _sit(**extra) -> dict:
    sit = {
        "id": "dos1",
        "stimme": "Bianca",
        "tenant": laden("meddent"),
        "sammler": {
            "modus": "buchen", "phase": "", "frage": "",
            "bekannt": True, "anruferCheck": "ja",
            "grund": "Kontrolluntersuchung",
            "motivId": "kch-k", "motivName": "KCH Kontrolluntersuchung",
            "letzterBesuch": _vor(1100),
            "letzterGrund": "IMP OP Implantation",
        },
        "messages": [],
    }
    sit.update(extra)
    return sit


def test_fuellen_zieht_kartei_und_mas():
    sit = _sit()
    sit["sammler"]["letzterBesuch"] = ""
    sit["sammler"]["letzterGrund"] = ""
    sit["anruferKartei"] = {
        "letzterBesuch": _vor(1100),
        "letzterGrund": "IMP OP Implantation",
        "doctorName": "Dr. Petsas",
        "calendarId": "kal-p",
    }
    sit["gedaechtnis"] = "Praxisgedächtnis:\n- 01.09.: Rückruf erbeten. (noch offen)"
    d = dossier.fuellen(sit)
    assert d["bereit"] is True
    assert d["letzterGrund"] == "IMP OP Implantation"
    assert d["letzterArzt"] == "Dr. Petsas"
    assert d["masOffen"] and "Rückruf" in d["masOffen"][0]
    assert "verlauf" in d["takte"]


def test_luecke_nicht_bei_ziffern_oder_confirm():
    sit = _sit()
    sit["sammler"]["frage"] = "telefon_check"
    assert dossier.ist_luecke(sit, art="satz") is False
    assert dossier.satz(sit) == ""
    sit["sammler"]["frage"] = ""
    sit["sammler"]["phase"] = "bestaetigen"
    assert dossier.ist_luecke(sit, art="satz") is False
    assert dossier.naechster_takt(sit) == ""


def test_luecke_bei_hintergrund_und_buchung():
    sit = _sit()
    sit["hgLaeuft"] = {"vorrat": True}
    assert dossier.ist_luecke(sit, art="satz") is True
    text = dossier.satz(sit)
    assert text.startswith("Letztes Mal") and "?" not in text


def test_satz_nie_vor_identitaet():
    sit = _sit()
    sit["sammler"]["bekannt"] = False
    sit["sammler"]["anruferCheck"] = ""
    dossier.fuellen(sit)
    assert dossier.satz(sit) == ""


def test_verwerfen_anrufer_leert_besuch():
    sit = _sit()
    dossier.fuellen(sit)
    dossier.verwerfen_anrufer(sit)
    d = sit["dossier"]
    assert d["letzterGrund"] == "" and "verlauf" not in (d.get("takte") or [])


def test_spur_signal_nur_neues_implantat():
    assert dossier.spur_signal("Letztes Mal Implantat, alles gut.") == ""
    assert dossier.spur_signal("Das Implantat vor zwei Jahren war super.") == ""
    assert dossier.spur_signal("Ich brauche noch ein Implantat.") == "implantat"
    assert dossier.spur_signal(
        "Das Implantat vor zwei Jahren war super, ich brauche noch eins."
    ) == "implantat"


def test_spurwechsel_kontrolle_zu_implantat():
    import os
    sit = _sit()
    s = gehirn.sammler(sit)
    os.environ["MAS_GEDAECHTNIS"] = "0"
    try:
        neu = gehirn.einsammeln(
            sit,
            "Das Implantat vor zwei Jahren war super, ich brauche noch ein Implantat.",
        )
    finally:
        os.environ.pop("MAS_GEDAECHTNIS", None)
    assert "grund" in neu
    assert "Implantat" in s["grund"]
    assert s["grund"] != "Kontrolluntersuchung"
    assert sit["dossier"]["spur"].startswith("Implantat") or "implantat" in sit["dossier"]["spur"].lower()


def test_filler_nimmt_dossier_satz_wenn_kartei_leer():
    sit = _sit()
    dossier.fuellen(sit)
    assert not sit.get("karteiFillerText")
    text = kartei_satz(sit)
    assert "Letztes Mal" in text and "?" not in text


def test_markiere_zieht_takt_nur_einmal():
    sit = _sit()
    dossier.fuellen(sit)
    assert dossier.naechster_takt(sit) == "verlauf"
    dossier.markiere(sit, "verlauf")
    assert "verlauf" in sit["dossier"]["gesagt"]
    assert dossier.naechster_takt(sit) == "pzr"
