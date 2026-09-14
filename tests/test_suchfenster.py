"""W-SUCHFENSTER (14.09.2026): Termine ueber 6 Monate statt nur im laufenden.

Chef: "bianca macht nur im laufenden monat termine ... das fenster muss auf
6 monate erweitert werden". Live-Anrufe:

* da746a65 — Schmerzen, Zimmer-Weg (Thaler): kein Akut-Slot, KEIN Ersatz-
  Motiv auf dem Zimmer-Weg -> "kein freier Termin" + Rueckruf.
* 5aa87268 — "heute um halb zwei oder 14 Uhr": 20 Slots im Vorrat, keiner
  heute -> pick_slots lieferte [] -> "kein freier Termin" bei vollem Kalender.
* Monatswuensche ("im Oktober", "Ende November", "in drei Wochen") waren
  KEIN Wunsch — die Suche lief ab heute, die 20 Plattform-Slots endeten
  mitten im laufenden Monat.

Vier Bausteine, hier festgenagelt:
1. Parser: Monat/Drittel/relativer Abstand -> von/bis bzw. minDaysAhead;
   Uhrzeit ohne "Uhr" ("halb zwei", "um zwei").
2. pick_slots: Zeitraum-Filter; ohne Treffer das NAECHSTBESTE (als solches
   markiert) statt einer leeren Liste.
3. start_datum: Zeitraum/Wochentag/Abstand setzen den Suchstart.
4. find_slots: bei ungedecktem Wunsch seitenweise vorwaerts (max. SEITEN_MAX
   Seiten, 6-Monats-Horizont); Zimmer-Weg mit Kontroll-Ersatz.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from bianca import flow, gehirn, verwalten
from kern import calendar as kal
from kern import slots as sl
from kern.slots import parse_slot_wish, pick_slots, zeitraum_aus_text
from kern.tenants import laden

TZ = ZoneInfo("Europe/Berlin")
HEUTE = date(2026, 9, 14)  # Montag


def _k(w: dict | None) -> dict:
    return {a: b for a, b in (w or {}).items() if b not in (None, 0, [], "")}


def _iso(tag: date, h: int, m: int = 0) -> str:
    return datetime(tag.year, tag.month, tag.day, h, m, tzinfo=TZ).isoformat(timespec="seconds")


def _heute() -> date:
    return datetime.now(TZ).date()


# --- 1. Parser ---------------------------------------------------------------

def test_monat_wird_zeitraum_nie_in_der_vergangenheit():
    assert zeitraum_aus_text("im Oktober", HEUTE) == ("2026-10-01", "2026-10-31")
    # vergangener Monat rollt ins naechste Jahr; "Mai" (3 Buchstaben) zaehlt
    assert zeitraum_aus_text("im Mai", HEUTE) == ("2027-05-01", "2027-05-31")
    assert zeitraum_aus_text("im März", HEUTE) == ("2027-03-01", "2027-03-31")
    assert zeitraum_aus_text("im Maerz", HEUTE) == ("2027-03-01", "2027-03-31")
    # laufender Monat bleibt der laufende
    assert zeitraum_aus_text("noch im September", HEUTE) == ("2026-09-01", "2026-09-30")


def test_monatsdrittel_und_offene_grenzen():
    assert zeitraum_aus_text("Anfang November bitte", HEUTE) == ("2026-11-01", "2026-11-10")
    assert zeitraum_aus_text("Mitte Oktober", HEUTE) == ("2026-10-11", "2026-10-20")
    assert zeitraum_aus_text("Ende Oktober", HEUTE) == ("2026-10-21", "2026-10-31")
    assert zeitraum_aus_text("ab Dezember", HEUTE) == ("2026-12-01", "")
    assert zeitraum_aus_text("bis Oktober", HEUTE) == ("", "2026-10-31")


def test_relative_monate():
    assert zeitraum_aus_text("nächsten Monat", HEUTE) == ("2026-10-01", "2026-10-31")
    assert zeitraum_aus_text("naechsten Monat", HEUTE) == ("2026-10-01", "2026-10-31")
    assert zeitraum_aus_text("kommenden Monat", HEUTE) == ("2026-10-01", "2026-10-31")
    assert zeitraum_aus_text("übernächsten Monat", HEUTE) == ("2026-11-01", "2026-11-30")
    assert zeitraum_aus_text("Mitte nächsten Monats", HEUTE) == ("2026-10-11", "2026-10-20")
    assert zeitraum_aus_text("noch in diesem Monat", HEUTE) == ("2026-09-01", "2026-09-30")
    # Jahreswechsel: Dezember + 1 = Januar des Folgejahres
    assert zeitraum_aus_text("nächsten Monat", date(2026, 12, 3)) == ("2027-01-01", "2027-01-31")


def test_parse_slot_wish_traegt_zeitraum_und_wochentag_zusammen():
    w = parse_slot_wish("Ende Oktober, gern ein Donnerstag nachmittags")
    assert w["weekday"] == 4
    assert (w["hourMin"], w["hourMax"]) == (12, 18)
    # von/bis relativ zu HEUTE des Testlaufs: Monat Oktober, Drittel "Ende"
    assert w["von"].endswith("-10-21") and w["bis"].endswith("-10-31")
    assert w["date"] is None


def test_konkreter_tag_schlaegt_zeitraum_im_selben_satz():
    w = parse_slot_wish("am 3. Oktober")
    assert w["date"].endswith("-10-03")
    assert w["von"] is None and w["bis"] is None


def test_relativer_abstand_in_wochen_monaten_tagen():
    assert _k(parse_slot_wish("in drei Wochen")) == {"minDaysAhead": 21}
    assert _k(parse_slot_wish("in zwei Monaten")) == {"minDaysAhead": 60}
    assert _k(parse_slot_wish("in vierzehn Tagen")) == {"minDaysAhead": 14}
    assert _k(parse_slot_wish("in einer Woche")) == {"minDaysAhead": 7}
    assert _k(parse_slot_wish("in etwa 6 Wochen")) == {"minDaysAhead": 42}
    # gedeckelt auf das 6-Monats-Fenster
    assert parse_slot_wish("in 12 Monaten")["minDaysAhead"] == sl.FENSTER_TAGE


def test_uhrzeit_ohne_uhr_halb_zwei_ist_dreizehn():
    """Anruf 5aa87268: 'heute um halb zwei' — der Parser kannte nur '... Uhr'."""
    assert _k(parse_slot_wish("heute um halb zwei")) == {"hour": 13}
    assert _k(parse_slot_wish("um halb neun")) == {"hour": 8}
    assert _k(parse_slot_wish("halb sechs")) == {"hour": 17}
    assert _k(parse_slot_wish("um zwei")) == {"hour": 14}
    assert _k(parse_slot_wish("gegen drei")) == {"hour": 15}
    assert _k(parse_slot_wish("um neun")) == {"hour": 9}
    # explizites "Uhr" gewinnt weiter
    assert _k(parse_slot_wish("heute um halb zwei oder 14 Uhr")) == {"hour": 14}


def test_uhrzeit_ohne_uhr_gegenproben():
    """Zaehlwoerter, Verschieben und Datumsordinale sind KEINE Uhrzeit."""
    assert parse_slot_wish("um zwei Wochen verschieben")["hour"] is None
    assert parse_slot_wish("ich brauche um drei Termine")["hour"] is None
    assert parse_slot_wish("meinen Termin um zwei verschieben")["hour"] is None
    w = parse_slot_wish("um 3. Oktober")
    assert w["hour"] is None and w["date"].endswith("-10-03")
    assert parse_slot_wish("in drei Wochen")["hour"] is None


def test_wunsch_deuten_haelt_zeitraum_fuer_gehaltvoll():
    w = gehirn._wunsch_deuten("Am liebsten im Oktober.")
    assert w and w["von"].endswith("-10-01")
    # "heute" raeumt einen Zeitraum aus demselben Satz nicht weg, gewinnt aber
    w2 = gehirn._wunsch_deuten("heute um halb zwei")
    assert w2 and w2["date"] == _heute().isoformat() and w2["hour"] == 13
    assert w2["von"] is None and w2["bis"] is None
    assert gehirn._wunsch_deuten("Ich heiße Meier.") is None


# --- 2. Mischen ueber mehrere Zuege ----------------------------------------------

def test_mischen_neuer_zeitraum_ersetzt_alten_tag_und_zeitraum():
    alt = {"date": "2026-09-14", "hourMin": 12, "hourMax": 18}
    neu = parse_slot_wish("dann lieber im Oktober")
    out = gehirn._wunsch_mischen(alt, neu)
    assert out["date"] is None
    assert out["von"].endswith("-10-01") and out["bis"].endswith("-10-31")
    assert (out["hourMin"], out["hourMax"]) == (12, 18)  # Tageszeit bleibt


def test_mischen_konkreter_tag_ersetzt_zeitraum():
    alt = parse_slot_wish("im Oktober")
    neu = parse_slot_wish("dann der 3. Oktober")
    out = gehirn._wunsch_mischen(alt, neu)
    assert out["date"].endswith("-10-03")
    assert out["von"] is None and out["bis"] is None


def test_mischen_naechste_woche_ersetzt_zeitraum():
    alt = parse_slot_wish("im Oktober")
    neu = parse_slot_wish("dann doch nächste Woche")
    out = gehirn._wunsch_mischen(alt, neu)
    assert out["minDaysAhead"] == 7
    assert out["von"] is None and out["bis"] is None


def test_mischen_wochentag_bleibt_im_zeitraum():
    alt = parse_slot_wish("im Oktober")
    neu = parse_slot_wish("ein Donnerstag wäre gut")
    out = gehirn._wunsch_mischen(alt, neu)
    assert out["weekday"] == 4
    assert out["von"].endswith("-10-01") and out["bis"].endswith("-10-31")


# --- 3. start_datum ---------------------------------------------------------------

def _s_mit(wunsch: dict) -> dict:
    return {"wunsch": wunsch}


def test_start_datum_zeitraum_setzt_monatsanfang_nie_vergangenheit():
    heute = _heute()
    # ein Monat, der sicher in der Zukunft liegt
    m = heute.month % 12 + 2
    jahr = heute.year + (1 if m <= heute.month else 0)
    if m > 12:
        m -= 12
        jahr += 1
    von = date(jahr, m, 1).isoformat()
    assert gehirn.start_datum(_s_mit({"von": von, "bis": None})) == von
    # laufender Monat: "von" liegt in der Vergangenheit -> sofort suchen ("")
    assert gehirn.start_datum(_s_mit({"von": heute.replace(day=1).isoformat()})) == ""


def test_start_datum_wochentag_ist_der_naechste_wochentag():
    heute = _heute()
    # Wunsch-Wochentag: Sonntag=0 ... Samstag=6 (WEEKDAYS-Konvention)
    ziel_wunsch = (heute.weekday() + 1 + 3) % 7  # drei Tage weiter
    start = gehirn.start_datum(_s_mit({"weekday": ziel_wunsch}))
    assert start == (heute + timedelta(days=3)).isoformat()
    # heutiger Wochentag: heute selbst -> "" (ab sofort)
    assert gehirn.start_datum(_s_mit({"weekday": (heute.weekday() + 1) % 7})) == ""


def test_start_datum_naechste_woche_donnerstag_kombiniert():
    heute = _heute()
    ziel_wunsch = (heute.weekday() + 1 + 2) % 7  # uebermorgen als Wochentag
    start = gehirn.start_datum(_s_mit({"weekday": ziel_wunsch, "minDaysAhead": 7}))
    # fruehestens in 7 Tagen UND an diesem Wochentag -> in 9 Tagen
    assert start == (heute + timedelta(days=9)).isoformat()


def test_start_datum_konkreter_tag_gewinnt():
    heute = _heute()
    tag = (heute + timedelta(days=40)).isoformat()
    assert gehirn.start_datum(_s_mit({"date": tag, "von": "2099-01-01"})) == tag


# --- 4. pick_slots: Zeitraum + Naechstbestes ---------------------------------------

def _pool(heute: date) -> list[str]:
    """20 Slots ueber die naechsten ~4 Wochen, keiner heute (wie 5aa87268)."""
    out = []
    for tage in (1, 2, 3, 6, 7, 8, 9, 10, 13, 14):
        d = heute + timedelta(days=tage)
        out.append(_iso(d, 9, 15))
        out.append(_iso(d, 14, 0))
    return out


def test_pick_slots_filtert_zeitraum():
    heute = _heute()
    pool = _pool(heute)
    von = (heute + timedelta(days=6)).isoformat()
    bis = (heute + timedelta(days=9)).isoformat()
    picked = pick_slots(pool, wish={"von": von, "bis": bis}, now_ms=int(datetime.now(TZ).timestamp() * 1000))
    assert picked["wishMatched"] is True
    assert picked["slots"]
    assert all(von <= x["date"] <= bis for x in picked["slots"])


def test_pick_slots_heute_ohne_treffer_bietet_naechstbestes_statt_nichts():
    """Anruf 5aa87268: 'heute um 14 Uhr' — kein Slot heute, 20 Slots im Vorrat."""
    heute = _heute()
    pool = _pool(heute)
    now_ms = int(datetime.now(TZ).replace(hour=8, minute=0).timestamp() * 1000)
    picked = pick_slots(pool, wish={"date": heute.isoformat(), "hour": 14}, now_ms=now_ms)
    assert picked["wishMatched"] is False, "der Wunsch ist NICHT erfuellt — ehrlich markieren"
    assert picked["slots"], "aber es gibt Zeiten: die naechstliegenden anbieten"
    # das Naechstbeste liegt VOR dem Rest, nicht irgendwo in drei Wochen
    assert picked["slots"][0]["date"] in {
        (heute + timedelta(days=1)).isoformat(),
        (heute + timedelta(days=2)).isoformat(),
    }
    assert "Genau dann ist leider nichts frei" in sl.spoken_offer(picked["slots"], wish_matched=False)


def test_pick_slots_zeitraum_ohne_treffer_bietet_naechstbestes():
    heute = _heute()
    pool = _pool(heute)
    von = (heute + timedelta(days=60)).isoformat()
    bis = (heute + timedelta(days=90)).isoformat()
    picked = pick_slots(pool, wish={"von": von, "bis": bis}, now_ms=int(datetime.now(TZ).timestamp() * 1000))
    assert picked["wishMatched"] is False
    assert picked["slots"], "Zeitraum leer -> naechstliegende Zeiten (die spaetesten im Vorrat)"
    # naechstbestes zum Zeitraum = die Slots, die dem Anker am naechsten liegen
    assert picked["slots"][-1]["date"] == (heute + timedelta(days=14)).isoformat()


def test_pick_slots_schub_bleibt_leer_ohne_treffer():
    """Frueher/spaeter-Schub darf NICHT auf Vormittags-Slots zurueckfallen."""
    heute = _heute()
    pool = _pool(heute)
    picked = pick_slots(pool, wish={"date": heute.isoformat(), "hour": 14}, schub=True,
                        now_ms=int(datetime.now(TZ).replace(hour=8, minute=0).timestamp() * 1000))
    assert picked == {"slots": [], "wishMatched": False}


# --- 5. Paging in find_slots ---------------------------------------------------------

def _seiten_fake(seiten: dict[str, list[str]], protokoll: list[str], *, ok: bool = True):
    """_find_slots_seite-Ersatz: Slots je Startdatum ("" = heute)."""
    def fake(tenant, ctx, *, start_date="", egal=False, source=""):
        protokoll.append(start_date)
        if not ok:
            return {"ok": False, "error": "kaputt"}
        return {
            "ok": True, "slots": list(seiten.get(start_date, [])),
            "calendar": {"id": ctx.get("calendarId")}, "motive": None,
            "doctorName": "Dr. Petsas", "dispatch": {"name": "getFreeTimeSlots"},
        }
    return fake


def test_find_slots_ohne_wunsch_genau_ein_aufruf(monkeypatch):
    heute = _heute()
    protokoll: list[str] = []
    monkeypatch.setattr(kal, "_find_slots_seite",
                        _seiten_fake({"": [_iso(heute + timedelta(days=1), 9)]}, protokoll))
    found = kal.find_slots({"clientId": "c"}, {"calendarId": "k"})
    assert found["ok"] and len(found["slots"]) == 1
    assert protokoll == [""]


def test_find_slots_blaettert_bis_der_wunsch_gedeckt_ist(monkeypatch):
    """Erste Seite (20 Slots) endet vor dem Wunschtag -> Folgeseite ab dem letzten Tag."""
    heute = _heute()
    seite1 = [_iso(heute + timedelta(days=1 + i // 2), 9 + 5 * (i % 2)) for i in range(20)]  # Tag 1..10
    letzter = max(x[:10] for x in seite1)
    wunschtag = heute + timedelta(days=25)
    seite2 = [_iso(date.fromisoformat(letzter), 16), _iso(wunschtag, 10), _iso(wunschtag + timedelta(days=1), 11)]
    protokoll: list[str] = []
    monkeypatch.setattr(kal, "_find_slots_seite", _seiten_fake({"": seite1, letzter: seite2}, protokoll))
    found = kal.find_slots({"clientId": "c"}, {"calendarId": "k"}, wish={"date": wunschtag.isoformat()})
    assert protokoll == ["", letzter], protokoll
    isos = kal._iso_liste(found["slots"])
    assert any(x.startswith(wunschtag.isoformat()) for x in isos)
    # Dubletten (Slot am Nahttag) nur einmal
    assert len(isos) == len({x[:16] for x in isos})
    assert found["dispatch"]["seiten"] == [
        {"startDate": heute.isoformat(), "n": 20},
        {"startDate": letzter, "n": 3},
    ]


def test_find_slots_seite_unter_zwanzig_springt_dreissig_tage(monkeypatch):
    heute = _heute()
    seite1 = [_iso(heute + timedelta(days=2), 9), _iso(heute + timedelta(days=5), 14)]  # < 20 = 30 Tage durchsucht
    start2 = (heute + timedelta(days=30)).isoformat()
    wunschtag = heute + timedelta(days=45)
    protokoll: list[str] = []
    monkeypatch.setattr(kal, "_find_slots_seite",
                        _seiten_fake({"": seite1, start2: [_iso(wunschtag, 9)]}, protokoll))
    found = kal.find_slots({"clientId": "c"}, {"calendarId": "k"}, wish={"date": wunschtag.isoformat()})
    assert protokoll == ["", start2]
    assert any(x.startswith(wunschtag.isoformat()) for x in kal._iso_liste(found["slots"]))


def test_find_slots_hoert_nach_seiten_max_auf(monkeypatch):
    """Unerfuellbarer Wunsch: hoechstens SEITEN_MAX Folgeseiten, dann Schluss."""
    heute = _heute()
    protokoll: list[str] = []

    def fake(tenant, ctx, *, start_date="", egal=False, source=""):
        protokoll.append(start_date)
        basis = date.fromisoformat(start_date) if start_date else heute
        return {"ok": True, "slots": [_iso(basis + timedelta(days=1 + i), 9) for i in range(20)],
                "calendar": None, "motive": None, "doctorName": "", "dispatch": {}}

    monkeypatch.setattr(kal, "_find_slots_seite", fake)
    found = kal.find_slots({"clientId": "c"}, {"calendarId": "k"}, wish={"weekday": 0, "hour": 3})
    assert len(protokoll) == 1 + kal.SEITEN_MAX
    assert found["ok"] and len(found["slots"]) > 20


def test_find_slots_bleibt_im_sechs_monats_fenster(monkeypatch):
    heute = _heute()
    protokoll: list[str] = []
    horizont = heute + timedelta(days=kal.FENSTER_TAGE)
    dahinter = horizont + timedelta(days=2)

    def fake(tenant, ctx, *, start_date="", egal=False, source=""):
        protokoll.append(start_date)
        # 20 Slots, alle HINTER dem Horizont: die Folgeseite laege dahinter.
        return {"ok": True, "slots": [_iso(dahinter, 8 + i % 10, 0) for i in range(20)],
                "calendar": None, "motive": None, "doctorName": "", "dispatch": {}}

    monkeypatch.setattr(kal, "_find_slots_seite", fake)
    found = kal.find_slots({"clientId": "c"}, {"calendarId": "k"}, wish={"date": "2099-01-01"})
    assert protokoll == [""], "Folgeseite laege hinter dem 6-Monats-Horizont -> nicht geholt"
    assert len(found["slots"]) == 20


def test_find_slots_seitenstarts_bleiben_im_fenster(monkeypatch):
    heute = _heute()
    protokoll: list[str] = []

    def fake(tenant, ctx, *, start_date="", egal=False, source=""):
        protokoll.append(start_date)
        basis = date.fromisoformat(start_date) if start_date else heute
        # 20 Slots ueber 40 Tage -> jede Seite schiebt den Start um ~38 Tage
        return {"ok": True, "slots": [_iso(basis + timedelta(days=2 * i), 9) for i in range(20)],
                "calendar": None, "motive": None, "doctorName": "", "dispatch": {}}

    monkeypatch.setattr(kal, "_find_slots_seite", fake)
    kal.find_slots({"clientId": "c"}, {"calendarId": "k"}, wish={"date": "2099-01-01"})
    horizont = (heute + timedelta(days=kal.FENSTER_TAGE)).isoformat()
    assert 1 < len(protokoll) <= 1 + kal.SEITEN_MAX
    assert all(not p or p <= horizont for p in protokoll)


def test_find_slots_leere_folgeseite_beendet_das_blaettern(monkeypatch):
    heute = _heute()
    seite1 = [_iso(heute + timedelta(days=1 + i // 2), 9 + 5 * (i % 2)) for i in range(20)]
    letzter = max(x[:10] for x in seite1)
    protokoll: list[str] = []
    monkeypatch.setattr(kal, "_find_slots_seite", _seiten_fake({"": seite1}, protokoll))
    found = kal.find_slots({"clientId": "c"}, {"calendarId": "k"}, wish={"date": "2099-01-01"})
    assert protokoll == ["", letzter]
    assert len(found["slots"]) == 20


def test_find_slots_fehler_der_ersten_seite_bleibt_fehler(monkeypatch):
    protokoll: list[str] = []
    monkeypatch.setattr(kal, "_find_slots_seite", _seiten_fake({}, protokoll, ok=False))
    found = kal.find_slots({"clientId": "c"}, {"calendarId": "k"}, wish={"date": "2099-01-01"})
    assert found["ok"] is False and protokoll == [""]


def test_find_slots_egal_blaettert_im_gewinner_kalender(monkeypatch):
    """'Arzt egal': Seite 1 waehlt die Plattform, Folgeseiten bleiben bei DEM Arzt."""
    heute = _heute()
    seite1 = [_iso(heute + timedelta(days=1 + i // 2), 9 + 5 * (i % 2)) for i in range(20)]
    letzter = max(x[:10] for x in seite1)
    gesehen: list[dict] = []

    def fake(tenant, ctx, *, start_date="", egal=False, source=""):
        gesehen.append({"start": start_date, "egal": egal, "cal": ctx.get("calendarId")})
        return {"ok": True, "slots": list(seite1) if not start_date else [],
                "calendar": None, "motive": None, "doctorName": "Dr. Michael Petsas, M.Sc.",
                "dispatch": {}}

    monkeypatch.setattr(kal, "_find_slots_seite", fake)
    monkeypatch.setattr(kal, "kalender_von", lambda tenant, name: {"id": "PETSAS", "name": name} if "Petsas" in name else None)
    kal.find_slots({"clientId": "c"}, {}, egal=True, wish={"date": "2099-01-01"})
    assert gesehen[0] == {"start": "", "egal": True, "cal": None}
    assert gesehen[1] == {"start": letzter, "egal": False, "cal": "PETSAS"}


def test_naechste_seite_regeln():
    heute = "2026-09-14"
    voll = [f"2026-09-{15 + i // 2:02d}T09:00:00" for i in range(20)]  # 20 Slots, letzter Tag 24.09.
    assert kal._naechste_seite("", voll, heute) == "2026-09-24"
    assert kal._naechste_seite("2026-09-14", ["2026-09-20T09:00:00"], heute) == "2026-10-14"
    assert kal._naechste_seite("2026-09-14", [], heute) == ""
    # alle 20 Slots am Starttag -> einen Tag weiter
    assert kal._naechste_seite("2026-09-14", [f"2026-09-14T{8 + i % 10:02d}:00:00" for i in range(20)], heute) == "2026-09-15"
    # < 20 Slots, letzter HINTER Tag 30 -> die Plattform lief den 90-Tage-Weg
    # (Tag 30-120 komplett) -> 120 Tage weiter statt Doppel-Suche ab Tag 30
    assert kal._naechste_seite("2026-09-14", ["2026-11-03T09:00:00", "2026-11-10T09:00:00"], heute) == "2027-01-12"


# --- 6. Zimmer-Weg mit Kontroll-Ersatz (Anruf da746a65) --------------------------------

def test_find_slots_raeume_faellt_auf_kontrolle_zurueck(monkeypatch):
    heute = _heute()
    protokoll: list[tuple[str, str]] = []

    def fake_find(tenant, ctx, **kw):
        protokoll.append((ctx.get("calendarId"), ctx.get("visitMotiveId")))
        if ctx.get("visitMotiveId") == "kontrolle" and ctx.get("calendarId") == "zimmer2":
            return {"ok": True, "slots": [_iso(heute + timedelta(days=3), 9)]}
        return {"ok": True, "slots": []}

    monkeypatch.setattr(kal, "find_slots", fake_find)
    monkeypatch.setattr(kal, "motiv_von",
                        lambda tenant, name: {"id": "kontrolle", "name": "KCH Kontrolluntersuchung"})
    raeume = [{"id": "zimmer1", "name": "Zimmer 1"}, {"id": "zimmer2", "name": "Zimmer 2"}]
    found = kal.find_slots_raeume(
        {"clientId": "c"}, {"visitMotiveId": "akut", "visitMotiveName": "KCH akute Beschwerden"}, raeume)
    assert found["ok"] and found["slots"]
    assert found["calendar"] == {"id": "zimmer2", "name": "Zimmer 2"}
    assert found["motivFallback"] == "kontrolle"
    assert found["motivOriginal"] == {"id": "akut", "name": "KCH akute Beschwerden"}
    # Runde 1: beide Zimmer mit Akut; Runde 2: Kontrolle, erster Treffer gewinnt
    assert protokoll == [("zimmer1", "akut"), ("zimmer2", "akut"),
                         ("zimmer1", "kontrolle"), ("zimmer2", "kontrolle")]


def test_find_slots_raeume_ohne_ersatz_bleibt_ehrlich_leer(monkeypatch):
    monkeypatch.setattr(kal, "find_slots", lambda tenant, ctx, **kw: {"ok": True, "slots": []})
    monkeypatch.setattr(kal, "motiv_von", lambda tenant, name: None)  # kein Kontroll-Motiv
    raeume = [{"id": "zimmer1", "name": "Zimmer 1"}]
    found = kal.find_slots_raeume({"clientId": "c"}, {"visitMotiveId": "akut", "visitMotiveName": "Akut"}, raeume)
    assert found["ok"] and not found["slots"]
    assert "motivFallback" not in found


def test_find_slots_raeume_nie_akut_als_ersatz(monkeypatch):
    """Ersatz darf nie ein Notfall-Motiv sein (Blessing/Thaler: visitMotives[0] = Akut)."""
    monkeypatch.setattr(kal, "find_slots", lambda tenant, ctx, **kw: {"ok": True, "slots": []})
    monkeypatch.setattr(kal, "motiv_von",
                        lambda tenant, name: {"id": "notfall", "name": "Akutsprechstunde / Notfall"})
    raeume = [{"id": "zimmer1", "name": "Zimmer 1"}]
    found = kal.find_slots_raeume({"clientId": "c"}, {"visitMotiveId": "pzr", "visitMotiveName": "PZR"}, raeume)
    assert "motivFallback" not in found


# --- 7. Ende-zu-Ende: Angebot blaettert in den Wunschmonat ----------------------------

def _katalog() -> list[dict]:
    return [
        {"id": "kontrolle", "name": "KCH Kontrolluntersuchung", "nameForPatient": "Kontrolle",
         "allowOnlineBooking": True, "calendarIds": []},
    ]


def _buch_sit() -> dict:
    sit = {
        "tenant": laden("meddent"),
        "messages": [{"role": "system", "content": "x"}],
        "stimme": "Bianca",
        "motivKatalog": _katalog(),
    }
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True,
              "arzt": {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg",
                       "calendarName": "Dr. Petsas"},
              "grund": "Kontrolle", "grundWortlaut": "zur Kontrolle",
              "motivId": "kontrolle", "motivName": "KCH Kontrolluntersuchung",
              "vorname": "Julia", "nachname": "Berger", "buchstabiert": True,
              "versicherung": "gesetzlich", "phase": "angebot"})
    return sit


def test_angebot_startet_im_wunschmonat_und_bietet_dort_an(monkeypatch):
    """'im <naechster Monat>' -> Suche startet am Monatsersten, Angebot liegt im Monat."""
    sit = _buch_sit()
    s = gehirn.sammler(sit)
    heute = _heute()
    m = heute.month % 12 + 1
    jahr = heute.year + (1 if m == 1 else 0)
    erster = date(jahr, m, 1)
    s["wunsch"] = {"weekday": None, "hourMin": None, "hourMax": None, "hour": None,
                   "minDaysAhead": 0, "date": None, "tage": None,
                   "von": erster.isoformat(), "bis": kal._tag_plus(erster.isoformat(), 27)}
    gesehen: list[str] = []

    def fake(tenant, ctx, *, start_date="", egal=False, source=""):
        gesehen.append(start_date)
        basis = date.fromisoformat(start_date) if start_date else heute
        return {"ok": True, "slots": [_iso(basis + timedelta(days=1 + i), 9 + (i % 3) * 3) for i in range(6)],
                "calendar": {"id": ctx.get("calendarId")}, "motive": None, "doctorName": "", "dispatch": {}}

    monkeypatch.setattr(flow.kal, "_find_slots_seite", fake)
    ang = flow._angebot(sit)
    assert ang and ang.get("text")
    assert gesehen[0] == erster.isoformat(), "Suchstart = Monatsanfang, nicht heute"
    offered = [o["iso"] for o in sit["offered"]]
    assert offered and all(o[:7] == erster.isoformat()[:7] for o in offered)
    assert "Genau dann ist leider nichts frei" not in ang["text"]


def test_angebot_heute_ohne_treffer_sagt_naechstbestes_statt_kein_termin(monkeypatch):
    """Anruf 5aa87268 nachgestellt: 'heute um 14 Uhr', Kalender heute voll."""
    sit = _buch_sit()
    s = gehirn.sammler(sit)
    heute = _heute()
    s["wunsch"] = {"weekday": None, "hourMin": None, "hourMax": None, "hour": 14,
                   "minDaysAhead": 0, "date": heute.isoformat(), "tage": None, "von": None, "bis": None}
    pool = _pool(heute)

    def fake(tenant, ctx, *, start_date="", egal=False, source=""):
        return {"ok": True, "slots": list(pool), "calendar": {"id": ctx.get("calendarId")},
                "motive": None, "doctorName": "", "dispatch": {}}

    monkeypatch.setattr(flow.kal, "_find_slots_seite", fake)
    ang = flow._angebot(sit)
    assert ang and ang.get("text")
    assert "keinen freien Termin" not in ang["text"]
    assert sit["offered"], "Zeiten da -> anbieten, nicht Rueckruf"
    assert s["phase"] == "angebot" and s["frage"] == "slotwahl"
    assert not sit.get("keinSlotFertig")


# --- 8. Verwaltung: 'mein Termin im Oktober' filtert nach Zeitraum -------------------

def test_hinweis_passt_filtert_nach_zeitraum():
    heute = _heute()
    w = parse_slot_wish("mein Termin im Oktober")
    assert verwalten._hinweis_hat(w)
    okt = w["von"][:7]
    im_oktober = {"iso": f"{okt}-15T10:00:00+02:00"}
    im_dezember = {"iso": f"{w['von'][:4]}-12-15T10:00:00+01:00"}
    assert verwalten._hinweis_passt(im_oktober, w) is True
    assert verwalten._hinweis_passt(im_dezember, w) is False
    assert heute  # ruhig halten: Datum nur fuer Lesbarkeit
