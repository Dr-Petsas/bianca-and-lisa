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
import re
import threading
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

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
    a = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
    name = ""
    if _s(s.get("nachname")):
        name = f"{_s(s.get('vorname'))} {_s(s.get('nachname'))}".strip()
    if not name:
        name = _s(pat.get("name"))
    if not name:
        name = f"{_s(a.get('vorname'))} {_s(a.get('nachname'))}".strip()
    roh = (_s(s.get("telefon")) or _s(s.get("aktePhone")) or _s(pat.get("phone"))
           or _s(book.get("phone")) or _s(a.get("telefon"))
           or _s(sit.get("callerPhone")))
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


# Vorheriges TELEFON-Gespraech (Chef 08.09.2026): bekannt = wir haben schon
# miteinander gesprochen. Bestandskunde in der Kartei ist etwas anderes —
# ein Erstgespraech bleibt "Ich bin die Neue", auch wenn die Nummer matcht.
_ANRUF_KANAL = frozenset({"bianca_call", "lisa_call", "lisa_outbound"})
_WOCHENTAG = (
    "Montag", "Dienstag", "Mittwoch", "Donnerstag",
    "Freitag", "Samstag", "Sonntag",
)


def anruf_wann_sprechbar(ts: Any, jetzt: datetime | None = None) -> str:
    """Relatives Wann fuer 'Sie hatten … schon einmal angerufen'."""
    try:
        ms = float(ts or 0)
    except (TypeError, ValueError):
        return "neulich"
    if ms <= 0:
        return "neulich"
    if ms < 1e12:
        ms *= 1000.0
    tz = ZoneInfo("Europe/Berlin")
    dann = datetime.fromtimestamp(ms / 1000.0, tz)
    nun = jetzt or datetime.now(tz)
    if nun.tzinfo is None:
        nun = nun.replace(tzinfo=tz)
    delta = (nun.date() - dann.date()).days
    if delta <= 0:
        return "heute"
    if delta == 1:
        return "gestern"
    if delta == 2:
        return "vorgestern"
    if delta <= 6:
        return f"am {_WOCHENTAG[dann.weekday()]}"
    if delta < 14:
        return "letzte Woche"
    return "neulich"


