"""Intent-Erkennung (W-INTENT 03.09.2026): erst erkennen, dann handeln.

Chef: Bianca (und Lisa) muessen JEDERZEIT die Intention des Anrufers kennen —
die Erkennung schwingt bei jedem Satz mit, VOR den deterministischen
Maschinen. Drei Stufen halten die Latenz klein:

1. FAST-PATH (0 ms): Diktat-/Formular-Antworten (Ziffern, Buchstabieren,
   kurzes Ja/Nein, Slotwahl) sind nie ein neues Anliegen -> zug=verfeinern,
   KEIN LLM-Call. Das sind die latenzkritischen Zuege mitten in der Aufnahme.
2. LLM (kern/llm.chat, dasselbe vLLM wie das Gespraech): Temperatur 0,
   kleines JSON (~60 Tokens), eigener Timeout ueber einen Thread-Future —
   die 20-s-Leine des Clients gilt hier NICHT (INTENT_TIMEOUT, Default 4 s).
3. FALLBACK (LLM tot/zu langsam/unparsebar): kompakte Heuristik. Buchen nur
   bei AUSDRUECKLICHEM Terminwunsch — nie als stiller Default.

Notaus: INTENT_SCHICHT=0 -> erkennen() liefert immer 'halten', und
bianca/gehirn.einsammeln laesst die alte Regex-Modus-Erkennung wieder zu.

Kein Zugriff auf bianca/* oder lisa/* (Schichtung): der Sammler wird als
schlichtes Dict aus der Sitzung gelesen.
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from kern import llm

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="intent")


def enabled() -> bool:
    return os.environ.get("INTENT_SCHICHT", "1").strip().lower() not in ("0", "false", "no")


def _timeout_s() -> float:
    try:
        return float(os.environ.get("INTENT_TIMEOUT", "4.0"))
    except ValueError:
        return 4.0


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


# --- Fast-Path: Formular-Antworten brauchen kein LLM ------------------------

# Wechsel-Signale: sobald so ein Wort faellt, ist der Satz KEIN reiner
# Formular-Zug mehr — das LLM muss ihn deuten (Themenwechsel moeglich).
_WECHSEL_RE = re.compile(
    r"sprech\w*|verbind\w*|verbunden|durchstell\w*|weiterleit\w*|"
    r"absag\w*|stornier\w*|verschieb\w*|umbuch\w*|verleg\w*|"
    r"r(?:ü|ue)ckruf\w*|zur(?:ü|ue)ckruf\w*|"
    r"rechnung\w*|abrechnung\w*|rezept\w*|(?:ü|ue)berweisung\w*|befund\w*|"
    r"heil\w*kostenplan|\bhkp\b|kostenvoranschlag|\bkva\b|"
    r"frage\b|fragen\b|wissen\b|fertig\b|urlaub\b|ge(?:ö|oe)ffnet|offen\b|"
    r"mitarbeiter\w*|anmeldung|empfang|buchhaltung|praxisleitung|"
    r"doktor|\bdr\b\.?|arzt|(?:ä|ae)rztin|"
    r"kein\w*\s+termin|nicht\s+buchen",
    re.I,
)

_JA_NEIN_RE = re.compile(
    r"^\s*(?:ja|jawohl|genau|richtig|korrekt|passt|gerne?|okay?|super|prima|"
    r"nein|nee|n(?:ö|oe)|nicht|danke|alles\s+klar|in\s+ordnung|mhm+|stimmt"
    r")(?:[\s,.!?]+(?:ja|nein|genau|richtig|danke|gerne?|okay?|bitte|schon|so|das|passt|stimmt|gut)){0,3}[\s.!?]*$",
    re.I,
)
_ZIFFERN_RE = re.compile(r"^[\d\s\-+.,]+$")
_ZAHLWORT_RE = re.compile(
    r"^\s*(?:(?:null|eins|zwei|drei|vier|f(?:ü|ue)nf|sechs|sieben|acht|neun|"
    r"zehn|doppel\w*|und|die|nummer|ist|lautet|\d+)[\s,.\-]*){2,}$",
    re.I,
)
_BUCHSTABIER_RE = re.compile(
    r"^\s*(?:[A-Za-zÄÖÜäöü]\s*(?:wie\s+\w+)?[\s,.\-]*){2,}$"
)
_SLOTWAHL_RE = re.compile(
    r"^\s*(?:de[rn]\s+)?(?:erste\w*|zweite\w*|dritte\w*|letzte\w*|"
    r"(?:um\s+)?\d{1,2}(?::\d{2})?\s*uhr\w*|vormittag\w*|nachmittag\w*|"
    r"morgens|abends|fr(?:ü|ue)her?|sp(?:ä|ae)ter?|"
    r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|"
    r"heute|morgen|(?:ü|ue)bermorgen)"
    r"(?:[\s,.]+\w+){0,4}[\s.!?]*$",
    re.I,
)

# Formular-Fragen der Maschine: Antworten darauf sind Ernte, kein Anliegen.
_FORMULAR_FRAGEN = {
    "name", "vorname", "nachname", "telefon", "telefon_check", "telefon_alt",
    "buchstabieren", "schonmal", "versicherung", "anrufer_check", "geburtstag",
    "wunsch", "terminwahl", "slotwahl", "bestaetigung", "absage_ok",
    "frisch_absage_ok", "behandlung", "pzr",
}


def _ist_formular_antwort(sit: dict, text: str) -> bool:
    """True = sicher nur Ernte fuer die laufende Maschine (kein LLM noetig)."""
    t = _s(text)
    if not t or _WECHSEL_RE.search(t):
        return False
    if _JA_NEIN_RE.match(t) or _ZIFFERN_RE.match(t) or _ZAHLWORT_RE.match(t) \
            or _BUCHSTABIER_RE.match(t):
        return True
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    frage = _s(s.get("frage"))
    phase = _s(s.get("phase"))
    if _SLOTWAHL_RE.match(t) and (phase in {"angebot", "bestaetigen"}
                                  or frage in {"wunsch", "terminwahl", "slotwahl"}):
        return True
    if frage in _FORMULAR_FRAGEN and len(t.split()) <= 4:
        # Kurzantwort auf eine offene Formular-Frage ("Berger", "Kontrolle").
        return True
    return False


# --- Fallback-Heuristik (LLM tot / unparsebar) ------------------------------

_FB_ERREICHEN_RE = re.compile(
    r"sprech\w*|verbind\w*|verbunden|durchstell\w*|weiterleit\w*|"
    r"talk\s+to|speak\s+(?:to|with)|"
    r"h(?:ä|ae)tte?\s+gern\w*\s+(?:den|die|herrn|frau)?\s*(?:doktor|dr\b)|"
    r"mitarbeiter\w*|anmeldung|empfang|praxisleitung|personal\b|"
    r"echte[nr]?\s+mensch\w*|richtige[nr]?\s+mensch\w*",
    re.I,
)
_FB_ABSAGE_RE = re.compile(
    r"absag\w*|abzusagen|abgesagt|stornier\w*|abbestell\w*|\bcancel\w*|"
    r"nicht\s+(?:kommen|wahrnehmen|schaffen|einhalten)",
    re.I,
)
_FB_VERSCHIEBEN_RE = re.compile(
    r"verschieb\w*|umbuch\w*|verleg\w*|umleg\w*|vorverleg\w*|anderen\s+tag",
    re.I,
)
_FB_RUECKRUF_RE = re.compile(
    r"r(?:ü|ue)ckruf|zur(?:ü|ue)ckruf\w*|ruft\s+mich|meldet\s+(?:sich|euch)|"
    r"nachricht\s+hinterlass\w*|ausricht\w*|call\s*back",
    re.I,
)
_FB_AUSKUNFT_RE = re.compile(
    r"wann\s+(?:ist|war|habe?\s+ich)\b.{0,30}termin|"
    r"habe?\s+ich\s+(?:noch\s+)?(?:irgend)?einen\s+termin|"
    r"\bfertig\b|\burlaub\b|ge(?:ö|oe)ffnet|offen\s+heute|"
    r"was\s+kostet|wie\s+teuer|wo\s+(?:finde|ist|sind)|wie\s+komme?\s+ich",
    re.I,
)
_FB_NEU_RE = re.compile(
    r"(?:termin\w*)\s*(?:\w+\s+){0,4}?(?:vereinbar\w*|ausmach\w*|buch\w*|machen|haben|brauch\w*)|"
    r"(?:brauch\w*|h(?:ä|ae)tte?\s+gern\w*|m(?:ö|oe)chte\w*|will)\s+(?:\w+\s+){0,4}?termin",
    re.I,
)


def _fallback(sit: dict, text: str) -> dict[str, Any]:
    """Deterministische Not-Deutung. Buchen NUR bei ausdruecklichem
    Terminwunsch — nie als Default (Chef 03.09.2026)."""
    t = _s(text)
    aus = {"kanal": "ok", "zug": "wechseln", "fuer": "selbst",
           "ersatz": None, "spiegel": t[:80], "quelle": "fallback"}
    if not t:
        return {**aus, "zug": "halten", "handlung": "KEINE", "gegenstand": ""}
    if _FB_ERREICHEN_RE.search(t):
        return {**aus, "handlung": "ERREICHEN", "gegenstand": "PERSON"}
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    im_angebot = _s(s.get("phase")) in {"angebot", "bestaetigen"}
    if im_angebot and (_FB_ABSAGE_RE.search(t) or _FB_VERSCHIEBEN_RE.search(t)):
        # "Passt nicht / den nicht" mitten im Slot-Angebot meint das ANGEBOT,
        # keinen Bestandstermin — die Maschine verhandelt selbst weiter.
        return {**aus, "zug": "verfeinern", "handlung": "KEINE", "gegenstand": ""}
    if _FB_VERSCHIEBEN_RE.search(t):
        return {**aus, "handlung": "AENDERN", "gegenstand": "VORGANG", "ersatz": True}
    if _FB_ABSAGE_RE.search(t):
        return {**aus, "handlung": "AENDERN", "gegenstand": "VORGANG", "ersatz": False}
    if _FB_RUECKRUF_RE.search(t):
        return {**aus, "handlung": "ABGEBEN", "gegenstand": "SACHE"}
    if _FB_AUSKUNFT_RE.search(t):
        gg = "VORGANG" if "termin" in t.lower() else "REGEL"
        return {**aus, "handlung": "WISSEN", "gegenstand": gg}
    if _FB_NEU_RE.search(t):
        return {**aus, "handlung": "ANLEGEN", "gegenstand": "VORGANG"}
    return {**aus, "zug": "halten", "handlung": "KEINE", "gegenstand": ""}


# --- LLM-Deutung --------------------------------------------------------------

_SYSTEM = """Du klassifizierst den LETZTEN Anrufer-Satz eines Praxis-Telefonats. Antworte NUR mit einem JSON-Objekt, keine Erklaerung.

