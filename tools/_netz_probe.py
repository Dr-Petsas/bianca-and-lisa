"""Erreichbarkeit der Ohr-Dienste aus dem laufenden App-Container pruefen.

Hintergrund: die Tailnet-IPs haben am 19.09.2026 gewechselt (pickadoc1
100.82.122.62 -> 100.77.30.98, Dev-Rechner 100.81.214.94 -> 100.111.107.2).
Eine hart notierte IP in der Server-.env ist danach still tot — Parakeet
oder Qwen antworten nicht mehr, ohne dass es am Telefon auffaellt.

Aufruf im Container:

    docker exec -w /app telefonki-bianca-1 python tools/_netz_probe.py
"""

from __future__ import annotations

import os
import urllib.request

ZIELE = [
    ("STT_BASE (.env)", (os.environ.get("STT_BASE") or "").rstrip("/") + "/health"),
    ("STT ueber Tailscale-Namen", "http://pickadoc1.tail22c4dd.ts.net:8212/health"),
    ("STT ueber Docker-Gateway", "http://172.17.0.1:8212/health"),
]
for teil in (os.environ.get("STT_QWEN_FINAL_BASE") or "").split(","):
    teil = teil.strip().rstrip("/")
    if teil:
        ZIELE.append((f"Qwen {teil}", teil + "/health"))


def main() -> int:
    for name, url in ZIELE:
        if not url or url == "/health":
            print(f"{name:34} -> nicht gesetzt")
            continue
        try:
            with urllib.request.urlopen(url, timeout=4) as r:
                leib = r.read(140).decode("utf-8", "ignore")
            print(f"{name:34} -> {r.status} {leib}")
        except Exception as exc:  # noqa: BLE001 — Diagnose, nie werfend
            print(f"{name:34} -> FEHLER {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
