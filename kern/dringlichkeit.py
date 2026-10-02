"""Dringlichkeit aus dem Gesagten — vor Motiv und vor dem Suchfenster.

Patienten sagen den Schaden selten mit dem Katalogwort: „Zahn abgebrochen“,
„Brücke lose“, „Prothese kaputt“, „Melanomuntersuchung“, „Abszess in der
Schwangerschaft“. Drei alte Listen (anliegen_art, praxisregeln.akut, eilig)
trafen davon nur Teile und buchten danach wie eine normale Kontrolle.

Diese Karte ist die eine Bewertung. Sie bleibt am Anruf hängen (die höhere
Stufe gewinnt). Die Praxis entscheidet die Handlung:

- Sofort-kommen / 116 117 (Blessing-Marker oder Anliegen-Wahl) → bestehender
  Kommen-Satz, kein Kalender.
- Sonst Termin: Akut- oder Reparaturmotiv, Suche ab heute, ein fester Satz.
  Einen späteren Wunsch gilt erst, nachdem dieser Satz gesprochen wurde.

Melanom bleibt auf dem bestehenden Heute-oder-Kommen-Weg in ``eilig``.
Notaus: ``DRINGLICHKEIT=0``.
"""

from __future__ import annotations

import os
import re
from typing import Any

SATZ_HEUTE = (
    "Das klingt dringend. Ich suche Ihnen den frühesten Platz, "
    "am besten noch heute."
)

WEICHE_GRUENDE = frozenset({
    "zahnersatz-beratung",
    "kontrolluntersuchung",
    "kontrolle",
    "schwangerschaftsvorsorge",
    "vorsorge",
    "professionelle zahnreinigung",
})

_AKUT_MUSTER = [r"akut", r"notfall", r"schmerz"]
_REPARATUR_MUSTER = [r"ze\s+repar", r"repar", r"zahnersatz", r"\bze\b"]
_GYN_MUSTER = [r"akut", r"notfall", r"infekt", r"sprech", r"kontroll"]

