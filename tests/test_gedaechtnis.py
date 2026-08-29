"""W-GEDAECHTNIS (Chef 29.08.2026): Gesprächs-Reports ins MAS-Praxisgedächtnis
und Anrufer-Kontext im Hintergrund — offline, ohne Netz (httpx gestubbt)."""

from __future__ import annotations

import os
import threading

import kern.gedaechtnis as ged
from bianca.prompt import system_prompt as bianca_prompt
from lisa.prompt import system_prompt as lisa_prompt


def _sit_bianca(**extra) -> dict:
    sit = {
        "id": "abc123",
        "stimme": "Bianca",
        "startedAt": "2026-08-29T08:00:00+00:00",
        "sammler": {
            "vorname": "Martin", "nachname": "Berger",
            "telefon": "0177 1234567", "grund": "Zahnschmerzen",
            "modus": "buchen", "patientId": "PAT9",
            "arzt": {"calendarName": "Dr. Patrikis"},
        },
        "messages": [
            {"role": "user", "content": "Ich habe furchtbare Angst vor Spritzen."},
        ],
        "zuege": [],
        "tools": [{"name": "book_slot", "ok": True}],
        "lastBook": {"booked": True, "slotIso": "2026-09-02T09:00", "dryRun": False},
    }
    sit.update(extra)
    return sit


def test_zusammenfassung_terminpopup_stil():
    text = ged.zusammenfassung(_sit_bianca())
    assert text.startswith("Laut Anruf (Bianca): Martin Berger — ")
    assert "Termin vereinbart am 02.09. um 09:00 Uhr bei Dr. Patrikis wegen Zahnschmerzen" in text
    assert "Patient erwähnt" in text and "Angst vor Spritzen" in text


def test_zusammenfassung_notiz_und_absage():
    sit = _sit_bianca(lastBook=None, praxisNotiz="Termin nicht gefunden — bitte prüfen")
    sit["lastCancel"] = {"ok": True, "slotIso": "2026-09-02T09:00"}
    text = ged.zusammenfassung(sit)
    assert "bestehenden Termin abgesagt (02.09. um 09:00 Uhr)" in text
    assert "Rückruf-Notiz an die Praxis: Termin nicht gefunden" in text


def test_zusammenfassung_ohne_kalender():
    sit = _sit_bianca(lastBook=None, tools=[])
    sit["sammler"]["grund"] = ""
    sit["sammler"]["modus"] = ""
    text = ged.zusammenfassung(sit)
    assert "Gespräch ohne Kalenderänderung" in text


def test_event_bianca_eingehend_matched():
    ev = ged._event(_sit_bianca())
    assert ev["id"] == "telefonki:bianca_call:abc123"
    assert ev["channel"] == "bianca_call" and ev["direction"] == "in"
    assert ev["counterparty"] == {"kind": "patient", "name": "Martin Berger", "ref": "01771234567"}
    assert ev["subject"]["patientId"] == "PAT9" and ev["subject"]["matchStatus"] == "matched"
    assert ev["signals"] == {"appointmentRequest": True}
    assert ev["status"] == "none" and ev["ts"] > 0


def test_event_notiz_wird_offen():
    ev = ged._event(_sit_bianca(lastBook=None, praxisNotiz="Rückruf bitte"))
    assert ev["status"] == "open"
    assert ev["signals"]["callbackRequested"] is True


def test_event_lisa_ausgehend_unmatched():
    sit = {
        "id": "x9", "stimme": "Lisa", "auftrag": "Recall-Anruf",
        "patient": {"name": "Petra Müller", "phone": "01770000002"},
        "messages": [{"role": "user", "content": "Ja, gerne."}],
    }
    ev = ged._event(sit)
    assert ev["channel"] == "lisa_call" and ev["direction"] == "out"
    assert ev["subject"]["matchStatus"] == "unmatched"
    assert ev["counterparty"]["name"] == "Petra Müller"


def test_report_sendet_und_merkt():
    calls = []

    class _R:
        status_code = 201

        @staticmethod
        def json():
            return {"ok": True, "created": True}

    echt = ged.httpx.post
    ged.httpx.post = lambda url, **kw: calls.append((url, kw)) or _R()
    try:
        sit = _sit_bianca()
        out = ged.report_senden(sit)
        assert out and out["ok"] and out["created"]
        url, kw = calls[0]
        assert url.endswith("/brain/events")
        assert kw["headers"]["X-Client-Id"]
        assert kw["json"]["summary"].startswith("Laut Anruf (Bianca)")
        assert sit["gedaechtnisReport"]["id"] == "telefonki:bianca_call:abc123"
    finally:
        ged.httpx.post = echt


def test_report_leeres_gespraech_schweigt():
    echt = ged.httpx.post
    ged.httpx.post = lambda *a, **k: (_ for _ in ()).throw(AssertionError("kein Netz erwartet"))
    try:
        sit = {"id": "leer1", "stimme": "Bianca", "messages": [], "zuege": [], "tools": []}
        assert ged.report_senden(sit) is None
    finally:
        ged.httpx.post = echt


