"""W-NAMENS-SMS-RETTUNG (05.10.2026): Namens-SMS an die Anrufernummer,
wenn Bianca den Nachnamen mehrmals nicht versteht — auch mit
``NAMENS_LINK=0`` (P0-Containment der Platzhalter-Reservierung).

Live 05.10.2026 buchstabierten Anrufer drei-, viermal; die SMS kam nie,
weil das Containment beide Hälften abgeschaltet hatte."""

import pytest

from bianca import agent, flow, gehirn, verwalten
from kern import namenslink, stille
from tests.test_bianca_bausteine import _sit


@pytest.fixture(autouse=True)
def _live_modus(monkeypatch):
    monkeypatch.setenv("NAMENS_LINK", "0")
    monkeypatch.delenv("NAMENS_SMS", raising=False)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)


def _cf(aufrufe, status="open", **mehr):
    def cf(route, body, timeout=None):
        aufrufe.append(dict(body))
        if body.get("action") == "create":
            return 200, {"status": "ok", "token": "tok-rettung", "url": "u",
                         "sent": True}, {}
        return 200, {"status": status, **mehr}, {}
    return cf


def _leitungs_sit():
    sit = _sit()
    sit["id"] = "sitzung-rettung"
    sit["callerPhone"] = "+491776004600"
    return sit


def _readback_offen(sit, name="Pusch"):
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": False, "vorname": "Anna",
        "nachname": name, "buchstabiert": True,
        "nachnameCheck": "offen", "frage": "nachname_check",
    })
    return s


def test_live_modus_trennt_namens_sms_von_reservierung():
    sit = _leitungs_sit()
    gehirn.sammler(sit).update({"modus": "buchen", "warSchonMal": False})
    assert namenslink.aktiv() is False
    assert namenslink.nur_name() is True
    assert namenslink.erlaubt(sit)
    # Keine Platzhalter-Akte, kein Parallel-Link vor dem Buchstabieren.
    assert namenslink.skip_documents(sit) is False
    assert namenslink.soll_statt_buchstabieren(sit) is False


def test_handy_kommt_aus_der_leitung():
    sit = _sit()
    sit["callerPhone"] = "+491776004600"
    assert namenslink.handy(sit) == "+491776004600"
    sit["callerPhone"] = "+4921154244101"
    assert namenslink.handy(sit) == ""


def test_notaus_namens_sms(monkeypatch):
    monkeypatch.setenv("NAMENS_SMS", "0")
    assert namenslink.erlaubt(_leitungs_sit()) is False


def test_zweites_nein_auf_die_ruecklese_schickt_die_sms(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(namenslink, "_cf_call", _cf(aufrufe))
    sit = _leitungs_sit()
    s = _readback_offen(sit)
    erst = flow.zug(sit, "Nein.")
    assert "buchstabieren" in erst["text"].lower()
    assert not aufrufe
    _readback_offen(sit, "Busk")
    zweit = flow.zug(sit, "Nein, das stimmt nicht.")
    assert "sms" in zweit["text"].lower()
    assert s["frage"] == "namenslink"
    create = [a for a in aufrufe if a.get("action") == "create"]
    assert len(create) == 1
    assert create[0]["phone"] == "+491776004600"
    # Reine Namensabfrage: nie Termin, Akte oder Slot am Link.
    assert create[0]["appointmentId"] == ""
    assert create[0]["patientId"] == ""
    assert create[0]["start"] == ""


def test_ohne_handy_bleibt_es_beim_buchstabieren(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(namenslink, "_cf_call", _cf(aufrufe))
    sit = _sit()
    sit["callerPhone"] = "+4921154244101"
    _readback_offen(sit)
    flow.zug(sit, "Nein.")
    _readback_offen(sit, "Busk")
    aus = flow.zug(sit, "Nein.")
    assert "buchstabieren" in aus["text"].lower()
    assert not aufrufe


def test_scope_ueberlebt_die_slotwahl(monkeypatch):
    monkeypatch.setattr(namenslink, "_cf_call", _cf([]))
    sit = _leitungs_sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    namenslink.starten(sit)
    assert namenslink._scope_passt(sit)
    s["slotIso"] = "2026-10-07T09:00:00"
    s["calendarId"] = "kal-1"
    assert namenslink._scope_passt(sit)


def test_getippter_name_fuehrt_die_buchung_weiter(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(namenslink, "_cf_call", _cf(
        aufrufe, status="done", firstName="Anna", lastName="Busch"))
    sit = _leitungs_sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False})
    namenslink.starten(sit)
    assert s["frage"] == "namenslink"
    aus = flow.zug(sit, "Okay.")
    assert s["nachname"] == "Busch"
    assert s["vorname"] == "Anna"
    assert s["frage"] != "namenslink"
    assert aus and aus["text"].startswith("Danke, Ihren Namen habe ich jetzt.")
    # Buchung, nicht die Termin-Suche der Verwaltung.
    assert s["modus"] == "buchen"


def test_gesprochener_name_wartet_statt_falsch_zu_buchen(monkeypatch):
    monkeypatch.setattr(namenslink, "_cf_call", _cf([]))
    sit = _leitungs_sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False, "nachname": "Pusch"})
    namenslink.starten(sit)
    aus = flow.zug(sit, "Busch.")
    assert "warte" in aus["text"].lower()
    assert s["frage"] == "namenslink"


def test_sms_geht_nicht_fuehrt_zum_langsamen_buchstabieren(monkeypatch):
    monkeypatch.setattr(namenslink, "_cf_call", _cf([]))
    sit = _leitungs_sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False})
    s["nameFehlversuche"] = 2
    namenslink.starten(sit)
    aus = flow.zug(sit, "Die SMS ist nicht angekommen.")
    assert "buchstab" in aus["text"].lower()
    assert s["frage"] == "buchstabieren"
    assert namenslink.rettung_faellig(sit) is False


