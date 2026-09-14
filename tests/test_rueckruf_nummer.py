"""W-RUECKRUF-NUMMER (14.09.2026, Anrufe da746a65 / 5aa87268) — offline.

Live sagte Bianca nach leerer Slotsuche "Die Praxis meldet sich kurzfristig
bei Ihnen" — und in der Rueckruf-Notiz stand KEINE Nummer (Anrufer ohne
uebermittelte Rufnummer, im Gespraech war noch keine gefallen, weil die
Nummer seit W-TELEFON-ZULETZT erst VOR dem Eintragen erfragt wird). Die
Praxis konnte gar nicht zurueckrufen.

Regel: steht die Notiz ohne Nummer, ist die Nummer jetzt die offene Frage —
deterministisch wie telefon_check (Ziffern -> Readback -> Ja -> Nummer in
Notiz + Dock nachgetragen). Ablehnung/"nichts mehr" schliesst EHRLICH ohne
Nummer ab; zwei unklare Antworten ebenfalls (nie eine Schleife). Ist die
Nummer bekannt (Anrufer-ID, Akte, bestaetigt), wird nichts gefragt — die
Notiz traegt sie von Anfang an.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bianca import flow, gehirn, verwalten
from kern.tenants import laden


def _katalog() -> list[dict]:
    return [{"id": "kontrolle", "name": "KCH Kontrolluntersuchung",
             "nameForPatient": "Kontrolle", "allowOnlineBooking": True, "calendarIds": []}]


def _sit(anrufer_nummer: str = "") -> dict:
    sit = {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}],
           "stimme": "Bianca", "motivKatalog": _katalog()}
    if anrufer_nummer:
        sit["anrufer"] = {"vorname": "Julia", "nachname": "Berger", "telefon": anrufer_nummer}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True,
              "arzt": {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg",
                       "calendarName": "Dr. Petsas"},
              "grund": "Kontrolle", "grundWortlaut": "zur Kontrolle",
              "motivId": "kontrolle", "motivName": "KCH Kontrolluntersuchung",
              "vorname": "Julia", "nachname": "Berger", "buchstabiert": True,
              "versicherung": "gesetzlich", "phase": "angebot",
              "wunsch": {"weekday": None, "hourMin": None, "hourMax": None, "hour": None,
                         "minDaysAhead": 0, "date": None, "tage": None, "von": None, "bis": None}})
    return sit


def _leer(tenant, ctx, *, start_date="", egal=False, source=""):
    return {"ok": True, "slots": [], "calendar": {"id": ctx.get("calendarId")},
            "motive": None, "doctorName": "", "dispatch": {}}


@pytest.fixture
def notizen(tmp_path: Path, monkeypatch):
    """Kein Slot in der CF, Notizen landen in tmp — liefert die JSONL-Zeilen."""
    monkeypatch.setattr(verwalten, "DATA_DIR", tmp_path)
    monkeypatch.setattr(flow.kal, "_find_slots_seite", _leer)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    datei = tmp_path / "praxis_notizen.jsonl"

    def lesen() -> list[dict]:
        if not datei.exists():
            return []
        return [json.loads(z) for z in datei.read_text(encoding="utf-8").splitlines() if z.strip()]
    return lesen


def _offen(sit: dict) -> bool:
    return bool((sit.get("rueckrufNummer") or {}).get("offen"))


# --- Start: wann wird gefragt, wann nicht -----------------------------------

def test_kein_slot_ohne_nummer_fragt_die_nummer(notizen):
    sit = _sit()
    s = gehirn.sammler(sit)
    ang = flow._angebot(sit)
    assert ang["text"].endswith(flow._RUECKRUF_NUMMER_FRAGE)
    assert "sonst noch etwas" not in ang["text"]
    assert _offen(sit) and s["frage"] == "telefon" and s["phase"] == "fertig"
    n = notizen()
    assert len(n) == 1 and n[0]["anliegen"] == "neubuchung" and n[0]["telefon"] == ""


def test_kein_slot_mit_anrufer_id_fragt_nicht_und_notiz_traegt_nummer(notizen):
    """Die Leitung kennt den Anrufer: nichts fragen, Nummer steht in JSONL und Dock."""
    sit = _sit(anrufer_nummer="+491771234567")
    ang = flow._angebot(sit)
    assert "Rufnummer" not in ang["text"] and "sonst noch etwas" in ang["text"]
    assert "rueckrufNummer" not in sit
    n = notizen()
    assert n[0]["telefon"] == "01771234567"
    assert "Tel: 01771234567" in sit["praxisNotiz"]


def test_kein_slot_mit_bestaetigter_nummer_fragt_nicht(notizen):
    sit = _sit()
    s = gehirn.sammler(sit)
    s["telefon"] = "01511234567"
    s["telefonOk"] = True
    ang = flow._angebot(sit)
    assert "Rufnummer" not in ang["text"]
    assert notizen()[0]["telefon"] == "01511234567"


def test_gehoerte_unbestaetigte_nummer_wird_erst_rueckbestaetigt(notizen):
    """telefonOffen ohne Ja: nie ungeprueft in die Notiz — Readback zuerst."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["telefonOffen"] = "01511234567"
    ang = flow._angebot(sit)
    assert "Stimmt das so" in ang["text"]
    assert s["frage"] == "telefon_check" and _offen(sit)
    assert notizen()[0]["telefon"] == ""


