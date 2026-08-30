"""Kampagne Stufe 1 — Einstellungen, kein Patient.

Chef 30.08.2026: vor der Empfängerliste den Telefon-Auftrag zur Kampagne
falten. Fakten stehen auf der Kampagnenseite (Name, Terminfenster,
Besuchsgrund, Behandler, Begrüßung). Nichts erfinden. Kein Müller, keine
Kartei, kein MAS. Fehlt etwas, das die Seite nicht trägt, geht die Frage
an den Chef — nicht ins Mikro.
"""

from __future__ import annotations

import re
from typing import Any

_DEFAULT_PROMPT = (
    "freundlich erinnern, slots im zeitraum anbieten, termin buchen"
)
_MOTIV_RE = re.compile(
    r"recall|kontrolle|nachsorge|prophylaxe|zahnreinigung|\bpzr\b|"
    r"roentgen|röntgen|implantat|recall",
    re.I,
)
def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _norm(text: str) -> str:
    return re.sub(r"[^a-zäöüß0-9]+", " ", (text or "").lower()).strip()


def _kampagne(roh: Any) -> dict[str, str]:
    k = roh if isinstance(roh, dict) else {}
    von = _s(k.get("zeitraumVon") or k.get("startDate"))[:10]
    bis = _s(k.get("zeitraumBis") or k.get("endDate"))[:10]
    zeitraum = _s(k.get("zeitraum"))
    if not zeitraum and (von or bis):
        zeitraum = f"{von or '—'} – {bis or '—'}"
    return {
        "name": _s(k.get("name")),
        "praxis": _s(k.get("praxis")),
        "behandler": _s(k.get("behandler") or k.get("calendarName")),
        "calendarId": _s(k.get("calendarId")),
        "motiv": _s(k.get("motiv") or k.get("visitMotiveName") or k.get("termingrund")),
        "visitMotiveId": _s(k.get("visitMotiveId")),
        "zeitraumVon": von,
        "zeitraumBis": bis,
        "zeitraum": zeitraum,
        "greeting": _s(k.get("greeting")),
        "kiName": _s(k.get("kiName")),
        "sprache": _s(k.get("sprache") or k.get("language")),
        "dauerMin": _s(k.get("dauerMin") or k.get("visitDuration")),
    }


def _antworten(roh: Any) -> dict[str, str]:
    if isinstance(roh, dict):
        return {str(k): _s(v) for k, v in roh.items() if _s(v)}
    if isinstance(roh, list):
        out: dict[str, str] = {}
        for item in roh:
            if not isinstance(item, dict):
                continue
            kid = _s(item.get("id") or item.get("key"))
            txt = _s(item.get("text") or item.get("antwort"))
            if kid and txt:
                out[kid] = txt
        return out
    return {}


def _hat_fenster(k: dict[str, str]) -> bool:
    return bool(k["zeitraumVon"] or k["zeitraumBis"] or (
        k["zeitraum"] and "—" not in k["zeitraum"]
    ))


def _prompt_schwach(auftrag: str) -> bool:
    n = _norm(auftrag)
    if len(n) < 28:
        return True
    return _DEFAULT_PROMPT in n


def _fakten(k: dict[str, str], *, auftrag: str) -> list[str]:
    zeilen: list[str] = []
    if k["name"]:
        zeilen.append(f"Kampagne: {k['name']}")
    if k["praxis"]:
        zeilen.append(f"Praxis: {k['praxis']}")
    if k["motiv"]:
        zeilen.append(f"Besuchsgrund: {k['motiv']}")
    if k["behandler"]:
        zeilen.append(f"Behandler: {k['behandler']}")
    else:
        zeilen.append("Behandler: alle (wie auf der Kampagnenseite).")
    if _hat_fenster(k):
        zeilen.append(
            f"Terminfenster: {k['zeitraum']}. "
            "Später nur in diesem Fenster buchen, nichts außerhalb anbieten."
        )
    if k["dauerMin"]:
        zeilen.append(f"Termindauer: {k['dauerMin']} Minuten.")
    if k["greeting"]:
        zeilen.append(f"Begrüßung laut Seite: {k['greeting']}")
    if k["kiName"]:
        zeilen.append(f"KI-Name auf der Seite: {k['kiName']}")
    if _prompt_schwach(auftrag) and _hat_fenster(k):
        zeilen.append(
            "Der Telefon-Prompt ist noch die Standardformel — "
            "Motiv, Zeitraum und Behandler kommen von der Kampagnenseite."
        )
    return zeilen


