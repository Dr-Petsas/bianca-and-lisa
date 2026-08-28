"""Biancas Buchungsfluss — deterministisch, ohne LLM auf dem Pflichtpfad.

Jeder Zug: erst Slot-Wahl/Bestätigung prüfen, dann alle Deuter (gehirn),
dann Hintergrund anstoßen (Kartei + Slot-Vorrat), dann die nächste Frage
stellen ODER das Angebot machen. Liefert None, wenn der Satz nichts mit der
Buchung zu tun hat — dann übernimmt das LLM (mit status_zeile im Prompt).
"""

from __future__ import annotations

import re
from typing import Any, Callable

from bianca import gehirn, hintergrund, telefon, verwalten, weiterleiten
from kern import calendar as kal
from kern import gehoer, gespraech
from kern.patients import arzt_sprechname
from kern.sitzung import merke_tool
from kern.slots import pick_slots, slot_wahl, spoken_offer, spoken_slot, zeit_von
from kern.tenants import motiv_von
from kern import zeiten

Melde = Callable[[str], None] | None

_ABLEHNUNG_RE = re.compile(r"passt nicht|passt mir nicht|keiner davon|nichts davon|geht nicht|geht bei mir nicht|anderer termin|was anderes", re.I)
# Dringlichkeit (kanonischer Grund aus gehirn._GRUND_MAP): Notfaelle bekommen
# die naechstmoeglichen Plaetze DICHT angeboten — Streuung gilt dort nicht.
_DRINGEND_RE = re.compile(r"akut|notfall|schmerz", re.I)
_KUERZEL_RE = re.compile(r"^[A-ZÄÖÜ]{2,4}\s+")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _zeit_von(t: str) -> tuple[int | None, int | None]:
    return zeit_von(t)


def _slot_wahl(text: str, offered: list[dict]) -> str:
    """Welchen der angebotenen Termine meint der Anrufer? '' wenn unklar."""
    iso = slot_wahl(text, offered)
    if iso:
        return iso
    if offered and len(offered) == 1 and (
        gehirn.ist_ja(text) or re.search(r"nehm|passt|gerne|gut\b", text, re.I)
    ):
        return offered[0]["iso"]
    return ""


def _kalender_strikt(tenant: dict, name: str) -> dict | None:
    """Kalender NUR über den Namen finden — ohne Default-Rückfall.

    kern.tenants.kalender_von fällt auf den Standard-Kalender zurück, wenn
    nichts passt. Beim Binden eines Angebots wäre genau das der Fehler vom
    27.08.2026 (fremder Slot im falschen Kalender) — lieber ehrlich None.
    """
    q = _s(name).lower()
    if not q:
        return None
    cals = tenant.get("calendars") if isinstance(tenant.get("calendars"), list) else []
    for c in cals:
        if _s(c.get("name")).lower() == q:
            return c
    tokens = [t for t in q.replace(".", " ").replace(",", " ").split()
              if t not in {"dr", "doktor", "med", "msc", "m.sc"}]
    best, score = None, 0
    for c in cals:
        n = _s(c.get("name")).lower()
        s = sum(1 for t in tokens if t and t in n)
        if s > score:
            best, score = c, s
    return best


