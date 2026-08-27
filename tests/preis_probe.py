"""E2E-Probe Praxiswissen (Chef 27.08.2026): Zwischenfragen nach Preis und
Anfahrt während der Nummer-Erfassung.

Erwartung gegen den LAUFENDEN Bianca-Dienst (Port 8096, neuer Stand):
- "Was kostet eine Zahnreinigung?" -> circa 150 Euro (gesprochen
  "einhundertfünfzig Euro"), danach zurück zur offenen Handynummer-Frage.
- Preis NICHT in der Liste (Wurzelbehandlung) -> Verweis an den Zahnarzt,
  kein erfundener Betrag.
- "Wie komme ich zu Ihnen?" -> Wegbeschreibung (Grafenberg, Luise-Rainer-
  Straße), "welche Bahn?" -> Linien in Wortform — und immer zurück zur Frage.

Bewusst OHNE Buchung: die Probe bricht vor der Nummernabgabe ab und legt
auf — der echte Kalender (WRITE_LIVE) bleibt unberührt.
"""

import json
import sys

import httpx

BIANCA = "http://127.0.0.1:8096"


def zug(client: httpx.Client, sid: str, text: str) -> str:
    reply = {}
    with client.stream("POST", f"{BIANCA}/api/turn", json={"sessionId": sid, "text": text}, timeout=90.0) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("type") == "reply" or ("type" not in ev and "text" in ev):
                reply = ev
    print(f"  DU : {text}")
    print(f"  BIA: {reply.get('text')}")
    return reply.get("text") or ""


def main() -> int:
    c = httpx.Client()
    start = c.post(f"{BIANCA}/api/start", json={"tenant": "meddent"}, timeout=30.0)
    start.raise_for_status()
    sid = ""
    for line in start.text.splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        sid = ev.get("sessionId") or sid
    assert sid, "keine Sitzung"

    # Bis zur Handynummer-Frage (kein Buchungsabschluss!):
    t1 = zug(c, sid, "Guten Tag, hier ist Michael Peters, ich hätte gerne einen Termin zur Kontrolle.")
    assert "schon" in t1.lower(), f"Erwartet 'schon mal da?'-Frage: {t1}"
    t2 = zug(c, sid, "Nein, noch nicht.")
    assert "wann" in t2.lower() or "vormittag" in t2.lower(), f"Erwartet Wunsch-Frage: {t2}"
    t3 = zug(c, sid, "Nächste Woche vormittags.")
    if "buchstabier" in t3.lower():
        t3 = zug(c, sid, "P wie Paula, E wie Emil, T wie Theodor, E wie Emil, R wie Richard, S wie Samuel.")
    assert "handynummer" in t3.lower() or "nummer" in t3.lower(), f"Erwartet Telefon-Frage: {t3}"

    # 1) Preis IN der Liste: Zahnreinigung -> circa 150 Euro + zurück zur Frage.
    tp = zug(c, sid, "Ähm, ganz kurz — was kostet denn eine Zahnreinigung bei Ihnen?")
    lp = tp.lower()
    assert "hundertfünfzig" in lp or "150" in tp, f"Preis 150 fehlt: {tp}"
    assert "euro" in lp, f"'Euro' fehlt: {tp}"
    assert "nummer" in lp or "handy" in lp, f"Offene Telefon-Frage fehlt: {tp}"

    # 2) Preis NICHT in der Liste: Wurzelbehandlung -> Verweis, kein Betrag.
    tw = zug(c, sid, "Und was kostet eine Wurzelbehandlung?")
    lw = tw.lower()
    assert "zahnarzt" in lw or "praxis" in lw, f"Verweis an den Zahnarzt fehlt: {tw}"
    assert "euro" not in lw, f"Erfundener Preis: {tw}"
    assert "nummer" in lw or "handy" in lw, f"Offene Telefon-Frage fehlt: {tw}"

    # 3) Anfahrt: voller Wegbeschreibungs-Text (bis zum Ende!), dann zurück zur Frage.
    ta = zug(c, sid, "Ähm, und wie komme ich denn zu Ihnen?")
    la = ta.lower()
    assert "grafenberg" in la and "luise-rainer" in la, f"Wegbeschreibung fehlt: {ta}"
    assert "haus b" in la and "etage" in la, f"Text bricht ab (Token-Limit?): {ta}"
    assert "nummer" in la or "handy" in la, f"Offene Telefon-Frage fehlt: {ta}"

    # 4) ÖPNV: Linien in Wortform (nie Ziffern).
    to = zug(c, sid, "Und mit der Bahn — welche Linie fährt denn zu Ihnen?")
    lo = to.lower()
    assert ("zweiundsiebzig" in lo or "dreiundachtzig" in lo or "siebenhundertneun" in lo), \
        f"ÖPNV-Linien fehlen: {to}"
    assert "u72" not in lo and "709" not in to, f"Linien müssen Wortform bleiben: {to}"
    assert "nummer" in lo or "handy" in lo, f"Offene Telefon-Frage fehlt: {to}"

    c.post(f"{BIANCA}/api/hangup", json={"sessionId": sid}, timeout=30.0)
    print("\nWISSENS-PROBE GRUEN — Preise, Verweis, Anfahrt und Bahnlinien sitzen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