def _letzter_anruf_aus_hits(hits: list, *, nicht_id: str = "") -> dict:
    """Neuester Telefon-Kontakt aus einer Brain-Suche — erledigte zaehlen."""
    best: dict[str, Any] | None = None
    skip = _s(nicht_id).lower()
    for h in hits or []:
        if not isinstance(h, dict):
            continue
        kanal = _s(h.get("channel")).lower()
        if kanal and kanal not in _ANRUF_KANAL:
            continue
        eid = _s(h.get("id"))
        if skip and skip in eid.lower():
            continue
        try:
            ts = float(h.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        if ts < 1e12:
            ts *= 1000.0
        if best is None or ts > float(best["ts"]):
            best = {"ts": ts, "kanal": kanal, "id": eid}
    if not best:
        return {}
    best["wann"] = anruf_wann_sprechbar(best["ts"])
    return best


def letzter_anruf_holen(telefon: str, client_id: str = "", *, nicht_id: str = "") -> dict:
    """MAS-Suche: gab es zu dieser Nummer schon ein Telefongespraech?"""
    ziffern = "".join(c for c in _s(telefon) if c.isdigit())
    if not enabled() or len(ziffern) < 7:
        return {}
    try:
        r = httpx.get(
            f"{MAS_URL}/brain/search",
            params={"q": ziffern, "kind": "event", "sinceDays": 90, "limit": 20},
            headers=_headers(client_id), timeout=KONTEXT_WARTE_S,
        )
        return _letzter_anruf_aus_hits(r.json().get("results") or [], nicht_id=nicht_id)
    except Exception:
        return {}


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


def outbound_offen_legen(bundle: dict) -> None:
    """Beim Lisa-Wählversuch sofort eine offene Notiz legen — bevor jemand rangeht.

    Sonst weiß Bianca nichts, wenn der Patient während des Klingelns oder
    nach einem Nicht-Erreichen zurückruft (Hangup-Report kommt dann nie)."""
    if not enabled():
        return
    p = bundle.get("patient") if isinstance(bundle.get("patient"), dict) else {}
    vor = _s(p.get("firstName") or p.get("first_name"))
    nach = _s(p.get("lastName") or p.get("last_name"))
    name = _s(p.get("name") or p.get("fullName") or f"{vor} {nach}")
    roh = (_s(p.get("phone") or p.get("mobilePhoneNumber") or p.get("phoneNumber"))
           or _s(bundle.get("toE164") or bundle.get("to")))
    telefon = "".join(c for c in roh if c.isdigit())
    if len(telefon) < 7:
        telefon = ""
    auftrag = _s(bundle.get("auftrag") or bundle.get("prompt") or bundle.get("task_prompt"))
    grund = auftrag[:180] if auftrag else "Rückruf der Praxis"
    pcid = _s(bundle.get("phoneCallId") or bundle.get("uuid"))
    if not pcid:
        return
    body = {
        "id": f"telefonki:lisa_outbound:{pcid}",
        "channel": "lisa_call",
        "direction": "out",
        "type": "note",
        "counterparty": {"kind": "patient", "name": name, "ref": telefon or None},
        "subject": {
            "patientId": _s(p.get("id") or p.get("patientId")) or None,
            "name": name,
            "matchStatus": "matched" if _s(p.get("id") or p.get("patientId")) else "unmatched",
            "matchMethod": "name" if _s(p.get("id") or p.get("patientId")) else None,
        },
        "summary": f"Lisa hat {name or 'den Patienten'} angerufen: {grund}.",
        "signals": {"callbackRequested": True},
        "status": "open",
        "confidence": 0.95,
        "payloadRef": {"kind": "telefonki_outbound", "id": pcid},
        "extractor": "telefonki@v1",
    }
    cid = _s(bundle.get("clientId") or (bundle.get("agent") or {}).get("clientId"))

    def arbeit() -> None:
        try:
            r = httpx.post(f"{MAS_URL}/brain/events", json=body,
                           headers=_headers(cid), timeout=WARTE_S)
            print(f"lisa-gedaechtnis outbound {body['id']} -> {r.status_code}",
                  flush=True)
        except Exception as e:
            print(f"lisa-gedaechtnis outbound fail {e}", flush=True)

    threading.Thread(target=arbeit, daemon=True).start()


def _offen_ids(roh: Any) -> list[str]:
    out: list[str] = []
    for x in roh or []:
        s = _s(x)
        if s and s not in out:
            out.append(s)
    return out


# Empfangs-/Lisa-Themenotiz (Herbst 08.09.2026): die Praxis schreibt
# "schlaf schiene ist schon abholbreit" als frontdesk/note mit status=none.
# caller-context zeigt nur status=open — ohne diesen Filter sieht Bianca
# den Rückrufgrund nicht, obwohl die Notiz Minuten vor dem Rückruf da war.
_THEMA_RE = re.compile(
    r"abhol|schien|narval|schnarch|nicht erreicht|"
    r"zur(ü|ue)ckruf|anrufen|angerufen|bitte.{0,16}ruf",
    re.I,
)
_THEMA_KANAL = {"frontdesk", "lisa_call", "lisa_outbound", "lisa_sms"}
_THEMA_TAGE_MS = 14 * 24 * 60 * 60 * 1000


def _event_ist_themenotiz(e: dict) -> bool:
    """Offen ODER frische Empfangs-/Lisa-Notiz mit Rückruf-Thema."""
    if not isinstance(e, dict):
        return False
    st = _s(e.get("status")).lower()
    if st in {"resolved", "done", "closed", "erledigt"}:
        return False
    if st == "open":
        return True
    if st not in {"", "none"}:
        return False
    kanal = _s(e.get("channel")).lower()
    summ = _s(e.get("summary") or e.get("snippet"))
    if not summ or not _THEMA_RE.search(summ):
        return False
    if kanal and kanal not in _THEMA_KANAL:
        return False
    try:
        ts = float(e.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    if ts <= 0:
        return False
    if ts < 1e12:
        ts *= 1000.0
    age = time.time() * 1000.0 - ts
    return 0 <= age <= _THEMA_TAGE_MS


def _kontext_stand(telefon: str, name: str, client_id: str = "") -> tuple[str, list[str]]:
    """Text + offene Event-Ids. Erledigte Einträge kommen nicht in den Mund."""
    if telefon:
        r = httpx.get(f"{MAS_URL}/brain/caller-context",
                      params={"phone": telefon}, headers=_headers(client_id),
                      timeout=KONTEXT_WARTE_S)
        d = r.json()
        ids = _offen_ids(d.get("openEventIds"))
        if d.get("found") and _s(d.get("context")):
            return str(d.get("context")).strip(), ids
        # caller-context liest intern queryRecent (aufsteigend, Limit): bei
        # vielen Events im 14-Tage-Fenster fallen genau die NEUESTEN raus
        # (live 29.08.2026: frisches Event unauffindbar). Die Suche laeuft
        # ueber queryLatest (neueste zuerst) und traegt counterparty.ref im
        # Suchtext — der robuste Rueckweg fuer die Rufnummer.
        text, suche_ids = _suche_nach_nummer(telefon, client_id)
        if text:
            return text, suche_ids
    if name:
        r = httpx.get(f"{MAS_URL}/brain/karteikarte",
                      params={"name": name, "sinceDays": _KARTEI_TAGE},
                      headers=_headers(client_id), timeout=KONTEXT_WARTE_S)
        d = r.json()
        events = sorted(d.get("events") or [], key=lambda e: e.get("ts") or 0, reverse=True)
        zeilen: list[str] = []
        ids: list[str] = []
        for e in events:
            if not _event_ist_themenotiz(e):
                continue
            summ = _s(e.get("summary"))
            if not summ:
                continue
            wann = _wann_zeile(e.get("ts"))
            zeilen.append(f"- {wann + ': ' if wann else ''}{summ} (noch offen)")
            eid = _s(e.get("id"))
            if eid:
                ids.append(eid)
            if len(zeilen) >= _MAX_ZEILEN:
                break
        if zeilen:
            return (f"Praxisgedächtnis zu {name}:\n" + "\n".join(zeilen)
                    + "\nNutze das aktiv: erkenne den Zusammenhang an, statt bei Null anzufangen."), ids
    return "", []


def _kontext_holen(telefon: str, name: str, client_id: str = "") -> str:
    """Synchroner Abruf: erst der Rufnummern-Endpunkt (sprechfertig),
    hilfsweise die Gedächtnis-Suche nach der Nummer und die Karteikarte
    nach Name (Events selbst zu Zeilen gefaltet)."""
    return _kontext_stand(telefon, name, client_id)[0]


def _suche_nach_nummer(telefon: str, client_id: str = "") -> tuple[str, list[str]]:
    """GET /brain/search?q=<ziffern>&kind=event — nur offene Zeilen."""
    r = httpx.get(f"{MAS_URL}/brain/search",
                  params={"q": telefon, "kind": "event", "sinceDays": 14, "limit": 10},
                  headers=_headers(client_id), timeout=KONTEXT_WARTE_S)
    d = r.json()
    hits = sorted((d.get("results") or []), key=lambda h: h.get("ts") or 0, reverse=True)
    zeilen: list[str] = []
    ids: list[str] = []
    wer = ""
    for h in hits:
        if h.get("kind") != "event":
            continue
        if not _event_ist_themenotiz(h):
            continue
        summ = _s(h.get("snippet") or h.get("summary"))
        if not summ:
            continue
        wann = _wann_zeile(h.get("ts"))
        zeilen.append(f"- {wann + ': ' if wann else ''}{summ} (noch offen)")
        eid = _s(h.get("id"))
        if eid:
            ids.append(eid)
        if not wer:
            kandidat = _s(h.get("counterpartyName")) or _s(h.get("subjectName"))
            if kandidat and not kandidat[:1].isdigit():
                wer = kandidat
        if len(zeilen) >= _MAX_ZEILEN:
            break
    if not zeilen:
        return "", []
    return ((f"Praxisgedächtnis zu dieser Rufnummer{f' (vermutlich {wer})' if wer else ''}:\n"
             + "\n".join(zeilen)
             + "\nNutze das aktiv: erkenne den Zusammenhang an, statt bei Null anzufangen."), ids)


def _kontext_arbeit(sit: dict, telefon: str, name: str, key: str) -> None:
    stimme = notes.stimme_von(sit).lower()
    try:
        text, ids = _kontext_stand(telefon, name, _client_id(sit))
        if sit.get("gedaechtnisKey") != key:
            return  # inzwischen ist mehr bekannt — der neuere Lauf gewinnt
        sit["gedaechtnis"] = text
        sit["gedaechtnisOffen"] = ids
        try:
            from kern import dossier
            dossier.fuellen(sit)
        except Exception:
            pass
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


def fakt_senden(sit: dict, zeile: str, *, art: str = "fakt") -> None:
    """Festen Fakt mitten im Gespräch ins MAS — nie auf dem Mund-Pfad.

    Eigene Event-Id je Fakt, damit der Hangup-Report unberührt bleibt.
    Daemon-Thread, nie werfend. Notaus wie report_senden."""
    if not enabled():
        return
    text = _s(zeile)
    sid = _s(sit.get("id"))
    if not text or not sid:
        return
    n = int(sit.get("gedaechtnisFaktNr") or 0) + 1
    sit["gedaechtnisFaktNr"] = n
    stimme = notes.stimme_von(sit).lower()
    kanal = "bianca_call" if stimme == "bianca" else "lisa_call"
    telefon, name = _wer(sit)
    body = {
        "id": f"telefonki:fakt:{sid}:{n}",
        "channel": kanal,
        "direction": "in" if kanal == "bianca_call" else "out",
        "type": "note",
        "counterparty": {"kind": "patient", "name": name, "ref": telefon or None},
        "summary": text[:400],
        "signals": {},
        "status": "none",
        "confidence": 0.9,
        "payloadRef": {"kind": "telefonki_fakt", "id": sid, "art": art, "n": n},
        "extractor": "telefonki@v1",
    }

    def arbeit() -> None:
        try:
            r = httpx.post(f"{MAS_URL}/brain/events", json=body,
                           headers=_headers(_client_id(sit)), timeout=WARTE_S)
            print(f"{stimme}-gedaechtnis fakt {body['id']} -> {r.status_code}",
                  flush=True)
        except Exception as e:
            print(f"{stimme}-gedaechtnis fakt fail {e}", flush=True)

    threading.Thread(target=arbeit, daemon=True).start()


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


def kontext_abwarten(sit: dict, max_s: float = 1.5) -> None:
    """Kurz warten, bis der Hintergrund-Kontext da ist — nie länger als max_s.

    Wenn der Rückrufer sofort nach dem Grund fragt, darf der Mund nicht
    raten. Der Abruf läuft schon seit der Begrüßung; hier nur der Rest."""
    if sit.get("gedaechtnis") is not None:
        return
    if not enabled():
        return
    if not sit.get("gedaechtnisKey"):
        kontext_anstossen(sit)
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_s:
        if sit.get("gedaechtnis") is not None:
            return
        if not sit.get("gedaechtnisKey"):
            return
        time.sleep(0.08)


def offen_erledigen(sit: dict, note: str = "Mitgeteilt — Rückrufer informiert.") -> None:
    """Offene Team-/Rückruf-Notizen zur Anrufernummer schließen.

    In der Sekunde, in der der Angerufene zurückruft und nach dem Grund
    fragt (erledigt weil mitgeteilt) — nie auf dem Mund-Pfad. Nutzt
    POST /brain/caller-context/resolve. Notaus wie report_senden."""
    if not enabled():
        return
    telefon, _name = _wer(sit)
    ids = [x for x in (sit.get("gedaechtnisOffen") or []) if _s(x)]
    if not telefon and not ids:
        return
    sit["gedaechtnisOffen"] = []
    sit["gedaechtnis"] = ""
    stimme = notes.stimme_von(sit)
    body = {
        "phone": telefon,
        "actor": stimme or "Bianca",
        "note": _s(note) or "Am Telefon erledigt",
        "eventIds": ids,
    }

    def arbeit() -> None:
        try:
            r = httpx.post(f"{MAS_URL}/brain/caller-context/resolve", json=body,
                           headers=_headers(_client_id(sit)), timeout=WARTE_S)
            print(f"{stimme.lower()}-gedaechtnis erledigt {telefon or ids} -> {r.status_code}",
                  flush=True)
        except Exception as e:
            print(f"{stimme.lower()}-gedaechtnis erledigt fail {e}", flush=True)

    threading.Thread(target=arbeit, daemon=True).start()


def kontext_block(sit: dict) -> str:
    """Prompt-Block für beide Stimmen — leer, wenn nichts vorliegt."""
    text = _s_mehrzeilig(sit.get("gedaechtnis"))
    if not text:
        return ""
    return f"\nPRAXISGEDÄCHTNIS (frühere Kontakte)\n{text}\n"


def _s_mehrzeilig(v: Any) -> str:
    return str(v or "").strip()
