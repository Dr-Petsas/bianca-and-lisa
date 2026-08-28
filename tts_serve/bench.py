"""TTS-Shootout: Chatterbox / CosyVoice (Container auf der 5090) gegen die
ElevenLabs-Baseline — gemessen wird BLOCKING wie live (kern/tts.speak wartet
auf das ganze Audio), gespeichert wird mit derselben Pegel-Schicht wie live.

Baseline (von diesem Rechner):
  .venv\\Scripts\\python tts_serve\\bench.py --engine eleven --voice bianca
  .venv\\Scripts\\python tts_serve\\bench.py --engine eleven --voice lisa

Lokale Container (sobald sie auf der 5090 laufen):
  .venv\\Scripts\\python tts_serve\\bench.py --engine lokal --url http://192.168.0.246:8210 --voice bianca
  .venv\\Scripts\\python tts_serve\\bench.py --engine lokal --url http://192.168.0.246:8211 --voice bianca

Referenz-Stimmen fuer die Container erzeugen (einmalig, aus ElevenLabs):
  .venv\\Scripts\\python tts_serve\\bench.py --ref-erzeugen

Ergebnis je Lauf: WAVs + ergebnis.csv unter tts_serve/bench_out/<lauf>/ und
eine Zusammenfassung (p50/p95-Latenz, Echtzeit-Faktor) auf der Konsole.
"""

from __future__ import annotations

import argparse
import json
import statistics
import struct
import sys
import time
from pathlib import Path

import httpx

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent))

from kern.config import (  # noqa: E402
    BIANCA_VOICE_ID,
    ELEVENLABS_API_KEY,
    ELEVENLABS_TTS_MODEL,
    ELEVENLABS_VOICE_ID,
)
from kern.tts import pcm16_wav  # noqa: E402

RATE = 24000
# Zentrale Stimmen-Landkarte (Chef 28.08.2026): bianca traegt auch Clara V7 +
# Demo-Clara (aliase.json: clara -> bianca). mann = Demo-Maennerstimme
# (Chef 24.08.2026), quizmaster = Demo-Quiz — IDs aus dem Pickadoc-Demo-Repo.
VOICE_IDS = {
    "bianca": BIANCA_VOICE_ID,
    "lisa": ELEVENLABS_VOICE_ID,
    "mann": "isKDUCXg28Ua3lIGHC0k",
    "quizmaster": "pNInz6obpgDQGcFmaJgB",
}

# Klon-Referenzen (Chef 28.08.2026: laengere Passagen, Bianca klang nicht
# wie das Original). Echte Umlaute, ruhiger Praxiston — Klone uebernehmen
# den Duktus. WORTGETREU — die .txt daneben ist CosyVoices Prompt-Transkript.
#
# ZWEI Laengen, weil die Engines gegenlaeufig ticken:
# - Chatterbox: je mehr Material, desto stabiler der Klang -> ~40 s
#   (stimmen/<name>.wav).
# - CosyVoice: der Prompt geht in JEDE Synthese ein; ist er laenger als der
#   Sprech-Satz, kommen Stummel/Abbrueche ("synthesis text too short than
#   prompt text", live 28.08.2026) -> ~10 s (stimmen/cosyvoice/<name>.wav).
REF_TEXT = (
    "Guten Tag, hier ist die Zahnarztpraxis am Stadtpark, schön, dass Sie "
    "anrufen. Was kann ich für Sie tun? Einen kleinen Moment bitte, ich "
    "schaue kurz in den Kalender. Also, am Donnerstag, dem vierzehnten, "
    "hätte ich um halb elf etwas frei, alternativ am Freitagnachmittag um "
    "Viertel nach drei. Passt Ihnen einer der beiden Termine? Wunderbar, "
    "dann trage ich Sie gleich ein. Bringen Sie bitte Ihre Versichertenkarte "
    "mit, und falls Sie Unterlagen von einer anderen Praxis haben, gern auch "
    "diese. Wenn etwas dazwischenkommt, rufen Sie uns einfach an, wir finden "
    "immer eine Lösung. Vielen Dank für Ihren Anruf, bis Donnerstag, und "
    "einen schönen Tag noch."
)

