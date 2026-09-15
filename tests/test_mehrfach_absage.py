"""W-MEHRFACH-ABSAGE (15.09.2026): "beide/alle/den ersten und den zweiten"
sagen mehrere vorgelesene Termine gemeinsam ab — EINE Rueckbestaetigung, dann
nacheinander ueber cancel-by-id, Teilfehler ehrlich, schleifenfreier Abschluss.

Der wichtigere Teil sind die Gegenproben: nie "beide abgesagt", wenn nur ein
Werkzeug erfolgreich war; "Nein" laesst alles bestehen; ein einzelnes "den
ersten" bleibt der bewaehrte Einzelweg.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bianca import flow, gehirn, verwalten  # noqa: E402
from kern.tenants import laden  # noqa: E402


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


ZWEI = {
    "ok": True,
    "patient": {"id": "pat-1", "firstName": "Martin", "lastName": "Berger"},
    "appointments": [
        {
            "id": "apt-1", "iso": "2026-09-03T10:00", "date": "2026-09-03",
            "calendarId": "cal-1", "doctorName": "Dr. Petsas",
            "motivId": "vm-1", "motivName": "Kontrolluntersuchung",
            "spoken": "am Donnerstag, den dritten September um zehn Uhr",
        },
        {
            "id": "apt-2", "iso": "2026-09-10T14:00", "date": "2026-09-10",
            "calendarId": "cal-1", "doctorName": "Dr. Petsas",
            "motivId": "vm-1", "motivName": "Kontrolluntersuchung",
            "spoken": "am Donnerstag, den zehnten September um vierzehn Uhr",
        },
    ],
}


def _bis_wahl(sit, monkeypatch, cancel):
    """Fluss bis zur Termin-Wahl mit zwei gefundenen Terminen treiben."""
    monkeypatch.setattr(verwalten.kal, "find_patient_appointments",
                        lambda t, c: {k: (list(v) if isinstance(v, list) else v)
                                      for k, v in ZWEI.items()})
    monkeypatch.setattr(verwalten.kal, "cancel_by_id", cancel)
    monkeypatch.setattr(verwalten.hintergrund, "anstossen", lambda sit: None)
    z1 = flow.zug(sit, "Guten Tag, ich möchte meine Termine absagen.")
    assert z1 and "nachname" in z1["text"].lower()
    z2 = flow.zug(sit, "Berger.")
    assert z2 and "mehrere termine" in z2["text"].lower()
    assert gehirn.sammler(sit)["phase"] == "wahl"
    return z2


def test_mehrfach_auswahl_erkennung():
    zwei = ZWEI["appointments"]
    assert len(verwalten._mehrfach_auswahl("beide", zwei)) == 2
    assert len(verwalten._mehrfach_auswahl("alle absagen", zwei)) == 2
    assert len(verwalten._mehrfach_auswahl("den ersten und den zweiten", zwei)) == 2
    # Einzelwahl ist KEIN Mehrfach-Wunsch.
    assert verwalten._mehrfach_auswahl("den ersten", zwei) == []
    assert verwalten._mehrfach_auswahl("den zweiten bitte", zwei) == []
    # Nur ein Termin: nie Mehrfach.
    assert verwalten._mehrfach_auswahl("beide", zwei[:1]) == []


def test_beide_absagen_sammelbestaetigung_und_beide_weg(monkeypatch):
    aufrufe = []

    def _cancel(t, c, aid):
        aufrufe.append(aid)
        return {"ok": True, "cancelled": True, "appointmentId": aid,
                "spoken": "Der Termin ist abgesagt."}

    sit = _sit()
    _bis_wahl(sit, monkeypatch, _cancel)

    # "Beide." -> EINE gemeinsame Rueckbestaetigung, noch nichts abgesagt.
    z = flow.zug(sit, "Beide bitte.")
    assert z and "wirklich" in z["text"].lower()
    assert gehirn.sammler(sit)["phase"] == "mehrfach_bestaetigen"
    assert aufrufe == [], "vor dem Ja darf nichts abgesagt sein"

    # "Ja." -> beide nacheinander abgesagt.
    z = flow.zug(sit, "Ja, bitte.")
    assert aufrufe == ["apt-1", "apt-2"]
    low = z["text"].lower()
    assert "abgesagt" in low
    assert "neuen termin" in low  # schleifenfreier Abschluss (neubuchung)
    assert gehirn.sammler(sit)["frage"] == "neubuchung"


def test_beide_absagen_teilfehler_ehrlich(monkeypatch):
    """Nur der erste klappt — nie 'beide abgesagt' behaupten."""
    def _cancel(t, c, aid):
        if aid == "apt-1":
            return {"ok": True, "cancelled": True, "appointmentId": aid}
        return {"ok": False, "spoken": "Das hat nicht geklappt."}

    sit = _sit()
    _bis_wahl(sit, monkeypatch, _cancel)
    flow.zug(sit, "Beide.")
    z = flow.zug(sit, "Ja.")
    low = z["text"].lower()
    assert "abgesagt sind" in low  # der erfolgreiche Teil
    assert "nicht geklappt" in low  # der Fehler ehrlich benannt
    assert "kümmert sich" in low


def test_beide_absagen_nein_behaelt_termine(monkeypatch):
    aufrufe = []

    def _cancel(t, c, aid):
        aufrufe.append(aid)
        return {"ok": True, "cancelled": True, "appointmentId": aid}

    sit = _sit()
    _bis_wahl(sit, monkeypatch, _cancel)
    flow.zug(sit, "Beide.")
    z = flow.zug(sit, "Nein, doch nicht.")
    assert aufrufe == [], "Nein sagt nichts ab"
    assert "bestehen" in z["text"].lower()
    assert gehirn.sammler(sit)["phase"] == "wahl"


def test_einzelwahl_bleibt_einzelweg(monkeypatch):
    """'den ersten' darf nie den Mehrfach-Weg zuenden."""
    def _cancel(t, c, aid):
        return {"ok": True, "cancelled": True, "appointmentId": aid}

    sit = _sit()
    _bis_wahl(sit, monkeypatch, _cancel)
    z = flow.zug(sit, "Den ersten bitte.")
    # Einzelbestaetigung (kein Mehrfach): "wirklich absagen … ?"
    assert gehirn.sammler(sit)["phase"] == "absage_bestaetigen"
    assert "absagen" in z["text"].lower()