_ZE = r"bruecke|krone|prothese|zahnersatz|gebiss|verblendung"
_SCHADEN = (
    r"lose|locker|wackel\w*|kaputt|gebrochen|abgebrochen|zerbrochen|"
    r"rausgefallen|herausgefallen|abgefallen|abgeplatzt|"
    r"haelt\s+nicht|sitzt\s+nicht"
)
_ZE_KAPUTT_RE = re.compile(
    rf"(?:{_ZE})[^.!?]{{0,60}}(?:{_SCHADEN})|(?:{_SCHADEN})[^.!?]{{0,60}}(?:{_ZE})",
    re.I,
)
_ZAHN_KAPUTT_RE = re.compile(
    r"(?:zahn\w*|schneidezahn|backenzahn|stueck\s+zahn)"
    r"[^.!?]{0,30}(?:abgebrochen|abgeplatzt|rausgefallen|ausgefallen)"
    r"|(?:abgebrochen|abgeplatzt|rausgefallen)"
    r"[^.!?]{0,30}(?:zahn\w*|stueck)",
    re.I,
)
_ZAHN_ABSZESS_RE = re.compile(
    r"\babszess\b|dicke\s+backe|backe\s+(?:dick|geschwollen)|"
    r"\beitrig\b|vereitert",
    re.I,
)
_HAUT_RE = re.compile(
    r"\bmelanom\w*|\bmelanoma\w*|"
    r"verdacht\s+auf\s+(?:ein(?:en)?\s+)?(?:haut)?krebs|"
    r"(?:haut)?krebsverdacht|"
    r"muttermal\w*[^.!?]{0,40}(?:blut|waechst|groesser|schwarz)|"
    r"\babszess\b|\beitrig\b",
    re.I,
)
_HAUT_RUHIG_RE = re.compile(
    r"hautscreening|hautkrebsvorsorge|krebsvorsorge",
    re.I,
)
# Paket 5 (02.10.2026, Replay blessing-dringlich): akute Hautbeschwerden, die
# NICHT Melanom/Abszess sind — blutende/offene/entzündete Wunde, nässende/
# stark juckende/brennende Stelle. Das ist MEDIZINISCH akut (Suche ab heute),
# unabhaengig vom Wort „dringend". Ein ruhiger Beratungs-/Kontrollwunsch
# („Ausschlag anschauen lassen", „irgendwann ein Kontrolltermin") traegt kein
# solches Symptom und bleibt Stufe 0 (Gegenprobe).
_HAUT_AKUT_RE = re.compile(
    r"\bwunde\w*[^.!?]{0,30}(?:blut|offen|n(?:ae|ä)sst|n(?:ae|ä)sse|"
    r"entz(?:ü|ue)nd\w*|eitert|eitrig|schlimmer|aufgeplatzt)|"
    r"\bblutet\b|\bblutende\w*\s+wunde|\bblutung\w*|"
    r"\boffene\s+wunde|aufgekratzt|aufgeplatzt|"
    r"stark\w*\s+(?:juck\w*|brenn\w*|schmerz\w*)|"
    r"\ballergische[nr]?\s+(?:schock|reaktion)",
    re.I,
)
_GYN_SYMPTOM_RE = re.compile(
    r"\babszess\b|\beitrig\b|\bblutung\w*|\bblutet\b|"
    r"geschwollen|starke\s+schmerzen|unterleibsschmerz\w*",
    re.I,
)
_GYN_ORT_RE = re.compile(
    r"schwanger\w*|intimbereich|\bintim\b|unterleib|scheide|vulva|genital",
    re.I,
)
_ENTWARNUNG_RE = re.compile(
    r"nichts\s+akutes|nicht\s+akut|kein(?:e)?\s+notfall|"
    r"nur\s+(?:die\s+)?(?:normale\s+)?kontrolle|"
    r"nicht\s+lose|nicht\s+kaputt|nicht\s+abgebrochen|"
    r"keine\s+schmerzen",
    re.I,
)
_ABSAGE_RE = re.compile(r"\babsag\w*|\bstornier\w*", re.I)
_SCHON_GESAGT_RE = re.compile(
    r"klingt akut|klingt dringend|\b112\b|wartezeit|bereitschaftsdienst",
    re.I,
)


def an() -> bool:
    return (os.environ.get("DRINGLICHKEIT") or "1").strip().lower() not in {
        "0", "off", "false", "nein",
    }


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _norm(text: str) -> str:
    t = _s(text).casefold()
    t = (t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
         .replace("ß", "ss"))
    t = re.sub(r"\ba\s+bgebrochen\b", "abgebrochen", t)
    t = re.sub(r"\bkaput\b", "kaputt", t)
    t = re.sub(r"\b(?:abszess|abszes|abscess)\w*", "abszess", t)
    # Satzgrenzen weg: „Mir ist die Brücke.“ / „Sie ist lose.“ ist ein Schaden.
    t = re.sub(r"[.!?…]+", " ", t)
    return " ".join(t.split())


def _leer() -> dict[str, Any]:
    return {"stufe": 0, "cluster": "", "kern": "", "muster": [], "wortlaut": ""}


def _karte(stufe: int, cluster: str, kern: str, muster: list[str],
           wortlaut: str) -> dict[str, Any]:
    return {
        "stufe": stufe,
        "cluster": cluster,
        "kern": kern,
        "muster": list(muster),
        "wortlaut": _s(wortlaut)[:160],
    }


