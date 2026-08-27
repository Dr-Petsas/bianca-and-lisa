"""Alle Offline-Tests ohne pytest ausführen: jede tests/test_*.py importieren
und alle test_*-Funktionen aufrufen. Probe-Skripte (echtes LLM/Netz) bleiben
bewusst außen vor."""

from __future__ import annotations

import importlib
import os
import sys
import traceback

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
sys.path.insert(0, HIER)


def main() -> int:
    gruen = 0
    rot = []
    for datei in sorted(os.listdir(HIER)):
        if not (datei.startswith("test_") and datei.endswith(".py")):
            continue
        modul = importlib.import_module(datei[:-3])
        for name in sorted(dir(modul)):
            if not name.startswith("test_"):
                continue
            fn = getattr(modul, name)
            if not callable(fn):
                continue
            try:
                fn()
                gruen += 1
            except Exception:
                rot.append(f"{datei}::{name}")
                traceback.print_exc()
    print(f"gruen: {gruen}, rot: {len(rot)}")
    for r in rot:
        print(f"ROT {r}")
    return 1 if rot else 0


if __name__ == "__main__":
    raise SystemExit(main())