REF_TEXT_KURZ = (
    "Guten Tag, hier ist die Zahnarztpraxis am Stadtpark. Am Donnerstag um "
    "halb elf hätte ich einen Termin frei. Passt Ihnen das?"
)

# Der Quizmaster klingt nach Show, nicht nach Praxis — Klone uebernehmen den
# Duktus der Referenz, darum ein eigener Text.
REF_TEXT_QUIZ = (
    "Herzlich willkommen zur grossen Quizrunde! Ich bin Ihr Quizmaster und "
    "heute geht es um alles. Erste Frage, aufgepasst: Wie viele Zaehne hat "
    "ein erwachsener Mensch? Achtundzwanzig? Zweiunddreissig? Die Spannung "
    "steigt, die Uhr laeuft, drei, zwei, eins. Richtig, zweiunddreissig! "
    "Fantastisch, weiter geht die wilde Fahrt!"
)

REF_TEXT_QUIZ_KURZ = (
    "Herzlich willkommen zur grossen Quizrunde! Erste Frage, aufgepasst: "
    "Wie viele Zaehne hat ein erwachsener Mensch?"
)

REF_TEXTE = {"quizmaster": REF_TEXT_QUIZ}
REF_TEXTE_KURZ = {"quizmaster": REF_TEXT_QUIZ_KURZ}


def _wav_roh(pcm: bytes, rate: int = RATE) -> bytes:
    """WAV OHNE Pegel-Anhebung — Klon-Referenzen bleiben unverfaelscht."""
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16,
        1, 1, rate, rate * 2, 2, 16, b"data", len(pcm),
    )
    return header + pcm


def _eleven_pcm(text: str, voice_id: str, modell: str = "", latenz_optimiert: bool = True) -> bytes:
    modell = modell or ELEVENLABS_TTS_MODEL
    params = {"output_format": "pcm_24000"}
    if latenz_optimiert:
        params["optimize_streaming_latency"] = "3"
    r = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
        params=params,
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Accept": "application/octet-stream"},
        json={
            "text": text,
            "model_id": modell,
            **({"language_code": "de"} if ("v2_5" in modell or "_v3" in modell) else {}),
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.85, "use_speaker_boost": True},
        },
        timeout=60.0,
    )
    if r.status_code != 200:
        raise RuntimeError(f"eleven_http_{r.status_code}")
    return r.content


def _lokal_pcm(text: str, voice: str, url: str) -> bytes:
    r = httpx.post(f"{url.rstrip('/')}/speak", json={"text": text, "voice": voice}, timeout=120.0)
    if r.status_code != 200:
        raise RuntimeError(f"lokal_http_{r.status_code}: {r.text[:200]}")
    return r.content


def ref_erzeugen() -> None:
    if not ELEVENLABS_API_KEY:
        raise SystemExit("ELEVENLABS_API_KEY fehlt — Referenzen brauchen die heutigen Stimmen.")
    ziel = HIER / "stimmen"
    ziel.mkdir(exist_ok=True)
    ziel_cosy = ziel / "cosyvoice"
    ziel_cosy.mkdir(exist_ok=True)
    for name, vid in VOICE_IDS.items():
        print(f"rendere Referenz {name} (Voice {vid}) ...", flush=True)
        # Referenzen IMMER mit dem vollen Qualitaetsmodell und OHNE
        # Latenz-Optimierung rendern (Chef 28.08.2026: Bianca-Klon klang
        # nicht wie das Original — Ursache war die flash-gerenderte Referenz).
        for ordner, text in (
            (ziel, REF_TEXTE.get(name, REF_TEXT)),
            (ziel_cosy, REF_TEXTE_KURZ.get(name, REF_TEXT_KURZ)),
        ):
            pcm = _eleven_pcm(text, vid, modell="eleven_multilingual_v2", latenz_optimiert=False)
            (ordner / f"{name}.wav").write_bytes(_wav_roh(pcm))
            (ordner / f"{name}.txt").write_text(text, encoding="utf-8")
            print(f"  {ordner.name}/{name}.wav ({len(pcm) / 2 / RATE:.1f} s)", flush=True)
    print("Fertig. Ordner tts_serve/ jetzt auf die 5090 kopieren.")


