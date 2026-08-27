"""Live-Handprobe Bianca (Port 8096): kompletter eingehender Buchungs-Anruf.

Weg: bestehender Patient (Levi Tzannis), "weiß nicht mehr bei wem ich war"
(-> masPatientLastDoctor im Hintergrund), Wunsch "nächste Woche vormittags",
Angebot, Wahl, Bestätigung -> ECHTE Buchung (WRITE_LIVE), Notiz beim Auflegen.
Danach räumt die Probe auf: der gebuchte Termin wird wieder abgesagt.
"""

import json
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
    tt = out.get("timings") or {}
    print(f">> {text}")
    print(f"<< {out.get('text')}")
    print(f"   [{dt}s rund, llm={tt.get('llm')}s tts={tt.get('tts')}s, filler={filler}, book={out.get('book')}]")
    print()
    return out


def main() -> int:
    cli = httpx.Client(timeout=90)
    h = cli.get(f"{BASE}/health").json()
    print(f"health: llm={h.get('llm', {}).get('ok')} tts={h.get('tts')} voice={h.get('voice')} writeLive={h.get('writeLive')}")
    if not h.get("writeLive"):
        print("WRITE_LIVE ist aus — Probe misst dann nur den Trocken-Pfad.")
    print()

    r = cli.post(f"{BASE}/api/start", json={"tenant": "meddent"}).json()
    sid = r.get("sessionId")
    print(f"<< (Start) {r.get('text')}   [timings={r.get('timings')}]")
    print()

    zug(cli, sid, "Guten Tag, ich hätte gern einen Termin zur Kontrolle.")
    zug(cli, sid, "Ja, ich war schon mal bei Ihnen.")
    zug(cli, sid, "Das weiß ich ehrlich gesagt nicht mehr.")
    zug(cli, sid, "Levi Tzannis.")
    # Hintergrund arbeiten lassen: Kartei + letzter Behandler + Slot-Vorrat.
    time.sleep(2.5)
    angebot = zug(cli, sid, "Nächste Woche vormittags wäre gut.")

    # Falls die Kartei noch nicht durch war, fragt sie jetzt nach Buchstabierung/Handy.
    if "buchstabieren" in (angebot.get("text") or "").lower():
        zug(cli, sid, "T wie Theodor, Z wie Zacharias, A wie Anton, N wie Nordpol, N wie Nordpol, I wie Ida, S wie Samuel.")
        time.sleep(1.5)
        angebot = zug(cli, sid, "Und meine Nummer haben Sie ja in der Akte.")

    wahl = zug(cli, sid, "Dann nehme ich den ersten bitte.")
    buchung = zug(cli, sid, "Ja, das passt so.")

    book = buchung.get("book") or {}
    print(f"BUCHUNG: booked={book.get('booked')} slot={book.get('slotIso')}")

    lc = cli.get(f"{BASE}/api/last-call").json().get("call") or {}
    tools = lc.get("tools") or []
    aid = ""
    for t in tools:
        if t.get("name") == "book_slot" and t.get("appointmentId"):
            aid = t["appointmentId"]
    print(f"appointmentId={aid or '—'}  sammler={lc.get('sammler')}")
    print()

    hj = cli.post(f"{BASE}/api/hangup", json={"sessionId": sid}).json()
    note = hj.get("note") or {}
    print(f"NOTIZ beim Auflegen: ok={note.get('ok')} dryRun={note.get('dryRun')} ziel={note.get('appointmentId') or ''}")
    print((note.get("note") or "")[:400])
    print()

    # Aufräumen: den Probe-Termin wieder absagen.
    slot = book.get("slotIso") or ""
    if book.get("booked") and slot:
        from kern import calendar as kal
        from kern.tenants import laden
        weg = kal.cancel_appointment(
            laden("meddent"),
            {"firstName": "Levi", "lastName": "Tzannis", "appointmentDate": slot[:10]},
        )
        print(f"AUFGERÄUMT: cancelled={weg.get('cancelled')} ({weg.get('spoken')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
