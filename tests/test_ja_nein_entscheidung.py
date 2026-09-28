"""Getaggte Ja/Nein-Fragen: natürliche Bestätigung und Ablehnung."""

from bianca import gehirn, verwalten
from kern import ohr, stille


def test_natuerliche_bestaetigungen_werden_semantisch_erkannt():
    faelle = (
        "Das ist korrekt.",
        "Das stimmt.",
        "Das passt für mich.",
        "Ist richtig.",
        "Ganz genau.",
        "Auf jeden Fall.",
        "Selbstverständlich.",
        "Einverstanden.",
        "Von mir aus.",
        "Damit bin ich einverstanden.",
        "Dagegen habe ich nichts.",
        "Das wäre für mich in Ordnung.",
        "Das würde passen.",
        "So ist es.",
        "Das ist in Ordnung.",
        "Das kann so bleiben.",
        "Machen Sie das bitte so.",
        "Bitte so eintragen.",
        "Den Termin nehme ich.",
        "Mhm.",
        "Mm-hmm.",
        "Jaa.",
    )
    for text in faelle:
        assert gehirn.ist_ja(text), text
        assert not gehirn.ist_nein(text), text


def test_natuerliche_ablehnungen_haben_vorrang():
    faelle = (
        "Das ist nicht korrekt.",
        "Das stimmt so nicht.",
        "Das passt für mich nicht.",
        "Bitte nicht eintragen.",
        "Das möchte ich nicht.",
        "Damit bin ich nicht einverstanden.",
        "Das lehne ich ab.",
        "Das wäre mir nicht recht.",
        "Das ist nicht mein Termin.",
        "Dieser Termin gehört mir nicht.",
        "Machen Sie das bitte nicht.",
        "Lieber nicht.",
        "Auf keinen Fall.",
        "Auf gar keinen Fall.",
        "Das ist falsch.",
        "So nicht.",
        "Das kommt nicht infrage.",
    )
    for text in faelle:
        assert gehirn.ist_nein(text), text
        assert not gehirn.ist_ja(text), text


def test_identitaetsfrage_versteht_umschreibungen():
    for text in ("Das bin ich.", "Ich bin das.", "Am Apparat.", "Sie sprechen mit mir."):
        assert gehirn.ja_nein_entscheidung(text, "anrufer_check") == "ja"
    for text in (
        "Das bin ich nicht.",
        "Ich bin nicht Frau Meier.",
        "Ich bin jemand anderes.",
        "Falsche Person.",
        "Sie haben den Falschen.",
    ):
        assert gehirn.ja_nein_entscheidung(text, "anrufer_check") == "nein"


def test_behandlerfrage_versteht_umschreibungen():
    for text in (
        "Gerne wieder.",
        "Wieder bei Doktor Petsas.",
        "Bei ihm.",
        "Beim gleichen Arzt.",
    ):
        assert gehirn.ja_nein_entscheidung(text, "arzt_check") == "ja"
    for text in (
        "Nicht wieder bei ihm.",
        "Lieber zu einem anderen Arzt.",
        "Eine andere Behandlerin bitte.",
        "Lieber jemand anderes.",
    ):
        assert gehirn.ja_nein_entscheidung(text, "arzt_check") == "nein"


def test_terminempfaenger_versteht_umschreibungen():
    for text in ("Für mich.", "Für mich selbst."):
        assert gehirn.ja_nein_entscheidung(text, "fuer_wen_check") == "ja"
    for text in (
        "Für jemand anderen.",
        "Für meine Tochter.",
        "Nicht für mich.",
        "Lieber jemand anderes.",
        "Für meinen Bruder.",
    ):
        assert gehirn.ja_nein_entscheidung(text, "fuer_wen_check") == "nein"


def test_aktionsfrage_versteht_hoefliche_aufforderung():
    assert (
        gehirn.ja_nein_entscheidung(
            "Können Sie das genau so eintragen?",
            "bestaetigung",
        )
        == "ja"
    )
    assert (
        gehirn.ja_nein_entscheidung(
            "Tragen Sie den Termin bitte nicht ein.",
            "bestaetigung",
        )
        == "nein"
    )
    assert (
        gehirn.ja_nein_entscheidung(
            "Ja, aber bitte nicht eintragen.",
            "bestaetigung",
        )
        == "nein"
    )


def test_kalenderschreibschutz_nutzt_dieselben_semantischen_entscheide():
    assert verwalten._bestaetigung_eindeutig(
        "Können Sie das genau so eintragen?"
    )
    assert verwalten._ablehnung_eindeutig(
        "Tragen Sie den Termin bitte nicht ein."
    )
    assert not verwalten._bestaetigung_eindeutig(
        "Ja, aber bitte nicht eintragen."
    )
    assert verwalten._bestaetigung_eindeutig(
        "Das bin ich.",
        "anrufer_check",
    )


def test_fragezustand_liefert_explizites_antworttyp_tag():
    assert ohr.sprachkontext({"sammler": {"frage": "anrufer_check"}}) == "ja_nein"
    assert ohr.sprachkontext({"sammler": {"frage": "bestaetigung"}}) == "ja_nein"
    assert ohr.sprachkontext({"sammler": {"frage": "buchstabieren"}}) == "name"
    assert ohr.sprachkontext({"sammler": {"frage": "grund"}}) == ""


def test_hoerfehler_wiederholt_die_entscheidungsfrage_statt_dialogverlust():
    sit = {
        "messages": [
            {
                "role": "assistant",
                "content": "Soll der Termin wieder bei Doktor Petsas sein?",
            }
        ]
    }
    erste = stille.hoerfehler_nachfrage(sit, ja_nein=True)
    zweite = stille.hoerfehler_nachfrage(sit, ja_nein=True)

    assert "Doktor Petsas" in erste
    assert "Ja oder Nein" in erste
    assert erste != zweite
    assert "Wobei darf ich Ihnen helfen" not in erste
