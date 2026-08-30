"""Praxisgedächtnis (MAS-2 /brain): Gesprächs-Reports schreiben, Kontext lesen.

Chef 29.08.2026: "schreiben bianca und lisa reports in das MAS gedächtnis?
die müssen geschrieben werden als Gesprächszusammenfassung ähnlich wie in dem
terminpopup ... das muss sichergestellt sein ab jetzt und bianca muss prüfen
ob irgendetwas im kontext vorliegt während sie mit dem user spricht ... das
muss also im Hintergrund abgefragt werden."

Zwei Wege, beide Stimmen (Lisa und Bianca):

1. REPORT am Gesprächsende (hangup-Nacharbeit): EIN Event an
   POST {MAS_URL}/brain/events — Kanal bianca_call/lisa_call (im MAS-Schema
   vorgesehen), idempotente Id "telefonki:<kanal>:<sessionId>", Zusammenfassung
   im Terminpopup-Stil ("Laut Anruf (Bianca): ... Termin vereinbart am ...").
   Eine offene Rückruf-Notiz (praxisNotiz, W-SAMMELN) macht das Event "open"
   -> das MAS legt daraus einen Vorgang an und legt ihn der Praxis vor.

2. KONTEXT während des Gesprächs: sobald Telefonnummer oder Name feststehen,
   fragt ein Daemon-Thread GET /brain/caller-context?phone= (dafür gebaut,
   sprechfertiger deutscher Text) bzw. GET /brain/karteikarte?name= ab. Das
   Ergebnis landet in sit["gedaechtnis"] und von dort als eigener Block im
   System-Prompt — die Stimme weiß dann z. B. "die Praxis hat gestern
   versucht, Sie zu erreichen".

Nichts hier blockiert den Mund-Pfad: Reports laufen in der ohnehin
asynchronen hangup-Nacharbeit, der Kontext in eigenen Daemon-Threads.
Fehler werden geloggt und verschluckt — das Telefonat leidet nie.

Notaus: MAS_GEDAECHTNIS=0 (Umgebungsvariable) oder leere MAS_URL => kein
Netz, byte-identisches Verhalten wie vor W-GEDAECHTNIS.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Any

import httpx

from kern import notes
from kern.config import MAS_CLIENT_ID, MAS_TOKEN, MAS_URL

WARTE_S = 8.0
# Kontext-Abfragen laufen in Daemon-Threads NEBEN dem Gespraech — dort darf
# der Firestore-Scan der Karteikarte auch mal laenger brauchen (live 29.08.:
# ~8-12 s bei kaltem Cache). Bei Timeout wird die Marke zurueckgenommen und
# der naechste Zug versucht es erneut.
KONTEXT_WARTE_S = 15.0
_KARTEI_TAGE = 90
_MAX_ZEILEN = 3


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def enabled() -> bool:
    if not MAS_URL:
        return False
    return os.environ.get("MAS_GEDAECHTNIS", "").strip().lower() not in {"0", "false", "no", "off"}


def anzeige() -> str:
    return f"MAS {MAS_URL}" if enabled() else "aus"


def _client_id(sit: dict | None) -> str:
    """W-MANDANT: die Firebase-clientId des Sitzungs-Mandanten — Fallback
    bleibt die Prozess-Env (MAS_CLIENT_ID, byte-identisch fuer meddent)."""
    t = (sit or {}).get("tenant") or {}
    return _s(t.get("clientId")) or MAS_CLIENT_ID


def _headers(client_id: str = "") -> dict[str, str]:
    h = {"X-Client-Id": client_id or MAS_CLIENT_ID}
    if MAS_TOKEN:
        h["X-Service-Token"] = MAS_TOKEN
    return h


def _wer(sit: dict) -> tuple[str, str]:
    """(telefon, name) des Gesprächspartners — leer, wenn (noch) unbekannt."""
    s = sit.get("sammler") or {}
    pat = sit.get("patient") or {}
    book = sit.get("booking") or {}
    name = ""
    if _s(s.get("nachname")):
        name = f"{_s(s.get('vorname'))} {_s(s.get('nachname'))}".strip()
    if not name:
        name = _s(pat.get("name"))
    roh = _s(s.get("telefon")) or _s(s.get("aktePhone")) or _s(pat.get("phone")) or _s(book.get("phone"))
    telefon = "".join(c for c in roh if c.isdigit())
    if len(telefon) < 7:
        telefon = ""
    return telefon, name


def _wann_sprech(iso: str) -> str:
    """'2026-09-02T09:00' -> '02.09. um 09:00 Uhr' (Claras Sprech-Schicht
    macht daraus beim Vorlesen selbst eine relative Angabe)."""
    iso = _s(iso)
    if len(iso) < 10:
        return ""
    aus = f"{iso[8:10]}.{iso[5:7]}."
    if len(iso) >= 16:
        aus += f" um {iso[11:16]} Uhr"
    return aus


def _wann_zeile(ts: Any) -> str:
    try:
        d = datetime.fromtimestamp(float(ts) / 1000.0)
        return d.strftime("%d.%m.")
    except (TypeError, ValueError, OSError):
        return ""


def zusammenfassung(sit: dict) -> str:
    """Gesprächszusammenfassung im Terminpopup-Stil — attribuiert, EIN Absatz."""
    stimme = notes.stimme_von(sit)
    _, name = _wer(sit)
    teile: list[str] = []

    buch = sit.get("lastBook") or {}
    if buch.get("booked") or buch.get("dryRun"):
        t = "Termin vereinbart"
        wann = _wann_sprech(buch.get("slotIso"))
        if wann:
            t += f" am {wann}"
        s = sit.get("sammler") or {}
        arzt = _s((s.get("arzt") or {}).get("calendarName")) or _s(sit.get("angebotArzt"))
        if arzt:
            t += f" bei {arzt}"
        grund = notes.grund_kurz(sit)
        if grund:
            t += f" wegen {grund}"
        if buch.get("dryRun"):
            t += " (nur Test)"
        teile.append(t)
    storno = sit.get("lastCancel") or {}
    if storno.get("ok"):
        t = "bestehenden Termin abgesagt"
        wann = _wann_sprech(storno.get("slotIso"))
        if wann:
            t += f" ({wann})"
        if storno.get("dryRun"):
            t += " (nur Test)"
        teile.append(t)
    umzug = sit.get("lastMove") or {}
    if umzug.get("ok"):
        t = "Termin verschoben"
        wann = _wann_sprech(umzug.get("slotIso"))
        if wann:
            t += f" auf {wann}"
        if umzug.get("dryRun"):
            t += " (nur Test)"
        teile.append(t)
    if (sit.get("lastCreate") or {}).get("ok"):
        teile.append("neue Patientenakte angelegt")
    if _s(sit.get("praxisNotiz")):
        teile.append(f"Rückruf-Notiz an die Praxis: {_s(sit.get('praxisNotiz'))}")

    if not teile:
        s = sit.get("sammler") or {}
        grund = notes.grund_kurz(sit) or _s(s.get("grund"))
        if grund:
            teile.append(f"Anliegen: {grund} — nichts gebucht oder geändert")
        elif _s(sit.get("auftrag")) and stimme.lower() == "lisa":
            teile.append(f"Auftrag: {_s(sit.get('auftrag'))[:140]}")
        else:
            teile.append("Gespräch ohne Kalenderänderung")

    kopf = f"Laut Anruf ({stimme}): "
    if name:
        kopf += f"{name} — "
    text = kopf + "; ".join(teile) + "."
    for zeile in notes.besondere_zeilen(sit):
        text += f" {zeile}."
    return text[:600]


def _event(sit: dict) -> dict:
    stimme = notes.stimme_von(sit)
    kanal = "bianca_call" if stimme.lower() == "bianca" else "lisa_call"
    telefon, name = _wer(sit)
    s = sit.get("sammler") or {}
    pat = sit.get("patient") or {}
    patient_id = _s(s.get("patientId")) or _s(pat.get("id"))
    offen = bool(_s(sit.get("praxisNotiz")))

    signals: dict[str, Any] = {}
    if (sit.get("lastBook") or sit.get("lastCancel") or sit.get("lastMove")
            or _s(s.get("modus")) in {"buchen", "absagen", "verschieben"}):
        signals["appointmentRequest"] = True
    if offen:
        signals["callbackRequested"] = True

    ts = None
    try:
        roh = _s(sit.get("startedAt"))
        if roh:
            ts = int(datetime.fromisoformat(roh).timestamp() * 1000)
    except ValueError:
        ts = None

    ev: dict[str, Any] = {
        "id": f"telefonki:{kanal}:{_s(sit.get('id'))}",
        "channel": kanal,
        # Bianca nimmt eingehende Anrufe an, Lisa ruft hinaus.
        "direction": "in" if kanal == "bianca_call" else "out",
        "type": "interaction",
        "counterparty": {"kind": "patient", "name": name, "ref": telefon or None},
        "subject": {
            "patientId": patient_id or None,
            "name": name,
            "matchStatus": "matched" if patient_id else "unmatched",
            "matchMethod": "name" if patient_id else None,
        },
        "summary": zusammenfassung(sit),
        "signals": signals,
        # Offene Rückruf-Notiz => open (MAS macht einen Vorgang daraus und
        # legt ihn vor); alles andere ist erledigt => none, kein Ticket.
        "status": "open" if offen else "none",
        "confidence": 0.95,
        "payloadRef": {"kind": "telefonki_session", "id": _s(sit.get("id"))},
        "extractor": "telefonki@v1",
    }
    if ts:
        ev["ts"] = ts
    return ev


def report_senden(sit: dict) -> dict | None:
    """Gesprächs-Report ins Praxisgedächtnis — aus der hangup-Nacharbeit.

    Läuft dort schon in einem Daemon-Thread; hier wird also blockierend
    gepostet (Timeout), nie geworfen. Idempotent über die Event-Id — ein
    zweites Auflegen derselben Sitzung erzeugt kein zweites Event."""
    if not enabled():
        return None
    name = notes.stimme_von(sit).lower()
    if not notes.nutzer_saetze(sit) and not (sit.get("tools") or []):
        # Nur Begrüßung, kein Wort vom Anrufer: kein Report wert.
        print(f"{name}-gedaechtnis: leeres Gespraech, kein Report", flush=True)
        return None
    try:
        body = _event(sit)
        r = httpx.post(f"{MAS_URL}/brain/events", json=body,
                       headers=_headers(_client_id(sit)), timeout=WARTE_S)
        d = r.json() if r.status_code in (200, 201) else {}
        sit["gedaechtnisReport"] = {"ok": bool(d.get("ok")), "created": bool(d.get("created")),
                                    "id": body["id"], "status": r.status_code}
        print(f"{name}-gedaechtnis report {body['id']} -> {r.status_code} "
              f"created={d.get('created')}", flush=True)
        return sit["gedaechtnisReport"]
    except Exception as e:
        print(f"{name}-gedaechtnis report fail {e}", flush=True)
        return None


def _kontext_holen(telefon: str, name: str, client_id: str = "") -> str:
    """Synchroner Abruf: erst der Rufnummern-Endpunkt (sprechfertig),
    hilfsweise die Gedächtnis-Suche nach der Nummer und die Karteikarte
    nach Name (Events selbst zu Zeilen gefaltet)."""
    if telefon:
        r = httpx.get(f"{MAS_URL}/brain/caller-context",
                      params={"phone": telefon}, headers=_headers(client_id),
                      timeout=KONTEXT_WARTE_S)
        d = r.json()
        if d.get("found") and _s(d.get("context")):
            return str(d.get("context")).strip()
        # caller-context liest intern queryRecent (aufsteigend, Limit): bei
        # vielen Events im 14-Tage-Fenster fallen genau die NEUESTEN raus
        # (live 29.08.2026: frisches Event unauffindbar). Die Suche laeuft
        # ueber queryLatest (neueste zuerst) und traegt counterparty.ref im
        # Suchtext — der robuste Rueckweg fuer die Rufnummer.
        text = _suche_nach_nummer(telefon, client_id)
        if text:
            return text
    if name:
        r = httpx.get(f"{MAS_URL}/brain/karteikarte",
                      params={"name": name, "sinceDays": _KARTEI_TAGE},
                      headers=_headers(client_id), timeout=KONTEXT_WARTE_S)
        d = r.json()
        events = sorted(d.get("events") or [], key=lambda e: e.get("ts") or 0, reverse=True)
        zeilen: list[str] = []
        for e in events:
            summ = _s(e.get("summary"))
            if not summ:
                continue
            wann = _wann_zeile(e.get("ts"))
            offen = " (noch offen)" if e.get("status") == "open" else ""
            zeilen.append(f"- {wann + ': ' if wann else ''}{summ}{offen}")
            if len(zeilen) >= _MAX_ZEILEN:
                break
        if zeilen:
            return (f"Praxisgedächtnis zu {name}:\n" + "\n".join(zeilen)
                    + "\nNutze das aktiv: erkenne den Zusammenhang an, statt bei Null anzufangen.")
    return ""


def _suche_nach_nummer(telefon: str, client_id: str = "") -> str:
    """GET /brain/search?q=<ziffern>&kind=event — Zeilen im caller-context-Stil."""
    r = httpx.get(f"{MAS_URL}/brain/search",
                  params={"q": telefon, "kind": "event", "sinceDays": 14, "limit": 10},
                  headers=_headers(client_id), timeout=KONTEXT_WARTE_S)
    d = r.json()
    hits = sorted((d.get("results") or []), key=lambda h: h.get("ts") or 0, reverse=True)
    zeilen: list[str] = []
    wer = ""
    for h in hits:
        if h.get("kind") != "event":
            continue
        summ = _s(h.get("snippet"))
        if not summ:
            continue
        wann = _wann_zeile(h.get("ts"))
        offen = " (noch offen)" if h.get("status") == "open" else ""
        zeilen.append(f"- {wann + ': ' if wann else ''}{summ}{offen}")
        if not wer:
            kandidat = _s(h.get("counterpartyName")) or _s(h.get("subjectName"))
            if kandidat and not kandidat[:1].isdigit():
                wer = kandidat
        if len(zeilen) >= _MAX_ZEILEN:
            break
    if not zeilen:
        return ""
    return (f"Praxisgedächtnis zu dieser Rufnummer{f' (vermutlich {wer})' if wer else ''}:\n"
            + "\n".join(zeilen)
            + "\nNutze das aktiv: erkenne den Zusammenhang an, statt bei Null anzufangen.")


def _kontext_arbeit(sit: dict, telefon: str, name: str, key: str) -> None:
    stimme = notes.stimme_von(sit).lower()
    try:
        text = _kontext_holen(telefon, name, _client_id(sit))
        if sit.get("gedaechtnisKey") != key:
            return  # inzwischen ist mehr bekannt — der neuere Lauf gewinnt
        sit["gedaechtnis"] = text
        wer = name or telefon
        if text:
            print(f"{stimme}-gedaechtnis kontext zu {wer!r}: {len(text)} Zeichen", flush=True)
        else:
            print(f"{stimme}-gedaechtnis kontext zu {wer!r}: nichts", flush=True)
    except Exception as e:
        # Netz-Wackler: Marke zurücknehmen, ein späterer Zug darf es neu versuchen.
        if sit.get("gedaechtnisKey") == key:
            sit["gedaechtnisKey"] = ""
        print(f"{stimme}-gedaechtnis kontext fail {e}", flush=True)


def kontext_anstossen(sit: dict) -> None:
    """Hintergrund-Abfrage starten, sobald Telefon oder Name feststehen.

    Key-gesichert: pro (Telefon|Name)-Stand läuft genau EIN Abruf; ändert
    sich der Stand (Name kommt dazu, Nummer bestätigt), läuft er erneut."""
    if not enabled():
        return
    telefon, name = _wer(sit)
    if not telefon and not name:
        return
    key = f"{telefon}|{name}".lower()
    if sit.get("gedaechtnisKey") == key:
        return
    sit["gedaechtnisKey"] = key
    threading.Thread(target=_kontext_arbeit, args=(sit, telefon, name, key), daemon=True).start()


def kontext_block(sit: dict) -> str:
    """Prompt-Block für beide Stimmen — leer, wenn nichts vorliegt."""
    text = _s_mehrzeilig(sit.get("gedaechtnis"))
    if not text:
        return ""
    return f"\nPRAXISGEDÄCHTNIS (frühere Kontakte)\n{text}\n"


def _s_mehrzeilig(v: Any) -> str:
    return str(v or "").strip()
