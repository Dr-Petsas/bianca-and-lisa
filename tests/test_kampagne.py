"""Kampagne Stufe 1: Seite trägt das Fenster, Lisa erfindet nichts."""

from __future__ import annotations

from kern import calendar
from lisa import kampagne


SEITE = {
    "name": "Recall September",
    "praxis": "Zahnärzte im Medical Center Düsseldorf",
    "behandler": "Dr. Petsas",
    "motiv": "Kontrolle",
    "zeitraumVon": "2026-09-01",
    "zeitraumBis": "2026-09-30",
    "zeitraum": "01.09.2026 – 30.09.2026",
    "greeting": "Hallo, hier spricht Lisa von der Praxis.",
}

DEFAULT = (
    "Freundlich erinnern, Slots im Zeitraum anbieten, Termin buchen; "
    "Datenschutz beachten; bei Unsicherheit Rückruf notieren."
)


def test_seite_mit_fenster_fragt_nicht_nach_zeitraum():
    out = kampagne.vertiefen(DEFAULT, kampagne=SEITE)
    assert out["ok"] and out["bereit"]
    assert not out["fragen"]
    assert any("Terminfenster" in z for z in out["unterlage"])
    assert "01.09.2026" in out["briefing"] or "2026-09-01" in " ".join(out["unterlage"])
    assert "pzr" not in out["briefing"].lower()


def test_fehlendes_fenster_wird_gefragt():
    k = {**SEITE, "zeitraumVon": "", "zeitraumBis": "", "zeitraum": ""}
    out = kampagne.vertiefen(DEFAULT, kampagne=k)
    assert out["ok"] and not out["bereit"]
    assert any(f["id"] == "zeitraum" for f in out["fragen"])


def test_chef_antwort_schliesst_luecke():
    leer = {"name": "Kampagne X", "praxis": "Testpraxis"}
    out = kampagne.vertiefen("Bitte anrufen.", kampagne=leer)
    ids = {f["id"] for f in out["fragen"]}
    assert "zeitraum" in ids and "motiv" in ids
    fertig = kampagne.vertiefen(
        "Bitte anrufen.",
        kampagne=leer,
        antworten={"zeitraum": "1. bis 15. Oktober", "motiv": "Nachsorge Implantat"},
    )
    assert fertig["bereit"]
    assert not fertig["fragen"]
    assert "1. bis 15. Oktober" in fertig["briefing"]
    assert "Nachsorge Implantat" in fertig["briefing"]


def test_standardprompt_erfindet_kein_pzr():
    out = kampagne.vertiefen(DEFAULT, kampagne=SEITE)
    text = (out["briefing"] + " " + " ".join(out["unterlage"])).lower()
    assert "pzr" not in text
    assert "zahnreinigung" not in text
    assert "kontrolle" in text


def test_ohne_alles_scheitert():
    out = kampagne.vertiefen("  ")
    assert not out["ok"]


def test_probe_name_aus_kampagne():
    assert kampagne.probe_name(SEITE) == "Probe Recall September"
    assert kampagne.probe_name({}) == "Probe Recall"


def test_kalender_fenster_filter():
    ctx = {"kampagneVon": "2026-09-01", "kampagneBis": "2026-09-15"}
    assert calendar._im_fenster("2026-09-10T09:00:00", ctx)
    assert not calendar._im_fenster("2026-08-31T09:00:00", ctx)
    assert not calendar._im_fenster("2026-09-16T09:00:00", ctx)
    roh = ["2026-08-31T09:00:00", "2026-09-02T10:00:00", "2026-09-20T11:00:00"]
    assert calendar._filter_fenster(roh, ctx) == ["2026-09-02T10:00:00"]


def test_probe_schreibt_nicht_trotz_write_live():
    echt = calendar.WRITE_LIVE
    calendar.WRITE_LIVE = True
    try:
        assert calendar._trocken({"probe": True})
        assert not calendar._trocken({})
        out = calendar.book_slot({}, {"probe": True, "slotIso": "2026-09-10T09:00:00"},
                                 slot_iso="2026-09-10T09:00:00")
        assert out["ok"] and out["dryRun"] and not out.get("booked")
        weg = calendar.book_slot(
            {},
            {"probe": True, "slotIso": "2026-08-01T09:00:00",
             "kampagneVon": "2026-09-01", "kampagneBis": "2026-09-30"},
            slot_iso="2026-08-01T09:00:00",
        )
        assert not weg["ok"]
        assert "Fenster" in weg["spoken"] or "Zeitfenster" in weg["spoken"]
    finally:
        calendar.WRITE_LIVE = echt


def test_stufe2_nimmt_fenster_von_der_seite():
    from lisa import vorbereitung as vorb
    echt_g = vorb._gedaechtnis_stand
    echt_t = vorb._termine
    vorb._gedaechtnis_stand = lambda n, p: ([], "nichts")
    vorb._termine = lambda tid, pat: ([], [])
    try:
        out = kampagne.sammeln_patient(
            DEFAULT,
            kampagne=SEITE,
            patient={"id": "p1", "name": "Anna Berger", "firstName": "Anna",
                     "lastName": "Berger", "phone": "01761110001"},
        )
        assert out["ok"]
        assert any("Terminfenster" in z for z in out["unterlage"])
        assert not any("zeitraum" in x.lower() for x in out["luecken"])
        assert "pzr" not in " ".join(out["luecken"]).lower()
    finally:
        vorb._gedaechtnis_stand = echt_g
        vorb._termine = echt_t


def test_stufe2_liste_ohne_empfaenger_scheitert():
    out = kampagne.sammeln_liste(DEFAULT, kampagne=SEITE, patienten=[])
    assert not out["ok"] and out["offen"] == 0


def test_stufe2_liste_zaehlt_offen():
    from lisa import vorbereitung as vorb
    echt_g = vorb._gedaechtnis_stand
    echt_t = vorb._termine
    vorb._gedaechtnis_stand = lambda n, p: ([], "nichts")
    vorb._termine = lambda tid, pat: ([], [])
    try:
        out = kampagne.sammeln_liste(
            DEFAULT, kampagne=SEITE,
            patienten=[
                {"id": "a", "name": "Anna Berger", "phone": "0176111"},
                {"id": "b", "firstName": "", "lastName": "", "phone": ""},
            ],
        )
        assert out["ok"]
        assert out["fertig"] + out["offen"] == 2
        assert any(x["patientId"] == "a" for x in out["patienten"])
    finally:
        vorb._gedaechtnis_stand = echt_g
        vorb._termine = echt_t
