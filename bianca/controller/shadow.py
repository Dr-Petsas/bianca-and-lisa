"""Shadow-Beobachter fuer den deterministischen Dialogkern (DIALOG_CONTROLLER).

STRIKT INERT. Dieser Baustein veraendert NIE die Live-Antwort. Ist der Schalter
``CONTROLLER_SHADOW=1`` gesetzt, laeuft nach JEDEM echten Bianca-Zug der reine
Reducer (``bianca/controller/reducer.py``) still parallel; ein kompaktes
Vergleichs- und Gesundheitsprotokoll wird als JSONL geschrieben. Bei
ausgeschaltetem Schalter ist ``umhuellen`` die IDENTITAET — der Live-Pfad ist
dann byte-identisch und ohne jeden Mehraufwand.

Wozu: der Kern soll den grossen Fluss (``bianca/flow.py`` + Waechter) spaeter
ersetzen. BEVOR etwas scharf geschaltet wird, wollen wir schwarz auf weiss
sehen,
  * wo der Live-Fluss schlecht ist (Frage zu bereits gefuelltem Feld,
    dieselbe Frage mehrfach in Folge = Schleife) und
  * was der Kern stattdessen entschieden haette (naechste Frage/Werkzeug).

Reichweite des Shadow (bewusst ehrlich):
  * Sammelphase (Reihenfolge der Fragen): der Kern wird aus den LIVE geernteten
    Slots gespeist -> der Vergleich der naechsten Frage ist aussagekraeftig.
  * Schreib-/Suchphase (Werkzeug-Ergebnisse): die ``ToolOutcome``s stecken tief
    im Fluss und werden hier NICHT rekonstruiert. Ab dem ersten Werkzeug-Zug
    protokolliert der Shadow darum nur noch die Live-Gesundheitssignale und
    haelt den Kern an ("wartet auf Werkzeug"). Das ist die Klasse, in der die
    heutigen Schleifen-/Doppelfragen ohnehin fast alle liegen.

Persistenz: der Kern-Zustand haengt unter dem ``_``-praefixierten Schluessel
``_ctrlShadow`` an der Sitzung — solche Felder werden bewusst NICHT nach JSON
geschrieben (W-ABSAGE-STALLONE), ueberleben also einen Prozess-Neustart nicht
und koennen die Sitzungssicherung nie stoeren.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from bianca.controller import policy as _policy
from bianca.controller.reducer import reduce as _reduce
from bianca.controller.typen import (
    Intent,
    Naechste,
    Quelle,
    SemanticEvent,
    SlotValue,
    State,
)

# --------------------------------------------------------------------------- #
# Schalter + Ablage.
# --------------------------------------------------------------------------- #
_LOG_DIR = Path(os.environ.get("CONTROLLER_SHADOW_DIR") or ".data/controller-shadow")


def _an() -> bool:
    return str(os.environ.get("CONTROLLER_SHADOW") or "").strip() in {"1", "true", "on", "yes"}


# Live-Sammlerfeld -> Kern-Slotname (nur eindeutig uebersetzbare Felder).
_FELD_MAP: dict[str, str] = {
    "grund": "besuchsgrund",
    "nachname": "nachname",
    "vorname": "vorname",
    "versicherung": "versicherung",
    "telefon": "telefon",
    "arzt": "behandler",
    "slotIso": "terminwahl",
}
# Zusaetzlich: Wunschzeit kommt aus wunschText.
_WUNSCH_QUELLE = "wunschText"

_MODUS_INTENT: dict[str, Intent] = {
    "buchen": Intent.BUCHEN,
    "absagen": Intent.ABSAGEN,
    "verschieben": Intent.VERSCHIEBEN,
    "auskunft": Intent.AUSKUNFT,
}

# Live-Fragen, die eine Ja/Nein-Antwort erwarten (fuer die Bestaetigungs-Deutung).
_JANEIN_FRAGEN = {
    "schonmal", "arzt_check", "anrufer_check", "fuer_wen_check",
    "telefon_check", "versicherung_check", "vorname_check", "nachname_check",
    "bestaetigung", "pzr", "rueckruf_ja", "sonst_noch", "termin_ok",
}


# --------------------------------------------------------------------------- #
# Snapshot der relevanten Sammlerfelder (vor dem Zug).
# --------------------------------------------------------------------------- #
def _snapshot(sit: dict) -> dict[str, str]:
    s = (sit.get("sammler") or {}) if isinstance(sit, dict) else {}
    snap: dict[str, str] = {}
    for feld in list(_FELD_MAP) + [_WUNSCH_QUELLE, "modus", "phase", "frage"]:
        snap[feld] = str(s.get(feld) or "")
    return snap


def _mandant(sit: dict) -> dict:
    t = sit.get("tenant") if isinstance(sit, dict) else None
    return t if isinstance(t, dict) else {}


# --------------------------------------------------------------------------- #
# Live-Signale (unabhaengig vom Kern) — die Fehlklassen direkt am Fluss messen.
# --------------------------------------------------------------------------- #
def _live_signale(sit: dict, nachher: dict[str, str]) -> dict[str, Any]:
    """Erkennt am reinen Live-Zustand: Frage-zu-gefuelltem-Feld und Schleife."""
    sig: dict[str, Any] = {}
    frage = nachher.get("frage") or ""

    # I1-Verdacht: die jetzt offene Frage betrifft ein bereits gefuelltes Feld.
    if frage:
        feld = None
        for live_feld, _ctrl in _FELD_MAP.items():
            if live_feld == frage or (frage == "wunsch" and live_feld == "grund"):
                feld = live_feld
                break
        if frage == "wunsch":
            feld = _WUNSCH_QUELLE
        if feld and nachher.get(feld):
            sig["frage_zu_gefuelltem_feld"] = {"frage": frage, "feld": feld}

    # Schleifen-Verdacht: dieselbe Frage in drei Zuegen in Folge.
    hist = list(sit.get("_ctrlShadowFragen") or [])
    if frage:
        hist.append(frage)
    hist = hist[-4:]
    sit["_ctrlShadowFragen"] = hist
    letzte = [f for f in hist if f]
    if len(letzte) >= 3 and letzte[-1] and letzte[-3:] == [letzte[-1]] * 3:
        sig["schleife"] = {"frage": letzte[-1], "n": 3}
    return sig


# --------------------------------------------------------------------------- #
# Kern speisen: LIVE geerntete Slots -> SemanticEvent -> reduce.
# --------------------------------------------------------------------------- #
def _intent(vorher: dict[str, str], nachher: dict[str, str], spoken: str) -> Intent | None:
    modus = nachher.get("modus") or vorher.get("modus") or ""
    it = _MODUS_INTENT.get(modus)
    if it:
        return it
    return None


def _neue_slots(vorher: dict[str, str], nachher: dict[str, str]) -> dict[str, str]:
    """Feld-Updates dieses Zugs (neu gefuellt oder geaendert), auf Kern-Namen."""
    out: dict[str, str] = {}
    for live_feld, ctrl in _FELD_MAP.items():
        v_neu = nachher.get(live_feld) or ""
        if v_neu and v_neu != (vorher.get(live_feld) or ""):
            out[ctrl] = v_neu
    w_neu = nachher.get(_WUNSCH_QUELLE) or ""
    if w_neu and w_neu != (vorher.get(_WUNSCH_QUELLE) or ""):
        out["wunschzeit"] = w_neu
    return out


def _bestaetigung(vorher: dict[str, str], spoken: str) -> bool | None:
    """Ja/Nein-Deutung — nur wenn vor dem Zug eine Ja/Nein-Frage offen war."""
    frage = vorher.get("frage") or ""
    if frage not in _JANEIN_FRAGEN:
        return None
    try:
        from bianca import gehirn
    except Exception:
        return None
    if gehirn.ist_ja(spoken):
        return True
    if gehirn.ist_nein(spoken):
        return False
    return None


def _kern_zug(sit: dict, spoken: str, vorher: dict[str, str],
              nachher: dict[str, str]) -> dict[str, Any] | None:
    """Fuettert den Kern mit den Live-Signalen und gibt die Kern-Decision zurueck."""
    intent = _intent(vorher, nachher, spoken)
    if intent is None:
        return None  # Familie (verbinden/dokument/notfall/...) im Shadow ausgelassen

    pol = sit.get("_ctrlShadowPolicy")
    if pol is None:
        pol = _policy.aus_tenant(_mandant(sit))
        sit["_ctrlShadowPolicy"] = pol
    st = sit.get("_ctrlShadow")
    if not isinstance(st, State):
        st = State()

    slots = {
        k: SlotValue(wert=v, quelle=Quelle.GESAGT)
        for k, v in _neue_slots(vorher, nachher).items()
    }
    ev = SemanticEvent(
        intent=intent,
        slots=slots,
        bestaetigung=_bestaetigung(vorher, spoken),
        roh=spoken[:120],
    )
    st2, dec = _reduce(st, ev, pol)
    sit["_ctrlShadow"] = st2

    kern: dict[str, Any] = {"naechste": dec.naechste.value}
    if getattr(pol, "policy_revision", 0):
        kern["policy_rev"] = pol.policy_revision
    if dec.speak:
        kern["akt"] = dec.speak.akt.value
        if dec.speak.frage_id:
            kern["frage_id"] = dec.speak.frage_id
    if dec.tool:
        kern["tool"] = dec.tool.name
    if dec.naechste == Naechste.WERKZEUG:
        kern["wartet_auf_werkzeug"] = True
    return kern


# --------------------------------------------------------------------------- #
# Protokoll.
# --------------------------------------------------------------------------- #
def _live_zug(reply: dict, nachher: dict[str, str]) -> dict[str, Any]:
    r = reply if isinstance(reply, dict) else {}
    live: dict[str, Any] = {"frage": nachher.get("frage") or ""}
    if r.get("book"):
        live["book"] = True
    if r.get("hangup"):
        live["hangup"] = True
    if r.get("transfer"):
        live["transfer"] = True
    if r.get("warte"):
        live["warte"] = True
    txt = str(r.get("text") or "")
    if txt:
        live["text"] = txt[:160]
    return live


def _schreibe(zeile: dict[str, Any]) -> None:
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        tag = datetime.now(timezone.utc).strftime("%Y%m%d")
        with (_LOG_DIR / f"{tag}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(zeile, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Protokoll darf den Anruf NIE beeintraechtigen.


def beobachte(sit: dict, spoken: str, reply: dict, vorher: dict[str, str]) -> None:
    """Nach dem Live-Zug: Kern still mitlaufen lassen + Vergleich protokollieren."""
    if not isinstance(sit, dict):
        return
    nachher = _snapshot(sit)
    sig = _live_signale(sit, nachher)
    kern = _kern_zug(sit, spoken, vorher, nachher)

    zeile: dict[str, Any] = {
        "ts": time.time(),
        "sid": str(sit.get("id") or ""),
        "mandant": str(_mandant(sit).get("clientId") or ""),
        "zug": int(sit.get("_ctrlShadowZug") or 0) + 1,
        "roh": str(spoken or "")[:120],
        "modus": nachher.get("modus") or "",
        "live": _live_zug(reply, nachher),
    }
    sit["_ctrlShadowZug"] = zeile["zug"]
    if kern is not None:
        zeile["kern"] = kern
        lf = zeile["live"].get("frage") or ""
        kf = kern.get("frage_id") or ""
        if lf and kf and lf != kf and not kern.get("wartet_auf_werkzeug"):
            zeile["divergenz_frage"] = {"live": lf, "kern": kf}
    if sig:
        zeile["live_signale"] = sig
    _schreibe(zeile)


# --------------------------------------------------------------------------- #
# Die eine Einhaengung: Umhuellung des Live-Turn-Handlers.
# --------------------------------------------------------------------------- #
def umhuellen(turn_fn: Callable) -> Callable:
    """Gibt den beobachtenden Wrapper zurueck — oder (Schalter aus) die
    Originalfunktion UNVERAENDERT (byte-identischer Live-Pfad)."""
    if not _an():
        return turn_fn

    def _wrap(sit: dict, spoken: str, **kw):
        vorher = _snapshot(sit) if isinstance(sit, dict) else {}
        reply = turn_fn(sit, spoken, **kw)
        try:
            beobachte(sit, spoken, reply if isinstance(reply, dict) else {}, vorher)
        except Exception as e:  # der Shadow darf den Anruf NIE stoeren
            _schreibe({"ts": time.time(), "fehler": repr(e)[:200]})
        return reply

    _wrap.__name__ = getattr(turn_fn, "__name__", "user_turn")
    _wrap.__wrapped__ = turn_fn  # type: ignore[attr-defined]
    return _wrap


__all__ = ["umhuellen", "beobachte"]
