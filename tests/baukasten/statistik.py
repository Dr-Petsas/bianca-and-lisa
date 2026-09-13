"""Zeitbezogene Qualitätsstatistik aus Studio- und Belastungstest-Berichten."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


def _json(pfad: Path) -> dict[str, Any]:
    try:
        data = json.loads(pfad.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _zeit(text: object, fallback: str = "") -> str:
    roh = str(text or fallback or "")
    m = re.search(r"(20\d{2})[-]?(\d{2})[-]?(\d{2})[T _-]?(\d{2})?:?(\d{2})?", roh)
    if not m:
        return ""
    uhr = f"T{m.group(4) or '00'}:{m.group(5) or '00'}:00"
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}{uhr}"


def _aehnlich(a: object, b: object) -> float:
    norm = lambda x: re.sub(r"[^a-z0-9äöüß]+", "", str(x or "").lower())
    x, y = norm(a), norm(b)
    if not x or not y:
        return 1.0
    return SequenceMatcher(None, x, y).ratio()


def _empfehlung(problem: str) -> str:
    k = problem.lower()
    if "nachname" in k or "telefon" in k or "stt" in k:
        return "Erkennung der Patientendaten und Rückbestätigung im Dialog prüfen."
    if "motiv" in k or "besuchsgrund" in k:
        return "Besuchsgrund-Mapping gegen den aktuellen Praxiskatalog nachschärfen."
    if "gebucht" in k or "abgesagt" in k or "verschoben" in k:
        return "Deterministischen Kalenderweg und Werkzeugbeleg dieses Gesprächs prüfen."
    if "latenz" in k or "erster ton" in k:
        return "Langsamsten Zug im Gespräch öffnen und STT-, LLM- und TTS-Zeit vergleichen."
    if "festgefahren" in k or "schleife" in k:
        return "Offene Pflichtfrage und Wiederholungswächter an dieser Stelle untersuchen."
    if "fehler" in k or "timeout" in k or "leer" in k:
        return "Serverereignisse und den letzten vollständigen Zug vor dem Abbruch prüfen."
    return "Roten Gesprächsverlauf öffnen und die erste Abweichung vom Soll untersuchen."


def _studio_gespraeche(basis: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lauf_pfad in basis.glob("*/lauf.json"):
        lauf = _json(lauf_pfad)
        lauf_id = str(lauf.get("laufId") or lauf_pfad.parent.name)
        lauf_tenant = str(lauf.get("tenant") or "")
        for kurz in lauf.get("stories") or []:
            if not isinstance(kurz, dict):
                continue
            story_id = str(kurz.get("id") or "")
            bericht = _json(lauf_pfad.parent / story_id / "bericht.json")
            erg = bericht.get("ergebnis") or {}
            story = bericht.get("story") or {}
            zuege = bericht.get("zuege") or []
            tenant = str(story.get("tenant") or lauf_tenant)
            checks = [
                str(c.get("name") or "Unbekannter Check")
                for c in (erg.get("checks") or kurz.get("checks") or [])
                if isinstance(c, dict) and not c.get("ok")
            ]
            fehler = str(bericht.get("fehler") or kurz.get("fehler") or "")
            if fehler:
                checks.insert(0, fehler)
            user_zuege = [z for z in zuege if isinstance(z, dict) and z.get("wer") == "anrufer"]
            stt_warn = sum(
                1 for z in user_zuege
                if z.get("gehoert") and _aehnlich(
                    z.get("gesprochen") or z.get("text"), z.get("gehoert"),
                ) < 0.72
            )
            lat = [
                float(z.get("latenzS") or 0)
                for z in zuege if isinstance(z, dict) and z.get("wer") == "bianca"
                and z.get("latenzS")
            ]
            ton = [
                float(z.get("ersterTonS") or 0)
                for z in zuege if isinstance(z, dict) and z.get("wer") == "bianca"
                and z.get("ersterTonS")
            ]
            ok = bool(erg.get("ok", kurz.get("ok")))
            out.append({
                "art": "Studio",
                "laufId": lauf_id,
                "storyId": story_id,
                "tenant": tenant,
                "zeit": _zeit(bericht.get("start"), str(lauf.get("gestartet") or lauf_id)),
                "ok": ok,
                "turns": len(user_zuege) or max(0, int(erg.get("zuege") or 0) // 2),
                "latenz": round(sum(lat) / len(lat), 3) if lat else 0.0,
                "ersterTon": round(sum(ton) / len(ton), 3) if ton else 0.0,
                "sttWarn": stt_warn,
                "probleme": checks or ([] if ok else ["Gespräch nicht erfolgreich"]),
            })
    return out


def _last_gespraeche(basis: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pfad in basis.glob("*/lasttest.json"):
        data = _json(pfad)
        lauf_id = str(data.get("laufId") or pfad.parent.name)
        zeit = _zeit(data.get("gestartet"), lauf_id)
        for i, call in enumerate(data.get("laeufe") or [], 1):
            if not isinstance(call, dict):
                continue
            fehler = str(call.get("fehler") or "")
            ok = bool(call.get("ok"))
            out.append({
                "art": "Belastung",
                "laufId": lauf_id,
                "storyId": f"Gespräch {call.get('nr') or i}",
                "tenant": str(call.get("tenant") or ""),
                "zeit": zeit,
                "ok": ok,
                "turns": len(call.get("zuege") or []),
                "latenz": float(call.get("antwortS") or 0),
                "ersterTon": float(call.get("ersterTonS") or 0),
                "sttWarn": 0,
                "probleme": [fehler] if fehler else ([] if ok else ["Belastungsgespräch abgebrochen"]),
            })
    return out


def _trend(gespraeche: list[dict[str, Any]]) -> dict[str, Any]:
    if len(gespraeche) < 4:
        return {"text": "Noch zu wenig Daten für einen belastbaren Vergleich.", "richtung": "neutral"}
    fenster = min(10, len(gespraeche) // 2)
    alt, neu = gespraeche[-2 * fenster:-fenster], gespraeche[-fenster:]

    def quote(xs: list[dict[str, Any]]) -> float:
        return 100.0 * sum(1 for x in xs if x["ok"]) / max(1, len(xs))

    def latenz(xs: list[dict[str, Any]]) -> float:
        vals = [float(x["latenz"]) for x in xs if x["latenz"]]
        return sum(vals) / len(vals) if vals else 0.0

    dq = round(quote(neu) - quote(alt), 1)
    dl = round(latenz(neu) - latenz(alt), 2)
    richtung = "besser" if dq > 0 or (dq == 0 and dl < -0.1) else (
        "schlechter" if dq < 0 or (dq == 0 and dl > 0.1) else "gleich"
    )
    return {
        "richtung": richtung,
        "erfolgsquoteDelta": dq,
        "latenzDeltaS": dl,
        "fenster": fenster,
        "text": (
            f"Letzte {fenster} vs. vorherige {fenster}: "
            f"Erfolgsquote {dq:+.1f} Punkte, Antwortzeit {dl:+.2f} s."
        ),
    }


def aus_berichten(basis: Path, tenant: str = "") -> dict[str, Any]:
    """Alle vorhandenen Testberichte eines Mandanten kumuliert auswerten."""
    tid = str(tenant or "").strip()
    gespraeche = _studio_gespraeche(basis) + _last_gespraeche(basis)
    if tid:
        gespraeche = [g for g in gespraeche if g["tenant"] == tid]
    gespraeche.sort(key=lambda g: (g["zeit"], g["laufId"], g["storyId"]))

    tage: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "gespraeche": 0, "turns": 0, "erfolgreich": 0, "fehlgeschlagen": 0,
        "latenzen": [], "ersteToene": [], "sttWarn": 0,
    })
    probleme: Counter[str] = Counter()
    letzte_problemzeit: dict[str, str] = {}
    analysen: list[dict[str, Any]] = []
    for g in gespraeche:
        tag = (g["zeit"] or "unbekannt")[:10]
        t = tage[tag]
        t["gespraeche"] += 1
        t["turns"] += int(g["turns"])
        t["erfolgreich" if g["ok"] else "fehlgeschlagen"] += 1
        if g["latenz"]:
            t["latenzen"].append(float(g["latenz"]))
        if g["ersterTon"]:
            t["ersteToene"].append(float(g["ersterTon"]))
        t["sttWarn"] += int(g["sttWarn"])
        for p in g["probleme"]:
            problem = str(p or "").strip()
            if problem:
                probleme[problem] += 1
                letzte_problemzeit[problem] = g["zeit"]
        if not g["ok"] or g["probleme"]:
            gruende = g["probleme"] or ["Gespräch nicht erfolgreich"]
            analysen.append({
                **g,
                "empfehlung": _empfehlung(gruende[0]),
            })

    zeitreihe: list[dict[str, Any]] = []
    kum_g, kum_ok, kum_fehler = 0, 0, 0
    for tag in sorted(tage):
        t = tage[tag]
        kum_g += t["gespraeche"]
        kum_ok += t["erfolgreich"]
        kum_fehler += t["fehlgeschlagen"]
        zeitreihe.append({
            "datum": tag,
            "gespraeche": t["gespraeche"],
            "turns": t["turns"],
            "erfolgreich": t["erfolgreich"],
            "fehlgeschlagen": t["fehlgeschlagen"],
            "erfolgsquote": round(100.0 * t["erfolgreich"] / max(1, t["gespraeche"]), 1),
            "latenzS": round(sum(t["latenzen"]) / len(t["latenzen"]), 2) if t["latenzen"] else 0.0,
            "ersterTonS": round(sum(t["ersteToene"]) / len(t["ersteToene"]), 2) if t["ersteToene"] else 0.0,
            "sttWarn": t["sttWarn"],
            "kumuliert": {"gespraeche": kum_g, "erfolgreich": kum_ok, "fehlgeschlagen": kum_fehler},
        })

    gesamt = len(gespraeche)
    erfolg = sum(1 for g in gespraeche if g["ok"])
    turns = sum(int(g["turns"]) for g in gespraeche)
    lat = [float(g["latenz"]) for g in gespraeche if g["latenz"]]
    toene = [float(g["ersterTon"]) for g in gespraeche if g["ersterTon"]]
    warnungen: list[dict[str, str]] = []
    if gesamt and erfolg < gesamt:
        warnungen.append({
            "stufe": "kritisch" if erfolg / gesamt < 0.8 else "warnung",
            "text": f"{gesamt - erfolg} von {gesamt} Gesprächen sind fehlgeschlagen.",
        })
    if toene and sum(toene) / len(toene) > 2.0:
        warnungen.append({"stufe": "warnung", "text": "Der erste Ton liegt im Mittel über zwei Sekunden."})
    stt_gesamt = sum(int(g["sttWarn"]) for g in gespraeche)
    if stt_gesamt:
        warnungen.append({"stufe": "hinweis", "text": f"{stt_gesamt} deutlich abweichende STT-Züge erkannt."})
    if not warnungen:
        warnungen.append({
            "stufe": "ok" if gesamt else "hinweis",
            "text": "Keine Qualitätswarnung im gewählten Zeitraum." if gesamt else "Noch keine Testdaten für diese Praxis.",
        })

    top = [
        {
            "problem": p,
            "anzahl": n,
            "zuletzt": letzte_problemzeit.get(p, ""),
            "empfehlung": _empfehlung(p),
        }
        for p, n in probleme.most_common(12)
    ]
    return {
        "tenant": tid,
        "gesamt": {
            "gespraeche": gesamt,
            "turns": turns,
            "erfolgreich": erfolg,
            "fehlgeschlagen": gesamt - erfolg,
            "erfolgsquote": round(100.0 * erfolg / max(1, gesamt), 1) if gesamt else 0.0,
            "latenzS": round(sum(lat) / len(lat), 2) if lat else 0.0,
            "ersterTonS": round(sum(toene) / len(toene), 2) if toene else 0.0,
        },
        "trend": _trend(gespraeche),
        "zeitreihe": zeitreihe,
        "warnungen": warnungen,
        "probleme": top,
        "analysen": list(reversed(analysen[-30:])),
    }
