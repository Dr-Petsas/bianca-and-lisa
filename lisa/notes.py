"""Terminnotizen: Besonderes aus dem Gespräch, kurz fürs Notizfeld."""

from __future__ import annotations

import re
from typing import Any

BESONDERS = re.compile(
    r"\b("
    r"angst|ängst|aengst|nervös|nervoes|panik|weint|weinen|"
    r"spritze|betäub|betaeub|narkose|sedier|"
    r"schmerz|tut weh|empfind|"
    r"allergie|bluter|herz|schrittmacher|pacemaker|schwanger|"
    r"rollstuhl|rollator|gehhilfe|"
    r"begleit|mit kind|mit mutter|mit vater|nicht allein|"
    r"dolmetsch|übersetz|uebersetz|englisch|türkisch|tuerkisch|arabisch|"
    r"nur vormittag|nur nachmittag|nur früh|nur frueh"
    r")\w*\b",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def notiz_anhaengen(vorhanden: str, notiz: str, *, herkunft: str = "Lisa") -> str:
    alt = _s(vorhanden)
    neu = _s(notiz)
    if not neu:
        return alt
    zeile = f"{neu} ({herkunft})" if herkunft else neu
    schon = [
        z.strip().lower()
        for z in alt.splitlines()
        if z.strip()
    ]
    if zeile.lower() in schon or neu.lower() in schon:
        return alt
    return f"{alt}\n{zeile}" if alt else zeile


def besonderes(text: str) -> list[str]:
    gefunden = []
    for m in BESONDERS.finditer(text or ""):
        wort = m.group(0).lower()
        if wort not in gefunden:
            gefunden.append(wort)
    return gefunden


def nutzer_saetze(sit: dict[str, Any]) -> list[str]:
    out = []
    for z in sit.get("zuege") or []:
        t = _s(z.get("textIn"))
        if t:
            out.append(t)
    for m in sit.get("messages") or []:
        if m.get("role") == "user":
            t = _s(m.get("content"))
            if t and not t.startswith("(") and t not in out:
                out.append(t)
    return out[-12:]


def zusammenfassung(sit: dict[str, Any]) -> str:
    satze = nutzer_saetze(sit)
    extra = besonderes(" ".join(satze))
    aktion = ""
    last = sit.get("lastBook") or sit.get("lastMove") or sit.get("lastCancel")
    if last:
        if last.get("name") == "cancel_appointment" or sit.get("lastCancel"):
            aktion = "Absage am Telefon."
        elif last.get("name") == "move_appointment" or sit.get("lastMove"):
            aktion = "Verschoben am Telefon."
        elif last.get("booked") or last.get("dryRun"):
            aktion = "Neuer Termin am Telefon."
    bits = [aktion] if aktion else []
    if extra:
        bits.append("Patient: " + ", ".join(extra) + ".")
    elif satze:
        kurz = satze[-1]
        if len(kurz) > 140:
            kurz = kurz[:137] + "…"
        bits.append(f"Patient sagte: {kurz}")
    return _s(" ".join(bits))


def braucht_notiz(sit: dict[str, Any]) -> bool:
    if sit.get("lastBook") or sit.get("lastMove") or sit.get("lastCancel"):
        return True
    return bool(besonderes(" ".join(nutzer_saetze(sit))))
