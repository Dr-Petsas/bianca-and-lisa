"""End-zu-End-Probe der Client-Kette: kern.tts gegen den ECHTEN Container.

Prüft kann_stream() und zieht eine Äußerung über speak_stream — zählt
Häppchen und misst die Zeit bis zum ersten. Läuft mit der .env des Repos.
"""

from __future__ import annotations

import time

from kern import tts

eng = tts.engine()
print(f"engine={eng.name} anzeige={tts.engine_anzeige()!r} kann_stream={getattr(eng, 'kann_stream', lambda: False)()}")

text = ("Ich habe Ihren Termin am Donnerstag um vierzehn Uhr dreißig eingetragen. "
        "Bitte bringen Sie Ihre Versichertenkarte mit. Falls etwas dazwischenkommt, "
        "rufen Sie uns einfach an, dann finden wir gemeinsam einen neuen Termin.")
t0 = time.perf_counter()
erster = 0.0
stuecke = []
for wav in eng.speak_stream(text):
    if not erster:
        erster = time.perf_counter() - t0
    stuecke.append(len(wav))
gesamt = time.perf_counter() - t0
audio_s = sum(max(0, n - 44) for n in stuecke) / 2 / tts.PCM_RATE
print(f"haeppchen={len(stuecke)} erster={erster:.2f}s gesamt={gesamt:.2f}s audio={audio_s:.1f}s")
