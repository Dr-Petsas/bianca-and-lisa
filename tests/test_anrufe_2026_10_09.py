"""Intent-Regressionen aus den Live-Anrufen vom 09.10.2026.

Nach den Verwaltungs-Fixes vom 08.10.2026 (Stufe 3a: termin_ok wiederholt die
Folgefrage statt abzugeben) bekamen Anrufer auf Rückfragen zum GEFUNDENEN
Termin nur noch das Menü „so lassen, verschieben oder absagen?“. Dazu alte,
jetzt sichtbar gewordene Lücken: verneinte Änderungs- und Buchungswünsche,
offener Dokument-Zweig.

- 09d33a45 (Blessing): „Ja, um wie viel Uhr?“ / „nicht verschieben, nicht
  absagen, sondern ich will kommen“.
- 65c04df1 (Blessing): „keine Vorschläge … bekommen“, „keine E-Mails“,
  „keinen neuen Termin ausmachen“.
- b4dba8bf (Blessing): Rezept -> „Kann ich einen Termin vereinbaren?“.
"""
from __future__ import annotations

import json

import pytest

from bianca import agent, flow, gehirn, verwalten
from kern import hirn, intent, meta_bitten, praxisregeln
from kern.tenants import laden

DEZ = {
    "ok": True,
    "patient": {"id": "pat-h", "firstName": "Ingrid", "lastName": "Hösl"},
    "appointments": [{
        "id": "apt-dez", "iso": "2026-12-21T10:00", "date": "2026-12-21",
        "calendarId": "cal-fs", "doctorName": "Franziska Schmidt",
        "motivId": "vm-pzr",
        "motivName": "Professionelle Zahnreinigung (PZR) + Vorsorge",
        "spoken": "am Montag, den einundzwanzigsten Dezember um zehn Uhr bei Franziska Schmidt",
    }],
}
MENUE = "so lassen, verschieben oder absagen"


def _sit(tenant: str = "meddent") -> dict:
    sit = {"tenant": laden(tenant),
           "messages": [{"role": "system", "content": "x"}],
           "stimme": "bianca"}
    hirn.init(sit)
    sit["anrufer"] = {"vorname": "Ingrid", "nachname": "Hösl",
                      "patientId": "pat-h", "geschlecht": "female",
                      "telefon": "+491701234567"}
    return sit


@pytest.fixture
def ohne_netz(monkeypatch, tmp_path):
    from kern import llm

    def _knall(*a, **k):
        raise AssertionError("LLM darf hier nicht laufen")

    def _keine_slots(*a, **k):
        raise AssertionError("keine Slotsuche — der Termin bleibt")

    monkeypatch.setattr(llm, "chat", _knall)
    monkeypatch.setattr(llm, "chat_stream", _knall)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    monkeypatch.setattr(verwalten.hintergrund, "anstossen", lambda sit: None)
    monkeypatch.setattr(verwalten.kal, "find_patient_appointments",
                        lambda t, c: json.loads(json.dumps(DEZ)))
    monkeypatch.setattr(verwalten.kal, "find_slots_behandler", _keine_slots)
    monkeypatch.setattr(verwalten, "DATA_DIR", tmp_path)
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    yield tmp_path


def _zug(sit: dict, satz: str) -> dict:
    aus = agent.user_turn(sit, satz)
    assert aus is not None, satz
    return aus


def _gefunden(sit: dict) -> None:
    _zug(sit, "Habe ich da einen Termin?")
    assert gehirn.sammler(sit)["frage"] == "termin_ok"


# --- termin_ok: Rückfragen zum gefundenen Termin (09d33a45) -------------------

def test_um_wie_viel_uhr_nennt_den_termin_statt_menue(ohne_netz):
    sit = _sit()
    _gefunden(sit)
    aus = _zug(sit, "Ja, um wie viel Uhr?")
    assert "einundzwanzigsten Dezember um zehn Uhr" in aus["text"]
    assert MENUE not in aus["text"]
    assert gehirn.sammler(sit)["frage"] == "termin_ok"


def test_nicht_verschieben_nicht_absagen_sondern_kommen(ohne_netz):
    sit = _sit()
    _gefunden(sit)
    aus = _zug(sit, (
        "Nein, ich möchte ihn nicht verschieben, nicht absagen, sondern ich "
        "will kommen, aber um wie viel Uhr soll ich kommen? Am 19.10."))
    s = gehirn.sammler(sit)
    assert s["modus"] == "auskunft", "kein Verschiebe-Dialog"
    assert "einundzwanzigsten Dezember um zehn Uhr" in aus["text"]
    assert "bleibt es dabei" in aus["text"]
    assert s["frage"] == "sonst_noch"