def _ctx_bauen(sit: dict) -> dict:
    """Sammler-Stand in den Buchungskontext spiegeln (den kern.calendar kennt)."""
    s = gehirn.sammler(sit)
    ctx = sit.setdefault("booking", {})
    a = s["arzt"] or {}
    bind = sit.get("angebotKalender") or {}
    if _s(bind.get("calendarId")) or _s(bind.get("calendarName")):
        # Es liegt ein Angebot auf dem Tisch: gebucht wird IMMER in dem
        # Kalender, aus dem die angebotenen Zeiten kamen — auch wenn die
        # Kartei-Recherche den Sammler inzwischen umgestellt hat.
        if _s(bind.get("calendarId")):
            ctx["calendarId"] = bind["calendarId"]
        else:
            ctx.pop("calendarId", None)
        ctx["calendarName"] = _s(bind.get("calendarName"))
    elif a.get("calendarId"):
        ctx["calendarId"] = a["calendarId"]
        ctx["calendarName"] = a.get("calendarName") or ""
    elif _s(sit.get("angebotArzt")):
        # "Egal"-Fall: die Cloud Function hat den schnellsten Arzt gewählt —
        # zum Buchen lösen wir dessen Kalender über den Namen auf.
        ctx.pop("calendarId", None)
        ctx["calendarName"] = sit["angebotArzt"]
    if s["motivId"]:
        ctx["visitMotiveId"] = s["motivId"]
        ctx["visitMotiveName"] = s["motivName"]
    elif s["grund"] and not _s(ctx.get("visitMotiveName")):
        ctx["visitMotiveName"] = "Kontrolluntersuchung"
    if s["patientId"]:
        ctx["patientId"] = s["patientId"]
    if s["vorname"]:
        ctx["firstName"] = s["vorname"]
    if s["nachname"]:
        ctx["lastName"] = s["nachname"]
    name = f"{s['vorname']} {s['nachname']}".strip()
    if name:
        ctx["patientName"] = name
    tel = s["telefon"] or s["aktePhone"]
    if tel:
        ctx["phone"] = tel
    if sit.get("slotVorrat"):
        ctx["slotVorrat"] = list(sit["slotVorrat"])
    return ctx


def _grund_sprechbar(s: dict) -> str:
    roh = s["motivName"] or s["grund"] or "Ihr Termin"
    return _KUERZEL_RE.sub("", roh)


def _quittung(s: dict, neu: set[str], sit: dict | None = None) -> str:
    if "kartei" in neu and s.get("bekannt"):
        wen = gehirn.anrede(s, (sit or {}).get("patient"))
        kopf = f"Willkommen zurück, {wen}. " if wen else "Willkommen zurück — ich habe Sie in der Kartei. "
        mem = (sit or {}).get("letzterAnruf") or {}
        satz = _s(mem.get("satz"))
        if satz and sit is not None and not sit.get("gedaechtnisGesagt"):
            sit["gedaechtnisGesagt"] = True
            if not s.get("grund"):
                sit["gedaechtnisOffen"] = True
                return kopf + f"{satz}, richtig? "
            return kopf + f"{satz}. "
        return kopf
    if "nachname" in neu and s["buchstabiert"]:
        return f"Danke — {s['nachname']}, notiert. "
    if "name" in neu:
        # Namentlich nur Herr/Frau + Nachname. Nie Vorname zuerst
        # ("Danke, Peter Okay" / "Herr Peter" — live 28.08.2026).
        wen = gehirn.anrede(s, (sit or {}).get("patient"))
        if wen:
            return f"Danke, {wen}. "
        return "Danke. "
    if "telefon" in neu:
        if s.get("bekannt"):
            wen = gehirn.anrede(s, (sit or {}).get("patient"))
            return f"Willkommen zurück, {wen}. " if wen else "Prima, die Nummer habe ich. "
        return "Prima, die Nummer habe ich. "
    if "telefonAkte" in neu:
        return "Alles klar — dann nehmen wir die Nummer aus Ihrer Akte. "
    if "grund" in neu:
        return "Alles klar. "
    if "wunsch" in neu:
        return "Gut. "
    return ""


def _readback(sit: dict) -> dict:
    s = gehirn.sammler(sit)
    a = s["arzt"] or {}
    bind = sit.get("angebotKalender") or {}
    # Gesprochen wird NUR Titel + Nachname ("Doktor Petsas") — englische
    # Vornamen (Michael) liest die Sprachausgabe sonst englisch vor.
    beim = arzt_sprechname(bind.get("calendarName") or a.get("calendarName") or sit.get("angebotArzt") or "")
    wer = f"{s['vorname']} {s['nachname']}".strip()
    s["phase"] = "bestaetigen"
    s["frage"] = "bestaetigung"
    teile = [_grund_sprechbar(s), spoken_slot(s["slotIso"])]
    if beim:
        teile.append(f"bei {beim}")
    if wer:
        teile.append(f"für {wer}")
    return {"text": f"Dann halte ich fest: {', '.join(teile)}. Soll ich das so eintragen?"}


