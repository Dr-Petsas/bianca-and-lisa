"""Rueckwaertskompatible Task-Grenze vor dem Flow-Monolithen (W-TASK-GRENZE
09.09.2026).

Ziel dieses Schritts ist NICHT, die 2.000+ Zeilen aus `bianca/flow.py` zu
verschieben, sondern eine duenne, typisierte Grenze davor zu setzen: eine
Registry der fachfreien Aufgaben (buchen/absagen/verschieben/auskunft/
anmeldung/rueckruf) und einen Adapter, der den bestehenden `flow.zug`
UNVERAENDERT aufruft und dessen Ergebnis in ein Lifecycle
(active/done/parked/failed) einordnet.

`flow.zug` buendelt heute schon Buchung (`bianca/flow`), Absage/Verschieben/
Auskunft (`bianca/verwalten`) und Weiterleitung/Rueckruf (`bianca/weiterleiten`).
Der Adapter ist deshalb ein transparenter Umschlag: die gesprochene Antwort und
JEDER Werkzeugaufruf bleiben Byte fuer Byte gleich; hinzu kommt nur ein
Task-Ledger in der Sitzung (`sit["taskLedger"]`, inert).

Notaus `TASK_ADAPTERS=0` => `zug` ist exakt `flow.zug` (kein Ledger, kein
Klassifizieren). Tests: `tests/test_tasks.py`.
"""

from __future__ import annotations

import os
from typing import Any

from bianca import flow

TASK_TYPEN = ("buchen", "absagen", "verschieben", "auskunft", "anmeldung", "rueckruf")
LIFECYCLE = ("active", "done", "parked", "failed")

# Fachfreie Aufgabe -> bewaehrter Eintrittspunkt (nur Doku/Introspektion;
# der Aufruf laeuft weiterhin gebuendelt ueber flow.zug).
REGISTRY: dict[str, dict[str, str]] = {
    "buchen": {"modul": "bianca.flow", "eintritt": "zug"},
    "absagen": {"modul": "bianca.verwalten", "eintritt": "zug"},
    "verschieben": {"modul": "bianca.verwalten", "eintritt": "zug"},
    "auskunft": {"modul": "bianca.verwalten", "eintritt": "zug"},
    "anmeldung": {"modul": "bianca.weiterleiten", "eintritt": "zug"},
    "rueckruf": {"modul": "bianca.weiterleiten", "eintritt": "zug"},
}

_MODUS_TYP = {
    "buchen": "buchen",
    "absagen": "absagen",
    "verschieben": "verschieben",
    "auskunft": "auskunft",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def enabled() -> bool:
    return os.environ.get("TASK_ADAPTERS", "1").strip().lower() not in {
        "0", "false", "no",
    }


def registry() -> dict[str, dict[str, str]]:
    """Kopie der Task-Registry (typisierte Aufgabenliste)."""
    return {k: dict(v) for k, v in REGISTRY.items()}


def aktueller_typ(sit: dict) -> str:
    """Fachfreie Aufgabe des aktuellen Zugs — best effort, nur zum Melden."""
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    modus = _MODUS_TYP.get(_s(s.get("modus")))
    if modus:
        return modus
    ab = sit.get("hirnAbgeben")
    if isinstance(ab, dict) and ab.get("offen"):
        return "rueckruf"
    if sit.get("hirnVerbinden") or sit.get("hirnAbgeben"):
        return "anmeldung"
    return ""


def _geparkte_ids(sit: dict) -> set[str]:
    h = sit.get("hirn") if isinstance(sit.get("hirn"), dict) else {}
    return {
        _s(a.get("id"))
        for a in (h.get("anliegen") or [])
        if isinstance(a, dict) and a.get("status") == "geparkt"
    }


def lifecycle(sit: dict, fl: dict | None, *, geparkt_vorher: set[str]) -> str:
    """Ergebnis des Zugs einordnen. '' wenn der Fluss nichts uebernommen hat."""
    if fl is None:
        return ""
    if fl.get("error"):
        return "failed"
    if fl.get("transfer") or fl.get("hangup"):
        return "done"
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    phase = _s(s.get("phase"))
    if phase in {"gebucht", "fertig"}:
        return "done"
    if _geparkte_ids(sit) - geparkt_vorher:
        return "parked"
    return "active"


def _ledger_schreiben(sit: dict, typ: str, status: str) -> None:
    if not status:
        return
    eintrag = {"typ": typ or "?", "status": status}
    ledger = sit.setdefault("taskLedger", [])
    if not (ledger and ledger[-1] == eintrag):
        ledger.append(eintrag)
    sit["taskLedger"] = ledger[-12:]


def zug(sit: dict, gesagt: str, melde=None) -> dict | None:
    """Transparenter Adapter vor flow.zug.

    Gibt EXAKT das Ergebnis von flow.zug zurueck (gleiche Antwort, gleiche
    Werkzeugaufrufe). Zusaetzlich: Task-Typ + Lifecycle ins Ledger. Bei
    TASK_ADAPTERS=0 wird flow.zug direkt durchgereicht.
    """
    if not enabled():
        return flow.zug(sit, gesagt, melde)
    typ = aktueller_typ(sit)
    geparkt_vorher = _geparkte_ids(sit)
    fl = flow.zug(sit, gesagt, melde)
    if not typ:
        typ = aktueller_typ(sit)
    _ledger_schreiben(sit, typ, lifecycle(sit, fl, geparkt_vorher=geparkt_vorher))
    return fl
