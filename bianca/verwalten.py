"""Bestandstermine am Telefon: ansagen, absagen, verschieben — deterministisch.

Gleiche Bauart wie flow.py: kein LLM auf dem Pflichtpfad. Die Termine kommen
in EINEM warmen Aufruf (agentFindPatientAppointments: Patient + kommende
Termine inkl. Behandler und Kalender-ID), der Storno trifft punktgenau die
Termin-ID (agentCancelAppointmentById), das Verschieben laeuft ueber
postpone mit Termin-ID. Liefert None, wenn der Satz nichts mit dem Anliegen
zu tun hat — dann uebernimmt das LLM (Status steht im Prompt).
"""

from __future__ import annotations

from typing import Any, Callable

from bianca import gehirn, hintergrund
from kern import calendar as kal
from kern.sitzung import merke_tool
from kern.slots import pick_slots, spoken_offer, spoken_slot

Melde = Callable[[str], None] | None

_MODI = {"absagen", "verschieben", "auskunft"}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _ctx(sit: dict) -> dict:
    """Minimaler Kontext fuer die Namens-Suche und die Schreib-Aufrufe."""
    s = gehirn.sammler(sit)
    ctx = sit.setdefault("booking", {})
    if s["vorname"]:
        ctx["firstName"] = s["vorname"]
    if s["nachname"]:
        ctx["lastName"] = s["nachname"]
    name = f"{s['vorname']} {s['nachname']}".strip()
    if name:
        ctx["patientName"] = name
    if s["patientId"]:
        ctx["patientId"] = s["patientId"]
    tel = s["telefon"] or s["aktePhone"]
    if tel:
        ctx["phone"] = tel
    return ctx


def _gewaehlt(sit: dict) -> dict:
    aid = _s(sit.get("verwaltenTermin"))
    for a in sit.get("gefunden") or []:
        if _s(a.get("id")) == aid:
            return a
    return {}


def _finden(sit: dict, melde: Melde) -> dict:
    """Kommende Termine zum Namen holen — einmal pro Name, dann aus dem Cache."""
    s = gehirn.sammler(sit)
    key = f"{s['vorname']}|{s['nachname']}".lower()
    if sit.get("gefundenKey") == key and isinstance(sit.get("gefunden"), list):
        return {"ok": True, "appointments": sit["gefunden"]}
    if melde:
        melde("list_appointments")
    res = kal.find_patient_appointments(sit["tenant"], _ctx(sit))
    if res.get("ok") and not res.get("notFound"):
        sit["gefunden"] = res.get("appointments") or []
        sit["gefundenKey"] = key
        pat = res.get("patient") or {}
        if _s(pat.get("id")):
            s["patientId"] = _s(pat.get("id"))
            s["bekannt"] = True
            s["warSchonMal"] = True
            if not s["vorname"] and _s(pat.get("firstName")):
                s["vorname"] = _s(pat.get("firstName"))
    return res


def _arzt_uebernehmen(sit: dict, termin: dict) -> None:
    """Behandler des Bestandstermins als Vorgabe fuer eine Folge-Buchung."""
    s = gehirn.sammler(sit)
    if termin.get("calendarId") and not (s["arzt"] or {}).get("calendarId"):
        s["arzt"] = {
            "typ": "letzter",
            "calendarId": _s(termin.get("calendarId")),
            "calendarName": _s(termin.get("doctorName")),
        }


def _liste_sprechbar(termine: list[dict]) -> str:
    teile = [_s(a.get("spoken")) for a in termine[:3] if _s(a.get("spoken"))]
    if len(teile) > 1:
        return "; ".join(teile[:-1]) + "; und " + teile[-1]
    return teile[0] if teile else ""


def _kein_termin(sit: dict, modus: str) -> dict:
    s = gehirn.sammler(sit)
    wer = f"{s['vorname']} {s['nachname']}".strip()
    s["phase"] = "fertig"
    s["frage"] = "neubuchung"
    was = {
        "absagen": "Da gibt es also nichts abzusagen.",
        "verschieben": "Da gibt es also nichts zu verschieben.",
    }.get(modus, "")
    return {"text": _s(
        f"Ich sehe unter {wer or 'Ihrem Namen'} aktuell keinen kommenden Termin. "
        f"{was} Soll ich Ihnen direkt einen neuen Termin anbieten?"
    )}


def _absage_frage(sit: dict, termin: dict) -> dict:
    s = gehirn.sammler(sit)
    sit["verwaltenTermin"] = _s(termin.get("id"))
    s["phase"] = "absage_bestaetigen"
    s["frage"] = "absage_ok"
    return {"text": f"Soll ich den Termin {termin.get('spoken')} wirklich absagen?"}


