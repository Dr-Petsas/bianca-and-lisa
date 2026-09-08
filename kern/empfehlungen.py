"""Fachneutrale Next-Best-Actions aus verifizierten Sitzungsfakten.

Das LLM erfindet keine Angebote. Dieses Modul liefert nur strukturierte,
nachvollziehbare Kandidaten; Dossier/Flow entscheiden weiterhin wie bisher,
ob und wann ein bestehender Takt gesprochen wird. Damit ist die erste Stufe
verhaltenskompatibel und spaeter fuer weitere Fachtemplates erweiterbar.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from kern import fachprofil, motive

_PHASE_DICHT = {"angebot", "bestaetigen", "gebucht", "fertig"}
_PZR_RE = re.compile(r"zahnreinigung|prophylaxe|\bpzr\b", re.I)
_AKUT_RE = re.compile(r"schmerz|notfall|\bweh\b|akut", re.I)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _tage(iso: str) -> int:
    tag = _s(iso)[:10]
    if not tag:
        return -1
    try:
        datum = datetime.strptime(tag, "%Y-%m-%d").date()
    except ValueError:
        return -1
    return (datetime.now().date() - datum).days


def _kandidat(
    *,
    eid: str,
    art: str,
    prioritaet: int,
    quelle: str,
    grund: str,
    fach: str,
    legacy_takt: str = "",
) -> dict[str, Any]:
    return {
        "id": eid,
        "art": art,
        "status": "geeignet",
        "prioritaet": prioritaet,
        "quelle": quelle,
        "grund": grund,
        "fach": fach,
        "legacyTakt": legacy_takt,
    }


def kandidaten(sit: dict[str, Any], fakten: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Geeignete Aktionen, nur aus vorhandenem Katalog/Kartei/MAS.

    Die Reihenfolge ist stabil und fachlich priorisiert. Neue Fachangebote
    duerfen spaeter ausschliesslich hier beziehungsweise in Template-Daten
    entstehen, nie spontan im Sprachmodell.
    """
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    d = fakten if isinstance(fakten, dict) else {}
    template = fachprofil.template(sit)
    fach = str(template["id"])
    erlaubt = set(template.get("empfehlungen") or [])
    gesagt = {str(x) for x in (d.get("gesagt") or [])}
    phase = _s(s.get("phase"))
    modus = _s(s.get("modus"))
    grund = _s(s.get("grund"))
    letzter_grund = _s(d.get("letzterGrund") or s.get("letzterGrund"))
    letzter_besuch = _s(d.get("letzterBesuch") or s.get("letzterBesuch"))
    bekannt = bool(s.get("bekannt") or s.get("anruferCheck") == "ja")
    akut = bool(_AKUT_RE.search(grund))

    out: list[dict[str, Any]] = []
    if (
        "verlauf" in erlaubt
        and "verlauf" not in gesagt
        and bekannt
        and letzter_grund
        and modus == "buchen"
        and phase not in _PHASE_DICHT
        and not akut
        and _tage(letzter_besuch) > 7
    ):
        out.append(_kandidat(
            eid="verlauf",
            art="nachsorge",
            prioritaet=80,
            quelle="patientenkartei",
            grund="frueherer Besuch ist bekannt",
            fach=fach,
            legacy_takt="verlauf",
        ))

    if (
        "pzr" in erlaubt
        and "pzr" not in gesagt
        and modus == "buchen"
        and grund
        and phase not in _PHASE_DICHT
        and not akut
        and not _PZR_RE.search(f"{grund} {_s(s.get('motivName'))}")
        and motive.fuehrt_pzr(sit)
    ):
        out.append(_kandidat(
            eid="pzr",
            art="zusatzangebot",
            prioritaet=40,
            quelle="fachtemplate+besuchsgrundkatalog",
            grund="Praxis fuehrt PZR und der aktuelle Termin ist keine PZR",
            fach=fach,
            legacy_takt="pzr",
        ))

    if (
        sit.get("gedaechtnisOffen")
        and fachprofil.patient_layer(sit).get("identitaet") == "bestaetigt"
    ):
        out.append(_kandidat(
            eid="offener_vorgang",
            art="kontext",
            prioritaet=100,
            quelle="mas",
            grund="offener Praxisvorgang zum bestaetigten Patienten",
            fach=fach,
        ))

    return sorted(out, key=lambda x: (-int(x["prioritaet"]), str(x["id"])))


def legacy_takte(sit: dict[str, Any], fakten: dict[str, Any] | None = None) -> list[str]:
    """Kompatibilitaetsbruecke fuer das heutige Dossier."""
    return [
        str(k["legacyTakt"])
        for k in kandidaten(sit, fakten)
        if k.get("legacyTakt")
    ]
