"""Standorteinstellungen aus Pickadoc: Oeffnungszeiten (W-STANDORT 13.09.2026).

Chef (wörtlich): „öffnungszeiten bitte aus den Standorteinstellungen ablesen
und im prompt verankern bei blessing und thaler".

Die Praxen pflegen ihre Zeiten im Portal am STANDORT
(``clients/{clientId}/locations/{locationId}.openingHours`` — Modell
docgendaweb ``shared/models/openingHours``: je Wochentag ``hasOpen``/``open``
und ``hasPause``/``pause``). Im Agent-Prompt standen die Zeiten bei Thaler und
Blessing nur als Fliesstext in Formen, die ``kern.wissen`` nicht liest
(Wochentag und Uhrzeit auf getrennten Zeilen, „7.30 - 13.30 Uhr & 14 - 17
Uhr") — das Modell antwortete frei und lag in der Probe vom 13.09. zweimal
falsch (Thaler Freitag, Blessing „halb zwoelf" statt 12:30).

Die Cloud Function ``onPickadocPhoneCall`` liefert das Standort-Dokument
(noch) nicht mit. Deshalb liest dieses Modul es direkt ueber die Firestore-
REST-API — mit demselben Service-Account, den W-CALLAUDIO fuer den Audio-
Upload nutzt (``kern.anrufaudio._access_token``, hier mit Datastore-Scope).
Nur LESEN, ein Dokument je Mandant, TTL-Cache, Fehler halten den letzten
guten Stand (stale-while-error) — der Anruf-Pfad leidet nie.

Wirkung (``anreichern``):
- ``tenant["standort"]`` = {name, adresse, telefon, zeiten, text, prompt}
- ``tenant["dbPrompt"]`` bekommt einen Block „Öffnungszeiten laut
  Standorteinstellungen" — NUR wenn der Agent-Prompt nicht schon eine
  ausdrueckliche Einzeiler-Angabe „Öffnungszeiten: …" traegt (MedDent pflegt
  die dort, Chef-Auftrag galt Thaler und Blessing). So bleibt MedDent
  byte-identisch und der Prompt traegt nie zwei widerspruechliche Angaben.
- ``kern.wissen.praxis_antwort`` spricht die Standort-Zeiten deterministisch,
  ``kern.praxisregeln.praxis_offen`` rechnet damit (Blessing-Akutregel).

Vorsicht vor Portal-DEFAULTS: ein nie gepflegter Standort traegt Mo–So
08:00–18:00 (Konstruktor-Default des Modells). Diese Form gilt als „nicht
gepflegt" und liefert KEINE Zeiten — lieber schweigen als raten.

Notaus: ``STANDORT_ZEITEN=0`` => byte-identisches Alt-Verhalten.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from kern.config import FIREBASE_CREDENTIALS

_SCOPE = "https://www.googleapis.com/auth/datastore"
_FIRESTORE_BASE = "https://firestore.googleapis.com/v1"
_TTL_S = float(os.environ.get("STANDORT_TTL_S") or "600")
_FEHL_TTL_S = 60.0
_WARTE_S = float(os.environ.get("STANDORT_WARTE_S") or "2.5")

TAGE = ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag")
_TAG_EN = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_TAG_SPRECH = {
    "montag": "Montag", "dienstag": "Dienstag", "mittwoch": "Mittwoch",
    "donnerstag": "Donnerstag", "freitag": "Freitag", "samstag": "Samstag",
    "sonntag": "Sonntag",
}
PROMPT_MARKER = "# Öffnungszeiten laut Standorteinstellungen"

# Ausdrueckliche Einzeiler-Angabe im Agent-Prompt („- Öffnungszeiten: Mo - Do:
# 08:00 - 18:00 Uhr, …") — dieselbe Form, die kern.wissen liest. Steht sie
# da, bleibt der Prompt wie er ist (kein zweiter, widerspruechlicher Block).
_EXPLIZIT_RE = re.compile(
    r"^[ \t]*[-*]?[ \t]*(?:öffnungs|oeffnungs|sprech)zeiten?[ \t]*:[ \t]*\S", re.I | re.M)

_LOCK = threading.Lock()
_CACHE: dict[str, dict[str, Any]] = {}
_PROJEKT: dict[str, str] = {}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def an() -> bool:
    """Standort-Lesen aktiv? Braucht den Service-Account-Key; Notaus per Env."""
    if os.environ.get("STANDORT_ZEITEN", "").strip().lower() in {"0", "false", "off", "no"}:
        return False
    return bool(FIREBASE_CREDENTIALS) and Path(FIREBASE_CREDENTIALS).is_file()


def anzeige() -> str:
    if an():
        return f"Standort-Öffnungszeiten aus Firestore ({len(_CACHE)} im Cache)"
    return "Standort-Öffnungszeiten aus (kein Service-Account-Key oder STANDORT_ZEITEN=0)"


# ---------------------------------------------------------------------------
# Firestore-REST
# ---------------------------------------------------------------------------

def _projekt() -> str:
    if not _PROJEKT.get("id"):
        import json
        sa = json.loads(Path(FIREBASE_CREDENTIALS).read_text(encoding="utf-8"))
        _PROJEKT["id"] = _s(sa.get("project_id")) or "docgenda"
    return _PROJEKT["id"]


def _decode(v: Any) -> Any:
    """Firestore-REST-Wert (typisiert) -> Python."""
    if not isinstance(v, dict):
        return v
    if "mapValue" in v:
        felder = (v.get("mapValue") or {}).get("fields") or {}
        return {k: _decode(w) for k, w in felder.items()}
    if "arrayValue" in v:
        return [_decode(w) for w in ((v.get("arrayValue") or {}).get("values") or [])]
    if "integerValue" in v:
        try:
            return int(v["integerValue"])
        except (TypeError, ValueError):
            return 0
    if "doubleValue" in v:
        return v["doubleValue"]
    if "booleanValue" in v:
        return bool(v["booleanValue"])
    if "stringValue" in v:
        return v["stringValue"]
    if "timestampValue" in v:
        return v["timestampValue"]
    if "nullValue" in v:
        return None
    return v


def _dokument(client_id: str, location_id: str) -> dict[str, Any] | None:
    """Das Standort-Dokument lesen (nur die gebrauchten Felder) — None bei Fehler."""
    from kern import anrufaudio
    token = anrufaudio._access_token(_SCOPE)
    pfad = f"projects/{_projekt()}/databases/(default)/documents/clients/{client_id}/locations/{location_id}"
    r = httpx.get(
        f"{_FIRESTORE_BASE}/{pfad}",
        params=[("mask.fieldPaths", f) for f in
                ("name", "street", "postalCode", "city", "phone", "phoneNumber", "openingHours")],
        headers={"Authorization": f"Bearer {token}"},
        timeout=_WARTE_S,
    )
    if r.status_code != 200:
        print(f"standort {client_id}/{location_id} -> http {r.status_code}: {r.text[:160]}",
              flush=True)
        return None
    d = r.json()
    felder = d.get("fields") if isinstance(d, dict) else None
    if not isinstance(felder, dict):
        return None
    return {k: _decode(v) for k, v in felder.items()}


# ---------------------------------------------------------------------------
# Oeffnungszeiten normalisieren
# ---------------------------------------------------------------------------

def _hhmm(t: Any) -> str:
    if not isinstance(t, dict):
        return ""
    try:
        h = int(t.get("hour"))
        m = int(t.get("minute") or 0)
    except (TypeError, ValueError):
        return ""
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return ""
    return f"{h:02d}:{m:02d}"


def _minuten(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def zeiten_von(opening: Any) -> dict[str, list[tuple[str, str]]] | None:
    """openingHours (Portal-Modell) -> {wochentag: [(von, bis), ...]}.

    Geschlossene Tage stehen mit leerer Liste drin. Eine Pause teilt das
    Fenster in zwei Spannen. None, wenn nichts Gepflegtes vorliegt
    (unbrauchbare Werte oder der Portal-Default Mo–So 08:00–18:00 ohne jede
    Anpassung — nie raten). ``enabled`` wird am STANDORT bewusst ignoriert:
    das Portal (``ClientLocation.fromObject``) setzt es dort immer auf true,
    der gespeicherte Wert traegt keine Information.
    """
    if not isinstance(opening, dict):
        return None
    out: dict[str, list[tuple[str, str]]] = {}
    for de, en in zip(TAGE, _TAG_EN):
        tag = opening.get(en)
        if not isinstance(tag, dict):
            return None
        if tag.get("hasOpen") is not True:
            out[de] = []
            continue
        von = _hhmm((tag.get("open") or {}).get("start"))
        bis = _hhmm((tag.get("open") or {}).get("end"))
        if not von or not bis or _minuten(von) >= _minuten(bis):
            return None
        spannen = [(von, bis)]
        if tag.get("hasPause") is True:
            p_von = _hhmm((tag.get("pause") or {}).get("start"))
            p_bis = _hhmm((tag.get("pause") or {}).get("end"))
            if (p_von and p_bis and _minuten(von) < _minuten(p_von)
                    < _minuten(p_bis) < _minuten(bis)):
                spannen = [(von, p_von), (p_bis, bis)]
        out[de] = spannen
    # Portal-Default (Konstruktor): alle sieben Tage 08:00–18:00 offen — das
    # hat niemand so gepflegt, eine Praxis mit Sonntagssprechstunde erst recht.
    if all(out[t] == [("08:00", "18:00")] for t in TAGE):
        return None
    if not any(out[t] for t in TAGE):
        return None
    return out


def offen(zeiten: dict[str, list[tuple[str, str]]] | None, jetzt) -> bool | None:
    """Ist die Praxis zu ``jetzt`` (datetime) geoeffnet? None ohne Zeiten."""
    if not zeiten:
        return None
    spannen = zeiten.get(TAGE[jetzt.weekday()])
    if spannen is None:
        return None
    minute = jetzt.hour * 60 + jetzt.minute
    for von, bis in spannen:
        if _minuten(von) <= minute <= _minuten(bis):
            return True
    return False


# ---------------------------------------------------------------------------
# Sprech- und Prompt-Form
# ---------------------------------------------------------------------------

def _zeit_sprech(hhmm: str) -> str:
    """'07:30' -> '7:30 Uhr', '14:00' -> '14 Uhr' — kern.sprech.sanitize macht
    daraus 'sieben Uhr dreißig' bzw. 'vierzehn Uhr' (jede Zeit traegt 'Uhr')."""
    h, m = hhmm.split(":")
    return f"{int(h)} Uhr" if m == "00" else f"{int(h)}:{m} Uhr"


def _spannen_sprech(spannen: list[tuple[str, str]]) -> str:
    return " und ".join(f"von {_zeit_sprech(a)} bis {_zeit_sprech(b)}" for a, b in spannen)


def _tage_sprech(tage: list[str]) -> str:
    namen = [_TAG_SPRECH[t] for t in tage]
    if len(namen) == 1:
        return namen[0]
    idx = [TAGE.index(t) for t in tage]
    if len(idx) >= 3 and idx == list(range(idx[0], idx[0] + len(idx))):
        return f"{namen[0]} bis {namen[-1]}"
    return ", ".join(namen[:-1]) + f" und {namen[-1]}"


def sprechform(zeiten: dict[str, list[tuple[str, str]]] | None) -> str:
    """Gesprochene Form, gruppiert nach gleichen Zeiten:
    'Montag und Mittwoch von 7:30 Uhr bis 13:30 Uhr und von 14 Uhr bis 17 Uhr,
    Dienstag und Donnerstag …, Freitag geschlossen'. Samstag/Sonntag nur, wenn
    offen — geschlossene Wochenenden sagt niemand dazu."""
    if not zeiten:
        return ""
    gruppen: list[tuple[list[tuple[str, str]], list[str]]] = []
    for tag in TAGE:
        spannen = zeiten.get(tag) or []
        if not spannen and tag in ("samstag", "sonntag"):
            continue
        for sp, tage in gruppen:
            if sp == spannen:
                tage.append(tag)
                break
        else:
            gruppen.append((spannen, [tag]))
    teile: list[str] = []
    for sp, tage in gruppen:
        wer = _tage_sprech(tage)
        teile.append(f"{wer} geschlossen" if not sp else f"{wer} {_spannen_sprech(sp)}")
    return ", ".join(teile)


def prompt_block(zeiten: dict[str, list[tuple[str, str]]] | None) -> str:
    """Block fuer den Praxis-Prompt — eine Zeile je Wochentag, Zeiten als
    HH:MM-HH:MM Uhr (dieselbe Form liest praxisregeln.praxis_offen)."""
    if not zeiten:
        return ""
    zeilen = [PROMPT_MARKER + " (verbindlich — sie ersetzen alle anderen "
              "Zeitangaben im Profil; nur diese Zeiten nennen, Wunschtermine "
              "ausserhalb gibt es nicht):"]
    for tag in TAGE:
        spannen = zeiten.get(tag) or []
        if spannen:
            zeilen.append(f"{_TAG_SPRECH[tag]}: " + ", ".join(f"{a}-{b} Uhr" for a, b in spannen))
        else:
            zeilen.append(f"{_TAG_SPRECH[tag]}: geschlossen")
    return "\n".join(zeilen)


# ---------------------------------------------------------------------------
# Laden mit Cache + Tenant anreichern
# ---------------------------------------------------------------------------

def _bauen(doc: dict[str, Any]) -> dict[str, Any]:
    zeiten = zeiten_von(doc.get("openingHours"))
    adresse = _s(" ".join(_s(doc.get(k)) for k in ("street", "postalCode", "city")))
    return {
        "name": _s(doc.get("name")),
        "adresse": adresse,
        "telefon": _s(doc.get("phoneNumber")) or _s(doc.get("phone")),
        "zeiten": zeiten,
        "text": sprechform(zeiten),
        "prompt": prompt_block(zeiten),
    }


_LAEUFT: set[str] = set()   # Keys mit laufendem Lesezugriff (ein Faden je Standort)


def _holen(key: str, cid: str, lid: str) -> dict[str, Any] | None:
    """Ein Lesezugriff + Cache-Pflege (stale-while-error). Nie werfend."""
    now = time.monotonic()
    wert: dict[str, Any] | None = None
    try:
        doc = _dokument(cid, lid)
        if doc is not None:
            wert = _bauen(doc)
            print(f"standort {key} -> Zeiten {'ja' if wert.get('zeiten') else 'nein'}"
                  f" name={wert.get('name')!r}", flush=True)
    except Exception as e:
        print(f"standort {key} fail {type(e).__name__}: {e}", flush=True)
    with _LOCK:
        alt = _CACHE.get(key) or {}
        if wert is None and alt.get("wert") is not None:
            # Fehler, aber ein guter alter Stand liegt vor: behalten, spaeter
            # erneut versuchen (Zeitstempel frisch, damit nicht jeder Anruf
            # in den Timeout laeuft).
            _CACHE[key] = {"t": now, "wert": alt["wert"], "stale": True}
            _LAEUFT.discard(key)
            return alt["wert"]
        _CACHE[key] = {"t": now, "wert": wert}
        _LAEUFT.discard(key)
    return wert


def laden(client_id: Any, location_id: Any) -> dict[str, Any] | None:
    """Standort-Fakten fuer (clientId, locationId) — gecacht, nie werfend.

    - erster Zugriff je Mandant: synchron lesen (der Warmstart des Servers
      erledigt das fuer alle lokalen Mandanten, bevor der erste Anruf kommt)
    - abgelaufener Stand: SOFORT den alten Wert liefern und im Hintergrund
      auffrischen (stale-while-revalidate) — der Anruf-Pfad wartet nie auf
      Firestore, sobald einmal etwas da war
    - Fehler halten den letzten guten Stand; ohne jeden Stand wird 60 s
      nicht erneut versucht
    """
    cid, lid = _s(client_id), _s(location_id)
    if not cid or not lid or not an():
        return None
    key = f"{cid}/{lid}"
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit:
            alter = now - hit["t"]
            frisch = alter < (_TTL_S if hit.get("wert") is not None else _FEHL_TTL_S)
            if frisch:
                return hit.get("wert")
            if hit.get("wert") is not None:
                if key not in _LAEUFT:
                    _LAEUFT.add(key)
                    threading.Thread(target=_holen, args=(key, cid, lid),
                                     daemon=True, name=f"standort-{lid}").start()
                return hit["wert"]
        _LAEUFT.add(key)
    return _holen(key, cid, lid)


def hat_explizite_zeiten(prompt: str) -> bool:
    return bool(_EXPLIZIT_RE.search(str(prompt or "")))


def anreichern(t: dict[str, Any] | None) -> dict[str, Any] | None:
    """tenant um Standort-Fakten ergaenzen (idempotent, nie werfend).

    - ``t["standort"]`` immer, wenn das Dokument lesbar war
    - Prompt-Block NUR ohne ausdrueckliche Einzeiler-Angabe im Agent-Prompt
      und nur einmal (Marker).
    """
    if not isinstance(t, dict) or not an():
        return t
    try:
        st = laden(t.get("clientId"), t.get("locationId"))
    except Exception as e:  # pragma: no cover - laden faengt selbst
        print(f"standort anreichern fail {type(e).__name__}: {e}", flush=True)
        st = None
    if not st:
        return t
    t["standort"] = dict(st)
    block = _s(st.get("prompt")) and str(st.get("prompt"))
    prompt = str(t.get("dbPrompt") or "")
    if block and PROMPT_MARKER not in prompt and not hat_explizite_zeiten(prompt):
        t["dbPrompt"] = (prompt.rstrip() + "\n\n" + block).strip() if prompt.strip() else block
    return t


def cache_leeren() -> None:
    with _LOCK:
        _CACHE.clear()
