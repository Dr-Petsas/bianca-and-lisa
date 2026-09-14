"""W-RECHNUNG (14.09.2026, Thaler-Anruf 3ad3b6d3) — offline, ohne Modell.

Chef (woertlich): "Rechnungsreklamation., Fehlerhafte Rechnung., Fehler,
abrechnungsfehler, Buchhaltung...Rechnung... diese und aehnliche Worte/Saetze
muessen wir nachschaerfen dadurch, dass Bianca sagt, dass Rechnungsthemen nur
persoenlich in der Praxis besprochen werden koennen, oder sie einen Rueckruf
anbietet und einrichtet auf Wunsch. Sie selbst hat keine Autorisation, ueber
Rechnungen zu reden."

Live antwortete Bianca auf "Rechnungsreklamation." und "Fehlerhafte Rechnung."
zweimal mit dem Unklar-Satz — zwei verschenkte Zuege.

Regeln seitdem (kern/rechnung.py + bianca/flow._rechnung_zug):
- Erkennung deterministisch (0 ms): harte Rechnungswoerter immer, weiche nur
  mit Beschwerde-Marker und ohne Termin-/Kassen-Kontext; "Buchhaltung" ist ein
  Rechnungsthema, kein Durchstell-Wunsch; ein NAMENTLICH verlangter Behandler
  bleibt Weiterleitung; im Diktat (Nummer/Buchstabieren) nie.
- Zug: Erklaerung + Rueckruf-Frage (frage=rechnung_rueckruf). Ja -> der
  bewaehrte ABGEBEN-Weg (Name, Nummer, echte Notiz). Nein/persoenlich ->
  ehrlich abschliessen. Unklar -> EINE Nachfrage, dann gilt Nein.
- Mitten in einer Buchung wird diese geparkt und kommt danach zurueck —
  mit den beim Rueckruf diktierten Kontaktdaten im Checkpoint.
- Am LLM-Ausgang: Rechnungs-Behauptungen des Modells fallen (Betrag,
  Zahlungsstand, "ich kuemmere mich"); der Verweis auf die Praxis bleibt.
- Report: das Thema steht im Gedaechtnis-Report, auch ohne Rueckruf.

LLM darf hier NIE laufen; Kalender/Hintergrund gestummt.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bianca import agent, flow, gehirn, verwalten, weiterleiten
from kern import gedaechtnis, hirn, rechnung
from kern.tenants import laden


def _s(v) -> str:
    return " ".join(str(v or "").split()).strip()


def _sit() -> dict:
    sit = {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}],
           "stimme": "bianca"}
    hirn.init(sit)
    return sit


@pytest.fixture
def ohne_netz(tmp_path: Path, monkeypatch):
    """LLM = Testbruch, Hintergrund stumm, Notizen in tmp; liefert die JSONL-Zeilen."""
    from kern import llm

    def _knall(*a, **k):
        raise AssertionError("LLM darf hier nicht laufen")

    monkeypatch.setattr(llm, "chat", _knall)
    monkeypatch.setattr(llm, "chat_stream", _knall)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    monkeypatch.setattr(verwalten.hintergrund, "anstossen", lambda sit: None)
    monkeypatch.setattr(verwalten, "DATA_DIR", tmp_path)
    monkeypatch.setenv("MAS_GEDAECHTNIS", "0")
    monkeypatch.setenv("INTENT_NACHZUG", "0")
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    monkeypatch.delenv("RECHNUNG", raising=False)
    monkeypatch.delenv("RECHNUNG_WACHE", raising=False)
    datei = tmp_path / "praxis_notizen.jsonl"

    def lesen() -> list[dict]:
        if not datei.exists():
            return []
        return [json.loads(z) for z in datei.read_text(encoding="utf-8").splitlines() if z.strip()]
    return lesen


def _zug(sit: dict, text: str, **k) -> str:
    return _s(agent.user_turn(sit, text, **k).get("text"))


def _stand(sit: dict) -> str:
    return _s((sit.get("rechnungStand") or {}).get("status"))


def _hirn(sit: dict) -> list[tuple[str, str, bool]]:
    return [(_s(a.get("handlung")), _s(a.get("status")), bool(a.get("rechnung")))
            for a in (sit.get("hirn") or {}).get("anliegen") or []]


# --- Erkennung --------------------------------------------------------------

@pytest.mark.parametrize("satz", [
    "Rechnungsreklamation.",
    "Fehlerhafte Rechnung.",
    "Ich habe einen Abrechnungsfehler entdeckt.",
    "Buchhaltung.",
    "Buchhaltung, es geht um die Rechnung.",
    "Kann ich mit der Buchhaltung sprechen?",
    "Ich habe eine Mahnung bekommen, obwohl ich bezahlt habe.",
    "Die Rechnung stimmt nicht.",
    "Ich habe zu viel bezahlt.",
    "Sie haben mir doppelt abgebucht.",
    "Ich habe keine Rechnung bekommen.",
    "Ich habe da eine Frage zur Rechnung.",
    "Rufen Sie mich wegen der Rechnung zurück.",
])
def test_erkennung_rechnungsthemen(satz):
    assert rechnung.erkannt(satz, _sit()), satz


@pytest.mark.parametrize("satz", [
    "Was kostet eine Zahnreinigung?",
    "Wird die Zahnreinigung von der Kasse bezahlt?",
    "Ich brauche einen Termin zur Kontrolle.",
    "Ich hätte gern einen Termin, was kostet das?",
    "Ich möchte mit Doktor Petsas über die Rechnung sprechen.",
    "Rechnungshofer.",
    "Berechnung der Kosten bitte.",
    "Es geht nicht um die Rechnung, ich brauche einen Termin.",
    "Ich brauche keine Rechnung, nur den Termin.",
    "Die Buchhaltung meinte, ich soll einen Termin machen.",
    "Ja, gerne.",
])
def test_erkennung_gegenproben(satz):
    """Preisfragen, Termine, namentlich verlangter Arzt, Nachnamen — nie
    Rechnungsthema (ein Fehltreffer kostet einen laufenden Vorgang)."""
    assert not rechnung.erkannt(satz, _sit()), satz


def test_erkennung_schweigt_im_diktat():
    """Waehrend Nummer/Buchstabieren laeuft, oeffnet kein Wort das Thema —
    ausser der Aufrufer fuehrt das Rechnungs-Diktat selbst (im_diktat)."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["frage"] = "telefon"
    s["telefonTeil"] = "0171"
    assert rechnung.diktat_laeuft(sit)
    assert not rechnung.erkannt("Ich habe da noch eine Frage zur Rechnung.", sit)
    assert rechnung.erkannt("Ich habe da noch eine Frage zur Rechnung.", sit, im_diktat=True)
    s["frage"] = "buchstabieren"
    s["telefonTeil"] = ""
    assert not rechnung.erkannt("Rechnungsprüfer.", sit)
    s["frage"] = "wunsch"
    assert not rechnung.diktat_laeuft(sit)
    assert rechnung.erkannt("Die Rechnung war falsch.", sit)


