"""Stille-Wächter: nach ~4 Sekunden Funkstille ergreift die Stimme selbst
das Wort (Chef 27.08.2026: "ein stille wächter der nach 4 sekunden stille
zurück auf die jobspur oder das letzte thema bringt").

Der Stups kommt NIE bei null an: Er sagt an, wo das Gespräch steht — welcher
Auftrag läuft, was schon eingesammelt ist, was noch fehlt (Bianca: Sammler +
offene Pflichtfrage; Lisa: Auftrag + zuletzt gestellte Frage). War gerade ein
Nebenthema am Zug (Talk-Floor), knüpft der ERSTE Stups dort an; der zweite
holt auf die Job-Spur. Nach MAX_STUPSE Stupsen ohne Antwort schweigt die
Stimme, bis der Anrufer wieder spricht — kein Endlos-Genöle.

Die 4 Sekunden misst das Browser-Dock (bianca_web/app.js, web/app.js) nach
dem Ende der eigenen Wiedergabe; der Dienst liefert auf POST /api/stille nur
den fertigen Stups-Zug. Hier liegt die stimmen-unabhängige Mechanik:
Zähler (JSON-tauglich in der Sitzung), Anreden, Frage-Wiederholung mit
Präfix (nie wortgleich — Wiederholungs-Wächter-Regel) und das Einhängen in
das Gesprächsprotokoll.
"""

from __future__ import annotations

import re
from typing import Any

# Richtwert fuer die Docks (dokumentiert an EINER Stelle): so lange darf es
# nach dem Sprech-Ende still sein, bevor der Stups kommt.
STUPS_NACH_S = 4.0
# Mehr als zwei Stupse in Folge sind Genoele — danach wartet die Stimme.
MAX_STUPSE = 2

_SATZ_ENDE_RE = re.compile(r"(?<=[.!?…])\s+")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _stand(sit: dict) -> dict:
    st = sit.get("stille")
    if not isinstance(st, dict):
        st = {}
        sit["stille"] = st
    st.setdefault("stupse", 0)
    st.setdefault("jobStups", False)
    return st


def reset(sit: dict) -> None:
    """Der Anrufer hat wieder gesprochen — Stups-Zaehlung beginnt von vorn."""
    st = _stand(sit)
    st["stupse"] = 0
    st["jobStups"] = False


def stups_zaehlen(sit: dict) -> int:
    """Naechste Stups-Nummer (1-basiert) — Cap prueft der Aufrufer."""
    st = _stand(sit)
    st["stupse"] = int(st.get("stupse") or 0) + 1
    return st["stupse"]


def job_stups_gemerkt(sit: dict) -> bool:
    """War schon ein Stups mit voller Stand-Ansage? Dann beim naechsten nur
    noch kurz die offene Frage — nicht denselben Sermon zweimal."""
    st = _stand(sit)
    war = bool(st.get("jobStups"))
    st["jobStups"] = True
    return war


def anrede(n: int) -> str:
    return "Sind Sie noch dran?" if n <= 1 else "Ich bin noch da."


def frage_praefix(satz: str) -> str:
    """Eine offene Frage wiederholen, ohne wortgleich zu werden."""
    satz = _s(satz)
    return f"Meine Frage war: {satz}" if satz else ""


def nur_fragesaetze(text: str) -> str:
    """Nur die Frage-Sätze eines Zuges — für den KURZEN Wiederhol-Stups:
    Begleitsätze ("Die brauche ich für ...") kamen schon beim ersten Mal
    und würden sonst wortgleich wiederholt."""
    saetze = [x for x in _SATZ_ENDE_RE.split(_s(text)) if x.rstrip().endswith("?")]
    return " ".join(saetze).strip()


def letzte_frage(msgs: list[dict]) -> str:
    """Der letzte Frage-Satz der juengsten Assistenten-Antwort — was war
    zuletzt offen? (Nur die juengste Antwort: aeltere Fragen sind bedient.)"""
    for m in reversed(msgs or []):
        if m.get("role") != "assistant":
            continue
        for satz in reversed(_SATZ_ENDE_RE.split(_s(m.get("content")))):
            if satz.rstrip().endswith("?"):
                return satz.strip()
        return ""
    return ""


def anhaengen(sit: dict, text: str) -> None:
    """Den Stups ins Gespraechsprotokoll haengen, damit Folgezuege (LLM und
    Wiederholungs-Wächter) ihn kennen. An die letzte Assistenten-Antwort
    anfuegen statt einer neuen Nachricht — das Chat-Template bleibt sauber."""
    text = _s(text)
    if not text:
        return
    msgs = sit.get("messages")
    if not isinstance(msgs, list):
        return
    if msgs and msgs[-1].get("role") == "assistant" and isinstance(msgs[-1].get("content"), str):
        msgs[-1]["content"] = (_s(msgs[-1].get("content")) + " " + text).strip()
    else:
        msgs.append({"role": "assistant", "content": text})
