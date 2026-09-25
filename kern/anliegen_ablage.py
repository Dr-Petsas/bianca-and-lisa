"""Veroeffentlichte Anliegen-Strategien pro Mandant.

Chef 20.09.2026: zu jedem Anliegen legt die Praxis fest, wie Bianca reagiert
(nur persoenlich / Rueckruf / Notiz), inkl. eigenem Satz. Die Terminverwaltung
steht nicht in dieser Datei — die bleibt fest.

    Portal-Wahrheit: ``clients/{clientId}/settings/biancaAnliegen``
(Superuser > Bianca indiv. Settings), gelesen wie ``kern/standort.py``.
Lokale Datei ``.data/anliegen/<mandant>.json`` ist nur Rueckfall.
``kern.anliegen_katalog.parse`` liest den Inhalt; eine verbogene Datei
landet auf der konservativsten Option.

Notaus: ``ANLIEGEN_ABLAGE=0``.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from kern.config import DATA_DIR, FIREBASE_CREDENTIALS

ORDNER = DATA_DIR / "anliegen"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$", re.I)

# Portal-Ablage (Superuser > Bianca indiv. Settings):
# clients/{clientId}/settings/biancaAnliegen — gleicher Firestore-Weg wie
# kern/standort.py. Die Studio-Datei bleibt Rueckfall.
_TTL_S = float(os.environ.get("ANLIEGEN_TTL_S") or "600")
_FEHL_TTL_S = 60.0
_WARTE_S = float(os.environ.get("ANLIEGEN_WARTE_S") or "2.5")
_LOCK = threading.Lock()
_CACHE: dict[str, dict[str, Any]] = {}
_LAEUFT: set[str] = set()


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def an() -> bool:
    return _s(os.getenv("ANLIEGEN_ABLAGE", "1")).lower() not in (
        "0", "off", "false", "nein",
    )


def _id_ok(tenant_id: str) -> str:
    kennung = _s(tenant_id)
    return kennung if _ID_RE.match(kennung) else ""


def pfad(tenant_id: str) -> Path | None:
    kennung = _id_ok(tenant_id)
    return (ORDNER / f"{kennung}.json") if kennung else None


def lesen(tenant_id: str) -> dict[str, Any] | None:
    if not an():
        return None
    p = pfad(tenant_id)
    if p is None or not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and isinstance(d.get("policy"), dict) else None


def policy(tenant_id: str) -> dict[str, Any] | None:
    eintrag = lesen(tenant_id)
    return dict(eintrag["policy"]) if eintrag else None


def schreiben(tenant_id: str, vertrag: dict[str, Any], *,
              wer: str = "superuser", notiz: str = "") -> dict[str, Any]:
    if not an():
        return {"ok": False, "fehler": "Ablage ist per ANLIEGEN_ABLAGE=0 abgeschaltet."}
    p = pfad(tenant_id)
    if p is None:
        return {"ok": False, "fehler": f"Unzulaessige Mandanten-Kennung: {tenant_id!r}"}
    if not isinstance(vertrag, dict):
        return {"ok": False, "fehler": "Kein Vertrag."}
    from kern import anliegen_katalog as ak

    regeln, warn = ak.parse(vertrag)
    sauber = ak.as_dict(regeln)
    eintrag = {
        "tenant": _id_ok(tenant_id),
        "policy": sauber,
        "wer": _s(wer) or "superuser",
        "notiz": _s(notiz)[:200],
        "zeit": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "warnungen": warn,
    }
    try:
        ORDNER.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=ORDNER, delete=False, suffix=".tmp",
        ) as fh:
            json.dump(eintrag, fh, ensure_ascii=False, indent=2)
            tmp = Path(fh.name)
        tmp.replace(p)
    except OSError as exc:
        return {"ok": False, "fehler": f"Schreiben fehlgeschlagen: {exc}"}
    return {"ok": True, "pfad": str(p), "zeit": eintrag["zeit"],
            "warnungen": warn, "anliegen": list(regeln)}


def loeschen(tenant_id: str) -> dict[str, Any]:
    p = pfad(tenant_id)
    if p is None:
        return {"ok": False, "fehler": f"Unzulaessige Mandanten-Kennung: {tenant_id!r}"}
    if not p.is_file():
        return {"ok": True, "hinweis": "Es war nichts veroeffentlicht."}
    try:
        p.unlink()
    except OSError as exc:
        return {"ok": False, "fehler": f"Loeschen fehlgeschlagen: {exc}"}
    return {"ok": True}


def alle() -> list[dict[str, Any]]:
    if not an() or not ORDNER.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(ORDNER.glob("*.json")):
        eintrag = lesen(p.stem)
        if eintrag is None:
            continue
        pol = eintrag.get("policy") or {}
        anl = pol.get("anliegen") if isinstance(pol, dict) else {}
        out.append({
            "tenant": p.stem,
            "wer": eintrag.get("wer"),
            "zeit": eintrag.get("zeit"),
            "notiz": eintrag.get("notiz"),
            "anzahl": len(anl) if isinstance(anl, dict) else 0,
        })
    return out


def db_an() -> bool:
    """Portal-Dokument lesen? Braucht den Service-Account; Notaus per Env."""
    if _s(os.getenv("ANLIEGEN_DB", "1")).lower() in ("0", "off", "false", "nein"):
        return False
    return bool(FIREBASE_CREDENTIALS) and Path(FIREBASE_CREDENTIALS).is_file()


def _dokument(client_id: str) -> dict[str, Any] | None:
    """``clients/{id}/settings/biancaAnliegen`` — None bei Fehler/404."""
    cid = _s(client_id)
    if not cid:
        return None
    import httpx
    from kern import anrufaudio, standort

    token = anrufaudio._access_token("https://www.googleapis.com/auth/datastore")
    pfad = (
        f"projects/{standort._projekt()}/databases/(default)/documents/"
        f"clients/{cid}/settings/biancaAnliegen"
    )
    r = httpx.get(
        f"{standort._FIRESTORE_BASE}/{pfad}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=_WARTE_S,
    )
    if r.status_code == 404:
        return {}
    if r.status_code != 200:
        print(f"anliegen-db {cid} -> http {r.status_code}: {r.text[:160]}",
              flush=True)
        return None
    d = r.json()
    felder = d.get("fields") if isinstance(d, dict) else None
    if not isinstance(felder, dict):
        return {}
    return {k: standort._decode(v) for k, v in felder.items()}


def _policy_aus_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(doc, dict) or not doc:
        return None
    roh = doc.get("anliegen") if isinstance(doc.get("anliegen"), dict) else None
    if not roh:
        return None
    from kern import anliegen_katalog as ak

    regeln, _ = ak.parse({"anliegen": roh})
    if not regeln:
        return None
    return ak.as_dict(regeln)


def _holen(cid: str) -> dict[str, Any] | None:
    now = time.monotonic()
    wert: dict[str, Any] | None = None
    try:
        wert = _policy_aus_doc(_dokument(cid))
    except Exception as exc:
        print(f"anliegen-db {cid} fail {type(exc).__name__}: {exc}", flush=True)
    with _LOCK:
        alt = _CACHE.get(cid) or {}
        if wert is None and alt.get("wert") is not None:
            _CACHE[cid] = {"t": now, "wert": alt["wert"], "stale": True}
            _LAEUFT.discard(cid)
            return alt["wert"]
        _CACHE[cid] = {"t": now, "wert": wert}
        _LAEUFT.discard(cid)
    return wert


def aus_db(client_id: Any) -> dict[str, Any] | None:
    """Veroeffentlichte Portal-Policy, gecacht, nie werfend."""
    cid = _s(client_id)
    if not cid or not db_an():
        return None
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(cid)
        if hit:
            alter = now - hit["t"]
            frisch = alter < (_TTL_S if hit.get("wert") is not None else _FEHL_TTL_S)
            if frisch:
                return hit.get("wert")
            if hit.get("wert") is not None:
                if cid not in _LAEUFT:
                    _LAEUFT.add(cid)
                    threading.Thread(
                        target=_holen, args=(cid,), daemon=True,
                        name=f"anliegen-{cid[:8]}",
                    ).start()
                return hit["wert"]
        _LAEUFT.add(cid)
    return _holen(cid)


def cache_leeren() -> None:
    with _LOCK:
        _CACHE.clear()
        _LAEUFT.clear()


def _datei_policy(tenant: dict[str, Any], tenant_id: str) -> dict[str, Any] | None:
    kennungen = [
        _s(tenant_id),
        _s(tenant.get("_id")),
        _s(tenant.get("id")),
        _s(tenant.get("clientId")),
    ]
    aliases = tenant.get("tenantAliases") or []
    if isinstance(aliases, (list, tuple)):
        kennungen.extend(_s(x) for x in aliases)
    gesehen: set[str] = set()
    for kennung in kennungen:
        if not kennung or kennung in gesehen:
            continue
        gesehen.add(kennung)
        vertrag = policy(kennung)
        if vertrag:
            return vertrag
    try:
        from kern import tenants

        client = _s(tenant.get("clientId"))
        for t in tenants.liste():
            ids = [
                _s(t.get("id")),
                _s(t.get("clientId")),
                *[
                    _s(a) for a in (t.get("aliases") or [])
                    if _s(a)
                ],
            ]
            if client and client in ids:
                vertrag = policy(_s(t.get("id")))
                if vertrag:
                    return vertrag
            if any(k in ids for k in gesehen if k):
                vertrag = policy(_s(t.get("id")))
                if vertrag:
                    return vertrag
    except Exception:
        pass
    return None


def anreichern(tenant: dict[str, Any], tenant_id: str = "") -> dict[str, Any]:
    """``tenant['anliegenPolicy']`` fuellen, wenn noch nichts da ist.

    Reihenfolge: schon gesetzt → Portal-Firestore (Chef-Seite) → lokale Datei.
    """
    if not isinstance(tenant, dict):
        return tenant
    if isinstance(tenant.get("anliegenPolicy"), dict) and tenant["anliegenPolicy"]:
        return tenant
    db = aus_db(tenant.get("clientId"))
    if db:
        tenant["anliegenPolicy"] = db
        tenant["_anliegenPolicyQuelle"] = "portal"
        return tenant
    datei = _datei_policy(tenant, tenant_id)
    if datei:
        tenant["anliegenPolicy"] = datei
        tenant["_anliegenPolicyQuelle"] = "ablage"
    return tenant


__all__ = ["an", "alle", "anreichern", "aus_db", "cache_leeren", "db_an",
           "loeschen", "lesen", "pfad", "policy", "schreiben", "ORDNER"]