def _absagen(sit: dict, melde: Melde) -> dict:
    s = gehirn.sammler(sit)
    termin = _gewaehlt(sit)
    if melde:
        melde("cancel_appointment")
    res = kal.cancel_by_id(sit["tenant"], _ctx(sit), _s(termin.get("id")))
    merke_tool(sit, "cancel_appointment", res)
    if res.get("ok"):
        _arzt_uebernehmen(sit, termin)
        sit["gefundenKey"] = ""  # Bestand hat sich geaendert
        s["phase"] = "fertig"
        s["frage"] = "neubuchung"
        wann = _s(termin.get("spoken")) or "wie besprochen"
        return {
            "text": f"Erledigt — der Termin {wann} ist abgesagt. "
                    "Möchten Sie direkt einen neuen Termin vereinbaren?",
            "book": {"cancelled": True, "spoken": res.get("spoken") or ""},
        }
    s["phase"] = "fertig"
    s["frage"] = ""
    return {"text": res.get("spoken") or "Die Absage hat gerade nicht geklappt. Die Praxis kümmert sich darum."}


def _verschieb_wunsch_frage(sit: dict, termin: dict) -> dict:
    s = gehirn.sammler(sit)
    sit["verwaltenTermin"] = _s(termin.get("id"))
    s["phase"] = "verschieb_wunsch"
    s["frage"] = "wunsch"
    return {"text": (
        f"Gerne — es geht um den Termin {termin.get('spoken')}. "
        "Wann passt es Ihnen denn besser: eher vormittags oder nachmittags, und ab welchem Tag?"
    )}


def _verschieb_angebot(sit: dict, melde: Melde) -> dict:
    """Freie Zeiten im Kalender des Bestandstermins suchen, Wunsch beachten."""
    s = gehirn.sammler(sit)
    termin = _gewaehlt(sit)
    if not termin:
        return _kein_termin(sit, "verschieben")
    if melde:
        melde("offer_slots")
    such_ctx = {
        "calendarId": _s(termin.get("calendarId")),
        "calendarName": _s(termin.get("doctorName")),
        "visitMotiveId": _s(termin.get("motivId")),
        "visitMotiveName": _s(termin.get("motivName")) or "Kontrolluntersuchung",
    }
    found = kal.find_slots(
        sit["tenant"], such_ctx,
        start_date=gehirn.start_datum(s),
        egal=not such_ctx["calendarId"],
        source="pickadoc-bianca",
    )
    if not found.get("ok"):
        s["phase"] = "fertig"
        s["frage"] = ""
        return {"text": (
            "Der Terminkalender antwortet gerade nicht. "
            "Die Praxis ruft Sie zum Verschieben kurzfristig zurück."
        )}
    isos = [x for x in kal._iso_liste(found.get("slots") or []) if x[:16] != _s(termin.get("iso"))[:16]]
    picked = pick_slots(isos, wish=s["wunsch"])
    if not picked["slots"]:
        s["phase"] = "verschieb_wunsch"
        s["frage"] = "wunsch"
        return {"text": (
            "Zu diesem Wunsch finde ich gerade nichts Freies. "
            "Ginge auch ein anderer Tag oder eine andere Tageszeit?"
        )}
    offered = [{"iso": x["iso"], "spoken": spoken_slot(x["iso"])} for x in picked["slots"]]
    sit["offered"] = offered
    s["phase"] = "verschieb_angebot"
    s["frage"] = "slotwahl"
    return {"text": spoken_offer(picked["slots"], wish_matched=picked["wishMatched"])}


def _verschieb_readback(sit: dict, neu_iso: str) -> dict:
    s = gehirn.sammler(sit)
    termin = _gewaehlt(sit)
    s["slotIso"] = neu_iso
    s["phase"] = "verschieb_bestaetigen"
    s["frage"] = "verschieb_ok"
    return {"text": (
        f"Dann verschiebe ich den Termin {termin.get('spoken')} "
        f"auf {spoken_slot(neu_iso)}. Passt das so?"
    )}


def _verschieben(sit: dict, melde: Melde) -> dict:
    s = gehirn.sammler(sit)
    termin = _gewaehlt(sit)
    ctx = _ctx(sit)
    ctx["appointmentId"] = _s(termin.get("id"))
    if melde:
        melde("move_appointment")
    res = kal.move_appointment(sit["tenant"], ctx, slot_iso=s["slotIso"])
    merke_tool(sit, "move_appointment", res)
    if res.get("ok") and (res.get("moved") or res.get("dryRun")):
        _arzt_uebernehmen(sit, termin)
        sit["gefundenKey"] = ""
        s["phase"] = "fertig"
        s["frage"] = ""
        return {
            "text": (res.get("spoken") or "Der Termin ist verschoben.")
                    + " Kann ich sonst noch etwas für Sie tun?",
            "book": {"moved": True, "slotIso": res.get("slotIso") or "", "spoken": res.get("spoken") or ""},
        }
    if res.get("slots"):
        sit["offered"] = res["slots"]
        s["phase"] = "verschieb_angebot"
        s["frage"] = "slotwahl"
        s["slotIso"] = ""
        return {"text": res.get("spoken") or "Der Platz ist gerade weg — ich habe Alternativen."}
    s["phase"] = "fertig"
    s["frage"] = ""
    return {"text": res.get("spoken") or "Das Verschieben hat gerade nicht geklappt. Die Praxis ruft Sie dazu zurück."}


