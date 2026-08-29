"""Erst-Ansagen frisch rendern + waermen (Chef 29.08.2026).

Rendert die aktuellen Begruessungen beider Stimmen gegen den echten
TTS-Container, misst Dauer und laengste Pause roh vs. gestrafft
(kern/tts.pausen_straffen) und legt die abgenommenen Renders in den
Platten-Cache — mit DENSELBEN Keys, die die Dienste beim Start nutzen
(Stimme "bianca" bzw. "lisa"). Schreibt nie in Kalender oder Kartei.
"""

from __future__ import annotations

import array
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kern import tenants, tts


def _analyse(blob: bytes) -> tuple[float, float]:
    """(Dauer s, laengste Stille s) eines eigenen PCM16-WAVs."""
    if not blob or blob[:4] != b"RIFF":
        return 0.0, 0.0
    a = array.array("h")
    a.frombytes(blob[44:])
    fenster = tts.PCM_RATE // 100  # 10 ms
    n = len(a) // fenster
    laengste = lauf = 0
    for i in range(n):
        if max((abs(s) for s in a[i * fenster:(i + 1) * fenster]), default=0) < tts.AKTIV_SCHWELLE:
            lauf += 1
            laengste = max(laengste, lauf)
        else:
            lauf = 0
    return len(a) / tts.PCM_RATE, laengste * fenster / tts.PCM_RATE


def main() -> int:
    if not tts.TTS_BASE:
        print("TTS_BASE ist leer — nichts zu rendern (ElevenLabs-Pfad).")
        return 1
    from bianca.greeting import begruessung as bianca_gruss
    from lisa.greeting import begruessung as lisa_gruss

    t = tenants.laden("meddent")
    plaene = [
        ("bianca", bianca_gruss(tenants.praxis_melde(t))),
        ("lisa", lisa_gruss(tenants.praxis_von(t), "Kontrolltermin vorverlegen",
                            behandler=t.get("behandler") or "")),
    ]
    for stimme, text in plaene:
        tts.set_voice("", stimme)
        print(f"[{stimme}] {text}")
        roh = tts.engine().speak(text)
        d, p = _analyse(roh)
        print(f"  roh:       {d:5.2f} s, laengste Pause {p:.2f} s")
        d, p = _analyse(tts.pausen_straffen(roh))
        print(f"  gestrafft: {d:5.2f} s, laengste Pause {p:.2f} s")
        # Rohen LRU-Eintrag verwerfen, dann regulaer waermen (frischer
        # Render + Straffung + Laengen-/Gegenhoer-Abnahme + Platten-Pin).
        tts._vergessen(text)
        tts.warm(text)
        d, p = _analyse(tts.speak_dauerhaft(text))
        print(f"  gewaermt:  {d:5.2f} s, laengste Pause {p:.2f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
