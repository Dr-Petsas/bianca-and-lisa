"""Session-Brain (W-HIRN 03.09.2026): ein Anliegen-Gedaechtnis fuer BEIDE Stimmen.

Chef (03.09.2026): "erst erkennen dann handeln" — Bianca kannte nur den
Default 'Termin buchen', dabei ist Buchen nur EINE Loesung fuer EINES von
mehreren Anliegen. Dieses Modul haelt pro Anruf, WAS der Mensch will
(Handlung x Gegenstand), eine kurze Warteschlange fuer ein zweites Anliegen
und die Uebersetzung in die bestehenden deterministischen Maschinen.

Arbeitsteilung:
- kern/intent.py DEUTET den Satz (LLM + Fast-Paths + Fallback) -> Deutung.
- hirn.anwenden() SCHREIBT die Deutung in die Sitzung: Queue, aktives
  Anliegen, und (nur Bianca) sammler["modus"] als Freigabe der Maschinen.
- Die Maschinen (bianca/flow, bianca/verwalten, bianca/weiterleiten,
  Lisas Werkzeuge) loesen das Anliegen wie bisher — sie laufen nur noch
  NACH der Erkennung, nie mehr als Default.

Handlungen (fachfrei, aus Blessing/Thaler/Meddent-Gespraechen destilliert):
  ERREICHEN  Person oder Rolle soll jetzt da sein
  WISSEN     Antwort ueber etwas Bestehendes/Geltendes
  AENDERN    an einem bestehenden Vorgang drehen (ersatz: neuer Slot ja/nein)
  ANLEGEN    etwas Neues — fast immer der neue Termin
  ABGEBEN    die Praxis erledigt es spaeter (Notiz, Rueckruf)
  KEINE      der Satz traegt keine Handlung

Gegenstaende: PERSON | VORGANG | SACHE | REGEL.

Das Hirn lebt NUR in diesem Anruf (sit["hirn"], JSON-tauglich, wird mit der
Sitzung gesichert). Das Praxisgedaechtnis (kern/gedaechtnis.py) bleibt die
anruf-uebergreifende Schicht — hier keine Ueberschneidung.
"""

from __future__ import annotations

import re
from typing import Any

HANDLUNGEN = {"ERREICHEN", "WISSEN", "AENDERN", "ANLEGEN", "ABGEBEN", "KEINE"}
GEGENSTAENDE = {"PERSON", "VORGANG", "SACHE", "REGEL", ""}
ZUEGE = {"halten", "verfeinern", "wechseln", "zweites", "zurueck"}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def leer() -> dict[str, Any]:
    return {"anliegen": [], "aktiv": "", "naechsteId": 1}


def init(sit: dict, *, auftrag: str = "") -> dict[str, Any]:
    """Hirn in der Sitzung anlegen. Lisa saet den Chef-Auftrag als erstes
    Anliegen (quelle=auftrag); Bianca startet leer — kein Default-Buchen."""
    h = leer()
    sit["hirn"] = h
    seed = seed_von_auftrag(auftrag) if _s(auftrag) else None
    if seed:
        _anhaengen(sit, seed, aktivieren=True)
    return h


# --- Lisa-Seed: Chef-Auftrag -> erstes Anliegen ----------------------------

_SEED_ABSAGE_RE = re.compile(r"absag\w*|abgesagt|storn\w*|\bcancel\w*", re.I)
_SEED_VERSCHIEBEN_RE = re.compile(
    r"verschieb\w*|verschoben|umbuch\w*|verleg\w*|umleg\w*|vorverleg\w*", re.I,
)
_SEED_TERMIN_RE = re.compile(
    r"\btermin\w*|recall\w*|kontrolle|prophylaxe|nachsorge|buch\w*|erinner\w*|"
    r"slot\w*|sprechstunde\w*|zahnreinigung",
    re.I,
)


def seed_von_auftrag(auftrag: str) -> dict[str, Any] | None:
    """Deterministisch, ohne LLM — der Chef-Text ist kurz und bekannt."""
    t = _s(auftrag)
    if not t:
        return None
    if _SEED_ABSAGE_RE.search(t) and not _SEED_VERSCHIEBEN_RE.search(t):
        return _anliegen("AENDERN", "VORGANG", ersatz=False, spiegel=t, quelle="auftrag")
    if _SEED_VERSCHIEBEN_RE.search(t):
        return _anliegen("AENDERN", "VORGANG", ersatz=True, spiegel=t, quelle="auftrag")
    if _SEED_TERMIN_RE.search(t):
        return _anliegen("ANLEGEN", "VORGANG", spiegel=t, quelle="auftrag")
    # Reine Nachricht (lisa/mission.rahme_auftrag kennt dieselbe Grenze):
    # ausrichten und fertig — kein Termin-Gespraech eroeffnen.
    return _anliegen("ABGEBEN", "SACHE", spiegel=t, quelle="auftrag")


