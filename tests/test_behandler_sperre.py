"""W-BEHANDLER-SPERRE (Chef 13.09.2026) — offline, ohne LLM, ohne Netz.

Chef (wörtlich): "Dr. Nikolaou soll vorerst raus aus der telefonischen
Buchung." Live-Probe 13.09.: Bianca versprach Termine "bei Doktor Nikolaou"
und buchte still bei Doktor Petsas — falsche Ansage plus falsche Buchung.

Vertrag: ein gesperrter Behandler verschwindet aus Arztwahl, Slot-Suche und
Buchung, sein NAME bleibt aber bekannt (ehrliche Absage + freie Behandler
zur Wahl). Ohne ``telefonGesperrteBehandler`` ist alles byte-identisch.
"""

import copy

from bianca import arzt as arztmod, flow, gehirn, hintergrund
from kern import behandler_sperre, tenants as kern_tenants
from kern.tenants import laden

PETSAS = "zex5bmv5jfIHWVW6zHbg"


def _tenant() -> dict:
    return behandler_sperre.anwenden(laden("meddent"))


def _sit() -> dict:
    return {"tenant": _tenant(), "messages": [{"role": "system", "content": "x"}]}


def _namen(t: dict) -> list[str]:
    return [c.get("name") for c in t.get("calendars") or []]


# --- anwenden ----------------------------------------------------------------

def test_meddent_datei_sperrt_nikolaou():
    assert behandler_sperre.gesperrte_namen(laden("meddent")) == ["Nikolaou"]


def test_anwenden_entfernt_gesperrten_kalender_und_merkt_ihn():
    roh = laden("meddent")
    assert any("Nikolaou" in n for n in _namen(roh))
    t = behandler_sperre.anwenden(roh)
    assert not any("Nikolaou" in n for n in _namen(t)), _namen(t)
    assert [g["name"] for g in behandler_sperre.gesperrte_kalender(t)] == ["Dr. Nikolaou"]
    # Default bleibt Petsas (war nicht gesperrt).
    assert t["defaultCalendarId"] == PETSAS
    # Idempotent: zweites Anwenden aendert nichts mehr.
    vorher = copy.deepcopy(t)
    behandler_sperre.anwenden(t)
    assert t == vorher


def test_anwenden_ohne_sperrliste_ist_byte_identisch():
    roh = laden("meddent")
    roh.pop("telefonGesperrteBehandler", None)
    vorher = copy.deepcopy(roh)
    assert behandler_sperre.anwenden(roh) is roh
    assert roh == vorher


def test_gesperrter_default_rueckt_nach():
    t = {
        "telefonGesperrteBehandler": ["Nikolaou"],
        "defaultCalendarId": "nik",
        "calendars": [{"id": "nik", "name": "Dr. Nikolaou"}, {"id": "pet", "name": "Dr. Petsas"}],
    }
    behandler_sperre.anwenden(t)
    assert t["defaultCalendarId"] == "pet"
    assert _namen(t) == ["Dr. Petsas"]


def test_ist_gesperrt_wortweise_nicht_substring():
    t = {"telefonGesperrteBehandler": ["Niko"]}
    assert behandler_sperre.ist_gesperrt(t, "Dr. Nikolaou") is False
    t2 = {"telefonGesperrteBehandler": ["Nikolaou"]}
    assert behandler_sperre.ist_gesperrt(t2, "Doktor Georgios Nikolaou") is True
    assert behandler_sperre.ist_gesperrt(t2, "Dr. Petsas") is False


def test_db_kalender_mit_langform_werden_gesperrt():
    """Die CF liefert 'Doktor Georgios Nikolaou' — die Sperre traegt nur den
    Nachnamen und muss trotzdem greifen."""
    t = laden("meddent")
    t["calendars"] = [
        {"id": "a", "name": "Doktor Michael Petsas"},
        {"id": "b", "name": "Doktor Theodosios Patrikis, M.Sc."},
        {"id": "c", "name": "Doktor Georgios Nikolaou"},
    ]
    t["defaultCalendarId"] = "a"
    behandler_sperre.anwenden(t)
    assert [c["id"] for c in t["calendars"]] == ["a", "b"]


