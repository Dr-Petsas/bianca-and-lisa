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
from kern import gespraech
from kern.patients import arzt_sprechname, telefon_aktualisieren, versicherung_aktualisieren
from kern.sitzung import merke_tool
from kern.slots import WEEKDAYS, _weekday_of, pick_slots, spoken_offer, spoken_slot
from kern.tenants import motiv_von

Melde = Callable[[str], None] | None

# "Welche Nummer? / Sagen Sie das nochmal": bei offener Akten-Nummer-Frage
# wird die Nummer deterministisch ERNEUT vorgelesen (Chef 29.08.2026: "die KI
# muss das mehrmals vorlesen können") — nie ans LLM, das kennt die Ziffern nicht.
_NOCHMAL_RE = re.compile(
    r"noch\s*ein?mal|nochmal|wiederhol|wie\s+bitte|welche\s+nummer|"
    r"nicht\s+verstanden|versteh|langsam(er)?\b|wie\s+war\s+die",
    re.I,
)

_H_WORT = {
    "ein": 1, "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
    "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11,
    "zwölf": 12, "zwoelf": 12, "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15,
    "fuenfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18, "neunzehn": 19,
    "zwanzig": 20,
}
_M_WORT = {
    "fünf": 5, "fuenf": 5, "zehn": 10, "fünfzehn": 15, "fuenfzehn": 15,
    "zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40,
    "fünfundvierzig": 45, "fuenfundvierzig": 45, "fünfzig": 50, "fuenfzig": 50,
}
_M_ZEHNER = {
    "zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40,
    "fünfzig": 50, "fuenfzig": 50,
}


def _minuten_von(wort: str) -> int | None:
    """Minutenwort 1-59 — auch zusammengesetzt ('vierundvierzig').

    Live 27.08.2026: 'neun Uhr vierundvierzig' fiel durch, weil _M_WORT nur
    runde Werte kennt — die Slot-Wahl scheiterte und das Angebot kam wortgleich
    ein zweites Mal.
    """
    w = _s(wort).lower()
    if not w:
        return None
    if w in _M_WORT:
        return _M_WORT[w]
    if w in _H_WORT and _H_WORT[w] <= 20:
        return _H_WORT[w]
    m = re.match(r"^([a-zäöüß]+)und([a-zäöüß]+)$", w)
    if m and m.group(1) in _H_WORT and _H_WORT[m.group(1)] <= 9 and m.group(2) in _M_ZEHNER:
        return _M_ZEHNER[m.group(2)] + _H_WORT[m.group(1)]
    return None
_ABLEHNUNG_RE = re.compile(r"passt nicht|passt mir nicht|keiner davon|nichts davon|geht nicht|geht bei mir nicht|anderer termin|was anderes", re.I)
# Dringlichkeit (kanonischer Grund aus gehirn._GRUND_MAP): Notfaelle bekommen
# die naechstmoeglichen Plaetze DICHT angeboten — Streuung gilt dort nicht.
_DRINGEND_RE = re.compile(r"akut|notfall|schmerz", re.I)
# Chef 03.09.2026: mit der Bestaetigungs-SMS geht ein Link raus, ueber den
# der Anrufer die Unterlagen fuer den Termin ausfuellt (Anamnese,
# Datenschutz, Aufklaerung) — Bianca sagt das bei der Buchung dazu.
_SMS_LINK_SATZ = (
    " In der SMS ist auch ein Link — darüber füllen Sie bitte vorab kurz die"
    " Unterlagen für Ihren Termin aus, zum Beispiel Anamnese und Datenschutz."
)
_KUERZEL_RE = re.compile(r"^[A-ZÄÖÜ]{2,4}\s+")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _zeit_von(t: str) -> tuple[int | None, int | None]:
    """Gehörte Uhrzeit: '9 uhr 15', 'um 14:30', 'neun uhr fünfzehn', 'halb zehn'."""
    m = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*uhr\b(?:\s+(\d{1,2})\b)?", t)
    if not m:
        m = re.search(r"\bum\s+(\d{1,2})(?:[:.](\d{2}))?\b", t)
    if m:
        minute = m.group(2) or (m.group(3) if m.lastindex and m.lastindex >= 3 else None)
        return int(m.group(1)), (int(minute) if minute else None)
    m = re.search(r"\bhalb\s+([a-zäöü]+|\d{1,2})\b", t)
    if m:
        w = m.group(1)
        h = int(w) if w.isdigit() else _H_WORT.get(w)
        if h:
            return h - 1, 30
    m = re.search(r"\b([a-zäöü]+)\s+uhr(?:\s+([a-zäöüß]+))?\b", t)
    if m and m.group(1) in _H_WORT:
        return _H_WORT[m.group(1)], _minuten_von(m.group(2) or "")
    m = re.search(r"\bum\s+([a-zäöüß]+)\b", t)
    if m and m.group(1) in _H_WORT:
        # 'Montag um zehn' OHNE das Wort 'Uhr' (live 28.08.2026): die Wahl
        # fiel durch, der Satz wurde als NEUER Wunsch geerntet und das
        # Angebot lief wortgleich in den Wiederholungs-Waechter ('Gut.').
        return _H_WORT[m.group(1)], None
    return None, None


