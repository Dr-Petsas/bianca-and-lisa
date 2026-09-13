"""W-TRANSFER-RUECKKEHR (13.09.2026): nach einem Verbinde-Versuch geht es in
DERSELBEN Sitzung weiter — nie auf null.

Chef (woertlich): "bei nicht erfolgreichem Verbinden darf nicht auf 0
zurueckgefallen werden im Gespraech!!! es muss da weiter gehen wo man
aufgehoert hat."

Mechanik: der Asterisk-Dialplan kehrt nach dem Dial zum Behandler mit
Goto(bianca) zurueck (besetzt, keine Antwort ODER Gespraech beim Behandler
beendet, Anrufer noch dran). Die Bruecke erkennt die Rueckkehr an der
unveraenderten Anruf-UUID und meldet die alte Sitzung als ``resumeSessionId``
an /api/start. Hier wird geprueft, ob die Sitzung wirklich zu diesem Anruf
gehoert (gleiche DID, gleicher Anrufer, ein Transfer lief tatsaechlich, nicht
zu alt) und der Zustand fuer die Fortsetzung vorbereitet:

- ERREICHEN-Anliegen im Hirn ist bedient; das zuletzt geparkte Anliegen
  (z. B. die unterbrochene Buchung) rueckt mit Checkpoint zurueck.
- Hangup-Marken zuruecksetzen, damit das ECHTE Ende spaeter wieder Notiz,
  Report und CF-Abschluss schreibt (der Transfer-Hangup lief schon einmal
  durch; identische Notizzeilen filtert masAppointmentNote, der MAS-Report
  bekommt eine eigene Event-Id — s. gedaechtnis._event).
- Kein zweiter PhoneCall-Datensatz: /api/start ruft fuer die Rueckkehr weder
  fuer_did noch call_erfassen — Tenant und phoneCallId bleiben die alten.

Notaus: TRANSFER_RUECKKEHR=0 => jede Rueckkehr ist ein frischer Anruf wie vor
dem 13.09.2026.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from bianca import session
from kern import hirn, spur, stille, tenants

# Aelter darf die Sitzung nicht sein — die Bruecke raeumt ohnehin nach 15 min.
RUECKKEHR_MAX_S = float(os.environ.get("TRANSFER_RUECKKEHR_MAX_S", "1800"))


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def enabled() -> bool:
    return os.environ.get("TRANSFER_RUECKKEHR", "1") != "0"


def passt(sit: dict | None, *, did: str = "", caller: str = "") -> str:
    """'' wenn die Sitzung zu diesem Anruf gehoert, sonst der Grund."""
    if not isinstance(sit, dict) or not _s(sit.get("id")):
        return "unbekannt"
    if _s(sit.get("stimme")).lower() != "bianca":
        return "keine-bianca-sitzung"
    if not (sit.get("weiterleitungZiel") or sit.get("transferHistorie")):
        return "kein-transfer"
    sit_did = tenants.nummer_norm(sit.get("did"))
    neu_did = tenants.nummer_norm(did)
    if not sit_did or not neu_did or sit_did != neu_did:
        return "did-fremd"
    sit_caller = tenants.nummer_norm(sit.get("callerPhone"))
    neu_caller = tenants.nummer_norm(caller)
    if sit_caller and neu_caller and sit_caller != neu_caller:
        return "anrufer-fremd"
    try:
        start = datetime.fromisoformat(_s(sit.get("startedAt")))
        alter = (datetime.now(start.tzinfo or timezone.utc) - start).total_seconds()
        if alter > RUECKKEHR_MAX_S:
            return "zu-alt"
    except (TypeError, ValueError):
        return "ohne-startzeit"
    return ""


def aufnehmen(sid: str, *, did: str = "", caller: str = "", schnell: bool = False,
              seit_s: float = 0.0, ziel: str = "") -> dict | None:
    """Die Sitzung des Transfers fuer die Fortsetzung vorbereiten.

    None => kein passender Stand, der Aufrufer startet einen normalen Anruf."""
    if not enabled():
        print(f"bianca-rueckkehr aus (TRANSFER_RUECKKEHR=0) sid={sid!r}", flush=True)
        return None
    sit = session.holen(sid)
    grund = passt(sit, did=did, caller=caller)
    if grund:
        print(f"bianca-rueckkehr abgelehnt sid={sid!r} grund={grund}", flush=True)
        return None
    assert sit is not None
    vorbereiten(sit, schnell=schnell, seit_s=seit_s, ziel=ziel)
    return sit


def vorbereiten(sit: dict, *, schnell: bool = False, seit_s: float = 0.0,
                ziel: str = "") -> dict:
    """Zustand fuer die Fortsetzung stellen (ohne Netz, ohne LLM)."""
    n = int(sit.get("transferRueckkehrN") or 0) + 1
    wl = sit.pop("weiterleitungZiel", None) or {}
    wer = _s(ziel) or _s(wl.get("name"))
    hist = sit.setdefault("transferHistorie", [])
    hist.append({
        "ziel": wer,
        "nummer": _s(wl.get("nummer")),
        "zeit": datetime.now(timezone.utc).isoformat(),
        "seitS": float(seit_s or 0.0),
        "schnell": bool(schnell),
    })
    sit["transferRueckkehrN"] = n
    rk: dict[str, Any] = {"n": n, "ziel": wer, "schnell": bool(schnell),
                          "seitS": float(seit_s or 0.0), "offen": True}
    sit["transferRueckkehr"] = rk
    # Der Verbinde-Zweig ist bedient — kein haengender Zettel, der beim
    # naechsten Satz eine zweite Weiterleitung anstoesst.
    sit["weiterleiten"] = {}
    sit.pop("hirnVerbinden", None)
    # Letzte Aeusserung war Ansage + Jingle: kein Barge-Rest, keine
    # Satzkarte, kein gehaltenes Satzfragment darf in die Fortsetzung
    # hineinspielen ("Also, wo war ich: ..." nach dem Klingeln).
    sit.pop("unterbrochen", None)
    sit.pop("ausspr", None)
    sit.pop("halbsatz", None)
    sit.pop("halbsatzZahl", None)
    # Der Transfer-Hangup hat Notiz/Report einmal geschrieben. Das ECHTE Ende
    # muss die Fortsetzung noch einmal erfassen (Buchung danach!). Der
    # MAS-Report der Fortsetzung traegt die Phase in der Event-Id
    # (gedaechtnis._event_id) — kein Duplikat-Verwurf im MAS.
    sit.pop("hangupNotiert", None)
    sit.pop("gedaechtnisReport", None)
    # Stille-Stupse dieser Phase von vorn; der Anruf-Gesamtzaehler bleibt.
    stille.reset(sit)
    # Hirn: ERREICHEN ist bedient, geparktes Anliegen (Buchung) rueckt zurueck.
    wieder = hirn.nach_transfer_ruecken(sit)
    if isinstance(wieder, dict):
        rk["wieder"] = {"id": _s(wieder.get("id")), "handlung": _s(wieder.get("handlung"))}
    spur.merken(sit, "transfer-rueckkehr",
                f"n={n} ziel={wer or '-'} schnell={int(bool(schnell))}"
                + (f" wieder={_s(wieder.get('handlung'))}" if isinstance(wieder, dict) else ""))
    print(f"bianca-rueckkehr sid={sit.get('id')!r} n={n} ziel={wer!r} "
          f"seit={seit_s}s schnell={bool(schnell)} "
          f"wieder={_s((wieder or {}).get('handlung')) or '-'}", flush=True)
    return rk


def offen(sit: dict) -> dict | None:
    """Die noch nicht gesprochene Rueckkehr (fuer agent.start_reply)."""
    rk = sit.get("transferRueckkehr")
    if isinstance(rk, dict) and rk.get("offen"):
        return rk
    return None