def _fragen(auftrag: str, k: dict[str, str], antworten: dict[str, str]) -> list[dict[str, str]]:
    """Nur was die Seite nicht schon trägt. Kein Fenster, wenn Daten da sind."""
    out: list[dict[str, str]] = []
    if not _hat_fenster(k) and not antworten.get("zeitraum"):
        out.append({
            "id": "zeitraum",
            "frage": "In welchem Zeitraum sollen die Termine liegen?",
            "hinweis": "Auf der Seite fehlen noch Von/Bis.",
        })
    hat_motiv = bool(k["motiv"]) or bool(_MOTIV_RE.search(auftrag)) or bool(
        _MOTIV_RE.search(k["name"]))
    if not hat_motiv and not antworten.get("motiv"):
        out.append({
            "id": "motiv",
            "frage": "Worum geht es in dieser Kampagne (Besuchsgrund)?",
            "hinweis": "Kein Grund auf der Seite, nichts erfinden (kein PZR aus dem Hut).",
        })
    return out


def _plan(auftrag: str, *, fakten: list[str], antworten: dict[str, str],
          fragen: list[dict[str, str]]) -> str:
    teile = [
        _s(auftrag) or "Anrufen und Termin im Kampagnenfenster anbieten.",
        "",
        "Gesprächsplan Kampagne (nicht vorlesen, nichts erfinden):",
        "1) Eingang wie auf der Seite: wer, Praxis, dann das Thema.",
        "2) Ziel: einen Termin IM Terminfenster der Kampagne vereinbaren.",
        "3) Nur Fakten von der Seite und aus den Chef-Antworten. Leere Felder bleiben leer.",
    ]
    if fakten:
        teile.append("Von der Kampagnenseite:")
        teile.extend(f"- {z}" for z in fakten)
    if antworten:
        teile.append("Chef hat ergänzt:")
        teile.extend(f"- {k}: {v}" for k, v in antworten.items())
    if fragen:
        teile.append("Offen (Chef, nicht den Angerufenen fragen):")
        teile.extend(f"- {f['frage']}" for f in fragen)
    teile.append(
        "[Regie: Keine Preise, Befunde oder Gründe erfinden. "
        "Keine Termine außerhalb des Fensters anbieten. "
        "Probe-Gespräch: Kalender nicht schreiben.]"
    )
    return "\n".join(teile)


def probe_name(k: dict[str, str] | None = None) -> str:
    name = _s((k or {}).get("name"))
    if name:
        return f"Probe {name}"[:80]
    return "Probe Recall"


def vertiefen(auftrag: str, *, kampagne: dict | None = None,
              antworten: dict | list | None = None) -> dict[str, Any]:
    """Stufe 1. auftrag bleibt der Chef-Text; briefing ist der Plan."""
    auftrag = _s(auftrag)
    k = _kampagne(kampagne)
    ant = _antworten(antworten)
    if not auftrag and not k["name"] and not k["motiv"] and not _hat_fenster(k):
        return {
            "ok": False,
            "error": "auftrag fehlt",
            "auftrag": "",
            "briefing": "",
            "unterlage": [],
            "fragen": [],
            "luecken": [],
            "bereit": False,
            "probeName": probe_name(k),
            "kampagne": k,
        }
    if not auftrag:
        auftrag = "Freundlich anrufen und einen Termin im Kampagnenfenster vereinbaren."
    fakten = _fakten(k, auftrag=auftrag)
    fragen = _fragen(auftrag, k, ant)
    # Chef-Antworten werden Fakten, nicht nochmal Frage.
    for kid, text in ant.items():
        if kid == "zeitraum":
            fakten.append(f"Terminfenster (Chef): {text}. Nur darin buchen.")
        elif kid == "motiv":
            fakten.append(f"Besuchsgrund (Chef): {text}")
        else:
            fakten.append(f"{kid}: {text}")
    briefing = _plan(auftrag, fakten=fakten, antworten=ant, fragen=fragen)
    return {
        "ok": True,
        "auftrag": auftrag,
        "briefing": briefing,
        "unterlage": fakten,
        "fragen": fragen,
        "luecken": [f["frage"] for f in fragen],
        "bereit": not fragen,
        "probeName": probe_name(k),
        "kampagne": k,
    }


