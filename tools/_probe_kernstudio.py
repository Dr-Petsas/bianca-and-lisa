"""Rauchprobe der Dialogkern-Seite im Studio — ohne Server, ohne LLM, ohne Netz.

Prueft die vier Endpunkte von ``tests/baukasten/editor.py`` ueber ihren
Testklienten: Maskenschema, Policy je Praxis, Start und Zuege. Werkzeuge sind
simuliert (``ToolGatewaySim``) — es wird nichts gebucht und nichts gespeichert.

Aufruf:  python tools\\_probe_kernstudio.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Kein LLM-Versuch in der Probe: der Kern faellt dann auf seine Regeln zurueck.
os.environ["LLM_BASE"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from tests.baukasten import editor  # noqa: E402

K = TestClient(editor.app)
FEHLER: list[str] = []


def pruefe(bedingung: bool, text: str) -> None:
    print(("  OK   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        FEHLER.append(text)


def maske() -> dict:
    print("\n[1] Maskenschema")
    j = K.get("/api/kern/maske").json()
    pruefe(j.get("ok") is True, "api/kern/maske antwortet ok")
    gruppen = j.get("gruppen") or []
    pruefe(len(gruppen) >= 6, f"mindestens sechs Abschnitte ({len(gruppen)})")
    felder = [f for g in gruppen for f in (g.get("felder") or [])]
    pruefe(len(felder) >= 15, f"Felder in der Maske ({len(felder)})")
    pruefe(all(f.get("pfad") and f.get("typ") for f in felder),
           "jedes Feld traegt Pfad und Typ")
    pruefe(bool(j.get("invarianten")), "Invarianten werden mitgeliefert")
    pruefe(bool(j.get("szenarien")), "Werkzeug-Szenarien werden mitgeliefert")
    # Telefon darf nie als Reihenfolge-Feld waehlbar sein (W-TELEFON-ZULETZT).
    listen = [f for f in felder if f.get("typ") == "liste"]
    pruefe(all("telefon" not in (f.get("auswahl") or []) for f in listen),
           "Telefon steht in keiner Reihenfolge-Auswahl")
    return j


def policys() -> None:
    print("\n[2] Policy je Praxis")
    for tenant in ("meddent", "blessing", "ruether", "thaler"):
        j = K.post("/api/kern/policy", json={"tenant": tenant}).json()
        ok = j.get("ok") is True and j.get("tenant") == tenant
        quelle = j.get("quelle")
        pruefe(ok, f"{tenant}: Policy aufgeloest (Quelle {quelle})")
        pruefe(quelle in ("vertrag", "legacy"), f"{tenant}: Quelle bekannt")
        pruefe(isinstance(j.get("policy"), dict) and bool(j["policy"]),
               f"{tenant}: Policy ist ein Dict")

    print("\n[3] Maske uebersteuert die Praxis")
    a = K.post("/api/kern/policy", json={"tenant": "meddent"}).json()
    roh = dict(a["policy"])
    roh["rueckfrage"] = dict(roh.get("rueckfrage") or {})
    roh["rueckfrage"]["max_rueckfragen"] = 1
    b = K.post("/api/kern/policy", json={"tenant": "meddent", "policy": roh}).json()
    pruefe(b.get("quelle") == "uebersteuert", "Quelle meldet uebersteuert")
    pruefe(b["policy"]["rueckfrage"]["max_rueckfragen"] == 1,
           "uebersteuerter Wert kommt zurueck")
    unveraendert = K.post("/api/kern/policy", json={"tenant": "meddent"}).json()
    pruefe(unveraendert["policy"]["rueckfrage"]["max_rueckfragen"]
           == a["policy"]["rueckfrage"]["max_rueckfragen"],
           "Praxisstand bleibt unberuehrt (nichts gespeichert)")


def gespraech() -> None:
    print("\n[4] Gespraech gegen den reinen Kern")
    s = K.post("/api/kern/start", json={"tenant": "meddent", "szenario": "normal"}).json()
    pruefe(s.get("ok") is True, "Start antwortet ok")
    sid = (s.get("kopf") or {}).get("sid") or ""
    pruefe(bool(sid), "Sitzung hat eine Kennung")
    pruefe(bool((s.get("zug") or {}).get("antwort")), "Begruessung wird gesprochen")

    saetze = [
        "Guten Tag, ich braeuchte einen Termin zur Kontrolle.",
        "Nein, ich war noch nie bei Ihnen.",
        "Bei Doktor Petsas bitte.",
        "Naechste Woche Dienstag vormittags.",
    ]
    letzter = {}
    for satz in saetze:
        j = K.post("/api/kern/zug", json={"sid": sid, "text": satz}).json()
        if j.get("ok") is not True:
            pruefe(False, f"Zug scheitert: {j.get('fehler')}")
            return
        letzter = j["zug"]
        z = letzter.get("zustand") or {}
        print(f"       > {satz}\n       < {letzter.get('antwort')}"
              f"   [{z.get('task') or '-'} / {z.get('phase') or '-'}]")
    z = letzter.get("zustand") or {}
    pruefe(z.get("zugNr", 0) >= len(saetze), "Zugzaehler laeuft mit")
    pruefe(bool(letzter.get("antwort")), "letzter Zug spricht")

    print("\n[5] Schleifen-Aufsicht greift (max_rueckfragen = 1)")
    a = K.post("/api/kern/policy", json={"tenant": "meddent"}).json()
    roh = dict(a["policy"])
    roh["rueckfrage"] = dict(roh.get("rueckfrage") or {})
    roh["rueckfrage"]["max_rueckfragen"] = 1
    roh["rueckfrage"]["zusammenfassung_bei_stocken"] = True
    s2 = K.post("/api/kern/start",
                json={"tenant": "meddent", "szenario": "normal", "policy": roh}).json()
    sid2 = s2["kopf"]["sid"]
    pruefe(s2["kopf"]["quelle"] == "uebersteuert", "Probe laeuft mit der Maske")
    zuege = []
    for _ in range(6):
        j = K.post("/api/kern/zug", json={"sid": sid2, "text": "haeh?"}).json()
        if j.get("ok") is not True:
            break
        zuege.append(j["zug"])
        print(f"       < {j['zug'].get('antwort')}"
              f"   [stock {(j['zug'].get('zustand') or {}).get('stockZahl')}"
              f"/{(j['zug'].get('zustand') or {}).get('stockBudget')}]")
    gruende = [z.get("grund") for z in zuege if z.get("grund")]
    endet = any(z.get("uebergeben") or z.get("hangup") for z in zuege)
    pruefe(bool(gruende) or endet,
           f"Aufsicht meldet sich oder beendet ({gruende or 'Ende'})")
    antworten = [z.get("antwort") for z in zuege]
    pruefe(len(set(antworten)) > 1 or endet,
           "keine wortgleiche Endlos-Wiederholung")

    print("\n[6] Simulierte Werkzeuge schreiben nie echt")
    s3 = K.post("/api/kern/start", json={"tenant": "meddent", "szenario": "slot_weg"}).json()
    pruefe(s3.get("ok") is True, "Szenario slot_weg startet")
    pruefe((s3["kopf"].get("szenario") or "") == "slot_weg", "Szenario wird gefuehrt")

    print("\n[7] Unbekannte Sitzung wird ehrlich abgelehnt")
    j = K.post("/api/kern/zug", json={"sid": "gibtsnicht", "text": "hallo"}).json()
    pruefe(j.get("ok") is False and bool(j.get("fehler")),
           "abgelaufene Sitzung meldet einen Fehler")


def seite() -> None:
    print("\n[8] Seite und Mittel werden ausgeliefert")
    for pfad in ("/dialogkern", "/web/dialogkern.js", "/web/stil.css"):
        r = K.get(pfad)
        pruefe(r.status_code == 200 and len(r.content) > 200, f"{pfad} ({r.status_code})")
    r = K.get("/web/stil.css")
    pruefe(b"kern-raster" in r.content, "Stil kennt das Dialogkern-Raster")


if __name__ == "__main__":
    maske()
    policys()
    gespraech()
    seite()
    print("\n" + ("ALLES GRUEN" if not FEHLER
                  else f"{len(FEHLER)} FEHLER:\n  - " + "\n  - ".join(FEHLER)))
    sys.exit(1 if FEHLER else 0)
