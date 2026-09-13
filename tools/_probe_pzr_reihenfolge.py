"""Live-Probe (read-only): Behandler vor Zahnreinigung, Geschlecht im Schnappschuss.

Laeuft IM bianca-Container gegen den ausgelieferten Code. Es wird nichts
gebucht und nichts geschrieben: die Probe stellt nur Fragen und liest den
Buchungs-Schnappschuss.

    docker cp tools/_probe_pzr_reihenfolge.py telefonki-bianca-1:/app/tools/
    docker exec -w /app telefonki-bianca-1 python tools/_probe_pzr_reihenfolge.py
"""

from bianca import flow, gehirn
from kern.tenants import laden


def _sit() -> dict:
    return {"tenant": laden("meddent"),
            "messages": [{"role": "system", "content": "x"}]}


def main() -> int:
    fehler: list[str] = []
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "schonmal",
              "grund": "Kontrolluntersuchung",
              "motivId": "8QCwEyR3Jyao63PmJ7vo",
              "motivName": "KCH Kontrolluntersuchung"})
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda _sit: None
    try:
        z1 = flow.zug(sit, "Nein.")
        t1 = (z1 or {}).get("text", "")
        print("1) nach 'Nein.':", t1)
        if "Behandler" not in t1:
            fehler.append("Behandlerfrage fehlt nach 'noch nie da'")
        if "Zahnreinigung" in t1:
            fehler.append("Zahnreinigung ueberholt die Behandlerwahl")

        z2 = flow.zug(sit, "Zu Doktor Petsas.")
        t2 = (z2 or {}).get("text", "")
        print("2) nach Behandlerwahl:", t2)
        if "Zahnreinigung" not in t2:
            fehler.append("Zahnreinigung wird nach dem Behandler nicht angeboten")
    finally:
        flow.hintergrund.anstossen = echt

    # Geschlecht/Anrede: Vorname direkt gesetzt (ohne einsammeln).
    sit2 = _sit()
    s2 = gehirn.sammler(sit2)
    s2.update({"modus": "buchen", "warSchonMal": False, "arzt": {"typ": "egal"},
               "grund": "Kontrolluntersuchung", "wunsch": {},
               "vorname": "Peter", "nachname": "Berger",
               "buchstabiert": True, "telefon": "01776004600",
               "telefonOk": True})
    ctx = flow._ctx_bauen(sit2)
    print("3) Schnappschuss gender:", ctx.get("gender"), "| Anrede:",
          gehirn.anrede(s2))
    if ctx.get("gender") != "m":
        fehler.append("gender fehlt im Termin-Schnappschuss")
    stand = flow.status_zeile(sit2)
    print("4) Statuszeile:", stand)
    if "Anrede=Herr Berger" not in stand:
        fehler.append("Anrede fehlt in der Statuszeile")

    if fehler:
        print("pzr-probe: FEHLER")
        for f in fehler:
            print("  -", f)
        return 1
    print("pzr-probe: ALLES WIE GEWOLLT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
