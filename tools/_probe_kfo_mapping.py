"""Mappt "schiefe Zaehne gerade haben" auf Kieferorthopaedie? (read-only)

Chef 13.09.2026 zum Anruf 1fbda5db: "dann sagt bianca dass sie einen termin
zur Kontrolluntersuchung buchen wird, ich weiss nicht ob sie im kalender auf
kieferorthopaedie gemappt haette". Im Session-Hirn stand:
    grund   = "Ich habe schiefe Zehen, ich moechte die gerade haben."   (STT!)
    motivId = qOQCI4vV2EhQVmKmRqdu / "KCH Kontrolluntersuchung"

Diese Probe liest NUR: echter Motivkatalog des Mandanten + das Mapping.
Sie bucht nicht, schreibt nichts.
"""

from bianca import besuchsgrund
from kern import motive
from kern.tenants import laden

SAETZE = [
    "Ich habe schiefe Zehen, ich möchte die gerade haben.",   # live verhoert
    "Ich habe schiefe Zähne, ich möchte die gerade haben.",   # korrekt gehoert
    "Ich möchte eine Zahnspange.",
    "Können Sie mir Invisalign machen?",
    "Ich hätte gern eine Beratung zur Kieferorthopädie.",
]


def main() -> int:
    sit = {"tenant": laden("meddent")}
    motive.anstossen(sit)
    kat = motive.katalog(sit) or []
    print(f"Katalog: {len(kat)} Besuchsgruende")
    treffer = [m for m in kat if any(
        w in f"{m.get('name','')} {m.get('info','')}".lower()
        for w in ("kiefer", "ortho", "invisalign", "aligner", "spange", "kfo"))]
    print(f"davon kieferorthopaedisch: {len(treffer)}")
    for m in treffer:
        print(f"  - {m.get('name')!r}  id={m.get('id')}")
    print()
    for satz in SAETZE:
        vm = besuchsgrund.katalog_treffer(satz, katalog=kat)
        kern, motiv = besuchsgrund.deute(sit["tenant"], satz, katalog=kat)
        print(f"{satz!r}")
        print(f"   katalog_treffer -> {(vm or {}).get('name')!r}")
        print(f"   deute           -> kern={kern!r} motiv={(motiv or {}).get('name')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
