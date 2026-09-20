"""Enforce-Adapter: der Dialogkern spricht am Telefon.

Bis zum 19.09.2026 lief der Kern ausschliesslich im Schatten
(``bianca/controller/shadow.py``) — er entschied still mit, gesprochen hat
immer der Legacy-Fluss. Dieses Modul ist der Schalter dazu: ist der Kern fuer
DIESEN Anruf scharf, beantwortet er den Zug selbst, mit den ECHTEN
Kalenderwerkzeugen (``tool_gateway.ToolGateway`` -> ``kern/calendar.py``).

Der Ablauf ist nicht neu geschrieben, sondern derselbe, der im Studio gespielt
wird (``orchestrator.TestGespraech``): Verstehen -> Reducer -> Werkzeug-
Schleife -> Renderer. Der EINZIGE Unterschied ist das eingehaengte Gateway.
Es gibt bewusst keinen zweiten, nur fuer Live gepflegten Ablauf — sonst
driften Studio-Probe und Telefon auseinander.

Drei Sicherheiten:

1. **Mandantenscharfer Schalter.** ``CONTROLLER_ENFORCE`` nimmt ``0``/``off``
   (Default, byte-identischer Legacy-Pfad), ``1``/``all`` (jeder Anruf) oder
   eine Liste von Marken: clientId, Mandantenname, angerufene Nummer (DID)
   ODER Anrufernummer. So kann genau EINE Testnummer den neuen Kern hoeren,
   waehrend jeder Patient den bewaehrten Weg bekommt.
2. **Uebergabe statt Raten.** Fuehrt der Kern eine Aufgabe nicht
   (``Naechste.UEBERGEBEN``), gibt ``zug`` ``None`` zurueck — der Legacy-Pfad
   uebernimmt im SELBEN Zug. Vorher werden die schon geernteten Angaben in
   den Legacy-Sammler gespiegelt, damit niemand zweimal seinen Namen
   buchstabiert.
3. **Nie werfend.** Jede Ausnahme endet in der Uebergabe an Legacy, nie in
   einem stummen Anruf. Der Kern-Zustand haengt unter dem ``_``-praefixierten
   Schluessel ``_kernLauf`` an der Sitzung (wird nicht nach JSON geschrieben —
   W-ABSAGE-STALLONE) und lebt damit genau so lange wie der Prozess.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bianca.controller import policy as _policy
from bianca.controller.orchestrator import TestGespraech
from bianca.controller.tool_gateway import ToolGateway
from bianca.controller.typen import Naechste

_LOG_DIR = Path(os.environ.get("CONTROLLER_LIVE_DIR") or ".data/controller-live")

_AUS = {"", "0", "off", "aus", "false", "no", "nein"}
_ALLE = {"1", "all", "alle", "true", "on", "ja", "enforce"}


def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""


# --------------------------------------------------------------------------- #
# Schalter
# --------------------------------------------------------------------------- #
def _marken(sit: dict) -> set[str]:
    """Alles, woran dieser Anruf erkannt werden darf (klein geschrieben)."""
    t = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    roh = [
        _s(t.get("clientId")), _s(t.get("id")), _s(t.get("_id")),
        _s(t.get("mandant")), _s(t.get("name")), _s(sit.get("mandant")),
        # Angerufene Nummer und Anrufer. ``callerPhone`` ist der Schluessel,
        # den ``agentprofil.call_erfassen`` wirklich setzt (+E164) — ohne ihn
        # koennte eine einzelne TESTNUMMER den Kern nicht scharf stellen.
        _s(sit.get("did")), _s(sit.get("caller")), _s(sit.get("callerPhone")),
    ]
    marken = {m.lower() for m in roh if m}
    # Nummern zusaetzlich nackt (0177… == +49177…): die letzten 9 Ziffern
    # sind bei deutschen Nummern der unterscheidende Teil.
    for m in list(marken):
        ziffern = "".join(c for c in m if c.isdigit())
        if len(ziffern) >= 7:
            marken.add(ziffern)
            marken.add(ziffern[-9:])
    return marken


def an(sit: dict) -> bool:
    """Spricht der Kern in DIESEM Anruf?"""
    roh = _s(os.environ.get("CONTROLLER_ENFORCE")).lower()
    if roh in _AUS:
        return False
    if roh in _ALLE:
        return True
    if not isinstance(sit, dict):
        return False
    marken = _marken(sit)
    for teil in roh.replace(";", ",").split(","):
        wunsch = teil.strip().lower()
        if not wunsch:
            continue
        if wunsch in marken:
            return True
        ziffern = "".join(c for c in wunsch if c.isdigit())
        if len(ziffern) >= 7 and (ziffern in marken or ziffern[-9:] in marken):
            return True
    return False


# --------------------------------------------------------------------------- #
# Ruhe-Schwelle je Frage (dieselbe Staffelung wie gehirn.stille_ms)
# --------------------------------------------------------------------------- #
_KURZ = 350      # Ja/Nein, Wahl — der Anrufer antwortet in einem Wort
_DIKTAT = 1500   # Name/Nummer — nie mitten in der Ziffernfolge schneiden
_NORMAL = 500

_JANEIN_FRAGEN = frozenset({
    "schonmal", "anrufer_check", "rueckruf_ja", "anmeldung_rueckruf",
    "arzt_notiz", "mehrfach_ok", "fach_weiter", "auskunft_klar",
})
_DIKTAT_FRAGEN = frozenset({"nachname", "vorname", "telefon", "buchstabieren"})


def _stille_ms(offene_frage: str, wahl: bool, janein: bool) -> int:
    if offene_frage in _DIKTAT_FRAGEN:
        return _DIKTAT
    if offene_frage in _JANEIN_FRAGEN or wahl or janein:
        return _KURZ
    return _NORMAL


# --------------------------------------------------------------------------- #
# Lauf: Kern-Zustand + echtes Gateway, an der Sitzung gehalten
# --------------------------------------------------------------------------- #
def _tenant(sit: dict) -> dict:
    t = sit.get("tenant")
    return t if isinstance(t, dict) else {}


def _protokoll_hook(sit: dict):
    """Rohergebnis jedes Werkzeugs in die Tool-Spur der Sitzung schreiben.

    Die Spur ist die Evidenz, aus der CallR die Kategorie, ``/anrufe`` die
    Werkzeug-Karte und der Gedaechtnis-Report seine Zeile bauen. Ohne diesen
    Haken waere eine Kern-Buchung fuer die Nacharbeit unsichtbar.
    """
    def _merke(name: str, res: dict, args: dict) -> None:
        from kern import sitzung as _sitzung
        _sitzung.merke_tool(sit, name, res, args=args)
    return _merke


def _vorbelegen(gespraech: TestGespraech, sit: dict) -> None:
    """Erkannten Anrufer und letzten Besuch in den Kern-Zustand heben.

    Beides ist bereits belegte Wahrheit aus der Cloud Function bzw. der
    Kartei (``kern/agentprofil``, ``bianca/hintergrund``) — der Kern soll den
    Anrufer nicht nach etwas fragen, was die Praxis schon weiss.
    """
    a = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
    if a:
        weiblich = _s(a.get("geschlecht")).lower().startswith(("f", "w"))
        gespraech.state.anrufer = {
            "anrede": "Frau" if weiblich else "Herr",
            "nachname": _s(a.get("nachname")),
            "vorname": _s(a.get("vorname")),
            "telefon": _s(a.get("telefon")),
            "patientId": _s(a.get("patientId")),
        }
    k = sit.get("anruferKartei") if isinstance(sit.get("anruferKartei"), dict) else {}
    if k:
        gespraech.state.letzter_besuch = {
            "arzt": _s(k.get("arzt")) or _s(k.get("doctorName")),
            "grund": _s(k.get("grund")) or _s(k.get("motivName")),
            "wann": _s(k.get("wann")) or _s(k.get("abstand")),
        }


def lauf(sit: dict) -> TestGespraech:
    """Den Kern-Lauf dieses Anrufs holen (oder anlegen)."""
    g = sit.get("_kernLauf")
    if isinstance(g, TestGespraech):
        return g
    tenant = _tenant(sit)
    gw = ToolGateway(
        tenant,
        # Der Kern ist jetzt die Wahrheit: er darf schreiben. Die harten
        # Gates bleiben darunter (WRITE_LIVE, _testNoWrite, Read-after-write,
        # Patienten-Bindung) — die leben in kern/calendar.py.
        nur_lesen=False,
        sit=sit,
        protokoll=_protokoll_hook(sit),
    )
    try:
        from bianca.controller import hirn as _hirn
        llm = _hirn.deuten
    except Exception:
        llm = None  # ohne Modell greift die Regel-NLU in verstehen.deuten
    g = TestGespraech(_policy.aus_tenant(tenant), llm=llm, gateway=gw)
    _vorbelegen(g, sit)
    sit["_kernLauf"] = g
    return g


# --------------------------------------------------------------------------- #
# Uebergabe: was der Kern schon weiss, soll Legacy nicht erneut erfragen
# --------------------------------------------------------------------------- #
# Kern-Slot -> Legacy-Sammlerfeld. BEWUSST ohne ``terminwahl``/Slot-ISO: eine
# gespiegelte Slotwahl koennte den Legacy-Fluss zum Buchen bringen, ohne dass
# der Anrufer sie im Legacy-Wortlaut bestaetigt hat.
_SPIEGEL = {
    "nachname": "nachname",
    "vorname": "vorname",
    "telefon": "telefon",
    "besuchsgrund": "grund",
    "behandler": "arzt",
    "versicherung": "versicherung",
    "wunschzeit": "wunschText",
}
_MODUS = {"buchen": "buchen", "absagen": "absagen",
          "verschieben": "verschieben", "auskunft": "auskunft"}


def _spiegeln(sit: dict, g: TestGespraech) -> None:
    aktiv = g.state.aktiv()
    if aktiv is None:
        return
    s = sit.setdefault("sammler", {})
    for slot, feld in _SPIEGEL.items():
        sv = aktiv.slots.get(slot)
        wert = _s(getattr(sv, "wert", "")) if sv else ""
        if wert and not _s(s.get(feld)):
            s[feld] = wert
    modus = _MODUS.get(aktiv.typ)
    if modus and not _s(s.get("modus")):
        s["modus"] = modus


# --------------------------------------------------------------------------- #
# Protokoll (eigene Datei, damit der Schatten-Vergleich lesbar bleibt)
# --------------------------------------------------------------------------- #
def _schreibe(zeile: dict[str, Any]) -> None:
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        tag = datetime.now(timezone.utc).strftime("%Y%m%d")
        with (_LOG_DIR / f"{tag}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(zeile, ensure_ascii=False) + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Der Zug
# --------------------------------------------------------------------------- #
def zug(sit: dict, spoken: str, *, stille: bool = False) -> dict[str, Any] | None:
    """Einen Anrufer-Zug vom Kern beantworten.

    Rueckgabe: Antwort-Dict wie der Legacy-Fluss (``text``/``hangup``/
    ``warte``/``stilleMs``) — oder ``None``, wenn der Legacy-Pfad uebernehmen
    soll (Uebergabe, Fehler, Schalter aus).
    """
    if not isinstance(sit, dict) or not an(sit):
        return None
    t0 = time.time()
    try:
        g = lauf(sit)
        za = g.stille() if stille else g.eingabe(_s(spoken))
    except Exception as exc:  # noqa: BLE001 — ein Kern-Fehler legt nie auf
        _schreibe({"ts": time.time(), "sid": _s(sit.get("id")),
                   "fehler": repr(exc)[:300], "roh": _s(spoken)[:120]})
        return None

    text = _s(za.antwort)
    eintrag: dict[str, Any] = {
        "ts": time.time(),
        "sid": _s(sit.get("id")),
        "mandant": _s(_tenant(sit).get("clientId")),
        "zug": int(sit.get("_kernZug") or 0) + 1,
        "roh": _s(spoken)[:160],
        "naechste": _s(za.naechste),
        "grund": _s(za.grund),
        "tool": _s(za.tool),
        "text": text[:240],
        "ms": int((time.time() - t0) * 1000),
    }
    sit["_kernZug"] = eintrag["zug"]

    if za.uebergeben:
        # Der Kern fuehrt diese Aufgabe nicht — Legacy im selben Zug.
        try:
            _spiegeln(sit, g)
        except Exception:
            pass
        eintrag["uebergabe"] = True
        _schreibe(eintrag)
        return None

    if not text:
        if _s(za.naechste) == Naechste.WARTEN.value:
            # Zustand fortgeschrieben, aber der Anrufer hat den Turn noch
            # nicht abgegeben (Diktat-Fragment). Stiller Zug, weiterhoeren.
            _schreibe(eintrag)
            return {"text": "", "book": None, "warte": True,
                    "stilleMs": _DIKTAT}
        # Kein Satz, keine Uebergabe: das darf nie ein stummer Anruf sein.
        eintrag["stumm"] = True
        _schreibe(eintrag)
        return None

    _schreibe(eintrag)
    erw = getattr(g, "_erw", None)
    aus: dict[str, Any] = {
        "text": text,
        "book": None,
        "stilleMs": _stille_ms(
            _s(getattr(erw, "offene_frage", "")),
            bool(getattr(erw, "wahl", False)),
            bool(getattr(erw, "janein", False)),
        ),
    }
    if za.hangup or _s(za.naechste) == Naechste.AUFLEGEN.value:
        aus["hangup"] = True
    return aus


def uebernimmt(sit: dict) -> bool:
    """Hat der Kern in diesem Anruf schon gesprochen? (Diagnose/UI)"""
    return bool(isinstance(sit, dict) and sit.get("_kernZug"))


__all__ = ["an", "zug", "lauf", "uebernimmt"]