# --- Arztwahl / Prompt / STT -------------------------------------------------

def test_arztwahl_frage_ohne_nikolaou():
    frage = gehirn.arztwahl_frage(_tenant())
    assert "Nikolaou" not in frage, frage
    assert "Doktor Petsas oder Doktor Patrikis" in frage, frage


def test_behandler_reihe_ohne_nikolaou():
    namen = [c.get("name") for c in kern_tenants.behandler_reihe(_tenant())]
    assert namen == ["Dr. Petsas", "Dr. Patrikis"], namen


def test_prompt_behandlerzeile_ohne_nikolaou():
    from bianca.agent import _behandler_alle
    assert "Nikolaou" not in _behandler_alle(_tenant())


def test_stt_hoert_gesperrten_namen_weiter():
    kw = kern_tenants.stt_keywords(_tenant())
    assert any("Nikolaou" in k for k in kw), kw


# --- deute: Name erkannt, aber gesperrt ------------------------------------

def test_deute_liefert_gesperrt_statt_default():
    t = _tenant()
    d = arztmod.deute("Ich möchte einen Termin bei Doktor Nikolaou.", t)
    assert d and d["typ"] == "gesperrt", d
    assert d["calendarId"] == "" and "Nikolaou" in d["calendarName"]
    # Freie Behandler unveraendert.
    d2 = arztmod.deute("Ich möchte einen Termin bei Doktor Petsas.", t)
    assert d2 and d2["typ"] == "genannt" and d2["calendarId"] == PETSAS


def test_deute_verhoerter_gesperrter_name_im_doktor_kontext():
    d = arztmod.deute("Bei Doktor Nikolau bitte.", _tenant())
    assert d and d["typ"] == "gesperrt", d


def test_deute_korrektur_weg_vom_gesperrten():
    d = arztmod.deute("Nein, nicht Doktor Nikolaou — ich wollte zu Doktor Patrikis.", _tenant())
    assert d and d["typ"] == "genannt" and "Patrikis" in d["calendarName"], d


# --- Buchungsfluss: ehrliche Ansage + freie Wahl ----------------------------

def test_neupatient_nennt_nikolaou_hoert_absage_und_wahl():
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({"modus": "buchen", "warSchonMal": False, "frage": "arzt"})
        z = flow.zug(sit, "Bei Doktor Nikolaou bitte.")
        assert z is not None
        text = z["text"]
        assert "Nikolaou" in text and "nicht vergeben" in text, text
        assert "Doktor Petsas oder Doktor Patrikis" in text, text
        # KEIN Kalender gesetzt — nie still auf den Default.
        assert not (s.get("arzt") or {}).get("calendarId"), s.get("arzt")
        assert s["frage"] == "arzt"
        # Danach normal waehlen.
        z2 = flow.zug(sit, "Dann Doktor Patrikis.")
        assert z2 is not None
        assert (s.get("arzt") or {}).get("calendarName") == "Dr. Patrikis", s.get("arzt")
    finally:
        flow.hintergrund.anstossen = echt


def test_einstiegssatz_mit_gesperrtem_behandler_bucht_nicht_bei_ihm():
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({"modus": "buchen"})
        z = flow.zug(sit, "Ich hätte gern einen Termin zur Kontrolle bei Doktor Nikolaou.")
        assert z is not None
        assert "Nikolaou" in z["text"] and "nicht vergeben" in z["text"], z["text"]
        assert not (s.get("arzt") or {}).get("calendarId")
    finally:
        flow.hintergrund.anstossen = echt


def test_quittung_spricht_hinweis_genau_einmal():
    s = dict(gehirn.FELDER_START)
    s["arztGesperrtName"] = "Doktor Nikolaou"
    q = flow._quittung(s, {"arztGesperrt"})
    assert q.strip() == behandler_sperre.hinweis("Doktor Nikolaou")
    # Ohne frische Nennung: kein Hinweis mehr.
    assert "Nikolaou" not in flow._quittung(s, {"grund"})