def bewerten(text: str, fach: str = "") -> dict[str, Any]:
    """Stufe 2 = heute suchen oder sofort kommen. Stufe 0 = normaler Termin."""
    if not an():
        return _leer()
    roh = _s(text)
    t = _norm(roh)
    if not t or _ENTWARNUNG_RE.search(t):
        return _leer()
    if _ABSAGE_RE.search(t) and not (
        _ZE_KAPUTT_RE.search(t) or _ZAHN_KAPUTT_RE.search(t)
    ):
        return _leer()
    fid = (fach or "").strip().lower()

    if fid == "zahnmedizin":
        intim = bool(_GYN_ORT_RE.search(t) and re.search(r"\babszess\b", t))
        if intim:
            return _karte(2, "fremd", "", [], roh)
        if _ZE_KAPUTT_RE.search(t):
            return _karte(2, "ze", "Reparatur Zahnersatz", _REPARATUR_MUSTER, roh)
        if _ZAHN_KAPUTT_RE.search(t) or (
            _ZAHN_ABSZESS_RE.search(t) and not _GYN_ORT_RE.search(t)
        ):
            return _karte(
                2, "zahn", "akute Beschwerden/Notfall", _AKUT_MUSTER, roh)
        return _leer()

    if fid == "dermatologie":
        # Blessing: Abszess in der Schwangerschaft im Intimbereich ist ein
        # Hautnotfall, keine Vorsorge und kein fachfremder Verweis.
        if _HAUT_RUHIG_RE.search(t) and not _HAUT_RE.search(t) \
                and not _HAUT_AKUT_RE.search(t):
            return _leer()
        if _HAUT_RE.search(t):
            cluster = "melanom" if re.search(r"\bmelanom|\bmelanoma|krebsverdacht", t) else "haut"
            return _karte(2, cluster, "akute Beschwerden/Notfall", _AKUT_MUSTER, roh)
        # Paket 5: akute Hautbeschwerde (blutende/offene Wunde o. Ä.) steuert
        # ebenso ab heute — kein stiller Standard-Slot Monate spaeter.
        if _HAUT_AKUT_RE.search(t):
            return _karte(2, "haut", "akute Beschwerden/Notfall", _AKUT_MUSTER, roh)
        return _leer()

    if fid == "gynaekologie":
        if re.search(r"schwangerschaftsvorsorge|vorsorgeuntersuchung", t) \
                and not _GYN_SYMPTOM_RE.search(t):
            return _leer()
        if _GYN_SYMPTOM_RE.search(t):
            return _karte(2, "gyn", "akute Beschwerden", _GYN_MUSTER, roh)
        return _leer()

    return _leer()


def fenster(sit: dict | None, text: str = "") -> str:
    """Letzte Anrufer-Sätze plus der aktuelle — Schäden kommen oft zweizügig."""
    teile: list[str] = []
    msgs = (sit or {}).get("messages") if isinstance(sit, dict) else None
    for m in (msgs or [])[-8:]:
        if isinstance(m, dict) and m.get("role") == "user":
            teile.append(_s(m.get("content")))
    teile.append(_s(text))
    return " ".join([x for x in teile if x][-3:])


def _fach(tenant: dict | None) -> str:
    from kern import fachprofil
    return fachprofil.fach_id(tenant or {})


def konzept(tenant: dict | None, text: str) -> tuple[str, list[str]] | None:
    """(Kern, Motiv-Muster) wenn der Satz ein dringendes Motiv erzwingt."""
    k = bewerten(text, _fach(tenant))
    if int(k["stufe"]) < 2 or not k["kern"]:
        return None
    return k["kern"], list(k["muster"])


def oeffnet_buchung(text: str, tenant: dict | None = None) -> bool:
    """Schaden ohne das Wort Termin ist trotzdem eine Neubuchung."""
    if not an():
        return False
    t = _norm(text)
    if _ABSAGE_RE.search(t) and not (
        _ZE_KAPUTT_RE.search(t) or _ZAHN_KAPUTT_RE.search(t)
    ):
        return False
    k = bewerten(text, _fach(tenant))
    return int(k["stufe"]) >= 2 and bool(k.get("kern"))


def stufe(sit: dict | None) -> int:
    k = (sit or {}).get("dringlichkeit") if isinstance(sit, dict) else None
    if not isinstance(k, dict):
        return 0
    try:
        return int(k.get("stufe") or 0)
    except (TypeError, ValueError):
        return 0