# --- Kernzugriffe -----------------------------------------------------------

def _anliegen(handlung: str, gegenstand: str = "", *, fuer: str = "selbst",
              ersatz: bool | None = None, spiegel: str = "",
              quelle: str = "entdeckt") -> dict[str, Any]:
    return {
        "id": "",
        "handlung": handlung if handlung in HANDLUNGEN else "KEINE",
        "gegenstand": gegenstand if gegenstand in GEGENSTAENDE else "",
        "fuer": "anderer" if fuer == "anderer" else "selbst",
        "ersatz": ersatz if isinstance(ersatz, bool) else None,
        "spiegel": _s(spiegel)[:160],
        "status": "offen",
        "quelle": quelle,
    }


def hirn(sit: dict) -> dict[str, Any]:
    h = sit.get("hirn")
    if not isinstance(h, dict) or "anliegen" not in h:
        h = leer()
        sit["hirn"] = h
    return h


def aktiv(sit: dict) -> dict[str, Any] | None:
    h = hirn(sit)
    aid = _s(h.get("aktiv"))
    if not aid:
        return None
    for a in h.get("anliegen") or []:
        if a.get("id") == aid:
            return a
    return None


def _anhaengen(sit: dict, a: dict[str, Any], *, aktivieren: bool) -> dict[str, Any]:
    h = hirn(sit)
    n = int(h.get("naechsteId") or 1)
    a["id"] = f"a{n}"
    h["naechsteId"] = n + 1
    h.setdefault("anliegen", []).append(a)
    h["anliegen"] = h["anliegen"][-8:]
    if aktivieren:
        alt = aktiv(sit)
        if alt is not None and alt.get("status") == "aktiv":
            alt["status"] = "geparkt"
        a["status"] = "aktiv"
        h["aktiv"] = a["id"]
        _schalten(sit, a)
    return a


def anliegen_hinzufuegen(sit: dict, a: dict[str, Any] | None,
                         *, aktivieren: bool = True) -> dict[str, Any] | None:
    """Oeffentlicher Weg fuer neue Anliegen von aussen (z. B. Lisas
    /api/auftrag: neuer Chef-Auftrag mitten im Gespraech)."""
    if not isinstance(a, dict):
        return None
    return _anhaengen(sit, a, aktivieren=aktivieren)


def modus_von(a: dict[str, Any] | None) -> str:
    """Handlung x Gegenstand -> Bianca-Maschinenmodus ('' = keine Maschine,
    das Gespraechs-LLM antwortet mit dem Anliegen-Stand im Prompt)."""
    if not a:
        return ""
    handlung = _s(a.get("handlung"))
    gegenstand = _s(a.get("gegenstand"))
    if handlung == "ANLEGEN":
        return "buchen"
    if handlung == "AENDERN":
        # ersatz unbekannt -> verschieben (haelt den Termin, bietet Ausweich
        # an — der Anrufer kann ablehnen; absagen nur bei klarem 'kein Ersatz').
        return "absagen" if a.get("ersatz") is False else "verschieben"
    if handlung == "WISSEN" and gegenstand == "VORGANG":
        return "auskunft"
    return ""


def _ist_bianca(sit: dict) -> bool:
    return _s(sit.get("stimme")).lower() == "bianca"


def _schalten(sit: dict, a: dict[str, Any]) -> None:
    """Das aktive Anliegen in die Maschinen uebersetzen.

    Bianca: sammler["modus"] ist die Freigabe der deterministischen Fluesse —
    frueher setzte ihn die _TERMIN_RE-Regex (Default buchen), jetzt NUR das
    Hirn. Lisa hat keinen Sammler; dort wirkt das Anliegen ueber stand_block()
    im Prompt plus die vorhandenen Werkzeuge.
    """
    handlung = _s(a.get("handlung"))
    if handlung == "ERREICHEN":
        # bianca/weiterleiten.zug konsumiert den Zettel (auch wenn die
        # Verbinde-Regex den Satz nicht fasst: "Ich haette gern Doktor X").
        sit["hirnVerbinden"] = {"person": _s(a.get("spiegel"))}
    if handlung == "ABGEBEN":
        sit["hirnAbgeben"] = {"offen": True, "was": _s(a.get("spiegel"))}
    if not _ist_bianca(sit):
        return
    s = sit.setdefault("sammler", {})
    modus = modus_von(a)
    if modus:
        if s.get("modus") != modus or s.get("phase") == "fertig":
            s["modus"] = modus
            if s.get("phase") != "gebucht":
                # 'gebucht' bleibt stehen: flow.zug traegt dort die
                # Frisch-Absage-Sonderwege (W-FRISCH-ABSAGE 02.09.2026).
                s["phase"] = ""
            s["frage"] = ""
            # Signal fuer flow/verwalten: gleiche Konvention wie frueher die
            # Regex-Ernte ("modus" in neu) — dort haengt der Verwaltungs-Reset.
            sit["hirnModusNeu"] = True
    elif s.get("modus") and s.get("phase") not in {"gebucht"}:
        # Nicht-Buchungs-Anliegen aktiv: die Buchungs-/Verwaltungsmaschine
        # still legen, damit sie nicht in ihre naechste Frage zurueckfaellt.
        s["modus"] = ""
        s["frage"] = ""


