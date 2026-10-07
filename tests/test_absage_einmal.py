"""W-ABSAGE-EINMAL + W-KEIN-RESUME-NACH-FEHLER (07.10.2026, Blessing-Anruf
9fc1f105): die Plattform lehnte die Absage dreimal mit „Appointment cannot be
canceled (not confirmed or already processed)“ ab. Bianca versuchte dieselbe
Termin-ID erneut, sagte dreimal „Die Praxis kümmert sich darum.“ und sprang
nach jedem Fehlschlag per Auto-Resume in „Bei welchem Behandler …“ zurück.

Offline, kein Netz, kein LLM.
"""

import pytest

from bianca import agent, gehirn, verwalten
from kern import hirn
from kern.tenants import laden

_LIVE_FEHLER = {
    "ok": False,
    "dispatch": {"status": 400, "body": {
        "status": "error",
        "message": "Appointment cannot be canceled (not confirmed or already processed)",
    }},
}
_TERMIN = {"id": "apt-9fc1", "spoken": "am Donnerstag, dem 15. Oktober um 10:30 Uhr",
           "iso": "2026-10-15T10:30", "patientLastName": "Berger",
           "patientFirstName": "Anna"}


def _deutung(handlung, *, ersatz=None, spiegel=""):
    return {"kanal": "ok", "zug": "wechseln", "handlung": handlung,
            "gegenstand": "VORGANG", "fuer": "selbst", "ersatz": ersatz,
            "spiegel": spiegel}


def _sit():
    sit = {"stimme": "Bianca", "tenant": laden("meddent"),
           "messages": [{"role": "system", "content": "x"}]}
    hirn.init(sit)
    # Live: „Ich möchte meinen Termin“ (Halbsatz) -> ANLEGEN, dann „Stornieren.“
    hirn.anwenden(sit, _deutung("ANLEGEN", spiegel="Termin"))
    sit["sammler"].update({"frage": "arzt"})
    hirn.anwenden(sit, _deutung("AENDERN", ersatz=False, spiegel="Termin stornieren"))
    s = gehirn.sammler(sit)
    s.update({"nachname": "Berger", "vorname": "Anna", "phase": "absage_bestaetigen",
              "frage": "absage_ok"})
    sit["gefunden"] = [dict(_TERMIN)]
    sit["verwaltenTermin"] = _TERMIN["id"]
    return sit


@pytest.fixture
def cf(monkeypatch):
    aufrufe = []

    def cancel(tenant, ctx, tid):
        aufrufe.append(tid)
        return dict(cf.antwort)

    cf.antwort = dict(_LIVE_FEHLER)
    monkeypatch.setattr(verwalten.kal, "cancel_by_id", cancel)
    monkeypatch.setattr(verwalten, "_notiz_schreiben", lambda sit, **kw: cf.notiz)
    cf.notiz = True
    monkeypatch.delenv("ABSAGE_EINMAL", raising=False)
    monkeypatch.delenv("RESUME_NACH_FEHLER", raising=False)
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    cf.aufrufe = aufrufe
    return cf


def test_unbestaetigter_termin_ehrlich_statt_kuemmert_sich(cf):
    sit = _sit()
    fl = verwalten._absagen(sit, None)
    assert cf.aufrufe == ["apt-9fc1"]
    assert "noch nicht bestätigt" in fl["text"]
    assert "kümmert sich" not in fl["text"]
    assert fl["text"].endswith("Kann ich sonst noch etwas für Sie tun?")
    assert gehirn.sammler(sit)["frage"] == "sonst_noch"


def test_zweiter_versuch_geht_nie_mehr_an_die_plattform(cf):
    sit = _sit()
    verwalten._absagen(sit, None)
    fl = verwalten._absagen(sit, None)
    assert cf.aufrufe == ["apt-9fc1"]
    assert "bereits für die Praxis notiert" in fl["text"]


def test_absage_frage_fuer_gescheiterte_id_fragt_nicht_erneut(cf):
    sit = _sit()
    verwalten._absagen(sit, None)
    fl = verwalten._absage_frage(sit, dict(_TERMIN))
    assert "wirklich absagen" not in fl["text"]
    assert "bereits für die Praxis notiert" in fl["text"]
    assert gehirn.sammler(sit)["phase"] == "fertig"


