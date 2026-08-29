"""Offline-Tests fuer Story-Bauer + Runner-Logik des Baukasten-Tests.

Kein Netz, kein Audio: geprueft wird die pure Drehbuch-Logik —
Story-Bau, Frage->Baustein-Mapping (deckt ALLE Maschinen-Fragen),
Slot-Verhandlung, Abschweifer-Einmaligkeit, Halbsatz-Paare und die
Bewertung der Berichte.
"""

from __future__ import annotations

import datetime

from kern import halbsatz
from tests.baukasten import geschichten, saetze
from tests.baukasten.runner import bewerten, ziel_datum


def _lage_mit(frage: str, *, eroeffnet: bool = True, text: str = "") -> dict:
    lage = geschichten.lage_neu()
    lage["eroeffnet"] = eroeffnet
    lage["frage"] = frage
    lage["biancaText"] = text
    return lage


# ------------------------------------------------------------------ Story-Bau

def test_automatik_baut_valide_stories():
    for nr in range(1, 21):
        s = geschichten.automatik(nr, tag="Mittwoch")
        assert s["stimme"] in saetze.STIMMEN_M + saetze.STIMMEN_W
        assert s["vorname"] and s["nachname"] in saetze.NACHNAMEN
        assert s["grund"] in saetze.GRUENDE
        assert s["anliegen"] == geschichten.TERMIN
        assert 1 <= s["slotAnnahme"] <= 3
        for anker, thema in s["abschweifer"]:
            assert anker in geschichten.ABSCHWEIF_ANKER
            assert thema in saetze.ABSCHWEIFER
        # Reproduzierbar: gleicher Aufruf, gleiche Story.
        assert geschichten.automatik(nr, tag="Mittwoch") == s


def test_folge_story_erbt_persona():
    basis = geschichten.automatik(3)
    folge = geschichten.folge_story(basis, geschichten.ABSAGEN)
    assert folge["nachname"] == basis["nachname"]
    assert folge["stimme"] == basis["stimme"]
    assert folge["anliegen"] == geschichten.ABSAGEN
    assert folge["schonmal"] is True
    assert folge["folgeVon"] == basis["id"]
    assert not folge["abschweifer"] and not folge["halbsatz"]


def test_doku_story_traegt_anliegen():
    s = geschichten.doku_story(7, "rezept")
    assert s["anliegen"] == "rezept"
    assert not s["halbsatz"]


# ------------------------------------------------------- Mapping-Vollstaendigkeit

ALLE_FRAGEN = [
    "schonmal", "arzt", "name", "vorname", "nachname", "grund", "wunsch",
    "buchstabieren", "telefon", "telefon_check", "telefon_alt",
    "versicherung", "versicherung_check", "pzr", "slotwahl", "bestaetigung",
    "rueckblick", "wann", "behandlung", "neubuchung", "absage_ok",
    "verschieb_ok", "terminwahl",
]


def test_mapping_deckt_alle_maschinen_fragen():
    story = geschichten.automatik(1)
    story["behandler"] = "Petsas"
    for fid in ALLE_FRAGEN:
        zug = geschichten.naechster_baustein(story, _lage_mit(fid))
        assert (zug.get("text") or "").strip(), f"keine Antwort fuer frage={fid}"
        assert not zug.get("auflegen"), f"auflegen bei offener frage={fid}"


def test_eroeffnung_kommt_zuerst_und_nur_einmal():
    story = geschichten.automatik(2)
    story["halbsatz"] = False
    story["abschweifer"] = []
    lage = geschichten.lage_neu()
    zug = geschichten.naechster_baustein(story, lage)
    assert zug["baustein"] == "eroeffnung"
    assert lage["eroeffnet"] is True
    lage["frage"] = "schonmal"
    zug2 = geschichten.naechster_baustein(story, lage)
    assert zug2["baustein"] == "schonmal"
    assert "Nein" in zug2["text"]  # Neupatient


