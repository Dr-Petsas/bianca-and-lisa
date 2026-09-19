# Probe: Dock-Chat gegen den Dialogkern, EXAKT den Weg des Browsers.
#
# Der Chat im Dock schickt "studio/api/kern/*" relativ zur Seite — also durch
# Biancas Durchreiche (bianca/server.py -> STUDIO_BASE) an den Editor. Diese
# Probe geht denselben Weg: faellt die Durchreiche aus, faellt sie hier auf,
# nicht erst im Browser. Schreibt nichts (Kern nutzt den Sim-Gateway).
#
# Aufruf:  python tools\_probe_dock_kern.py [basis]
#   basis  Default http://127.0.0.1:8096  (oder die Tunnel-URL .../bianca)

import json
import sys
import urllib.error
import urllib.request

BASIS = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8096").rstrip("/")
SAETZE = [
    "ich moechte einen termin verschieben",
    "sag das nochmal",
    "vergiss es",
    "ich braeuchte einen termin zur kontrolle",
]
# Cloudflare laesst nackte Skript-Aufrufe nicht durch — Browser-Koepfe mitsenden.
KOEPFE = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": BASIS + "/",
    "Origin": BASIS,
}


def ruf(pfad, daten=None):
    korb = None if daten is None else json.dumps(daten).encode()
    anfrage = urllib.request.Request(BASIS + pfad, data=korb, headers=KOEPFE)
    try:
        with urllib.request.urlopen(anfrage, timeout=60) as antwort:
            return antwort.status, json.loads(antwort.read().decode())
    except urllib.error.HTTPError as fehler:
        return fehler.code, fehler.read().decode()[:300]


def main():
    stand, maske = ruf("/studio/api/kern/maske")
    if stand != 200 or not isinstance(maske, dict):
        print(f"FEHLER Maske {stand}: {maske}")
        return 1
    lagen = [s.get("id") for s in maske.get("szenarien", [])]
    felder = sum(len(g.get("felder", [])) for g in maske.get("gruppen", []))
    print(f"Maske ok — {len(maske.get('gruppen', []))} Gruppen / {felder} Felder, "
          f"{len(maske.get('invarianten', []))} Invarianten, Lagen: {', '.join(lagen) or '(keine)'}")

    stand, start = ruf("/studio/api/kern/start", {"tenant": "meddent", "szenario": lagen[0] if lagen else ""})
    if stand != 200 or not start.get("ok"):
        print(f"FEHLER Start {stand}: {start}")
        return 1
    kopf = start.get("kopf") or {}
    sid = (start.get("zug") or {}).get("sid") or kopf.get("sid")
    print(f"Start ok — {kopf.get('praxis')} · Policy {kopf.get('quelle')} r{kopf.get('revision')} · "
          f"Verstehen {'Modell' if kopf.get('hirn') else 'Regeln'} · sid {str(sid)[:8]}")
    print(f"  Bianca: {(start.get('zug') or {}).get('antwort', '')}")

    for satz in SAETZE:
        stand, zug = ruf("/studio/api/kern/zug", {"sid": sid, "text": satz})
        if stand != 200 or not zug.get("ok"):
            print(f"FEHLER Zug {stand}: {zug}")
            return 1
        z = zug.get("zug") or {}
        zu = z.get("zustand") or {}
        spur = " · ".join(t for t in [
            z.get("grund"), ("-> " + z["naechste"]) if z.get("naechste") else "",
            ("Werkzeug " + z["tool"]) if z.get("tool") else "",
            ("Anliegen " + zu["task"]) if zu.get("task") else "",
            ("Frage %sx" % zu["stockZahl"]) if zu.get("stockZahl") else "",
            "UEBERGABE" if z.get("uebergeben") else "",
        ] if t)
        print(f"\n  Du:     {satz}")
        print(f"  Bianca: {z.get('antwort', '')}")
        print(f"          [{spur}]")

    print("\nDurchreiche und Kern antworten — der Dock-Chat ist verdrahtet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
