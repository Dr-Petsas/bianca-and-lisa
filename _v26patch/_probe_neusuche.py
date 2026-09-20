"""V2.6-Container: Neusuche nach Ablehnung, ohne Netz."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bianca import gehirn, verwalten
from kern.slots import parse_slot_wish, pick_slots

TZ = ZoneInfo("Europe/Berlin")


def _iso(tage, h, m=0):
    d = datetime.now(TZ).replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=tage)
    return d.isoformat(timespec="seconds")


def main():
    live = "Ja, ich möchte bitte den Termin um 12 Uhr verschieben auf Dienstag 13.30 Uhr."
    w = parse_slot_wish(live)
    assert w and w.get("weekday") == 2 and w.get("hour") == 13 and w.get("minute") == 30, w
    print("parse Live-Satz ok", w)
    w2 = parse_slot_wish("Ich möchte übermorgen um 13.30 Uhr.")
    assert w2 and w2.get("hour") == 13 and w2.get("minute") == 30, w2
    print("parse übermorgen 13.30 ok", w2)

    # naechster Dienstag / Montag relativ zu heute
    heute = datetime.now(TZ)
    bis_mo = (7 - heute.weekday()) % 7
    if bis_mo == 0:
        bis_mo = 7
    montag = _iso(bis_mo, 9, 15)
    dienstag12 = _iso(bis_mo + 1, 12, 15)
    dienstag13 = _iso(bis_mo + 1, 13, 0)
    dienstag1330 = _iso(bis_mo + 1, 13, 30)
    aus = pick_slots(
        [montag, dienstag12, dienstag13, dienstag1330],
        wish={"weekday": 2, "hour": 13, "minute": 30},
    )
    isos = [s["iso"][:16] for s in aus["slots"]]
    assert montag[:16] not in isos, isos
    assert dienstag1330[:16] in isos, isos
    assert aus["wishMatched"] is True
    print("pick 13:30 vor 13:00 ok", isos)

    sit = {"tenant": {"id": "meddent", "calendars": []}, "messages": [{"role": "system", "content": "x"}]}
    s = gehirn.sammler(sit)
    alt1, alt2, neu = _iso(1, 9, 15), _iso(1, 11, 45), dienstag1330
    s.update({
        "modus": "verschieben", "phase": "verschieb_angebot", "frage": "slotwahl",
        "wunsch": {"weekday": 2, "hour": 13, "minute": 30},
    })
    sit["offered"] = [{"iso": alt1}, {"iso": alt2}]
    sit["gefunden"] = [{
        "id": "t1", "iso": _iso(2, 10, 10), "calendarId": "c1",
        "doctorName": "Dr. X", "motivId": "k", "motivName": "K",
    }]
    sit["verwaltenTermin"] = "t1"
    echt = verwalten.kal.find_slots_behandler
    verwalten.kal.find_slots_behandler = lambda *a, **k: {"ok": True, "slots": [alt1, alt2, neu]}
    try:
        text = verwalten._verschieb_angebot(sit, None)
    finally:
        verwalten.kal.find_slots_behandler = echt
    offered = [o["iso"][:16] for o in sit.get("offered") or []]
    assert alt1[:16] not in offered and alt2[:16] not in offered, offered
    assert dienstag1330[:16] in offered, offered
    print("neusuche ohne Altangebot ok", offered, text.get("text"))
    print("ALLE GRUEN")


if __name__ == "__main__":
    main()
