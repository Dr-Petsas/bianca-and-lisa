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


def test_anrufer_schluss_ohne_write_ist_gut():
    # Chef 26.09.2026: ein sauberer Abschied des Anrufers ist kein Fehl-Anruf.
    row = scorer.bewerten(
        _m(
            ("Ich hätte da mal eine allgemeine Frage gehabt.",
             "Gerne, wie kann ich Ihnen helfen?"),
            ("Ach, hat sich erledigt. Vielen Dank, auf Wiederhören.",
             "Sehr gerne, auf Wiederhören."),
        )
    )
    assert row.klasse == "gut"
    assert row.gruende == ["anrufer_abschluss_guter_verlauf"]


def test_anrufer_schluss_nach_unklar_bleibt_unvollstaendig():
    row = scorer.bewerten(
        _m(
            ("Ich brauche einen Termin.", "Das habe ich leider nicht verstanden."),
            ("Ach, ich probiere es später. Danke, tschüss.", "Auf Wiederhören."),
            dauer=20_000,
        )
    )
    assert row.klasse == "unvollstaendig"


def test_patient_nicht_gefunden_ist_harter_fehler():
    # „Patient nicht gefunden … ist ganz kritisch und darf es nicht geben.“
    row = scorer.bewerten(
        _m(
            ("Ich möchte meinen Termin absagen.", "Wie ist Ihr Nachname?"),
            ("Müller.", "Einen Moment, ich schaue nach."),
            tools=[{"name": "agentFindPatientAppointments", "notFound": True}],
        )
    )
    assert row.klasse == "fehlerhaft"
    assert "patient_nicht_gefunden" in row.gruende


def test_patient_nicht_gefunden_durch_online_link_ist_kein_fehler():
    row = scorer.bewerten(
        _m(
            ("Ich möchte einen Termin.", "Wie ist Ihr Nachname?"),
            ("Müller.", "Ich schicke Ihnen den Buchungslink per SMS."),
            tools=[{"name": "agentFindPatientAppointments", "notFound": True}],
            onlineBuchungslink={"ok": True, "an": "+4915100000000"},
        )
    )
    assert row.klasse != "fehlerhaft"
    assert "patient_nicht_gefunden" not in row.gruende


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


def test_richtig_behandelter_zahnnotfall_ist_erfolg_trotz_zwei_reibungen():
    """Live Thaler 28.09., f5a20db4…: kein Fail, Notfall korrekt gelöst."""
    manifest = _m(
        (
            "Ich brauche einen Termin.",
            "Wir kennen uns noch nicht. Ich bin die Neue! "
            "Habe ich Sie richtig erkannt?",
        ),
        ("Ja, hier ist Schranner.", "Sind Sie noch dran?"),
        (
            "Vom Zahn ist etwas abgebrochen.",
            "Das klingt akut. Kommen Sie bitte jetzt direkt in die Praxis. "
            "Eine feste Uhrzeit gibt es dafür nicht.",
        ),
        tenant="thaler",
        sid="f5a20db4e6ed489293dc5ec6fbcf33ee",
        dauer=53_320,
    )
    manifest["zuege"][-1]["waechter"] = [
        {"w": "notfall-vorrang", "d": "Vom Zahn ist etwas abgebrochen."},
    ]

    row = scorer.bewerten(manifest)

    assert row.klasse == "gut"
    assert row.gruende == ["zahnnotfall_richtig_erkannt_mit_reibung"]
    assert row.evidenz == ["notfall"]
    assert row.manuellPruefen is True


def test_notfall_marker_ueberstimmt_keinen_harten_fehler():
    manifest = _m(
        (
            "Vom Zahn ist etwas abgebrochen.",
            "Kommen Sie bitte jetzt direkt in die Praxis.",
        ),
        tools=[{"name": "masBookAppointment", "ok": False, "error": "kaputt"}],
    )
    manifest["zuege"][0]["waechter"] = [{"w": "notfall-vorrang"}]

    row = scorer.bewerten(manifest)

    assert row.klasse == "fehlerhaft"
    assert "write_fehlgeschlagen:book" in row.gruende


