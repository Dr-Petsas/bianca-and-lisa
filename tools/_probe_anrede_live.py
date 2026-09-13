"""W-ANREDE Live-Probe: greift die Wache im laufenden Container?

Read-only: kein Anruf, kein Kalender, kein Schreiben. Laedt den ECHTEN
Mandanten (tenants/meddent.json bzw. DB-Basis) und schickt Saetze durch
`bianca.agent._anrede_wache_anwenden`.

    docker cp tools/_probe_anrede_live.py telefonki-bianca-1:/app/tools/
    docker exec -w /app telefonki-bianca-1 python tools/_probe_anrede_live.py
"""

from __future__ import annotations

from bianca import agent as bianca_agent
from kern import anrede_wache, tenants

TENANT = tenants.laden("meddent")

FAELLE = [
    # (Beschreibung, Sitzung, Satz, soll die Anrede fallen?)
    ("unbekannter Anrufer", {}, "Gerne, Herr Meier. Ich buche Ihnen einen Termin zur Kontrolle.", True),
    ("unbekannter Anrufer", {}, "Frau Schneider, das habe ich notiert.", True),
    ("Anrufer hat sich vorgestellt", {"nachname": "Meier", "geschlecht": "m"},
     "Gerne, Herr Meier. Ich buche Ihnen einen Termin zur Kontrolle.", False),
    ("Behandler des Mandanten", {}, "Herrn Doktor Petsas verbinde ich gern.", False),
    ("Titel ohne Namen", {}, "Einen Moment, Herr Doktor.", False),
]


def main() -> None:
    print(f"modus={anrede_wache.modus()}  tenant={TENANT.get('mandantId') or 'meddent'}")
    fehler = 0
    for was, sammler, satz, soll_fallen in FAELLE:
        sit = {"tenant": TENANT, "sammler": dict(sammler)}
        raus = bianca_agent._anrede_wache_anwenden(sit, satz)
        gefallen = raus != satz
        ok = gefallen == soll_fallen
        fehler += 0 if ok else 1
        print(f"{'OK  ' if ok else 'FEHL'} [{was}]")
        print(f"      vorher : {satz}")
        print(f"      nachher: {raus}")
    print("anrede-probe:", "ALLES WIE GEWOLLT" if not fehler else f"{fehler} FEHLER")


if __name__ == "__main__":
    main()
