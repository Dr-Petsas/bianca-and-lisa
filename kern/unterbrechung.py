"""Barge-in mit Fortsetzung (W-BARGE 29.08.2026) — für BEIDE Stimmen.

Chef: "wenn sich unsere sprachen kreuzen, muss die KI-Assistentin aufhören,
mit hmm oder okay konkret auf den Einwand reagieren und dann erst nach
Klärung fortfahren, wo sie stehengeblieben ist."

Drei Bausteine, alle stimmen-unabhängig (kern/dienst.py hängt sie ein):

1. SATZ-KARTE: Beim Sprechen merkt sich der Dienst je Äußerung die Sätze
   und ihre End-Zeitpunkte im Audio (der Stream-Feeder pusht satzweise,
   die Blocking-Fügung kennt die WAV-Längen — beides exakt, nichts geraten).
2. EINGANG: Das Dock meldet beim Reinsprechen die Abspielposition
   (bargeUrl + bargeMs). Daraus entsteht der ungesprochene REST, und das
   Gesprächsprotokoll wird auf das wirklich Gesagte gestutzt — das LLM und
   der Wiederholungs-Wächter dürfen nicht glauben, der Anrufer hätte Sätze
   gehört, die nie gespielt wurden.
3. FORTSETZEN: Nach dem Einwand-Zug wird der Rest mit einer Brücke
   ("Also, wo war ich: …") angehängt — aber NUR, wenn der Einwand den
   Zustand nicht bewegt hat: keine Buchung/Schreibaktion und keine neue
   Frage in der Antwort (fragt die Maschine schon, wäre der alte Rest
   doppelt oder veraltet). Fehlalarm (nichts/Echo gehört) => einfach an
   der Unterbrechungsstelle weitersprechen, ohne LLM.

Die Quittung ("Hm." / "Okay.") spielt das Dock SOFORT beim Stopp aus dem
vorgewärmten Cache — noch bevor Aufnahme und Einwand-Zug laufen.

Kein Netz, kein LLM — reine Textarbeit, JSON-tauglicher Zustand in der
Sitzung. Notaus: BARGE_WEITER=0 (Umgebungsvariable) => Eingang/Fortsetzen
sind stumm und /api/quittung liefert keine URLs — Verhalten wie vor W-BARGE.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Sofort-Quittungen beim Reinsprech-Stopp (Chef: "mit hmm oder okay").
QUITTUNGEN = ("Hm.", "Okay.")

# Brücken zurück zum unterbrochenen Rest — rotieren, nie zweimal dieselbe
# in Folge (Wiederholungs-Wächter-Regel gilt auch hier).
BRUECKEN = (
    "Also, wo war ich:",
    "Zurück zu dem, was ich gerade sagte:",
    "Also, weiter:",
)

# Protokoll-Platzhalter, wenn der Anrufer VOR dem ersten Satz reinsprach.
ABGEBROCHEN = "(vom Anrufer unterbrochen)"

_SATZ_ENDE_RE = re.compile(r"(?<=[.!?…])\s+")

# Abbruch-Befehl im Einwand ("Stopp.", "Hör auf!"): der Anrufer will die
# Ansage NICHT zu Ende hören — der Rest wird verworfen, nie fortgesetzt.
# Live 29.08.2026: auf "Stopp." sagte Bianca "Alles klar, ich höre auf …
# Also, wo war ich: …" und wiederholte die komplette Ansage.
_ABBRUCH_RE = re.compile(
    r"\b(?:aufh(?:ö|oe)r(?:en|st)?|h(?:ö|oe)r(?:en)?\s+(?:sie\s+)?(?:bitte\s+)?auf|"
    r"sei(?:en\s+sie)?\s+(?:bitte\s+)?(?:still|leise|ruhig)|"
    r"ruhe\s+(?:bitte|jetzt)|schluss\s+(?:jetzt|damit)|lass(?:en\s+sie)?\s+das|"
    r"nicht\s+weiter(?:reden|sprechen)|genug\s+(?:jetzt|davon))\b",
    re.I,
)
_ABBRUCH_KURZ = {"stopp", "stop", "halt", "schluss", "genug", "ruhe", "still", "leise"}


def ist_abbruch(text: str) -> bool:
    """Will der Anrufer die Wiedergabe beenden (nicht nur einwenden)?"""
    t = _s(text)
    if not t:
        return False
    if _ABBRUCH_RE.search(t):
        return True
    toks = _norm(t).split()
    return 0 < len(toks) <= 3 and any(tok in _ABBRUCH_KURZ for tok in toks)


def enabled() -> bool:
    return os.environ.get("BARGE_WEITER", "1").strip().lower() not in ("0", "false", "no")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _norm(text: str) -> str:
    """Vergleichsform wie im Wiederholungs-Wächter: klein, ohne Satzzeichen."""
    return " ".join(re.sub(r"[^a-zäöüß0-9 ]", " ", _s(text).casefold()).split())


def saetze(text: str) -> list[str]:
    return [x for x in _SATZ_ENDE_RE.split(_s(text)) if x]


def merken(sit: dict, *, url: str, karte: dict, text: str,
           vorab_text: str = "", vorab_url: str = "") -> None:
    """Die gerade gesprochene Äußerung als Satz-Karte in die Sitzung legen.

    ``karte`` kommt aus dienst.stimme/stimme_stream — die Listen darin
    (saetze, endenMs) werden REFERENZIERT, nicht kopiert: der Stream-Feeder
    füllt endenMs weiter, während schon gesprochen wird.
    """
    sit["ausspr"] = {
        "url": _s(url),
        "vorabText": _s(vorab_text),
        "vorabUrl": _s(vorab_url),
        "saetze": karte.get("saetze") if isinstance(karte.get("saetze"), list) else [],
        "endenMs": karte.get("endenMs") if isinstance(karte.get("endenMs"), list) else [],
        "text": _s(text),
    }


def eingang(sit: dict, barge_url: str, barge_ms: Any) -> bool:
    """Dock-Meldung: Wiedergabe von ``barge_url`` wurde bei ``barge_ms``
    unterbrochen. Merkt den ungesprochenen Rest (sit["unterbrochen"]) und
    stutzt das Gesprächsprotokoll auf das wirklich Gesagte.
    True = es gibt einen Rest, an dem fortgefahren werden kann."""
    sit.pop("unterbrochen", None)
    if not enabled():
        return False
    a = sit.get("ausspr") or {}
    url = _s(barge_url)
    if not url:
        return False
    try:
        ms = max(0.0, float(barge_ms or 0.0))
    except (TypeError, ValueError):
        ms = 0.0
    alle = [s for s in (a.get("saetze") or []) if _s(s)]
    gesprochen: list[str] = []
    rest: list[str] = []
    if url == _s(a.get("vorabUrl")):
        # Schon der Vorab-Satz (eigenes Audio VOR dem Antwort-Audio) wurde
        # unterbrochen — nichts gilt als gehört, alles ist Rest.
        if _s(a.get("vorabText")):
            rest.append(_s(a.get("vorabText")))
        rest.extend(alle)
    elif url == _s(a.get("url")):
        if _s(a.get("vorabText")):
            gesprochen.append(_s(a.get("vorabText")))
        enden = a.get("endenMs") or []
        for i, satz in enumerate(alle):
            ende = enden[i] if i < len(enden) else None
            if isinstance(ende, (int, float)) and float(ende) <= ms:
                gesprochen.append(satz)
            else:
                # kein End-Zeitpunkt (noch nicht gerendert / Render-Fehler)
                # oder nach der Unterbrechung => ungesprochen.
                rest.append(satz)
    else:
        # Fremdes Audio (Füller, Jingle, Stups) — keine Karte, kein Rest.
        return False
    if not rest:
        return False
    sit["unterbrochen"] = {"rest": rest, "gesprochen": " ".join(gesprochen).strip()}
    _protokoll_stutzen(sit, sit["unterbrochen"]["gesprochen"])
    return True


def _protokoll_stutzen(sit: dict, gesprochen: str) -> None:
    """Die letzte Assistenten-Nachricht trägt die volle GEPLANTE Antwort —
    nach dem Barge hat der Anrufer aber nur den Anfang gehört. Für den
    LLM-Kontext und den Wiederholungs-Wächter zählt das wirklich Gesagte
    (sonst würde der Wächter den später gesprochenen Rest als 'schon
    gesagt' streichen)."""
    msgs = sit.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return
    if msgs[-1].get("role") != "assistant":
        return
    msgs[-1]["content"] = _s(gesprochen) or ABGEBROCHEN


def nachtragen(sit: dict, text: str) -> None:
    """Später doch gesprochenen Text (Brücke + Rest) ans Protokoll anfügen —
    wie stille.anhaengen: an die letzte Assistenten-Antwort, keine neue
    Nachricht (das Chat-Template bleibt sauber)."""
    text = _s(text)
    if not text:
        return
    msgs = sit.get("messages")
    if not isinstance(msgs, list):
        return
    if msgs and msgs[-1].get("role") == "assistant" and isinstance(msgs[-1].get("content"), str):
        inhalt = _s(msgs[-1].get("content"))
        msgs[-1]["content"] = (inhalt + " " + text).strip() if inhalt != ABGEBROCHEN else text
    else:
        msgs.append({"role": "assistant", "content": text})


def ist_echo(sit: dict, gesagt: str) -> bool:
    """Lautsprecher-Echo der eigenen Stimme? Nur bei aktivem Barge geprüft.
    Kurze echte Reaktionen ("ja", "nein", "stopp") werden NIE geschluckt —
    erst ab drei Wörtern, und nur wenn das Gehörte wortgleich im gerade
    Gesagten steckt (Claras Barge-in-Echo-Regel, aufs Dock übersetzt)."""
    u = sit.get("unterbrochen")
    if not isinstance(u, dict) or not enabled():
        return False
    g = _norm(gesagt)
    if not g or len(g.split()) < 3:
        return False
    gespr = _norm(u.get("gesprochen") or "")
    return bool(gespr) and g in gespr


def fortsetzen(sit: dict, text: str, reply: dict | None = None,
               gesagt: str = "") -> str:
    """Nach dem Einwand-Zug: unterbrochenen Rest anhängen — oder verwerfen.

    Verworfen wird, wenn der Einwand den Zustand bewegt hat: eine Buchung/
    Schreibaktion lief (reply["book"]) oder die Antwort stellt schon eine
    Frage (dann treibt die Maschine neu — der alte Rest wäre doppelt oder
    veraltet). Ebenso bei einem Abbruch-Befehl ("Stopp.", "Hör auf!"):
    wer stoppt, will den Rest NICHT hören. Wortgleich in der Antwort
    enthaltene Rest-Sätze fallen weg.
    """
    u = sit.pop("unterbrochen", None)
    t = _s(text)
    if not isinstance(u, dict) or not enabled():
        return t
    rest = [s for s in (u.get("rest") or []) if _s(s)]
    if not t or not rest:
        return t
    if ist_abbruch(gesagt):
        return t
    if (reply or {}).get("book"):
        return t
    if "?" in t:
        return t
    da = {_norm(s) for s in saetze(t)}
    rest = [s for s in rest if _norm(s) and _norm(s) not in da]
    if not rest:
        return t
    n = int(sit.get("brueckeNr") or 0)
    sit["brueckeNr"] = n + 1
    anhang = f"{BRUECKEN[n % len(BRUECKEN)]} {' '.join(rest)}"
    nachtragen(sit, anhang)
    return _s(f"{t} {anhang}")


def wiederaufnahme(sit: dict) -> str:
    """Fehlalarm oder leerer Einwurf: Text, mit dem die Stimme an der
    Unterbrechungsstelle weiterspricht (ohne Brücke, ohne LLM). Räumt den
    Zustand und trägt den Rest ins Protokoll nach. '' = nichts zu tun."""
    u = sit.get("unterbrochen")
    if not isinstance(u, dict) or not enabled():
        return ""
    sit.pop("unterbrochen", None)
    rest = [s for s in (u.get("rest") or []) if _s(s)]
    text = " ".join(rest).strip()
    if text:
        nachtragen(sit, text)
    return text