def _angebot(sit: dict, melde: Melde = None) -> dict:
    s = gehirn.sammler(sit)

    # "Weiß nicht, bei wem ich war": erst die Behandler-Recherche abwarten
    # (Füller überbrückt), NICHT sofort global suchen — Chef-Vorgabe.
    a = s["arzt"] or {}
    if a.get("typ") == "unbekannt" and not a.get("calendarId") and hintergrund.kartei_laeuft(sit):
        if melde:
            melde("offer_slots")
        hintergrund.kartei_abwarten(sit, max_s=3.0)
        a = s["arzt"] or {}

    sit.pop("angebotKalender", None)  # neues Angebot => neue Bindung
    ctx = _ctx_bauen(sit)
    vorrat = list(sit.get("slotVorrat") or [])
    wish, zu_vor = zeiten.wunsch_richten(s["wunsch"], sit.get("tenant"))
    if wish:
        s["wunsch"] = wish
    egal = not a.get("calendarId")
    if a.get("calendarId") and (wish or {}).get("date"):
        ab = kal.arzt_abwesen(
            sit["tenant"],
            calendar_id=_s(a.get("calendarId")),
            start=_s(wish.get("date")),
        )
        treffer = next((d for d in (ab.get("doctors") or []) if d.get("isAbsent")), None)
        if treffer:
            bis = _s(treffer.get("absentUntil"))
            name = arzt_sprechname(a.get("calendarName") or treffer.get("doctorName") or "")
            zu_vor = (
                (zu_vor + " " if zu_vor else "")
                + (f"{name} ist bis einschließlich {bis} nicht da. " if bis
                   else f"{name} ist an dem Tag nicht da. ")
                + "Ich schaue, wo sonst etwas frei ist."
            ).strip()
            egal = True
            sit.pop("angebotArzt", None)

    def _laden() -> dict:
        if melde:
            melde("offer_slots")
        if egal:
            found = kal.finde_schnellsten(
                sit["tenant"], ctx,
                start_date=gehirn.start_datum(s),
                wish=wish,
                source="pickadoc-bianca",
            )
        else:
            found = kal.find_slots(
                sit["tenant"], ctx,
                start_date=gehirn.start_datum(s),
                egal=False,
                source="pickadoc-bianca",
            )
        if found.get("ok"):
            frisch = kal._iso_liste(found.get("slots") or [])
            if frisch:
                sit["slotVorrat"] = frisch
                ctx["slotVorrat"] = list(frisch)
            if egal and _s(found.get("doctorName")):
                sit["angebotArzt"] = _s(found.get("doctorName")).split(",")[0].strip()
        return found

    nachladen = not vorrat
    if wish and wish.get("date") and vorrat and not any(str(v).startswith(str(wish["date"])) for v in vorrat):
        nachladen = True
    if nachladen:
        found = _laden()
        vorrat = list(sit.get("slotVorrat") or [])
        if not found.get("ok") and not vorrat:
            s["phase"] = ""
            return {"text": (
                "Der Terminkalender antwortet gerade nicht. "
                "Die Praxis ruft Sie kurzfristig zurück — Ihre Nummer habe ich ja."
            )}

    dringend = bool(_DRINGEND_RE.search(f"{s['grund']} {s['motivName']}"))
    picked = pick_slots(vorrat, wish=wish, dringend=dringend, tenant=sit.get("tenant"))
    if wish and not picked["wishMatched"] and not nachladen:
        # Der Vorrat passt nicht zum Wunsch (z. B. "nächste Woche"): einmal
        # gezielt ab Wunschdatum nachladen, bevor wir Ausweichzeiten anbieten.
        _laden()
        vorrat = list(sit.get("slotVorrat") or [])
        picked = pick_slots(vorrat, wish=wish, dringend=dringend, tenant=sit.get("tenant"))

    # Merken, aus WELCHEM Kalender dieses Angebot kommt: die Buchung bindet
    # sich daran, nicht an spätere Sammler-Umbauten (Vorfall 27.08.2026:
    # Patrikis-Slot wurde in Petsas' Kalender gebucht -> "Termin gerade weg").
    if egal:
        name = _s(sit.get("angebotArzt"))
        cal = _kalender_strikt(sit["tenant"], name)
        sit["angebotKalender"] = {
            "calendarId": _s((cal or {}).get("id")),
            "calendarName": name or _s((cal or {}).get("name")),
        }
    else:
        sit["angebotKalender"] = {
            "calendarId": _s(a.get("calendarId")),
            "calendarName": _s(a.get("calendarName")),
        }
    offered = [{"iso": x["iso"], "spoken": spoken_slot(x["iso"])} for x in picked["slots"]]
    zuletzt = sit.pop("angebotZuletzt", None)
    sit["offered"] = offered
    s["phase"] = "angebot"
    s["frage"] = "slotwahl"
    vor = ""
    hinweis = _s(sit.get("arztHinweis"))
    if hinweis and not sit.get("arztHinweisGesagt"):
        sit["arztHinweisGesagt"] = True
        vor = hinweis + " "
    elif egal and _s(sit.get("angebotArzt")) and not sit.get("angebotArztGesagt"):
        sit["angebotArztGesagt"] = True
        vor = f"Am schnellsten geht es bei {arzt_sprechname(sit['angebotArzt'])}. "
    if offered and zuletzt == [o["iso"] for o in offered]:
        # Wiederhol-Wache: derselbe Wunsch fuehrt zum SELBEN Ergebnis — das
        # ehrlich sagen statt das Angebot wortgleich herunterzubeten
        # (live 27.08.2026: identische Slot-Liste zweimal hintereinander).
        liste = "; oder ".join(o["spoken"] for o in offered)
        return {"text": vor + f"Näher an Ihrem Wunsch habe ich leider nichts — es bleibt bei {liste}. Passt davon einer?"}
    if zu_vor:
        vor = (zu_vor + " " + vor).strip() + " "
    return {"text": vor + spoken_offer(picked["slots"], wish_matched=picked["wishMatched"])}