def test_notaus_rechnung_null(monkeypatch):
    monkeypatch.setenv("RECHNUNG", "0")
    assert not rechnung.erkannt("Rechnungsreklamation.", _sit())


def test_rueckruf_wunsch_und_persoenlich():
    assert rechnung.rueckruf_gewuenscht("Rufen Sie mich wegen der Rechnung zurück.")
    assert rechnung.rueckruf_gewuenscht("Können Sie mich bitte zurückrufen?")
    assert rechnung.rueckruf_gewuenscht("Die Praxis soll sich bei mir melden.")
    assert not rechnung.rueckruf_gewuenscht("Rufen Sie mich nicht an.")
    assert not rechnung.rueckruf_gewuenscht("Die Rechnung ist falsch.")
    assert rechnung.persoenlich_klaeren("Nein danke, ich komme vorbei.")
    assert rechnung.persoenlich_klaeren("Das kläre ich dann vor Ort.")
    assert not rechnung.persoenlich_klaeren("Ja, bitte.")


# --- Der Anruf 3ad3b6d3, wie er haette laufen sollen -------------------------

def test_anruf_3ad3b6d3_rechnungsreklamation_bis_zur_notiz(ohne_netz):
    """Kein Unklar-Satz mehr: Erklaerung + Rueckruf-Frage, Ja -> Name ->
    Nummer -> Readback Ziffer fuer Ziffer -> Ja -> echte Notiz mit Nummer,
    Stand notiert, Report traegt es; 'Nein, das war alles' legt auf."""
    sit = _sit()
    t1 = _zug(sit, "Rechnungsreklamation.")
    assert rechnung.ERKLAERUNG in t1 and rechnung.RUECKRUF_FRAGE in t1
    assert "verstanden" not in t1.lower()
    s = gehirn.sammler(sit)
    assert s["frage"] == "rechnung_rueckruf" and _stand(sit) == "offen"
    assert _hirn(sit) == [("ABGEBEN", "aktiv", True)]

    t2 = _zug(sit, "Ja, bitte.")
    assert t2 == rechnung.NAME_FRAGE
    assert _stand(sit) == "rueckruf" and sit["hirnAbgeben"]["offen"] is True

    t3 = _zug(sit, "Müller.")
    assert t3 == rechnung.NUMMER_FRAGE
    t4 = _zug(sit, "0177 1234567")
    # Readback statt Notiz: die Nummer wird erst nach dem Ja fest.
    assert t4.startswith("Ich wiederhole die Nummer") and "Stimmt das so?" in t4
    assert "null eins sieben sieben" in t4.lower()
    s = gehirn.sammler(sit)
    assert s["frage"] == "telefon_check" and s["telefonOffen"] == "01771234567"
    assert not s["telefon"] and ohne_netz() == [] and _stand(sit) == "rueckruf"

    t5 = _zug(sit, "Ja, richtig.")
    # Kein zweites Vorlesen der eben bestaetigten Nummer, dafuer die Folgefrage.
    assert t5 == f"{rechnung.NOTIERT} {rechnung.SONST_NOCH}"
    assert "null eins sieben sieben" not in t5.lower()
    assert _stand(sit) == "notiert"
    assert _hirn(sit) == [("ABGEBEN", "erledigt", True)]
    assert sit["hirnAbgeben"]["offen"] is False
    assert gehirn.sammler(sit)["frage"] == "sonst_noch"

    n = ohne_netz()
    assert len(n) == 1
    assert "Rechnung" in n[0]["was"] and n[0]["telefon"] == "01771234567"
    assert n[0]["name"].endswith("Müller")
    assert "Rechnung" in _s(sit.get("praxisNotiz"))

    report = gedaechtnis.zusammenfassung(sit)
    assert "Rückruf-Notiz" in report and "Rechnungsthema angesprochen" in report

    aus = agent.user_turn(sit, "Nein, das war alles.")
    assert _s(aus.get("text")) == rechnung.SONST_NOCH_NEIN and aus.get("hangup") is True
    assert len(ohne_netz()) == 1


