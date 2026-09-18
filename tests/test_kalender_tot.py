"""W-KALENDER-TOT (17.09.2026) — offline, ohne Netz.

Befund aus der Gesamtauswertung aller Bianca-Anrufe 14.–17.09.: bei Blessing
lieferte ``masPatientLastDoctor`` fuer Bestandspatienten die calendarId des
ALTEN Termins — ``TphQRh53x8SToBSa8DdB``, ein Kalender, den die Praxis nicht
mehr fuehrt. Jede Slotsuche damit lief auf HTTP 500 („Could not load doctor“):
61 Fehler in 10 Anrufen, jedes Mal „Der Terminkalender antwortet gerade nicht“
plus Rueckruf-Notiz statt Termin.

Vertrag: eine Kalender-Id aus der Kartei zaehlt nur, wenn der Mandant sie
heute fuehrt. Sonst wird der Behandler ueber den Namen aufgeloest (einziger
Behandler-Kalender zaehlt auch); ohne Treffer bleibt die Id leer und der
Fluss fragt ehrlich nach dem Behandler. Besuch und Grund bleiben fuer den
Rueckblick erhalten. Live-Ids bleiben byte-identisch.
"""

from bianca import arzt as arztmod, gehirn, hintergrund
from kern.tenants import laden

TOT = "TphQRh53x8SToBSa8DdB"
BLESSING = "8krcWh7AuXEfgWc1blzQ"
PETSAS = "zex5bmv5jfIHWVW6zHbg"
PATRIKIS = "RHYdoQFD7oAhqIepLzC2"


class _Antwort:
    status_code = 200

    def __init__(self, d: dict):
        self._d = d

    def json(self) -> dict:
        return self._d


def _kartei(calendar_id: str, name: str, *, naechster: dict | None = None) -> _Antwort:
    d = {
        "status": "success",
        "lastAppointment": {
            "startIso": "2026-05-04T10:00:00+02:00",
            "calendarId": calendar_id,
            "calendarName": name,
            "doctorName": name,
            "visitMotiveName": "Hautkrebsscreening",
        },
    }
    if naechster:
        d["nextAppointment"] = naechster
    return _Antwort(d)


class _SofortThread:
    def __init__(self, target=None, daemon=None, **kw):
        self._target = target

    def start(self) -> None:
        if self._target:
            self._target()


def _cf(monkeypatch, antwort: _Antwort) -> None:
    monkeypatch.setattr(arztmod.httpx, "post", lambda *a, **k: antwort)


# --- letzter_behandler ---------------------------------------------------------

def test_blessing_toter_kalender_wird_auf_den_einzigen_behandler_aufgeloest(monkeypatch):
    t = laden("blessing")
    _cf(monkeypatch, _kartei(TOT, "Doktor Blessing"))
    info = arztmod.letzter_behandler(t, "p1")
    assert info["ok"] and info["war"]
    assert info["calendarId"] == BLESSING, info
    assert info["kalenderTot"] is True
    # Besuch und Grund bleiben — der Rueckblick braucht sie.
    assert info["lastIso"].startswith("2026-05-04")
    assert info["grund"] == "Hautkrebsscreening"


def test_toter_kalender_mit_bekanntem_namen_nimmt_den_namens_kalender(monkeypatch):
    t = laden("meddent")
    _cf(monkeypatch, _kartei(TOT, "Dr. Patrikis"))
    info = arztmod.letzter_behandler(t, "p1")
    assert info["calendarId"] == PATRIKIS
    assert info["kalenderTot"] is True


def test_toter_kalender_ohne_namens_treffer_bleibt_leer_statt_default(monkeypatch):
    """Zwei oder mehr Behandler und ein unbekannter Name: NICHT still den
    Standard-Behandler binden — der Fluss soll fragen."""
    t = laden("meddent")
    _cf(monkeypatch, _kartei(TOT, "Dr. Fremd"))
    info = arztmod.letzter_behandler(t, "p1")
    assert info["ok"] and info["war"]
    assert info["calendarId"] == ""
    assert info["kalenderTot"] is True


def test_lebender_kalender_bleibt_byte_identisch(monkeypatch):
    t = laden("meddent")
    _cf(monkeypatch, _kartei(PETSAS, "Dr. Petsas"))
    info = arztmod.letzter_behandler(t, "p1")
    assert info["calendarId"] == PETSAS
    assert info["kalenderTot"] is False


def test_ohne_kalenderliste_wird_historische_id_nicht_verwendet(monkeypatch):
    """Ohne heutige Kalenderliste ist die alte Id nicht verifizierbar.
    Lieber Behandler neu klären als einen gelöschten Kalender aufrufen."""
    _cf(monkeypatch, _kartei(TOT, "Dr. Irgendwer"))
    info = arztmod.letzter_behandler({"clientId": "x", "locationId": "y"}, "p1")
    assert info["calendarId"] == ""
    assert info["kalenderTot"] is True


def test_kalender_tot_helfer():
    t = laden("meddent")
    assert arztmod._kalender_tot(t, TOT) is True
    assert arztmod._kalender_tot(t, PETSAS) is False
    assert arztmod._kalender_tot(t, "") is False
    assert arztmod._kalender_tot({}, TOT) is True


# --- Hintergrund: Kartei zur Rufnummer -------------------------------------------

def test_kartei_von_anrufer_toter_kalender_ohne_bindung_aber_mit_rueckblick(monkeypatch):
    """Bestandspatient bei MedDent, letzter Termin auf einem toten Kalender
    mit unbekanntem Namen: die Kartei kommt (Rueckblick), aber ohne
    calendarId — arzt_check_frage bleibt leer, der Fluss fragt den Behandler,
    und NIE wird der tote Kalender fuer eine Slotsuche gebunden."""
    sit = {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}
    sit["anrufer"] = {"patientId": "p1", "vorname": "Anna", "nachname": "Muster"}
    _cf(monkeypatch, _kartei(TOT, "Dr. Fremd"))
    monkeypatch.setattr(hintergrund.threading, "Thread", _SofortThread)
    hintergrund.kartei_von_anrufer(sit)
    k = sit.get("anruferKartei")
    assert isinstance(k, dict) and k, sit.get("anruferKartei")
    assert k["calendarId"] == ""
    assert k["letzterBesuch"].startswith("2026-05-04")
    assert gehirn.arzt_check_frage(sit) == ""
    assert gehirn.anrufer_behandler_uebernehmen(sit) is False
    assert not (gehirn.sammler(sit).get("arzt") or {}).get("calendarId")


def test_kartei_von_anrufer_blessing_toter_kalender_bindet_die_lebende_aerztin(monkeypatch):
    sit = {"tenant": laden("blessing"), "messages": [{"role": "system", "content": "x"}]}
    sit["anrufer"] = {"patientId": "p1", "vorname": "Anna", "nachname": "Muster"}
    _cf(monkeypatch, _kartei(TOT, "Doktor Blessing"))
    monkeypatch.setattr(hintergrund.threading, "Thread", _SofortThread)
    hintergrund.kartei_von_anrufer(sit)
    k = sit.get("anruferKartei")
    assert isinstance(k, dict) and k["calendarId"] == BLESSING
    assert TOT not in str(k)