def merken(sit: dict, text: str = "") -> dict[str, Any]:
    """Höhere Stufe bleibt. Ausdrückliche Entwarnung setzt zurück."""
    if not an() or not isinstance(sit, dict):
        return _leer()
    neu = bewerten(fenster(sit, text), _fach(
        sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}))
    alt = sit.get("dringlichkeit") if isinstance(sit.get("dringlichkeit"), dict) else _leer()
    if _ENTWARNUNG_RE.search(_norm(text)):
        sit["dringlichkeit"] = _leer()
        return sit["dringlichkeit"]
    if int(neu["stufe"]) >= int(alt.get("stufe") or 0) and int(neu["stufe"]) > 0:
        sit["dringlichkeit"] = neu
        return neu
    return alt if int(alt.get("stufe") or 0) else neu


def _wahl(tenant: dict | None) -> str:
    try:
        from kern import anliegen_zug
        r = anliegen_zug.regel_fuer(tenant, "notfall")
    except Exception:
        return ""
    return str(getattr(r, "wahl", "") or "")


def sucht_ab_heute(sit: dict | None) -> bool:
    """Termin suchen ab heute. Sofort-kommen-Praxen hängen vorher auf."""
    if stufe(sit) < 2:
        return False
    tenant = (sit or {}).get("tenant") if isinstance((sit or {}).get("tenant"), dict) else {}
    wahl = _wahl(tenant)
    if wahl == "akuttermin":
        return True
    if wahl in {"sofort", "bereitschaft"}:
        return False
    from kern import praxisregeln
    if praxisregeln.notfall_sofort_aktiv(tenant):
        return False
    k = (sit or {}).get("dringlichkeit") if isinstance(sit, dict) else {}
    if isinstance(k, dict) and k.get("cluster") == "fremd":
        return False
    return True


def sofort_text(sit: dict, text: str = "") -> str:
    """Kommen-Satz, wenn die Praxis akute Fälle nicht als Termin führt.

    Melanom bleibt bei ``eilig`` (heute anbieten, sonst kommen).
    """
    if not an() or not isinstance(sit, dict):
        return ""
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    k = bewerten(fenster(sit, text) or text, _fach(tenant))
    if int(k["stufe"]) < 2 or k.get("cluster") in {"", "melanom", "fremd"}:
        return ""
    if sucht_ab_heute({**sit, "dringlichkeit": k, "tenant": tenant}):
        return ""
    wahl = _wahl(tenant)
    if wahl == "akuttermin":
        return ""
    try:
        from kern import anliegen_zug
        r = anliegen_zug.regel_fuer(tenant, "notfall")
        satz = anliegen_zug.satz(r, tenant) if r is not None else ""
    except Exception:
        satz = ""
    if satz:
        return satz
    from kern import eilig
    return eilig.KOMMEN_SATZ


def voranstellen(sit: dict, text: str) -> str:
    """Den Dringlichkeitssatz genau einmal vor die nächste Frage."""
    if not an() or not isinstance(sit, dict) or stufe(sit) < 2:
        return text
    if sit.get("dringlichkeitGesagt"):
        return text
    t = _s(text)
    if sit.get("akutSofort") or sit.get("eiligKomme") or _SCHON_GESAGT_RE.search(t):
        sit["dringlichkeitGesagt"] = True
        sit["dringlichkeitGehoert"] = True
        return text
    k = sit.get("dringlichkeit") if isinstance(sit.get("dringlichkeit"), dict) else {}
    if isinstance(k, dict) and k.get("cluster") == "fremd":
        sit["dringlichkeitGesagt"] = True
        sit["dringlichkeitGehoert"] = True
        satz = (
            "Das klingt dringend und gehört in eine ärztliche Untersuchung, "
            "nicht in einen normalen Termin."
        )
        return f"{satz} {t}".strip()
    sit["dringlichkeitGesagt"] = True
    sit["dringlichkeitGehoert"] = True
    return f"{SATZ_HEUTE} {t}".strip()