def test_nummer_nein_auf_readback_einmal_neu_dann_ja(ohne_netz):
    """'Nein, die letzte war eine neun' auf das Readback: Korrektur schlaegt
    Fragment (kein einsames '9'), die Nummer wird neu erfragt, das zweite
    Readback bestaetigt — erst DANN steht die Notiz, mit der richtigen Nummer."""
    sit = _sit()
    _zug(sit, "Die Rechnung ist falsch.")
    _zug(sit, "Ja.")
    _zug(sit, "Berger.")
    t = _zug(sit, "0151 2345678")
    assert "Stimmt das so?" in t
    t2 = _zug(sit, "Nein, die letzte war eine neun.")
    assert t2 == rechnung.NUMMER_NOCHMAL
    s = gehirn.sammler(sit)
    assert s["frage"] == "telefon" and s["telefonTeil"] == "" and s["telefonOffen"] == ""
    assert ohne_netz() == []
    t3 = _zug(sit, "0151 2345679")
    assert "Stimmt das so?" in t3 and "neun" in t3
    t4 = _zug(sit, "Ja.")
    assert t4.startswith(rechnung.NOTIERT)
    n = ohne_netz()
    assert len(n) == 1 and n[0]["telefon"] == "01512345679"


def test_nummer_unklar_zweimal_dann_ehrlich_ohne_nummer(ohne_netz):
    """Zwischenfrage auf die Nummern-Frage: deterministisch beantwortet und
    erneut erfragt; beim zweiten Mal ehrlich ohne sichere Nummer abschliessen
    — die Notiz traegt den Namen, nie eine geratene Nummer. Kein Modell."""
    sit = _sit()
    _zug(sit, "Ich habe eine Mahnung bekommen.")
    _zug(sit, "Ja, gerne.")
    _zug(sit, "Krause.")
    t = _zug(sit, "Wie lange dauert das denn?")
    assert t == rechnung.NUMMER_ZWISCHENFRAGE
    assert gehirn.sammler(sit)["frage"] == "telefon"
    t2 = _zug(sit, "Das weiß ich jetzt nicht.")
    assert t2.startswith(rechnung.NUMMER_UNSICHER) and rechnung.SONST_NOCH in t2
    assert _stand(sit) == "rueckruf"
    n = ohne_netz()
    assert len(n) == 1 and not n[0]["telefon"] and n[0]["name"].endswith("Krause")
    assert "nicht sicher erfasst" in n[0]["was"]
    assert "Kontaktdaten blieben unvollständig" in gedaechtnis.zusammenfassung(sit)