def _ansagen(sit: dict) -> dict:
    s = gehirn.sammler(sit)
    termine = sit.get("gefunden") or []
    s["phase"] = "fertig"
    s["frage"] = ""
    if len(termine) == 1:
        _arzt_uebernehmen(sit, termine[0])
        sit["verwaltenTermin"] = _s(termine[0].get("id"))
        # Gespraechsnotiz beim Auflegen an DIESEN Termin haengen.
        sit.setdefault("booking", {})["appointmentId"] = _s(termine[0].get("id"))
        return {"text": (
            f"Ihr nächster Termin: {termine[0].get('spoken')}. "
            "Passt der so, oder möchten Sie ihn verschieben oder absagen?"
        )}
    return {"text": (
        f"Sie haben {len(termine)} kommende Termine: {_liste_sprechbar(termine)}. "
        "Kann ich sonst noch etwas für Sie tun?"
    )}


def _dispatch(sit: dict, melde: Melde) -> dict | None:
    """Name ist da: Termine holen und je nach Anliegen weitermachen."""
    s = gehirn.sammler(sit)
    res = _finden(sit, melde)
    if not res.get("ok"):
        s["phase"] = "fertig"
        s["frage"] = ""
        return {"text": (
            "Ich komme gerade nicht an den Terminkalender. "
            "Die Praxis ruft Sie dazu zurück — entschuldigen Sie bitte."
        )}
    if res.get("notFound"):
        return _kein_termin(sit, s["modus"])
    termine = sit.get("gefunden") or []
    if not termine:
        return _kein_termin(sit, s["modus"])
    if s["modus"] == "auskunft":
        return _ansagen(sit)
    if len(termine) == 1:
        if s["modus"] == "absagen":
            return _absage_frage(sit, termine[0])
        sit["verwaltenTermin"] = _s(termine[0].get("id"))
        if s["wunsch"]:
            return _verschieb_angebot(sit, melde)
        return _verschieb_wunsch_frage(sit, termine[0])
    verb = "absagen" if s["modus"] == "absagen" else "verschieben"
    s["phase"] = "wahl"
    s["frage"] = "terminwahl"
    return {"text": f"Sie haben mehrere Termine: {_liste_sprechbar(termine)}. Welchen möchten Sie {verb}?"}


