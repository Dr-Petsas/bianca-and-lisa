"""W-ONLINE-FALLBACK (26.09.2026): Online-Buchungslink nach Namens-Fails.

Die Gegenproben (kein Handy, kein Buchungsmodus, schon gesendet) sind der
teurere Teil — ein falsch ausgeloester Link waere ein Fehlverhalten.
"""

from kern import online_fallback


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
    assert "SMS" in aus["text"]
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