def test_nummer_dreimal_unklar_auf_readback_gibt_auf(ohne_netz):
    """Weder Ja noch Nein noch Ziffern auf das Readback: noch einmal vorlesen,
    nach drei Anlaeufen ehrlich aufgeben — keine Endlosschleife."""
    sit = _sit()
    _zug(sit, "Abrechnungsfehler.")
    _zug(sit, "Ja.")
    _zug(sit, "Vogel.")
    t = _zug(sit, "0170 1112233")
    assert "Stimmt das so?" in t
    t2 = _zug(sit, "Moment, ich suche gerade.")
    assert "Stimmt das so?" in t2
    t3 = _zug(sit, "Äh, wie bitte?")
    assert "Stimmt das so?" in t3
    t4 = _zug(sit, "Hm, weiß nicht.")
    assert t4.startswith(rechnung.NUMMER_UNSICHER)
    assert len(ohne_netz()) == 1 and not ohne_netz()[0]["telefon"]


def test_sonst_noch_ja_und_danach_termin(ohne_netz):
    """'Ja.' auf 'Kann ich sonst noch etwas fuer Sie tun?' -> 'Gerne — was
    kann ich noch fuer Sie tun?'; der Terminwunsch danach eroeffnet die
    Buchung. 'Ja, danke.' dagegen ist ein hoeflicher Abschluss."""
    sit = _sit()
    _zug(sit, "Meine Rechnung stimmt nicht.")
    _zug(sit, "Nein.")
    assert gehirn.sammler(sit)["frage"] == "sonst_noch"
    assert _zug(sit, "Ja.") == rechnung.SONST_NOCH_JA
    assert gehirn.sammler(sit)["frage"] == ""
    t = _zug(sit, "Ich brauche einen Termin zur Kontrolle.")
    assert "schon einmal bei uns" in t
    assert gehirn.sammler(sit)["modus"] == "buchen"

    sit2 = _sit()
    _zug(sit2, "Meine Rechnung stimmt nicht.")
    _zug(sit2, "Nein.")
    aus = agent.user_turn(sit2, "Ja, danke.")
    assert _s(aus.get("text")) == rechnung.SONST_NOCH_NEIN and aus.get("hangup") is True


def test_sonst_noch_rechnung_erneut_bleibt_deterministisch(ohne_netz):
    """Auf die Folgefrage kommt das Rechnungsthema noch einmal: kuerzere
    Erklaerung + Rueckruf-Frage (kein Modell), das Ja fuehrt zur Sammelei."""
    sit = _sit()
    _zug(sit, "Die Rechnung ist falsch.")
    _zug(sit, "Nein.")
    t = _zug(sit, "Aber die Rechnung ist wirklich falsch, da stimmt der Betrag nicht.")
    assert rechnung.ERKLAERUNG_WIEDERHOLT in t and rechnung.RUECKRUF_FRAGE_WIEDERHOLT in t
    assert _zug(sit, "Ja.") == rechnung.NAME_FRAGE


