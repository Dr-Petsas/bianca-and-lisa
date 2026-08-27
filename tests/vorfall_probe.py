"""Einmal-Probe (27.08.2026): die zwei gescheiterten Live-Gespräche nachspielen.

Anruf A (Bianca, echte Buchung + sofortige Absage als Aufräumen):
  "Dr. Petzers" (STT-Hörfehler), "Äh, nein" (Neupatient), englischer
  Zahlen-Glitch ("six hundred") — früher: Arzt-Schleife + Fantasie-Termine.

Anruf B (Lisa): ein Plauder-Zug — der Vorab-Satz (LLM-Stream) muss als
  Füller-Ereignis VOR der Endantwort eintreffen.
"""

import json
import pathlib
import sys
import time

import httpx

BIANCA = "http://127.0.0.1:8096"
LISA = "http://127.0.0.1:8095"
SESS_DIR = pathlib.Path(__file__).resolve().parents[1] / ".data" / "bianca_sessions"


def _angebot_streuung_pruefen(sid: str) -> None:
    """Nach dem Auflegen: gespeicherte Sitzung lesen und pruefen, dass das
    Angebot GESTREUT war — nie zwei Slots < 2,5 h am selben Tag (Chef 27.08.:
    live kamen 12:15/12:45/13:15 bzw. 09:30/09:45/10:00)."""
    pfad = SESS_DIR / f"{sid}.json"
    for _ in range(60):  # Nacharbeit (LLM-Kurzfassung) laeuft im Hintergrund
        if pfad.is_file():
            break
        time.sleep(0.5)
    assert pfad.is_file(), f"Sitzung {sid} wurde nicht gespeichert"
    sess = json.loads(pfad.read_text(encoding="utf-8"))
    offered = sess.get("offered") or []
    assert offered, "kein Angebot in der Sitzung"
    minuten = []
    for o in offered:
        iso = str(o.get("iso") or "")
        minuten.append((iso[:10], int(iso[11:13]) * 60 + int(iso[14:16]), iso))
    for i, (tag_a, min_a, iso_a) in enumerate(minuten):
        for tag_b, min_b, iso_b in minuten[i + 1:]:
            if tag_a == tag_b:
                assert abs(min_a - min_b) >= 150, f"Angebot zu dicht: {iso_a} / {iso_b}"
    print(f"  >>> Angebot gestreut ok: {[m[2][:16] for m in minuten]}")


def ndjson_zug(client: httpx.Client, base: str, pfad: str, body: dict) -> dict:
    """Einen NDJSON-Zug lesen; liefert reply-Objekt + Ereignis-Zeitpunkte."""
    t0 = time.perf_counter()
    ereignisse = []
    reply = {}
    with client.stream("POST", f"{base}{pfad}", json=body, timeout=60.0) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.strip():
                continue
            ev = json.loads(line)
            ereignisse.append((round(time.perf_counter() - t0, 2), ev.get("type") or "json"))
            if ev.get("type") == "reply" or ("type" not in ev and ("sessionId" in ev or "text" in ev)):
                reply = ev
    reply["_ereignisse"] = ereignisse
    return reply


def sag(client: httpx.Client, sid: str, text: str) -> dict:
    out = ndjson_zug(client, BIANCA, "/api/turn", {"sessionId": sid, "text": text})
    t = out.get("timings") or {}
    print(f"  DU : {text}")
    print(f"  BIA: {out.get('text')}   [llm={t.get('llm')}s tts={t.get('tts')}s ereignisse={out['_ereignisse']}]")
    return out


