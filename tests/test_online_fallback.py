"""W-ONLINE-FALLBACK (26.09.2026): Online-Buchungslink nach Namens-Fails.

Die Gegenproben (kein Handy, kein Buchungsmodus, schon gesendet) sind der
teurere Teil — ein falsch ausgeloester Link waere ein Fehlverhalten.
"""

import pytest

from bianca import agent
from kern import namenslink, online_fallback


@pytest.fixture(autouse=True)
def _namens_sms_aus(monkeypatch):
    """W-NAMENS-SMS-VORRANG (01.10.2026): Die Namens-SMS (agentNameConfirm
    create) hat jetzt Vorrang vor dem Online-Buchungslink. Diese Datei prüft
    die Online-Link-Mechanik als LETZTEN Ausweg — also für den Fall, dass die
    Namens-SMS NICHT starten kann. Der Vorrang selbst wird im eigenen Test
    unten geprüft (dort wird die Fixture überschrieben)."""
    monkeypatch.setattr(namenslink, "starten", lambda *a, **k: None)


def _sit(**extra):
    sit = {
        "id": "sess-online-1",
        "tenant": {"clientId": "C1", "locationId": "L1", "_testNoWrite": True},
        "sammler": {"modus": "buchen"},
        "anrufer": {"telefon": "+491771234567"},
    }
    sit.update(extra)
    return sit


def test_greift_bei_buchung_mit_erkanntem_handy():
    sit = _sit()
    assert online_fallback.erkannte_handy(sit)
    assert online_fallback.greift(sit, "nachname") is True
    assert online_fallback.greift(sit, "buchstabieren") is True


def test_greift_nicht_ohne_erkannte_nummer():
    sit = _sit(anrufer={})
    assert online_fallback.erkannte_handy(sit) == ""
    assert online_fallback.greift(sit, "nachname") is False


def test_diktierte_oder_aktennummer_ohne_caller_id_reicht_nicht():
    sit = _sit(
        anrufer={},
        sammler={
            "modus": "buchen",
            "telefon": "+491771234567",
            "telefonOk": True,
            "telefonBekannt": "+491771234567",
            "kontaktTelefon": "+491771234567",
        },
    )
    assert online_fallback.erkannte_handy(sit) == ""
    assert online_fallback.greift(sit, "nachname") is False


def test_greift_nicht_bei_festnetz():
    sit = _sit(anrufer={"telefon": "+4921112345"})
    assert online_fallback.greift(sit, "nachname") is False


def test_greift_nicht_ausserhalb_buchung():
    sit = _sit(sammler={"modus": "absagen"})
    assert online_fallback.greift(sit, "nachname") is False


def test_greift_nicht_bei_fremdem_feld():
    sit = _sit()
    assert online_fallback.greift(sit, "telefon") is False
    assert online_fallback.greift(sit, "versicherung") is False


def test_greift_nicht_wenn_schon_gesendet():
    sit = _sit(onlineBuchungslink={"ok": True})
    assert online_fallback.greift(sit, "nachname") is False


def test_greift_nicht_bei_notaus(monkeypatch):
    monkeypatch.setenv("ONLINE_FALLBACK", "0")
    sit = _sit()
    assert online_fallback.greift(sit, "nachname") is False


