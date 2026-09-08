"""Fachtemplate + Praxis- + Patient-Layer fuer jede Telefon-Sitzung.

Das Modul ist absichtlich rein lesend: Es klassifiziert den vorhandenen
Besuchsgrund-Katalog und baut daraus eine kleine, JSON-taugliche
Schichtenbeschreibung. Es aendert weder Prompt noch Flow. Dadurch kann das
Grundgeruest zuerst im Live-Verkehr beobachtet werden, bevor ein Fachtemplate
Gesprächsentscheidungen beeinflusst.

Prioritaet:
    Kern-Sicherheit > Fachtemplate > Praxis-Layer > Patientenkontext > LLM.

Keine clientIds, Praxisnamen oder Preise im Fachkern. Eine Praxis kann das
Template spaeter explizit ueber ``fachtemplate``/``fachgebiet`` setzen; sonst
wird es konservativ aus ihrem echten Motivkatalog erkannt.
"""

from __future__ import annotations

import re
from typing import Any

VERSION = 1

_KERN_FAEHIGKEITEN = (
    "anliegen_stapeln",
    "themen_parken",
    "werkzeuge_verifizieren",
    "patientendossier",
    "frist_erstton",
    "schleifen_begrenzen",
)

_KERN_SCHUTZ = (
    "Keine Erledigt-Behauptung ohne erfolgreiches Werkzeug.",
    "Keine Patientenfakten vor bestaetigter Identitaet sprechen.",
    "Keine Preise, Termine oder Praxisregeln erfinden.",
)

_TEMPLATES: dict[str, dict[str, Any]] = {
    "allgemein": {
        "name": "Allgemeine Praxis",
        "faehigkeiten": (),
        "empfehlungen": ("verlauf",),
        "schutz": (),
    },
    "zahnmedizin": {
        "name": "Zahnmedizin",
        "faehigkeiten": (
            "zahn_besuchsgrund",
            "pzr",
            "bleaching",
            "zahn_verlauf",
        ),
        "empfehlungen": ("verlauf", "pzr"),
        "schutz": (
            "Keine Diagnose oder individuelle Heilaussage.",
            "Akut- und Schmerz-Anliegen haben Vorrang vor Zusatzangeboten.",
        ),
    },
    "gynaekologie": {
        "name": "Gynaekologie",
        "faehigkeiten": (
            "gyn_besuchsgrund",
            "gyn_verlauf",
        ),
        "empfehlungen": ("verlauf",),
        "schutz": (
            "Keine Diagnose oder individuelle Heilaussage.",
            "Vorsorge nur aus Praxisregel oder Patientendossier ableiten.",
        ),
    },
    "orthopaedie": {
        "name": "Orthopaedie",
        "faehigkeiten": (
            "ortho_besuchsgrund",
            "ortho_verlauf",
        ),
        "empfehlungen": ("verlauf",),
        "schutz": (
            "Keine Diagnose oder individuelle Heilaussage.",
            "Akute Verletzungen haben Vorrang vor Zusatzangeboten.",
        ),
    },
    "dermatologie": {
        "name": "Dermatologie",
        "faehigkeiten": (
            "derma_besuchsgrund",
            "derma_verlauf",
        ),
        "empfehlungen": ("verlauf",),
        "schutz": (
            "Keine Diagnose oder individuelle Heilaussage.",
            "Vorsorge nur aus Praxisregel oder Patientendossier ableiten.",
        ),
    },
}

_ALIASE = {
    "allgemein": "allgemein",
    "arztpraxis": "allgemein",
    "zahn": "zahnmedizin",
    "zahnarzt": "zahnmedizin",
    "zahnmedizin": "zahnmedizin",
    "dental": "zahnmedizin",
    "gyn": "gynaekologie",
    "gynaekologie": "gynaekologie",
    "gynäkologie": "gynaekologie",
    "frauenarzt": "gynaekologie",
    "orthopaedie": "orthopaedie",
    "orthopädie": "orthopaedie",
    "ortho": "orthopaedie",
    "dermatologie": "dermatologie",
    "hautarzt": "dermatologie",
    "derma": "dermatologie",
}

