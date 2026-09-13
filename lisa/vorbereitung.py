"""Lisas belegte Sammelphase vor dem Waehlen — nichts erfinden."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from kern import agentprofil, gedaechtnis
from kern import patients as patmod

_RECALL_RE = re.compile(
    r"recall|kontrolle|nachsorge|prophylaxe|zahnreinigung|\bpzr\b", re.I)
_PRAXIS_RE = re.compile(
    r"termin|praxis|zahn|arzt|behandlung|kontroll|pzr|rezept|überweisung|"
    r"ueberweisung|befund|patient", re.I)
_FIRMA_RE = re.compile(
    r"firma|labor|bestell|liefer|lieferant|rechnung|auftrag|pizza|ticket|"
    r"flug|hotel|zoll|awb|paket|versand", re.I)
_MAIL_RE = re.compile(r"e-?mail|\bmail\b|nadine|geschrieben", re.I)
_ANRUF_RE = re.compile(r"anruf|angerufen|lisa|bianca|nicht erreicht|rückruf|rueckruf", re.I)
_MUELL_THEMA_RE = re.compile(r"zoll|awb|paketversand|tracking", re.I)
_THEMA_STOP = {
    "ein", "eine", "einen", "einer", "eines", "der", "die", "das", "den",
    "dem", "des", "und", "oder", "bitte", "mal", "mit", "von", "für",
    "fuer", "auf", "aus", "bei", "zum", "zur", "ins", "im", "ist", "sind",
    "soll", "sollte", "wird", "werden", "dass", "wie", "was", "wer", "wir",
    "sie", "ich", "du", "ihr", "nicht", "noch", "auch", "nur", "sehr",
    "hier", "dort",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _kerne(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß]{3,}", (text or "").lower())
            if w not in _THEMA_STOP}


def _phone(pat: dict) -> str:
    roh = _s(pat.get("phone")) or _s(pat.get("phoneDisplay")) or _s(pat.get("devPhoneRaw"))
    return "".join(c for c in roh if c.isdigit())


def _name(pat: dict) -> str:
    return _s(pat.get("name")) or (
        f"{_s(pat.get('firstName'))} {_s(pat.get('lastName'))}".strip())


def _termin_datum(item: dict) -> datetime | None:
    iso = _s(item.get("iso") or item.get("date") or "")
    if len(iso) < 10:
        return None
    try:
        return datetime.fromisoformat(iso[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _jung(item: dict, tage: int = 14) -> bool:
    d = _termin_datum(item)
    return bool(d and datetime.now(timezone.utc) - d <= timedelta(days=tage))


def _bald(item: dict, tage: int = 21) -> bool:
    d = _termin_datum(item)
    jetzt = datetime.now(timezone.utc)
    return bool(d and jetzt <= d <= jetzt + timedelta(days=tage))


def _filter_event(ev: dict, auftrag: str) -> bool:
    text = _s(ev.get("summary"))
    if not text:
        return False
    firma = bool(_FIRMA_RE.search(auftrag))
    praxis = bool(_RECALL_RE.search(auftrag) or _PRAXIS_RE.search(auftrag))
    if praxis and not firma and _MUELL_THEMA_RE.search(text):
        return False
    if _PRAXIS_RE.search(text) and not _FIRMA_RE.search(text):
        kerne = _kerne(auftrag)
        if kerne and not any(k in text.lower() for k in kerne):
            return False
    return True


def _gedaechtnis_stand(name: str, phone: str) -> tuple[list[dict], str]:
    if not gedaechtnis.enabled():
        return [], "aus"
    if not name and not phone:
        return [], "nichts"
    try:
        return gedaechtnis.ereignisse_holen(phone, name), "ok"
    except Exception as e:
        print(f"lisa-vorbereitung gedaechtnis fail {e}", flush=True)
        return [], "tot"


def _termine(tenant_id: str, pat: dict) -> tuple[list, list]:
    past = list(pat.get("past") or [])
    upcoming = list(pat.get("upcoming") or [])
    if past or upcoming:
        return past, upcoming
    if not tenant_id or not (pat.get("id") or _name(pat)):
        return [], []
    try:
        t = agentprofil.fuer_tenant(tenant_id)
        hist = patmod.termine_fuer(t, pat if pat.get("id") else {"name": _name(pat)})
        return hist.get("past") or [], hist.get("upcoming") or []
    except Exception as e:
        print(f"lisa-vorbereitung termine fail {e}", flush=True)
        return [], []


def _unterlage(past: list, upcoming: list, events: list[dict], auftrag: str) -> list[str]:
    zeilen: list[str] = []
    if upcoming:
        zeilen.append("Kartei, kommend: " + "; ".join(
            _s(x.get("label")) for x in upcoming[:4] if _s((x or {}).get("label"))))
    if past:
        zeilen.append("Kartei, zuletzt: " + "; ".join(
            _s(x.get("label")) for x in past[-3:] if _s((x or {}).get("label"))))
    for ev in events:
        if not _filter_event(ev, auftrag):
            continue
        summ = _s(ev.get("summary"))
        wann = ""
        try:
            if ev.get("ts"):
                wann = datetime.fromtimestamp(float(ev["ts"]) / 1000.0).strftime("%d.%m.")
        except (TypeError, ValueError, OSError):
            pass
        offen = " (noch offen)" if ev.get("status") == "open" else ""
        kanal = "Mail" if _MAIL_RE.search(summ) else (
            "Anruf" if _ANRUF_RE.search(summ) else "Kontakt")
        zeilen.append(f"{kanal}{', ' + wann if wann else ''}: {summ}{offen}")
        if len([z for z in zeilen if z.startswith(("Mail", "Anruf", "Kontakt"))]) >= 6:
            break
    return [z for z in zeilen if z]


def _einwaende(past: list, upcoming: list, events: list[dict], auftrag: str) -> list[str]:
    out: list[str] = []
    praxis = bool(_RECALL_RE.search(auftrag) or (
        _PRAXIS_RE.search(auftrag) and not _FIRMA_RE.search(auftrag)))
    if praxis:
        for t in upcoming[:2]:
            label = _s(t.get("label")) or "demnächst"
            if _bald(t) or label:
                out.append(
                    f"Erwartet: „Ich komme doch schon {label}.“ — bestehenden "
                    "Termin nutzen, keinen zweiten darüberbuchen.")
                break
        jung = [t for t in past if _jung(t)] or (past[-1:] if past else [])
        if jung:
            label = _s(jung[-1].get("label")) or "kürzlich"
            out.append(
                f"Erwartet: „Ich war doch erst {label} da.“ — nicht "
                "widersprechen und nur belegte Angaben verwenden.")
    for ev in events:
        if not _filter_event(ev, auftrag):
            continue
        summ = _s(ev.get("summary"))
        if re.search(r"nächste woche|naechste woche|kommt (schon|sowieso)|bereits termin",
                     summ, re.I):
            out.append(
                f"Erwartet aus dem Gedächtnis: Widerspruch zu „{summ[:120]}“ "
                "bestätigen, nicht übergehen.")
            break
    out.append(
        "Eingang: Wer sind Sie? Woher die Nummer? Was ist das? "
        "KI oder Mensch? Wieso rufen Sie an?")
    return out


def _luecken(auftrag: str, *, name: str, phone: str, past: list, upcoming: list,
             events: list[dict], stand: str) -> list[str]:
    fragen: list[str] = []
    if not name and not phone:
        fragen.append("Wen genau anrufen? Name oder Nummer fehlt.")
    if stand == "tot":
        fragen.append("Praxisgedächtnis antwortet nicht — nur Kartei und Auftrag gelten.")
    nutzbar = [e for e in events if _filter_event(e, auftrag)]
    if _RECALL_RE.search(auftrag) and not past and not upcoming and not nutzbar:
        fragen.append(
            "Recall ohne Historie: Wann war der letzte Besuch? Welcher Arzt? "
            "PZR? Was gilt bei einem Widerspruch?")
    if _FIRMA_RE.search(auftrag) and not nutzbar:
        fragen.append(
            "Firmenanruf ohne Mail- oder Anrufvorgang: Welche Unterlage gilt?")
    return fragen


def _plan(auftrag: str, *, unterlage: list[str], einwaende: list[str],
          luecken: list[str]) -> str:
    teile = [
        _s(auftrag) or "Anrufen.",
        "",
        "Gesprächsplan (nicht vorlesen, nichts erfinden):",
        "1) Eingang: wer, warum, auf Nachfrage KI/Nummer — dann das Thema.",
        "2) Nur Fakten aus Auftrag und Unterlage. Leere Felder bleiben leer.",
    ]
    if unterlage:
        teile.append("Unterlage (nutzen, nicht vorlesen):")
        teile.extend(f"- {z}" for z in unterlage)
    else:
        teile.append("Unterlage: keine — nichts aus einem Gedächtnis behaupten.")
    if einwaende:
        teile.append("Einwände nur diese:")
        teile.extend(f"- {z}" for z in einwaende)
    if luecken:
        teile.append("Offen (Chef, nicht den Angerufenen fragen):")
        teile.extend(f"- {z}" for z in luecken)
    teile.append(
        "[Regie: Nach zwei Sätzen nicht aufhören. Keine Preise, Befunde "
        "oder Gründe erfinden.]")
    return "\n".join(teile)


def sammeln(auftrag: str, *, tenant_id: str = "",
            patient: dict | None = None) -> dict[str, Any]:
    auftrag = _s(auftrag)
    if not auftrag:
        return {
            "ok": False, "error": "auftrag fehlt", "auftrag": "",
            "briefing": "", "unterlage": [], "einwaende": [], "luecken": [],
            "bereit": False, "gedaechtnis": "nichts", "hatStand": False,
            "gedaechtnisText": "",
        }
    pat = patient if isinstance(patient, dict) else {}
    name = _name(pat)
    phone = _phone(pat)
    if phone in {"01776004600", "1776004600"}:
        phone = "".join(c for c in _s(pat.get("phone")) if c.isdigit())
        if phone in {"01776004600", "1776004600"}:
            phone = ""
    past, upcoming = _termine(tenant_id, pat)
    events, stand = _gedaechtnis_stand(name, phone)
    if stand == "ok" and not events:
        stand = "nichts"
    unterlage = _unterlage(past, upcoming, events, auftrag)
    einwaende = _einwaende(past, upcoming, events, auftrag)
    luecken = _luecken(
        auftrag, name=name, phone=phone, past=past, upcoming=upcoming,
        events=events, stand=stand)
    briefing = _plan(
        auftrag, unterlage=unterlage, einwaende=einwaende, luecken=luecken)
    blockiert = [
        x for x in luecken
        if not x.startswith("Praxisgedächtnis antwortet nicht")
    ]
    return {
        "ok": True,
        "auftrag": auftrag,
        "briefing": briefing,
        "unterlage": unterlage,
        "einwaende": einwaende,
        "luecken": luecken,
        "bereit": not blockiert,
        "gedaechtnis": stand,
        "hatStand": bool(unterlage),
        "gedaechtnisText": "\n".join(unterlage),
        "past": past,
        "upcoming": upcoming,
    }