def test_notfall_marker_ohne_richtige_anweisung_ist_keine_erfolgsevidenz():
    manifest = _m(
        ("Vom Zahn ist etwas abgebrochen.", "Das habe ich nicht verstanden."),
    )
    manifest["zuege"][0]["waechter"] = [{"w": "notfall-vorrang"}]

    row = scorer.bewerten(manifest)

    assert "notfall" not in row.evidenz
    assert "zahnnotfall_richtig_erkannt" not in " ".join(row.gruende)


def test_englische_stt_altlast_macht_sicher_beibehaltenen_termin_nicht_zum_fail():
    """Live Thaler 28.09., 8e68db99…: Ablauf richtig, Parakeet-Englisch falsch."""
    unklar = "Das habe ich akustisch nicht sicher mitbekommen. Wobei darf ich Ihnen helfen?"
    row = scorer.bewerten(
        _m(
            (
                "Ja.",
                "Wir kennen uns noch nicht. Ich bin die Neue! "
                "Wie kann ich Sie unterstützen?",
            ),
            ("Oh, Gott.", unklar),
            ("Damn it.", unklar),
            (
                "Ich habe morgen einen Termin, den würde ich eventuell absagen wollen.",
                "Ich habe Ihren Termin morgen um elf Uhr gefunden. "
                "Soll ich ihn wirklich absagen?",
            ),
            (
                "Nein.",
                "Alles klar, der Termin bleibt bestehen. "
                "Kann ich sonst noch etwas für Sie tun?",
            ),
            ("Queen Service.", unklar),
            (
                "Mit normalen Menschen telefonieren.",
                "Eine menschliche Verbindung ist nicht eingerichtet.",
            ),
            tenant="thaler",
            sid="8e68db99ea954aaead15b07109b56f89",
            dauer=102_521,
        )
    )

    assert row.klasse == "gut"
    assert row.gruende == ["termin_nach_nein_sicher_beibehalten"]
    assert row.evidenz == ["termin_beibehalten"]
    assert "stt_englisch_alt:2" in row.reibungen
    assert not any(g.startswith("frage_wiederholt:") for g in row.gruende)
    assert row.manuellPruefen is True


def test_echte_deutsche_wiederholung_bleibt_trotz_beibehalten_harter_fehler():
    frage = "Das habe ich nicht verstanden. Wobei darf ich Ihnen helfen?"
    row = scorer.bewerten(
        _m(
            ("Unklar eins.", frage),
            ("Unklar zwei.", frage),
            ("Unklar drei.", frage),
            ("Nein.", "Alles klar, der Termin bleibt bestehen."),
        )
    )

    assert row.klasse == "fehlerhaft"
    assert any(g.startswith("frage_wiederholt:3:") for g in row.gruende)


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


def test_meine_frage_war_ist_keine_presence():
    """Auswertung 06.10.2026: die Stups-/Hoerfehler-Wiederholung ist kein
    "Sind Sie noch dran?" und darf die Presence-Quote nicht aufblasen."""
    row = scorer.bewerten(
        _m(
            ("Termin bitte.", "Meine Frage war: Waren Sie schon einmal bei uns?"),
            ("Ja.", "Der Termin ist fest eingetragen."),
            lastBook={"ok": True, "appointmentId": "a1"},
        )
    )
    assert not any(r.startswith("presence") for r in row.reibungen)


def test_transfer_spur_ist_beleg():
    m = _m(
        ("Ich möchte mit Doktor Petsas sprechen.",
         "Ich verbinde Sie mit Doktor Petsas."),
        ("", ""),
    )
    m["zuege"][1]["waechter"] = [{"w": "transfer", "d": "Dr. Petsas"}]
    row = scorer.bewerten(m)
    assert "transfer" in row.evidenz
    assert "erfolg_ohne_beweis:transfer" not in row.gruende


def test_transfer_ohne_spur_bleibt_unbelegt():
    row = scorer.bewerten(
        _m(
            ("Ich möchte mit Doktor Petsas sprechen.",
             "Ich verbinde Sie mit Doktor Petsas."),
        )
    )
    assert "transfer" not in row.evidenz
