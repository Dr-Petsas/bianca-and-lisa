"""W-KANDIDATEN C: SMS-Link nur bei unsicherer Identifikation."""

from bianca import flow, gehirn, verwalten
from kern import namenslink
from kern import patients
from tests.test_bianca_bausteine import GEFUNDEN, _sit, _suchname, _verwaltung_start


def _handy_sit():
    sit = _sit()
    sit["id"] = "sitzung-namenslink"
    sit["anrufer"] = {"telefon": "+491776004600"}
    return sit


def test_neupatient_fremdes_handy_bekommt_pfad():
    sit = _sit()
    sit["anrufer"] = {"telefon": "+491771234567"}
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "warSchonMal": False,
        "nachname": "Patrikis",
        "vorname": "Konstantinos",
    })
    assert namenslink.erlaubt(sit)
    assert namenslink.ohne_stammdaten(sit)
    assert namenslink.soll_statt_buchstabieren(sit)
    assert namenslink.skip_documents(sit)
    assert namenslink.test_unbekannt(sit) is False


def test_bestand_behaelt_sofort_sms():
    sit = _sit()
    sit["anrufer"] = {
        "telefon": "+491771234567",
        "nachname": "Müller",
        "vorname": "Anna",
    }
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "warSchonMal": True,
        "bekannt": True,
        "anruferCheck": "ja",
        "nachname": "Müller",
        "vorname": "Anna",
        "telefon": "+491771234567",
        "telefonOk": True,
    })
    assert namenslink.erlaubt(sit)
    assert namenslink.ohne_stammdaten(sit) is False
    assert namenslink.skip_documents(sit) is False


def test_ohne_handy_kein_link():
    sit = _sit()
    assert namenslink.starten(sit) is None


def test_festnetz_kein_link():
    sit = _sit()
    sit["anrufer"] = {"telefon": "+492113021234"}
    assert namenslink.starten(sit) is None


def test_notaus_kein_link(monkeypatch):
    sit = _handy_sit()
    monkeypatch.setenv("NAMENS_LINK", "0")
    assert namenslink.starten(sit) is None


def test_platzhalter_akte_darf_chef_handy(monkeypatch):
    monkeypatch.setattr(patients, "WRITE_LIVE", False)
    aus = patients.akte_anlegen(
        {"clientId": "c", "locationId": "l", "_testNoWrite": True},
        first="Reservierung",
        last="SMS",
        phone="01776004600",
    )
    assert aus["ok"] is True
    assert aus["patient"]["phone"] == "+491776004600"
    gesperrt = patients.akte_anlegen(
        {"clientId": "c", "locationId": "l", "_testNoWrite": True},
        first="Michael",
        last="Petsas",
        phone="01776004600",
    )
    assert gesperrt["ok"] is False


def test_kiriakos_ist_canary():
    sit = _sit()
    sit["anrufer"] = {"telefon": "+491525304756"}
    assert namenslink.ist_canary("01525304756")
    assert namenslink.ist_canary("+49 152 5304756")
    assert namenslink.erlaubt(sit)
    assert namenslink.test_unbekannt(sit)


def test_chef_unbekannt_parkt_nummer_ohne_petsas():
    sit = _handy_sit()
    sit["anrufer"] = {
        "telefon": "+491776004600",
        "vorname": "Michael",
        "nachname": "Petsas",
        "patientId": "pat-petsas",
        "geschlecht": "m",
    }
    assert gehirn.anrufer_bekannt(sit) == {}
    assert gehirn.anrufer_hallo_jetzt(sit, "Ich hätte gern einen Termin.") == ""
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "grund"
    assert "petsas" not in frage.lower()
    assert s["vorname"] == "Reservierung"
    assert s["nachname"] == "SMS"
    assert s["telefon"] == "+491776004600"
    assert s["telefonOk"] is True
    assert namenslink.erkannte_nummer(sit) == "+491776004600"
    ctx = flow._ctx_bauen(sit)
    assert ctx["firstName"] == "Reservierung"
    assert ctx["lastName"] == "SMS"
    assert ctx["phone"] == "+491776004600"
    assert ctx["phoneConfirmed"] == "+491776004600"
    assert ctx.get("patientId") in {None, ""}
    assert ctx.get("skipConfirmation") is True
    assert ctx.get("platzhalterAkte") is True