_MARKER = {
    "gynaekologie": re.compile(
        r"gyn(?:ä|ae)kolog|frauenarzt|schwanger|kinderwunsch|wechseljahr|"
        r"kolposkop|abstrich|verh(?:ü|ue)tung|spirale",
        re.I,
    ),
    "orthopaedie": re.compile(
        r"orthop(?:ä|ae)d|wirbels(?:ä|ae)ule|bandscheib|arthrose|"
        r"knie|h(?:ü|ue)fte|schulter|gelenk|r(?:ü|ue)cken",
        re.I,
    ),
    "dermatologie": re.compile(
        r"dermatolog|hautarzt|hautkrebs|muttermal|neurodermit|"
        r"psoriasis|ekzem|akne",
        re.I,
    ),
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _tenant(quelle: Any) -> dict[str, Any]:
    if not isinstance(quelle, dict):
        return {}
    t = quelle.get("tenant")
    return t if isinstance(t, dict) else quelle


def _katalog(quelle: Any) -> list[dict[str, Any]]:
    if isinstance(quelle, list):
        return [x for x in quelle if isinstance(x, dict)]
    if not isinstance(quelle, dict):
        return []
    kat = quelle.get("motivKatalog")
    if isinstance(kat, list) and kat:
        return [x for x in kat if isinstance(x, dict)]
    t = _tenant(quelle)
    kat = t.get("visitMotives")
    return [x for x in kat if isinstance(x, dict)] if isinstance(kat, list) else []


def _motivtext(katalog: list[dict[str, Any]]) -> str:
    teile: list[str] = []
    for vm in katalog:
        for key in (
            "name", "nameForPatient", "patientInfo",
            "landingPageHeadline", "landingPageDescription",
        ):
            text = _s(vm.get(key))
            if text:
                teile.append(text)
    return " ".join(teile)


def _alias(v: Any) -> str:
    roh = _s(v).casefold()
    if not roh:
        return ""
    kompakt = re.sub(r"[^a-zäöüß]+", "", roh)
    direkt = _ALIASE.get(roh) or _ALIASE.get(kompakt)
    if direkt:
        return direkt
    if re.search(r"zahn|dental|dentist", roh):
        return "zahnmedizin"
    if re.search(r"gyn(?:ä|ae)kolog|frauenarzt", roh):
        return "gynaekologie"
    if re.search(r"orthop(?:ä|ae)d", roh):
        return "orthopaedie"
    if re.search(r"dermatolog|hautarzt", roh):
        return "dermatologie"
    return ""


def fach_id(quelle: Any) -> str:
    """Fach-ID: expliziter Praxiswert gewinnt, sonst konservativer Katalog."""
    tenant = _tenant(quelle)
    for key in ("fachtemplate", "fachgebiet", "specialty", "speciality"):
        explizit = _alias(tenant.get(key))
        if explizit:
            return explizit

    katalog = _katalog(quelle)
    if not katalog:
        return "allgemein"

    # Bestehende, strenge Dental-Erkennung bleibt die Wahrheit fuer Zahn.
    from kern import motive
    if motive.ist_zahn(katalog):
        return "zahnmedizin"

    text = _motivtext(katalog)
    for fid in ("gynaekologie", "orthopaedie", "dermatologie"):
        if _MARKER[fid].search(text):
            return fid
    return "allgemein"


def template(quelle: Any) -> dict[str, Any]:
    """Unveraenderliche Template-Daten als frisches JSON-Dict."""
    fid = fach_id(quelle)
    roh = _TEMPLATES.get(fid) or _TEMPLATES["allgemein"]
    return {
        "id": fid,
        "name": roh["name"],
        "faehigkeiten": list(_KERN_FAEHIGKEITEN) + list(roh["faehigkeiten"]),
        "empfehlungen": list(roh["empfehlungen"]),
        "schutz": list(_KERN_SCHUTZ) + list(roh["schutz"]),
    }


def praxis_layer(tenant: dict[str, Any] | None) -> dict[str, Any]:
    """Individueller Layer ohne Patienten- oder Prompt-Inhalte."""
    t = tenant if isinstance(tenant, dict) else {}
    cals = t.get("calendars") if isinstance(t.get("calendars"), list) else []
    vms = t.get("visitMotives") if isinstance(t.get("visitMotives"), list) else []
    return {
        "quelle": _s(t.get("_quelle")) or "datei",
        "clientId": _s(t.get("clientId")),
        "locationId": _s(t.get("locationId")),
        "praxis": _s(t.get("praxisName")),
        "kalender": len(cals),
        "besuchsgruende": len(vms),
        "hatDbPrompt": bool(str(t.get("dbPrompt") or "").strip()),
        "hatWeiterleitung": bool(t.get("weiterleitungen")),
    }


def patient_layer(sit: dict[str, Any] | None) -> dict[str, Any]:
    """Nur Statussignale; vor Identitaetsbestaetigung keine PHI spiegeln."""
    sit = sit if isinstance(sit, dict) else {}
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    bestaetigt = bool(
        s.get("anruferCheck") == "ja"
        or (
            s.get("bekannt")
            and (s.get("patientId") or (s.get("nachname") and s.get("telefonOk")))
        )
    )
    erkannt = bool(sit.get("anrufer") or s.get("patientId") or sit.get("patient"))
    if bestaetigt:
        identitaet = "bestaetigt"
    elif erkannt:
        identitaet = "erkannt_unbestaetigt"
    else:
        identitaet = "anonym"
    return {
        "identitaet": identitaet,
        "hatKartei": bool(s.get("patientId") or (sit.get("patient") or {}).get("id")),
        "hatLetztenBesuch": bool(bestaetigt and s.get("letzterBesuch")),
        "hatPraxisgedaechtnis": bool(bestaetigt and sit.get("gedaechtnis")),
        "offeneVorgaenge": len(sit.get("gedaechtnisOffen") or []) if bestaetigt else 0,
    }


def schichten(sit: dict[str, Any]) -> dict[str, Any]:
    """Alle Layer einer Sitzung, rein aus bereits vorhandenen Daten."""
    t = template(sit)
    return {
        "version": VERSION,
        "reihenfolge": ["kern", "fach", "praxis", "patient", "llm"],
        "kern": {
            "id": "telefonki",
            "faehigkeiten": list(_KERN_FAEHIGKEITEN),
            "schutz": list(_KERN_SCHUTZ),
        },
        "fach": t,
        "praxis": praxis_layer(_tenant(sit)),
        "patient": patient_layer(sit),
    }


def aktualisieren(sit: dict[str, Any]) -> dict[str, Any]:
    """Layer-Snapshot in der Sitzung aktualisieren und zurueckgeben."""
    lagen = schichten(sit)
    sit["layers"] = lagen
    return lagen