def bench(engine: str, voice: str, url: str, korpus: Path) -> None:
    saetze = [json.loads(z) for z in korpus.read_text(encoding="utf-8").splitlines() if z.strip()]
    lauf = f"{engine}-{voice}" if engine == "eleven" else f"lokal-{url.rsplit(':', 1)[-1]}-{voice}"
    out = HIER / "bench_out" / lauf
    out.mkdir(parents=True, exist_ok=True)

    def rendern(text: str) -> bytes:
        if engine == "eleven":
            return _eleven_pcm(text, VOICE_IDS[voice])
        return _lokal_pcm(text, voice, url)

    # Warmlauf ausserhalb der Wertung (Verbindungsaufbau, Container-Caches).
    try:
        rendern("Guten Tag.")
    except Exception as e:
        raise SystemExit(f"Warmlauf fehlgeschlagen — Engine nicht erreichbar? {e}")

    zeilen = ["id;kategorie;zeichen;latenz_s;audio_s;rtf;fehler"]
    latenzen: list[float] = []
    audio_je_synthese: list[float] = []
    fehler = 0
    for s in saetze:
        sid, text = s["id"], s["text"]
        t0 = time.perf_counter()
        try:
            pcm = rendern(text)
            dt = time.perf_counter() - t0
        except Exception as e:
            fehler += 1
            print(f"  {sid}: FEHLER {e}", flush=True)
            zeilen.append(f"{sid};{s['kategorie']};{len(text)};;;;{e}")
            continue
        audio_s = len(pcm) / 2 / RATE
        rtf = audio_s / dt if dt > 0 else 0.0
        latenzen.append(dt)
        audio_je_synthese.append(rtf)
        (out / f"{sid}.wav").write_bytes(pcm16_wav(pcm))
        zeilen.append(f"{sid};{s['kategorie']};{len(text)};{dt:.2f};{audio_s:.2f};{rtf:.2f};")
        print(f"  {sid}: {dt:.2f} s fuer {audio_s:.1f} s Audio (x{rtf:.1f})", flush=True)
    (out / "ergebnis.csv").write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    if latenzen:
        lat = sorted(latenzen)
        p50 = statistics.median(lat)
        p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
        print(f"\n{lauf}: {len(latenzen)} ok, {fehler} Fehler")
        print(f"  Latenz p50 {p50:.2f} s, p95 {p95:.2f} s, max {lat[-1]:.2f} s")
        print(f"  Echtzeit-Faktor (Audio-s je Synthese-s) Median x{statistics.median(audio_je_synthese):.1f}")
        print(f"  WAVs + CSV: {out}")
    else:
        print(f"\n{lauf}: nichts gerendert ({fehler} Fehler)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--engine", choices=["eleven", "lokal"], default="")
    p.add_argument("--voice", choices=sorted(VOICE_IDS), default="bianca")
    p.add_argument("--url", default="", help="TTS-Container, z. B. http://192.168.0.246:8210")
    p.add_argument("--korpus", default=str(HIER / "korpus.jsonl"))
    p.add_argument("--ref-erzeugen", action="store_true", help="Klon-Referenzen aus ElevenLabs rendern")
    a = p.parse_args()

    if a.ref_erzeugen:
        ref_erzeugen()
        return
    if not a.engine:
        raise SystemExit("--engine eleven|lokal angeben (oder --ref-erzeugen)")
    if a.engine == "lokal" and not a.url:
        raise SystemExit("--url fehlt (Chatterbox :8210, CosyVoice :8211)")
    korpus = Path(a.korpus)
    if not korpus.is_file():
        raise SystemExit(f"Korpus fehlt: {korpus} — erst tts_serve/korpus_bauen.py laufen lassen.")
    bench(a.engine, a.voice, a.url, korpus)


if __name__ == "__main__":
    main()