def test_kontext_telefon_vor_karteikarte():
    def fake_get(url, params=None, **kw):
        class _R:
            @staticmethod
            def json():
                if "caller-context" in url:
                    return {"ok": True, "found": True, "name": "Berger",
                            "context": "Praxisgedächtnis zu dieser Rufnummer: - gestern: Lisa hat angerufen."}
                raise AssertionError("karteikarte darf nicht mehr laufen")
        return _R()

    echt = ged.httpx.get
    ged.httpx.get = fake_get
    try:
        text = ged._kontext_holen("01771234567", "Martin Berger")
        assert "Rufnummer" in text
    finally:
        ged.httpx.get = echt


def test_kontext_suche_faengt_queryrecent_luecke():
    """caller-context verliert bei >800 Events die neuesten (queryRecent asc) —
    dann MUSS die Gedächtnis-Suche (queryLatest) die Nummer trotzdem finden."""
    def fake_get(url, params=None, **kw):
        class _R:
            @staticmethod
            def json():
                if "caller-context" in url:
                    return {"ok": True, "found": False, "context": ""}
                if "/brain/search" in url:
                    assert params["q"] == "01770000001" and params["kind"] == "event"
                    return {"ok": True, "results": [
                        {"kind": "case", "ts": 9, "snippet": "egal"},
                        {"kind": "event", "ts": 1767100000000, "status": "open",
                         "snippet": "Laut Anruf (Lisa): Kasimir Probefall nicht erreicht.",
                         "counterpartyName": "Kasimir Probefall"},
                    ]}
                raise AssertionError(url)
        return _R()

    echt = ged.httpx.get
    ged.httpx.get = fake_get
    try:
        text = ged._kontext_holen("01770000001", "")
        assert text.startswith("Praxisgedächtnis zu dieser Rufnummer (vermutlich Kasimir Probefall):")
        assert "nicht erreicht. (noch offen)" in text
    finally:
        ged.httpx.get = echt


def test_kontext_karteikarte_faltet_events():
    def fake_get(url, params=None, **kw):
        class _R:
            @staticmethod
            def json():
                assert "karteikarte" in url and params["name"] == "Martin Berger"
                return {"ok": True, "events": [
                    {"ts": 1000, "summary": "Alt und egal", "status": "none"},
                    {"ts": 1767000000000, "summary": "Laut Anruf: Termin verschoben.", "status": "none"},
                    {"ts": 1767100000000, "summary": "Rückruf erbeten.", "status": "open"},
                ]}
        return _R()

    echt = ged.httpx.get
    ged.httpx.get = fake_get
    try:
        text = ged._kontext_holen("", "Martin Berger")
        assert text.startswith("Praxisgedächtnis zu Martin Berger:")
        assert "Rückruf erbeten. (noch offen)" in text
        # Neuestes zuerst.
        assert text.index("Rückruf erbeten") < text.index("Termin verschoben")
    finally:
        ged.httpx.get = echt


def test_kontext_anstossen_key_gesichert():
    laeufe = []
    echt_thread = ged.threading.Thread

    class _SofortThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._target, self._args = target, args

        def start(self):
            laeufe.append(self._args)

    echt_holen = ged._kontext_holen
    ged.threading.Thread = _SofortThread
    try:
        sit = _sit_bianca()
        ged.kontext_anstossen(sit)
        ged.kontext_anstossen(sit)  # gleicher Stand -> kein zweiter Lauf
        assert len(laeufe) == 1
        sit["sammler"]["telefon"] = "0177 9999999"  # neuer Stand -> neuer Lauf
        ged.kontext_anstossen(sit)
        assert len(laeufe) == 2
    finally:
        ged.threading.Thread = echt_thread
        ged._kontext_holen = echt_holen


def test_kontext_arbeit_schreibt_in_sitzung():
    echt = ged._kontext_holen
    ged._kontext_holen = lambda t, n: "Praxisgedächtnis zu Martin Berger: - 28.08.: Rückruf erbeten."
    try:
        sit = _sit_bianca()
        sit["gedaechtnisKey"] = "01771234567|martin berger"
        ged._kontext_arbeit(sit, "01771234567", "Martin Berger", sit["gedaechtnisKey"])
        assert "Rückruf erbeten" in sit["gedaechtnis"]
    finally:
        ged._kontext_holen = echt


def test_notaus_schaltet_alles_ab():
    os.environ["MAS_GEDAECHTNIS"] = "0"
    try:
        assert ged.enabled() is False
        assert ged.report_senden(_sit_bianca()) is None
        sit = _sit_bianca()
        ged.kontext_anstossen(sit)
        assert "gedaechtnisKey" not in sit
    finally:
        os.environ.pop("MAS_GEDAECHTNIS", None)
    assert ged.enabled() is True


def test_prompt_block_beide_stimmen():
    sit = _sit_bianca(gedaechtnis="Praxisgedächtnis zu Martin Berger:\n- 28.08.: Rückruf erbeten.")
    block = ged.kontext_block(sit)
    assert block.startswith("\nPRAXISGEDÄCHTNIS")
    b = bianca_prompt(praxis="Testpraxis", behandler="Dr. T", kontext=block)
    assert "PRAXISGEDÄCHTNIS (frühere Kontakte)" in b and "Rückruf erbeten" in b
    l = lisa_prompt(praxis="Testpraxis", behandler="Dr. T", auftrag="Recall",
                    patient="Martin Berger", kontext=block)
    assert "PRAXISGEDÄCHTNIS (frühere Kontakte)" in l and "Rückruf erbeten" in l
    assert ged.kontext_block({"gedaechtnis": ""}) == ""
