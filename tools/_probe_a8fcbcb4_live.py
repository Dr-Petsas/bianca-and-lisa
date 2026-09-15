"""Abnahme-Probe W-AKTE-HANDY im Container (read-only, kein Kalender-Write).

Prueft am DEPLOYTEN Stand die vier Wachen aus Anruf a8fcbcb4:
Handy-Erkennung, telefon_alt nie gegen Festnetz, Abschlussfrage mit
Antwort-Verarbeitung, Fakten-Wache fuer Buchungs-/Nummern-Behauptung.

    docker exec -w /app telefonki-bianca-test-1 python tools/_probe_a8fcbcb4_live.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("TALK_SCHICHT", "0")

from bianca import flow, gehirn, telefon  # noqa: E402
from kern import calendar, fakten_wache, patients  # noqa: E402

FEST = "0712331540"
HANDY = "015254528152"

fehler: list[str] = []


def pruef(name: str, ist, soll) -> None:
    ok = ist == soll
    print(f"{'OK   ' if ok else 'ROT  '} {name}: {ist!r}" + ("" if ok else f" (soll {soll!r})"))
    if not ok:
        fehler.append(name)


# 1) Handy-Erkennung
pruef("ist_handy Festnetz", telefon.ist_handy(FEST), False)
pruef("ist_handy Handy", telefon.ist_handy(HANDY), True)
pruef("ist_handy_de Festnetz", patients.ist_handy_de(FEST), False)
pruef("ist_handy_de Handy", patients.ist_handy_de(HANDY), True)

# 2) telefon_alt nie gegen eine Festnetz-Aktennummer
basis = {
    "modus": "buchen", "warSchonMal": True,
    "vorname": "Annemarie", "nachname": "Mack", "buchstabiert": True,
    "patientId": "Uz5O", "bekannt": True,
    "telefon": HANDY, "telefonOk": True,
}


def frage_id(akte: str) -> str:
    fid, _text = gehirn.naechste_frage({"sammler": dict(basis, aktePhone=akte)})
    return fid


pruef("telefon_alt nicht gegen Festnetz", frage_id(FEST) != "telefon_alt", True)
pruef("telefon_alt gegen altes Handy", frage_id("01701234567"), "telefon_alt")

# 3) Abschlussfrage: registriert + Antwort verarbeitet
sit = {"sammler": {}}
frage = flow._sonst_noch_frage(sit)
pruef("Abschlussfrage Text", frage, flow._SONST_NOCH)
pruef("Abschlussfrage registriert", sit["sammler"].get("frage"), "sonst_noch")
pruef("Abschlussfrage gemerkt", sit.get("sonstNochGefragt"), True)
nein = flow._sonst_noch_antwort(sit, "nein danke", ja_text="Gerne.", nein_text="Danke, tschuess.")
pruef("Nein legt auf", bool((nein or {}).get("hangup")), True)
sit2 = {"sammler": {"frage": "sonst_noch"}, "sonstNochGefragt": True}
ja = flow._sonst_noch_antwort(sit2, "ja", ja_text="Gerne — was kann ich noch tun?", nein_text="x")
pruef("Ja laedt ein", bool((ja or {}).get("hangup")), False)

# 4) Fakten-Wache
leer = {"sammler": {"telefon": HANDY}, "tools": []}
pruef(
    "Buchungs-Behauptung faellt",
    fakten_wache.unbelegte_behauptung(leer, "Dann ist alles für Sie eingetragen."),
    "buchen",
)
pruef(
    "Nummern-Behauptung faellt",
    fakten_wache.unbelegte_behauptung(leer, "Alles klar, die Nummer ist gespeichert."),
    "nummer",
)
pruef(
    "Verneinung bleibt frei",
    fakten_wache.unbelegte_behauptung(leer, "Der Termin ist noch nicht eingetragen."),
    "",
)
belegt = {"sammler": {"aktePhone": HANDY, "telefon": HANDY}, "tools": []}
pruef(
    "Kartei-Stand ist belegt",
    fakten_wache.unbelegte_behauptung(belegt, "Ihre Nummer ist bei uns hinterlegt."),
    "",
)
echt = {"sammler": {"telefon": HANDY}, "tools": [], "lastBook": {"ok": True}}
pruef(
    "Echte Buchung darf das sagen",
    fakten_wache.unbelegte_behauptung(echt, "Dann ist alles für Sie eingetragen."),
    "",
)

print(f"BOOK_FIX_PHONE={calendar.BOOK_FIX_PHONE} BOOK_VERIFY_AKTE={calendar.BOOK_VERIFY_AKTE}")
print("PROBE GRUEN" if not fehler else f"PROBE ROT: {fehler}")
raise SystemExit(1 if fehler else 0)