def _slot_wahl(text: str, offered: list[dict]) -> str:
    """Welchen der angebotenen Termine meint der Anrufer? '' wenn unklar."""
    if not offered:
        return ""
    t = f" {_s(text).lower()} "

    wd = next((idx for idx, cre in WEEKDAYS if cre.search(t)), None)
    hour, minute = _zeit_von(t)
    if hour is not None:
        c = [o for o in offered
             if int(o["iso"][11:13]) == hour and (minute is None or int(o["iso"][14:16]) == minute)]
        if not c:
            c = [o for o in offered
                 if int(o["iso"][11:13]) % 12 == hour % 12 and (minute is None or int(o["iso"][14:16]) == minute)]
        if len(c) > 1 and wd is not None:
            # 'Montag um zehn' bei zwei Zehn-Uhr-Slots: Wochentag grenzt ein.
            cw = [o for o in c if _weekday_of(o["iso"][:10]) == wd]
            if cw:
                c = cw
        if len(c) == 1:
            return c[0]["iso"]
        if minute is not None and not c:
            # Konkrete Zielzeit ohne exakten Treffer: auf den NÄCHSTLIEGENDEN
            # angebotenen Slot runden ('neun Uhr vierundvierzig' -> 09:45).
            # Live 27.08.2026 wiederholte Bianca sonst wortgleich das Angebot.
            ziel = hour * 60 + minute

            def _abstand(o: dict) -> int:
                slot = int(o["iso"][11:13]) * 60 + int(o["iso"][14:16])
                slot12 = (int(o["iso"][11:13]) % 12) * 60 + int(o["iso"][14:16])
                return min(abs(slot - ziel), abs(slot12 - (hour % 12) * 60 - minute))

            nah = sorted(offered, key=_abstand)
            if _abstand(nah[0]) <= 20 and (len(nah) == 1 or _abstand(nah[1]) > _abstand(nah[0])):
                return nah[0]["iso"]

    if wd is not None:
        c = [o for o in offered if _weekday_of(o["iso"][:10]) == wd]
        if len(c) > 1 and hour is not None:
            # Zwei Slots am selben Tag: die gehoerte Stunde entscheidet.
            ch = [o for o in c
                  if int(o["iso"][11:13]) % 12 == hour % 12
                  and (minute is None or int(o["iso"][14:16]) == minute)]
            if ch:
                c = ch
        if len(c) == 1:
            return c[0]["iso"]

    dm = re.search(r"\b(\d{1,2})\.\s?(\d{1,2})\.", t)
    if dm:
        jahr = offered[0]["iso"][:4]
        datum = f"{jahr}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}"
        c = [o for o in offered if o["iso"].startswith(datum)]
        if len(c) == 1:
            return c[0]["iso"]

    rel = gehirn._relatives_datum(t)
    if rel:
        c = [o for o in offered if o["iso"].startswith(rel)]
        if len(c) == 1:
            return c[0]["iso"]

    if "vormittag" in t or "nachmittag" in t:
        früh = "vormittag" in t
        c = [o for o in offered
             if (int(o["iso"][11:13]) < 12) == früh]
        if len(c) == 1:
            return c[0]["iso"]

    if re.search(r"\b(erste[rns]?|ersteren)\b", t):
        return offered[0]["iso"]
    if re.search(r"\b(zweite[rns]?)\b", t) and len(offered) > 1:
        return offered[1]["iso"]
    if re.search(r"\b(dritte[rns]?)\b", t) and len(offered) > 2:
        return offered[2]["iso"]
    if re.search(r"\b(letzte[rns]?)\b", t):
        return offered[-1]["iso"]

    if len(offered) == 1 and (gehirn.ist_ja(t) or re.search(r"nehm|passt|gerne|gut\b", t)):
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
    # Besuchsgrund BEHANDLERSPEZIFISCH aufloesen — bei JEDEM Kontext-Bau neu
    # (Chef 30.08.2026): Motive sind kalendergebunden (calendarIds); wechselt
    # der Behandler im Gespraech, muss das Motiv gegen DESSEN Katalog neu
    # gesucht werden. Ohne frischen Katalog bleibt der bisherige Stand.
    if s["motivId"] or s["grund"]:
        ziel_id = _s(ctx.get("calendarId"))
        if not ziel_id and _s(ctx.get("calendarName")):
            ziel_id = _s((_kalender_strikt(sit.get("tenant") or {}, ctx["calendarName"]) or {}).get("id"))
        vm = gehirn.motiv_fuer_kalender(sit, ziel_id)
        if vm and _s(vm.get("id")) != s["motivId"]:
            print(f"bianca-motiv: {s['motivName'] or s['motivId'] or '?'} -> "
                  f"{vm.get('name')} (Kalender {ziel_id or 'alle'})", flush=True)
        if vm:
            s["motivId"] = _s(vm.get("id"))
            s["motivName"] = _s(vm.get("name"))
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
    # Fuer eine NEUE Akte (book_slot -> akte_anlegen): Geschlecht aus dem
    # Vornamen-Waechter und der erfragte Versichertenstatus (29.08.2026).
    if s["geschlecht"]:
        ctx["gender"] = s["geschlecht"]
    if s["versicherung"]:
        ctx["privateInsurance"] = s["versicherung"] == "privat"
    if sit.get("slotVorrat"):
        ctx["slotVorrat"] = list(sit["slotVorrat"])
    if sit.get("slotGesperrt"):
        ctx["slotGesperrt"] = list(sit["slotGesperrt"])
    return ctx


def _grund_sprechbar(s: dict) -> str:
    roh = s["motivName"] or s["grund"] or "Ihr Termin"
    return _KUERZEL_RE.sub("", roh)