def anwenden(sit: dict, deutung: dict[str, Any] | None) -> dict[str, Any]:
    """Eine Deutung (kern/intent.py) in die Sitzung schreiben.

    Liefert {"zug": ..., "anliegen": aktives Anliegen oder None}.
    Bei kanal != ok oder handlung KEINE aendert sich nichts — nie ein
    stiller Fallback auf buchen.
    """
    d = deutung or {}
    zug = _s(d.get("zug")) or "halten"
    if zug not in ZUEGE:
        zug = "halten"
    kanal = _s(d.get("kanal")) or "ok"
    a = aktiv(sit)
    if kanal != "ok":
        return {"zug": "kanal", "anliegen": a}

    if zug in {"halten", "verfeinern"}:
        if a is not None and _s(d.get("spiegel")) and d.get("konfidenz_spiegel", True):
            # Spiegel darf sich schaerfen, Handlung bleibt.
            if len(_s(d.get("spiegel"))) > len(_s(a.get("spiegel"))):
                a["spiegel"] = _s(d.get("spiegel"))[:160]
        return {"zug": zug, "anliegen": a}

    if zug == "zurueck":
        h = hirn(sit)
        for kand in reversed(h.get("anliegen") or []):
            if kand.get("status") == "geparkt":
                if a is not None and a.get("status") == "aktiv":
                    a["status"] = "geparkt"
                kand["status"] = "aktiv"
                h["aktiv"] = kand["id"]
                _schalten(sit, kand)
                return {"zug": zug, "anliegen": kand}
        return {"zug": "halten", "anliegen": a}

    handlung = _s(d.get("handlung")).upper()
    if handlung not in HANDLUNGEN or handlung == "KEINE":
        return {"zug": "halten", "anliegen": a}
    neu = _anliegen(
        handlung,
        _s(d.get("gegenstand")).upper(),
        fuer=_s(d.get("fuer")) or "selbst",
        ersatz=d.get("ersatz") if isinstance(d.get("ersatz"), bool) else None,
        spiegel=_s(d.get("spiegel")),
    )

    if zug == "zweites" and a is not None:
        # Zusaetzliches Anliegen: merken, das aktuelle laeuft weiter.
        _anhaengen(sit, neu, aktivieren=False)
        return {"zug": zug, "anliegen": a}

    # wechseln — oder erstes Anliegen des Gespraechs.
    if a is not None and a.get("handlung") == handlung \
            and modus_von(a) == modus_von(neu):
        # Gleiche Handlung, gleiche Maschine: kein echter Wechsel.
        if len(neu["spiegel"]) > len(_s(a.get("spiegel"))):
            a["spiegel"] = neu["spiegel"]
        if isinstance(d.get("ersatz"), bool):
            a["ersatz"] = d["ersatz"]
        return {"zug": "halten", "anliegen": a}
    ein = _anhaengen(sit, neu, aktivieren=True)
    return {"zug": "wechseln" if a is not None else "erstes", "anliegen": ein}


def erledigt(sit: dict, *, naechstes: bool = True) -> dict[str, Any] | None:
    """Aktives Anliegen abhaken; naechstes offenes ruecken lassen."""
    h = hirn(sit)
    a = aktiv(sit)
    if a is not None:
        a["status"] = "erledigt"
    h["aktiv"] = ""
    if not naechstes:
        return None
    for kand in h.get("anliegen") or []:
        if kand.get("status") == "offen":
            kand["status"] = "aktiv"
            h["aktiv"] = kand["id"]
            _schalten(sit, kand)
            return kand
    return None


