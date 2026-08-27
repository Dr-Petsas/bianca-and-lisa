"""Baut den Test-Korpus fuer den TTS-Shootout aus den ECHTEN Bausteinen des
Repos — keine erfundenen Beispielsaetze: genau das, was Lisa und Bianca live
sprechen (Fueller, Begruessungen, Pflichtfragen, Nummern-Readback,
Weiterleitung, Stille-Stupse), plus wenige handverlesene Haertefaelle
(Datum/Uhrzeit, englisch klingende Namen, Fachwoerter, langer Talk-Satz).

Aufruf:  .venv\\Scripts\\python tts_serve\\korpus_bauen.py
Schreibt: tts_serve/korpus.jsonl  (id, kategorie, text)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bianca import telefon, weiterleiten  # noqa: E402
from bianca.gehirn import FRAGE_VARIANTEN  # noqa: E402
from bianca.greeting import begruessung as bianca_gruss  # noqa: E402
from kern import filler, sprech, stille  # noqa: E402
from lisa.greeting import begruessung as lisa_gruss  # noqa: E402

PRAXIS = "Med Dent Zahnklinik"

HAERTEFAELLE = [
    "Am Donnerstag, den dritten September, haette ich um vierzehn Uhr dreissig einen Termin frei.",
    "Alternativ gaebe es noch Mittwoch um neun Uhr fuenfzehn oder Freitag um sechzehn Uhr.",
    "Sie sind dann bei Doktor Michael Petsas zur Prophylaxe eingetragen.",
    "Die Wurzelbehandlung bei Doktor Patrikis dauert ungefaehr eine Stunde.",
    "Oh, das kenne ich — bei Gewitter wird das Wartezimmer auch bei uns immer ganz schoen leer. "
    "Aber keine Sorge, wir finden gleich trotzdem einen Termin fuer Sie.",
    "Ja, gerne.",
    "Alles klar, vielen Dank fuer Ihren Anruf. Auf Wiederhoeren!",
]


def _saetze() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for s in filler.alle_saetze():
        out.append(("filler", s))
    out.append(("gruss", bianca_gruss(PRAXIS)))
    out.append(("gruss", lisa_gruss(
        PRAXIS, "Ihr Kontrolltermin muss leider vorverlegt werden.",
        patient={"firstName": "Anna", "lastName": "Bauer", "gender": "w"},
    )))
    for varianten in FRAGE_VARIANTEN.values():
        for v in varianten:
            out.append(("frage", v))
    out.append(("nummer", f"Ich wiederhole die Nummer: {telefon.sprechbar('01776004600')}. Stimmt das so?"))
    out.append(("weiterleiten", weiterleiten.WAHRHEIT
                + " Ich kann Sie aber gern mit einem unserer Aerzte verbinden."))
    out.append(("weiterleiten", "Sehr gern — zu welchem unserer Aerzte darf ich Sie verbinden?"))
    out.append(("stups", f"{stille.anrede(1)} Wir waren mitten in der Terminaufnahme. "
                "Ihren Namen habe ich schon."))
    out.append(("stups", f"{stille.anrede(2)} {stille.frage_praefix('Wie ist denn Ihre Handynummer?')}"))
    for s in HAERTEFAELLE:
        out.append(("haerte", s))
    return out


def main() -> None:
    ziel = Path(__file__).resolve().parent / "korpus.jsonl"
    gesehen: set[str] = set()
    zaehler: dict[str, int] = {}
    zeilen: list[str] = []
    for kategorie, roh in _saetze():
        text = sprech.sanitize(roh)
        if not text or text in gesehen:
            continue
        gesehen.add(text)
        zaehler[kategorie] = zaehler.get(kategorie, 0) + 1
        eintrag = {"id": f"{kategorie}-{zaehler[kategorie]:02d}", "kategorie": kategorie, "text": text}
        zeilen.append(json.dumps(eintrag, ensure_ascii=False))
    ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    print(f"korpus geschrieben: {ziel} ({len(zeilen)} Saetze, {sum(len(z) for z in zeilen)} Zeichen)")
    for k, n in sorted(zaehler.items()):
        print(f"  {k}: {n}")


if __name__ == "__main__":
    main()
