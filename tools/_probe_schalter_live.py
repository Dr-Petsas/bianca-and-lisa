"""Live-Probe: fuer WELCHE Anrufe ist der Dialogkern scharf? (read-only)

Liest die echte ``CONTROLLER_ENFORCE``-Umgebung des laufenden Containers und
fragt ``live.an()`` mit Sitzungen, wie ``agentprofil.call_erfassen`` sie baut
(``callerPhone`` in +E164, Tenant mit clientId/Name). Schreibt nichts.

    docker exec -w /app telefonki-bianca-1 python tools/_probe_schalter_live.py
"""

from __future__ import annotations

import os

from bianca.controller import live

MEDDENT = {"clientId": "MEe4ZQHEzOPzLcexyhdT", "name": "meddent"}
THALER = {"clientId": "AnFOHJHL4jzhIkGkOxpA", "name": "thaler"}

FAELLE = [
    ("Chef-Handy an MedDent", {"callerPhone": "+491776004600", "tenant": MEDDENT}),
    ("Chef-Handy an Thaler", {"callerPhone": "+491776004600", "tenant": THALER}),
    ("fremder Patient MedDent", {"callerPhone": "+4917612345678", "tenant": MEDDENT}),
    ("unterdrueckte Nummer", {"tenant": MEDDENT}),
]


def main() -> int:
    print(f"CONTROLLER_ENFORCE = {os.environ.get('CONTROLLER_ENFORCE') or '(leer)'}")
    print(f"CONTROLLER_SHADOW  = {os.environ.get('CONTROLLER_SHADOW') or '(leer)'}")
    for name, sit in FAELLE:
        print(f"  {name:26} -> Kern spricht: {live.an(dict(sit))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