def _buchen(sit: dict, melde: Melde = None) -> dict:
    s = gehirn.sammler(sit)
    if melde:
        melde("book_slot")
    ctx = _ctx_bauen(sit)
    res = kal.book_slot(sit["tenant"], ctx, slot_iso=s["slotIso"])
    merke_tool(sit, "book_slot", res)
    book = {
        "booked": bool(res.get("booked")),
        "dryRun": bool(res.get("dryRun")),
        "slotIso": res.get("slotIso") or "",
        "spoken": res.get("spoken") or "",
    }
    if res.get("ok") and (res.get("booked") or res.get("dryRun")):
        s["phase"] = "gebucht"
        s["frage"] = ""
        text = res.get("spoken") or "Der Termin ist eingetragen."
        if res.get("booked"):
            zusatz = _s((sit.get("tenant") or {}).get("abschluss"))
            if zusatz:
                text += " " + zusatz
            elif s["telefon"] or s["aktePhone"]:
                text += " Die Bestätigung kommt gleich per SMS."
            text += " Kann ich sonst noch etwas für Sie tun?"
        return {"text": text, "book": book}
    if res.get("slotTaken"):
        sit["offered"] = res.get("slots") or []
        s["phase"] = "angebot"
        s["frage"] = "slotwahl"
        s["slotIso"] = ""
        return {"text": res.get("spoken") or "Der Termin ist gerade weg — ich schaue nach Alternativen.", "book": book}
    s["phase"] = ""
    gesagt = _s(res.get("spoken"))
    if "nummer" in gesagt.lower() or "handy" in gesagt.lower():
        s["frage"] = "telefon"
        s["telefonOk"] = False
    return {"text": gesagt or "Das hat gerade nicht geklappt. Die Praxis ruft Sie dazu zurück.", "book": book}