def test_rueckruf_direkt_verlangt_keine_frage(ohne_netz):
    """'Rufen Sie mich wegen der Rechnung zurueck' — die Frage entfaellt,
    Erklaerung + sofort der Name."""
    sit = _sit()
    t = _zug(sit, "Rufen Sie mich wegen der Rechnung zurück.")
    assert t.startswith(rechnung.ERKLAERUNG) and t.endswith(rechnung.NAME_FRAGE)
    assert rechnung.RUECKRUF_FRAGE not in t
    assert gehirn.sammler(sit)["frage"] == "name" and _stand(sit) == "rueckruf"


def test_nein_persoenlich_schliesst_ehrlich_ab(ohne_netz):
    sit = _sit()
    _zug(sit, "Die Rechnung ist fehlerhaft.")
    t = _zug(sit, "Nein danke, ich komme vorbei.")
    assert t.startswith(rechnung.ABGELEHNT) and "sonst noch etwas" in t
    assert _stand(sit) == "persoenlich"
    assert gehirn.sammler(sit)["frage"] == "sonst_noch"
    assert _hirn(sit) == [("ABGEBEN", "erledigt", True)]
    assert ohne_netz() == []
    assert "persönlich in der Praxis" in gedaechtnis.zusammenfassung(sit)


def test_nein_kurz_ohne_rueckruf(ohne_netz):
    sit = _sit()
    _zug(sit, "Meine Rechnung stimmt nicht.")
    t = _zug(sit, "Nein.")
    assert t.startswith(rechnung.ABGELEHNT)
    assert _stand(sit) == "abgelehnt" and ohne_netz() == []
    assert "kein Rückruf gewünscht" in gedaechtnis.zusammenfassung(sit)


def test_unklar_einmal_nachfragen_dann_gilt_nein(ohne_netz):
    """Kein Verhoer: eine Nachfrage, danach Nein — und kein Modell."""
    sit = _sit()
    _zug(sit, "Die Rechnung ist falsch.")
    t2 = _zug(sit, "Das ist doch eine Frechheit.")
    assert rechnung.RUECKRUF_UNKLAR in t2
    assert gehirn.sammler(sit)["frage"] == "rechnung_rueckruf"
    t3 = _zug(sit, "Was soll das denn.")
    assert t3.startswith(rechnung.ABGELEHNT)
    assert _stand(sit) == "abgelehnt" and gehirn.sammler(sit)["frage"] == ""
    assert rechnung.SONST_NOCH not in t3  # aufgegeben: kurz, ohne Folgefrage


def test_abschied_auf_die_frage_legt_auf_und_gilt_als_nein(ohne_netz):
    sit = _sit()
    _zug(sit, "Abrechnungsfehler.")
    aus = agent.user_turn(sit, "Nein danke, auf Wiederhören.")
    assert aus.get("hangup") is True
    assert _stand(sit) == "abgelehnt"
    assert gehirn.sammler(sit)["frage"] == ""


# --- Buchhaltung: Rechnungsthema, kein Durchstellen ---------------------------

def test_buchhaltung_ist_rechnungsthema_dann_arzt_namentlich_verbindet(ohne_netz):
    """'Kann ich mit der Buchhaltung sprechen?' -> Rechnungs-Erklaerung (nicht
    die Rollen-Erklaerung der Weiterleitung); 'Nein, verbinden Sie mich mit
    Doktor Patrikis' verneint die Frage UND verbindet (Jingle + transfer)."""
    sit = _sit()
    t1 = _zug(sit, "Kann ich mit der Buchhaltung sprechen?")
    assert rechnung.ERKLAERUNG in t1 and rechnung.RUECKRUF_FRAGE in t1
    assert weiterleiten.WAHRHEIT not in t1
    events: list[str] = []
    aus = agent.user_turn(sit, "Nein, verbinden Sie mich bitte mit Doktor Patrikis.",
                          melde=events.append)
    assert aus.get("transfer", {}).get("nummer") == "+4921130293034"
    assert aus.get("hangup") and weiterleiten.JINGLE_EVENT in events
    assert _stand(sit) == "abgelehnt"


