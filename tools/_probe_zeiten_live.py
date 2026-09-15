"""Live-Gegenprobe W-ZEITEN-WACHE (15.09.2026) — read-only, bucht nie.

Stellt jedem Mandanten die drei Fragen, auf die Ben (Rüther) am 15.09.2026
drei verschiedene Zeitpläne erfunden hat, und prüft:

- Rüther (keine belegten Zeiten): KEINE erfundene Zeit mehr im Mund —
  entweder die ehrliche Auskunft der Wache oder ein Satz ohne Zeitplan.
- MedDent/Thaler/Blessing (belegte Zeiten): die ECHTEN Zeiten kommen
  weiter — das ist die teurere Fehlerrichtung.

Aufruf im Container (dort steht das echte LLM/die echte DB):
    docker exec -w /app telefonki-bianca-test-1 python tools/_probe_zeiten_live.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bianca import agent as bagent
from bianca import session as bsession
from kern import zeiten_wache
from kern.tenants import laden
from kern.wissen import auskunft_themen, praxis_antwort

FRAGEN = [
    "Wann haben Sie geöffnet?",
    "Wann habt ihr auf?",
    "Haben Sie am Freitag offen?",
]

# Mandanten, die ihre Zeiten belegt haben sollten
MIT_ZEITEN = {"meddent", "thaler", "blessing"}


def _zeile(txt: str, breite: int = 150) -> str:
    return " ".join(str(txt or "").split())[:breite]


def probe(mandant: str) -> list[str]:
    fehler: list[str] = []
    t = laden(mandant)
    belegt = zeiten_wache.zeiten_belegt(t)
    print(f"\n=== {mandant} — Zeiten belegt: {'JA' if belegt else 'NEIN'} "
          f"(Wache {'aus' if belegt else 'SCHARF'}) ===")
    if mandant in MIT_ZEITEN and not belegt:
        fehler.append(f"{mandant}: Zeiten gelten als UNBELEGT — Wache wuerde "
                      f"die echte Auskunft streichen")
    for frage in FRAGEN:
        themen = auskunft_themen(frage)
        det, _ = praxis_antwort(t, frage)
        sit = bsession.neu(tenant=t)
        try:
            antw = bagent.user_turn(sit, frage)
        except Exception as exc:                       # LLM/Netz
            print(f"  F: {frage}\n     FEHLER: {exc}")
            fehler.append(f"{mandant}/{frage}: {exc}")
            continue
        text = " ".join(str(antw.get("text") or "").split())
        spur = ", ".join(e.get("w", "") for e in (antw.get("waechter") or []))
        print(f"  F: {frage}")
        print(f"     Thema erkannt: {sorted(themen) or '—'}"
              f" | deterministisch: {'JA' if det else 'nein'}")
        print(f"     A: {_zeile(text)}")
        if spur:
            print(f"     Waechter: {spur}")
        if belegt:
            # Gegenprobe: die echten Zeiten muessen weiter gesprochen werden.
            if "zeiten-wache" in spur:
                fehler.append(f"{mandant}/{frage}: Wache hat eine BELEGTE "
                              f"Auskunft gestrichen")
            if "Uhr" not in text and det:
                fehler.append(f"{mandant}/{frage}: deterministische Auskunft "
                              f"kam nicht im Mund an")
        else:
            if zeiten_wache.ist_zeit_auskunft(text):
                fehler.append(f"{mandant}/{frage}: ERFUNDENE Zeit noch im "
                              f"Mund: {_zeile(text, 90)}")
    return fehler


def main() -> int:
    fehler: list[str] = []
    for mandant in ["ruether", "meddent", "thaler", "blessing"]:
        try:
            fehler += probe(mandant)
        except Exception as exc:
            print(f"\n=== {mandant}: KONNTE NICHT GEPRUEFT WERDEN: {exc}")
            fehler.append(f"{mandant}: {exc}")
    print("\n" + "=" * 60)
    if fehler:
        print(f"ROT — {len(fehler)} Befund(e):")
        for f in fehler:
            print(f"  - {f}")
        return 1
    print("GRUEN — keine erfundenen Zeiten, belegte Auskuenfte unberuehrt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