Felder:
"kanal": "ok" | "tot" (nur Floskel/Rauschen/kein Inhalt) | "sprache" (nicht Deutsch, unklar)
"zug": "verfeinern" (Antwort auf die offene Frage der Maschine: Name, Nummer, Ja/Nein, Datum, Slotwahl) | "halten" (gleiches Anliegen, nichts Neues) | "wechseln" (JETZT will er etwas anderes) | "zweites" (zusaetzliches Anliegen, das aktuelle laeuft weiter) | "zurueck" (zum vorherigen/geparkten Anliegen)
"handlung": "ERREICHEN" (Person/Rolle sprechen/verbinden) | "WISSEN" (Auskunft: ist X fertig, wann ist mein Termin, Preis, Anfahrt, offen, Arzt da) | "AENDERN" (bestehenden Termin absagen/verschieben/korrigieren) | "ANLEGEN" (neuen Termin vereinbaren) | "ABGEBEN" (Rueckruf/Nachricht/die Praxis soll sich kuemmern) | "KEINE"
"gegenstand": "PERSON" | "VORGANG" (bestehender Termin) | "SACHE" (laufende Behandlung, Schiene, Rezept, Rechnung, Dokument) | "REGEL" (Oeffnung, Ort, Preis, Zustaendigkeit)
"fuer": "selbst" | "anderer" (ruft fuer Dritte: Angehoerige, Labor, andere Praxis, Firma)
"ersatz": nur bei AENDERN: true (will neuen/anderen Termin) | false (nur absagen, keinen neuen) | sonst null
"spiegel": das Anliegen in maximal 8 Worten, in den Worten des Anrufers

