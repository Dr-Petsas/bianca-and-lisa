"""Behandler telefonisch sperren (W-BEHANDLER-SPERRE, Chef 13.09.2026).

Chef (wörtlich): "Dr. Nikolaou soll vorerst raus aus der telefonischen
Buchung." Ein gesperrter Behandler verschwindet aus ALLEM, was Bianca am
Telefon anbietet oder bucht — aber sein Name bleibt BEKANNT: wer ihn nennt,
bekommt eine ehrliche Ansage plus die freien Behandler, statt dass der Wunsch
still im Default-Kalender landet (Live-Probe 13.09.: Bianca versprach Termine
"bei Doktor Nikolaou" und buchte dann bei Doktor Petsas — eine falsche Buchung
mit falscher Ansage).

Die Sperre ist MANDANTENSCHARF und steht in der Tenant-Datei
(``telefonGesperrteBehandler``: Liste von Namensteilen, z. B. ["Nikolaou"]).
Ohne Eintrag verhaelt sich alles byte-identisch wie vorher. Sie wird an EINER
Stelle angewendet — ``anwenden(tenant)`` in kern/agentprofil (CF-Pfad und
Datei-Rueckfall), also fuer jeden Anruf und jede Dock-Sitzung gleich:

- ``tenant["calendars"]`` verliert die gesperrten Kalender (Arztwahl, Slot-
  Suche, Buchung, Prompt-Behandlerzeile sehen ihn nicht mehr);
- zeigt ``defaultCalendarId`` auf einen gesperrten Kalender, rueckt der erste
  freie nach (nie ein gesperrter Default);
- ``tenant["_gesperrteKalender"]`` haelt die entfernten Eintraege (id/name),
  damit arzt.deute den Namen weiter ERKENNT ("gesperrt") und
  arzt.letzter_behandler einen alten Termin bei ihm richtig zuordnet.

Nichts hier bucht, nichts hier spricht — es liefert nur Fakten und den
Hinweistext, den flow._quittung ausspricht.
"""
from __future__ import annotations

import re
from typing import Any


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^\wäöüÄÖÜß]+", _s(name).lower()) if len(t) >= 3}


def gesperrte_namen(tenant: dict | None) -> list[str]:
    """Konfigurierte Sperr-Namensteile des Mandanten (leer = keine Sperre)."""
    roh = (tenant or {}).get("telefonGesperrteBehandler")
    if not isinstance(roh, list):
        return []
    out: list[str] = []
    for n in roh:
        n = _s(n)
        if n and n not in out:
            out.append(n)
    return out


def ist_gesperrt(tenant: dict | None, kalender_name: str) -> bool:
    """Trifft ein Sperr-Namensteil den Kalendernamen? Wortweise, nie Substring —
    "Niko" sperrt nicht "Nikolaou", "Nikolaou" sperrt "Doktor Georgios Nikolaou"."""
    namen = gesperrte_namen(tenant)
    if not namen or not _s(kalender_name):
        return False
    kal = _tokens(kalender_name)
    for n in namen:
        st = _tokens(n)
        if st and st <= kal:
            return True
    return False


def gesperrte_kalender(tenant: dict | None) -> list[dict[str, str]]:
    """Die beim Anwenden entfernten Kalender (id/name) — fuer arzt.deute und
    letzter_behandler. Leer ohne Sperre."""
    roh = (tenant or {}).get("_gesperrteKalender")
    if not isinstance(roh, list):
        return []
    return [dict(c) for c in roh if isinstance(c, dict) and _s(c.get("name"))]


def anwenden(tenant: dict | None) -> dict | None:
    """Sperre auf einen fertig geladenen Mandanten legen (idempotent).

    Entfernt gesperrte Kalender aus ``calendars``, rueckt den Default nach und
    merkt die entfernten Eintraege unter ``_gesperrteKalender``. Ohne Sperr-
    Liste kehrt der Mandant unveraendert zurueck."""
    if not isinstance(tenant, dict):
        return tenant
    if not gesperrte_namen(tenant):
        return tenant
    cals = tenant.get("calendars") if isinstance(tenant.get("calendars"), list) else []
    frei: list[dict] = []
    weg: list[dict[str, str]] = list(gesperrte_kalender(tenant))
    for c in cals:
        if not isinstance(c, dict):
            continue
        if ist_gesperrt(tenant, _s(c.get("name"))):
            eintrag = {"id": _s(c.get("id")), "name": _s(c.get("name"))}
            if eintrag not in weg:
                weg.append(eintrag)
            continue
        frei.append(c)
    if weg:
        tenant["_gesperrteKalender"] = weg
    if len(frei) != len(cals):
        tenant["calendars"] = frei
    dflt = _s(tenant.get("defaultCalendarId"))
    if dflt and any(_s(w.get("id")) == dflt for w in weg):
        # Der Default darf nie ein gesperrter Kalender sein — sonst liefe
        # "egal"/"weiss nicht" (arzt_default) still in die Sperre.
        ersatz = next((_s(c.get("id")) for c in frei if _s(c.get("id"))), "")
        if ersatz:
            tenant["defaultCalendarId"] = ersatz
        else:
            tenant.pop("defaultCalendarId", None)
    return tenant


def treffer(tenant: dict | None, text: str) -> str:
    """Nennt der Text einen gesperrten Behandler? Liefert den Kalendernamen
    (oder den Sperr-Namensteil, wenn der Kalender nicht bekannt ist), sonst ""."""
    namen = gesperrte_namen(tenant)
    if not namen or not _s(text):
        return ""
    toks = _tokens(text)
    if not toks:
        return ""
    for n in namen:
        st = _tokens(n)
        if st and st <= toks:
            for k in gesperrte_kalender(tenant):
                if ist_gesperrt({"telefonGesperrteBehandler": [n]}, _s(k.get("name"))):
                    return _s(k.get("name"))
            return n
    return ""


def hinweis(gesprochen: str) -> str:
    """Ehrliche Ansage fuer einen gesperrten Behandler — OHNE Frage (die
    stellt gehirn.naechste_frage anschliessend mit den freien Behandlern).
    ``gesprochen`` ist die fertige Sprechform ("Doktor Nikolaou")."""
    g = _s(gesprochen)
    if not g:
        return ""
    return f"Termine bei {g} kann ich telefonisch im Moment leider nicht vergeben."
