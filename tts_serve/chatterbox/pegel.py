"""Nachbearbeitung je Synthese-Stueck: Rand-Stille kappen, Runaway erkennen.

Vorfall 28.08.2026 ("Artefakte/Genuschel"): Chatterbox haengt an manche
Stuecke sekundenlange Fast-Stille mit Atem-/Nuschel-Resten an (live gemessen:
Haeppchen mit 54-69 % Stille-Anteil, RMS weit unter Sprachniveau) und laeuft
selten in Runaway-Babble (27 s Audio fuer 50 Zeichen, 27.08. gemessen).
Beides gehoert NICHT auf die Leitung:

- rand_trim() kappt fuehrende/abschliessende Stille auf ein kurzes Polster —
  Satzpausen entstehen an der Naht aus den Polstern beider Nachbarstuecke.
- ist_runaway() meldet unplausibel langes Audio fuer die Textlaenge; der
  Server rendert dann EINMAL neu (Sampling ist stochastisch) und nimmt das
  kuerzere Ergebnis.

Bewusst ohne torch/numpy: pure bytes/array-Arithmetik, damit die Dev-Suite
(tests/test_chatterbox_pegel.py) das Modul ohne GPU-Umgebung prueft.
"""

from __future__ import annotations

import array

RATE = 24000
FENSTER = 720            # 30 ms
STILLE_RMS = 300         # Fenster-RMS darunter = Stille (wie kern/tts.py)
POLSTER_S = 0.15         # so viel Rand-Stille darf bleiben

# Sprechdauer-Plausibilitaet: Deutsch liegt bei ~13-15 Zeichen/s (~70 ms/
# Zeichen). Kalibriert am Cache-Befund 28.08.2026 (zweite Runde): gute
# Renders lagen bei 47-97 ms/Zeichen, Babble ab ~120 — mit 0,6/1,6 rutschte
# "Sagen Sie mir bitte noch Ihre Handynummer?" (6,04 s, 144 ms/Z) noch
# durch. Ein falscher Alarm kostet nur einen zweiten Render (das kuerzere
# gewinnt) — lieber einmal umsonst wuerfeln als Babble pinnen.
S_JE_ZEICHEN = 0.09
GRUND_S = 0.4
RUNAWAY_FAKTOR = 1.4
RUNAWAY_MIN_ABSTAND_S = 1.2


def _fenster_still(samples: array.array, ab: int) -> bool:
    quad = 0
    for s in samples[ab: ab + FENSTER]:
        quad += s * s
    return (quad / FENSTER) ** 0.5 < STILLE_RMS


def rand_trim(pcm: bytes) -> bytes:
    """Fuehrende/abschliessende Stille auf je POLSTER_S kappen (sample-gerade).

    Innere Pausen bleiben unangetastet — nur die Raender, damit halb leere
    Schwanz-Stuecke nicht als eigene 'Nuschel-Haeppchen' auf die Docks gehen.
    """
    n = len(pcm) // 2
    if n < FENSTER * 3:
        return pcm
    samples = array.array("h", pcm[: n * 2])
    vorn = 0
    while vorn + FENSTER <= n and _fenster_still(samples, vorn):
        vorn += FENSTER
    hinten = n
    while hinten - FENSTER >= vorn and _fenster_still(samples, hinten - FENSTER):
        hinten -= FENSTER
    if hinten <= vorn:
        # komplett still: kurzes Polster zurueckgeben statt Leerlauf
        return pcm[: int(POLSTER_S * RATE) * 2]
    polster = int(POLSTER_S * RATE)
    von = max(0, vorn - polster)
    bis = min(n, hinten + polster)
    return samples[von:bis].tobytes()


def max_plausibel_s(text: str) -> float:
    erwartet = GRUND_S + S_JE_ZEICHEN * len(text or "")
    return max(RUNAWAY_FAKTOR * erwartet, erwartet + RUNAWAY_MIN_ABSTAND_S)


def ist_runaway(text: str, dauer_s: float) -> bool:
    """True, wenn das Audio fuer diesen Text unplausibel lang geraten ist."""
    return dauer_s > max_plausibel_s(text)