def test_arzt_namentlich_mit_rechnung_bleibt_weiterleitung(ohne_netz):
    """'Ich moechte mit Doktor Petsas ueber die Rechnung sprechen' ist ein
    Verbinde-Wunsch — Jingle, keine Rechnungs-Erklaerung."""
    sit = _sit()
    events: list[str] = []
    aus = agent.user_turn(sit, "Ich möchte mit Doktor Petsas über die Rechnung sprechen.",
                          melde=events.append)
    assert aus.get("transfer", {}).get("nummer") == "+4921130293035"
    assert weiterleiten.JINGLE_EVENT in events
    assert not sit.get("rechnungStand")


# --- Mitten in der Buchung --------------------------------------------------

def _bis_arzt_frage(sit: dict) -> None:
    _zug(sit, "Ich hätte gern einen Termin zur Kontrolle.")
    t = _zug(sit, "Nein, ich war noch nie bei Ihnen.")
    assert gehirn.sammler(sit)["frage"] == "arzt", t


def test_in_der_buchung_nein_holt_die_buchung_zurueck(ohne_netz):
    sit = _sit()
    _bis_arzt_frage(sit)
    t = _zug(sit, "Ach, und die Rechnung von letztem Mal war falsch.")
    assert rechnung.ERKLAERUNG in t and rechnung.RUECKRUF_FRAGE in t
    assert _hirn(sit) == [("ANLEGEN", "geparkt", False), ("ABGEBEN", "aktiv", True)]
    s = gehirn.sammler(sit)
    assert s["frage"] == "rechnung_rueckruf" and s["modus"] == ""

    t2 = _zug(sit, "Nein.")
    assert t2.startswith(rechnung.ABGELEHNT_KURZ)
    assert "zurück zu Ihrem Termin" in t2 and "Behandler" in t2
    assert t2.count("?") == 1
    s = gehirn.sammler(sit)
    assert s["modus"] == "buchen" and s["frage"] == "arzt" and s["warSchonMal"] is False
    assert _hirn(sit) == [("ANLEGEN", "aktiv", False), ("ABGEBEN", "erledigt", True)]
    assert _stand(sit) == "abgelehnt"


def test_in_der_buchung_ja_kontakt_landet_im_checkpoint(ohne_netz):
    """Rueckruf mitten in der Buchung: Name + Nummer werden diktiert, die
    Notiz geschrieben, die Buchung kommt zurueck — und kennt den Namen schon."""
    sit = _sit()
    _bis_arzt_frage(sit)
    _zug(sit, "Die Rechnung war doppelt.")
    assert _zug(sit, "Ja.") == rechnung.NAME_FRAGE
    _zug(sit, "Schmidt.")
    _zug(sit, "Anna.")
    t = _zug(sit, "0170 9876543")
    assert "Stimmt das so?" in t and "zurück zu Ihrem Termin" not in t
    assert _hirn(sit) == [("ANLEGEN", "geparkt", False), ("ABGEBEN", "aktiv", True)]
    t = _zug(sit, "Ja.")
    assert t.startswith(rechnung.NOTIERT) and "zurück zu Ihrem Termin" in t and "Behandler" in t
    assert rechnung.SONST_NOCH not in t  # der Ruecksprung stellt die Frage
    s = gehirn.sammler(sit)
    assert s["modus"] == "buchen" and s["frage"] == "arzt"
    assert s["nachname"] == "Schmidt" and s["vorname"] == "Anna"
    assert s["telefonBekannt"] == "01709876543" and not s["telefon"]
    assert _stand(sit) == "notiert"
    assert _hirn(sit) == [("ANLEGEN", "aktiv", False), ("ABGEBEN", "erledigt", True)]
    n = ohne_netz()
    assert len(n) == 1 and n[0]["telefon"] == "01709876543" and "Rechnung" in n[0]["was"]


