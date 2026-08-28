"""Nebenläufige Arbeit WÄHREND der Anrufer noch spricht — das Tempo-Geheimnis.

Sobald der Sammler genug weiß, laufen hier im Hintergrund:
  1. Kartei-Suche (Name -> Patientenakte, Handy aus der Akte)
  2. Letzter Behandler ("weiß nicht mehr, bei wem ich war")
  3. Slot-Vorrat (freie Termine für Kalender/Grund/Zeitraum vorladen)

Wenn das Angebot dran ist, liegt die Antwort meist schon da — keine Totzeit.
Alles daemon-Threads, nichts blockiert den Mund-Pfad.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from bianca import arzt as arztmod
from bianca import gehirn
from kern import anruf_gedaechtnis, calendar, patients
from kern.patients import arzt_sprechname


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _laeuft(sit: dict, schluessel: str) -> bool:
    flags = sit.setdefault("hgLaeuft", {})
    if flags.get(schluessel):
        return True
    flags[schluessel] = True
    return False


def _frei(sit: dict, schluessel: str) -> None:
    sit.setdefault("hgLaeuft", {})[schluessel] = False


def _karte_binden(sit: dict, s: dict, pat: dict) -> bool:
    """Kartei-Treffer ins Gedächtnis: Name, Nummer, Geschlecht, ID."""
    if not _s(pat.get("id")):
        return False
    s["patientId"] = _s(pat.get("id"))
    s["bekannt"] = True
    s["aktePhone"] = _s(pat.get("phone"))
    if _s(pat.get("firstName")):
        s["vorname"] = _s(pat.get("firstName"))
    if _s(pat.get("lastName")):
        s["nachname"] = _s(pat.get("lastName"))
    s["buchstabiert"] = True
    if _s(pat.get("gender")):
        s["geschlecht"] = _s(pat.get("gender"))
    sit["patient"] = {**(sit.get("patient") or {}), **pat}
    anruf_gedaechtnis.anbinden(
        sit,
        phone=s.get("telefon") or s.get("aktePhone") or sit.get("anruferNummer") or "",
        patient_id=s["patientId"],
    )
    print(f"bianca-kartei: gefunden {pat.get('name')!r} id={pat.get('id')}", flush=True)
    return True


def karte_aus_handy(sit: dict) -> bool:
    """Sync: Nummer gegen die Kartei. Ein Treffer => Name merken und anreden."""
    s = gehirn.sammler(sit)
    handy = s.get("telefon") or sit.get("anruferNummer") or ""
    if not handy or s.get("patientId") or s.get("handyGeprueft"):
        return False
    s["handyGeprueft"] = True
    try:
        pat = patients.nach_handy(sit["tenant"], handy)
    except Exception as e:
        print(f"bianca-kartei handy fail {e}", flush=True)
        return False
    return _karte_binden(sit, s, pat)


def karte_aus_name(sit: dict) -> bool:
    """Sync: Nachname (+ Vorname) gegen die Kartei, wenn die Nummer nicht eindeutig war."""
    s = gehirn.sammler(sit)
    if s.get("patientId") or not s.get("nachname") or s.get("nameGeprueft"):
        return False
    s["nameGeprueft"] = True
    try:
        pat = patients.patient_aufloesen(sit["tenant"], {
            "name": f"{s['vorname']} {s['nachname']}".strip(),
            "firstName": s["vorname"],
            "lastName": s["nachname"],
        })
        if not _s(pat.get("id")):
            pat = patients.nach_name_phonetisch(sit["tenant"], s["vorname"], s["nachname"])
    except Exception as e:
        print(f"bianca-kartei name fail {e}", flush=True)
        return False
    return _karte_binden(sit, s, pat)


def kartei_anstossen(sit: dict) -> None:
    """Patient auflösen, sobald Nummer oder Nachname da ist — parallel."""
    s = gehirn.sammler(sit)
    handy = s.get("telefon") or sit.get("anruferNummer") or ""
    name_key = f"{s['vorname']}|{s['nachname']}".lower() if s["nachname"] else ""
    tel_key = f"tel|{patients.handy_kern(handy)}" if handy else ""
    # Nach einem Nummern-Fehltreffer trotzdem noch per Name suchen.
    if s["patientId"] and (s["aktePhone"] or not name_key):
        return
    if tel_key and s.get("handyGeprueft") and not name_key:
        return
    key = name_key or tel_key
    if not key or s["gesucht"] == key:
        return
    s["gesucht"] = key
    if _laeuft(sit, "kartei"):
        return

    def arbeit() -> None:
        try:
            tenant = sit["tenant"]
            pat: dict = {}
            if handy and not s.get("handyGeprueft"):
                pat = patients.nach_handy(tenant, handy)
                s["handyGeprueft"] = True
            if not _s(pat.get("id")) and s["nachname"] and not s.get("nameGeprueft"):
                s["nameGeprueft"] = True
                pat = patients.patient_aufloesen(tenant, {
                    "name": f"{s['vorname']} {s['nachname']}".strip(),
                    "firstName": s["vorname"],
                    "lastName": s["nachname"],
                })
                if not _s(pat.get("id")):
                    pat = patients.nach_name_phonetisch(tenant, s["vorname"], s["nachname"])
            if not _karte_binden(sit, s, pat):
                print(f"bianca-kartei: kein Treffer fuer {key!r}", flush=True)
            # "Weiß nicht mehr, bei wem ich war": jetzt können wir nachschlagen.
            if (s.get("arzt") or {}).get("typ") == "unbekannt" and s["patientId"]:
                if _s(s.get("phase")) in {"angebot", "bestaetigen", "gebucht"}:
                    # Zu spät: ein Angebot ist schon draußen. Den Suchrahmen
                    # jetzt umzustellen würde die Buchung in einen ANDEREN
                    # Kalender lenken als den, aus dem die Zeiten kamen
                    # (live passiert 27.08.2026: Patrikis-Slot in Petsas'
                    # Kalender gebucht -> "Termin ist gerade weg").
                    print("bianca-kartei: Angebot laeuft schon, Behandler-Wechsel unterlassen", flush=True)
                else:
                    info = arztmod.letzter_behandler(tenant, s["patientId"])
                    if info.get("ok") and info.get("calendarId"):
                        s["arzt"] = {
                            "typ": "letzter",
                            "calendarId": info["calendarId"],
                            "calendarName": info.get("calendarName") or "",
                        }
                        name = arzt_sprechname(info.get("doctorName") or info.get("calendarName") or "")
                        if name:
                            sit["arztHinweis"] = (
                                f"Ich sehe hier: Sie waren zuletzt bei {name} — "
                                "ich schaue direkt in dem Kalender."
                            )
                        print(f"bianca-kartei: letzter Behandler {name!r}", flush=True)
                    else:
                        # Keine Historie gefunden: global suchen statt raten.
                        s["arzt"] = {"typ": "egal"}
                        print("bianca-kartei: keine Behandler-Historie, suche global", flush=True)
            vorrat_anstossen(sit)
        except Exception as e:
            # Netz-Wackler: Suchmarke zurücknehmen, damit ein späterer Zug
            # denselben Namen noch einmal versuchen darf.
            if s.get("gesucht") == key and not s.get("patientId"):
                s["gesucht"] = ""
            print(f"bianca-kartei fail {e}", flush=True)
        finally:
            _frei(sit, "kartei")

    threading.Thread(target=arbeit, daemon=True).start()


def _vorrat_schluessel(sit: dict) -> str:
    s = gehirn.sammler(sit)
    a = s.get("arzt") or {}
    if a.get("calendarId"):
        scope = a["calendarId"]
    elif a.get("typ") in {"egal"} or s["warSchonMal"] is False:
        scope = "EGAL"
    else:
        return ""  # Kalender-Rahmen noch unklar — nicht ins Blaue suchen
    return f"{scope}|{s['motivId'] or 'std'}|{gehirn.start_datum(s)}"


def vorrat_anstossen(sit: dict) -> None:
    """Freie Termine vorladen, sobald der Suchrahmen steht oder sich ändert."""
    key = _vorrat_schluessel(sit)
    if not key or sit.get("vorratKey") == key:
        return
    sit["vorratKey"] = key
    if _laeuft(sit, "vorrat"):
        return

    def arbeit(mein_key: str) -> None:
        try:
            s = gehirn.sammler(sit)
            tenant = sit["tenant"]
            a = s.get("arzt") or {}
            egal = not a.get("calendarId")
            ctx = {
                "calendarId": a.get("calendarId") or "",
                "calendarName": a.get("calendarName") or "",
                "visitMotiveId": s["motivId"],
                "visitMotiveName": s["motivName"] or "Kontrolluntersuchung",
            }
            if egal:
                found = calendar.finde_schnellsten(
                    tenant, ctx,
                    start_date=gehirn.start_datum(s),
                    wish=s.get("wunsch") or {},
                    source="pickadoc-bianca",
                )
            else:
                found = calendar.find_slots(
                    tenant, ctx,
                    start_date=gehirn.start_datum(s),
                    egal=False,
                    source="pickadoc-bianca",
                )
            # Nur speichern, wenn der Rahmen noch stimmt — sonst würde eine
            # überholte Suche (alter Arzt/Tag) das frische Ziel überschreiben.
            if found.get("ok") and sit.get("vorratKey") == mein_key:
                isos = calendar._iso_liste(found.get("slots") or [])
                sit["slotVorrat"] = isos
                if egal and _s(found.get("doctorName")):
                    # Titel-Anhängsel ("…, M.Sc.") nicht mit ansagen.
                    sit["angebotArzt"] = _s(found.get("doctorName")).split(",")[0].strip()
                print(f"bianca-vorrat: {len(isos)} Slots fuer {mein_key}", flush=True)
            elif not found.get("ok"):
                print(f"bianca-vorrat fail: {found.get('error')}", flush=True)
        except Exception as e:
            print(f"bianca-vorrat fail {e}", flush=True)
        finally:
            _frei(sit, "vorrat")
            # Hat sich der Rahmen währenddessen geändert? Dann gleich nochmal.
            if _vorrat_schluessel(sit) != sit.get("vorratKey"):
                sit["vorratKey"] = ""
                vorrat_anstossen(sit)

    threading.Thread(target=arbeit, args=(key,), daemon=True).start()


def anstossen(sit: dict) -> None:
    kartei_anstossen(sit)
    vorrat_anstossen(sit)


def kartei_laeuft(sit: dict) -> bool:
    return bool(sit.setdefault("hgLaeuft", {}).get("kartei"))


def kartei_abwarten(sit: dict, max_s: float = 3.0) -> None:
    """Kurz auf die Behandler-Recherche warten, statt global zu raten.

    Chef-Vorgabe: Bei "weiß nicht mehr, bei wem ich war" wird der letzte
    Behandler recherchiert und in DESSEN Kalender gesucht. Der Füller
    überbrückt die Wartezeit — global suchen nur, wenn wirklich nichts kommt.
    """
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_s:
        s = gehirn.sammler(sit)
        a = s.get("arzt") or {}
        if a.get("calendarId") or a.get("typ") == "egal":
            return
        if not kartei_laeuft(sit):
            return
        time.sleep(0.1)
