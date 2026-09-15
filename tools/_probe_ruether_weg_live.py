"""Live-Probe: Ben kann den Weg sagen, erfindet aber keine Zeiten.

Read-only. Kein Kalender-Write, kein LLM auf dem Fakten-Pfad (jeder
LLM-Aufruf ist hier ein Testbruch â€” die Auskunft MUSS deterministisch sein).

    docker exec -w /app telefonki-bianca-1 python tools/_probe_ruether_weg_live.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kern import agentprofil, assistent, wissen  # noqa: E402

DID = "+4921154244160"
FRAGEN_WEG = [
    "Wie komme ich denn zu Ihnen?",
    "Wo ist die Praxis?",
    "Sagen Sie mir bitte die Adresse.",
    # Der Live-Verhoerer aus Session dda01bf...: STT verstuemmelt die Wegfrage.
    "Rennen Sie mir kurz sagen, wie ich die praktisch erreiche.",
]
FRAGEN_ZEIT = [
    "Wann haben Sie geÃ¶ffnet?",
    "Wie sind Ihre Ã–ffnungszeiten?",
]

fehler: list[str] = []


def pruefe(bedingung: bool, was: str) -> None:
    print(f"  {'OK  ' if bedingung else 'FAIL'} {was}")
    if not bedingung:
        fehler.append(was)


t = agentprofil.fuer_did(DID)
print(f"Mandant {t.get('_id') or '?'} / Quelle {t.get('_quelle')} / "
      f"Assistenz {assistent.name(t)} ({assistent.genus(t)}), Stimme "
      f"{assistent.stimme(t)!r}")
print()

print("== Wegfrage ==")
for frage in FRAGEN_WEG:
    text, themen = wissen.praxis_antwort(t, frage)
    print(f'  "{frage}"')
    print(f"     -> {text or '(nichts)'}")
    pruefe("anfahrt" in themen, f"Thema anfahrt erkannt: {frage!r}")
    pruefe("Erich-Ollenhauer" in text, f"Adresse genannt: {frage!r}")
    pruefe(not any(z in text for z in "0123456789"),
           f"sprechbar ohne Ziffern: {frage!r}")

print()
print("== Zeitfrage: Portal traegt nur den Mo-So-Default, also schweigen ==")
for frage in FRAGEN_ZEIT:
    text, themen = wissen.praxis_antwort(t, frage)
    print(f'  "{frage}" -> {text or "(nichts â€” Gespraechspfad uebernimmt)"}')
    pruefe(not text, f"keine erfundene Zeit: {frage!r}")

print()
print("== Gegenprobe: die drei Zahnpraxen bleiben unberuehrt ==")
for did, erwartet in (("+4921154244101", "meddent"),
                      ("+4921154244105", "thaler")):
    andere = agentprofil.fuer_did(did)
    text, _ = wissen.praxis_antwort(andere, "Wie komme ich denn zu Ihnen?")
    print(f"  {erwartet}: {assistent.name(andere)} -> {(text or '(nichts)')[:90]}")
    pruefe("Erich-Ollenhauer" not in text, f"{erwartet} kennt Ruethers Adresse nicht")
    pruefe(assistent.name(andere) == "Bianca", f"{erwartet} bleibt Bianca")

print()
print(f"ERGEBNIS: {'ALLE GRUEN' if not fehler else str(len(fehler)) + ' FEHLER'}")
for f in fehler:
    print("   -", f)
raise SystemExit(1 if fehler else 0)
