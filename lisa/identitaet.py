"""Sitzt der Richtige am Telefon? Deterministischer Check vor dem Anliegen.

Chef 27.08.2026: Nach der Begruessung fragt Lisa "Spreche ich mit Vorname
Nachname?".
  ja    -> Anrede mit Nachnamen, dann Auftrag ("ich rufe im Auftrag von
           Doktor X an, um ...").
  nein  -> "Kann ich bitte Vorname Nachname sprechen?"
  Kommt darauf "das ist mein Sohn", "worum geht es", "Sie koennen mit mir
  sprechen", "der schlaeft", "ist nicht da" oder dergleichen: einfach mit
  DIESEM Gespraechspartner weitermachen.

Bewusst ohne LLM: der Check darf weder Wartezeit kosten noch uebersprungen
oder umformuliert werden. Erst danach uebernimmt das Modell.
"""

from __future__ import annotations

import re

from lisa.greeting import anrede
from lisa import nummer

# Zustaende in sit["idCheck"]:
#   frage  – Begruessung ist raus, wir warten auf die Antwort
#   holen  – "nein" kam, wir haben nach der Zielperson gefragt
#   warten – jemand holt die Zielperson ans Telefon
#   nummer – falsche Person; wir fragen nach einer anderen Rufnummer
#   fertig – Identitaet geklaert, ab hier spricht das Modell
FRAGE, HOLEN, WARTEN, NUMMER, FERTIG = "frage", "holen", "warten", "nummer", "fertig"

_JA = re.compile(
    r"\b(ja|jawohl|jup|jo|genau|richtig|korrekt|stimmt|selbst|persoenlich|persönlich|"
    r"am apparat|am telefon|spricht|der bin ich|die bin ich|das bin ich|bin ich)\b",
    re.I,
)
_NEIN = re.compile(
    r"\b(nein|nee|ne|nö|noe|nicht|falsch|verwaehlt|verwählt|verkehrt|niemand|"
    r"kenne ich nicht|gibt es hier nicht|wer ist da|wer spricht)\b",
    re.I,
)
# "Moment, ich hole ihn" — die Zielperson kommt gleich ans Telefon.
_HOLEN = re.compile(
    r"\b(moment|augenblick|sekunde|hole|hol ihn|hol sie|gebe ihn|gebe sie|geb ihn|"
    r"geb sie|verbinde|reiche weiter|gleich da|kommt gleich|warten sie)\b",
    re.I,
)
# "Das bin ich nicht, ich heiße …" — nicht der Gesuchte, übernimmt aber
# auch nicht das Anliegen. Dann nach der richtigen Nummer fragen.
_FREMDE = re.compile(
    r"das bin ich nicht|ich bin (?:es )?nicht|falsch verbunden|"
    r"haben sie sich verwählt|verwählt|falsche nummer|"
    r"ich heiße|ich heisse|mein name ist|"
    r"ich bin (?!seine|ihre|der|die|sein|ihr)\w+",
    re.I,
)
_FREMDE_NAME = re.compile(
    r"(?:ich bin|ich heiße|ich heisse|mein name ist|hier ist)\s+"
    r"(?!nicht|seine|ihre|der|die)([a-zäöüß\-]{2,}(?:\s+[a-zäöüß\-]{2,})?)",
    re.I,
)
# Dritter am Apparat: Zielperson nicht erreichbar ODER "reden Sie mit mir".
_DRITTER = re.compile(
    r"\b(sohn|tochter|kind|mann|frau|gatte|gattin|mutter|vater|eltern|schwester|bruder|"
    r"oma|opa|partner\w*|kollege|kollegin|"
    r"schlaeft|schläft|schlafen|nicht da|nicht zuhause|nicht zu hause|nicht hier|"
    r"unterwegs|arbeitet|auf arbeit|bei der arbeit|im urlaub|verreist|krank|"
    r"worum geht|worum handelt|was gibt es|um was geht|weshalb|warum rufen|"
    r"mit mir sprechen|mir sagen|mir ausrichten|ausrichten|weitergeben|bescheid sagen|"
    r"bin die mutter|bin der vater|bin seine|bin ihre)\b",
    re.I,
)


def _s(v: object) -> str:
    return " ".join(str(v or "").split()).strip()


def voller_name(patient: dict | None) -> str:
    p = patient or {}
    name = _s(p.get("name"))
    if not name:
        name = f"{_s(p.get('firstName'))} {_s(p.get('lastName'))}".strip()
    return name


def moeglich(patient: dict | None) -> bool:
    """Ohne Namen gibt es nichts zu bestaetigen — dann alter Ablauf."""
    return len(voller_name(patient).split()) >= 2


def frage_satz(patient: dict | None) -> str:
    name = voller_name(patient)
    return f"Spreche ich mit {name}?" if name else ""