def _eskalieren(sit: dict, fid: str) -> str:
    """Zweimal keine verwertbare Antwort auf dieselbe Pflichtfrage: Standard
    setzen und weitergehen statt im Kreis zu fragen (Chef 27.08.2026:
    'bianca hängt in Schleifen fest')."""
    s = gehirn.sammler(sit)
    if fid == "schonmal":
        s["warSchonMal"] = False
        return "Kein Problem — dann nehme ich Sie einfach neu auf. "
    if fid == "arzt":
        s["arzt"] = {"typ": "egal"}
        return "Machen wir es einfach: Ich schaue, wo es am schnellsten geht. "
    if fid == "grund":
        s["grund"] = "Kontrolluntersuchung"
        vm = motiv_von(sit.get("tenant") or {}, "Kontrolluntersuchung")
        if vm:
            s["motivId"] = _s(vm.get("id"))
            s["motivName"] = _s(vm.get("name"))
        return "Ich trage es erst einmal als Kontrolle ein — die Praxis passt das bei Bedarf an. "
    if fid == "wunsch":
        s["wunsch"] = {}
        return "Dann schaue ich einfach nach den nächsten freien Terminen. "
    if fid == "buchstabieren":
        s["buchstabiert"] = True
        return ""
    if fid == "telefon_check" and s["telefonOffen"]:
        # Zweimal keine klare Antwort auf die Rückbestätigung, aber auch kein
        # Nein: die vorgelesene Nummer gilt — nicht zum dritten Mal fragen
        # (Chef 27.08.2026: Nummer wurde mehrfach abgefragt und bestätigt).
        s["telefon"] = s["telefonOffen"]
        s["telefonOk"] = True
        s["telefonOffen"] = ""
        s["telefonTeil"] = ""
        return "Dann nehme ich die Nummer so auf. "
    if fid in {"telefon", "telefon_check"}:
        s["telefonAkte"] = True
        s["telefonOffen"] = ""
        s["telefonTeil"] = ""
        return "Die Nummer gleichen wir später in Ruhe ab. "
    return "Entschuldigung, das habe ich nicht mitbekommen. "


