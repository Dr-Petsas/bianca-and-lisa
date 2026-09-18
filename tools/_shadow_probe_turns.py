"""Treiber: fuehrt gefahrlos (testNoWrite) eine Buchungs-Konversation gegen
die lokale bianca-test-API und erzeugt so echte Shadow-Protokollzeilen.

Read/collect only: keine Kalender-Schreibzugriffe (test + testNoWrite).
"""
import json
import sys
import urllib.request

B = "http://127.0.0.1:8098"


def post(path, obj):
    r = urllib.request.Request(
        B + path,
        data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(r, timeout=30).read().decode()


def main():
    tenant = sys.argv[1] if len(sys.argv) > 1 else "meddent"
    s = json.loads(post("/api/start", {"test": True, "testNoWrite": True, "tenant": tenant}))
    sid = s.get("sessionId")
    print("SID", sid)
    konv = [
        "Guten Tag, ich haette gerne einen Termin",
        "Ja, ich war schon einmal da",
        "Bei Doktor Petsas",
        "Eine Kontrolle bitte",
        "Naechste Woche vormittags",
        "Mein Name ist Mueller",
        "Gesetzlich versichert",
    ]
    for t in konv:
        out = post("/api/turn", {"sessionId": sid, "text": t})
        letzte = ""
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("text"):
                letzte = d.get("text")
        print("U:", t, "|| B:", letzte[:80])
    print("FERTIG", sid)


if __name__ == "__main__":
    main()