def deute(text: str) -> str:
    """ja | nein | holen | dritter | fremd | unklar — Reihenfolge ist Absicht."""
    t = _s(text)
    if not t:
        return "unklar"
    if _HOLEN.search(t):
        return "holen"
    # "Nein, das ist mein Sohn" -> dritter schlaegt nein: nicht doppelt fragen.
    if _DRITTER.search(t):
        return "dritter"
    # "Das bin ich nicht" vor "das bin ich" (steht in _JA).
    # "Ja, ich bin Levi" darf nicht als fremd gelten.
    if _FREMDE.search(t):
        if _JA.search(t) and not re.search(r"\bnicht\b", t, re.I):
            return "ja"
        return "fremd"
    if _NEIN.search(t):
        return "nein"
    if _JA.search(t):
        return "ja"
    return "unklar"


def anliegen_satz(sit: dict) -> str:
    """Der Grund des Anrufs, moeglichst der vorbereitete Satz."""
    fertig = _s(sit.get("anliegen"))
    if fertig:
        return fertig
    from lisa.anliegen import notfalltext

    return notfalltext(sit)


def _mit_anrede(sit: dict) -> str:
    wen = anrede(sit.get("patient") or {})
    gruss = f"Guten Tag, {wen}." if wen else "Guten Tag."
    return f"{gruss} {anliegen_satz(sit)}".strip()


def _ohne_anrede(sit: dict, *, dank: str = "") -> str:
    kopf = f"{dank} " if dank else ""
    return f"{kopf}{anliegen_satz(sit)}".strip()


def _wer_sagt(gesagt: str) -> str:
    m = _FREMDE_NAME.search(_s(gesagt))
    return _s(m.group(1)) if m else ""


def _zu_nummer(sit: dict, gesagt: str) -> dict:
    sit["idCheck"] = NUMMER
    sit["idErgebnis"] = "fremd"
    return {"text": nummer.frage_nach_nummer(sit, wer=_wer_sagt(gesagt)), "warten": True}


def naechster_zug(sit: dict, gesagt: str) -> dict | None:
    """Antwort der Identitaets-Phase — oder None, wenn das Modell dran ist."""
    stand = _s(sit.get("idCheck"))
    if stand == NUMMER or nummer.aktiv(sit):
        zug = nummer.naechster_zug(sit, gesagt)
        if zug and nummer.stand(sit).get("phase") == nummer.FERTIG:
            sit["idCheck"] = FERTIG
        return zug
    if stand not in {FRAGE, HOLEN, WARTEN}:
        return None
    art = deute(gesagt)
    name = voller_name(sit.get("patient") or {})

    if art == "holen":
        sit["idCheck"] = WARTEN
        return {"text": "Gerne, ich warte einen Moment.", "warten": True}

    if stand == FRAGE:
        if art == "fremd":
            return _zu_nummer(sit, gesagt)
        if art == "dritter":
            sit["idCheck"] = FERTIG
            sit["idErgebnis"] = "dritter"
            return {"text": _ohne_anrede(sit, dank="Alles klar, danke.")}
        if art == "nein":
            sit["idCheck"] = HOLEN
            return {
                "text": f"Entschuldigen Sie bitte. Kann ich {name} sprechen?"
                if name else "Entschuldigen Sie bitte. Mit wem spreche ich?",
                "warten": True,
            }
        if art == "ja":
            sit["idCheck"] = FERTIG
            sit["idErgebnis"] = "bestaetigt"
            return {"text": _mit_anrede(sit)}
        # Unklar: einmal nachfassen, danach nicht weiter bohren.
        if not sit.get("idNachgefasst"):
            sit["idNachgefasst"] = True
            return {
                "text": f"Verzeihung, spreche ich mit {name}?" if name
                else "Verzeihung, mit wem spreche ich?",
                "warten": True,
            }
        sit["idCheck"] = FERTIG
        sit["idErgebnis"] = "unklar"
        return {"text": _ohne_anrede(sit)}

    # HOLEN / WARTEN: Zielperson kommt — oder die Nummer stimmt nicht.
    if art == "dritter":
        sit["idCheck"] = FERTIG
        sit["idErgebnis"] = "dritter"
        return {"text": _ohne_anrede(sit, dank="Alles klar, danke.")}
    if stand == WARTEN and art in {"ja", "unklar"}:
        sit["idCheck"] = FERTIG
        sit["idErgebnis"] = "bestaetigt"
        return {"text": _mit_anrede(sit)}
    if art == "ja":
        sit["idCheck"] = FERTIG
        sit["idErgebnis"] = "bestaetigt"
        return {"text": _mit_anrede(sit)}
    if art in {"fremd", "nein"}:
        return _zu_nummer(sit, gesagt)
    sit["idCheck"] = FERTIG
    sit["idErgebnis"] = "dritter"
    return {"text": _ohne_anrede(sit)}