def sync_nach_zug(sit: dict) -> None:
    """Nach jedem Maschinen-/LLM-Zug: Hirn mit dem Sammler abgleichen.

    - Maschine hat das Anliegen fertig (phase fertig/gebucht) -> erledigt,
      naechstes offenes Anliegen rueckt nach.
    - Maschine hat INTERN den Modus gewechselt (z. B. verwalten: Auskunft ->
      Neubuchung nach ausdruecklichem Ja) -> Anliegen nachtragen
      (quelle=maschine), damit Hirn und Maschine nie auseinanderlaufen.
    """
    if not _ist_bianca(sit) or "hirn" not in sit:
        return
    s = sit.get("sammler") or {}
    modus = _s(s.get("modus"))
    phase = _s(s.get("phase"))
    a = aktiv(sit)
    if a is not None and modus and modus == modus_von(a):
        if phase in {"fertig", "gebucht"} and a.get("status") == "aktiv":
            a["status"] = "erledigt"
            hirn(sit)["aktiv"] = ""
            naechst = None
            for kand in hirn(sit).get("anliegen") or []:
                if kand.get("status") == "offen":
                    naechst = kand
                    break
            if naechst is not None and phase != "gebucht":
                # Nach 'gebucht' fragt die Maschine selbst weiter — nur nach
                # 'fertig' rueckt das naechste Anliegen automatisch nach.
                naechst["status"] = "aktiv"
                hirn(sit)["aktiv"] = naechst["id"]
                _schalten(sit, naechst)
        return
    if modus and (a is None or modus != modus_von(a)):
        # Interner Maschinen-Wechsel: nachtragen statt gegensteuern.
        rueck = {"buchen": ("ANLEGEN", "VORGANG", None),
                 "absagen": ("AENDERN", "VORGANG", False),
                 "verschieben": ("AENDERN", "VORGANG", True),
                 "auskunft": ("WISSEN", "VORGANG", None)}.get(modus)
        if rueck:
            neu = _anliegen(rueck[0], rueck[1], ersatz=rueck[2],
                            spiegel=_s(s.get("grundWortlaut") or s.get("grund")),
                            quelle="maschine")
            h = hirn(sit)
            alt = aktiv(sit)
            if alt is not None and alt.get("status") == "aktiv":
                alt["status"] = "geparkt"
            n = int(h.get("naechsteId") or 1)
            neu["id"] = f"a{n}"
            h["naechsteId"] = n + 1
            neu["status"] = "aktiv"
            h.setdefault("anliegen", []).append(neu)
            h["anliegen"] = h["anliegen"][-8:]
            h["aktiv"] = neu["id"]


# --- Prompt-Stand -----------------------------------------------------------

_REGEL_JE_HANDLUNG = {
    "ERREICHEN": "Der Anrufer will eine Person/Rolle erreichen: durchstellen oder Rueckruf — KEINEN Termin anbieten, nicht nach Terminwuenschen fragen.",
    "WISSEN": "Der Anrufer will eine Auskunft: beantworten (Praxiswissen/Termine) — KEINEN neuen Termin andrehen.",
    "ABGEBEN": "Der Anrufer will, dass die Praxis sich kuemmert: Notiz/Rueckruf zusagen — KEINEN Termin anbieten.",
    "AENDERN": "Es geht um einen BESTEHENDEN Termin. Will der Anrufer keinen Ersatz, biete KEINEN neuen Termin an.",
    "ANLEGEN": "Der Anrufer moechte einen neuen Termin — die Terminaufnahme fuehrt die Maschine.",
}


def stand_block(sit: dict) -> str:
    """ANLIEGEN-Block fuer den Systemprompt (beide Stimmen). '' wenn leer."""
    h = sit.get("hirn")
    if not isinstance(h, dict):
        return ""
    a = aktiv(sit)
    zeilen: list[str] = []
    if a is not None:
        kopf = f"Aktives Anliegen: {a.get('handlung')}"
        if _s(a.get("spiegel")):
            kopf += f" — \u201e{_s(a.get('spiegel'))}\u201c"
        if a.get("fuer") == "anderer":
            kopf += " (ruft fuer eine andere Person an)"
        zeilen.append(kopf)
        regel = _REGEL_JE_HANDLUNG.get(_s(a.get("handlung")))
        if regel:
            if a.get("handlung") == "AENDERN" and a.get("ersatz") is False:
                regel = ("Es geht um einen BESTEHENDEN Termin, der Anrufer will "
                         "ABSAGEN OHNE Ersatz: keinen neuen Termin anbieten.")
            zeilen.append(regel)
    wartend = [x for x in (h.get("anliegen") or [])
               if x.get("status") in {"offen", "geparkt"}]
    if wartend:
        zeilen.append("Wartende Anliegen: " + "; ".join(
            f"{x.get('handlung')} \u201e{_s(x.get('spiegel'))[:60]}\u201c" for x in wartend[:3]
        ) + " — nach dem aktiven Anliegen darauf zurueckkommen.")
    if not zeilen:
        return ""
    return "ANLIEGEN (Session-Hirn — erst verstehen, dann loesen; buchen ist nur EINE Loesung)\n" + "\n".join(zeilen)