def test_unbekannt_flag_aus_erkennt_wieder(monkeypatch):
    monkeypatch.setenv("NAMENS_LINK_UNBEKANNT", "0")
    sit = _handy_sit()
    sit["anrufer"] = {
        "telefon": "+491776004600",
        "vorname": "Michael",
        "nachname": "Petsas",
    }
    a = gehirn.anrufer_bekannt(sit)
    assert a.get("nachname") == "Petsas"
    assert namenslink.test_unbekannt(sit) is False


def test_fremde_nummer_schickt_gehoerten_namen_ohne_ihn_vorzulesen(monkeypatch):
    """Neupatient: Name hören, nicht als Tatsache sagen, in der SMS vorausfüllen."""
    def cf(route, body, timeout=None):
        assert body["firstName"] == "Martin"
        assert body["lastName"] == "Berger"
        return 200, {
            "status": "ok",
            "token": "tok-prefill",
            "url": "https://example.test/n",
            "dryRun": True,
        }, {}

    monkeypatch.setattr(namenslink, "_cf_call", cf)
    sit = _sit()
    sit["id"] = "sitzung-prefill"
    sit["anrufer"] = {"telefon": "+491771234567"}
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "arzt": {"typ": "egal", "calendarId": "c", "calendarName": "Petsas"},
        "grund": "Kontrolle",
        "wunsch": {},
    })
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "nachname"
    assert "buchstabe" not in frage.lower()
    assert "Wie lautet Ihr Nachname?" in frage
    s["frage"] = fid
    neu = gehirn.einsammeln(sit, "Berger.")
    assert "Berger" not in flow._quittung(s, neu)
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "vorname"
    assert "Berger" not in frage
    s["frage"] = fid
    neu = gehirn.einsammeln(sit, "Martin.")
    quittung = flow._quittung(s, neu)
    assert "Martin" not in quittung and "Berger" not in quittung
    gehirn.naechste_frage(sit)
    assert s["vorname"] == "Reservierung"
    assert s["nachname"] == "SMS"
    assert namenslink.gehoerte_namen(sit) == ("Martin", "Berger")
    aus = namenslink.starten(sit, parallel=True)
    assert sit["namenslink"]["firstNameHint"] == "Martin"
    assert sit["namenslink"]["lastNameHint"] == "Berger"
    text = (aus or {}).get("text") or ""
    assert "Martin" not in text and "Berger" not in text


def test_neupatient_bekommt_sms_statt_buchstabieren():
    sit = _handy_sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "arzt": {"typ": "egal", "calendarId": "c", "calendarName": "Petsas"},
        "grund": "Kontrolle",
        "wunsch": {},
    })
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == ""
    assert "buchstabier" not in frage.lower()
    assert s["vorname"] == "Reservierung"
    assert namenslink.braucht_vor_buchung(sit) is False
    assert namenslink.skip_documents(sit) is True
    ctx = flow._ctx_bauen(sit)
    assert ctx.get("skipConfirmation") is True
    assert ctx["phone"] == "+491776004600"


def test_verifizierter_name_wird_nicht_von_stt_ueberschrieben():
    sit = _handy_sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "frage": "",
        "vorname": "Konstantinos",
        "nachname": "Patrikis",
        "nameVerified": True,
        "nameQuelle": "typed",
    })
    gehirn.einsammeln(sit, "Papadopulos.")
    assert s["nachname"] == "Patrikis"
    assert s["vorname"] == "Konstantinos"


def test_unsicherer_stt_name_soll_sms():
    sit = _handy_sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "warSchonMal": True,
        "nachname": "Xqzdfghjk",
        "vorname": "Anna",
        "buchstabiert": False,
        "bekannt": False,
        "nameVerified": False,
        "anruferCheck": "ja",
    })
    namenslink.stammdaten_parken(sit)
    assert s["vorname"] == "Reservierung"
    assert namenslink.skip_documents(sit) is True