def _quittung(s: dict, neu: set[str]) -> str:
    if "nachname" in neu and s["buchstabiert"]:
        return f"Danke — {s['nachname']}, notiert. "
    if "name" in neu:
        # Mit dem VOLLEN Namen quittieren — nie mit einem halben ("Danke,
        # Paul" klingt nach Anrede und war live 27.08.2026 auch noch falsch
        # zugeordnet). Fehlt ein Teil, fragt die nächste Frage ihn nach.
        if s["vorname"] and s["nachname"]:
            return f"Danke, {s['vorname']} {s['nachname']}. "
        return "Danke. "
    if "anruferCheck" in neu and s.get("anruferCheck") == "nein":
        # DB-Treffer verworfen (W-ANRUFER-CHECK): kurz entschuldigen, dann
        # kommt direkt die klassische Frage (schonmal/Name) hinterher.
        return "Entschuldigen Sie bitte — dann nehme ich Ihre Daten frisch auf. "
    if "telefon" in neu:
        return "Prima, die Nummer habe ich. "
    if "telefonAkte" in neu:
        return "Alles klar — dann nehmen wir die Nummer aus Ihrer Akte. "
    if "versicherung" in neu:
        art = "privat" if s.get("versicherung") == "privat" else "gesetzlich"
        return f"Alles klar — {art} versichert, notiert. "
    if "versicherungCheck" in neu:
        return "Prima, dann bleibt alles wie gehabt. "
    if "pzr" in neu:
        if s.get("pzr") == "ja":
            return "Sehr gerne — die Zahnreinigung nehme ich mit auf. "
        return "Alles klar, dann ohne Zahnreinigung. "
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
    # Geschlechts-Anrede (Chef 29.08.2026): "für Frau Müller" / "für Herrn
    # Müller" — ohne Geschlecht bleibt der volle Name.
    wer = gehirn.anrede(s, sit.get("patient"), beugen=True)
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
    # Gescheiterte Buchungs-ISOs nie wieder anbieten (W-BOOK-RETRY 01.09.2026).
    gesperrt = sit.get("slotGesperrt") or []
    if gesperrt:
        keys = {str(g)[:16] for g in gesperrt}
        vorrat = [v for v in vorrat if str(v)[:16] not in keys]
    wish = s["wunsch"]
    egal = not a.get("calendarId")

    def _laden() -> dict:
        if melde:
            melde("offer_slots")
        found = kal.find_slots(
            sit["tenant"], ctx,
            start_date=gehirn.start_datum(s),
            egal=egal,
            source="pickadoc-bianca",
        )
        if found.get("ok"):
            frisch = kal._iso_liste(found.get("slots") or [])
            if gesperrt:
                keys = {str(g)[:16] for g in gesperrt}
                frisch = [v for v in frisch if str(v)[:16] not in keys]
            if frisch:
                sit["slotVorrat"] = frisch
                ctx["slotVorrat"] = list(frisch)
                sit["vorratDispatch"] = (
                    found.get("dispatch")
                    if isinstance(found.get("dispatch"), dict) else None
                )
            if egal and _s(found.get("doctorName")):
                sit["angebotArzt"] = _s(found.get("doctorName")).split(",")[0].strip()
        merke_tool(sit, "getFreeTimeSlots", found)
        sit["vorratGemerkt"] = True
        return found

    nachladen = not vorrat
    if wish and wish.get("date") and vorrat and not any(str(v).startswith(str(wish["date"])) for v in vorrat):
        nachladen = True
    if nachladen:
        found = _laden()
        vorrat = list(sit.get("slotVorrat") or [])
        if gesperrt:
            keys = {str(g)[:16] for g in gesperrt}
            vorrat = [v for v in vorrat if str(v)[:16] not in keys]
        if not found.get("ok") and not vorrat:
            s["phase"] = ""
            return {"text": (
                "Der Terminkalender antwortet gerade nicht. "
                "Die Praxis ruft Sie kurzfristig zurück — Ihre Nummer habe ich ja."
            )}
    elif vorrat and not sit.get("vorratGemerkt"):
        # Hintergrund-Vorrat verbraucht: CF lief schon (bianca-vorrat), die
        # Tool-Karte fehlt sonst am Angebots-Zug (live 02.09. Tzannis).
        disp = sit.get("vorratDispatch") if isinstance(sit.get("vorratDispatch"), dict) else None
        merke_tool(sit, "getFreeTimeSlots", {
            "ok": True,
            "slots": list(vorrat),
            "dispatch": disp,
        })
        sit["vorratGemerkt"] = True

    dringend = bool(_DRINGEND_RE.search(f"{s['grund']} {s['motivName']}"))
    picked = pick_slots(vorrat, wish=wish, dringend=dringend, exclude_isos=gesperrt)
    if wish and not picked["wishMatched"] and not nachladen:
        # Der Vorrat passt nicht zum Wunsch (z. B. "nächste Woche"): einmal
        # gezielt ab Wunschdatum nachladen, bevor wir Ausweichzeiten anbieten.
        _laden()
        vorrat = list(sit.get("slotVorrat") or [])
        if gesperrt:
            keys = {str(g)[:16] for g in gesperrt}
            vorrat = [v for v in vorrat if str(v)[:16] not in keys]
        picked = pick_slots(vorrat, wish=wish, dringend=dringend, exclude_isos=gesperrt)

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
    if not offered:
        # KEIN Slot im Angebot: nie in die Slotwahl zwingen — dort haengt
        # sonst jede Folgeaeusserung ohne waehlbare Termine (Batch s09
        # 29.08.2026, LLM erfand "Welcher der genannten Termine?"). Das
        # Versprechen "die Praxis meldet sich" bekommt eine ECHTE Notiz.
        s["phase"] = "fertig"
        s["frage"] = ""
        verwalten.rueckruf_notiz(sit)
        return {"text": spoken_offer([], wish_matched=True)
                + " Kann ich sonst noch etwas für Sie tun?"}
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
        # Formulierung ROTIERT (live 28.08.2026): eine wortgleiche zweite
        # Ansage strich der Wiederholungs-Waechter komplett — der Anrufer
        # hoerte nur noch 'Gut.' und die Buchung hing in der Luft.
        liste = "; oder ".join(o["spoken"] for o in offered)
        z = int(sit.get("angebotFestgefahren") or 0)
        sit["angebotFestgefahren"] = z + 1
        txt = [
            f"Näher an Ihrem Wunsch habe ich leider nichts — es bleibt bei {liste}. Passt davon einer?",
            f"Ich habe wirklich nur diese Termine: {liste}. Sagen Sie gern einfach 'der erste' oder 'der zweite'.",
            f"Mehr ist dazu gerade nicht frei — noch einmal: {liste}. Welcher soll es sein?",
        ][z % 3]
        return {"text": vor + txt}
    sit.pop("angebotFestgefahren", None)
    return {"text": vor + spoken_offer(picked["slots"], wish_matched=picked["wishMatched"])}


