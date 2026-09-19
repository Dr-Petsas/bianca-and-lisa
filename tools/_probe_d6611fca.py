"""Nachstellung des MedDent-Anrufs d6611fca (19.09.2026 21:42) — nur Ernte, kein Netz."""
from bianca import gehirn

SAETZE = [
    # Live-Wortlaute des Anrufs
    "Ich bin mir nicht sicher, ob ich einen Termin bei Ihnen habe.",
    "Ja, mein Nachname ist Petsas, du hast mich doch erkannt.",
    # Gegenproben: echte Namen muessen weiter geerntet werden
    "Ich bin Michael Petsas.",
    "Ich heisse Mirko Sauer.",
    "Ich bin Sicher.",
    "Ich bin mir sicher, ich war letztes Jahr bei Doktor Petsas.",
    "Wir sind uns noch nicht begegnet.",
]

for satz in SAETZE:
    s = {"frage": "", "modus": ""}
    neu = gehirn.einsammeln(s, satz)
    sam = s.get("sammler") or {}
    print(f"{satz!r}")
    print(f"   modus={sam.get('modus') or s.get('modus')!r}"
          f" vorname={sam.get('vorname')!r} nachname={sam.get('nachname')!r}"
          f" neu={sorted(neu)}")
