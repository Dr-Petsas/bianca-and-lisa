"""Auftrag nach einem manuellen Teststudio-Einzellauf oder Selbst-Anruf.

Nur Einzellauf / Selbst-Anruf (nicht der 10er-Batch): Gespraech + Markierungen
+ Punkte + Chef-Vorschlag landen in uebergabe/. Im Chat reicht „Uebergabe“.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent
UEBERGABE_DIR = REPO / "uebergabe"
CHAT_SATZ = "Übergabe"

_LATENZ_ROT_S = 3.0
_ERSTER_TON_ROT_S = 1.6


def _norm(t: Any) -> str:
    s = "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in str(t or ""))
    return " ".join(s.split())


def _basis(ordner: Path | None = None) -> Path:
    p = ordner or UEBERGABE_DIR
    p.mkdir(parents=True, exist_ok=True)
    (p / "archiv").mkdir(parents=True, exist_ok=True)
    return p


def ersatz(story: dict, fehler: str) -> dict[str, Any]:
    """Minimal-Bericht, wenn der Lauf vor dem Anruf stirbt (z. B. Freifeld-TTS)."""
    return {
        "id": story.get("id") or "",
        "story": dict(story),
        "fehler": fehler,
        "zuege": [],
        "ergebnis": {
            "ok": False,
            "checks": [{"name": "kein Fehler", "ok": False, "soll": "", "ist": fehler}],
            "latenzMaxS": 0, "ersterTonMaxS": 0, "waechter": [], "zuege": 0,
        },
    }


def tickets_aus_bericht(bericht: dict) -> list[dict[str, str]]:
    """Deterministische Punkte: rote Checks, STT-Abweichung, Latenz, Lauf-Fehler."""
    out: list[dict[str, str]] = []
    fehler = str(bericht.get("fehler") or "").strip()
    if fehler:
        out.append({"art": "fehler", "titel": "Lauf-Fehler", "text": fehler})
    for c in (bericht.get("ergebnis") or {}).get("checks") or []:
        if c.get("ok"):
            continue
        if c.get("name") == "kein Fehler" and fehler:
            continue
        soll = str(c.get("soll") or "").strip()
        ist = str(c.get("ist") or "").strip()
        detail = " · ".join(x for x in (f"soll: {soll}" if soll else "",
                                        f"ist: {ist}" if ist else "") if x)
        out.append({"art": "check", "titel": f"Check rot: {c.get('name')}",
                    "text": detail or "ohne Soll/Ist"})
    for z in bericht.get("zuege") or []:
        if z.get("wer") != "anrufer":
            continue
        gesagt = str(z.get("text") or "").strip()
        gehoert = str(z.get("gehoert") or "").strip()
        if gesagt and gehoert and _norm(gesagt) != _norm(gehoert):
            out.append({"art": "stt", "titel": "Ohr hat etwas anderes gehört",
                        "text": f"gesagt: {gesagt}\ngehört: {gehoert}"})
    erg = bericht.get("ergebnis") or {}
    lat = float(erg.get("latenzMaxS") or 0)
    if lat > _LATENZ_ROT_S:
        out.append({"art": "latenz", "titel": f"Antwort dauerte {lat}s",
                    "text": "Zug-Latenz über 3 Sekunden — Anrufer hört zu lange nichts."})
    ton = float(erg.get("ersterTonMaxS") or 0)
    if ton > _ERSTER_TON_ROT_S:
        out.append({"art": "stille", "titel": f"Erster Ton nach {ton}s",
                    "text": "Länger als 1,5 Sekunden Stille — Füller/Watchdog prüfen."})
    return out


def gespraech_zeilen(zuege: list[dict]) -> list[str]:
    zeilen: list[str] = []
    for z in zuege or []:
        wer = "Bianca" if z.get("wer") == "bianca" else "Anrufer"
        if z.get("warte"):
            zeilen.append(f"- {wer}: … (Halbsatz-Wache)")
            continue
        text = str(z.get("text") or "").strip()
        extra = []
        if z.get("frage"):
            extra.append(f"frage={z['frage']}")
        if z.get("baustein"):
            extra.append(str(z["baustein"]))
        gehoert = str(z.get("gehoert") or "").strip()
        if gehoert and _norm(gehoert) != _norm(text):
            extra.append(f"gehört: {gehoert}")
        anhang = f"  ({', '.join(extra)})" if extra else ""
        zeilen.append(f"- {wer}: {text}{anhang}")
    return zeilen


def _story_kurz(story: dict) -> str:
    s = story or {}
    teile = [
        f"Stimme {s.get('stimme') or '—'}",
        f"{s.get('vorname') or ''} {s.get('nachname') or ''}".strip() or "ohne Name",
        f"Anliegen {s.get('anliegen') or 'termin'}",
    ]
    if s.get("grund"):
        teile.append(f"Grund {s['grund']}")
    frei = []
    for k, label in (("eroeffnungText", "Eröffnung"), ("grundText", "Grund-Text"),
                     ("wunschText", "Wunsch"), ("versicherungText", "Versicherung"),
                     ("slotText", "Slot"), ("abschweiferText", "Abschweifer")):
        if s.get(k):
            frei.append(f"{label}: {s[k]}")
    kopf = ", ".join(teile)
    return kopf + (("\n" + "\n".join(frei)) if frei else "")


def _norm_marken(roh: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    gesehen: set[int] = set()
    for m in roh or []:
        if not isinstance(m, dict):
            continue
        kom = str(m.get("kommentar") or "").strip()
        if not kom:
            continue
        try:
            idx = int(m.get("idx"))
        except (TypeError, ValueError):
            continue
        if idx in gesehen:
            continue
        gesehen.add(idx)
        out.append({
            "idx": idx,
            "wer": str(m.get("wer") or "Bianca"),
            "text": str(m.get("text") or "").strip(),
            "kommentar": kom,
        })
    out.sort(key=lambda x: x["idx"])
    return out


def _marken_block(marken: list[dict]) -> str:
    if not marken:
        return "- (keine markierten Antworten — im Verlauf auf „Stimmt nicht“ tippen)"
    zeilen = []
    for m in marken:
        zit = str(m.get("text") or "").strip()
        if len(zit) > 180:
            zit = zit[:177] + "…"
        zeilen.append(
            f"- [ ] **Zug {m.get('idx')} ({m.get('wer') or 'Bianca'})**\n"
            f"  gesagt: {zit or '—'}\n"
            f"  Kommentar: {m.get('kommentar')}"
        )
    return "\n".join(zeilen)


def markdown_bauen(paket: dict) -> str:
    tickets = paket.get("tickets") or []
    hinweis = str(paket.get("hinweis") or "").strip()
    punkte = "\n".join(
        f"- [ ] **{t.get('titel')}**\n  {t.get('text')}" for t in tickets
    ) or "- (keine automatischen roten Punkte — Gespräch trotzdem gegenlesen)"
    dialog = "\n".join(paket.get("gespraech") or []) or "- (kein Gespräch)"
    marken = _norm_marken(paket.get("marken"))
    return (
        f"# Übergabe für Grok\n\n"
        f"Im Chat reicht: **{CHAT_SATZ}**\n\n"
        f"Nur `F:\\Bianca&Lisa TelefonKI`. Clara, MAS-2, Lena-Voice, "
        f"pickadoc-live-base nicht anfassen.\n\n"
        f"- Lauf: `{paket.get('laufId') or '—'}`\n"
        f"- Story: `{paket.get('storyId') or '—'}`\n"
        f"- Ergebnis: {'grün' if paket.get('ok') else 'rot'}\n"
        f"- Ordner: `{paket.get('ordner') or UEBERGABE_DIR}`\n"
        f"- Geschrieben: {paket.get('geschrieben') or ''}\n\n"
        f"## Dein Verbesserungsvorschlag\n\n"
        f"{hinweis or '(noch leer — im Studio-Popup oder in vorschlag.md eintragen)'}\n\n"
        f"## Markierte Antworten\n\n"
        f"{_marken_block(marken)}\n\n"
        f"## Was automatisch auffiel\n\n"
        f"{punkte}\n\n"
        f"## Story\n\n"
        f"{paket.get('storyKurz') or '—'}\n\n"
        f"## Gespräch\n\n"
        f"{dialog}\n"
    )


def vorschlag_lesen(ordner: Path | None = None) -> str:
    p = _basis(ordner) / "vorschlag.md"
    if not p.is_file():
        return ""
    roh = p.read_text(encoding="utf-8")
    # Ueberschrift der Vorlage nicht als Inhalt zaehlen.
    ohne = re.sub(r"^#\s+Dein Vorschlag\s*", "", roh, count=1, flags=re.I).strip()
    if ohne.startswith("(Hier eintragen"):
        return ""
    return ohne


def vorschlag_schreiben(text: str, *, ordner: Path | None = None) -> Path:
    p = _basis(ordner) / "vorschlag.md"
    body = str(text or "").strip()
    p.write_text(("# Dein Vorschlag\n\n" + (body + "\n" if body else
                  "(Hier eintragen, was Bianca anders machen soll.)\n")),
                 encoding="utf-8")
    return p


def bauen(bericht: dict, lauf_id: str, *, hinweis: str = "",
          marken: list | None = None, ordner: Path | None = None) -> dict[str, Any]:
    story = bericht.get("story") or {}
    erg = bericht.get("ergebnis") or {}
    basis = _basis(ordner)
    paket = {
        "laufId": lauf_id,
        "storyId": bericht.get("id") or story.get("id") or "",
        "ok": bool(erg.get("ok")) and not bericht.get("fehler"),
        "geschrieben": datetime.now().isoformat(timespec="seconds"),
        "hinweis": str(hinweis or "").strip() or vorschlag_lesen(basis),
        "chatSatz": CHAT_SATZ,
        "tickets": tickets_aus_bericht(bericht),
        "marken": _norm_marken(marken),
        "gespraech": gespraech_zeilen(bericht.get("zuege") or []),
        "storyKurz": _story_kurz(story),
        "ordner": str(basis),
        "pfad": str(basis / "aktuell.md"),
    }
    paket["markdown"] = markdown_bauen(paket)
    return paket


def _ablegen(paket: dict, basis: Path) -> None:
    (basis / "aktuell.json").write_text(
        json.dumps(paket, ensure_ascii=False, indent=1), encoding="utf-8")
    (basis / "aktuell.md").write_text(paket["markdown"], encoding="utf-8")
    sid = re.sub(r"[^\w.-]+", "_", str(paket.get("storyId") or "story"))[:60]
    archiv = basis / "archiv" / f"{paket.get('laufId') or 'lauf'}-{sid}.md"
    archiv.write_text(paket["markdown"], encoding="utf-8")


def schreiben(bericht: dict, lauf_id: str, *, hinweis: str = "",
              marken: list | None = None, ordner: Path | None = None) -> dict[str, Any]:
    basis = _basis(ordner)
    paket = bauen(bericht, lauf_id, hinweis=hinweis, marken=marken, ordner=basis)
    if paket["hinweis"]:
        vorschlag_schreiben(paket["hinweis"], ordner=basis)
    elif not (basis / "vorschlag.md").is_file():
        vorschlag_schreiben("", ordner=basis)
    _ablegen(paket, basis)
    return paket


def lesen(ordner: Path | None = None) -> dict[str, Any] | None:
    basis = _basis(ordner)
    js = basis / "aktuell.json"
    if not js.is_file():
        return None
    try:
        paket = json.loads(js.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    chef = vorschlag_lesen(basis)
    if chef and chef != paket.get("hinweis"):
        paket["hinweis"] = chef
        paket["markdown"] = markdown_bauen(paket)
    return paket


def hinweis_setzen(hinweis: str, *, ordner: Path | None = None) -> dict[str, Any] | None:
    basis = _basis(ordner)
    paket = lesen(basis)
    if not paket:
        return None
    paket["hinweis"] = str(hinweis or "").strip()
    paket["geschrieben"] = datetime.now().isoformat(timespec="seconds")
    paket["markdown"] = markdown_bauen(paket)
    vorschlag_schreiben(paket["hinweis"], ordner=basis)
    _ablegen(paket, basis)
    return paket


def marken_setzen(marken: list, *, ordner: Path | None = None) -> dict[str, Any] | None:
    """Markierte Bianca-Antworten nachtragen — auch nach dem Einzellauf."""
    basis = _basis(ordner)
    paket = lesen(basis)
    if not paket:
        return None
    paket["marken"] = _norm_marken(marken)
    paket["geschrieben"] = datetime.now().isoformat(timespec="seconds")
    paket["markdown"] = markdown_bauen(paket)
    _ablegen(paket, basis)
    return paket