def test_slot_verhandlung_nimmt_beim_zweiten_mal_an():
    story = geschichten.automatik(4)
    story["slotAnnahme"] = 2
    story["slotRichtung"] = "frueher"
    story["abschweifer"] = []
    lage = _lage_mit("slotwahl")
    erster = geschichten.naechster_baustein(story, lage)
    assert erster["baustein"] == "slot_schieben"
    lage["frage"] = "slotwahl"
    zweiter = geschichten.naechster_baustein(story, lage)
    assert zweiter["baustein"] == "slot_annahme"


def test_slot_verhandlung_deckel_bei_drei():
    story = geschichten.automatik(5)
    story["slotAnnahme"] = 3
    story["abschweifer"] = []
    lage = _lage_mit("slotwahl")
    bausteine = []
    for _ in range(4):
        zug = geschichten.naechster_baustein(story, lage)
        bausteine.append(zug["baustein"])
        lage["frage"] = "slotwahl"
    assert bausteine[:2] == ["slot_schieben", "slot_schieben"]
    assert bausteine[2] == "slot_annahme"
    assert bausteine[3] == "slot_annahme"  # nie wieder schieben


def test_abschweifer_verdraengt_die_antwort_genau_einmal():
    story = geschichten.automatik(6)
    story["abschweifer"] = [("wunsch", "trump")]
    lage = _lage_mit("wunsch")
    erster = geschichten.naechster_baustein(story, lage)
    assert erster["baustein"] == "abschweifer_trump"
    assert erster["text"] in saetze.ABSCHWEIFER["trump"]
    lage["frage"] = "wunsch"  # Bianca stellt die Frage erneut
    zweiter = geschichten.naechster_baustein(story, lage)
    assert zweiter["baustein"] == "wunsch"
    assert "Mittwoch" in zweiter["text"]


def test_zwischenfrage_preis_bei_telefonfrage():
    story = geschichten.automatik(8)
    story["zwischenfragePreis"] = True
    story["abschweifer"] = []
    lage = _lage_mit("telefon")
    erster = geschichten.naechster_baustein(story, lage)
    assert erster["baustein"] == "zwischenfrage_preis"
    lage["frage"] = "telefon"
    zweiter = geschichten.naechster_baustein(story, lage)
    assert zweiter["baustein"] == "telefon"
    assert "null" in zweiter["text"].lower()


def test_readback_fehler_einmal_dann_ja():
    story = geschichten.automatik(9)
    story["readbackFehler"] = True
    story["abschweifer"] = []
    lage = _lage_mit("telefon_check")
    erster = geschichten.naechster_baustein(story, lage)
    assert erster["baustein"] == "readback_nein"
    lage["frage"] = "telefon_check"
    zweiter = geschichten.naechster_baustein(story, lage)
    assert zweiter["baustein"] == "readback_ja"


def test_abschluss_nichts_mehr_dann_abschied():
    story = geschichten.automatik(10)
    story["abschweifer"] = []
    lage = _lage_mit("", text="Der Termin ist eingetragen. Kann ich sonst noch etwas für Sie tun?")
    lage["gebucht"] = True
    erster = geschichten.naechster_baustein(story, lage)
    assert erster["baustein"] == "nichts_mehr"
    lage["biancaText"] = "Alles klar, dann bis nächste Woche!"
    zweiter = geschichten.naechster_baustein(story, lage)
    assert zweiter["baustein"] == "abschied"
    assert zweiter.get("auflegen") is True
    dritter = geschichten.naechster_baustein(story, lage)
    assert dritter.get("auflegen") is True and not dritter.get("text")


def test_halbsatz_paare_klingen_unfertig_und_fuegen_sich():
    for teil1, teil2 in saetze.HALBSATZ_PAARE:
        assert halbsatz.unfertig(teil1), teil1
        voll = f"{teil1} {teil2}"
        assert "termin" in voll.lower(), voll
        assert not halbsatz.unfertig(voll), voll


def test_halbsatz_eroeffnung_liefert_rest():
    story = geschichten.automatik(11)
    story["halbsatz"] = True
    lage = geschichten.lage_neu()
    zug = geschichten.naechster_baustein(story, lage)
    assert zug["baustein"] == "eroeffnung_halbsatz"
    assert zug.get("halbsatzRest")
    assert halbsatz.unfertig(zug["text"])


