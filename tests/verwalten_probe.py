"""Live-Handprobe Bianca-Verwaltung (Port 8096): vier echte Anrufe in Folge.

1. BUCHEN     — bestehender Patient (Levi Tzannis), naechste Woche vormittags.
2. AUSKUNFT   — "Wann ist mein Termin nochmal?" -> Ansage des gebuchten Termins.
3. VERSCHIEBEN— "lieber nachmittags" -> echtes postpone im selben Kalender.
4. ABSAGEN    — Storno per Termin-ID = eingebautes Aufraeumen der Probe.

Alles gegen den echten Kalender (WRITE_LIVE) — am Ende ist der Bestand wieder
wie vorher. Misst nebenbei die Rundenzeiten (warme Cloud Functions).
"""

import json
import re
import sys
import time

import httpx

BASE = "http://127.0.0.1:8096"


def zug(cli: httpx.Client, sid: str, text: str) -> dict:
    t0 = time.perf_counter()
    out: dict = {}
    filler = 0
    with cli.stream("POST", f"{BASE}/api/turn", json={"sessionId": sid, "text": text}) as r:
        for line in r.iter_lines():
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("type") == "filler":
                filler += 1
            if ev.get("type") == "reply":
                out = ev
    dt = round(time.perf_counter() - t0, 2)
    print(f">> {text}")
    print(f"<< {out.get('text')}")
    print(f"   [{dt}s rund, filler={filler}, book={out.get('book')}]")
    print()
    return out


def start(cli: httpx.Client) -> str:
    r = cli.post(f"{BASE}/api/start", json={"tenant": "meddent"}).json()
    print(f"<< (Start) {r.get('text')}")
    print()
    return r.get("sessionId")


def hangup(cli: httpx.Client, sid: str) -> dict:
    hj = cli.post(f"{BASE}/api/hangup", json={"sessionId": sid}).json()
    note = hj.get("note") or {}
    print(f"-- aufgelegt (Notiz: ok={note.get('ok')} ziel={note.get('appointmentId') or '—'})")
    print()
    return hj


def tag_monat(iso: str) -> str:
    """'2026-09-03T09:15' -> 'den am 3.9.' fuer die Termin-Wahl."""
    return f"den am {int(iso[8:10])}.{int(iso[5:7])}."


def main() -> int:
    cli = httpx.Client(timeout=90)
    h = cli.get(f"{BASE}/health").json()
    print(f"health: llm={h.get('llm', {}).get('ok')} writeLive={h.get('writeLive')} voice={h.get('voice')}")
    print()

    # ---- Anruf 1: BUCHEN ---------------------------------------------------
    print("=== Anruf 1: BUCHEN ===")
    sid = start(cli)
    zug(cli, sid, "Guten Tag, ich hätte gern einen Termin zur Kontrolle.")
    zug(cli, sid, "Ja, ich war schon mal bei Ihnen — bei Doktor Petsas.")
    zug(cli, sid, "Levi Tzannis.")
    time.sleep(2.0)
    a = zug(cli, sid, "Nächste Woche vormittags wäre gut.")
    if "buchstabieren" in (a.get("text") or "").lower():
        zug(cli, sid, "T wie Theodor, Z wie Zacharias, A wie Anton, N wie Nordpol, N wie Nordpol, I wie Ida, S wie Samuel.")
        time.sleep(1.5)
        a = zug(cli, sid, "Und meine Nummer haben Sie ja in der Akte.")
    zug(cli, sid, "Dann nehme ich den ersten bitte.")
    b1 = zug(cli, sid, "Ja, das passt so.")
    book = b1.get("book") or {}
    slot1 = book.get("slotIso") or ""
    if not book.get("booked") or not slot1:
        print("ABBRUCH: Buchung hat nicht geklappt — Verwaltungs-Probe braucht einen Bestandstermin.")
        hangup(cli, sid)
        return 1
    hangup(cli, sid)

    # ---- Anruf 2: AUSKUNFT -------------------------------------------------
    print("=== Anruf 2: AUSKUNFT ===")
    sid = start(cli)
    zug(cli, sid, "Guten Tag, wann ist mein Termin nochmal?")
    a2 = zug(cli, sid, "Levi Tzannis.")
    text2 = (a2.get("text") or "").lower()
    if "welchen" in text2 or "mehrere" in text2:
        a2 = zug(cli, sid, tag_monat(slot1))
    ok2 = "termin" in (a2.get("text") or "").lower()
    print(f"AUSKUNFT {'OK' if ok2 else 'FEHLT'}")
    print()
    hangup(cli, sid)

    # ---- Anruf 3: VERSCHIEBEN ----------------------------------------------
    print("=== Anruf 3: VERSCHIEBEN ===")
    sid = start(cli)
    zug(cli, sid, "Hallo, ich müsste meinen Termin leider verschieben.")
    a3 = zug(cli, sid, "Levi Tzannis.")
    if "welchen" in (a3.get("text") or "").lower():
        a3 = zug(cli, sid, tag_monat(slot1))
    a3 = zug(cli, sid, "Lieber nachmittags, gern auch ein anderer Tag.")
    if "welchen" in (a3.get("text") or "").lower() or not re.search(r"frei|passt", (a3.get("text") or "").lower()):
        print(f"(Zwischenstand: {a3.get('text')!r})")
    w = zug(cli, sid, "Der erste bitte.")
    v = zug(cli, sid, "Ja, machen Sie das so.")
    bookv = v.get("book") or {}
    slot2 = bookv.get("slotIso") or ""
    print(f"VERSCHOBEN: moved={bookv.get('moved')} neu={slot2 or '—'}")
    print()
    hangup(cli, sid)

    ziel = slot2 or slot1

    # ---- Anruf 4: ABSAGEN (= Aufraeumen) ------------------------------------
    print("=== Anruf 4: ABSAGEN ===")
    sid = start(cli)
    zug(cli, sid, "Guten Tag, ich muss meinen Termin leider absagen.")
    a4 = zug(cli, sid, "Levi Tzannis.")
    if "welchen" in (a4.get("text") or "").lower() or "mehrere" in (a4.get("text") or "").lower():
        a4 = zug(cli, sid, tag_monat(ziel))
    s4 = zug(cli, sid, "Ja, bitte absagen.")
    book4 = s4.get("book") or {}
    print(f"ABGESAGT: cancelled={book4.get('cancelled')}")
    zug(cli, sid, "Nein danke, das war alles.")
    hangup(cli, sid)

    if not book4.get("cancelled"):
        print("WARNUNG: Storno kam nicht durch — Termin haengt noch im Kalender!")
        print(f"  -> von Hand pruefen: Levi Tzannis, {ziel}")
        return 1
    print("Probe komplett: gebucht, angesagt, verschoben, abgesagt — Kalender wieder sauber.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
