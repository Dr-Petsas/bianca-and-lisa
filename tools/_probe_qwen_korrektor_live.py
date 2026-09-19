"""Live-Probe: hoert Qwen als KORREKTOR wirklich mit? (read-only)

Gefragt ist nicht, ob Qwen den gesprochenen Zug uebernimmt — das soll er
seit dem 18.09.2026 ausdruecklich NICHT (QWEN_LIVE_OHR=0, Parakeet ist
IMMER der gesprochene Zug). Gefragt ist, ob sein Ergebnis beim asynchronen
Korrektor ANKOMMT: nur daraus lernt Bianca Woerterbuch, Hotwords und
Verlaufs-Korrektur der Folgezuege (W-QWEN-KORREKTOR).

Laeuft IM Container (Netzwege + .env wie live):
    docker exec -w /app telefonki-bianca-1 python tools/_probe_qwen_korrektor_live.py

Schreibt nichts: kein Kalender, keine Sitzung, keine Akte. Das Audio wird
im TTS-Container gerendert und nur im Speicher gehalten.
"""

from __future__ import annotations

import sys
import threading
import time

from kern import stt, tts

# Saetze mit Fachwort/Namen — genau die Stellen, an denen Parakeet und Qwen
# auseinanderlaufen duerfen. Der dritte ist eine Kurzantwort (Gegenprobe:
# auch da darf der Korrektor nichts kaputt machen).
SAETZE = [
    ("Ich braeuchte ein Roentgenbild vom Zahn.", "Röntgenbild, Petsas"),
    ("Ich moechte zu Doktor Petsas in die Praxis.", "Petsas, Patrikis"),
    ("Ja, gerne.", ""),
]


def _wav(text: str) -> bytes:
    """Satz im echten TTS-Container rendern (kein Cache-Eintrag noetig)."""
    return tts.engine().speak(text)


def main() -> int:
    print(f"Ohr        : {stt.engine_anzeige()}")
    print(f"Parakeet   : {stt.STT_BASE or '(leer)'}")
    print(f"Qwen final : {stt.STT_QWEN_FINAL_BASE or '(leer)'}")
    print(f"Live-Ohr   : {stt.QWEN_LIVE_OHR} (False = nur Korrektor, so gewollt)")
    if not stt.STT_QWEN_FINAL_BASE and not stt.STT_QWEN_BASE:
        print("FEHLER: kein Qwen konfiguriert — Korrektor kann nie lernen.")
        return 2

    nachtraege = 0
    for satz, keywords in SAETZE:
        print(f"\n--- {satz!r}")
        try:
            blob = _wav(satz)
        except Exception as exc:
            print(f"  TTS fehlgeschlagen: {type(exc).__name__}: {exc}")
            return 2

        da = threading.Event()
        gemeldet: dict = {}

        def _nachtrag(info: dict) -> None:
            gemeldet.update(info)
            da.set()

        t0 = time.perf_counter()
        lokal = stt.transcribe(
            blob,
            mime="audio/wav",
            name="probe.wav",
            keywords=keywords,
            nachtrag=_nachtrag,
        )
        print(f"  Parakeet ({time.perf_counter() - t0:.2f}s): {lokal!r}")

        # Der Korrektor wartet nie — die PROBE darf warten, sonst sieht sie
        # den spaeten Qwen-Lauf nicht.
        if da.wait(12.0):
            nachtraege += 1
            print(
                f"  Qwen  ({gemeldet.get('s')}s, spaet={gemeldet.get('spaet')}): "
                f"{gemeldet.get('text')!r} "
                f"[{gemeldet.get('source')} {gemeldet.get('reason') or 'ok'}]"
            )
        else:
            print("  Qwen: KEIN Nachtrag — Korrektor bekommt nichts zu lernen.")

    print(f"\nNachtraege: {nachtraege}/{len(SAETZE)}")
    return 0 if nachtraege else 1


if __name__ == "__main__":
    raise SystemExit(main())