def test_buchen_fehlpfad_nach_zwei_slot_taken_fragt_die_nummer(notizen, monkeypatch):
    """'Meine Nummer haben Sie' (telefonAkte) wurde geglaubt — die Leitung
    zeigt aber keine: nach dem zweiten slotTaken kommt die Nummernfrage."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"phase": "bestaetigen", "telefonAkte": True, "telefonOk": True,
              "smsEmpfaenger": "patient", "slotIso": "2026-10-05T09:00:00+02:00"})
    sit["offered"] = [{"iso": s["slotIso"], "text": "x"}]
    sit["bookFails"] = 1
    monkeypatch.setattr(flow.kal, "book_slot",
                        lambda *a, **k: {"ok": False, "slotTaken": True, "spoken": "Der Termin ist gerade weg."})
    r = flow._buchen(sit)
    assert r["text"].endswith(flow._RUECKRUF_NUMMER_FRAGE)
    assert _offen(sit) and notizen()[0]["anliegen"] == "neubuchung"


# --- Der Zug: Ziffern -> Readback -> Ja -> nachgetragen ----------------------

def test_nummer_diktiert_readback_ja_nachgetragen(notizen):
    sit = _sit()
    s = gehirn.sammler(sit)
    flow._angebot(sit)
    r = flow.zug(sit, "null eins sieben sieben, eins zwei drei, vier fünf sechs sieben")
    assert "wiederhole die Nummer" in r["text"] and "Stimmt das so" in r["text"]
    assert s["frage"] == "telefon_check"
    r = flow.zug(sit, "Ja, genau.")
    assert "notiert" in r["text"] and "unter dieser Nummer" in r["text"]
    assert "sonst noch etwas" in r["text"] and not r.get("hangup")
    assert "rueckrufNummer" not in sit and s["phase"] == "fertig"
    n = notizen()
    assert len(n) == 2
    assert n[1]["anliegen"] == "rueckrufnummer" and n[1]["telefon"] == "01771234567"
    assert "Tel: 01771234567" in sit["praxisNotiz"]
    # Danach ist der Vorgang wirklich zu: Abschied legt auf, keine Slotsuche.
    r = flow.zug(sit, "Danke, tschüss.")
    assert r.get("hangup")


def test_ja_mit_abschied_traegt_nach_und_legt_auf(notizen):
    sit = _sit()
    flow._angebot(sit)
    flow.zug(sit, "null eins sieben sieben eins zwei drei vier fünf sechs sieben")
    r = flow.zug(sit, "Ja, das war's dann, danke.")
    assert r.get("hangup") and "unter dieser Nummer" in r["text"]
    assert notizen()[1]["telefon"] == "01771234567"


def test_nein_auf_readback_fragt_neu_statt_zu_schweigen(notizen):
    """'Nein, die letzte war eine neun' — die einsame 9 ist kein Diktat-Anfang."""
    sit = _sit()
    s = gehirn.sammler(sit)
    flow._angebot(sit)
    flow.zug(sit, "null eins fünf eins, zwei drei vier, fünf sechs sieben acht")
    r = flow.zug(sit, "Nein, die letzte war eine neun.")
    assert not r.get("warte") and "noch einmal" in r["text"]
    assert s["telefonTeil"] == "" and s["frage"] == "telefon" and _offen(sit)
    r = flow.zug(sit, "null eins fünf eins, zwei drei vier, fünf sechs sieben neun")
    assert "sieben neun" in r["text"] and "Stimmt das so" in r["text"]
    r = flow.zug(sit, "Ja.")
    assert "Tel: 01512345679" in sit["praxisNotiz"]


def test_nein_mit_neuer_nummer_liest_die_neue_vor(notizen):
    sit = _sit()
    flow._angebot(sit)
    flow.zug(sit, "null eins fünf eins, zwei drei vier, fünf sechs sieben acht")
    r = flow.zug(sit, "Nein: null eins sieben sieben, neun neun acht, sieben sechs fünf vier.")
    assert "Stimmt das so" in r["text"] and "sieben sieben" in r["text"]


def test_fragment_diktat_bleibt_still_und_fuegt_zusammen(notizen):
    """W-DATEN-FLOOR gilt auch hier: Teilstueck -> warte, kein Stups, kein Ton."""
    sit = _sit()
    s = gehirn.sammler(sit)
    flow._angebot(sit)
    r = flow.zug(sit, "null eins sieben sieben")
    assert r.get("warte") and r["text"] == "" and s["telefonTeil"] == "0177"
    r = flow.zug(sit, "eins zwei drei vier fünf sechs sieben")
    assert "Stimmt das so" in r["text"]


# --- Ohne Nummer abschliessen: ehrlich, nie eine Schleife --------------------

def test_ablehnung_schliesst_ohne_nummer_ab_und_gespraech_geht_weiter(notizen):
    sit = _sit()
    flow._angebot(sit)
    r = flow.zug(sit, "Nein, nicht nötig, ich melde mich dann selbst.")
    assert "Sprechzeiten" in r["text"] and "sonst noch etwas" in r["text"]
    assert not r.get("hangup") and "rueckrufNummer" not in sit
    assert len(notizen()) == 1 and notizen()[0]["telefon"] == ""
    r = flow.zug(sit, "Tschüss.")
    assert r.get("hangup")


def test_nichts_mehr_schliesst_ohne_nummer_ab_und_legt_auf(notizen):
    sit = _sit()
    flow._angebot(sit)
    r = flow.zug(sit, "Nee, das war's, danke.")
    assert r.get("hangup") and "notiert" in r["text"]
    assert "rueckrufNummer" not in sit


def test_zwischenfrage_wird_beantwortet_und_nummer_erneut_erfragt(notizen):
    """Kein LLM auf diesem Pfad: die Frage wird ehrlich beantwortet, die
    Nummer bleibt offen; die zweite unklare Antwort beendet ohne Nummer."""
    sit = _sit()
    flow._angebot(sit)
    r = flow.zug(sit, "Wie lange dauert das denn ungefähr?")
    assert "nicht genau sagen" in r["text"] and "Rufnummer" in r["text"]
    assert _offen(sit)
    r = flow.zug(sit, "Hm, weiß ich nicht so genau.")
    assert "rueckrufNummer" not in sit and "Sprechzeiten" in r["text"]


def test_meine_nummer_haben_sie_ohne_anrufer_id_ist_ehrlich(notizen):
    sit = _sit()
    flow._angebot(sit)
    r = flow.zug(sit, "Meine Nummer haben Sie doch.")
    assert "keine Nummer angezeigt" in r["text"] and "Rufnummer" in r["text"]
    assert _offen(sit)
    r = flow.zug(sit, "Die haben Sie doch.")
    assert "rueckrufNummer" not in sit  # zweimal -> ohne Nummer, keine Schleife


def test_anderes_anliegen_gewinnt_und_bricht_die_nummernfrage_ab(notizen):
    sit = _sit()
    s = gehirn.sammler(sit)
    flow._angebot(sit)
    r = flow.zug(sit, "Ich hätte gern noch einen Termin für meine Frau.")
    assert "rueckrufNummer" not in sit
    assert "Wann passt" in r["text"] and s["frage"] == "wunsch"
    assert any(e.get("w") == "rueckruf-nummer" and "abgebrochen" in str(e.get("d"))
               for e in (sit.get("_spur") or []))


def test_hirn_moduswechsel_bricht_die_nummernfrage_ab(notizen):
    """Die Intent-Schicht hat auf Absage geschaltet: die Verwaltung uebernimmt,
    die Nummernfrage wird nicht durchgedrueckt."""
    sit = _sit()
    s = gehirn.sammler(sit)
    flow._angebot(sit)
    s["modus"] = "absagen"
    sit["hirnModusNeu"] = True
    flow.zug(sit, "Ich möchte meinen anderen Termin absagen.")
    assert "rueckrufNummer" not in sit
    assert s["frage"] != "telefon"


# --- Bausteine in verwalten ----------------------------------------------------

def test_rueckruf_nummer_quellen_und_plausibilitaet():
    sit = _sit()
    s = gehirn.sammler(sit)
    assert verwalten.rueckruf_nummer(sit) == "" and verwalten.rueckruf_nummer_fehlt(sit)
    sit["callerPhone"] = "+49 177 1234567"
    assert verwalten.rueckruf_nummer(sit) == "01771234567"
    s["kontaktTelefon"] = "01519876543"  # Dritttermin: der Anrufer gewinnt vor der Leitung
    assert verwalten.rueckruf_nummer(sit) == "01519876543"
    s["telefon"] = "01601112222"
    assert verwalten.rueckruf_nummer(sit) == "01601112222"
    # eine bloss gehoerte Nummer zaehlt NIE
    s2 = gehirn.sammler(_sit())
    s2["telefonOffen"] = "01601112222"
    assert verwalten.rueckruf_nummer_fehlt({"tenant": {}, "sammler": s2})
    # Unplausibles aus der Leitung ("anonymous", zu kurz) zaehlt nicht
    sit3 = _sit()
    sit3["callerPhone"] = "anonymous"
    assert verwalten.rueckruf_nummer_fehlt(sit3)


def test_nachtragen_ohne_nummer_schreibt_nichts(notizen):
    sit = _sit()
    flow._angebot(sit)
    assert verwalten.rueckruf_nummer_nachtragen(sit) == ""
    assert len(notizen()) == 1
