"""Feste, nicht schoenrechenbare Rubrik fuer den 40/80-Tages-Scorer."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from tools import tages_scorer as scorer


def _m(
    *paare: tuple[str, str],
    tenant: str = "blessing",
    sid: str = "s1",
    dauer: int = 60_000,
    **extra,
) -> dict:
    zuege = [
        {
            "nr": i,
            "art": "listen",
            "textIn": text_in,
            "text": text_out,
            "timings": {},
        }
        for i, (text_in, text_out) in enumerate(paare, 1)
    ]
    out = {
        "id": sid,
        "tenantId": tenant,
        "startedAt": "2026-09-15T08:15:00+00:00",
        "dauerMs": dauer,
        "zuege": zuege,
    }
    out.update(extra)
    return out


def test_reines_hallo_ist_aufleger():
    row = scorer.bewerten(_m(("Hallo.", "Guten Tag.")))
    assert row.klasse == "aufleger"
    assert row.gewertet is False


def test_genanntes_anliegen_bleibt_nach_abbruch_in_der_wertung():
    row = scorer.bewerten(
        _m(("Ich brauche einen Termin.", "Waren Sie schon einmal bei uns?"), dauer=18_000)
    )
    assert row.klasse == "unvollstaendig"
    assert row.gewertet is True


def test_belegte_buchung_ohne_reibung_ist_super():
    row = scorer.bewerten(
        _m(
            ("Ich brauche einen Termin.", "Gern."),
            ("Ja.", "Der Termin ist fest eingetragen."),
            lastBook={"ok": True, "appointmentId": "a1"},
        )
    )
    assert row.klasse == "super"
    assert row.evidenz == ["book"]


def test_behauptete_buchung_ohne_beweis_ist_harter_fehler():
    row = scorer.bewerten(
        _m(
            ("Ich brauche einen Termin.", "Ihr Termin ist fest eingetragen."),
            ("Danke.", "Auf Wiederhören."),
        )
    )
    assert row.klasse == "fehlerhaft"
    assert "erfolg_ohne_beweis:book" in row.gruende


def test_explizit_fehlgeschriebene_buchung_ist_harter_fehler():
    row = scorer.bewerten(
        _m(
            ("Ich brauche einen Termin.", "Das hat leider nicht geklappt."),
            tools=[{"name": "masBookAppointment", "ok": False, "error": "slotTaken"}],
        )
    )
    assert row.klasse == "fehlerhaft"
    assert "write_fehlgeschlagen:book" in row.gruende


def test_erfolgreicher_retry_ist_gut_statt_fehlerhaft_oder_super():
    row = scorer.bewerten(
        _m(
            ("Ich brauche einen Termin.", "Der Termin ist fest eingetragen."),
            lastBook={"ok": True, "appointmentId": "a1"},
            tools=[
                {"name": "masBookAppointment", "ok": False, "error": "needs_phone"},
                {"name": "masUpdatePatientPhone", "ok": True},
                {"name": "masBookAppointment", "ok": True},
            ],
        )
    )
    assert row.klasse == "gut"
    assert "write_retry:book" in row.reibungen


def test_echte_praxisnotiz_ist_hoechstens_gut():
    row = scorer.bewerten(
        _m(
            ("Es geht um meinen Termin.", "Ich habe eine Rückrufbitte notiert."),
            praxisNotiz="Bitte zurückrufen",
        )
    )
    assert row.klasse == "gut"
    assert row.evidenz == ["note"]


def test_drei_unklar_saetze_bleiben_trotz_buchung_fehlerhaft():
    row = scorer.bewerten(
        _m(
            ("Termin bitte.", "Was meinen Sie damit?"),
            ("Morgen.", "Was meinen Sie damit?"),
            ("Ja.", "Was meinen Sie damit? Der Termin ist fest eingetragen."),
            lastBook={"ok": True, "appointmentId": "a1"},
        )
    )
    assert row.klasse == "fehlerhaft"
    assert any(g.startswith("unklar_schleife:") for g in row.gruende)


def test_eine_kleine_reibung_macht_belegten_abschluss_gut():
    row = scorer.bewerten(
        _m(
            ("Termin bitte.", "Ich bin die Neue!"),
            ("Ja.", "Der Termin ist fest eingetragen."),
            lastBook={"ok": True, "appointmentId": "a1"},
        )
    )
    assert row.klasse == "gut"
    assert row.reibungen == ["eisbrecher_neue"]


def test_mehrere_reibungen_machen_abschluss_durchwachsen():
    row = scorer.bewerten(
        _m(
            ("Termin bitte.", "Ich bin die Neue! Sind Sie noch dran?"),
            ("Ja.", "Der Termin ist fest eingetragen."),
            lastBook={"ok": True, "appointmentId": "a1"},
        )
    )
    assert row.klasse == "durchwachsen"
    assert len(row.reibungen) == 2


def test_regelantwort_ist_gut_und_muss_manuell_geprueft_werden():
    row = scorer.bewerten(
        _m(
            (
                "Ich brauche ein Rezept.",
                "Dafür müssen Sie persönlich in die Praxis kommen.",
            )
        )
    )
    assert row.klasse == "gut"
    assert row.manuellPruefen is True


def test_bericht_liefert_praxis_stunde_und_40_80_ziel():
    rows = []
    for i in range(4):
        rows.append(
            scorer.bewerten(
                _m(
                    ("Termin bitte.", "Der Termin ist fest eingetragen."),
                    sid=f"super-{i}",
                    lastBook={"ok": True, "appointmentId": f"a{i}"},
                )
            )
        )
    for i in range(4):
        rows.append(
            scorer.bewerten(
                _m(
                    ("Termin bitte.", "Eine Rückrufbitte ist notiert."),
                    sid=f"gut-{i}",
                    praxisNotiz="Bitte zurückrufen",
                )
            )
        )
    rows.extend(
        scorer.bewerten(
            _m(("Termin bitte.", "Wann passt es?"), sid=f"offen-{i}", dauer=180_000)
        )
        for i in range(2)
    )
    report = scorer.bericht(rows)
    assert report["gesamt"]["superPct"] == 40.0
    assert report["gesamt"]["superPlusGutPct"] == 80.0
    assert report["gesamt"]["ziel"]["super40"] is True
    assert report["gesamt"]["ziel"]["superPlusGut80"] is True
    assert report["gesamt"]["ziel"]["mindestens50"] is False
    assert report["praxen"]["blessing"]["gewertet"] == 10
    assert list(report["stunden"]) == ["2026-09-15 10:00"]


def test_manifest_filter_ist_read_only_und_schliesst_tests_aus(tmp_path):
    root = tmp_path / "anrufe"
    call = root / "echt"
    call.mkdir(parents=True)
    manifest = _m(("Termin bitte.", "Wann passt es?"))
    (call / "anruf.json").write_text(json.dumps(manifest), encoding="utf-8")
    test_call = root / "test"
    test_call.mkdir()
    test_manifest = _m(("Termin bitte.", "Wann passt es?"), sid="test")
    test_manifest["testAnruf"] = True
    (test_call / "anruf.json").write_text(json.dumps(test_manifest), encoding="utf-8")
    vorher = (call / "anruf.json").read_bytes()

    rows = scorer.manifests(
        root,
        start=datetime(2026, 9, 15, tzinfo=timezone.utc),
        ende=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )

    assert [sid for sid, _ in rows] == ["echt"]
    assert (call / "anruf.json").read_bytes() == vorher


def test_super_stichprobe_ist_deterministisch_und_ungefaehr_zehn_prozent():
    werte = [scorer._deterministische_stichprobe(f"session-{i}") for i in range(1000)]
    assert werte == [
        scorer._deterministische_stichprobe(f"session-{i}") for i in range(1000)
    ]
    assert 70 <= sum(werte) <= 130