def zug(sit: dict, gesagt: str, melde: Melde = None) -> dict | None:
    """Ein Anrufer-Satz durch den Buchungsfluss. None => LLM übernimmt."""
    s = gehirn.sammler(sit)
    t = _s(gesagt)
    if not t:
        return None

    if gehoer.wacklig(t, frage=_s(s.get("frage"))):
        n = int(sit.get("wackligZaehler") or 0) + 1
        sit["wackligZaehler"] = n
        if n <= 1:
            return {"text": gehoer.rueckfrage(sit)}
    else:
        sit["wackligZaehler"] = 0

    # Weiterleitungs-Wunsch ("Ich möchte einen Menschen sprechen"): eigener
    # deterministischer Zweig VOR allem anderen — Platzhalter fuer Kirris
    # Zaluma-/SIP-Weiterleitung (bianca/weiterleiten.py).
    wl = weiterleiten.zug(sit, t, melde)
    if wl is not None:
        return wl

    if s["phase"] == "gebucht":
        # Frisch gebucht — aber "sagen Sie ihn doch wieder ab" / "wann war
        # das nochmal?" gehoert in die Termin-Verwaltung, nicht ans LLM.
        neu = gehirn.einsammeln(sit, t)
        sit["ernteZuletzt"] = sorted(neu)  # Task-Signal fuer die Talk-Schicht
        if s["modus"] in {"absagen", "verschieben", "auskunft"}:
            sit["gefundenKey"] = ""  # Bestand frisch laden, der neue Termin zaehlt mit
            return verwalten.zug(sit, t, neu, melde)
        return None

    if s["phase"] == "bestaetigen":
        if gehirn.ist_ja(t):
            sit.pop("bestaetigenUnklar", None)
            return _buchen(sit, melde)
        if gehirn.ist_nein(t):
            sit.pop("bestaetigenUnklar", None)
            s["phase"] = ""
            s["slotIso"] = ""
            return {"text": "Kein Problem. Was darf ich ändern — der Zeitpunkt, der Name oder die Nummer?"}

    if s["phase"] in {"angebot", "bestaetigen"} and sit.get("offered"):
        iso = _slot_wahl(t, sit["offered"])
        if iso:
            s["slotIso"] = iso
            return _readback(sit)

    neu = gehirn.einsammeln(sit, t)
    # Rückkehrer: Nummer gegen die Kartei — ein Treffer füllt Name + Gedächtnis
    # noch in DIESEM Zug, damit die nächste Frage nicht erneut nach dem Namen fragt.
    if s["warSchonMal"] and not s.get("patientId"):
        if sit.get("anruferNummer") and "warSchonMal" in neu and not s.get("telefon"):
            s["telefon"] = sit["anruferNummer"]
            s["telefonOk"] = True
            s["telefonAkte"] = True
            neu.add("telefon")
        if (s.get("telefonOk") or sit.get("anruferNummer")) and hintergrund.karte_aus_handy(sit):
            neu.add("kartei")
        elif {"name", "nachname"} & neu and hintergrund.karte_aus_name(sit):
            neu.add("kartei")
    if sit.get("gedaechtnisOffen") and gehirn.ist_ja(t):
        mem = sit.get("letzterAnruf") or {}
        if _s(mem.get("grund")) and not s.get("grund"):
            s["grund"] = _s(mem.get("grund"))
            vm = motiv_von(sit.get("tenant") or {}, s["grund"])
            if vm:
                s["motivId"] = _s(vm.get("id"))
                s["motivName"] = _s(vm.get("name"))
            neu.add("grund")
        sit["gedaechtnisOffen"] = False
    elif sit.get("gedaechtnisOffen") and (gehirn.ist_nein(t) or "grund" in neu):
        sit["gedaechtnisOffen"] = False
    sit["ernteZuletzt"] = sorted(neu)  # Task-Signal fuer die Talk-Schicht

    # Bestandstermin-Anliegen (absagen/verschieben/ansagen) haben ihren
    # eigenen deterministischen Fluss.
    if s["modus"] in {"absagen", "verschieben", "auskunft"}:
        return verwalten.zug(sit, t, neu, melde)

    if s["modus"] != "buchen" and "modus" not in neu:
        return None

    if s["phase"] in {"angebot", "bestaetigen"}:
        if {"wunsch", "arzt", "grund"} & neu:
            # Anrufer will etwas anderes (Zeit/Arzt/Grund geändert): neu anbieten.
            # Das alte Angebot merken — kommt dasselbe wieder heraus, sagt die
            # Wiederhol-Wache in _angebot das ehrlich an.
            sit["angebotZuletzt"] = [o["iso"] for o in sit.get("offered") or []]
            s["phase"] = ""
            s["slotIso"] = ""
            sit["offered"] = []
            sit.pop("angebotKalender", None)
            if {"arzt", "grund"} & neu:
                # Anderer Kalender-Rahmen: alter Slot-Vorrat ist wertlos.
                sit["slotVorrat"] = []
                sit["vorratKey"] = ""
        elif gehirn.ist_nein(t) or _ABLEHNUNG_RE.search(t):
            s["phase"] = ""
            s["slotIso"] = ""
            sit["offered"] = []
            sit.pop("angebotKalender", None)
            s["frage"] = "wunsch"
            return {"text": "Wann würde es Ihnen denn besser passen — eher vormittags oder nachmittags?"}
        elif (s["phase"] == "bestaetigen" and not gehirn.ist_zwischenfrage(t)
              and not gespraech.traegt_thema(sit, t)):
            # Unklare Antwort auf "Soll ich das so eintragen?" bleibt
            # DETERMINISTISCH: das LLM erfand hier sonst Erledigt-Meldungen,
            # und der Frage-Anker stellte die Frage danach ERNEUT — genau die
            # Doppelfrage vom 27.08.2026. Beim zweiten unklaren, nicht
            # verneinenden Anlauf gilt der Termin als gewollt (der Anrufer
            # hat zweimal nicht widersprochen; die SMS bestätigt ihn eh).
            z = int(sit.get("bestaetigenUnklar") or 0) + 1
            sit["bestaetigenUnklar"] = z
            if z <= 1:
                return {"text": "Entschuldigung, das habe ich akustisch nicht verstanden — soll ich den Termin so eintragen? Ein kurzes Ja genügt."}
            sit.pop("bestaetigenUnklar", None)
            return _buchen(sit, melde)
        else:
            return None  # Zwischenfrage — LLM antwortet, Status hält die Spur

    if "telefonKorrektur" in neu:
        s["frage"] = "telefon"
        return {"text": "Entschuldigung! Dann bitte noch einmal — ganz in Ruhe, Ziffer für Ziffer."}

    hintergrund.anstossen(sit)

    fid, frage = gehirn.naechste_frage(sit)
    if fid:
        if gehirn.ist_zwischenfrage(t) or (
            not neu and fid != "telefon_check" and gespraech.traegt_thema(sit, t)
        ):
            # Echte Zwischenfrage/Abschweifung ("Was kostet das?") ODER ein
            # erzaehltes Nebenthema OHNE Ernte ("Meine Tochter heiratet!"):
            # das LLM antwortet natürlich (Talk-Schicht), zurueckgefuehrt
            # wird ueber Floor/Anker — zählt NIE als Leerlauf (Chef 27.08.:
            # "Abschweifungen müssen erlaubt sein"). Brachte der Satz Ernte,
            # macht die Maschine normal weiter; die Nummern-Rückbestätigung
            # (telefon_check) bleibt IMMER deterministisch.
            s["frage"] = fid
            return None
        if not neu and s["frage"] == fid:
            # Dieselbe Frage ist schon offen und der Satz brachte nichts Neues.
            zaehler = sit.setdefault("frageLeer", {})
            zaehler[fid] = int(zaehler.get(fid) or 0) + 1
            if zaehler[fid] <= 1:
                if fid == "telefon_check":
                    # Rückbestätigung bleibt deterministisch: das LLM erfand
                    # hier "die Nummer habe ich notiert" UND der Anker fragte
                    # danach erneut — die Doppelfrage vom 27.08.2026.
                    return {"text": "Entschuldigung, kurz zur Sicherheit: Stimmt die Nummer so? Ein kurzes Ja oder Nein genügt."}
                # Erster Leerlauf: das LLM antwortet kurz,
                # der Stand im Prompt führt zur offenen Frage zurück.
                return None
            # Zweiter Leerlauf: Standard setzen und WEITERGEHEN — nie wieder
            # dieselbe Frage im Kreis (Live-Schleife 27.08.2026).
            uebergang = _eskalieren(sit, fid)
            fid2, frage2 = gehirn.naechste_frage(sit)
            if not fid2:
                s["frage"] = ""
                ang = _angebot(sit, melde)
                if uebergang and ang and _s(ang.get("text")):
                    ang["text"] = uebergang + ang["text"]
                return ang
            s["frage"] = fid2
            if fid2 == fid:
                uebergang = uebergang or "Entschuldigung, das habe ich nicht mitbekommen. "
            return {"text": (uebergang + frage2).strip()}
        if s["frage"] != fid:
            (sit.get("frageLeer") or {}).pop(fid, None)
        s["frage"] = fid
        q = _quittung(s, neu, sit)
        if sit.get("gedaechtnisOffen") and "richtig?" in q:
            return {"text": q.strip()}
        return {"text": (q + frage).strip()}

    if not neu and s["frage"]:
        return None  # nichts Verwertbares gehört — LLM klärt, Status führt zurück

    s["frage"] = ""
    ang = _angebot(sit, melde)
    if ang and _s(ang.get("text")):
        q = _quittung(s, neu, sit)
        if q:
            ang["text"] = q + ang["text"]
    return ang