Regeln:
- Ein BESTEHENDER Termin plus Frage oder Sprechwunsch ist NIE ANLEGEN.
- Vorrang bei zwei Handlungen in einem Satz: ERREICHEN vor WISSEN vor AENDERN vor ABGEBEN vor ANLEGEN.
- "absagen und ich melde mich selbst wieder" => AENDERN ersatz=false.
- Steht im STAND "Angebot laeuft": Ablehnen/Absagen des ANGEBOTS ("passt nicht", "den nicht") ist zug="verfeinern", NICHT AENDERN — AENDERN nur bei klarem Bezug auf einen bestehenden Termin.
- Nur "Hallo", "Yeah", Geraeusche => kanal="tot".
- Kurze Antworten auf die offene Frage => zug="verfeinern", handlung="KEINE"."""


def _chat(messages: list[dict], max_tokens: int = 96) -> dict[str, Any]:
    """Duenner Umschlag um kern/llm.chat — in Tests monkeypatchbar."""
    return llm.chat(messages, None, temperature=0.0, max_tokens=max_tokens)


def _kontext(sit: dict, text: str, *, stimme: str) -> list[dict]:
    teile: list[str] = []
    h = sit.get("hirn") or {}
    akt = None
    for a in h.get("anliegen") or []:
        if a.get("id") == h.get("aktiv"):
            akt = a
            break
    if akt:
        z = f"Aktives Anliegen: {akt.get('handlung')} \u201e{_s(akt.get('spiegel'))[:60]}\u201c"
        teile.append(z)
    geparkt = [a for a in (h.get("anliegen") or []) if a.get("status") == "geparkt"]
    if geparkt:
        teile.append("Geparkt: " + "; ".join(
            f"{a.get('handlung')} \u201e{_s(a.get('spiegel'))[:40]}\u201c" for a in geparkt[:2]))
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if _s(s.get("frage")):
        teile.append(f"Offene Frage der Maschine: {_s(s.get('frage'))}")
    if _s(s.get("phase")) in {"angebot", "bestaetigen"}:
        teile.append("Angebot laeuft: die Maschine bietet gerade Termine an.")
    if stimme == "lisa" and _s(sit.get("auftrag")):
        teile.append(f"Chef-Auftrag dieses Anrufs: {_s(sit.get('auftrag'))[:120]}")
    # Letzte Zuege kompakt (max 6), damit Bezuege ("den", "ihn") deutbar sind.
    dialog: list[str] = []
    for m in (sit.get("messages") or [])[-7:]:
        rolle = m.get("role")
        inhalt = _s(m.get("content"))[:110]
        if not inhalt or rolle == "system":
            continue
        dialog.append(("A: " if rolle == "assistant" else "P: ") + inhalt)
    stand = "\n".join(teile) or "(noch kein Anliegen erkannt)"
    verlauf = "\n".join(dialog[-6:]) or "(Gespraechsanfang)"
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"STAND\n{stand}\n\nVERLAUF\n{verlauf}\n\nLETZTER SATZ DES ANRUFERS\n{_s(text)}\n\nJSON:"},
    ]


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse(text: str) -> dict[str, Any] | None:
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        roh = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(roh, dict):
        return None
    aus = {
        "kanal": _s(roh.get("kanal")).lower() or "ok",
        "zug": _s(roh.get("zug")).lower() or "halten",
        "handlung": _s(roh.get("handlung")).upper() or "KEINE",
        "gegenstand": _s(roh.get("gegenstand")).upper(),
        "fuer": "anderer" if _s(roh.get("fuer")).lower() == "anderer" else "selbst",
        "ersatz": roh.get("ersatz") if isinstance(roh.get("ersatz"), bool) else None,
        "spiegel": _s(roh.get("spiegel"))[:120],
        "quelle": "llm",
    }
    if aus["kanal"] not in {"ok", "tot", "sprache", "rauschen"}:
        aus["kanal"] = "ok"
    if aus["zug"] not in {"halten", "verfeinern", "wechseln", "zweites", "zurueck"}:
        aus["zug"] = "halten"
    if aus["handlung"] not in {"ERREICHEN", "WISSEN", "AENDERN", "ANLEGEN", "ABGEBEN", "KEINE"}:
        return None
    if aus["gegenstand"] not in {"PERSON", "VORGANG", "SACHE", "REGEL", ""}:
        aus["gegenstand"] = ""
    return aus


def erkennen(sit: dict, text: str, *, stimme: str = "bianca") -> dict[str, Any]:
    """Ein Anrufer-Satz -> Deutung fuer kern/hirn.anwenden().

    Schwingt bei jedem Satz mit (Chef 03.09.2026): Fast-Path fuer Formular-
    Antworten, sonst LLM mit hartem Timeout, sonst Fallback-Heuristik.
    """
    t = _s(text)
    if not enabled():
        return {"kanal": "ok", "zug": "halten", "handlung": "KEINE",
                "gegenstand": "", "quelle": "aus"}
    if not t:
        return {"kanal": "tot", "zug": "halten", "handlung": "KEINE",
                "gegenstand": "", "quelle": "leer"}
    h = sit.get("hirn") or {}
    if h.get("aktiv") and _ist_formular_antwort(sit, t):
        return {"kanal": "ok", "zug": "verfeinern", "handlung": "KEINE",
                "gegenstand": "", "quelle": "fastpath"}
    fut = _POOL.submit(_chat, _kontext(sit, t, stimme=stimme))
    try:
        out = fut.result(timeout=_timeout_s())
    except FutureTimeout:
        fut.cancel()
        print("intent: timeout -> fallback", flush=True)
        return _fallback(sit, t)
    except Exception as e:  # Pool/Transport kaputt: nie den Zug reissen
        print(f"intent: fehler {e} -> fallback", flush=True)
        return _fallback(sit, t)
    if not out.get("ok"):
        print(f"intent: llm {_s(out.get('error'))[:120]} -> fallback", flush=True)
        return _fallback(sit, t)
    deutung = _parse(out.get("text") or "")
    if deutung is None:
        print("intent: unparsebar -> fallback", flush=True)
        return _fallback(sit, t)
    return deutung