def test_nein_wann_haben_sie_geoeffnet_holt_die_buchung_sofort(ohne_netz):
    """Verneinung + Praxisfrage im selben Satz: Oeffnungszeiten UND die
    offene Buchungsfrage — nicht noch einmal die Rueckruf-Frage."""
    sit = _sit()
    _zug(sit, "Ich hätte gern einen Termin zur Kontrolle.")
    _zug(sit, "Ja, ich war schon mal da.")
    _zug(sit, "Ich habe da eine Frage zur Rechnung.")
    t = _zug(sit, "Nein, wann haben Sie geöffnet?")
    assert "Öffnungszeiten" in t and "Behandler" in t
    assert rechnung.RUECKRUF_FRAGE not in t and "Rückruf" not in t
    s = gehirn.sammler(sit)
    assert s["modus"] == "buchen" and s["frage"] == "arzt"
    assert _stand(sit) == "abgelehnt"


def test_nein_aber_termin_eroeffnet_die_buchung(ohne_netz):
    sit = _sit()
    _zug(sit, "Meine Rechnung stimmt nicht.")
    t = _zug(sit, "Nein, aber ich brauche noch einen Termin zur Kontrolle.")
    assert "schon einmal bei uns" in t
    s = gehirn.sammler(sit)
    assert s["modus"] == "buchen" and s["frage"] == "schonmal"
    assert _stand(sit) == "abgelehnt"
    assert ("ANLEGEN", "aktiv", False) in _hirn(sit)


def test_nach_der_notiz_noch_ein_termin(ohne_netz):
    sit = _sit()
    _zug(sit, "Ich habe eine Mahnung bekommen, obwohl ich bezahlt habe.")
    _zug(sit, "Ja.")
    _zug(sit, "Krause.")
    _zug(sit, "0160 1112233")
    _zug(sit, "Ja, stimmt.")
    assert _stand(sit) == "notiert"
    assert gehirn.sammler(sit)["frage"] == "sonst_noch"
    t = _zug(sit, "Ich brauche aber auch noch einen Termin zur Kontrolle.")
    assert "schon einmal bei uns" in t
    s = gehirn.sammler(sit)
    assert s["modus"] == "buchen" and s["frage"] == "schonmal"


# --- Erneut / doppelt -------------------------------------------------------

def test_erneut_nach_ablehnung_fragt_kuerzer_und_nimmt_ja(ohne_netz):
    sit = _sit()
    _zug(sit, "Die Rechnung ist falsch.")
    _zug(sit, "Nein.")
    t = _zug(sit, "Ich will aber über die Rechnung reden, da ist ein Fehler drin.")
    assert rechnung.ERKLAERUNG_WIEDERHOLT in t and rechnung.RUECKRUF_FRAGE_WIEDERHOLT in t
    assert rechnung.ERKLAERUNG not in t
    assert _stand(sit) == "offen" and gehirn.sammler(sit)["frage"] == "rechnung_rueckruf"
    assert _zug(sit, "Ja, gut.") == rechnung.NAME_FRAGE
    assert _stand(sit) == "rueckruf"


def test_erneut_nach_notiz_keine_zweite_sammelei(ohne_netz):
    sit = _sit()
    _zug(sit, "Rufen Sie mich wegen der Rechnung zurück.")
    _zug(sit, "Meier.")
    _zug(sit, "0171 2223344")
    _zug(sit, "Ja.")
    assert _stand(sit) == "notiert" and len(ohne_netz()) == 1
    t = _zug(sit, "Und was ist jetzt mit der Rechnung?")
    assert "schon notiert" in t and "meldet sich" in t
    assert rechnung.RUECKRUF_FRAGE not in t and rechnung.NAME_FRAGE not in t
    assert _stand(sit) == "notiert" and len(ohne_netz()) == 1
    assert gehirn.sammler(sit)["frage"] == "sonst_noch"
    assert not (sit.get("hirnAbgeben") or {}).get("offen")
    aus = agent.user_turn(sit, "Okay, danke.")
    assert aus.get("hangup") is True


# --- Diktat-Sicherheit --------------------------------------------------------

def test_rechnungshofer_ist_ein_nachname(ohne_netz):
    sit = _sit()
    _zug(sit, "Ich hätte gern einen Termin zur Kontrolle.")
    _zug(sit, "Nein, noch nie.")
    _zug(sit, "Petsas.")
    _zug(sit, "Nein.")
    _zug(sit, "Egal.")
    assert gehirn.sammler(sit)["frage"] == "buchstabieren"
    t = _zug(sit, "Rechnungshofer.")
    assert "Rechnungshofer" in t and "Vorname" in t
    assert rechnung.ERKLAERUNG not in t
    s = gehirn.sammler(sit)
    assert s["nachname"] == "Rechnungshofer" and s["frage"] == "vorname"
    assert not sit.get("rechnungStand")