def test_kommen_wollen_aber_uhrzeit_vergessen(ohne_netz):
    sit = _sit()
    _gefunden(sit)
    aus = _zug(sit, "Nein, ich möchte kommen, aber ich weiss nicht mehr, "
                    "um wie viel Uhr der Termin war.")
    assert "um zehn Uhr" in aus["text"]
    assert MENUE not in aus["text"]


def test_menue_nur_bei_kurzer_unklarer_antwort(ohne_netz):
    sit = _sit()
    _gefunden(sit)
    aus = _zug(sit, "Hm, äh.")
    assert MENUE in aus["text"]


def test_echter_verschiebewunsch_bleibt_verschieben(monkeypatch, ohne_netz):
    monkeypatch.setattr(verwalten.kal, "find_slots_behandler", lambda *a, **k: {
        "ok": True, "slots": ["2027-01-04T09:00:00+01:00"]})
    sit = _sit()
    _gefunden(sit)
    _zug(sit, "Ich möchte ihn nicht absagen, sondern verschieben.")
    assert gehirn.sammler(sit)["modus"] == "verschieben"


# --- Verneinte Änderungsverben in der Intent-Schicht -------------------------

def test_intent_verneintes_aendern_ist_kein_auftrag():
    satz = ("Nein, ich möchte ihn nicht verschieben, nicht absagen, sondern "
            "ich will kommen, aber um wie viel Uhr soll ich kommen? Am 19.10.")
    assert not intent._ist_verschieben(None, satz)
    assert not intent._ist_absage(satz)


def test_verhoerer_regex_trifft_nicht_die_richtige_schreibweise():
    assert not verwalten._VERHOERER_AENDERN_RE.search("nicht verschieben")
    assert verwalten._VERHOERER_AENDERN_RE.search("Ja, verscheiben.")
    assert verwalten._VERHOERER_AENDERN_RE.search("ver schieben bitte")


def test_intent_aendern_gegenproben():
    assert intent._ist_verschieben(None, "Ich möchte den Termin nicht absagen, sondern verschieben.")
    assert not intent._ist_absage("Ich möchte den Termin nicht absagen, sondern verschieben.")
    assert intent._ist_verschieben(None, "Kann man den nicht verschieben?")
    assert intent._ist_absage("Ich kann den Termin nicht wahrnehmen.")
    assert intent._ist_absage("Ich möchte meinen Termin absagen.")


# --- Verneinte Neubuchung (65c04df1) -----------------------------------------

@pytest.mark.parametrize("satz", [
    "Nein, der Termin passt so, ich möchte nur keine Vorschläge zu alternativen Terminen bekommen.",
    "Nein, ich möchte keinen neuen Termin ausmachen.",
])
def test_verneinte_neubuchung_ist_kein_terminwunsch(satz):
    assert not intent.neu_wunsch(satz)
    sit = _sit("blessing")
    res = intent.erkennen(sit, satz)
    assert res.get("handlung") != "ANLEGEN", (satz, res)


@pytest.mark.parametrize("satz", [
    "Ich kann nicht am Montag, ich brauche einen Termin am Dienstag.",
    "Ich brauche einen Termin.",
    "Dringender Termin.",
    "Neuer Termin.",
    "Einen Termin bitte.",
])
def test_neubuchung_gegenproben(satz):
    assert intent.neu_wunsch(satz), satz


def test_kein_neuer_termin_ist_abbruch():
    assert meta_bitten.deute("Nein, ich möchte keinen neuen Termin ausmachen.") == meta_bitten.ABBRECHEN
    assert meta_bitten.deute("Ich brauche keinen Termin mehr.") == meta_bitten.ABBRECHEN


@pytest.mark.parametrize("satz", [
    "Ich möchte keinen anderen Termin.",
    "Ich brauche keinen Termin, ich habe nur eine Frage.",
    "Ich möchte keinen neuen Termin, sondern meinen verschieben.",
    "Ich habe keinen Termin.",
])
def test_kein_termin_gegenproben_kein_abbruch(satz):
    assert meta_bitten.deute(satz) != meta_bitten.ABBRECHEN, satz


