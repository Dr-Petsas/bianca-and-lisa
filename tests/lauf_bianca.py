"""Testläufer ohne pytest: führt alle test_*-Funktionen der Kern-Suiten aus."""

import sys
import traceback

MODULE = [
    "tests.test_bianca_bausteine",
    "tests.test_weiterleiten",
    "tests.test_buchwache",
    "tests.test_sprech",
    "tests.test_wissen",
    "tests.test_filler",
    "tests.test_notes",
    "tests.test_patients",
    "tests.test_greeting",
    "tests.test_identitaet",
    "tests.test_notiz",
]


def main() -> int:
    gruen, rot = 0, 0
    for modname in MODULE:
        try:
            mod = __import__(modname, fromlist=["*"])
        except Exception:
            print(f"IMPORT ROT {modname}")
            traceback.print_exc()
            rot += 1
            continue
        for name in dir(mod):
            if not name.startswith("test_"):
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            try:
                fn()
                gruen += 1
            except Exception:
                print(f"ROT {modname}.{name}")
                traceback.print_exc()
                rot += 1
    print(f"\n{gruen} gruen, {rot} rot")
    return 1 if rot else 0


if __name__ == "__main__":
    sys.exit(main())