def test_budget_bietet_nur_an_und_sendet_noch_nicht(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(
        online_fallback,
        "_cf_call",
        lambda *args, **kwargs: aufrufe.append((args, kwargs)),
    )
    sit = _sit()

    aus = agent._frage_budget_ausstieg(sit, fid="nachname")

    assert aus["zustimmung"] is True
    assert "Soll ich Ihnen" in aus["text"]
    assert "Leitungsprobleme" in aus["text"]
    assert online_fallback.zustimmung_offen(sit)
    assert sit["sammler"]["frage"] == "online_fallback"
    assert not sit.get("frageBudgetDone")
    assert aufrufe == []


def test_online_fallback_erst_nach_drei_namensversuchen(monkeypatch):
    """Drei echte Fragen bleiben beim Namen; erst die vierte wird ersetzt."""
    aufrufe = []
    monkeypatch.setattr(
        online_fallback,
        "_cf_call",
        lambda *args, **kwargs: aufrufe.append((args, kwargs)),
    )
    sit = _sit()
    sit["sammler"]["frage"] = "nachname"
    frage = "Wie lautet Ihr Nachname?"

    for versuch in range(1, 4):
        aus = agent._frage_budget_pruefen(sit, frage)
        assert aus is None
        assert sit["frageBudget"]["versuche"] == versuch
        assert not online_fallback.zustimmung_offen(sit)
        assert aufrufe == []

    aus = agent._frage_budget_pruefen(sit, frage)
    assert aus is not None
    assert aus["zustimmung"] is True
    assert online_fallback.zustimmung_offen(sit)
    assert sit["frageBudget"]["versuche"] == 3
    assert aufrufe == []


def test_klares_ja_sendet_danach_und_beendet(monkeypatch):
    aufrufe = []

    def _cf(name, body):
        aufrufe.append((name, body))
        return 200, {
            "status": "ok",
            "sent": True,
            "url": "https://pickadoc.de/profile/C1/L1",
        }, {}

    monkeypatch.setattr(online_fallback, "_cf_call", _cf)
    sit = _sit()
    agent._frage_budget_ausstieg(sit, fid="nachname")

    aus = agent._online_fallback_antwort(sit, "Ja, bitte.")

    assert len(aufrufe) == 1
    assert aufrufe[0][1]["action"] == "booking-link"
    assert aus["hangup"] is True
    assert "geschickt" in aus["text"]
    assert sit["frageBudgetDone"] is True
    assert sit["sammler"]["frage"] == ""
    assert sit["onlineBuchungslink"]["url"].endswith("/C1/L1")


def test_nein_sendet_nichts_und_beendet(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(
        online_fallback,
        "_cf_call",
        lambda *args, **kwargs: aufrufe.append((args, kwargs)),
    )
    sit = _sit()
    agent._frage_budget_ausstieg(sit, fid="nachname")

    aus = agent._online_fallback_antwort(sit, "Nein, danke.")

    assert aufrufe == []
    assert aus["hangup"] is True
    assert "keine SMS" in aus["text"]
    assert sit["onlineFallback"]["status"] == "abgelehnt"


def test_unklare_zustimmung_fragt_einmal_nach_und_sendet_nie(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(
        online_fallback,
        "_cf_call",
        lambda *args, **kwargs: aufrufe.append((args, kwargs)),
    )
    sit = _sit()
    agent._frage_budget_ausstieg(sit, fid="nachname")

    nochmal = agent._online_fallback_antwort(sit, "Wie bitte?")
    ende = agent._online_fallback_antwort(sit, "Das weiß ich nicht.")

    assert "ja oder nein" in nochmal["text"]
    assert ende["hangup"] is True
    assert aufrufe == []


def test_senden_setzt_beleg_und_spricht_freundlich(monkeypatch):
    gesehen = {}

    def _cf(name, body):
        gesehen["name"] = name
        gesehen["body"] = body
        return 200, {"status": "ok", "sent": False, "dryRun": True,
                     "url": "https://pickadoc.de/profile/C1/L1"}, {}

    monkeypatch.setattr(online_fallback, "_cf_call", _cf)
    sit = _sit()
    aus = online_fallback.senden(sit)
    assert gesehen["name"] == "agentNameConfirm"
    assert gesehen["body"]["action"] == "booking-link"
    assert gesehen["body"]["phone"] == "+491771234567"
    assert gesehen["body"]["dryRun"] is True
    assert aus["ok"] is True
    assert aus["hangup"] is True
    assert aus["onlineFallback"] is True
    assert "direkten Link zur Online-Buchung" in aus["text"]
    beleg = sit["onlineBuchungslink"]
    assert beleg["ok"] is True
    assert beleg["an"] == "+491771234567"
    assert beleg["url"] == "https://pickadoc.de/profile/C1/L1"


def test_senden_bei_cf_fehler_behauptet_keine_sms(monkeypatch):
    def _cf(name, body):
        return 500, {"status": "error", "sent": False}, {}

    monkeypatch.setattr(online_fallback, "_cf_call", _cf)
    sit = _sit()
    sit["tenant"]["_testNoWrite"] = False
    aus = online_fallback.senden(sit)
    assert aus["ok"] is False
    assert aus["hangup"] is True
    assert "online" in aus["text"].lower()
    assert sit["onlineBuchungslink"]["ok"] is False


def test_namens_sms_hat_vorrang_vor_online_link(monkeypatch):
    """Kann die Namens-SMS starten, wird sie angeboten — NICHT der Online-Link.

    Der Anruf läuft dabei weiter (Namenseingabe per SMS); der Online-
    Buchungslink bleibt der letzte Ausweg, falls die Namens-SMS scheitert.
    """
    online_aufrufe = []
    monkeypatch.setattr(
        online_fallback,
        "_cf_call",
        lambda *a, **k: online_aufrufe.append((a, k)),
    )
    # Namens-SMS kann starten und liefert ihre eigene Antwort.
    namens_satz = {"text": "Ich schicke Ihnen kurz eine SMS."}
    monkeypatch.setattr(namenslink, "starten", lambda *a, **k: namens_satz)

    sit = _sit()
    aus = agent._frage_budget_ausstieg(sit, fid="nachname")

    assert aus is namens_satz
    assert not online_fallback.zustimmung_offen(sit)
    assert online_aufrufe == [], "der Online-Link darf nicht angeboten werden"


def test_online_link_bleibt_letzter_ausweg_wenn_namens_sms_scheitert(monkeypatch):
    """Scheitert die Namens-SMS (starten -> None), greift der Online-Link."""
    monkeypatch.setattr(namenslink, "starten", lambda *a, **k: None)
    monkeypatch.setattr(online_fallback, "_cf_call", lambda *a, **k: None)
    sit = _sit()
    aus = agent._frage_budget_ausstieg(sit, fid="nachname")
    assert aus["zustimmung"] is True
    assert online_fallback.zustimmung_offen(sit)


def test_beleg_raeumt_patient_nicht_gefunden():
    # Ein gesendeter Online-Link entkraeftet den kritischen Fail.
    from kern import anruf_anliegen
    manifest = {
        "tools": [{"name": "agentFindPatientAppointments",
                   "notFound": True}],
        "onlineBuchungslink": {"ok": True, "an": "+491771234567"},
    }
    assert anruf_anliegen.patient_nicht_gefunden(manifest) is False
    ohne = {"tools": [{"name": "agentFindPatientAppointments",
                       "notFound": True}]}
    assert anruf_anliegen.patient_nicht_gefunden(ohne) is True