def _telefon_alt_ausfuehren(sit: dict, melde: Melde = None) -> str:
    """Die Entscheidung zur Akten-Nummer umsetzen (Chef 29.08.2026).

    "neu"  => masUpdatePatientPhone schreibt die bestaetigte Nummer in die
              Akte (die Bestaetigungs-SMS der Plattform geht IMMER an die
              Akten-Nummer — erst nach dem Update kommt sie richtig an).
    "akte" => nichts schreiben, SMS geht an die Alt-Nummer.
    Erledigt-Ansage NUR nach echtem Erfolg; scheitert das Update, faellt die
    Entscheidung auf "notiz" zurueck und _buchen haengt die Praxis-Notiz an."""
    s = gehirn.sammler(sit)
    if s["telefonAlt"] == "akte":
        return "Alles klar — die Nummer bleibt in der Akte, und die Bestätigungs-SMS geht an diese Nummer. "
    if s["telefonAlt"] != "neu" or not (s["patientId"] and s["telefon"] and s["telefonOk"]):
        return ""  # in die Akte kommt NUR eine rueckbestaetigte Nummer
    if s["aktePhone"] and telefon.normaliert(s["aktePhone"]) == telefon.normaliert(s["telefon"]):
        return ""  # schon umgetragen (z. B. Sicherheitsnetz lief bereits)
    if melde:
        melde("update_phone")
    res = telefon_aktualisieren(sit["tenant"], s["patientId"], s["telefon"])
    merke_tool(sit, "update_phone", res)
    if res.get("ok"):
        s["aktePhone"] = s["telefon"]
        if res.get("dryRun"):
            return "Die neue Nummer hätte ich jetzt eingetragen — der Test schreibt die Kartei noch nicht. "
        return "Erledigt — die alte Nummer ist gelöscht, Ihre neue steht jetzt in der Akte. "
    s["telefonAlt"] = "notiz"
    print(f"bianca-telefon-alt: Update fehlgeschlagen — {res.get('error')}", flush=True)
    return "Das Umtragen klappt gerade technisch nicht — ich gebe Ihre neue Nummer der Praxis mit. "


def _versicherung_ausfuehren(sit: dict, melde: Melde = None) -> str:
    """Gemeldeten privat<->gesetzlich-Wechsel in die Kartei schreiben (29.08.2026).

    Nur bei BESTANDSAKTE mit erkanntem Wechsel — Neupatienten bekommen den
    Status direkt beim Anlegen (akte_anlegen ueber den Buchungskontext).
    Scheitert das Update, haengt _buchen eine Praxis-Notiz an den Termin."""
    s = gehirn.sammler(sit)
    if not (s["versicherungWechsel"] and s["patientId"] and s["versicherung"]):
        return ""
    if s["versicherungAkte"] == s["versicherung"]:
        return ""  # schon umgetragen (z. B. Sicherheitsnetz lief bereits)
    if melde:
        melde("update_insurance")
    res = versicherung_aktualisieren(sit["tenant"], s["patientId"], s["versicherung"] == "privat")
    merke_tool(sit, "update_insurance", res)
    if res.get("ok"):
        s["versicherungAkte"] = s["versicherung"]
        art = "privat" if s["versicherung"] == "privat" else "gesetzlich"
        if res.get("dryRun"):
            return "Den Versichertenstatus hätte ich jetzt umgetragen — der Test schreibt die Kartei noch nicht. "
        return f"Ich habe das in Ihrer Kartei aktualisiert — Sie sind jetzt als {art} versichert geführt. "
    s["versicherungNotiz"] = True
    print(f"bianca-versicherung: Update fehlgeschlagen — {res.get('error')}", flush=True)
    return "Das Umtragen klappt gerade technisch nicht — ich gebe es der Praxis mit. "


