"""Veroeffentlichte Praxis-Layer (``DialogPolicyV1``) ablegen und lesen.

Chef 19.09.2026: "aber so dass die spezifitäten jeder Praxis erhalten bleiben.
ausserdem hast du mir nicht gesagt wo ich die praxis layer einstelle."

Die Maske im Studio konnte die Policy bisher nur PROBIEREN — jeder Neustart
warf sie weg. Hier liegt der Speicherweg: ein veroeffentlichter Vertrag landet
als eigene Datei unter ``.data/dialogpolicy/<mandant>.json`` und wird von
``tenants.laden()`` in das Mandanten-Dict als ``dialogPolicy`` gelegt. Von dort
liest ``bianca/controller/policy.aus_tenant`` — also genau der produktive Weg.

Warum eine eigene Datei und nicht ``tenants/<mandant>.json``:

1. **Der Ordner ist auf pickadoc1 read-only gemountet** (``./tenants:ro``) —
   ein Schreibversuch aus dem Container scheitert. ``.data`` ist ein Volume.
2. **Die kuratierten Mandanten-Dateien bleiben Handarbeit.** Sprechformen,
   DIDs, Stimmen und Hotwords gehoeren dem Menschen; ein Formular soll sie
   nicht umschreiben koennen.
3. **Rueckweg ist ein Dateiloeschen.** Ohne Ablage-Datei verhaelt sich der
   Mandant byte-identisch wie vor dem 19.09.2026 (Legacy-Projektion aus den
   bekannten Flags).

Die Datei traegt NUR den Vertrag plus Herkunft (wer, wann). Sie wird beim
Lesen erneut durch ``dialog_policy.parse`` geschickt: eine von Hand verbogene
Datei kann den Kern nie in einen unmoeglichen Zustand bringen — im Zweifel
gilt der sichere Default, und die Warnungen stehen in der Maske.

Notaus: ``DIALOG_POLICY_ABLAGE=0`` => keine Datei wird gelesen (Schreiben
antwortet ehrlich mit Fehler).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from kern.config import DATA_DIR

ORDNER = DATA_DIR / "dialogpolicy"
# Mandanten-Kennungen sind Dateinamen — nie etwas anderes durchlassen
# (ein "../" in der Kennung schriebe sonst ausserhalb des Ordners).
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$", re.I)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def an() -> bool:
    """Notaus ``DIALOG_POLICY_ABLAGE=0``."""
    return _s(os.getenv("DIALOG_POLICY_ABLAGE", "1")).lower() not in (
        "0", "off", "false", "nein",
    )


def _id_ok(tenant_id: str) -> str:
    kennung = _s(tenant_id)
    return kennung if _ID_RE.match(kennung) else ""


def pfad(tenant_id: str) -> Path | None:
    kennung = _id_ok(tenant_id)
    return (ORDNER / f"{kennung}.json") if kennung else None


def lesen(tenant_id: str) -> dict[str, Any] | None:
    """Veroeffentlichter Eintrag (``policy`` + Herkunft), oder ``None``."""
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
    """Nur der Vertrag — das, was als ``tenant["dialogPolicy"]`` gilt."""
    eintrag = lesen(tenant_id)
    return dict(eintrag["policy"]) if eintrag else None


def schreiben(tenant_id: str, vertrag: dict[str, Any], *,
              wer: str = "superuser", notiz: str = "") -> dict[str, Any]:
    """Vertrag veroeffentlichen. Rueckgabe: ``{ok, pfad|fehler, revision}``.

    Der Vertrag muss bereits geparst und gueltig sein (die Maske schickt die
    ``as_dict()``-Form) — hier wird nur noch abgelegt.
    """
    if not an():
        return {"ok": False, "fehler": "Ablage ist per DIALOG_POLICY_ABLAGE=0 abgeschaltet."}
    p = pfad(tenant_id)
    if p is None:
        return {"ok": False, "fehler": f"Unzulaessige Mandanten-Kennung: {tenant_id!r}"}
    if not isinstance(vertrag, dict) or not vertrag:
        return {"ok": False, "fehler": "Leerer Vertrag — es gibt nichts zu veroeffentlichen."}
    eintrag = {
        "tenant": _id_ok(tenant_id),
        "policy": vertrag,
        "revision": vertrag.get("revision"),
        "wer": _s(wer) or "superuser",
        "notiz": _s(notiz)[:200],
        "zeit": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        ORDNER.mkdir(parents=True, exist_ok=True)
        # Atomar schreiben: ein halb geschriebener Vertrag wuerde beim naechsten
        # Anruf als kaputt gelesen (dann sicherer Default) — vermeidbar.
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=ORDNER, delete=False, suffix=".tmp",
        ) as fh:
            json.dump(eintrag, fh, ensure_ascii=False, indent=2)
            tmp = Path(fh.name)
        tmp.replace(p)
    except OSError as exc:
        return {"ok": False, "fehler": f"Schreiben fehlgeschlagen: {exc}"}
    return {"ok": True, "pfad": str(p), "revision": eintrag["revision"],
            "zeit": eintrag["zeit"]}


def loeschen(tenant_id: str) -> dict[str, Any]:
    """Veroeffentlichung zuruecknehmen — der Mandant laeuft wieder auf Legacy."""
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
    """Uebersicht fuer die Maske: welcher Mandant laeuft auf welchem Vertrag."""
    if not an() or not ORDNER.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(ORDNER.glob("*.json")):
        eintrag = lesen(p.stem)
        if eintrag is None:
            continue
        out.append({
            "tenant": p.stem,
            "revision": eintrag.get("revision"),
            "wer": eintrag.get("wer"),
            "zeit": eintrag.get("zeit"),
            "notiz": eintrag.get("notiz"),
        })
    return out


def anreichern(tenant: dict[str, Any], tenant_id: str = "") -> dict[str, Any]:
    """Veroeffentlichten Vertrag in ein Mandanten-Dict legen (in-place).

    Ein Vertrag, der schon am Mandanten steht (Datei/DB), wird NICHT
    ueberschrieben — die Ablage ist der Weg fuer Praxen, die keinen tragen.
    """
    if not isinstance(tenant, dict):
        return tenant
    if isinstance(tenant.get("dialogPolicy"), dict) and tenant["dialogPolicy"]:
        return tenant
    kennung = _s(tenant_id) or _s(tenant.get("_id")) or _s(tenant.get("id"))
    vertrag = policy(kennung)
    if vertrag:
        tenant["dialogPolicy"] = vertrag
        tenant["_dialogPolicyQuelle"] = "ablage"
    return tenant


__all__ = ["an", "alle", "anreichern", "loeschen", "lesen", "pfad", "policy",
           "schreiben", "ORDNER"]