def status_zeile(sit: dict) -> str:
    """Kompakter Buchungsstand für den LLM-Prompt, wenn der Fluss abgibt."""
    s = sit.get("sammler") or {}
    if s.get("modus") in {"absagen", "verschieben", "auskunft"}:
        return verwalten.status_zeile(sit)
    if not s or s.get("modus") != "buchen":
        return ""
    a = s.get("arzt") or {}
    teile = [
        f"Name={_s(s.get('vorname'))} {_s(s.get('nachname'))}".strip(),
        f"Kartei={'bekannt ' + _s(s.get('patientId')) if s.get('bekannt') else 'neu'}",
        f"Grund={_s(s.get('grund')) or '?'}",
        f"Arzt={_s(a.get('calendarName')) or a.get('typ') or '?'}",
        f"Telefon={_s(s.get('telefon')) or '?'}",
        f"Phase={_s(s.get('phase')) or 'sammeln'}",
    ]
    offen = ""
    if s.get("frage"):
        offen = f" Offene Frage: {s['frage']}."
    slots = "; ".join(_s(x.get("spoken")) for x in (sit.get("offered") or [])[:3])
    if slots:
        offen += f" Angeboten: {slots}."
    return (
        "Laufende Terminbuchung (führe den Anrufer immer dorthin zurück): "
        + ", ".join(teile) + "." + offen
    )