def test_mehrdeutig_mit_vorname_und_handy_startet_link(monkeypatch):
    def _find(t, c):
        return {
            "ok": True,
            "mehrdeutig": True,
            "patient": {},
            "appointments": [],
            "candidates": [
                {"id": "a", "firstName": "Anna", "lastName": "Müller"},
                {"id": "b", "firstName": "Peter", "lastName": "Müller"},
            ],
        }

    def cf(route, body, timeout=None):
        assert route == "agentNameConfirm"
        assert body["phone"] == "+491776004600"
        assert body["sessionId"] == "sitzung-namenslink"
        return 200, {
            "status": "ok",
            "token": "tok1234567890abcd",
            "url": "https://example.test/n",
            "dryRun": True,
        }, {"route": route}

    monkeypatch.setattr(verwalten.kal, "find_patient_appointments", _find)
    monkeypatch.setattr(namenslink, "_cf_call", cf)
    sit = _handy_sit()
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    s["nachname"] = "Müller"
    s["vorname"] = "Anna"
    aus = verwalten._dispatch(sit, None)
    assert aus and "sms" in aus["text"].lower()
    assert "Anna" not in aus["text"] and "Peter" not in aus["text"]
    assert s["frage"] == "namenslink"
    assert sit["namenslink"]["token"] == "tok1234567890abcd"


def test_erste_mehrdeutigkeit_fragt_vorname_ohne_sms(monkeypatch):
    def _find(t, c):
        return {"ok": True, "mehrdeutig": True, "patient": {}, "appointments": []}

    monkeypatch.setattr(verwalten.kal, "find_patient_appointments", _find)
    sit = _sit()
    sit["anrufer"] = {"telefon": "+491771234567"}
    z1 = _verwaltung_start(sit, "Ich möchte meinen Termin absagen.")
    assert z1 and "nachname" in z1["text"].lower()
    z2 = _suchname(sit, "Müller.")
    assert z2
    assert "vorname" in z2["text"].lower()
    assert "sms" not in z2["text"].lower()
    assert gehirn.sammler(sit)["frage"] == "vorname"


def test_notfound_nach_korrektur_mit_handy(monkeypatch):
    def _find(t, c):
        return {"ok": True, "notFound": True, "patient": {}, "appointments": []}

    def cf(route, body, timeout=None):
        return 200, {
            "status": "ok",
            "token": "tok-korrektur",
            "url": "https://example.test/n",
            "dryRun": True,
        }, {"route": route}

    monkeypatch.setattr(verwalten.kal, "find_patient_appointments", _find)
    monkeypatch.setattr(namenslink, "_cf_call", cf)
    sit = _handy_sit()
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    s["nachname"] = "Möbel"
    s["vorname"] = "Peter"
    sit["verwKorrektur"] = True
    aus = verwalten._dispatch(sit, None)
    assert aus and "sms" in aus["text"].lower()
    assert s["frage"] == "namenslink"


def test_getippter_name_wird_neu_gesucht(monkeypatch):
    gesucht = []

    def _find(t, c):
        gesucht.append(dict(c))
        if c.get("lastName") == "Tzannis":
            return dict(GEFUNDEN)
        return {"ok": True, "notFound": True, "patient": {}, "appointments": []}

    def cf(route, body, timeout=None):
        if body.get("action") == "create":
            return 200, {"status": "ok", "token": "tok-done", "url": "u", "dryRun": True}, {}
        assert body.get("action") == "status"
        return 200, {
            "status": "done",
            "firstName": "Thomas",
            "lastName": "Tzannis",
        }, {}

    monkeypatch.setattr(verwalten.kal, "find_patient_appointments", _find)
    monkeypatch.setattr(namenslink, "_cf_call", cf)
    sit = _handy_sit()
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    s["nachname"] = "Czannis"
    s["vorname"] = "Thomas"
    sit["verwKorrektur"] = True
    start = verwalten._dispatch(sit, None)
    assert start and s["frage"] == "namenslink"
    aus = verwalten.zug(sit, "Ja.", set(), None)
    assert aus and "wirklich absagen" in aus["text"].lower()
    assert s["nachname"] == "Tzannis"
    assert s["vorname"] == "Thomas"
    assert gesucht[-1]["lastName"] == "Tzannis"
    assert gesucht[-1]["firstName"] == "Thomas"