def test_rechnungsfrage_mitten_im_nummern_diktat_raeumt_nichts(ohne_netz):
    """Waehrend die Nummer diktiert wird, oeffnet 'Frage zur Rechnung' kein
    Thema — die Nummern-Frage bleibt, das Fragment bleibt."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "telefon", "telefonTeil": "0171",
              "nachname": "Berger", "vorname": "Julia", "buchstabiert": True})
    assert flow._rechnung_zug(sit, "Ich habe da noch eine Frage zur Rechnung.") is None
    assert s["frage"] == "telefon" and s["telefonTeil"] == "0171"
    assert not sit.get("rechnungStand")


# --- Wache am LLM-Ausgang -----------------------------------------------------

@pytest.mark.parametrize("satz", [
    "Ihre Rechnung über 240 Euro ist noch offen.",
    "Die Rechnung wurde bereits bezahlt, alles gut.",
    "Ich kümmere mich um die Rechnung.",
    "Ich prüfe die Abrechnung und melde mich.",
])
def test_wache_streicht_rechnungs_behauptungen(satz):
    neu, weg = rechnung.saeubern(satz)
    assert weg == [satz]
    assert neu == rechnung.WACHE_ERSATZ


@pytest.mark.parametrize("satz", [
    "Rechnungsthemen klärt die Praxis persönlich vor Ort. Soll ich einen Rückruf einrichten?",
    "Über Rechnungen darf ich leider keine Auskunft geben.",
    "Die Zahnreinigung kostet ungefähr 120 Euro.",
    "Das Bleaching kostet 350 Euro zusätzlich.",
    "Das kann ich am Telefon leider nicht klären.",
])
def test_wache_laesst_verweis_grenze_und_preise_stehen(satz):
    assert rechnung.saeubern(satz) == (satz, [])


def test_wache_mischsatz_behaelt_den_verweis():
    text = ("Ihre Rechnung über 240 Euro ist noch offen. "
            "Rechnungsfragen klärt die Praxis persönlich vor Ort.")
    neu, weg = rechnung.saeubern(text)
    assert weg == ["Ihre Rechnung über 240 Euro ist noch offen."]
    assert neu == "Rechnungsfragen klärt die Praxis persönlich vor Ort."


def test_agent_wache_enforce_shadow_off(monkeypatch):
    sit = _sit()
    satz = "Die Rechnung wurde bereits bezahlt."
    monkeypatch.setenv("RECHNUNG_WACHE", "enforce")
    assert agent._rechnung_wache_anwenden(sit, satz) == rechnung.WACHE_ERSATZ
    monkeypatch.setenv("RECHNUNG_WACHE", "shadow")
    assert agent._rechnung_wache_anwenden(sit, satz) == satz
    monkeypatch.setenv("RECHNUNG_WACHE", "off")
    assert agent._rechnung_wache_anwenden(sit, satz) == satz


# --- Report -----------------------------------------------------------------

def test_report_zeilen_je_stand():
    sit = {"rechnungStand": {"status": "notiert", "was": "Die Rechnung ist falsch."}}
    assert "Rückruf dazu notiert" in rechnung.zusammenfassung_zeile(sit)
    sit["rechnungStand"]["status"] = "abgelehnt"
    assert "kein Rückruf gewünscht" in rechnung.zusammenfassung_zeile(sit)
    sit["rechnungStand"]["status"] = "persoenlich"
    assert "persönlich in der Praxis" in rechnung.zusammenfassung_zeile(sit)
    sit["rechnungStand"]["status"] = "rueckruf"
    assert "unvollständig" in rechnung.zusammenfassung_zeile(sit)
    assert rechnung.zusammenfassung_zeile({}) == ""
    assert rechnung.zusammenfassung_zeile(None) == ""


def test_feste_saetze_vorgewaermt():
    saetze = gehirn.feste_saetze(laden("meddent"))
    for satz in rechnung.SAETZE:
        assert satz in saetze, satz