def test_ohne_notiz_kein_notiert_versprechen(cf):
    cf.notiz = False
    sit = _sit()
    verwalten._absagen(sit, None)
    fl = verwalten._absagen(sit, None)
    assert cf.aufrufe == ["apt-9fc1"]
    assert "notiert" not in fl["text"]
    assert "nicht absagen" in fl["text"]


def test_anderer_fehler_behaelt_alten_text(cf):
    cf.antwort = {"ok": False, "dispatch": {"status": 500, "body": "boom"}}
    sit = _sit()
    fl = verwalten._absagen(sit, None)
    assert "noch nicht bestätigt" not in fl["text"]


def test_erfolg_unveraendert(cf):
    cf.antwort = {"ok": True, "spoken": "x"}
    sit = _sit()
    fl = verwalten._absagen(sit, None)
    assert fl["text"].startswith("Erledigt — der Termin")
    assert fl["book"]["cancelled"] is True
    assert "schreibFehlerZug" not in sit


def test_andere_id_wird_weiter_abgesagt(cf):
    sit = _sit()
    verwalten._absagen(sit, None)
    zweiter = dict(_TERMIN, id="apt-anders")
    sit["gefunden"].append(zweiter)
    sit["verwaltenTermin"] = "apt-anders"
    verwalten._absagen(sit, None)
    assert cf.aufrufe == ["apt-9fc1", "apt-anders"]


def test_notaus_absage_einmal(cf, monkeypatch):
    monkeypatch.setenv("ABSAGE_EINMAL", "0")
    sit = _sit()
    fl = verwalten._absagen(sit, None)
    verwalten._absagen(sit, None)
    assert cf.aufrufe == ["apt-9fc1", "apt-9fc1"]
    assert "noch nicht bestätigt" not in fl["text"]


# --- W-KEIN-RESUME-NACH-FEHLER ------------------------------------------------

def test_kein_auto_resume_nach_gescheiterter_absage(cf):
    sit = _sit()
    fl = verwalten._absagen(sit, None)
    aus = agent._auto_resume_anhaengen(sit, fl)
    assert "zurück zu Ihrem Termin" not in aus["text"]
    assert "Behandler" not in aus["text"]
    assert sit["sammler"]["frage"] == "sonst_noch"
    # Auch der Folgezug (Hirn-Abgleich + Abschluss-Prüfung) holt die
    # geparkte Buchung nicht still zurück.
    hirn.sync_nach_zug(sit)
    assert hirn.wuerde_zuruecksprigen(sit) is None
    assert hirn.abschluss_ruecksprung_live(sit) is None
    ruhend = [a for a in sit["hirn"]["anliegen"] if a["status"] == "ruhend"]
    assert ruhend and ruhend[0]["handlung"] == "ANLEGEN"


def test_auto_resume_ohne_schreibfehler_unveraendert(cf):
    cf.antwort = {"ok": True, "spoken": "x"}
    sit = _sit()
    sit["sammler"]["phase"] = "fertig"
    aus = agent._auto_resume_anhaengen(sit, {"text": "Der Termin ist abgesagt.", "book": None})
    assert "zurück zu ihrem termin" in aus["text"].lower()


def test_neuer_wunsch_nach_fehler_legt_frisches_anliegen_an(cf):
    sit = _sit()
    fl = verwalten._absagen(sit, None)
    agent._auto_resume_anhaengen(sit, fl)
    hirn.anwenden(sit, _deutung("ANLEGEN", spiegel="neuen Termin"))
    assert sit["sammler"]["modus"] == "buchen"
    assert hirn.aktiv(sit)["handlung"] == "ANLEGEN"


def test_notaus_resume_nach_fehler(cf, monkeypatch):
    monkeypatch.setenv("RESUME_NACH_FEHLER", "1")
    sit = _sit()
    fl = verwalten._absagen(sit, None)
    aus = agent._auto_resume_anhaengen(sit, fl)
    assert "zurück zu ihrem termin" in aus["text"].lower()


def test_schreibfehler_flag_gilt_nur_fuer_den_zug(cf, monkeypatch):
    class _Halt(Exception):
        pass

    def halt(sit):
        raise _Halt

    sit = _sit()
    sit["schreibFehlerZug"] = True
    monkeypatch.setattr(agent, "_tote_identitaetsfrage_raeumen", halt)
    with pytest.raises(_Halt):
        agent.user_turn(sit, "Hallo")
    assert "schreibFehlerZug" not in sit