def test_stille_pollt_ohne_presence(monkeypatch):
    from bianca import agent

    def cf(route, body, timeout=None):
        return 200, {"status": "open"}, {}

    monkeypatch.setattr(namenslink, "_cf_call", cf)
    sit = _handy_sit()
    sit["sammler"] = {"modus": "absagen", "frage": "namenslink",
                      "nachname": "Müller"}
    sit["namenslink"] = {"token": "tok-stille"}
    aus = agent.stille_zug(sit)
    assert aus["text"] == ""
    from kern import stille as stille_kern
    assert stille_kern.gesamt(sit) == 0


def test_gesprochener_name_statt_link(monkeypatch):
    def _find(t, c):
        if c.get("lastName") == "Müller":
            return dict(GEFUNDEN)
        return {"ok": True, "notFound": True, "patient": {}, "appointments": []}

    def cf(route, body, timeout=None):
        if body.get("action") == "create":
            return 200, {"status": "ok", "token": "tok-sprechen", "url": "u", "dryRun": True}, {}
        return 200, {"status": "open"}, {}

    monkeypatch.setattr(verwalten.kal, "find_patient_appointments", _find)
    monkeypatch.setattr(namenslink, "_cf_call", cf)
    sit = _handy_sit()
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    s["nachname"] = "Möbel"
    s["vorname"] = "Peter"
    sit["verwKorrektur"] = True
    verwalten._dispatch(sit, None)
    s["nachname"] = "Müller"
    s["vorname"] = "Peter"
    aus = namenslink.zug(sit, "Peter Müller.", set(), None)
    assert aus and "wirklich absagen" in aus["text"].lower()


def test_platzhalter_bucht_ohne_zu_warten(monkeypatch):
    gebucht = []
    gebunden = []

    def _book(tenant, ctx, slot_iso=""):
        gebucht.append(dict(ctx))
        return {
            "ok": True, "booked": True, "slotIso": slot_iso,
            "appointmentId": "appt-canary", "patientId": "pat-canary",
            "spoken": "Der Termin ist fest eingetragen.",
        }

    def cf(route, body, timeout=None):
        if body.get("action") == "bind":
            gebunden.append(dict(body))
            return 200, {"status": "ok"}, {}
        assert body.get("firstName") == "Konstantinos"
        assert body.get("lastName") == "Patrikis"
        return 200, {
            "status": "ok",
            "token": "tok-buch",
            "url": "https://example.test/n",
            "dryRun": True,
        }, {}

    monkeypatch.setattr(namenslink, "_cf_call", cf)
    sit = _handy_sit()
    sit["tenant"] = {**sit["tenant"], "_testNoWrite": True}
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "warSchonMal": False,
        "phase": "bestaetigen",
        "arzt": {"typ": "genannt", "calendarId": "c", "calendarName": "Petsas"},
        "grund": "Kontrolle",
        "motivId": "m1",
        "motivName": "Kontrolle",
        "wunsch": {},
        "vorname": "Konstantinos",
        "nachname": "Patrikis",
        "slotIso": "2026-09-22T09:00:00+02:00",
        "telefon": "01776004600",
        "telefonOk": True,
        "versicherung": "gesetzlich",
        "versicherungOk": True,
        "pzr": "nein",
        "arztNotizFrage": "nein",
        "buchstabiert": False,
        "bekannt": False,
    })
    sit["buchIntent"] = True
    sit["angebotKalender"] = {"calendarId": "c", "calendarName": "Petsas"}
    echt = flow.kal.book_slot
    flow.kal.book_slot = _book
    try:
        aus = flow._buchen(sit)
    finally:
        flow.kal.book_slot = echt
    assert aus and "sms" in aus["text"].lower()
    assert "frau sms" not in aus["text"].lower()
    assert "herr sms" not in aus["text"].lower()
    assert "dokumente" in aus["text"].lower()
    assert "neunzig minuten" in aus["text"].lower()
    assert "warte" not in aus["text"].lower()
    assert gebucht and gebucht[0].get("skipConfirmation") is True
    assert gebucht[0].get("phone") == "+491776004600"
    assert gebucht[0].get("phoneConfirmed") == "+491776004600"
    assert gebucht[0].get("firstName") == "Reservierung"
    assert gebucht[0].get("lastName") == "SMS"
    assert sit["namenslink"]["token"] == "tok-buch"
    assert gebunden and gebunden[0]["appointmentId"] == "appt-canary"