def _buchen(sit: dict, melde: Melde = None) -> dict:
    s = gehirn.sammler(sit)
    if (s["telefonAlt"] == "neu" and s["patientId"] and s["telefon"] and s["aktePhone"]
            and telefon.normaliert(s["telefon"]) != telefon.normaliert(s["aktePhone"])):
        # Sicherheitsnetz (Eskalations-/Renn-Fall): Entscheidung "neue Nummer"
        # steht, aber das Update lief noch nicht — JETZT nachholen, BEVOR die
        # Buchung die Bestaetigungs-SMS an die Akten-Nummer schickt.
        _telefon_alt_ausfuehren(sit, melde)
    if (s["versicherungWechsel"] and s["patientId"] and s["versicherung"]
            and s["versicherungAkte"] != s["versicherung"]):
        # Sicherheitsnetz: privat<->gesetzlich-Wechsel gemeldet, aber noch
        # nicht in der Kartei — vor der Buchung nachholen, damit der
        # Termin-Schnappschuss den richtigen Status traegt.
        _versicherung_ausfuehren(sit, melde)
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
        sit.pop("buchIntent", None)
        sit.pop("bookFails", None)
        text = res.get("spoken") or "Der Termin ist eingetragen."
        if res.get("booked"):
            neu = telefon.normaliert(s["telefon"]) if s["telefon"] else ""
            akte = telefon.normaliert(s["aktePhone"]) if s["aktePhone"] else ""
            if neu and akte and neu != akte:
                # Bestandsakte traegt eine ANDERE Nummer als die gerade
                # rueckbestaetigte — die Bestaetigungs-SMS der Plattform geht
                # an die AKTEN-Nummer (live 29.08.2026: Alt-Akte mit
                # 0123456789, die SMS lief ins Leere, der Anrufer wartete).
                # Regulaer ist der Konflikt hier schon GEKLAERT (telefon_alt-
                # Frage + masUpdatePatientPhone); dieser Zweig ist der Rest:
                # Entscheidung "SMS an die alte", ungeklaert oder Update kaputt.
                if s["telefonAlt"] == "akte":
                    text += (" Die Bestätigung kommt gleich per SMS an die Nummer aus"
                             " Ihrer Akte." + _SMS_LINK_SATZ)
                else:
                    if melde:
                        melde("note_appointment")
                    kal.note_appointment(
                        sit["tenant"], ctx, sit,
                        note=(
                            f"Anrufer nennt neue Handynummer: {s['telefon']} — "
                            f"Akte trägt {s['aktePhone']}. Bitte Akte aktualisieren."
                        ),
                    )
                    text += " Ihre neue Handynummer gebe ich der Praxis mit."
            elif s["telefon"] or s["aktePhone"]:
                text += " Die Bestätigung kommt gleich per SMS." + _SMS_LINK_SATZ
            # Praxis-Notizen ans Terminpopup (29.08.2026): unklares Geschlecht
            # (Default weiblich) und ein nicht geschriebener Versicherungs-
            # Wechsel gehoeren sichtbar in den Termin.
            hinweise = []
            if s["pzr"] == "ja":
                # Chef 30.08.2026, exakter Wortlaut fuers Notizfeld: die
                # Zahnreinigung wird nicht als zweiter Slot gebucht, sondern
                # der Praxis am Termin sichtbar gemacht.
                hinweise.append("PLUS PZR heute")
                text += " Die professionelle Zahnreinigung habe ich mit dazu vermerkt."
            if s["versicherungNotiz"]:
                if s["versicherung"]:
                    hinweise.append(
                        f"Versichertenstatus am Telefon: jetzt {s['versicherung']} — "
                        "Akte konnte nicht aktualisiert werden, bitte nachtragen."
                    )
                else:
                    hinweise.append(
                        "Versichertenstatus (privat/gesetzlich) am Telefon nicht geklärt — bitte nachfragen."
                    )
            if s["geschlechtUnklar"]:
                hinweise.append(
                    "Bitte Geschlecht aktualisieren — Vorname unklar, vorläufig weiblich eingetragen."
                )
            if hinweise:
                if melde:
                    melde("note_appointment")
                kal.note_appointment(sit["tenant"], ctx, sit, note=" ".join(hinweise))
            text += " Kann ich sonst noch etwas für Sie tun?"
        return {"text": text, "book": book}
    if res.get("slotTaken"):
        # W-BOOK-RETRY 01.09.2026: phone_agent-Deckel — max. 2 slotTaken,
        # gescheiterte ISOs sperren, Intent merken (kein zweites Confirm).
        fail_iso = _s(s.get("slotIso")) or _s(res.get("slotIso"))
        gesperrt = list(sit.get("slotGesperrt") or [])
        if fail_iso and fail_iso not in gesperrt:
            gesperrt.append(fail_iso)
        sit["slotGesperrt"] = gesperrt
        keys = {str(g)[:16] for g in gesperrt}
        sit["slotVorrat"] = [
            v for v in (sit.get("slotVorrat") or []) if str(v)[:16] not in keys
        ]
        fails = int(sit.get("bookFails") or 0) + 1
        sit["bookFails"] = fails
        sit["buchIntent"] = True  # Anrufer hat schon Ja gesagt
        s["slotIso"] = ""
        if fails >= 2:
            s["phase"] = "fertig"
            s["frage"] = ""
            sit["offered"] = []
            verwalten.rueckruf_notiz(sit)
            return {
                "text": (
                    "Der Termin ist leider gerade nicht mehr frei, und die Alternativen "
                    "klappen auch nicht zuverlässig. Keine Sorge — ich schreibe eine Notiz, "
                    "und die Praxis meldet sich gleich bei Ihnen mit einem Termin. "
                    "Kann ich sonst noch etwas für Sie tun?"
                ),
                "book": book,
            }
        # Frisches Angebot OHNE die gesperrten ISOs.
        ang = _angebot(sit, melde)
        txt = _s(ang.get("text"))
        if txt and not txt.lower().startswith("der termin ist gerade weg"):
            txt = "Der Termin ist gerade weg. " + txt
        return {"text": txt or (res.get("spoken") or "Der Termin ist gerade weg."), "book": book}
    s["phase"] = ""
    gesagt = _s(res.get("spoken"))
    if "nummer" in gesagt.lower() or "handy" in gesagt.lower():
        s["frage"] = "telefon"
        s["telefonOk"] = False
    return {"text": gesagt or "Das hat gerade nicht geklappt. Die Praxis ruft Sie dazu zurück.", "book": book}


def _einschub(sit: dict, vorsatz: str = "") -> dict | None:
    """Rueckblick-/PZR-Einschub, wenn einer faellig ist — sonst None.

    Chef 30.08.2026: Bestandspatienten werden auf den letzten Besuch
    angesprochen (Verlaufs-Frage als Plauder-Einstieg, das LLM uebernimmt
    das sich entwickelnde Gespraech), und bei laengerer Pause wird eine
    Zahnreinigung zum Mitbuchen angeboten — beides EINMAL pro Anruf,
    der Rueckblick zuerst. Die offene Pflichtfrage verschiebt sich nur um
    einen Zug; naechste_frage stellt sie danach von selbst wieder."""
    s = gehirn.sammler(sit)
    if gehirn.rueckblick_faellig(s):
        s["rueckblick"] = "gefragt"
        s["frage"] = "rueckblick"
        return {"text": (vorsatz + gehirn.rueckblick_text(s)).strip()}
    if gehirn.pzr_faellig(s):
        s["pzr"] = "gefragt"
        s["frage"] = "pzr"
        return {"text": (vorsatz + gehirn.pzr_frage(s)).strip()}
    return None


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
    if fid == "anrufer_check":
        # Zweimal keine klare Antwort auf das vorgelesene Name+Nummer-Paar:
        # NICHTS uebernehmen (Sicherheit vor Tempo — falsche Identitaet waere
        # fatal), klassisch nach Name und Nummer fragen (W-ANRUFER-CHECK).
        s["anruferCheck"] = "nein"
        return "Dann gehen wir auf Nummer sicher und nehmen Ihre Daten einfach frisch auf. "
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
    if fid == "telefon_alt":
        # Zweimal keine klare Wahl: die gerade Ziffer fuer Ziffer bestaetigte
        # Nummer gilt — dafuer hat der Anrufer sie genannt. Das Umtragen holt
        # _buchen als Sicherheitsnetz nach (vor der SMS).
        s["telefonAlt"] = "neu"
        return "Dann nehme ich einfach Ihre neue Nummer. "
    if fid == "versicherung":
        # Keine klare Antwort: nicht blockieren und nichts raten — die Praxis
        # bekommt eine Notiz an den Termin (versicherungNotiz in _buchen).
        s["versicherungOk"] = True
        s["versicherungNotiz"] = True
        return "Das klären wir dann in der Praxis — ich vermerke es. "
    if fid == "versicherung_check":
        # Keine klare Antwort auf die Rueckfrage: Kartei-Stand bleibt.
        s["versicherungOk"] = True
        s["versicherung"] = s["versicherungAkte"]
        return "Dann lasse ich es wie gehabt eingetragen. "
    return "Entschuldigung, das habe ich nicht mitbekommen. "