def test_keine_vorschlaege_schreibt_notiz_und_termin_bleibt(ohne_netz):
    sit = _sit("blessing")
    _gefunden(sit)
    aus = _zug(sit, "Nein, der Termin passt so, ich möchte nur keine Vorschläge "
                    "zu alternativen Terminen bekommen.")
    assert "notiert" in aus["text"]
    assert "bleibt bestehen" in aus["text"]
    zeilen = (ohne_netz / "praxis_notizen.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(z)["anliegen"] == "benachrichtigung" for z in zeilen)
    assert gehirn.sammler(sit)["modus"] != "buchen"


def test_keine_emails_auf_sonst_noch(ohne_netz):
    sit = _sit("blessing")
    _gefunden(sit)
    _zug(sit, "Alles gut.")
    assert gehirn.sammler(sit)["frage"] == "sonst_noch"
    aus = _zug(sit, "Nein, ich möchte keine E-Mails bekommen.")
    assert "notiert" in aus["text"]
    assert gehirn.sammler(sit)["modus"] != "buchen"


def test_keine_erinnerung_bekommen_ist_kein_opt_out():
    assert not verwalten._KEINE_NACHRICHT_RE.search("Ich habe keine Erinnerung bekommen.")
    assert verwalten._KEINE_NACHRICHT_RE.search("Ich möchte keine E-Mails bekommen.")


def test_kein_neuer_termin_startet_keine_buchung(ohne_netz):
    sit = _sit("blessing")
    _gefunden(sit)
    _zug(sit, "Alles gut.")
    aus = _zug(sit, "Nein, ich möchte keinen neuen Termin ausmachen.")
    s = gehirn.sammler(sit)
    assert s["modus"] != "buchen"
    assert "Termin" not in (s.get("frage") or "")
    assert "?" in aus["text"] or aus.get("hangup")


# --- Bestandsfrage (Blessing 09.10.2026) --------------------------------------

def test_wann_ich_einen_termin_habe_ist_bestandsfrage():
    satz = ("Ich möchte wissen, wann ich einen Termin bei Frau Doktor "
            "Blessing habe, am neunzehnten oder am 16.")
    assert intent._BESTANDSFRAGE_RE.search(satz)


@pytest.mark.parametrize("satz", [
    "Wann ich einen Termin haben kann, ist mir egal.",
    "Ich möchte wissen, ob noch ein Termin zur Verfügung steht.",
    "Ich möchte wissen, wann ich einen Termin bekommen kann.",
])
def test_bestandsfrage_gegenproben(satz):
    assert not intent._BESTANDSFRAGE_RE.search(satz), satz


def test_ob_mein_termin_noch_steht_bleibt_bestandsfrage():
    assert intent._BESTANDSFRAGE_RE.search("Ich wollte fragen, ob mein Termin noch steht.")


# --- Dokument-Zweig schließt (b4dba8bf) ---------------------------------------

def test_rezept_dann_termin_startet_buchung(ohne_netz):
    t = laden("blessing")
    t["dbPrompt"] = (t.get("dbPrompt") or "") + f"\n- {praxisregeln.DOKUMENT_MARKER}: nur persönlich.\n"
    sit = {"tenant": t, "messages": [{"role": "system", "content": "x"}], "stimme": "bianca"}
    hirn.init(sit)
    sit["anrufer"] = {"vorname": "Isabell", "nachname": "Grübl", "patientId": "p1",
                      "geschlecht": "female", "telefon": "+491701234567"}
    aus = _zug(sit, "Ich benötige ein Rezept für eine Korrektionscreme.")
    assert "persönlich" in aus["text"]
    aus = _zug(sit, "Kann ich einen Termin vereinbaren?")
    assert "abholen" not in aus["text"]
    assert gehirn.sammler(sit)["modus"] == "buchen"
    assert "?" in aus["text"]


def test_uhrzeit_unbekannt_wort_erkannt():
    satz = ("Ich habe, glaube ich, am 19.10. einen Termin zur Abtragung an der "
            "Nase, aber ich habe es mir vergessen, aufzuschreiben, und ich bin "
            "nicht sicher, um wie viel Uhr es war.")
    assert verwalten._UNKLAR_RE.search(satz)
    assert verwalten._UHRZEIT_WORT_RE.search(satz)
