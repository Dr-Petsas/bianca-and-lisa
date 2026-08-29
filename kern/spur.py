"""Wächter-Spur (W-BK-3, Chef 29.08.2026): welcher Wächter hat eingegriffen?

Der Baukasten-Test soll je Antwort sehen, welche Regel/Regex/Wache den Zug
geformt hat ("welche regel regex wächter für diese antwort gegriffen hat").
Jeder Wächter meldet sich hier mit einem kurzen Namen + Detail; der Dienst
haengt die Liste ADDITIV als "waechter" an die Zug-Antwort und ins
Sitzungsprotokoll. Kein Netz, kein LLM — nur eine Liste in der Sitzung.

Namen (Stand 29.08.2026):
  barge-eingang        Anrufer hat reingesprochen, Rest berechnet
  barge-abbruch        Abbruch-Befehl — Rest verworfen
  barge-fortsetzen     Bruecke + ungesprochener Rest angehaengt
  barge-weiter         Fehlalarm: an der Unterbrechungsstelle fortgesetzt
  barge-echo           Lautsprecher-Echo der eigenen Stimme verworfen
  halbsatz-warte       unfertiger Satz — nicht geantwortet, weitergehoert
  halbsatz-fuge        Fragment mit dem Folgezug zusammengefuegt
  halbsatz-flush       Fragment allein beantwortet (nichts nachgekommen)
  wiederholung-variante  offene Frage gegen naechste Formulierung getauscht
  wiederholung-gestrichen  wortgleicher Satz gestrichen
  stille-stups         Stille-Waechter hat das Wort ergriffen
  talk-floor           Nebenthema hat den Floor (Talk/Blended/Zurueck)
  notfall-vorrang      Schmerz/Notfall raeumt alle Nebenthemen
"""

from __future__ import annotations

from typing import Any

_MAX = 24


def neu(sit: dict) -> None:
    """Zu Zug-Beginn aufrufen: die Spur des vorigen Zugs verwerfen."""
    sit["_spur"] = []


def merken(sit: dict, waechter: str, detail: str = "") -> None:
    """Einen Eingriff notieren — doppelte direkt hintereinander fallen weg."""
    try:
        spur = sit.setdefault("_spur", [])
        eintrag = {"w": str(waechter), "d": " ".join(str(detail or "").split())[:160]}
        if spur and spur[-1] == eintrag:
            return
        spur.append(eintrag)
        del spur[:-_MAX]
    except Exception:
        pass  # die Spur darf NIE einen Zug brechen


def abholen(sit: dict) -> list[dict[str, Any]]:
    """Spur entnehmen (fuer die Antwort dieses Zugs)."""
    try:
        return list(sit.pop("_spur", []) or [])
    except Exception:
        return []
