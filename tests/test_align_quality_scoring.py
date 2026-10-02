"""Paket 10: Ergebnisseite und Tages-Scorer teilen dieselbe Fehlergrenze."""

from __future__ import annotations

import pytest

from kern import anruf_anliegen
from tools import tages_scorer


def _manifest(*zuege: tuple[str, str], **extra) -> dict:
    manifest = {
        "id": extra.pop("sid", "anonym-qualitaet"),
        "tenantId": "meddent",
        "startedAt": "2026-10-02T10:00:00+00:00",
        "dauerMs": 45_000,
        "zuege": [
            {"nr": nr, "textIn": text_in, "text": text_out}
            for nr, (text_in, text_out) in enumerate(zuege, 1)
        ],
    }
    manifest.update(extra)
    return manifest


def _ist_fail_auf_beiden(manifest: dict) -> tuple[bool, bool]:
    ergebnis_fail = anruf_anliegen.anruf_wertung(manifest)[0] == "fehler"
    scorer_fail = tages_scorer.bewerten(manifest).klasse == "fehlerhaft"
    return ergebnis_fail, scorer_fail


@pytest.mark.parametrize(
    "manifest",
    [
        _manifest(
            ("Bitte rufen Sie mich zurück.", "Ich habe die Rückrufbitte notiert."),
            praxisNotiz="Rückruf erbeten.",
        ),
        _manifest(
            ("Ich brauche einen Termin.", "Wann passt es Ihnen?"),
        ),
        _manifest(
            ("Ich brauche einen Termin.", "Der Termin ist fest eingetragen."),
            lastBook={"ok": True, "appointmentId": "termin-anonym"},
        ),
        _manifest(
            ("Ich brauche einen Termin.", "Der Termin ist fest eingetragen."),
            lastBook={"ok": True, "appointmentId": "termin-retry"},
            tools=[
                {"name": "masBookAppointment", "ok": False, "error": "needs_phone"},
                {"name": "masUpdatePatientPhone", "ok": True},
                {"name": "masBookAppointment", "ok": True},
            ],
        ),
        _manifest(
            ("Ich brauche einen Termin.", "Ihr Termin ist fest eingetragen."),
        ),
        _manifest(
            ("Verbinden Sie mich bitte.", "Ich stelle Sie jetzt durch."),
        ),
        _manifest(
            ("Ich möchte meinen Termin absagen.", "Wie lautet Ihr Nachname?"),
            ("Muster.", "Unter diesem Namen finde ich keinen Termin."),
            tools=[{"name": "agentFindPatientAppointments", "notFound": True}],
        ),
        _manifest(
            ("Ich brauche einen Termin.", "Wie lautet Ihr Nachname?"),
            ("Muster.", "Wie lautet Ihr Nachname?"),
        ),
    ],
)
def test_ergebnisseite_und_scorer_haben_dieselbe_harte_fehlergrenze(
    manifest: dict,
):
    ergebnis_fail, scorer_fail = _ist_fail_auf_beiden(manifest)
    assert ergebnis_fail is scorer_fail


def test_rueckruf_ist_ehrlicher_abschluss_und_keine_fehlwertung():
    manifest = _manifest(
        (
            "Bitte lassen Sie mich zurückrufen.",
            "Ich habe Ihre Rückrufbitte für die Praxis notiert.",
        ),
        praxisNotiz="Rückruf erbeten.",
    )

    assert anruf_anliegen.anruf_wertung(manifest) == ("ok", [])
    row = tages_scorer.bewerten(manifest)
    assert row.klasse == "gut"
    assert row.gruende == ["ehrlicher_notiz_abschluss"]


def test_erfolgreicher_retry_bleibt_reibung_statt_harter_fehler():
    manifest = _manifest(
        ("Ich brauche einen Termin.", "Der Termin ist fest eingetragen."),
        lastBook={"ok": True, "appointmentId": "termin-retry"},
        tools=[
            {"name": "masBookAppointment", "ok": False, "error": "needs_phone"},
            {"name": "masUpdatePatientPhone", "ok": True},
            {"name": "masBookAppointment", "ok": True},
        ],
    )

    assert anruf_anliegen.harte_fehler(manifest) == []
    assert anruf_anliegen.anruf_wertung(manifest) == ("ok", [])
    row = tages_scorer.bewerten(manifest)
    assert row.klasse == "gut"
    assert "write_retry:book" in row.reibungen