# --- letzter_behandler / Kartei ---------------------------------------------

class _Antwort:
    status_code = 200

    def __init__(self, daten: dict):
        self._d = daten

    def json(self) -> dict:
        return self._d


def _kartei_antwort(calendar_id: str, calendar_name: str) -> _Antwort:
    return _Antwort({
        "status": "success",
        "lastAppointment": {
            "startIso": "2026-03-10T09:00:00+01:00",
            "calendarId": calendar_id,
            "calendarName": calendar_name,
            "doctorName": calendar_name,
            "visitMotiveName": "Kontrolle",
        },
    })


class _SofortThread:
    """Ersatz fuer threading.Thread: fuehrt target beim start() sofort aus."""

    def __init__(self, target=None, daemon=None, **kw):
        self._target = target

    def start(self) -> None:
        if self._target:
            self._target()


def _cf_stummschalten(monkeypatch, antwort: _Antwort) -> None:
    """masPatientLastDoctor ohne Netz: arzt.letzter_behandler postet direkt
    per httpx — hier bekommt es die gestellte Kartei-Antwort."""
    monkeypatch.setattr(arztmod.httpx, "post", lambda *a, **k: antwort)


def test_letzter_behandler_gesperrt_liefert_keinen_kalender(monkeypatch):
    t = _tenant()
    _cf_stummschalten(monkeypatch, _kartei_antwort("nik-intern", "Dr. Nikolaou"))
    info = arztmod.letzter_behandler(t, "p1")
    assert info["ok"] and info.get("gesperrt") is True
    assert info["calendarId"] == ""  # nie in den internen Kalender
    assert "Nikolaou" in info["calendarName"]
    assert info["lastIso"].startswith("2026-03-10") and info["grund"] == "Kontrolle"


def test_letzter_behandler_frei_unveraendert(monkeypatch):
    t = _tenant()
    _cf_stummschalten(monkeypatch, _kartei_antwort(PETSAS, "Dr. Petsas"))
    info = arztmod.letzter_behandler(t, "p1")
    assert info["ok"] and not info.get("gesperrt")
    assert info["calendarId"] == PETSAS


def test_kartei_von_anrufer_gesperrt_fragt_ehrlich_nach_behandler(monkeypatch):
    """Bestandspatient, zuletzt bei Nikolaou: Kartei traegt gesperrt=True ohne
    calendarId; die Behandler-Frage sagt es ehrlich und bietet die freien an —
    nie 'Soll der neue Termin wieder bei Doktor Nikolaou sein?'."""
    sit = _sit()
    sit["anrufer"] = {"patientId": "p1", "vorname": "Anna", "nachname": "Muster"}
    _cf_stummschalten(monkeypatch, _kartei_antwort("nik-intern", "Dr. Nikolaou"))
    # Die Kartei laeuft als Daemon-Thread — synchron abwarten.
    monkeypatch.setattr(hintergrund.threading, "Thread", _SofortThread)
    hintergrund.kartei_von_anrufer(sit)
    k = sit.get("anruferKartei") or {}
    assert k.get("gesperrt") is True and k.get("calendarId") == "", k
    assert k.get("letzterBesuch", "").startswith("2026-03-10")
    # Kein automatisches Binden an den gesperrten Kalender.
    assert gehirn.anrufer_behandler_uebernehmen(sit) is False
    assert gehirn.arzt_check_frage(sit) == ""
    frage = gehirn._arzt_gesperrt_frage(sit)
    assert "Nikolaou" in frage and "nicht vergeben" in frage, frage
    assert "Doktor Petsas oder Doktor Patrikis" in frage, frage
    # naechste_frage nimmt genau diesen Weg.
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True, "grund": "Kontrolle"})
    art, text = gehirn.naechste_frage(sit)
    assert art == "arzt" and "Nikolaou" in text and "Doktor Petsas" in text, (art, text)
