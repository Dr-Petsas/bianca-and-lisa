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
# Fix 5 (13.09.2026, vor den Feldtests): 6 -> 8. Mit MAX_STUPSE=2 sind das
# VIER Stille-Phasen von je ~8 s Funkstille (statt drei) — ein Anrufer, der
# am Tresen nachschaut oder einen Zettel sucht, wird nicht schon beim
# dritten Nachdenken verabschiedet. Die 15er-Schleife aus Session 9395e2ce
# faengt die Notleine damit weiterhin.
GESAMT_MAX = 8

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
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    if tenant.get("presenceEinmal") is True:
        return gesamt(sit) <= 1
    return gesamt(sit) <= PRESENCE_BIS


def kompakt_fertig(sit: dict) -> bool:
    """Opt-in: einmal Presence, einmal Jobfrage, danach sauber beenden."""
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    return tenant.get("presenceEinmal") is True and gesamt(sit) > 2


def anrede(n: int) -> str:
    return "Sind Sie noch dran?" if n <= 1 else "Ich bin noch da."


_PRAEFIXE = (
    "Meine Frage war: {satz}",
    "Noch einmal die Frage: {satz}",
    "Ich frage noch einmal: {satz}",
    "Kurz zurück zur Frage: {satz}",
    "Damit ich weiterkomme: {satz}",
)


_VORSATZ_RE = re.compile(
    r"^\s*(?:"
    r"entschuldigung,?\s+das\s+kam\s+nicht\s+sicher\s+an\.?"
    r"|meine\s+frage\s+war:"
    r"|noch\s+einmal\s+die\s+frage:"
    r"|ich\s+frage\s+noch\s+einmal:"
    r"|kurz\s+zur(?:ü|ue)ck\s+zur\s+frage:"
    r"|damit\s+ich\s+weiterkomme:"
    r"|damit\s+ich\s+das\s+f(?:ü|ue)r\s+sie\s+erledigen\s+kann:"
    r"|sind\s+sie\s+noch\s+dran\?"
    r"|ich\s+bin\s+noch\s+da\."
    r")\s*",
    re.I,
)
_JA_NEIN_ZUSATZ_RE = re.compile(r"\s*ein\s+kurzes\s+ja\s+oder\s+nein\s+gen(?:ü|ue)gt\.?\s*$", re.I)
_PRESENCE_RE = re.compile(r"^\s*(?:sind\s+sie\s+noch\s+dran|ich\s+bin\s+noch\s+da)\W*$", re.I)
_GRUSS_RE = re.compile(r"\bsie\s+sprechen\s+mit\b|\bhier\s+ist\s+\w+\s+von\b", re.I)
GRUSS_ERSATZ = "Wie kann ich Ihnen helfen?"


def kern_frage(satz: str) -> str:
    """Die nackte Frage ohne frühere Wiederhol-Vorsätze.

    Live 05.10.2026 (be543d80): jede Wiederholung setzte ihren Vorsatz VOR
    den schon vorhandenen — „Ich frage noch einmal: Noch einmal die Frage:
    Waren Sie …?“. Vorsätze, Entschuldigung und Ja/Nein-Zusatz fallen
    deshalb vor dem neuen Vorsatz weg; eine Begrüßung wird nie wörtlich
    als „Frage“ wiederholt."""
    satz = _s(satz)
    while True:
        neu = _VORSATZ_RE.sub("", satz, count=1)
        if neu == satz:
            break
        satz = neu
    satz = _JA_NEIN_ZUSATZ_RE.sub("", satz).strip()
    if _GRUSS_RE.search(satz):
        return GRUSS_ERSATZ
    if _PRESENCE_RE.match(satz):
        return ""
    return satz


def frage_praefix(satz: str, sit: dict | None = None) -> str:
    """Eine offene Frage wiederholen, ohne wortgleich zu werden.

    Mit `sit` rotiert der Vorsatz je Aufruf (Replay 53986f42 z10-z15: fuenfmal
    wortgleich "Meine Frage war: Und der Vorname?" — der Wiederholungs-
    Waechter sah den Praefix-Satz als neu, der Anrufer hoerte eine Schleife).
    Ohne `sit` bleibt der feste erste Vorsatz (Lisa, Korpus, Alt-Aufrufer)."""
    satz = kern_frage(satz)
    if not satz:
        return ""
    if not isinstance(sit, dict):
        return _PRAEFIXE[0].format(satz=satz)
    n = int(sit.get("fragePraefixN") or 0)
    sit["fragePraefixN"] = n + 1
    return _PRAEFIXE[n % len(_PRAEFIXE)].format(satz=satz)


def nur_fragesaetze(text: str) -> str:
    """Nur die Frage-Sätze eines Zuges — für den KURZEN Wiederhol-Stups:
    Begleitsätze ("Die brauche ich für ...") kamen schon beim ersten Mal
    und würden sonst wortgleich wiederholt."""
    saetze = [x for x in _SATZ_ENDE_RE.split(_s(text)) if x.rstrip().endswith("?")]
    return " ".join(saetze).strip()


def letzte_frage(msgs: list[dict]) -> str:
    """Der letzte Frage-Satz der juengsten Assistenten-Antwort — was war
    zuletzt offen? (Nur die juengste Antwort: aeltere Fragen sind bedient.)
    Presence-Floskeln sind keine offene Frage — dann zählt die Frage davor."""
    for m in reversed(msgs or []):
        if m.get("role") != "assistant":
            continue
        for satz in reversed(_SATZ_ENDE_RE.split(_s(m.get("content")))):
            if satz.rstrip().endswith("?") and not _PRESENCE_RE.match(satz):
                return satz.strip()
        if _PRESENCE_RE.match(_s(m.get("content")) or "x"):
            continue
        return ""
    return ""


def hoerfehler_nachfrage(
    sit: dict,
    *,
    frage: str = "",
    ja_nein: bool = False,
) -> str:
    """Die wirklich offene Frage kurz und abwechslungsreich wiederholen.

    So verliert ein akustisch unklarer Kurz-Zug den Formularfaden nicht.
    ``ja_nein`` nennt den erwarteten Antworttyp nur dann zusaetzlich, wenn
    die Frage ihn nicht ohnehin schon ausspricht.
    """
    offen = kern_frage(_s(frage) or letzte_frage((sit or {}).get("messages") or []))
    if not offen:
        return ""
    wiederholt = frage_praefix(offen, sit)
    if ja_nein and not re.search(r"\bja\b.{0,16}\bnein\b", offen, re.I):
        wiederholt += " Ein kurzes Ja oder Nein genügt."
    return f"Entschuldigung, das kam nicht sicher an. {wiederholt}"


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
