"""Terminnotizen: EIN Satz plus Auffälliges — kein Datenkern, kein Transkript.

Chef 27.08.2026: Name, Nummer, Datum, SMS-Hinweis stehen längst am Termin —
in die Notiz gehört nur "telefonisch Termin vereinbart wegen X // Bianca"
und, falls der Patient etwas Auffälliges erwähnt (Angst, Begleitung,
kurioser Grund), je eine kurze Zeile dazu. Deterministisch, ohne LLM:
gleicher Anruf ergibt gleiche Zeilen, die masAppointmentNote zeilen-
idempotent wegfiltert, statt bei jedem Schreiben neu formulierten Müll
anzuhängen."""

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
    zeile = f"{neu} // {herkunft}" if herkunft and not neu.rstrip().endswith(f"// {herkunft}") else neu
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


# Satzanfänge, die im gesprochenen Grund nur Anlauf sind: "Ich wollte mir die
# Fingernägel lackieren lassen" -> "Fingernägel lackieren".
_GRUND_ANLAUF_RE = re.compile(
    r"^(?:(?:äh+m*|aeh+m*|hm+|also|na|ja)[\s,.!—-]+)*"
    r"(?:ich\s+|wir\s+)?(?:wollte|will|würde|wuerde|möchte|moechte|muss|müsste|muesste|"
    r"brauche|bräuchte|brauchte|hätte|haette|habe|hab|soll|sollte)?\s*"
    r"(?:gern[e]?\s+)?(?:mir\s+|mich\s+|uns\s+)?(?:mal\s+|kurz\s+|bitte\s+|noch\s+|unbedingt\s+)*"
    r"(?:die\s+|den\s+|das\s+|meine[nm]?\s+|mein\s+|eine[nm]?\s+|ein\s+)?",
    re.I,
)
_GRUND_SCHLUSS_RE = re.compile(r"\s*(?:lassen|bitte|machen\s+lassen)\s*[.!?…]*\s*$", re.I)


def grund_kurz(sit: dict[str, Any]) -> str:
    """Der Grund in Patientenworten, kondensiert — für "… wegen X"."""
    s = sit.get("sammler") or {}
    roh = _s(s.get("grundWortlaut") or s.get("grund"))
    if not roh:
        return ""
    kurz = _GRUND_ANLAUF_RE.sub("", roh)
    kurz = _GRUND_SCHLUSS_RE.sub("", kurz).strip(" ,.!?…")
    kurz = kurz or roh.strip(" ,.!?…")
    if len(kurz) > 70:
        kurz = kurz[:67] + "…"
    return kurz[:1].upper() + kurz[1:] if kurz else ""


def zusammenfassung(sit: dict[str, Any]) -> str:
    """EINE Zeile fürs Notizfeld (ohne Herkunfts-Stempel — den hängt
    notiz_anhaengen an): "telefonisch Termin vereinbart wegen Zahnschmerzen"."""
    aktion = ""
    buch = sit.get("lastBook") or {}
    if (sit.get("lastCancel") or {}).get("ok"):
        aktion = "telefonisch Termin abgesagt"
    elif (sit.get("lastMove") or {}).get("ok"):
        aktion = "telefonisch Termin verschoben"
    elif buch.get("booked") or buch.get("dryRun"):
        aktion = "telefonisch Termin vereinbart"
        grund = grund_kurz(sit)
        if grund:
            aktion += f" wegen {grund}"
    return aktion


def besondere_zeilen(sit: dict[str, Any]) -> list[str]:
    """Auffälliges in Patientenworten — je Fund eine kurze Zeile, maximal zwei."""
    zeilen: list[str] = []
    for satz in nutzer_saetze(sit):
        if not BESONDERS.search(satz):
            continue
        kurz = satz if len(satz) <= 90 else satz[:87] + "…"
        zeile = f"Patient erwähnt: „{kurz}“"
        if zeile not in zeilen:
            zeilen.append(zeile)
        if len(zeilen) >= 2:
            break
    return zeilen


def braucht_notiz(sit: dict[str, Any]) -> bool:
    if sit.get("lastBook") or sit.get("lastMove") or sit.get("lastCancel"):
        return True
    return bool(besonderes(" ".join(nutzer_saetze(sit))))


def stimme_von(sit: dict[str, Any]) -> str:
    """Welche Stimme führt diese Sitzung? Lisa (Default) oder Bianca."""
    return _s(sit.get("stimme")) or "Lisa"


def termin_notiz(sit: dict[str, Any]) -> str:
    """Notiz fürs Terminpopup — minimal (Chef 27.08.2026):

        telefonisch Termin vereinbart wegen Fingernägel lackieren // Bianca
        Patient erwähnt: „Ich habe furchtbare Angst vor Spritzen“ // Bianca

    Kein Datenkern (Name/Nummer/Datum stehen am Termin), keine Kurzfassung,
    kein Transkript."""
    wer = stimme_von(sit)
    zeilen: list[str] = []
    kopf = zusammenfassung(sit)
    if kopf:
        zeilen.append(f"{kopf} // {wer}")
    for zusatz in besondere_zeilen(sit):
        zeilen.append(f"{zusatz} // {wer}")
    return "\n".join(zeilen)
