from __future__ import annotations

import json

import pytest

from tools import korrektur_pruefliste as kp


@pytest.mark.parametrize("satz", [
    "Nein, nein, nicht Thomas, Thannes ist mein Nachname.",
    "Ich meinte Doktor Petsas.",
    "Nicht Dienstag, sondern Donnerstag.",
    "Das stimmt nicht, die letzte Ziffer ist eine Neun.",
    "Sie haben mich falsch verstanden.",
    "Ich habe doch gesagt, dass ich privat versichert bin.",
    "Ich heiße nicht Rateike fertig, sondern Rateike.",
])
def test_korrekturen_werden_erkannt(satz):
    assert kp.art(satz) in {"korrektur", "widerspruch"}


@pytest.mark.parametrize("satz", [
    "Nein.",
    "Nein, danke.",
    "Nein, das war's.",
    "Nee, alles gut.",
    "Ich habe Sie nicht richtig verstanden.",
    "Ich möchte einen Termin.",
    "Ja, genau.",
    "",
])
def test_antworten_sind_keine_korrektur(satz):
    assert kp.art(satz) == ""


def test_nein_mit_inhalt_ist_widerspruch():
    assert kp.art("Nein, ich möchte meinen Termin absagen.") == "widerspruch"


def _zuege(*paare):
    return [{"textIn": a, "text": b} for a, b in paare]


def test_wiederholte_frage_nach_korrektur_ist_rot():
    zuege = _zuege(
        ("Thomas.", "Danke. Wie ist Ihr Vorname?"),
        ("Nein, nein, nicht Thomas, Thannes ist mein Nachname.",
         "Danke. Wie ist Ihr Vorname?"),
    )
    signale = kp.befunde(zuege, 1)
    assert "frage_wiederholt" in signale
    assert kp.stufe(signale) == "rot"


def test_erneute_korrektur_ist_rot():
    zuege = _zuege(
        ("Petsas.", "Danke."),
        ("Ich meinte Patrikis.", "Alles klar."),
        ("Nein, ich habe Patrikis gesagt.", "Gut."),
    )
    assert "korrektur_erneut" in kp.befunde(zuege, 1)


def test_quittierte_korrektur_ist_gruen():
    zuege = _zuege(
        ("Thomas.", "Danke. Wie ist Ihr Vorname?"),
        ("Nein, nein, nicht Thomas, Thannes ist mein Nachname.",
         "Entschuldigung — ich hatte Thomas gehört. Dann korrigiere ich auf Thannes. "
         "Wie ist Ihr Vorname?"),
    )
    signale = kp.befunde(zuege, 1)
    assert "quittiert" in signale
    assert kp.stufe(signale) == "gruen"


def test_unklar_satz_ist_rot():
    zuege = _zuege(
        ("Kontrolle.", "Zur Kontrolle, gerne."),
        ("Nein, ich will eine Zahnreinigung.", "Das habe ich nicht verstanden."),
    )
    assert kp.stufe(kp.befunde(zuege, 1)) == "rot"


def test_ohne_quittung_und_ohne_befund_ist_gelb():
    zuege = _zuege(
        ("Dienstag.", "Am Dienstag hätte ich neun Uhr."),
        ("Nicht Dienstag, sondern Donnerstag.", "Am Donnerstag hätte ich zehn Uhr."),
    )
    assert kp.stufe(kp.befunde(zuege, 1)) == "gelb"


def _manifest():
    return {
        "startedAt": "2026-10-06T08:00:00+00:00",
        "tenant": {"id": "meddent"},
        "sammler": {"nachname": "Thannes", "vorname": "Kiriakos"},
        "zuege": [
            {"textIn": "Hallo.", "text": "Hallo. Wie ist Ihr Nachname?"},
            {"textIn": "Thomas.", "text": "Danke. Wie ist Ihr Vorname?"},
            {"textIn": "Nein, nein, nicht Thomas, Thannes ist mein Nachname. "
                       "Meine Nummer ist 0177 1234567.",
             "text": "Danke. Wie ist Ihr Vorname?"},
        ],
    }


def test_pruefen_maskiert_namen_und_nummern():
    [e] = kp.pruefen("abcdef1234567890", _manifest())
    assert e["id"] == "abcdef12-z2"
    assert e["praxis"] == "meddent"
    assert e["stufe"] == "rot"
    assert "Thannes" not in e["eingabe"]
    assert "1234567" not in e["eingabe"]
    assert "[NAME]" in e["eingabe"] and "[NUMMER]" in e["eingabe"]
    assert len(e["vorlauf"]) == 2


def test_allerweltswort_im_verhoerten_namen_bleibt_lesbar():
    m = _manifest()
    m["sammler"]["name"] = "SMS Thannes"
    m["zuege"][2]["text"] = "Sie bekommen eine SMS. Wie ist Ihr Vorname?"
    [e] = kp.pruefen("abcdef1234567890", m)
    assert "SMS" in e["ist"]
    assert "Thannes" not in e["eingabe"]


def test_anrede_ohne_manifestfeld_wird_maskiert():
    assert kp.maskieren("Ah, Frau Pongracz — Herr Doktor Petsas.", []) == \
        "Ah, Frau [NAME] — Herr Doktor Petsas."


def test_klartext_zeigt_den_wortlaut():
    [e] = kp.pruefen("abcdef1234567890", _manifest(), klartext=True)
    assert "Thannes" in e["eingabe"]


def test_main_liest_nur_und_schreibt_den_bericht(tmp_path, capsys):
    root = tmp_path / "anrufe"
    ordner = root / "abcdef1234567890"
    ordner.mkdir(parents=True)
    pfad = ordner / "anruf.json"
    pfad.write_text(json.dumps(_manifest()), encoding="utf-8")
    vorher = pfad.read_bytes()
    ziel = tmp_path / "liste.json"

    assert kp.main(["--root", str(root), "--datum", "2026-10-06",
                    "--json", str(ziel)]) == 0

    assert pfad.read_bytes() == vorher
    rep = json.loads(ziel.read_text(encoding="utf-8"))
    assert rep["anrufe"] == 1 and rep["stufen"]["rot"] == 1
    assert "Thannes" not in ziel.read_text(encoding="utf-8")
    assert "[rot] abcdef12-z2" in capsys.readouterr().out


def test_anderer_tag_wird_nicht_gelesen(tmp_path, capsys):
    root = tmp_path / "anrufe"
    (root / "s1").mkdir(parents=True)
    (root / "s1" / "anruf.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    kp.main(["--root", str(root), "--datum", "2026-10-08"])
    assert "anrufe=0" in capsys.readouterr().out