# LLM hat nach frischer Buchung selbst nach Storno gefragt ("Soll ich … stornieren?") —
# auf Ja muss cancel_appointment laufen, nicht eine erfundene Bestaetigung
# (live 02.09. Tzannis: "Der Termin ist storniert" ohne Tool).
_STORNO_FRAGE_RE = re.compile(
    r"soll\s+ich[^.!?]{0,80}?(?:stornier\w*|absag\w*)|"
    r"(?:stornier\w*|absag\w*)[^.!?]{0,40}?(?:für\s+sie|fuer\s+sie|\?)",
    re.I,
)


def _frisch_termin(sit: dict) -> dict:
    """Termin, der in DIESEM Anruf gerade gebucht wurde (appointmentId)."""
    aid = _s((sit.get("booking") or {}).get("appointmentId")) or _s(
        (sit.get("lastBook") or {}).get("appointmentId")
    )
    if not aid:
        return {}
    s = gehirn.sammler(sit)
    iso = _s(s.get("slotIso")) or _s((sit.get("lastBook") or {}).get("slotIso"))
    a = s.get("arzt") or {}
    return {
        "id": aid,
        "iso": iso,
        "spoken": spoken_slot(iso) if iso else "wie gerade vereinbart",
        "calendarId": _s(a.get("calendarId")),
        "doctorName": _s(a.get("calendarName")),
        "motivId": _s(s.get("motivId")),
        "motivName": _s(s.get("motivName")),
    }


def _letzte_fragte_storno(sit: dict) -> bool:
    for m in reversed(sit.get("messages") or []):
        if (m or {}).get("role") == "assistant":
            return bool(_STORNO_FRAGE_RE.search(_s(m.get("content"))))
    return False


def _frisch_absagen(sit: dict, melde: Melde = None) -> dict:
    """Frisch gebuchten Termin wirklich per CF stornieren."""
    termin = _frisch_termin(sit)
    if not termin:
        return {"text": "Welchen Termin soll ich absagen?"}
    sit["verwaltenTermin"] = termin["id"]
    sit["gefunden"] = [termin]
    gehirn.sammler(sit)["modus"] = "absagen"
    return verwalten._absagen(sit, melde)


def _abgeben_zug(sit: dict, t: str) -> dict | None:
    """ABGEBEN-Anliegen (W-HIRN 03.09.2026): Rueckruf/Nachricht deterministisch.

    Frueher gab es diesen Weg nur, wenn zufaellig keine Slots frei waren
    (verwalten.rueckruf_notiz) — jetzt ist er eine eigene Loesung: Name und
    Nummer einsammeln, ECHTE Notiz (praxis_notizen.jsonl + Dock), fertig.
    KEIN Termin-Angebot. None => LLM klaert die Zwischenfrage.
    """
    from kern import hirn as kern_hirn

    s = gehirn.sammler(sit)
    ab = sit.get("hirnAbgeben") or {}
    neu = gehirn.einsammeln(sit, t)
    sit["ernteZuletzt"] = sorted(neu)
    if not s["nachname"]:
        if s["frage"] == "name" and not neu:
            return None  # Zwischenfrage — LLM antwortet, die Frage bleibt offen
        s["frage"] = "name"
        return {"text": "Das richte ich gern aus. Für den Rückruf: Wie ist Ihr Name?"}
    tel = s["telefon"] or s["aktePhone"]
    if not tel:
        if s["frage"] == "telefon" and not neu:
            return None
        s["frage"] = "telefon"
        return {"text": "Danke. Und unter welcher Nummer erreichen wir Sie am besten?"}
    name = f"{s['vorname']} {s['nachname']}".strip()
    verwalten.abgeben_notiz(sit, was=_s(ab.get("was")))
    ab["offen"] = False
    sit["hirnAbgeben"] = ab
    s["frage"] = ""
    s["phase"] = "fertig"
    kern_hirn.erledigt(sit)
    return {"text": (
        f"Alles notiert — die Praxis meldet sich bei Ihnen unter der "
        f"{telefon.sprechbar(tel)}. Kann ich sonst noch etwas für Sie tun?"
    )}


