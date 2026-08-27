"""Terminnotizen: Besonderes aus dem Gespräch, kurz fürs Notizfeld."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

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


def stimme_von(sit: dict[str, Any]) -> str:
    """Welche Stimme führt diese Sitzung? Lisa (Default) oder Bianca."""
    return _s(sit.get("stimme")) or "Lisa"


def protokoll(sit: dict[str, Any], *, limit: int = 2400) -> str:
    """Gesprächsverlauf als lesbare Zeilen (Patient:/Stimme:), fürs Notizfeld."""
    wer = stimme_von(sit)
    zeilen: list[str] = []
    for z in sit.get("zuege") or []:
        gesagt = _s(z.get("textIn"))
        antwort = _s(z.get("text"))
        if gesagt:
            zeilen.append(f"Patient: {gesagt}")
        if antwort:
            zeilen.append(f"{wer}: {antwort}")
    text = "\n".join(zeilen)
    if len(text) > limit:
        # Ende behalten (dort stehen Buchung/Bestätigung), sauber an Zeile schneiden.
        rest = text[-limit:]
        text = "…\n" + (rest.split("\n", 1)[-1] if "\n" in rest else rest)
    return text


def _stempel(sit: dict[str, Any]) -> str:
    raw = _s(sit.get("startedAt"))
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    try:
        dt = dt.astimezone(ZoneInfo("Europe/Berlin"))
    except Exception:
        pass
    return dt.strftime("%d.%m.%Y %H:%M")


def gespraechs_zusammenfassung(sit: dict[str, Any]) -> str:
    """Kurzfassung des Telefonats per LLM (3-5 Zeilen) — NICHT das Transkript.

    Chef 27.08.2026: kein Volltranskript mehr im Termin; nach dem Auflegen
    wird in einem zweiten Schritt nur die Zusammenfassung eingetragen.
    """
    verlauf = protokoll(sit, limit=4000)
    if not verlauf:
        return ""
    from kern import llm
    out = llm.chat([
        {"role": "system", "content": (
            "Du fasst ein Praxis-Telefonat für die Terminnotiz zusammen. "
            "Antworte NUR mit 2 bis 5 kurzen Zeilen auf Deutsch, je Zeile ein Punkt: "
            "Anliegen; Ergebnis (gebucht/abgesagt/verschoben mit Tag und Uhrzeit); "
            "Name und Telefonnummer, falls genannt; Besonderheiten (Schmerzen, Angst, "
            "Begleitung, Wünsche). Sachlich, keine Anrede, keine Floskeln, nichts erfinden."
        )},
        {"role": "user", "content": verlauf},
    ], None, temperature=0.1, max_tokens=220)
    if not out.get("ok"):
        return ""
    zeilen = [" ".join(z.split()) for z in str(out.get("text") or "").splitlines()]
    return "\n".join(z for z in zeilen if z)[:700]


def termin_notiz(sit: dict[str, Any]) -> str:
    """Notiz fürs Terminpopup: Kopfzeile + Gesprächs-Kurzfassung (kein Transkript)."""
    wer = stimme_von(sit)
    teile: list[str] = []
    kopf = zusammenfassung(sit)
    if kopf:
        teile.append(notiz_anhaengen("", kopf, herkunft=wer))
    kurz = gespraechs_zusammenfassung(sit)
    if kurz:
        stamp = _stempel(sit)
        teile.append(f"— Gespräch {wer}{(' ' + stamp) if stamp else ''}, Kurzfassung —")
        teile.append(kurz)
    return "\n".join(teile)