# ------------------------------------------------------------------ Bewertung

def _gruener_last_call(story: dict, ziel_iso: str) -> dict:
    return {
        "lastBook": {"booked": True, "slotIso": f"{ziel_iso}T09:00:00+02:00"},
        "sammler": {
            "grund": saetze.GRUENDE[story["grund"]][1],
            "telefon": "+491776004600",
            "nachname": story["nachname"],
        },
    }


def test_bewerten_gruen_bei_sauberer_buchung():
    story = geschichten.automatik(1)
    ziel = ziel_datum("Mittwoch")
    erg = bewerten(story, [], _gruener_last_call(story, ziel), ziel)
    assert erg["ok"], erg["checks"]


def test_bewerten_rot_bei_falscher_nummer():
    story = geschichten.automatik(1)
    ziel = ziel_datum("Mittwoch")
    lc = _gruener_last_call(story, ziel)
    lc["sammler"]["telefon"] = "015112345678"
    erg = bewerten(story, [], lc, ziel)
    assert not erg["ok"]
    rot = [c for c in erg["checks"] if not c["ok"]]
    assert any(c["name"] == "Telefon" for c in rot)


def test_bewerten_sammelt_waechter_und_latenz():
    story = geschichten.automatik(1)
    ziel = ziel_datum("Mittwoch")
    zuege = [
        {"wer": "bianca", "latenzS": 1.2, "ersterTonS": 0.4,
         "waechter": [{"w": "wiederholung-variante", "d": "wunsch"}]},
        {"wer": "bianca", "latenzS": 2.0, "ersterTonS": 0.9, "waechter": []},
        {"wer": "anrufer", "text": "Hallo"},
    ]
    erg = bewerten(story, zuege, _gruener_last_call(story, ziel), ziel)
    assert erg["latenzMaxS"] == 2.0
    assert erg["latenzMittelS"] == 1.6
    assert erg["waechter"] == ["wiederholung-variante"]


def test_frei_texte_ueberschreiben_katalog():
    story = geschichten.automatik(1)
    story["halbsatz"] = False
    story["abschweifer"] = []
    story["eroeffnungText"] = "Hallo, hier ist Martin Berger, ich brauche einen Termin."
    story["grundText"] = "Mir tut der Weisheitszahn weh."
    story["wunschText"] = "Am liebsten nächsten Dienstag nachmittags."
    story["versicherungText"] = "Ich bin privat versichert."
    story["slotText"] = "Den ersten nehmen wir."
    story["abschweiferText"] = "Ach, und wie teuer ist das eigentlich?"
    lage = geschichten.lage_neu()
    assert geschichten.naechster_baustein(story, lage)["baustein"] == "eroeffnung_frei"
    lage["frage"] = "schonmal"
    stoer = geschichten.naechster_baustein(story, lage)
    assert stoer["baustein"] == "abschweifer_frei"
    assert stoer["text"] == story["abschweiferText"]
    lage["frage"] = "grund"
    assert geschichten.naechster_baustein(story, lage)["text"] == story["grundText"]
    lage["frage"] = "wunsch"
    assert geschichten.naechster_baustein(story, lage)["baustein"] == "wunsch_frei"
    lage["frage"] = "versicherung"
    assert geschichten.naechster_baustein(story, lage)["baustein"] == "versicherung_frei"
    saetze_audio = geschichten.saetze_fuer_audio(story)
    assert story["eroeffnungText"] in saetze_audio
    assert story["grundText"] in saetze_audio
    assert story["abschweiferText"] in saetze_audio


def test_ziel_datum_ist_der_tag_der_kommenden_woche():
    freitag = datetime.date(2026, 8, 28)
    assert ziel_datum("Mittwoch", ab=freitag) == "2026-09-02"
    assert ziel_datum("Montag", ab=freitag) == "2026-08-31"
    mittwoch = datetime.date(2026, 8, 26)
    assert ziel_datum("Mittwoch", ab=mittwoch) == "2026-09-02"
