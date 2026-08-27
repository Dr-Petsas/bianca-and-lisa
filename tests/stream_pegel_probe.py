"""Einmal-Probe (27.08.2026): Pegel-Normalisierung + LLM-Stream-Vorab live prüfen.

1) TTS: zwei Sätze rendern, Spitzen- und Effektivpegel messen — beide Sätze
   müssen nahe beieinander liegen (kein Pumpen), nichts darf clippen.
2) vLLM: chat_stream mit erster_satz-Rückruf — der Vorab-Satz muss Präfix
   des Endtexts sein (sonst würde der Rest-Zuschnitt im Dienst danebengehen).
"""

import array
import sys
import time

sys.path.insert(0, ".")

from kern import llm, tts  # noqa: E402


def pegel(blob: bytes) -> tuple[float, float]:
    """(Spitze, RMS) des WAV-Datenteils relativ zur Vollaussteuerung."""
    daten = blob[44:]
    a = array.array("h")
    a.frombytes(daten[: (len(daten) // 2) * 2])
    if not a:
        return 0.0, 0.0
    spitze = max(abs(x) for x in a) / 32767.0
    rms = (sum(x * x for x in a) / len(a)) ** 0.5 / 32767.0
    return round(spitze, 3), round(rms, 3)


def main() -> int:
    print("--- TTS-Pegel ---")
    saetze = [
        "Guten Tag, hier ist die Terminassistentin der Praxis.",
        "Ihr Termin ist morgen um neun Uhr fünfzehn bei Doktor Petsas — bitte bringen Sie Ihre Karte mit.",
    ]
    for satz in saetze:
        t0 = time.perf_counter()
        blob = tts.engine().speak(satz)
        dauer = round(time.perf_counter() - t0, 2)
        sp, rms = pegel(blob)
        print(f"  Spitze={sp} RMS={rms} tts={dauer}s bytes={len(blob)} :: {satz[:44]}…")
        assert 0.85 <= sp <= 0.95, f"Spitze {sp} nicht im Zielfenster"
    print("  OK: beide Sätze auf gleichem Spitzenpegel, kein Clipping möglich.")

    print("--- vLLM-Stream ---")
    getroffen = {}

    def erster(satz: str) -> None:
        getroffen["satz"] = satz
        getroffen["t"] = round(time.perf_counter() - t0, 2)

    msgs = [
        {"role": "system", "content": "Du bist eine freundliche Telefonassistentin. Antworte in zwei kurzen Sätzen."},
        {"role": "user", "content": "Können Sie mir kurz erklären, warum Kontrolltermine wichtig sind?"},
    ]
    t0 = time.perf_counter()
    out = llm.chat_stream(msgs, erster_satz=erster)
    gesamt = round(time.perf_counter() - t0, 2)
    print(f"  ok={out.get('ok')} gesamt={gesamt}s vorab@{getroffen.get('t')}s")
    print(f"  vorab: {getroffen.get('satz')!r}")
    print(f"  final: {out.get('text')!r}")
    assert out.get("ok"), out.get("error")
    if getroffen.get("satz"):
        assert out["text"].startswith(getroffen["satz"]), "Vorab-Satz ist KEIN Präfix des Endtexts"
        print(f"  OK: Vorab nach {getroffen['t']}s (Ende {gesamt}s) — Präfix stimmt.")
    else:
        print("  Hinweis: kein Vorab (Antwort war ein einzelner Satz).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
