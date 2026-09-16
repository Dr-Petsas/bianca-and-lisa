"""Statische Sofort-Audios einer Mandantenstimme kontrolliert neu rendern.

Gedacht fuer einen neuen Stimmklon: Füller, Barge-Quittungen und
Stille-Notfallsaetze liegen dauerhaft im gemeinsamen TTS-Platten-Cache.
Der Cache-Schluessel trennt zwar die Stimmen, aber ein einmal mit einer
falschen Referenz erzeugter Eintrag bleibt sonst dauerhaft liegen.

Aufruf im App-Container:

    python tools/rerender_statische_stimme.py --tenant ruether
    python tools/rerender_statische_stimme.py --tenant ruether --schreiben

Nach dem Schreib-Lauf den betroffenen App-Container in einer Anrufpause neu
starten. Erst dann werden die frischen Dateien in die laufende URL-Ablage
eingelesen.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kern import assistent, filler, tenants, tts, unterbrechung
from kern.dienst import NOTFALL_SAETZE


def statische_saetze() -> list[str]:
    """Alle kurzen Audios, die der Dienst vor einem Anruf vorlaedt."""
    raus: list[str] = []
    for text in (
        *filler.alle_saetze(),
        *unterbrechung.QUITTUNGEN,
        *NOTFALL_SAETZE,
    ):
        sauber = " ".join(str(text or "").split()).strip()
        if sauber and sauber not in raus:
            raus.append(sauber)
    return raus


def _stimme_im_container(voice: str) -> None:
    if not tts.TTS_BASE:
        raise RuntimeError("TTS_BASE ist leer")
    r = httpx.get(f"{tts.TTS_BASE}/health", timeout=5.0)
    r.raise_for_status()
    stimmen = [str(x).strip().lower() for x in (r.json() or {}).get("voices", [])]
    if voice not in stimmen:
        raise RuntimeError(f"Stimme {voice!r} fehlt im TTS-Container: {stimmen}")


def rendern(tenant_id: str, *, schreiben: bool = False) -> int:
    tenant = tenants.laden(tenant_id)
    voice = assistent.stimme(tenant)
    if not voice:
        raise RuntimeError(
            f"Mandant {tenant_id!r} hat keine eigene Stimme; "
            "Prozess-Default wird nicht blind neu gerendert"
        )
    texte = statische_saetze()
    print(
        f"Mandant={tenant_id} Assistenz={assistent.name(tenant)} "
        f"Stimme={voice} Saetze={len(texte)}"
    )
    if not schreiben:
        for text in texte:
            print(f"  PLAN {text}")
        print("(Read-only. Mit --schreiben neu rendern.)")
        return 0

    _stimme_im_container(voice)
    fehler: list[str] = []
    with tts.stimme(voice):
        for text in texte:
            tts._vergessen(text)
            tts.warm(text)
            datei: Path = tts._dauerhaft_datei(text)
            if not datei.is_file() or datei.stat().st_size <= 44:
                fehler.append(text)
                print(f"  FEHLER {text}")
            else:
                print(f"  OK {datei.name} {datei.stat().st_size:>8} B  {text}")
    if fehler:
        raise RuntimeError(f"{len(fehler)} Audio(s) nicht neu gerendert")
    print(f"FERTIG: {len(texte)} Audios sicher mit Stimme {voice!r} gerendert.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", required=True)
    p.add_argument("--schreiben", action="store_true")
    args = p.parse_args()
    return rendern(args.tenant, schreiben=bool(args.schreiben))


if __name__ == "__main__":
    raise SystemExit(main())