def test_stilles_warten_auf_die_sms_zaehlt_nicht_als_stups(monkeypatch):
    monkeypatch.setattr(namenslink, "_cf_call", _cf([]))
    sit = _leitungs_sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False})
    namenslink.starten(sit)
    ticks = [agent.stille_zug(sit) for _ in range(3)]
    assert all(t.get("warte") and not t["text"] for t in ticks)
    assert stille.gesamt(sit) == 0
    hinweis = agent.stille_zug(sit)
    assert "sms" in hinweis["text"].lower()
    # Rettungs-SMS: nicht wieder zum Sprechen des Namens einladen.
    assert "geht nicht" in hinweis["text"].lower()
    assert "am telefon sagen" not in hinweis["text"].lower()
    assert not hinweis.get("hangup")


def test_langes_sms_warten_endet_im_langsamen_buchstabieren(monkeypatch):
    monkeypatch.setattr(namenslink, "_cf_call", _cf([]))
    sit = _leitungs_sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False})
    namenslink.starten(sit)
    letzte = None
    for _ in range(agent._NAMENSLINK_RETTUNG_MAX):
        letzte = agent.stille_zug(sit)
    assert "buchstabieren" in letzte["text"].lower()
    assert s["frage"] == "buchstabieren"
    assert not letzte.get("hangup")
    assert namenslink.rettung_faellig(sit) is False


# --- Stille mitten im Diktat (Kalchreuter/Renz, 05.10.2026) ---------------

def _diktat_sit(teil):
    sit = _sit()
    sit["messages"].append({"role": "assistant", "content":
                            "Buchstabieren Sie mir den Nachnamen bitte?"})
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False,
              "frage": "buchstabieren", "buchstabenTeil": teil})
    return sit, s


def test_vollstaendig_buchstabiert_und_still_wird_vorgelesen_statt_aufgelegt():
    sit, s = _diktat_sit("kalchreuter")
    erst = agent.stille_zug(sit)
    assert erst.get("warte") and not erst["text"]
    zweit = agent.stille_zug(sit)
    assert s["nachname"] == "Kalchreuter"
    assert s["frage"] == "nachname_check"
    assert "kalchreuter" in zweit["text"].lower()
    assert not zweit.get("hangup")
    assert stille.gesamt(sit) == 0


def test_kurzes_fragment_bleibt_stilles_warten():
    sit, s = _diktat_sit("re")
    for _ in range(3):
        aus = agent.stille_zug(sit)
        assert aus.get("warte") and not aus["text"]
    assert s["frage"] == "buchstabieren"


# --- Wiederhol-Vorsätze (be543d80, 05.10.2026) ----------------------------

def test_vorsaetze_verschachteln_sich_nicht():
    satz = ("Ich frage noch einmal: Noch einmal die Frage: Waren Sie schon "
            "einmal bei uns? Ein kurzes Ja oder Nein genügt.")
    assert stille.kern_frage(satz) == "Waren Sie schon einmal bei uns?"
    sit = {}
    neu = stille.frage_praefix(satz, sit)
    assert neu.count(":") == 1
    assert neu.endswith("Waren Sie schon einmal bei uns?")


def test_hoerfehler_nachfrage_wiederholt_keine_begruessung():
    sit = {"messages": [{"role": "assistant", "content":
                         "Guten Tag, Sie sprechen mit Bianca, der "
                         "Telefonassistentin. Wie kann ich Ihnen helfen?"}]}
    text = stille.hoerfehler_nachfrage(sit)
    assert "sprechen mit" not in text.lower()
    assert text.endswith(stille.GRUSS_ERSATZ)


def test_presence_ist_keine_offene_frage():
    msgs = [
        {"role": "assistant", "content": "Wie ist Ihr Nachname?"},
        {"role": "assistant", "content": "Sind Sie noch dran?"},
    ]
    assert stille.letzte_frage(msgs) == "Wie ist Ihr Nachname?"


def test_qwen_vorschlag_endet_nach_der_zweiten_unklaren_antwort(monkeypatch):
    monkeypatch.setattr(namenslink, "_cf_call", _cf([]))
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "nachname": "Pusch", "frage": "qwen_name"})
    sit["qwenNameVorschlag"] = "Busch"
    erst = verwalten._qwen_name_zug(sit, "Wie bitte?", None)
    assert "ja oder nein" in erst["text"].lower()
    zweit = verwalten._qwen_name_zug(sit, "Hm, weiß nicht.", None)
    assert "verstanden" not in zweit["text"].lower() or "falsch" in zweit["text"].lower()
    assert s["frage"] == "nachname"
    assert sit.get("qwenNameVerbraucht")


def test_qwen_ohne_vorschlag_liest_nie_einen_leeren_namen(monkeypatch):
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "nachname": "Pusch", "frage": "qwen_name"})
    aus = verwalten._qwen_name_zug(sit, "Hä?", None)
    assert "auch  verstanden" not in aus["text"]
    assert s["frage"] == "nachname"


def test_qwen_buchstabierkette_ist_die_antwort():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "nachname": "Pusch", "frage": "qwen_name"})
    sit["qwenNameVorschlag"] = "Bosch"
    aus = verwalten._qwen_name_zug(sit, "B-U-S-C-H, fertig.", None)
    assert s["nachname"] == "Busch"
    assert s["frage"] == "nachname_check"
    assert "busch" in aus["text"].lower()