def _luecken_kampagne(luecken: list[str], k: dict[str, str]) -> list[str]:
    """Fenster steht auf der Seite. PZR nicht erfinden, wenn das Motiv keins ist."""
    out: list[str] = []
    motiv = (k.get("motiv") or "").lower()
    hat_pzr = "pzr" in motiv or "zahnreinigung" in motiv or "prophylaxe" in motiv
    for x in luecken:
        xl = x.lower()
        if "zeitraum" in xl or "terminfenster" in xl or "von/bis" in xl:
            continue
        if x.startswith("Recall ohne Historie"):
            if hat_pzr:
                out.append(x)
            else:
                out.append(
                    "Kein Besuch in der Akte: Was sagen, wenn „ich war doch erst da“ kommt?"
                )
            continue
        out.append(x)
    return out


def sammeln_patient(auftrag: str, *, kampagne: dict | None = None,
                    patient: dict | None = None, tenant_id: str = "",
                    briefing: str = "") -> dict[str, Any]:
    """Stufe 2: Kampagnenauftrag plus dieser Patient. Nichts erfinden."""
    from lisa import vorbereitung

    auftrag = _s(auftrag)
    k = _kampagne(kampagne)
    pat = patient if isinstance(patient, dict) else {}
    if not auftrag:
        return {
            "ok": False, "error": "auftrag fehlt", "auftrag": "",
            "patientId": _s(pat.get("id")), "name": vorbereitung._name(pat),
            "briefing": "", "unterlage": [], "einwaende": [], "luecken": [],
            "bereit": False,
        }
    raw = vorbereitung.sammeln(auftrag, tenant_id=tenant_id, patient=pat)
    seite = _fakten(k, auftrag=auftrag)
    if _s(briefing):
        seite.append("Gesprächsplan der Kampagne (Stufe 1) gilt — nicht überschreiben.")
    unterlage = seite + list(raw.get("unterlage") or [])
    einwaende = list(raw.get("einwaende") or [])
    luecken = _luecken_kampagne(list(raw.get("luecken") or []), k)
    plan = vorbereitung._plan(
        auftrag, unterlage=unterlage, einwaende=einwaende, luecken=luecken,
    )
    if _s(briefing) and "Gesprächsplan Kampagne" in briefing:
        plan = _s(briefing) + "\n\n" + plan
    blockiert = [x for x in luecken if not x.startswith("Praxisgedächtnis antwortet nicht")]
    return {
        "ok": True,
        "auftrag": auftrag,
        "patientId": _s(pat.get("id")),
        "name": vorbereitung._name(pat) or _s(pat.get("name")),
        "briefing": plan,
        "unterlage": unterlage,
        "einwaende": einwaende,
        "luecken": luecken,
        "bereit": not blockiert,
        "gedaechtnis": raw.get("gedaechtnis") or "",
        "kampagne": k,
    }


def sammeln_liste(auftrag: str, *, kampagne: dict | None = None,
                  patienten: list | None = None, tenant_id: str = "",
                  briefing: str = "") -> dict[str, Any]:
    """Stufe 2 für die Empfängerliste — bevor Lisa alle anruft."""
    rows = [p for p in (patienten or []) if isinstance(p, dict)]
    if not rows:
        return {
            "ok": False, "error": "keine Empfänger", "bereit": False,
            "patienten": [], "offen": 0, "fertig": 0,
        }
    out = []
    for pat in rows:
        out.append(sammeln_patient(
            auftrag, kampagne=kampagne, patient=pat,
            tenant_id=tenant_id, briefing=briefing,
        ))
    offen = sum(1 for x in out if not x.get("bereit"))
    return {
        "ok": True,
        "bereit": offen == 0,
        "fertig": len(out) - offen,
        "offen": offen,
        "patienten": out,
    }
