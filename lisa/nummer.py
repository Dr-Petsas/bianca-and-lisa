"""Falsche Rufnummer: aufnehmen, rückbestätigen, Akte oder Notiz schreiben.

Chef 30.08.2026: Lisa wählt eine Nummer, sitzt jemand anderes am Apparat
oder die Nummer stimmt nicht. Dann nett nach der richtigen Nummer fragen.
Die kann die des Partners sein. Viele müssen im Handy oder auf einem Zettel
suchen — Zeit lassen, nicht nach vier Sekunden stupsen. Nichts erfinden.
Dieselbe Nummern-Maschine wie Bianca (hören, Null nachziehen, Rückbestätigung).
"""

from __future__ import annotations

import re
from typing import Any

from bianca import telefon
from kern import calendar, patients

FRAGEN = "fragen"
SUCHEN = "suchen"
CHECK = "check"
WEM = "wem"
FERTIG = "fertig"

_STILLE_DIKTAT = 1300
_STILLE_SUCHE = 2200
_WARTE_SUCHE = 18000
_WARTE_DIKTAT = 8000

_SUCHEN = re.compile(
    r"\b(moment|augenblick|sekunde|suche|such|warte|handy|zettel|"
    r"nachschau\w*|nachguck\w*|nachseh\w*|gucke|schaue|find\w*)\b",
    re.I,
)
_KENNE_NICHT = re.compile(
    r"weiß ich nicht|weiss ich nicht|keine ahnung|hab(?:e)? (?:ich )?nicht|"
    r"kenne (?:ich |die )?(?:nummer )?nicht|hab(?:e)? keine|nicht da|"
    r"kann ich nicht|geht nicht",
    re.I,
)
_PARTNER = re.compile(
    r"\b(partner\w*|mann|frau|freundin|freund|ehemann|ehefrau|freundin)\b",
    re.I,
)
_AKTE = re.compile(
    r"\b(bei (?:ihm|ihr|dem patienten)|für (?:ihn|sie)|seine|ihre|"
    r"hinterleg\w*|eintrag\w*|akte|von \w+)\b",
    re.I,
)
_MEINE = re.compile(
    r"\b(meine|mir|ich selbst|meine eigene|von mir)\b",
    re.I,
)
_JA = re.compile(r"\b(ja|jawohl|genau|richtig|stimmt|korrekt|jup|jo)\b", re.I)
_NEIN = re.compile(r"\b(nein|nee|ne|nö|noe|falsch|nicht|anderer|andere)\b", re.I)
_FALSCHE_NR = re.compile(
    r"nummer\s+(?:ist\s+)?(?:falsch|verkehrt|alt)|falsche\s+nummer|"
    r"nicht mehr (?:diese|die) nummer|andere nummer|neue nummer|"
    r"rufen sie (?:uns |sie )?(?:unter|auf)|erreichen (?:sie|uns) unter|"
    r"haben sie sich verwählt|verwählt|falsch verbunden",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _zielname(sit: dict) -> str:
    p = sit.get("patient") or {}
    name = _s(p.get("name"))
    if not name:
        name = f"{_s(p.get('firstName'))} {_s(p.get('lastName'))}".strip()
    return name


def stand(sit: dict) -> dict:
    n = sit.get("lisaNummer")
    if not isinstance(n, dict):
        n = {
            "phase": "",
            "offen": "",
            "ok": "",
            "teil": "",
            "rolle": "",
            "werSagt": "",
        }
        sit["lisaNummer"] = n
    return n


def aktiv(sit: dict) -> bool:
    return stand(sit).get("phase") in {FRAGEN, SUCHEN, CHECK, WEM}


def sucht(sit: dict) -> bool:
    return stand(sit).get("phase") == SUCHEN


def stille_fuer(sit: dict) -> dict[str, int]:
    """Ruhe-Schwelle und Wartezeit, bevor der Stups kommt."""
    ph = stand(sit).get("phase")
    if ph == SUCHEN:
        return {"stilleMs": _STILLE_SUCHE, "stilleWarteMs": _WARTE_SUCHE}
    if ph in {FRAGEN, CHECK, WEM}:
        return {"stilleMs": _STILLE_DIKTAT, "stilleWarteMs": _WARTE_DIKTAT}
    return {"stilleMs": 500}


def frage_nach_nummer(sit: dict, *, wer: str = "") -> str:
    n = stand(sit)
    n["phase"] = FRAGEN
    if wer:
        n["werSagt"] = wer
    name = _zielname(sit)
    if name:
        return (
            f"Kein Problem. Wissen Sie, unter welcher Nummer ich {name} "
            "erreiche? Nehmen Sie sich ruhig Zeit — im Handy nachschauen "
            "ist völlig in Ordnung."
        )
    return (
        "Kein Problem. Haben Sie eine andere Nummer, unter der ich die "
        "Person erreiche? Nehmen Sie sich ruhig Zeit."
    )


def anstoss(sit: dict, gesagt: str) -> str:
    """Leerer String, oder die erste Frage, wenn mitten im Gespräch eine
    falsche Nummer zur Sprache kommt."""
    if aktiv(sit):
        return ""
    t = _s(gesagt)
    if not _FALSCHE_NR.search(t):
        return ""
    gehoert = telefon.aus_satz(t)
    if gehoert:
        n = stand(sit)
        n["offen"] = gehoert
        n["phase"] = CHECK
        return _readback(gehoert)
    return frage_nach_nummer(sit)


def _readback(nummer: str) -> str:
    z = telefon.sprechbar(nummer)
    z = z[:1].upper() + z[1:] if z else z
    return f"Ich wiederhole die Nummer. {z}. Stimmt das so?"


def _teil_frage(teil: str) -> str:
    if teil.startswith("0") and 2 <= len(teil) <= 5:
        return (
            "Ja, ich habe den Anfang — diktieren Sie bitte weiter, "
            "Ziffer für Ziffer. Kein Stress."
        )
    return (
        "Die Nummer ist noch nicht vollständig. Einmal von vorn, "
        "Ziffer für Ziffer — die Null am Anfang bitte mit. Ich warte."
    )


def _wem_frage(sit: dict) -> str:
    name = _zielname(sit)
    if name:
        return (
            f"Ist das die Nummer von {name}, oder Ihre eigene — "
            "zum Beispiel die des Partners?"
        )
    return "Ist das die Nummer der gesuchten Person, oder Ihre eigene?"


def _ablegen(sit: dict) -> str:
    n = stand(sit)
    nummer = n.get("ok") or ""
    if not nummer:
        return "Danke, dann versuche ich es auf einem anderen Weg."
    name = _zielname(sit)
    rolle = n.get("rolle") or "unbekannt"
    wer = n.get("werSagt") or ""
    extra = f" Genannt von {wer}." if wer else ""
    if rolle == "partner":
        note = (
            f"Angerufene Nummer war nicht {name or 'der Patient'}. "
            f"Eigene/Partner-Nummer genannt: {nummer}.{extra} Akte nicht überschrieben."
        )
        _notiz(sit, note)
        n["phase"] = FERTIG
        return (
            "Danke, ich notiere Ihre Nummer für die Praxis und rufe "
            f"{name or 'dort'} nicht unter dieser Nummer an."
        )
    pat = sit.get("patient") or {}
    pid = _s(pat.get("id")) or _s((sit.get("booking") or {}).get("patientId"))
    if pid and rolle in {"patient", "akte", ""}:
        res = patients.telefon_aktualisieren(sit.get("tenant") or {}, pid, nummer)
        if res.get("ok"):
            pat["phone"] = nummer
            sit["patient"] = pat
            ctx = sit.setdefault("booking", {})
            ctx["phone"] = nummer
            n["phase"] = FERTIG
            if res.get("dryRun"):
                return (
                    f"Die Nummer für {name or 'die Akte'} hätte ich jetzt "
                    "umgetragen — der Test schreibt die Kartei noch nicht."
                )
            return f"Danke, ich habe die Nummer für {name or 'die Akte'} eingetragen."
        _notiz(sit, f"Neue Nummer {nummer} für {name or 'Patient'} — Update fehlgeschlagen.{extra}")
        n["phase"] = FERTIG
        return "Danke, ich gebe die neue Nummer der Praxis mit."
    _notiz(sit, f"Neue Nummer {nummer} für {name or 'die gesuchte Person'}.{extra}")
    n["phase"] = FERTIG
    return f"Danke, ich rufe {name or 'dort'} unter der neuen Nummer an."


def _notiz(sit: dict, text: str) -> None:
    alt = _s(sit.get("praxisNotiz"))
    sit["praxisNotiz"] = (alt + " " + text).strip() if alt else text
    ctx = sit.get("booking") or {}
    if ctx.get("appointmentId"):
        try:
            calendar.note_appointment(sit.get("tenant") or {}, ctx, sit, note=text)
        except Exception as e:
            print(f"lisa-nummer notiz fail {e}", flush=True)


def naechster_zug(sit: dict, gesagt: str) -> dict | None:
    """Deterministische Nummer-Aufnahme. None = nicht zuständig."""
    n = stand(sit)
    if n.get("phase") not in {FRAGEN, SUCHEN, CHECK, WEM}:
        start = anstoss(sit, gesagt)
        if not start:
            return None
        return {"text": start, "warten": True}
    t = _s(gesagt)
    if not t:
        return {"text": "Ich warte — sagen Sie die Nummer, wenn Sie soweit sind.", "warten": True}

    if n["phase"] == WEM:
        if _PARTNER.search(t) or _MEINE.search(t):
            n["rolle"] = "partner"
        elif _AKTE.search(t) or _JA.search(t):
            n["rolle"] = "patient"
        elif _NEIN.search(t):
            n["rolle"] = "partner"
        else:
            n["rolle"] = "patient"
        return {"text": _ablegen(sit)}

    if n["phase"] == CHECK:
        if _JA.search(t) and not _NEIN.search(t):
            n["ok"] = n.get("offen") or ""
            n["phase"] = WEM
            return {"text": _wem_frage(sit), "warten": True}
        if _NEIN.search(t):
            n["offen"] = ""
            n["teil"] = ""
            n["phase"] = FRAGEN
            return {"text": "Dann noch einmal, ganz in Ruhe, Ziffer für Ziffer.", "warten": True}
        neu = telefon.aus_satz(t)
        if neu:
            n["offen"] = neu
            return {"text": _readback(neu), "warten": True}
        return {"text": "Stimmt die Nummer so — ja oder nein?", "warten": True}

    # FRAGEN oder SUCHEN
    if _KENNE_NICHT.search(t) and not telefon.aus_satz(t):
        n["phase"] = FERTIG
        return {
            "text": "Kein Problem, dann versuche ich es auf einem anderen Weg. Vielen Dank."
        }
    if _SUCHEN.search(t) and not telefon.aus_satz(t):
        n["phase"] = SUCHEN
        return {
            "text": "Gern, nehmen Sie sich Zeit. Ich warte, bis Sie die Nummer haben.",
            "warten": True,
        }
    voll = telefon.aus_satz(t)
    if voll:
        n["offen"] = voll
        n["teil"] = ""
        n["phase"] = CHECK
        if _PARTNER.search(t):
            n["rolle"] = "partner"
        return {"text": _readback(voll), "warten": True}
    roh = telefon.ziffern(t)
    roh = telefon.mit_fuehrender_null(roh) if roh else ""
    if roh and 2 <= len(roh) < 10:
        n["teil"] = roh
        n["phase"] = SUCHEN
        return {"text": _teil_frage(roh), "warten": True}
    if n["phase"] == SUCHEN:
        return {
            "text": "Ich bin noch da. Sagen Sie die Nummer, wenn Sie sie haben.",
            "warten": True,
        }
    return {
        "text": "Sagen Sie die Nummer einfach Ziffer für Ziffer. Ich warte.",
        "warten": True,
    }