def main() -> int:
    c = httpx.Client()

    print("=== Anruf A: Bianca — Peters-Reprise (Hörfehler, Äh-nein, EN-Ziffern) ===")
    start = ndjson_zug(c, BIANCA, "/api/start", {"tenant": "meddent"})
    sid = start.get("sessionId")
    assert sid, "keine Sitzung"
    print(f"  BIA: {start.get('text')}")

    z1 = sag(c, sid, "Ich hätte gerne einen Termin bei Dr. Petzers, morgen gegen zehn.")
    assert "schon" in z1.get("text", "").lower(), "Erste Frage muss 'schon mal da?' sein"

    z2 = sag(c, sid, "Äh, nein.")
    t2 = z2.get("text", "").lower()
    assert "behandler" not in t2, "FEHLER-REPRISE: fragt nach letztem Behandler trotz Neupatient + genanntem Arzt"
    assert "worum" in t2 or "grund" in t2 or "kontrolle" in t2, f"Erwartet Grund-Frage, kam: {t2}"

    z3 = sag(c, sid, "Eine Kontrolle bitte.")
    assert "name" in z3.get("text", "").lower(), "Erwartet Namens-Frage"

    z4 = sag(c, sid, "Michael Peters.")
    assert "buchstabier" in z4.get("text", "").lower(), "Erwartet Buchstabier-Frage"

    z5 = sag(c, sid, "P wie Paula, E wie Emil, T wie Theodor, E wie Emil, R wie Richard, S wie Samuel.")
    assert "handynummer" in z5.get("text", "").lower(), "Erwartet Telefon-Frage"

    # Abschweifung mitten in der Aufnahme (Chef 27.08.: "Abschweifungen
    # müssen erlaubt sein"): LLM antwortet, danach zurück zur offenen Frage.
    za = sag(c, sid, "Ähm, ganz kurz — was kostet denn so eine Kontrolle bei Ihnen?")
    ta = za.get("text", "").lower()
    assert "uhr" not in ta or "nummer" in ta, f"Abschweifung darf kein Terminangebot erfinden: {ta}"
    assert "nummer" in ta or "handy" in ta, f"Nach Abschweifung muss die offene Telefon-Frage zurückkommen: {ta}"
    zb = sag(c, sid, "Und haben Sie Parkplätze vor der Tür?")
    tb = zb.get("text", "").lower()
    assert "nummer" in tb or "handy" in tb, f"Auch nach zweiter Abschweifung zurück zur Telefon-Frage: {tb}"
    assert "kontrolluntersuchung" not in tb or "eintragen" not in tb, "FEHLER: Eskalation nach Abschweifungen (darf nicht zählen)"

    z6 = sag(c, sid, "Null eins sieben sieben six hundred vier six hundred.")
    t6 = z6.get("text", "").lower()
    assert "wiederhole" in t6, "Erwartet Rückbestätigung der Nummer"
    glatt = t6.replace(",", "")
    assert "null eins sieben sieben sechs null null vier sechs null null" in glatt, f"EN-Glitch nicht übersetzt: {t6}"

    z7 = sag(c, sid, "Ja, stimmt genau.")
    t7 = z7.get("text", "").lower()
    assert "frei" in t7 or "uhr" in t7, f"Erwartet echtes Angebot, kam: {t7}"
    assert "juli" not in t7, "FEHLER-REPRISE: erfundenes Juli-Datum!"

    z8 = sag(c, sid, "Dann nehme ich den ersten bitte.")
    assert "eintragen" in z8.get("text", "").lower(), "Erwartet Bestätigungs-Frage"

    z9 = sag(c, sid, "Ja, bitte.")
    book = z9.get("book") or {}
    assert book.get("booked"), f"Buchung nicht fest: {z9.get('text')} {book}"
    print(f"  >>> FEST GEBUCHT: {book.get('slotIso')}")

    z10 = sag(c, sid, "Ach warten Sie — bitte sagen Sie den Termin doch wieder ab.")
    z11 = sag(c, sid, "Ja, wirklich absagen.")
    text_ab = (z10.get("text", "") + " " + z11.get("text", "")).lower()
    if "abgesagt" not in text_ab and "storniert" not in text_ab:
        z12 = sag(c, sid, "Ja.")
        text_ab += " " + z12.get("text", "").lower()
    assert "abgesagt" in text_ab or "storniert" in text_ab, f"Absage unklar: {text_ab}"
    print("  >>> Termin wieder abgesagt (Kalender sauber).")

    c.post(f"{BIANCA}/api/hangup", json={"sessionId": sid}, timeout=30.0)
    _angebot_streuung_pruefen(sid)

    print("=== Anruf B: Lisa — Vorab-Satz aus dem LLM-Strom ===")
    startL = ndjson_zug(c, LISA, "/api/start", {
        "tenant": "meddent",
        "auftrag": "Bitte an die Praxisschließung am Freitag erinnern. Kurz halten.",
        "patient": {"name": "Michael Petsassss", "firstName": "Michael", "lastName": "Petsassss",
                     "devPhone": "0177 6004600", "devPhoneRaw": "01776004600"},
    })
    sidL = startL.get("sessionId")
    assert sidL, "keine Lisa-Sitzung"
    print(f"  LISA: {startL.get('text')}")
    zi = ndjson_zug(c, LISA, "/api/turn", {"sessionId": sidL, "text": "Ja, am Apparat."})
    print(f"  LISA: {zi.get('text')}   ereignisse={zi['_ereignisse']}")
    zp = ndjson_zug(c, LISA, "/api/turn", {"sessionId": sidL, "text": "Warum ist die Praxis am Freitag denn geschlossen? Und was mache ich bei Schmerzen?"})
    print(f"  LISA: {zp.get('text')}   ereignisse={zp['_ereignisse']}")
    arten = [a for _, a in zp["_ereignisse"]]
    if "filler" in arten:
        t_filler = next(t for t, a in zp["_ereignisse"] if a == "filler")
        t_reply = next(t for t, a in zp["_ereignisse"] if a == "reply")
        print(f"  >>> Erster Ton nach {t_filler}s, Endantwort nach {t_reply}s (Ersparnis {round(t_reply - t_filler, 2)}s).")
    else:
        print("  Hinweis: kein Vorab-Ereignis in diesem Zug (Antwort war ein Einzelsatz).")
    c.post(f"{LISA}/api/hangup", json={"sessionId": sidL}, timeout=30.0)

    print("\nALLES GRUEN — beide Vorfaelle laufen jetzt sauber durch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
