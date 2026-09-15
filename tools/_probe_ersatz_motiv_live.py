"""W-ERSATZ-MOTIV live gegenpruefen — read-only, kein Kalender-Write.

Laeuft im Container:
    docker exec -w /app telefonki-bianca-1 python tools/_probe_ersatz_motiv_live.py

Teil A: welches Motiv springt je Mandant als Kontroll-Ausweich ein?
        Ruether darf KEINEN bekommen, die drei anderen ihren wie bisher.
Teil B: Ruether-Wunsch "Krebsvorsorge" durch die echte Slotsuche — kommt der
        Marker, und hoert der Anrufer den echten Grund statt "kein Termin frei"?
Teil C: Gegenprobe MedDent — leeres Fenster faellt weiter auf Kontrolle.

Die Rueckruf-Notiz von Teil B landet in /tmp, nicht in der echten Schlange.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

from bianca import besuchsgrund, flow, gehirn, verwalten  # noqa: E402
from bianca import session as bsession  # noqa: E402
from kern import agentprofil, calendar as kal, motive, tenants  # noqa: E402

DIDS = {
    "meddent": "+4921154244101",
    "thaler": "+4921154244105",
    "blessing": "+4921154244120",
    "ruether": "+4921154244160",
}
FEHLER: list[str] = []


def _pruef(bedingung: bool, text: str) -> None:
    print(f"{'OK   ' if bedingung else 'FEHLER'} {text}")
    if not bedingung:
        FEHLER.append(text)


def teil_a() -> None:
    print("\n--- A: Kontroll-Ausweich je Mandant " + "-" * 40)
    for name, did in DIDS.items():
        t = agentprofil.fuer_did(did) or {}
        vm = tenants.motiv_von(t, "Kontrolluntersuchung") or {}
        taugt = tenants.taugt_als_ersatz(vm)
        alt = kal._kontrolle_ersatz(
            t, {"calendarId": "x", "visitMotiveId": "gibt-es-nicht",
                "visitMotiveName": "Irgendwas"})
        gewaehlt = (alt or {}).get("visitMotiveName") or "KEINER"
        print(f"  {name:9} motiv_von='{vm.get('name') or '—'}'  "
              f"taugt={'ja' if taugt else 'nein'}  ausweich='{gewaehlt}'")
        if name == "ruether":
            _pruef(alt is None, "ruether bekommt keinen Ausweich")
        else:
            _pruef(bool(alt) and taugt, f"{name} behaelt echten Kontroll-Ausweich")


def _ruether_sit(t: dict) -> tuple[dict, dict]:
    kat = motive._telefon_katalog(motive.holen(t) or [])
    sit = bsession.neu(tenant=t)
    sit["motivKatalog"] = kat
    sit["anrufer"] = {"vorname": "Probe", "nachname": "Lesen",
                      "telefon": "+491771234567"}
    cal = (t.get("calendars") or [{}])[0]
    tr = besuchsgrund.katalog_treffer("Krebsvorsorge", katalog=kat) or {}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True,
              "arzt": {"typ": "genannt", "calendarId": cal.get("id"),
                       "calendarName": cal.get("name")},
              "grund": "Krebsvorsorge", "grundWortlaut": "Krebsvorsorge",
              "motivId": tr.get("id") or "", "motivName": tr.get("name") or "",
              "vorname": "Probe", "nachname": "Lesen", "buchstabiert": True,
              "versicherung": "gesetzlich", "phase": "angebot",
              "wunsch": {"weekday": None, "hourMin": None, "hourMax": None,
                         "hour": None, "minDaysAhead": 0, "date": None,
                         "tage": None, "von": None, "bis": None}})
    print(f"  Wunsch 'Krebsvorsorge' -> Motiv '{tr.get('name') or '—'}' "
          f"(buchbar={tr.get('allowOnlineBooking')})")
    return sit, dict(cal)


def teil_b(tmp: Path) -> None:
    print("\n--- B: Ruether, Wunsch Krebsvorsorge " + "-" * 38)
    t = agentprofil.fuer_did(DIDS["ruether"]) or {}
    sit, cal = _ruether_sit(t)
    s = gehirn.sammler(sit)
    # Buchbarkeit kommt aus dem frischen Sitzungs-Katalog — genau so, wie
    # flow._ctx_bauen sie mitgibt (tenant["visitMotives"] fuehrt bei Ruether
    # nur einen Ausschnitt und kennt die Krebsvorsorge gar nicht).
    such = {"calendarId": cal.get("id"), "calendarName": cal.get("name"),
            "visitMotiveId": s["motivId"], "visitMotiveName": s["motivName"]}
    kat_vm = next((m for m in (sit.get("motivKatalog") or [])
                   if (m.get("id") or "") == s["motivId"]), {})
    if kat_vm.get("allowOnlineBooking") is False:
        such["visitMotiveOnline"] = False
    found = kal.find_slots_behandler(t, such, source="probe-ersatz")
    slots = kal._iso_liste(found.get("slots") or [])
    print(f"  Slotsuche: {len(slots)} Zeiten  fallback={found.get('motivFallback') or '—'}"
          f"  marker='{found.get('motivNichtTelefonisch') or '—'}'")
    _pruef(not found.get("motivFallback"),
           "kein Endometriose-Ausweich in der Slotsuche")
    _pruef(bool(found.get("motivNichtTelefonisch")),
           "Slotsuche markiert 'telefonisch nicht vergeben'")

    verwalten.DATA_DIR = tmp
    ang = flow._angebot(sit) or {}
    text = ang.get("text") or ""
    print(f"  Ansage: {text}")
    _pruef("telefonisch nicht vergeben" in text,
           "Anrufer hoert den echten Grund")
    _pruef("keinen freien Termin" not in text,
           "nicht mehr 'kein freier Termin'")
    _pruef("Krebs" not in text and "GYN" not in text,
           "kein Kuerzel, kein Krebs im Mund")
    _pruef("Endometriose" not in text, "nie Endometriose-Zeiten angeboten")
    _pruef(not sit.get("offered"), "kein Slot im Angebot")
    notiz = tmp / "praxis_notizen.jsonl"
    _pruef(notiz.exists() and "Krebsvorsorge" in notiz.read_text(encoding="utf-8"),
           "Rueckruf-Notiz traegt den Wunsch")


def teil_c() -> None:
    print("\n--- C: Gegenprobe MedDent " + "-" * 49)
    t = agentprofil.fuer_did(DIDS["meddent"]) or {}
    kat = motive._telefon_katalog(motive.holen(t) or [])
    gesperrt = next((m for m in kat if m.get("allowOnlineBooking") is False), None)
    if not gesperrt:
        print("  (kein gesperrtes Motiv im Katalog — nichts zu pruefen)")
        return
    cal = (t.get("calendars") or [{}])[0]
    found = kal.find_slots_behandler(
        t, {"calendarId": cal.get("id"), "calendarName": cal.get("name"),
            "visitMotiveId": gesperrt.get("id"),
            "visitMotiveName": gesperrt.get("name")},
        source="probe-ersatz")
    slots = kal._iso_liste(found.get("slots") or [])
    print(f"  '{gesperrt.get('name')}' -> {len(slots)} Zeiten  "
          f"fallback={found.get('motivFallback') or '—'}  "
          f"marker='{found.get('motivNichtTelefonisch') or '—'}'")
    _pruef(bool(slots) or bool(found.get("motivFallback")),
           "MedDent faellt weiter auf Kontrolle zurueck")


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        teil_a()
        teil_b(Path(d))
        teil_c()
    print()
    if FEHLER:
        for f in FEHLER:
            print(f"  offen: {f}")
        return 1
    print("probe-ersatz-motiv: ALLE WACHEN GRUEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
