"""Schnellprobe des Anliegen-Katalogs (offline, kein Netz, schreibt nichts)."""
from kern import anliegen_katalog as ak

print("Anliegen:", len(ak.KATALOG))
for a in ak.KATALOG:
    print(f"  {a.id:22} {len(a.optionen)} Optionen, {len(a.haken)} Haken")

roh = {
    "anliegen": {
        "rezept": {"wahl": "versand", "haken": ["karte", "btm"],
                   "prosa": "Wiederholungsrezepte schicken wir raus"},
        "termin": {"wahl": "nie"},
        "quatsch": {"wahl": "nie"},
        "befund": {"wahl": "gibtsnicht"},
        "kosten": {"wahl": "eigene_auskunft"},
    }
}
regeln, warn = ak.parse(roh)
print("\nRegeln:", sorted(regeln))
for w in warn:
    print("  WARN:", w)
r = regeln["rezept"]
print("\nrezept  folge:", r.folge.value, "haken:", r.haken)
print("rezept  satz :", ak.antwort(r))
print("befund  wahl :", regeln["befund"].wahl, "(konservativ?)")
print("kosten  wahl :", regeln["kosten"].wahl, "(ohne Prosa -> Standard?)")
print("\nMaske-Felder:", sorted(ak.maske()))
print("Roundtrip:", sorted(ak.as_dict(regeln)["anliegen"]))
print("\nOhne Eintrag:", ak.aus_tenant({"praxisName": "x"}), ak.regel({}, "rezept"))