def zug(sit: dict, gesagt: str, melde: Melde = None) -> dict | None:
    """Ein Anrufer-Satz durch den Buchungsfluss. None => LLM übernimmt."""
    s = gehirn.sammler(sit)
    t = _s(gesagt)
    if not t:
        return None

    # Weiterleitungs-Wunsch ("Ich möchte einen Menschen sprechen"): eigener
    # deterministischer Zweig VOR allem anderen — Platzhalter fuer Kirris
    # Zaluma-/SIP-Weiterleitung (bianca/weiterleiten.py).
    wl = weiterleiten.zug(sit, t, melde)
    if wl is not None:
        return wl

    # W-HIRN (03.09.2026): die Intent-Schicht hat den Modus evtl. schon vor
    # diesem Zug geschaltet — das Signal wandert in die Ernte-Menge, damit
    # verwalten seinen Einstiegs-Reset faehrt wie frueher bei der Regex.
    hirn_modus_neu = bool(sit.pop("hirnModusNeu", False))

    # Rueckruf-/Notiz-Anliegen (ABGEBEN): eigener deterministischer Zweig —
    # Name + Nummer einsammeln, echte Notiz schreiben, KEIN Termin-Angebot.
    # Direkt zurueck (auch None => LLM): der Satz ist hier schon geerntet,
    # ein zweites einsammeln unten wuerde Ziffern doppelt zaehlen.
    ab = sit.get("hirnAbgeben")
    if isinstance(ab, dict) and ab.get("offen"):
        return _abgeben_zug(sit, t)

    if s["phase"] == "gebucht":
        # Frisch gebucht — aber "sagen Sie ihn doch wieder ab" / "wann war
        # das nochmal?" gehoert in die Termin-Verwaltung, nicht ans LLM.
        neu = gehirn.einsammeln(sit, t)
        if hirn_modus_neu:
            neu.add("modus")
        sit["ernteZuletzt"] = sorted(neu)  # Task-Signal fuer die Talk-Schicht
        frisch = _frisch_termin(sit)

        # Eigene Rueckfrage nach erfundener LLM-Storno-Behauptung (Erledigt-Wache).
        if s["frage"] == "frisch_absage_ok":
            if gehirn.ist_ja(t) and not gehirn.ist_nein(t):
                return _frisch_absagen(sit, melde)
            if gehirn.ist_nein(t):
                s["frage"] = ""
                return {"text": (
                    "Alles klar, der Termin bleibt bestehen. "
                    "Kann ich sonst noch etwas für Sie tun?"
                )}
            return {"text": "Soll ich den Termin wirklich absagen? Ein kurzes Ja oder Nein genügt."}

        # LLM fragte bereits "Soll ich stornieren?" — Ja => wirklich canceln
        # (W-FRISCH-ABSAGE 02.09.2026).
        if (frisch and _letzte_fragte_storno(sit)
                and gehirn.ist_ja(t) and not gehirn.ist_nein(t)):
            return _frisch_absagen(sit, melde)

        if s["modus"] in {"absagen", "verschieben", "auskunft"}:
            sit["gefundenKey"] = ""  # Bestand frisch laden, der neue Termin zaehlt mit
            # Frische Buchung: Nachnamen-Suche ueberspringen, direkt bestaetigen.
            if s["modus"] == "absagen" and frisch:
                return verwalten._absage_frage(sit, frisch)
            return verwalten.zug(sit, t, neu, melde)
        return None

    if s["phase"] == "bestaetigen":
        if gehirn.ist_ja(t):
            sit.pop("bestaetigenUnklar", None)
            return _buchen(sit, melde)
        if gehirn.ist_nein(t):
            sit.pop("bestaetigenUnklar", None)
            sit.pop("buchIntent", None)
            s["phase"] = ""
            s["slotIso"] = ""
            return {"text": "Kein Problem. Was darf ich ändern — der Zeitpunkt, der Name oder die Nummer?"}

    if s["phase"] in {"angebot", "bestaetigen"} and sit.get("offered"):
        iso = _slot_wahl(t, sit["offered"])
        if iso:
            s["slotIso"] = iso
            # Nach Ja + slotTaken: Intent steht — Alternativ-Slot direkt buchen
            # (kein zweites "Dann halte ich fest…", W-BOOK-RETRY 01.09.2026).
            if sit.get("buchIntent"):
                return _buchen(sit, melde)
            return _readback(sit)

    neu = gehirn.einsammeln(sit, t)
    if hirn_modus_neu:
        neu.add("modus")
    sit["ernteZuletzt"] = sorted(neu)  # Task-Signal fuer die Talk-Schicht

    # Bestandstermin-Anliegen (absagen/verschieben/ansagen) haben ihren
    # eigenen deterministischen Fluss.
    if s["modus"] in {"absagen", "verschieben", "auskunft"}:
        return verwalten.zug(sit, t, neu, melde)

    if s["modus"] != "buchen" and "modus" not in neu:
        return None

    if s["frage"] == "rueckblick":
        # Antwort auf die Verlaufs-Frage zum letzten Besuch (30.08.2026).
        # Ernte im Satz -> die Maschine macht normal weiter (faellt durch);
        # klar positive Kurzantwort -> Mini-Empathie + naechster Schritt;
        # alles andere (Erzaehlung, Negatives, Gegenfrage) -> LLM plaudert
        # (Talk-Schicht), der Stand im Prompt fuehrt spaeter zurueck.
        s["rueckblick"] = "fertig"
        s["frage"] = ""
        if not neu:
            ton = gehirn.rueckblick_reaktion(t)
            if not ton or gehirn.ist_zwischenfrage(t):
                return None
            hintergrund.anstossen(sit)
            ein = _einschub(sit, ton)  # z. B. direkt die Zahnreinigungs-Frage
            if ein is not None:
                return ein
            fid2, frage2 = gehirn.naechste_frage(sit)
            s["frage"] = fid2
            if fid2:
                return {"text": (ton + frage2).strip()}
            ang = _angebot(sit, melde)
            if ang and _s(ang.get("text")):
                ang["text"] = ton + ang["text"]
            return ang

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
                sit["vorratGemerkt"] = False
                sit.pop("vorratDispatch", None)
        elif gehirn.ist_nein(t) or _ABLEHNUNG_RE.search(t):
            s["phase"] = ""
            s["slotIso"] = ""
            sit["offered"] = []
            sit.pop("angebotKalender", None)
            sit.pop("buchIntent", None)
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

    if "telefonAlt" in neu:
        # Entscheidung zur Akten-Nummer ist gefallen: SOFORT umsetzen (bei
        # "neu" schreibt masUpdatePatientPhone die Akte, BEVOR spaeter die
        # Buchung die Bestaetigungs-SMS ausloest), dann normal weiter.
        vor = _telefon_alt_ausfuehren(sit, melde)
        hintergrund.anstossen(sit)
        fid2, frage2 = gehirn.naechste_frage(sit)
        s["frage"] = fid2
        if fid2:
            return {"text": (vor + frage2).strip()}
        ang = _angebot(sit, melde)
        if ang and _s(ang.get("text")):
            ang["text"] = vor + ang["text"]
        return ang

    if "versicherung" in neu and s["versicherungWechsel"] and s["patientId"]:
        # Gemeldeter privat<->gesetzlich-Wechsel einer Bestandsakte: SOFORT
        # in die Kartei schreiben (Erledigt-Ansage nur nach echtem Erfolg),
        # dann normal weiter im Fragenfluss.
        vor = _versicherung_ausfuehren(sit, melde)
        if vor:
            hintergrund.anstossen(sit)
            fid2, frage2 = gehirn.naechste_frage(sit)
            s["frage"] = fid2
            if fid2:
                return {"text": (vor + frage2).strip()}
            ang = _angebot(sit, melde)
            if ang and _s(ang.get("text")):
                ang["text"] = vor + ang["text"]
            return ang

    hintergrund.anstossen(sit)

    fid, frage = gehirn.naechste_frage(sit)

    # Rueckblick auf den letzten Besuch / Zahnreinigungs-Angebot (30.08.2026):
    # als eigener Zug, sobald die Kartei-Daten da sind — aber nie vor einer
    # Nummern-Rueckbestaetigung, nie statt einer Zwischenfragen-Antwort und
    # nie mitten in einem unbeantworteten Pflichtfragen-Faden.
    if (fid not in {"telefon_check", "telefon_alt"}
            and (neu or not s["frage"])
            and not gehirn.ist_zwischenfrage(t)
            and not gespraech.traegt_thema(sit, t)):
        ein = _einschub(sit, _quittung(s, neu))
        if ein is not None:
            return ein

    if fid:
        if (fid == "telefon_alt" and s["frage"] == "telefon_alt"
                and not neu and _NOCHMAL_RE.search(t)):
            # "Welche Nummer nochmal?" — die Alt-Nummer wortgleich erneut
            # vorlesen, so oft der Anrufer fragt (Chef 29.08.2026). Nie ans
            # LLM: das kennt die Ziffern aus der Akte nicht.
            return {"text": gehirn.telefon_alt_frage(s)}
        if gehirn.ist_zwischenfrage(t) or (
            not neu and fid not in {"telefon_check", "anrufer_check"}
            and gespraech.traegt_thema(sit, t)
        ):
            # Echte Zwischenfrage/Abschweifung ("Was kostet das?") ODER ein
            # erzaehltes Nebenthema OHNE Ernte ("Meine Tochter heiratet!"):
            # das LLM antwortet natürlich (Talk-Schicht), zurueckgefuehrt
            # wird ueber Floor/Anker — zählt NIE als Leerlauf (Chef 27.08.:
            # "Abschweifungen müssen erlaubt sein"). Brachte der Satz Ernte,
            # macht die Maschine normal weiter; die Nummern-Rückbestätigung
            # (telefon_check) bleibt IMMER deterministisch.
            if s["frage"] != "pzr":
                # Eine offene Zahnreinigungs-Frage bleibt offen ("Was kostet
                # die denn?" -> LLM nennt den Preis, das Ja danach zaehlt).
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
                if fid == "anrufer_check":
                    # Identitaets-Kontrolle bleibt ebenfalls deterministisch —
                    # das LLM darf hier nie "erkannt" erfinden (W-ANRUFER-CHECK).
                    return {"text": "Entschuldigung, kurz zur Kontrolle: Habe ich Sie richtig erkannt? Ein kurzes Ja oder Nein genügt."}
                if fid == "telefon_alt":
                    # Auch die Akten-Nummer-Frage bleibt deterministisch —
                    # mit der Nummer im Ohr faellt die Wahl leichter.
                    return {"text": gehirn.telefon_alt_frage(s)}
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
        return {"text": (_quittung(s, neu) + frage).strip()}

    if not neu and s["frage"]:
        return None  # nichts Verwertbares gehört — LLM klärt, Status führt zurück

    s["frage"] = ""
    ang = _angebot(sit, melde)
    if ang and _s(ang.get("text")):
        q = _quittung(s, neu)
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
        f"Grund={_s(s.get('grund')) or '?'}",
        f"Arzt={_s(a.get('calendarName')) or a.get('typ') or '?'}",
        f"Telefon={_s(s.get('telefon')) or '?'}",
        f"Phase={_s(s.get('phase')) or 'sammeln'}",
    ]
    if s.get("pzr") == "ja":
        teile.append("Zahnreinigung=kommt mit dazu")
    offen = ""
    if s.get("frage"):
        offen = f" Offene Frage: {s['frage']}."
    if s.get("frage") == "pzr":
        offen += " (Bianca hat gefragt, ob eine professionelle Zahnreinigung mit dazu soll — Preisfragen dazu beantwortet der Preise-Abschnitt.)"
    # Rueckblick-Kontext (30.08.2026): das LLM plaudert ueber den letzten
    # Besuch mit — es muss wissen, wann und weswegen der Anrufer da war.
    if s.get("rueckblick") and s.get("letzterGrund"):
        offen += (f" Kontext: Der Anrufer war zuletzt am {_s(s.get('letzterBesuch'))[:10]} da, "
                  f"Grund damals: {s['letzterGrund']}.")
        if s.get("rueckblick") == "gefragt":
            offen += " Bianca hat gerade nach dem Verlauf gefragt — reagiere empathisch auf die Antwort."
    slots = "; ".join(_s(x.get("spoken")) for x in (sit.get("offered") or [])[:3])
    if slots:
        offen += f" Angeboten: {slots}."
    return (
        "Laufende Terminbuchung (führe den Anrufer immer dorthin zurück): "
        + ", ".join(teile) + "." + offen
    )
