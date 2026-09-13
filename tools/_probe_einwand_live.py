"""Live-Probe (kein Kalender-Write): Einwand zuerst, Bezug in jedem Zug.

Teil A laeuft in-process gegen den deployten Fluss (kein Netz, kein Write) und
zeigt, dass ein Widerspruch NUR das bestrittene Feld raeumt und die Kette
danach dort weitergeht, wo sie stand — W-EINWAND.

Teil B geht ueber die echte Dock-API (Testsitzung ohne Write) und zeigt, dass
die Antwort erkennbar auf den letzten Satz eingeht — W-EINGEHEN.

    docker exec -w /app telefonki-bianca-1 python tools/_probe_einwand_live.py
"""

from __future__ import annotations

import json
import os

import httpx

from bianca import flow, gehirn
from kern import eingehen, einwand, hirn
from kern.tenants import laden

BASIS = "http://127.0.0.1:8096"


# --- Teil A: Einwand mitten im Faden ---------------------------------------

def _sit() -> dict:
    sit = {"tenant": laden("meddent"),
           "messages": [{"role": "system", "content": "x"}]}
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": True,
        "arzt": {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg",
                 "calendarName": "Dr. Petsas"},
        "nachname": "Rateike", "buchstabiert": True,
        "vorname": "Stefan", "vornameQuelle": "gesagt",
        "grund": "Kontrolle", "motivId": "kontrolle", "motivName": "KCH Kontrolle",
        "telefon": "01776004600", "telefonOk": True,
        "versicherung": "gesetzlich", "versicherungOk": True,
        "versicherungAkte": "gesetzlich",
        "pzr": "nein", "bleaching": "nein", "rueckblick": "fertig",
        "frage": "wunsch",
    })
    return sit


def _zug_offline(sit: dict, text: str) -> dict:
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        return flow.zug(sit, text) or {}
    finally:
        flow.hintergrund.anstossen = echt


def teil_a() -> None:
    print("== Teil A: Widerspruch mitten im Faden (offline, kein Write) ==")
    print(f"   Modi: EINWAND={einwand.modus()} EINGEHEN={eingehen.modus()} "
          f"AUTO_RESUME={hirn.auto_resume_modus()}")

    for satz in ("Moment, die Nummer stimmt nicht.",
                 "Nein, bei dem Behandler war ich nicht.",
                 "Nein, gesetzlich stimmt nicht mehr."):
        sit = _sit()
        r = _zug_offline(sit, satz)
        s = sit["sammler"]
        print(f"\n   ANRUFER : {satz}")
        print(f"   BIANCA  : {(r.get('text') or '').strip()[:180]}")
        print(f"   offen   : {s['frage']}")
        print(f"   steht    : nachname={s['nachname']!r} vorname={s['vorname']!r} "
              f"telefon={s['telefon']!r} grund={s['grund']!r} "
              f"arzt={'ja' if s['arzt'] else 'nein'} "
              f"versOk={s['versicherungOk']}")

    # Kette: nach der Korrektur weiter, wo sie stand.
    sit = _sit()
    _zug_offline(sit, "Nein, gesetzlich stimmt nicht mehr.")
    r = _zug_offline(sit, "Privat.")
    s = sit["sammler"]
    print("\n   -- Kette nach der Korrektur --")
    print("   ANRUFER : Privat.")
    print(f"   BIANCA  : {(r.get('text') or '').strip()[:180]}")
    print(f"   vers     : {s['versicherung']!r} ok={s['versicherungOk']} "
          f"-> offen={s['frage']} (Name/Nummer unangetastet: "
          f"{s['nachname']!r}/{s['telefon']!r})")


# --- Teil B: Bezug auf das Gesagte -----------------------------------------

def _zug_http(client: httpx.Client, sid: str, text: str) -> dict:
    r = client.post(f"{BASIS}/api/turn",
                    json={"sessionId": sid, "text": text}, timeout=120)
    r.raise_for_status()
    letzte: dict = {}
    for zeile in r.text.splitlines():
        if not zeile.strip():
            continue
        posten = json.loads(zeile)
        if posten.get("type") == "reply":
            letzte = posten
    return letzte


def teil_b() -> None:
    print("\n== Teil B: Bezug auf das Gesagte (echte Dock-API, Testsitzung) ==")
    saetze = [
        "Guten Tag, ich haette gern einen Termin zur Kontrolle.",
        "Nein, ich war noch nie bei Ihnen.",
    ]
    with httpx.Client() as client:
        r = client.post(f"{BASIS}/api/start",
                        json={"test": True, "testNoWrite": True}, timeout=60)
        r.raise_for_status()
        daten = r.json()
        sid = daten.get("sessionId") or daten.get("id")
        print(f"   session {sid}")
        print(f"   BIANCA  : {(daten.get('text') or '').strip()[:180]}")
        for satz in saetze:
            posten = _zug_http(client, sid, satz)
            print(f"\n   ANRUFER : {satz}")
            print(f"   BIANCA  : {(posten.get('text') or '').strip()[:220]}")
        client.post(f"{BASIS}/api/hangup", json={"sessionId": sid}, timeout=60)


def main() -> None:
    teil_a()
    if os.environ.get("PROBE_HTTP", "1") != "0":
        teil_b()


if __name__ == "__main__":
    main()
