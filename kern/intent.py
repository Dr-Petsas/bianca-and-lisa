"""Intent-Erkennung (W-INTENT 03.09.2026): erst erkennen, dann handeln.

Chef: Bianca (und Lisa) muessen JEDERZEIT die Intention des Anrufers kennen —
die Erkennung schwingt bei jedem Satz mit, VOR den deterministischen
Maschinen. Drei Stufen halten die Latenz klein:

1. FAST-PATH (0 ms, der Normalfall — Chef 03.09.2026 "die spritzigkeit und
   speed ist komplett weg", Antworten liefen auf ~8 s):
   a) Formular-Antworten (Ziffern, Buchstabieren, Ja/Nein, Slotwahl).
   b) Laeuft ein Anliegen, wird das LLM NUR bei Wechsel-Verdacht gerufen
      (Signalwoerter: sprechen/absagen/aendern/Rechnung/Rueckruf/"doch
      nicht" ...). Gewoehnliche Sammel-Antworten ("naechste Woche
      vormittags waere gut") kosten NICHTS.
   c) Eindeutige Erstsaetze ("Ich haette gern einen Termin", "Termin
      absagen", "Doktor sprechen"): genau EIN Kategorie-Treffer, keine
      Verneinung -> sofort, ohne LLM.
2. LLM (kern/llm.chat, dasselbe vLLM wie das Gespraech) nur fuer die
   mehrdeutigen Saetze: Temperatur 0, Mini-JSON (Spiegel max. 5 Worte,
   max_tokens 44 — das vLLM schafft ~20-25 Tokens/s, jedes Token zaehlt),
   eigener Timeout ueber einen Thread-Future — die 20-s-Leine des Clients
   gilt hier NICHT (INTENT_TIMEOUT, Default 2.5 s).
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
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from kern import llm

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="intent")


def enabled() -> bool:
    return os.environ.get("INTENT_SCHICHT", "1").strip().lower() not in ("0", "false", "no")


def _timeout_s() -> float:
    try:
        return float(os.environ.get("INTENT_TIMEOUT", "2.5"))
    except ValueError:
        return 2.5


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


# --- Fast-Path: Formular-Antworten brauchen kein LLM ------------------------

# Wechsel-Signale: sobald so ein Wort faellt, ist der Satz KEIN reiner
# Formular-Zug mehr — das LLM muss ihn deuten (Themenwechsel moeglich).
_WECHSEL_RE = re.compile(
    r"sprech\w*|verbind\w*|verbunden|durchstell\w*|weiterleit\w*|"
    r"absag\w*|stornier\w*|verschieb\w*|umbuch\w*|verleg\w*|(?:ä|ae)nder\w*|"
    r"r(?:ü|ue)ckruf\w*|zur(?:ü|ue)ckruf\w*|"
    r"rechnung\w*|abrechnung\w*|rezept\w*|(?:ü|ue)berweisung\w*|befund\w*|"
    r"heil\w*kostenplan|\bhkp\b|kostenvoranschlag|\bkva\b|"
    r"frage\b|fragen\b|wissen\b|fertig\b|urlaub\b|ge(?:ö|oe)ffnet|offen\b|"
    r"mitarbeiter\w*|anmeldung|empfang|buchhaltung|praxisleitung|"
    r"doktor|\bdr\b\.?|arzt|(?:ä|ae)rztin|"
    r"kein\w*\s+termin|nicht\s+buchen",
    re.I,
)

# Abbruch-/Umlenk-Floskeln: auch ohne Fachwort ein Fall fuers LLM
# ("vergessen Sie das", "doch nicht", "eigentlich wollte ich ...").
_ABBRUCH_RE = re.compile(
    r"vergessen\s+sie|doch\s+nicht|abbrechen|egal\b|stopp\b|eigentlich\b|"
    r"anders\w*\b|etwas\s+anderes|moment\b|halt\s+mal|stattdessen",
    re.I,
)


def _wechsel_verdacht(t: str, aktiv_handlung: str) -> bool:
    """Koennte dieser Satz das Anliegen wechseln? Nur dann lohnt das LLM.

    Der Kern der Latenz-Rettung (Chef 03.09.2026): mitten in einem Anliegen
    sind fast alle Saetze Ernte fuer die laufende Maschine — die zahlen
    KEINEN LLM-Aufschlag mehr. Das Lexikon deckt die Wechsel-Faelle aus der
    Meddent-/Blessing-Auswertung; was es faengt, entscheidet weiter das LLM.
    """
    if _WECHSEL_RE.search(t) or _ABBRUCH_RE.search(t):
        return True
    # "Termin" ist im Buchungs-/Aenderungs-Anliegen Alltagsvokabular der
    # Ernte — bei WISSEN/ERREICHEN/ABGEBEN dagegen ein neues Fass.
    if aktiv_handlung not in {"ANLEGEN", "AENDERN"} and re.search(r"\btermin", t, re.I):
        return True
    return False

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
# Einzel-Buchstaben MIT Pflicht-Trenner ("B E R G E R", "M wie Martha, U wie
# Uebermut") — ohne den Trenner-Zwang matchte das Muster JEDES Wort
# zeichenweise (Test test_ernte_im_anliegen_ohne_llm, 03.09.2026).
_BUCHSTABIER_RE = re.compile(
    r"^\s*(?:[A-Za-zÄÖÜäöü](?:\s+wie\s+\w+)?(?:[\s,.\-]+|$)){2,}$"
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


# --- Schnellstrasse: eindeutige Saetze brauchen kein LLM ---------------------

_NEGATION_RE = re.compile(r"\bnicht\b|\bkein\w*|\bniemals\b|\bnie\b", re.I)


def _eindeutig(t: str) -> dict[str, Any] | None:
    """Genau EIN Kategorie-Treffer, keine Verneinung, kein Roman ->
    Deutung sofort (0 ms). Mehrdeutiges geht weiter ans LLM."""
    if len(t.split()) > 18 or _NEGATION_RE.search(t):
        return None
    treffer: list[tuple[str, dict[str, Any]]] = []
    if _FB_ERREICHEN_RE.search(t):
        treffer.append(("ERREICHEN", {"handlung": "ERREICHEN", "gegenstand": "PERSON"}))
    if _FB_VERSCHIEBEN_RE.search(t):
        treffer.append(("VERSCHIEBEN", {"handlung": "AENDERN", "gegenstand": "VORGANG", "ersatz": True}))
    if _FB_ABSAGE_RE.search(t):
        treffer.append(("ABSAGE", {"handlung": "AENDERN", "gegenstand": "VORGANG", "ersatz": False}))
    if _FB_RUECKRUF_RE.search(t):
        treffer.append(("RUECKRUF", {"handlung": "ABGEBEN", "gegenstand": "SACHE"}))
    if _FB_AUSKUNFT_RE.search(t):
        treffer.append(("AUSKUNFT", {"handlung": "WISSEN",
                                     "gegenstand": "VORGANG" if "termin" in t.lower() else "REGEL"}))
    if _FB_NEU_RE.search(t):
        treffer.append(("NEU", {"handlung": "ANLEGEN", "gegenstand": "VORGANG"}))
    if len(treffer) != 1:
        return None
    aus = {"kanal": "ok", "zug": "wechseln", "fuer": "selbst", "ersatz": None,
           "spiegel": t[:80], "quelle": "schnell"}
    aus.update(treffer[0][1])
    return aus


# --- LLM-Deutung --------------------------------------------------------------

# Kompakt gehalten (Chef 03.09.2026, Latenz): das vLLM generiert ~20-25
# Tokens/s — jedes gesparte Ausgabe-Token sind ~45 ms. Der Prompt bleibt
# STATISCH, damit der vLLM-Prefix-Cache greift.
_SYSTEM = """Du klassifizierst den LETZTEN Anrufer-Satz eines Praxistelefonats. Antworte NUR mit kompaktem JSON in einer Zeile:
{"zug":"...","handlung":"...","gegenstand":"...","fuer":"selbst|anderer","ersatz":true|false|null,"spiegel":"max 5 Worte"}