def zug(sit: dict, gesagt: str, neu: set[str], melde: Melde = None) -> dict | None:
    """Ein Anrufer-Satz durch die Termin-Verwaltung. None => LLM uebernimmt."""
    from bianca.flow import _slot_wahl  # kein Kreis-Import auf Modulebene

    s = gehirn.sammler(sit)
    t = _s(gesagt)
    if s["modus"] not in _MODI:
        return None

    # 1) Offene Bestaetigungen zuerst — ein "ja" traegt sonst nichts Neues.
    if s["phase"] == "absage_bestaetigen":
        if gehirn.ist_ja(t):
            return _absagen(sit, melde)
        if gehirn.ist_nein(t):
            s["phase"] = "fertig"
            s["frage"] = ""
            return {"text": "Alles klar, der Termin bleibt bestehen. Kann ich sonst noch etwas für Sie tun?"}
        if "modus" in neu and s["modus"] == "verschieben":
            # "Nicht absagen — verschieben!" mitten in der Rueckfrage.
            termin = _gewaehlt(sit)
            if termin:
                if s["wunsch"]:
                    return _verschieb_angebot(sit, melde)
                return _verschieb_wunsch_frage(sit, termin)
        return None

    if s["phase"] == "verschieb_bestaetigen":
        if gehirn.ist_ja(t):
            return _verschieben(sit, melde)
        if gehirn.ist_nein(t) or "wunsch" in neu:
            s["slotIso"] = ""
            if "wunsch" in neu:
                return _verschieb_angebot(sit, melde)
            s["phase"] = "verschieb_wunsch"
            s["frage"] = "wunsch"
            return {"text": "Kein Problem. Wann passt es Ihnen denn besser?"}
        return None

    # 2) Auswahl des Bestandstermins ("den am Donnerstag"). Hier NIE ans LLM
    #    abgeben: ein frei erfundenes "dann sage ich den ab" waere fatal.
    if s["phase"] == "wahl" and sit.get("gefunden"):
        angebote = [{"iso": a.get("iso"), "spoken": a.get("spoken")} for a in sit["gefunden"] if a.get("iso")]
        iso = _slot_wahl(t, angebote)
        if iso:
            termin = next((a for a in sit["gefunden"] if _s(a.get("iso")) == iso), {})
            if termin:
                if s["modus"] == "absagen":
                    return _absage_frage(sit, termin)
                sit["verwaltenTermin"] = _s(termin.get("id"))
                if s["wunsch"]:
                    return _verschieb_angebot(sit, melde)
                return _verschieb_wunsch_frage(sit, termin)
        return {"text": (
            f"Da will ich nichts Falsches erwischen. Zur Auswahl: {_liste_sprechbar(sit['gefunden'])}. "
            "Sagen Sie einfach 'den ersten' oder 'den zweiten' — oder nennen Sie die Uhrzeit."
        )}

    # 3) Neuer Zeitpunkt beim Verschieben
    if s["phase"] == "verschieb_angebot" and sit.get("offered"):
        iso = _slot_wahl(t, sit["offered"])
        if iso:
            return _verschieb_readback(sit, iso)
        if "wunsch" in neu:
            return _verschieb_angebot(sit, melde)
        if gehirn.ist_nein(t):
            s["phase"] = "verschieb_wunsch"
            s["frage"] = "wunsch"
            return {"text": "Wann würde es Ihnen denn besser passen — eher vormittags oder nachmittags?"}
        return None

    if s["phase"] == "verschieb_wunsch":
        if "wunsch" in neu:
            return _verschieb_angebot(sit, melde)
        if not neu:
            return None

    # 4) Nach erledigter Absage: direkt neu buchen?
    if s["frage"] == "neubuchung":
        if gehirn.ist_ja(t) or "grund" in neu or "wunsch" in neu:
            s["modus"] = "buchen"
            s["phase"] = ""
            s["frage"] = ""
            if s["warSchonMal"] is None:
                s["warSchonMal"] = bool(s["patientId"])
            hintergrund.anstossen(sit)
            fid, frage = gehirn.naechste_frage(sit)
            s["frage"] = fid
            return {"text": frage or "Worum geht es denn — eine Kontrolle, Schmerzen, oder etwas anderes?"}
        if gehirn.ist_nein(t):
            s["frage"] = ""
            return {"text": "Alles klar. Kann ich sonst noch etwas für Sie tun?"}
        return None

    # 5) Ohne Namen geht nichts: einmal freundlich fragen.
    if not s["nachname"]:
        if s["frage"] == "name" and not neu:
            return None  # LLM klaert die Zwischenfrage, Status fuehrt zurueck
        s["frage"] = "name"
        was = {
            "absagen": "Damit ich den richtigen Termin absage",
            "verschieben": "Damit ich den richtigen Termin finde",
            "auskunft": "Damit ich in den Kalender schauen kann",
        }[s["modus"]]
        return {"text": f"{was}: Wie ist Ihr Vor- und Nachname?"}

    # 6) Name da — Termine holen und das Anliegen bedienen.
    if s["phase"] in {"", "fertig"} and (("name" in neu or "nachname" in neu or "modus" in neu) or sit.get("gefundenKey") != f"{s['vorname']}|{s['nachname']}".lower()):
        quittung = ""
        if ("name" in neu or "nachname" in neu) and s["nachname"]:
            voll = f"{s['vorname']} {s['nachname']}".strip()
            quittung = f"Danke, {voll}. "
        aus = _dispatch(sit, melde)
        if aus and quittung and _s(aus.get("text")):
            aus["text"] = quittung + aus["text"]
        return aus

    return None


def status_zeile(sit: dict) -> str:
    """Kompakter Verwaltungs-Stand fuer den LLM-Prompt, wenn der Fluss abgibt."""
    s = sit.get("sammler") or {}
    if s.get("modus") not in _MODI:
        return ""
    termine = "; ".join(_s(a.get("spoken")) for a in (sit.get("gefunden") or [])[:3])
    teile = [
        f"Anliegen={s.get('modus')}",
        f"Name={_s(s.get('vorname'))} {_s(s.get('nachname'))}".strip(),
        f"Phase={_s(s.get('phase')) or 'sammeln'}",
    ]
    offen = f" Offene Frage: {s['frage']}." if s.get("frage") else ""
    if termine:
        offen += f" Gefundene Termine: {termine}."
    return (
        "Laufende Termin-Verwaltung (fuehre den Anrufer immer dorthin zurueck): "
        + ", ".join(teile) + "." + offen
    )
