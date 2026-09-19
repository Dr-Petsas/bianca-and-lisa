"""Verstehen: Satz + Lage -> SemanticEvent. Der Reducer liest keinen Rohtext.

Eine Schicht fuer ALLE Biancas. Mandanten schaerfen nicht das Verstehen,
sondern die Policy (welche Aufgabe, welche Pflichtfelder, Transfer, Notfall).

Reihenfolge (Chef 19.09.2026): erst Verstehen, dann die Schublade.

  1. Formular-Taste (0 ms): nacktes Ja/Nein, reine Ordinalwahl, Power-#…
     Das ist keine Semantik.
  2. Hirn ZUERST: jeder andere Satz geht an das Modell MIT der Lage.
     Das Modell liefert ausschliesslich ein SemanticEvent. Die Maschine
     feuert DANACH aus dieser Schublade — NLU fuellt und korrigiert nicht.
  3. NLU nur wenn kein Modell da ist oder das Modell wirft.

``llm`` ist ein Callable ``(text, *, lage) -> SemanticEvent``.
Dock haengt ``hirn.deuten`` (vLLM) an; Tests geben einen Stub.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable, Mapping
from typing import Any

from bianca.controller import anliegen as _anliegen
from bianca.controller import fuer_wen as _fuer_wen
from bianca.controller import hirn as _hirn
from bianca.controller import meta as _meta
from bianca.controller import nlu_test
from bianca.controller import ordnen as _ordnen
from bianca.controller import wuensche as _wuensche
from bianca.controller.typen import Intent, Quelle, SemanticEvent, SlotValue, Verstand, replace

_VERWALTUNG = {Intent.VERSCHIEBEN, Intent.ABSAGEN}

# Meta-Bitten UEBER das Gespraech (meta.py) -> Intent. Sie gehen VOR allem
# anderen durch: sie sind Formeln, kein Anliegen, und muessen auch ohne Modell
# greifen — wer zum dritten Mal "Wie bitte?" sagt, darf nicht auf ein vLLM warten.
_META_INTENT: dict[str, Intent] = {
    _meta.WIEDERHOLEN: Intent.WIEDERHOLEN,
    _meta.ABBRECHEN: Intent.ABBRECHEN,
    _meta.AUSLASSEN: Intent.AUSLASSEN,
}

LlmVerstehen = Callable[..., SemanticEvent | Verstand]

_NUR_JA = re.compile(
    r"^\s*(ja|genau|richtig|stimmt|jup|gerne|ok|okay|jawohl|klar|yes)\s*[.!]?\s*$",
    re.I,
)
_NUR_NEIN = re.compile(
    r"^\s*(nein|ne|n[oö]e?|nee|nicht|falsch|no)\s*[.!]?\s*$",
    re.I,
)
_NUR_WAHL = re.compile(
    r"^\s*(?:der\s+|die\s+|das\s+)?"
    r"(?:erste|zweite|dritte|letzte|1|2|3|alle|beide)\s*[.!]?\s*$",
    re.I,
)
_ALLE_RE = re.compile(
    r"\b(?:alle|beide|s(?:ae|ä)mtliche|die\s+ganzen?)\b",
    re.I,
)
_ABSAGE_RE = re.compile(r"absag|stornier|cancel|streichen|loeschen|löschen", re.I)
_UMZUG_RE = re.compile(r"umgezogen|umzug|wohnortwechsel|weggezogen", re.I)
_ANZAHL_RE = re.compile(
    r"(?:habe|haben)\s+ich\s+(?:jetzt\s+|also\s+)*(\d+|zwei|drei|vier|fuenf|fünf)\s+termine"
    r"|ich\s+habe\s+(\d+|zwei|drei|vier|fuenf|fünf)\s+termine"
    r"|(\d+|zwei|drei|vier)\s+termine\s*\?",
    re.I,
)
_ZAHL = {
    "zwei": "2", "drei": "3", "vier": "4", "fuenf": "5", "fünf": "5",
}
_ALLE_WERTE = frozenset({"alle", "beide", "saemtliche", "sämtliche"})
_WESSEN_RE = re.compile(
    r"welcher?\s+ist\s+(?:denn\s+)?von|"
    r"welcher?\s+.{0,48}gehoer|"
    r"von\s+(?:meinem|meiner|meinen|ihrem|ihren)\s+\w+\s+(?:ist|gehoer)|"
    r"gehoert?\s+zu\s+(?:meinem|meiner|ihrem|ihren)",
    re.I,
)


# W-KERN-TEMPO (19.09.2026, MedDent-Anruf 5e5b15b0): jeder Satz ging ans
# Modell — 3,0 s / 4,3 s / 10,2 s je Zug. Eine Antwort auf eine geschlossene
# Frage ist aber eine Formel und braucht kein Modell. Deshalb zaehlt jetzt auch
# ein Ja/Nein/Wahl-KOPF, solange der Satz kurz ist, keine Frage stellt und kein
# zweites Anliegen traegt ("Ja, aber ich moechte absagen" geht weiter ans Modell).
_JA_KOPF = re.compile(
    r"^\s*(?:ja+|jo+|jup|jawohl|genau|richtig|stimmt|korrekt|klar|gerne|"
    r"ok(?:ay)?|yes|passt|sicher)\b",
    re.I,
)
_NEIN_KOPF = re.compile(r"^\s*(?:nein+|nee+|ne|n[oö]e?|falsch|nope|no)\b", re.I)
_WAHL_KOPF = re.compile(
    r"^\s*(?:der\s+|die\s+|das\s+|den\s+)?"
    r"(?:erste|zweite|dritte|vierte|letzte|alle|beide|[123])\b",
    re.I,
)
_KURZ_WOERTER = 5
_SIGNAL_RE = re.compile(
    r"\?|\baber\b|\bdoch\b|\bstattdessen\b|\bsondern\b|\btrotzdem\b",
    re.I,
)
# Fragen mit eigenem Leser in nlu_test (geschlossenes Vokabular oder ein
# deterministischer Extraktor). Traegt die Antwort genau diesen Wert, ist das
# Modell ueberfluessig — die Maschine wusste ohnehin, worauf sie wartet.
_REGEL_FRAGEN = frozenset({
    "nachname", "vorname", "telefon", "versicherung", "behandler",
    "schonmal", "besuchsgrund", "wunschzeit", "terminwahl", "fuer_wen",
})

# "Keine Ahnung" ist keine Angabe, sondern die Bitte, weiterzugehen. Live
# 19.09.2026 lief das ans Modell, landete als Wert "unbekannt" im Slot und wurde
# vorgelesen ("unbekannt — Wann soll ich suchen?"). Deterministisch ist es ein
# AUSLASSEN; ob das Feld verzichtbar ist, entscheidet allein der Reducer.
_NICHT_WISSEN_RE = re.compile(
    r"\b(?:kein[e]?\s+ahnung"
    r"|wei(?:ss|ß)\s+(?:ich\s+)?(?:noch\s+|leider\s+)?nicht"
    r"|wei(?:ss|ß)\s+ich\s+(?:gerade\s+|jetzt\s+)?nicht"
    r"|kann\s+ich\s+(?:so\s+)?nicht\s+sagen"
    r"|schwer\s+zu\s+sagen"
    r"|(?:habe|hab)\s+ich\s+(?:gerade\s+)?nicht\s+im\s+kopf)\b",
    re.I,
)
# NUR Feldfragen. Steuerfragen (Anrufer-Check, Auswahl) bleiben beim normalen
# Weg: dort ist "weiss nicht" keine Auslassung, sondern echte Unklarheit.
_NICHT_WISSEN_FRAGEN = frozenset({
    "schonmal", "behandler", "besuchsgrund", "wunschzeit", "versicherung",
    "nachname", "vorname", "telefon", "termin_hinweis", "aenderung",
    "arzt_notiz",
})
_NICHT_WISSEN_WOERTER = 9
_ZIFFER_RE = re.compile(r"\d")


def _ist_nicht_wissen(text: str, offene_frage: str) -> bool:
    t = " ".join(str(text or "").split())
    if offene_frage not in _NICHT_WISSEN_FRAGEN or not t:
        return False
    if len(t.split()) > _NICHT_WISSEN_WOERTER or _ZIFFER_RE.search(t):
        return False
    if not _NICHT_WISSEN_RE.search(t):
        return False
    # "Ich weiss nicht, ob ich einen Termin habe" ist ein ANLIEGEN, keine
    # Auslassung — das gehoert weiter dem Verstehen.
    return _anliegen.deute(t)[0] is None


# Zeitdeckel ums Modell: lieber die Regel-Deutung als ein Anrufer, der zehn
# Sekunden ins Leere hoert (Live 19.09.2026: ein Zug brauchte 10,2 s). Der
# angefangene Wurf laeuft im Hintergrund aus; er wird nur nicht mehr beachtet.
_BUDGET_S = 1.8


def _budget_s() -> float:
    try:
        return float(os.environ.get("KERN_HIRN_BUDGET_S", _BUDGET_S))
    except (TypeError, ValueError):
        return _BUDGET_S


def _mit_deckel(fn: Callable[[], Any], budget: float) -> tuple[Any, bool]:
    kasten: dict[str, Any] = {}

    def lauf() -> None:
        try:
            kasten["wert"] = fn()
        except BaseException as exc:  # noqa: BLE001 — wird unten neu geworfen
            kasten["fehler"] = exc

    faden = threading.Thread(target=lauf, name="kern-hirn", daemon=True)
    faden.start()
    faden.join(budget)
    if faden.is_alive():
        return None, True
    fehler = kasten.get("fehler")
    if fehler is not None:
        raise fehler
    return kasten.get("wert"), False


def _kurz_ohne_anliegen(t: str) -> bool:
    """Kurz, keine Rueckfrage, kein Einwand, kein zweites Anliegen."""
    if not t or len(t.split()) > _KURZ_WOERTER:
        return False
    if _SIGNAL_RE.search(t):
        return False
    return _anliegen.deute(t)[0] is None


def _ist_formular(text: str, *, janein: bool, wahl: bool) -> bool:
    t = str(text or "").strip()
    if not t:
        return True
    if t.startswith("#"):
        return True
    if janein and (_NUR_JA.match(t) or _NUR_NEIN.match(t)):
        return True
    if wahl and _NUR_WAHL.match(t):
        return True
    if not (janein or wahl):
        return False
    if not _kurz_ohne_anliegen(t):
        return False
    if janein and (_JA_KOPF.match(t) or _NEIN_KOPF.match(t)):
        return True
    return bool(wahl and _WAHL_KOPF.match(t))


# Nicht-Werte: das Modell schreibt "unbekannt"/"keine Ahnung" in einen Slot,
# wenn der Anrufer NICHTS gesagt hat. Der Reducer haelt das Feld dann fuer
# gefuellt und der Renderer liest es vor ("Keine Ahnung — Wann passt es
# Ihnen?", Live 19.09.2026). "egal" bleibt bewusst drin: das IST eine Angabe.
_KEIN_WERT = frozenset({
    "unbekannt", "unklar", "unbestimmt", "keine ahnung", "kein ahnung",
    "weiss nicht", "weiß nicht", "weiss ich nicht", "weiß ich nicht",
    "keine angabe", "nicht genannt", "nichts", "none", "null", "n/a", "na",
    "-", "--", "?", "leer",
})
# Nur Felder, die einen GEHOERTEN Wert tragen. Steuer-Slots bleiben aussen vor:
# "auskunft_art" kennt "unklar" als echten Zustand (= Anrufer hat noch nicht
# gesagt, ob bestehender oder neuer Termin) — ein Filter darauf verschluckt die
# Rueckfrage und schickt die Maschine direkt in die Namensfrage.
_WERT_SLOTS = frozenset({
    "nachname", "vorname", "telefon", "versicherung", "behandler",
    "besuchsgrund", "wunschzeit", "terminwahl", "termin_hinweis",
    "absage_grund", "fuer_wen", "zweit_fuer_wen",
})


def _ohne_nicht_werte(slots: dict[str, SlotValue]) -> dict[str, SlotValue]:
    for name, sv in list(slots.items()):
        if sv is None or name not in _WERT_SLOTS:
            continue
        wert = str(getattr(sv, "wert", "") or "").strip().lower().rstrip(".!?")
        if wert in _KEIN_WERT:
            slots.pop(name, None)
    return slots


def _kanon_slots(ev: SemanticEvent) -> SemanticEvent:
    """Hirn-Werte in die Form bringen, die Reducer und Suche wirklich lesen."""
    slots: dict[str, SlotValue] = _ohne_nicht_werte(dict(ev.slots))
    wz = slots.get("wunschzeit")
    if wz and wz.wert:
        kanon = _wuensche.wunschzeit(wz.wert)
        if kanon:
            slots["wunschzeit"] = replace(wz, wert=kanon)
    th = slots.get("termin_hinweis")
    if th and th.wert:
        kanon = _wuensche.wunschzeit(th.wert)
        if kanon:
            slots["termin_hinweis"] = replace(th, wert=kanon)
    bg = slots.get("besuchsgrund")
    if bg and bg.wert:
        kanon = _wuensche.besuchsgrund(bg.wert)
        if kanon:
            slots["besuchsgrund"] = replace(bg, wert=kanon)
    return replace(ev, slots=slots)


def _zweit_sichern(ev: SemanticEvent, text: str) -> SemanticEvent:
    """Zwei Verben im Satz: zweite Haelfte darf nie verloren gehen.

    Fuellt nur fehlende zweit_* und holt ein irres buchen/unklar
    zurueck auf das erste Verwaltungsanliegen. Andere Hirn-Slots bleiben.
    """
    extra = _anliegen.zwei_anliegen_slots(text)
    if not extra:
        extra = _anliegen.zwei_anliegen_slots(ev.verstanden or "")
    if not extra:
        return ev
    slots = dict(ev.slots)
    for name, wert in extra.items():
        cur = slots.get(name)
        if cur is None or not cur.wert:
            slots[name] = SlotValue(wert=wert, quelle=Quelle.ABGELEITET)
    zweit_person = slots.get("zweit_fuer_wen")
    fw = slots.get("fuer_wen")
    if zweit_person and zweit_person.wert and fw and fw.wert == zweit_person.wert:
        slots.pop("fuer_wen", None)
    intent = ev.intent
    if extra.get("zweit_anliegen") and intent not in _VERWALTUNG:
        prim, _ = _anliegen.deute(text)
        if prim in _VERWALTUNG:
            intent = prim
    return replace(ev, intent=intent, slots=slots)


def _zahl(wort: str) -> str:
    w = str(wort or "").strip().lower()
    return _ZAHL.get(w, w)


def ist_umzug_wert(wert: str) -> bool:
    return bool(wert) and bool(_UMZUG_RE.search(str(wert)))


def ist_alle_wert(wert: str) -> bool:
    return str(wert or "").strip().lower() in _ALLE_WERTE


def _verwaltung_sichern(ev: SemanticEvent, text: str) -> SemanticEvent:
    """Hirn-JSON darf Alle-Absage, Umzug und Anzahlfrage nicht verlieren.

    Der Reducer oeffnet nur Schubladen, die im Event stehen. Live hat das
    Modell 'Umzug' als Besuchsgrund und 'alle' als suche_weiter geliefert —
    dann feuert die Maschine wieder 'Welchen meinen Sie?'. Hier wird das
    Gesagte festgehalten, bevor eine Schublade aufgeht.
    """
    t = str(text or "")
    slots = dict(ev.slots)
    intent = ev.intent

    bg = slots.get("besuchsgrund")
    if bg and ist_umzug_wert(bg.wert):
        slots["absage_grund"] = SlotValue(wert="umzug", quelle=Quelle.ABGELEITET)
        slots.pop("besuchsgrund", None)
    elif _UMZUG_RE.search(t):
        cur = slots.get("absage_grund")
        if cur is None or not cur.wert:
            slots["absage_grund"] = SlotValue(wert="umzug", quelle=Quelle.ABGELEITET)

    tw = slots.get("terminwahl")
    alle = bool(tw and ist_alle_wert(tw.wert))
    if tw and alle:
        slots["terminwahl"] = SlotValue(wert="alle", quelle=tw.quelle)
    elif _ALLE_RE.search(t) and (
        intent == Intent.ABSAGEN
        or _ABSAGE_RE.search(t)
        or re.fullmatch(r"\s*(?:bitte\s+)?(?:alle|beide)\s*[.!]?\s*", t, re.I)
    ):
        alle = True
        slots["terminwahl"] = SlotValue(wert="alle", quelle=Quelle.ABGELEITET)
        if intent in (Intent.UNKLAR, Intent.AUSKUNFT, Intent.SMALLTALK, Intent.BUCHEN):
            intent = Intent.ABSAGEN
    if alle:
        slots.pop("suche_weiter", None)
        if intent in (Intent.UNKLAR, Intent.AUSKUNFT, Intent.SMALLTALK):
            intent = Intent.ABSAGEN

    m = _ANZAHL_RE.search(t)
    if m and not _ABSAGE_RE.search(t) and not alle:
        n = next((g for g in m.groups() if g), "")
        n = _zahl(n)
        if n:
            slots["anzahl"] = SlotValue(wert=n, quelle=Quelle.ABGELEITET)
            if intent in (Intent.AUSKUNFT, Intent.UNKLAR, Intent.SMALLTALK, Intent.BUCHEN):
                intent = Intent.BESTAETIGEN

    return replace(ev, intent=intent, slots=slots)


def _zuordnung_sichern(ev: SemanticEvent, text: str) -> SemanticEvent:
    """„Welcher ist von meinem Mann?“ oeffnet die Zuordnungs-Schublade."""
    t = " ".join(x for x in (text, ev.verstanden) if x)
    cur = ev.slots.get("termin_zuordnung")
    if cur and cur.wert:
        slots = dict(ev.slots)
        slots.pop("fuer_wen", None)
        return replace(ev, slots=slots)
    if not _WESSEN_RE.search(t):
        return ev
    rolle = _fuer_wen.deute(t)
    if not rolle:
        return ev
    slots = dict(ev.slots)
    slots["termin_zuordnung"] = SlotValue(wert=rolle, quelle=Quelle.ABGELEITET)
    slots.pop("fuer_wen", None)
    return replace(ev, slots=slots)


def _sichern(ev: SemanticEvent, text: str) -> SemanticEvent:
    return _zuordnung_sichern(
        _verwaltung_sichern(_zweit_sichern(ev, text), text),
        text,
    )


def _nlu(
    text: str,
    *,
    offene_frage: str,
    erwartet_janein: bool,
    erwartet_wahl: bool,
    llm_notiz: str = "",
) -> SemanticEvent:
    ev = nlu_test.deuten(
        text,
        offene_frage=offene_frage,
        erwartet_janein=erwartet_janein,
        erwartet_wahl=erwartet_wahl,
    )
    return _sichern(
        replace(_kanon_slots(ev), deutung="nlu", llm=llm_notiz),
        text,
    )


def deuten(
    text: str,
    *,
    offene_frage: str = "",
    erwartet_janein: bool = False,
    erwartet_wahl: bool = False,
    lage: Mapping[str, Any] | None = None,
    llm: LlmVerstehen | None = None,
) -> SemanticEvent:
    # Vor jeder Deutung: bittet der Anrufer etwas UEBER das Gespraech?
    # ``streng`` waehrend Angebot/Ruecklese: dort meint "moechte ich doch nicht"
    # meist den angebotenen Termin, nicht das ganze Anliegen.
    art = _meta.deute(text, streng=erwartet_janein or erwartet_wahl)
    if art:
        return SemanticEvent(
            intent=_META_INTENT[art],
            roh=str(text or ""),
            deutung="meta",
            llm="— Meta-Bitte, kein LLM —",
        )
    # "Hallo?" mitten in einer offenen Frage ist kein neuer Auftrag — der
    # Anrufer prueft, ob noch jemand da ist (Live 34979221, 10 s Stille).
    # Ein Hallo GANZ am Anfang (keine offene Frage) bleibt ein Anliegen/Gruss.
    if offene_frage and re.match(r"^\s*hallo+\s*[?]\s*$", str(text or ""), re.I):
        return SemanticEvent(
            intent=Intent.WIEDERHOLEN,
            roh=str(text or ""),
            deutung="meta",
            llm="— Hallo auf offener Frage, kein LLM —",
        )
    if _ist_formular(text, janein=erwartet_janein, wahl=erwartet_wahl):
        ev = nlu_test.deuten(
            text,
            offene_frage=offene_frage,
            erwartet_janein=erwartet_janein,
            erwartet_wahl=erwartet_wahl,
        )
        return _sichern(
            replace(ev, deutung="formular", llm="— Formular, kein LLM —"),
            text,
        )
    # Eindeutiges Anliegen ohne offene Ja/Nein-Frage: 0 ms, kein Modell.
    # Live 19.09.2026 kostete "Ich haette gern einen Termin." drei Sekunden
    # Hirn, bevor die Identitaetsfrage kam. Ein Mischzug ("Ja, aber absagen")
    # bleibt beim Modell, weil dort erwartet_janein gesetzt ist.
    if not offene_frage and not erwartet_janein and not erwartet_wahl:
        intent, extra = _anliegen.deute(text)
        # Mehr als ein Auftrag: das Modell (oder nachtraege) muss beide sehen.
        if intent is not None and len(_anliegen.befehlsfolge(text)) <= 1:
            slots = {
                k: SlotValue(wert=str(v), quelle=Quelle.GESAGT)
                for k, v in extra.items()
                if v
            }
            return _sichern(
                _kanon_slots(
                    SemanticEvent(
                        intent=intent,
                        slots=slots,
                        roh=str(text or ""),
                        deutung="anliegen",
                        llm="— Anliegen-Regex, kein LLM —",
                    )
                ),
                text,
            )
    # Regel-Schnellweg: die Maschine wartet auf ein Feld mit eigenem Leser und
    # bekommt genau diesen Wert. Kein Modell — sonst kostet "Petsas" 3 Sekunden.
    if offene_frage in _REGEL_FRAGEN and _kurz_ohne_anliegen(str(text or "").strip()):
        ev = nlu_test.deuten(
            text,
            offene_frage=offene_frage,
            erwartet_janein=erwartet_janein,
            erwartet_wahl=erwartet_wahl,
        )
        traf = ev.slots.get(offene_frage)
        if traf is not None and str(getattr(traf, "wert", "") or "").strip():
            return _sichern(
                replace(
                    _kanon_slots(ev),
                    deutung="regel",
                    llm="— Regel traf die offene Frage, kein LLM —",
                ),
                text,
            )
    # "Keine Ahnung" NACH dem Regel-Weg: wo die Regel eine echte Bedeutung kennt
    # (Behandler "weiss nicht" = egal), gewinnt sie. Sonst ist es ein AUSLASSEN —
    # verzichtbare Felder fallen weg, Pflichtfelder benennt der Reducer ehrlich.
    if _ist_nicht_wissen(text, offene_frage):
        return SemanticEvent(
            intent=Intent.AUSLASSEN,
            slots={"nicht_wissen": SlotValue(wert=offene_frage, quelle=Quelle.GESAGT)},
            roh=str(text or ""),
            deutung="meta",
            llm="— weiss nicht, kein LLM —",
        )
    if llm is None:
        return _nlu(
            text,
            offene_frage=offene_frage,
            erwartet_janein=erwartet_janein,
            erwartet_wahl=erwartet_wahl,
            llm_notiz="— Hirn nicht angeschlossen, NLU —",
        )
    ctx = dict(lage or {})
    ctx.setdefault("offene_frage", offene_frage)
    ctx.setdefault("erwartet_janein", erwartet_janein)
    ctx.setdefault("erwartet_wahl", erwartet_wahl)
    budget = _budget_s()
    try:
        if budget > 0:
            hirn, zu_spaet = _mit_deckel(lambda: llm(text, lage=ctx), budget)
            if zu_spaet:
                return _nlu(
                    text,
                    offene_frage=offene_frage,
                    erwartet_janein=erwartet_janein,
                    erwartet_wahl=erwartet_wahl,
                    llm_notiz=f"— Hirn ueber {budget:g} s, Regel —",
                )
        else:
            hirn = llm(text, lage=ctx)
    except Exception as exc:
        return _nlu(
            text,
            offene_frage=offene_frage,
            erwartet_janein=erwartet_janein,
            erwartet_wahl=erwartet_wahl,
            llm_notiz=f"— Hirn-Fehler, NLU — {exc}",
        )
    if isinstance(hirn, Verstand):
        ev = _ordnen.zu_event(hirn, lage=ctx, anrufer=text)
        ev = replace(ev, deutung="hirn", llm=hirn.llm or ev.llm, verstanden=hirn.verstanden)
    elif isinstance(hirn, SemanticEvent):
        ev = hirn
        if not ev.verstanden and ev.roh:
            ev = replace(ev, verstanden="")
    else:
        return _nlu(
            text,
            offene_frage=offene_frage,
            erwartet_janein=erwartet_janein,
            erwartet_wahl=erwartet_wahl,
            llm_notiz="— Hirn lieferte kein Verstehen, NLU —",
        )
    ev = _hirn.ohne_alte_wiederholung(ev, ctx)
    return _sichern(_kanon_slots(replace(ev, deutung=ev.deutung or "hirn")), text)


def nachtraege(
    text: str,
    *,
    erwartet_janein: bool = False,
    erwartet_wahl: bool = False,
    ev: SemanticEvent | None = None,
) -> list[SemanticEvent]:
    """Weitere Anliegen desselben Satzes (W-BEFEHLSLISTE), oder leer.

    Bewusst NICHT in ``deuten`` eingebaut: der Vertrag "ein Satz -> ein
    SemanticEvent" haelt jeden bestehenden Aufrufer unveraendert. Wer
    mehrteilige Anliegen will, fragt hier nach und legt sie mit
    ``reducer.nachtragen`` auf den Stapel.

    Kein Nachtrag auf einer offenen Ja/Nein- oder Wahlfrage: dort gehoert der
    Satz der Frage ("ja, den frueheren"), und ein geparkter Auftrag daraus
    waere geraten.
    """
    t = str(text or "").strip()
    if not t or erwartet_janein or erwartet_wahl:
        return []
    if ev is not None and ev.deutung in ("meta", "formular", "stille"):
        return []
    folge = _anliegen.befehlsfolge(t)
    if len(folge) < 2:
        return []
    schon = {ev.intent} if ev is not None else set()
    out: list[SemanticEvent] = []
    for name in folge:
        intent = _ordnen.FAMILIE_INTENT.get(name)
        if intent is None or intent in schon:
            continue
        schon.add(intent)
        out.append(
            SemanticEvent(
                intent=intent,
                roh=t[:120],
                deutung="nachtrag",
                llm="— Befehlsliste, kein LLM —",
            )
        )
    return out[:2]


__all__ = [
    "deuten",
    "nachtraege",
    "LlmVerstehen",
    "ist_umzug_wert",
    "ist_alle_wert",
]