zug: verfeinern=Antwort auf die offene Frage | halten=gleiches Anliegen | wechseln=will JETZT etwas anderes | zweites=zusaetzliches Anliegen, aktuelles laeuft weiter | zurueck=zum geparkten Anliegen
handlung: ERREICHEN=Person/Rolle sprechen/verbinden | WISSEN=Auskunft (fertig? wann? Preis? offen?) | AENDERN=bestehenden Termin absagen/verschieben | ANLEGEN=neuen Termin | ABGEBEN=Rueckruf/Nachricht, Praxis kuemmert sich | KEINE=Floskel/kein Anliegen
gegenstand: PERSON | VORGANG=bestehender Termin | SACHE=Behandlung/Rezept/Rechnung/Dokument | REGEL=Oeffnung/Ort/Preis
ersatz NUR bei AENDERN: true=will anderen Termin, false=nur absagen.
Regeln: Bestehender Termin plus Frage/Sprechwunsch ist NIE ANLEGEN. Vorrang ERREICHEN>WISSEN>AENDERN>ABGEBEN>ANLEGEN. Steht im STAND "Angebot laeuft", meint Ablehnen/Absagen das ANGEBOT: zug=verfeinern. Kurze Antwort auf die offene Frage: zug=verfeinern, handlung=KEINE."""


def _chat(messages: list[dict], max_tokens: int = 44) -> dict[str, Any]:
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
    # Letzte Zuege kompakt (max 4), damit Bezuege ("den", "ihn") deutbar sind —
    # knapp gehalten, der Prefill ist billig, aber nicht umsonst.
    dialog: list[str] = []
    for m in (sit.get("messages") or [])[-5:]:
        rolle = m.get("role")
        inhalt = _s(m.get("content"))[:90]
        if not inhalt or rolle == "system":
            continue
        dialog.append(("A: " if rolle == "assistant" else "P: ") + inhalt)
    stand = "\n".join(teile) or "(noch kein Anliegen erkannt)"
    verlauf = "\n".join(dialog[-4:]) or "(Gespraechsanfang)"
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

    Schwingt bei jedem Satz mit (Chef 03.09.2026) — aber fast immer ueber
    die 0-ms-Fast-Paths. Das LLM zahlt nur, wer mehrdeutig spricht:
    Wechsel-Verdacht im laufenden Anliegen oder ein unklarer Erstsatz.
    """
    t = _s(text)
    if not enabled():
        return {"kanal": "ok", "zug": "halten", "handlung": "KEINE",
                "gegenstand": "", "quelle": "aus"}
    if not t:
        return {"kanal": "tot", "zug": "halten", "handlung": "KEINE",
                "gegenstand": "", "quelle": "leer"}
    h = sit.get("hirn") or {}
    a_handlung = ""
    for a in h.get("anliegen") or []:
        if a.get("id") == h.get("aktiv"):
            a_handlung = _s(a.get("handlung"))
            break
    if h.get("aktiv"):
        if _ist_formular_antwort(sit, t):
            return {"kanal": "ok", "zug": "verfeinern", "handlung": "KEINE",
                    "gegenstand": "", "quelle": "fastpath"}
        if not _wechsel_verdacht(t, a_handlung):
            # Kein Wechsel-Signal: der Satz gehoert dem laufenden Anliegen
            # (Ernte/Erzaehlung/Zwischenfrage) — Maschine und Talk-Schicht
            # verarbeiten ihn wie gewohnt, OHNE LLM-Aufschlag.
            return {"kanal": "ok", "zug": "halten", "handlung": "KEINE",
                    "gegenstand": "", "quelle": "fastpath-still"}
    else:
        schnell = _eindeutig(t)
        if schnell is not None:
            return schnell
    t0 = time.monotonic()
    fut = _POOL.submit(_chat, _kontext(sit, t, stimme=stimme))
    try:
        out = fut.result(timeout=_timeout_s())
    except FutureTimeout:
        fut.cancel()
        print(f"intent: timeout {int((time.monotonic() - t0) * 1000)}ms -> fallback", flush=True)
        return _fallback(sit, t)
    except Exception as e:  # Pool/Transport kaputt: nie den Zug reissen
        print(f"intent: fehler {e} -> fallback", flush=True)
        return _fallback(sit, t)
    ms = int((time.monotonic() - t0) * 1000)
    if not out.get("ok"):
        print(f"intent: llm {_s(out.get('error'))[:120]} -> fallback", flush=True)
        return _fallback(sit, t)
    deutung = _parse(out.get("text") or "")
    if deutung is None:
        print(f"intent: unparsebar ({ms}ms) -> fallback", flush=True)
        return _fallback(sit, t)
    print(f"intent: llm {ms}ms zug={deutung['zug']} handlung={deutung['handlung']}", flush=True)
    return deutung
