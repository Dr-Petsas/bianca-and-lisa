"""W-PHANTOMNAME: Gegenprobe im laufenden Container (read-only, kein Netz)."""
from bianca import gehirn


def ernten(satz: str, frage: str = "") -> dict:
    sit: dict = {}
    s = gehirn.sammler(sit)
    s["frage"] = frage
    gehirn.einsammeln(sit, satz)
    return s


FAELLE = [
    ("Ich bin mir nicht sicher, ob ich einen Termin bei Ihnen habe.", "", ("", "")),
    ("Ich bin mir sicher, ich war letztes Jahr bei Doktor Petsas.", "", ("", "")),
    ("Wir sind uns noch nicht begegnet.", "", ("", "")),
    ("Ich bin nicht sicher, ob das der richtige Termin war.", "", ("", "")),
    ("Ich bin Michael Petsas.", "", ("Michael", "Petsas")),
    ("Ich heisse Mirko Sauer.", "", ("Mirko", "Sauer")),
    ("Michael Sicher", "nachname", ("Michael", "Sicher")),
]

fehler = 0
for satz, frage, (v_soll, n_soll) in FAELLE:
    s = ernten(satz, frage)
    v, n = s.get("vorname") or "", s.get("nachname") or ""
    ok = (v, n) == (v_soll, n_soll)
    fehler += 0 if ok else 1
    print(f"{'OK ' if ok else 'ROT'} {satz!r} -> vorname={v!r} nachname={n!r}")
print("FEHLER:", fehler)
raise SystemExit(1 if fehler else 0)
