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
from kern import calendar, gedaechtnis, motive, patients
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


def kartei_anstossen(sit: dict) -> None:
    """Patient auflösen, sobald ein Nachname da ist — parallel zum Gespräch."""
    s = gehirn.sammler(sit)
    key = f"{s['vorname']}|{s['nachname']}".lower()
    # patientId allein reicht nicht: kommt sie aus agentFindPatientAppointments
    # (Termin-Verwaltung), fehlt noch das Akten-Handy fuer eine Folge-Buchung.
    if not s["nachname"] or s["gesucht"] == key or (s["patientId"] and s["aktePhone"]):
        return
    s["gesucht"] = key
    if _laeuft(sit, "kartei"):
        return

    def arbeit() -> None:
        try:
            tenant = sit["tenant"]
            pat = patients.patient_aufloesen(tenant, {
                "name": f"{s['vorname']} {s['nachname']}".strip(),
                "firstName": s["vorname"],
                "lastName": s["nachname"],
            })
            if _s(pat.get("id")):
                s["patientId"] = _s(pat.get("id"))
                s["bekannt"] = True
                s["aktePhone"] = _s(pat.get("phone"))
                if not s["vorname"]:
                    s["vorname"] = _s(pat.get("firstName"))
                # Kartei-Geschlecht schlaegt die Vornamen-Schaetzung (29.08.2026).
                if _s(pat.get("gender")):
                    s["geschlecht"] = _s(pat.get("gender")).lower()
                    s["geschlechtQuelle"] = "akte"
                    s["geschlechtUnklar"] = False
                # Versichertenstatus aus der Akte — Grundlage fuer die
                # Bestands-Rueckfrage (nur privat<->gesetzlich zaehlt).
                if isinstance(pat.get("privateInsurance"), bool):
                    s["versicherungAkte"] = "privat" if pat["privateInsurance"] else "gesetzlich"
                sit["patient"] = {**(sit.get("patient") or {}), **pat}
                print(f"bianca-kartei: gefunden {pat.get('name')!r} id={pat.get('id')}", flush=True)
            else:
                print(f"bianca-kartei: kein Treffer fuer {key!r}", flush=True)
            # Letzter Besuch (fuer die Versicherungs-Rueckfrage nach >6
            # Monaten) — ein Abruf, den auch der Behandler-Zweig unten nutzt.
            besuch_info: dict[str, Any] = {}
            if s["patientId"] and not s["letzterBesuch"]:
                besuch_info = arztmod.letzter_behandler(tenant, s["patientId"])
                if besuch_info.get("ok") and besuch_info.get("war") and _s(besuch_info.get("lastIso")):
                    s["letzterBesuch"] = _s(besuch_info["lastIso"])
                    # Grund des letzten Besuchs — Stoff fuer die Rueckblick-
                    # Ansprache ("letztes Mal waren Sie wegen … da", 30.08.2026).
                    s["letzterGrund"] = _s(besuch_info.get("grund"))
                    print(f"bianca-kartei: letzter Besuch {s['letzterBesuch'][:10]} "
                          f"({s['letzterGrund'] or 'ohne Grund'})", flush=True)
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
                    info = besuch_info if besuch_info else arztmod.letzter_behandler(tenant, s["patientId"])
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
            found = calendar.find_slots(
                tenant, ctx,
                start_date=gehirn.start_datum(s),
                egal=egal,
                source="pickadoc-bianca",
            )
            # Nur speichern, wenn der Rahmen noch stimmt — sonst würde eine
            # überholte Suche (alter Arzt/Tag) das frische Ziel überschreiben.
            if found.get("ok") and sit.get("vorratKey") == mein_key:
                isos = calendar._iso_liste(found.get("slots") or [])
                sit["slotVorrat"] = isos
                # Dispatch fuer den Angebots-Zug merken — _angebot zeigt die
                # CF-Karte dann in der Unterhaltung (W-VORRAT-UI 02.09.2026),
                # auch wenn kein zweiter getFreeTimeSlots noetig ist.
                disp = found.get("dispatch")
                sit["vorratDispatch"] = disp if isinstance(disp, dict) else None
                sit["vorratGemerkt"] = False
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
    # Besuchsgrund-Katalog EINMAL pro Anruf frisch von der Plattform holen
    # (behandlerspezifisches Mapping, Chef 30.08.2026) — laeuft parallel.
    motive.anstossen(sit)
    kartei_anstossen(sit)
    vorrat_anstossen(sit)
    # W-GEDAECHTNIS: sobald Name/Telefon feststehen, im Praxisgedaechtnis
    # (MAS) nachsehen, ob etwas zu diesem Anrufer vorliegt — parallel.
    gedaechtnis.kontext_anstossen(sit)


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
