"""Handprobe: Kartei-Suche gegen die Live-Cloud-Functions (nur lesend)."""

import sys

from kern import patients
from kern.tenants import laden


def main() -> int:
    q = sys.argv[1] if len(sys.argv) > 1 else "Tzannis"
    t = laden("meddent")
    found = patients.search_patients(t, q)
    for p in found.get("patients") or []:
        k = patients.karten_patient(p)
        print(f"id={k.get('id')} name={k.get('name')!r} phone={k.get('phone')!r} test={k.get('test')}")
    if not found.get("patients"):
        print("kein Treffer", found.get("error") or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
