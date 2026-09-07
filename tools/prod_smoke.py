#!/usr/bin/env python3
"""Produktions-Smoke: DID → Agent → Weiterleitung + Live-Satz-Wachen.

Vor jedem Deploy (oder danach auf pickadoc1) ausfuehren:

    python tools/prod_smoke.py
    # im Container:
    docker exec -w /app telefonki-bianca-1 python tools/prod_smoke.py

Exit 0 = ok, Exit 1 = Regression — nicht deployen / Rollback pruefen.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fail(msg: str) -> None:
    print(f"FAIL  {msg}")
    raise SystemExit(1)


def _ok(msg: str) -> None:
    print(f"OK    {msg}")


def main() -> None:
    from kern import agentprofil, intent, tenants
    from bianca import flow, weiterleiten
    from kern.tenants import laden

    # --- 1) Intent: Besprechung ist kein ERREICHEN ---------------------------
    for satz in (
        "Ich brauche eine Implantatbesprechung.",
        "Ich brauche einen Termin zur ZE Besprechung.",
    ):
        d = intent._fallback({}, satz)
        if d.get("handlung") == "ERREICHEN":
            _fail(f"Intent ERREICHEN fuer {satz!r}")
        if weiterleiten.erkannt(satz):
            _fail(f"weiterleiten.erkannt fuer {satz!r}")
    _ok("Besprechung != ERREICHEN / Weiterleiten")

    # --- 2) Lokale Forwardings + Transfer-Pfad --------------------------------
    med = laden("meddent")
    wl = med.get("weiterleitungen") or []
    if len(wl) < 2:
        _fail("meddent.json weiterleitungen < 2 (Petsas/Patrikis)")
    sit = {"tenant": med, "messages": [{"role": "system", "content": "x"}]}
    events: list[str] = []
    z = flow.zug(sit, "Kann ich bitte mit Doktor Petsas sprechen?", events.append)
    tr = (z or {}).get("transfer") or {}
    if tr.get("nummer") != "+4921130293035":
        _fail(f"kein Petsas-Transfer: {z!r}")
    if weiterleiten.JINGLE_EVENT not in events:
        _fail("Jingle fehlt bei echter Weiterleitung")
    _ok(f"Weiterleitung Petsas -> {tr['nummer']} + Jingle")

    # --- 2b) Dienst-Schicht darf transfer nicht verschlucken ----------------
    from kern.dienst import Dienst
    d = Dienst(name="smoke", start_fn=lambda s: {},
               turn_fn=lambda s, t, **k: {
                   "text": "", "hangup": True,
                   "transfer": {"nummer": "+4921130293035", "name": "Dr. Petsas"},
               })
    d.stimme = lambda text, karte=None: ("", 0.0)  # type: ignore
    d.stimme_stream = lambda text, karte=None: ("", 0.0)  # type: ignore
    sit2 = {"tenant": med, "messages": [{"role": "system", "content": "x"}]}
    aus = d.json_antwort(sit2, art="listen", text_in="verbinden")
    if not (aus.get("transfer") or {}).get("nummer"):
        _fail("json_antwort verschluckt transfer (Jingle-ohne-Dial-Bug)")
    _ok("json_antwort reicht transfer durch")

    # --- 2c) CallR-Abschluss darf nicht wieder fehlen (W-LIVE-Regression) ---
    import inspect
    from bianca import server as bs
    if "did" not in getattr(bs.StartIn, "model_fields", {}):
        _fail("StartIn.did fehlt — SIP kann keinen phoneCallId setzen")
    hang = inspect.getsource(bs.api_hangup)
    if "call_abschliessen" not in hang:
        _fail("api_hangup ohne call_abschliessen — CallR-Transkripte sterben")
    if "mitschnitt.ende" not in hang:
        _fail("api_hangup ohne mitschnitt.ende")
    ja = inspect.getsource(Dienst.json_antwort)
    if "mitschnitt.zug" not in ja:
        _fail("json_antwort ohne mitschnitt.zug")
    _ok("CallR/Mitschnitt-Pfad verdrahtet")

    # --- 3) Jede DID: CF oder Geschwister liefert Agent + WL -----------------
    agentprofil.cache_leeren()
    dids = med.get("dids") or []
    if not dids:
        _fail("meddent.json ohne dids")
    for did in dids:
        t = agentprofil.fuer_did(did)
        if not t:
            _fail(f"kein Tenant fuer DID {did}")
        w = t.get("weiterleitungen") or []
        if not w and agentprofil.enabled():
            # CF tot + lokale Datei sollte WL haben — trotzdem pruefen
            if not (med.get("weiterleitungen") or []):
                _fail(f"DID {did}: keine weiterleitungen")
        if agentprofil.enabled() and not w:
            # Fallback-Datei muss WL tragen wenn CF leer
            if t.get("_quelle") == "cf" or str(t.get("_quelle") or "").startswith("cf"):
                _fail(f"DID {did}: CF-Tenant ohne weiterleitungen")
        _ok(f"DID {did} -> {t.get('_quelle')} wl={len(w) or len(med.get('weiterleitungen') or [])}")

    # --- 4) Prefill-Konstante SIP-Bruecke ------------------------------------
    from sip_bridge import server as bruecke
    if bruecke.PREBUF_MS < 800:
        _fail(f"BRIDGE_PREBUF_MS zu klein: {bruecke.PREBUF_MS}")
    _ok(f"SIP Prefill {bruecke.PREBUF_MS} ms")

    print("prod_smoke: ALLE WACHEN GRUEN")


if __name__ == "__main__":
    main()
