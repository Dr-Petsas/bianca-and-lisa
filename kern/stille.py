"""Stille-Wächter: nach ~4 Sekunden Funkstille ergreift die Stimme selbst
das Wort (Chef 27.08.2026).

W-STUPS-PRESENCE 01.09.2026 (phone_agent): der ERSTE Stups ist nur Presence
(„Sind Sie noch dran?"), der ZWEITE die kurze offene Frage — nie die
Pflichtfrage sofort wiederholen. Denk-Cue unterdrückt Stups kurz.
Nach MAX_STUPSE Stupsen ohne Antwort schweigt die Stimme, bis der
Anrufer wieder spricht — kein Endlos-Genöle.

W-STUPS-GESAMT 12.09.2026 (Live-Befund Session 9395e2ce, 109 Züge): der
Zähler `stupse` wird bei JEDEM echten Anrufer-Satz auf 0 gesetzt. In einem
langen Gespräch, in dem der Anrufer immer wieder am Thema vorbei redet,
wechselten sich deshalb 15 Mal "Sind Sie noch dran?" und dieselbe offene
Frage ab — MAX_STUPSE greift nur INNERHALB einer Stillephase. Seitdem läuft
zusätzlich ein Zähler über den GANZEN Anruf (`gesamt`):

- ab `PRESENCE_BIS` Stupsen im Anruf entfällt die Presence-Floskel und es
  kommt sofort die konkrete offene Frage (Presence hat der Anrufer oft genug
  gehört),
- ab `GESAMT_MAX` Stupsen ist das Gespräch erkennbar tot: die Notleine
  verabschiedet sich freundlich und legt auf (kern/abschied.notbremse_satz).

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

from kern import spur

# Richtwert fuer die Docks (dokumentiert an EINER Stelle): so lange darf es
# nach dem Sprech-Ende still sein, bevor der Stups kommt.
STUPS_NACH_S = 4.0
# Mehr als zwei Stupse in Folge sind Genoele — danach wartet die Stimme.
MAX_STUPSE = 2
# W-STUPS-GESAMT: bis hierhin darf die Presence-Floskel im ANRUF kommen.
PRESENCE_BIS = 3
# So viele Stupse im ganzen Anruf: dann ist das Gespraech tot (Notleine).
GESAMT_MAX = 6

_SATZ_ENDE_RE = re.compile(r"(?<=[.!?…])\s+")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _stand(sit: dict) -> dict:
    st = sit.get("stille")
    if not isinstance(st, dict):
        st = {}
        sit["stille"] = st
    st.setdefault("stupse", 0)
    st.setdefault("gesamt", 0)
    return st


def reset(sit: dict) -> None:
    """Der Anrufer hat wieder gesprochen — Stups-Zaehlung beginnt von vorn.

    `gesamt` bleibt bewusst stehen: er misst, wie oft Bianca im GANZEN Anruf
    ins Leere gesprochen hat (W-STUPS-GESAMT)."""
    st = _stand(sit)
    st["stupse"] = 0


def stups_zaehlen(sit: dict) -> int:
    """Naechste Stups-Nummer (1-basiert) — Cap prueft der Aufrufer."""
    st = _stand(sit)
    st["stupse"] = int(st.get("stupse") or 0) + 1
    st["gesamt"] = int(st.get("gesamt") or 0) + 1
    spur.merken(sit, "stille-stups", f"{st['stupse']}/{st['gesamt']}")
    return st["stupse"]


def gesamt(sit: dict) -> int:
    """Stupse im ganzen Anruf — Grundlage der Notleine."""
    return int(_stand(sit).get("gesamt") or 0)


def gespraech_tot(sit: dict) -> bool:
    """Zu viele Stupse im Anruf: weiter zu nöleln bringt nichts mehr."""
    return gesamt(sit) >= GESAMT_MAX


def presence_erlaubt(sit: dict) -> bool:
    """Hat der Anrufer „Sind Sie noch dran?" schon oft genug gehört?"""
    return gesamt(sit) <= PRESENCE_BIS


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