def _festnetz_sit():
    sit = _sit()
    sit["id"] = "sitzung-festnetz"
    sit["anrufer"] = {
        "telefon": "+492113021234",
        "vorname": "Martin",
        "nachname": "Berger",
        "patientId": "pat-fest",
        "geschlecht": "m",
    }
    return sit


def test_festnetz_fragt_handy_nicht_sms_ans_festnetz():
    sit = _festnetz_sit()
    s = gehirn.sammler(sit)
    gehirn.anrufer_daten_uebernehmen(sit)
    assert s["aktePhone"].startswith("0211") or "211" in s["aktePhone"]
    fid, frage = gehirn.telefon_frage(sit)
    assert fid == "telefon"
    assert "festnetz" in frage.lower()
    assert "0211" not in frage
    assert "null zwei eins eins" not in frage.lower()
    assert namenslink.starten(sit) is None
    assert namenslink.erlaubt(sit) is False


def test_festnetz_akte_zaehlt_nicht_als_sms_ziel():
    sit = _festnetz_sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "bekannt": True,
        "telefonAkte": True,
        "aktePhone": "02113021234",
        "telefonBekannt": "02113021234",
    })
    fid, frage = gehirn.telefon_frage(sit)
    assert fid == "telefon"
    assert "festnetz" in frage.lower()
    assert s["telefonAkte"] is False


def test_festnetz_ja_auf_festnetz_wird_abgelehnt():
    sit = _festnetz_sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "frage": "telefon_check",
        "telefonOffen": "02113021234",
    })
    neu = gehirn.einsammeln(sit, "Ja.")
    assert "telefonKorrektur" in neu
    assert not s["telefonOk"]
    assert not s["telefon"]
    fid, frage = gehirn.telefon_frage(sit)
    assert fid == "telefon"
    assert "festnetz" in frage.lower()


def test_festnetz_diktat_wird_nicht_vorgelesen():
    sit = _festnetz_sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "telefon"})
    gehirn.einsammeln(sit, "02113021234.")
    assert not s["telefonOffen"]
    fid, frage = gehirn.telefon_frage(sit)
    assert fid == "telefon"
    assert "handy" in frage.lower()


def test_festnetz_plus_canary_handy_bekommt_link(monkeypatch):
    def cf(route, body, timeout=None):
        assert body["phone"] == "+491776004600"
        if body.get("action") == "bind":
            return 200, {"status": "ok"}, {}
        return 200, {
            "status": "ok",
            "token": "tok-fest",
            "url": "https://example.test/n",
            "dryRun": True,
        }, {}

    monkeypatch.setattr(namenslink, "_cf_call", cf)
    sit = _festnetz_sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "warSchonMal": False,
        "telefon": "01776004600",
        "telefonOk": True,
        "vorname": "Martin",
        "nachname": "Berger",
        "buchstabiert": False,
        "bekannt": False,
    })
    assert namenslink.ist_festnetz_anrufer(sit)
    assert namenslink.handy(sit) == "+491776004600"
    assert namenslink.erlaubt(sit)
    assert namenslink.skip_documents(sit)
    assert namenslink.starten(sit, parallel=True)
    assert sit["namenslink"]["token"] == "tok-fest"


def test_platzhalter_wird_nie_frau_sms():
    sit = _handy_sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    namenslink.stammdaten_parken(sit)
    s["grund"] = "Kontrolle"
    s["motivName"] = "Kontrolle"
    s["slotIso"] = "2026-09-22T09:00:00+02:00"
    s["arzt"] = {"calendarName": "Doktor Petsas"}
    assert gehirn.anrede(s) == ""
    rb = flow._readback(sit)
    text = (rb.get("text") or "").lower()
    assert "frau sms" not in text
    assert "herr sms" not in text
    assert "reserviere ihnen" in text
    assert "sms" in text
    assert "neunzig minuten" in text
    from kern import anrede_wache
    assert "sms" not in anrede_wache.belegte_namen(sit)
    assert "reservierung" not in anrede_wache.belegte_namen(sit)
