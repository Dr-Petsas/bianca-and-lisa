"""Biancas Zug-Logik: Zustandsmaschine zuerst, Sprachmodell nur als Beifahrer.

Jeder Anrufer-Satz geht durch flow.zug() — deterministisch, ohne Modell-Latenz.
Nur wenn der Fluss abgibt (Zwischenfrage, Absage/Verschieben, Smalltalk),
übernimmt das Modell mit dem Buchungs-Stand im Prompt und denselben
Kalender-Werkzeugen wie Lisa (kern.zuege).
"""

from __future__ import annotations

import re
from typing import Any

from bianca import flow, gehirn, session, telefon
from bianca.greeting import begruessung
from bianca.prompt import TOOLS, system_prompt
from kern import gespraech, llm, stille, wiederholung, zuege
from kern import wissen as kern_wissen
from kern.calendar import slots_zeile


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


# --- Wachen für den LLM-Pfad -------------------------------------------------
# Live 27.08.2026: Das Modell ERFAND Terminangebote ("Mittwoch, den 24. Juli,
# um 09:30 Uhr" — in der Vergangenheit!), obwohl kein einziger echter Slot
# geladen war, und stellte eigene Fragen statt der offenen Sammler-Frage.

_ANGEBOT_VERB_RE = re.compile(
    r"\bbiete|\banbieten|\bhätte\b|\bhaette\b|\bfrei\b|\bvorschlag|\bschlage\b|\bpasst\s+ihnen",
    re.I,
)
_ANGEBOT_ZEIT_RE = re.compile(
    r"\b(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b|"
    r"\b\d{1,2}\.\s?(?:\d{1,2}\.|januar|februar|märz|maerz|april|mai|juni|juli|"
    r"august|september|oktober|november|dezember)|"
    r"\b(?:um|gegen)\s+\S{1,18}\s*uhr\b",
    re.I,
)
_FRAGE_KERN = {
    "schonmal": r"schon\s+(?:ein)?mal|bereits\s+bei\s+uns",
    "arzt": r"behandler|arzt|ärztin|aerztin|doktor",
    # auch "Vor- und Nachname": dort steht kein alleinstehendes "Name"
    "name": r"\bnamen?\b|vorname|nachname",
    "vorname": r"vorname",
    "nachname": r"nachname",
    "grund": r"worum|grund|anliegen|kontrolle",
    "wunsch": r"\bwann\b|vormittag|nachmittag|uhrzeit",
    "buchstabieren": r"buchstabier",
    "telefon": r"nummer|handy|telefon",
    "telefon_check": r"nummer|stimmt",
    "telefon_alt": r"nummer|alte|akte|löschen",
    "slotwahl": r"\buhr\b|termin.{0,30}passt|welcher",
    "bestaetigung": r"eintragen|so\s+buchen|festhalten",
    "versicherung": r"privat|gesetzlich|versichert",
    "versicherung_check": r"privat|gesetzlich|versichert|geändert|geaendert",
}
_SATZ_ENDE_RE = re.compile(r"(?<=[.!?…])\s+")

# Wiederhol-Wache (Chef 27.08.2026: "wenn der String Behandler im Gehirn
# gefüllt ist, ist der Wert halt da — fertig"): Fragen des Modells nach
# Feldern, die der Sammler LÄNGST hat, werden gestrichen. Der Frage-Anker
# hängt danach die wirklich offene Frage an.
_GEFUELLT_WACHEN: list[tuple[re.Pattern, Any]] = [
    (re.compile(r"handynummer|telefonnummer|welcher\s+nummer|ihre\s+nummer", re.I),
     lambda s: bool(s.get("telefonOk") or s.get("telefonAkte"))),
    (re.compile(r"bei\s+(welchem|wem)|welche[rm]?\s+(behandler|arzt|ärztin|aerztin)|zu\s+welchem\s+(arzt|behandler)", re.I),
     lambda s: bool((s.get("arzt") or {}).get("calendarId") or (s.get("arzt") or {}).get("typ") == "egal")),
    (re.compile(r"wie\s+(heißen|heissen)\s+sie|wie\s+(ist|lautet)\s+ihr\s+(vor.{0,6}|nach)?name|ihren\s+namen", re.I),
     lambda s: bool(s.get("vorname") and s.get("nachname"))),
    (re.compile(r"worum\s+geht\s+es|welche[rm]?\s+grund|was\s+für\s+ein\s+anliegen", re.I),
     lambda s: bool(s.get("grund"))),
    (re.compile(r"schon\s+(ein)?mal\s+bei\s+uns", re.I),
     lambda s: s.get("warSchonMal") is not None),
    (re.compile(r"buchstabier", re.I),
     lambda s: bool(s.get("buchstabiert"))),
    (re.compile(r"wann\s+passt\s+es\s+ihnen", re.I),
     lambda s: s.get("wunsch") is not None),
]


def _gefuellte_fragen_streichen(s: dict, text: str) -> str:
    """Sätze streichen, die ein bereits gefülltes Sammler-Feld erfragen."""
    saetze = _SATZ_ENDE_RE.split(text)
    behalten = []
    for satz in saetze:
        frage_satz = "?" in satz
        raus = frage_satz and any(
            cre.search(satz) and gefuellt(s) for cre, gefuellt in _GEFUELLT_WACHEN
        )
        if not raus:
            behalten.append(satz)
    return " ".join(x for x in behalten if x).strip()

# Behauptet das Modell eine Absage/Verschiebung, ohne dass ein Werkzeug lief?
# "sage ... ab" darf einen kompletten gesprochenen Termin ueberspannen
# ("ich sage den Termin morgen um zehn Uhr dreissig bei Doktor Petsas ab").
_ERLEDIGT_RE = re.compile(
    r"\b(abgesagt|storniert|verschoben|verlegt)\b|"
    r"\bsage\b[^.!?]{0,90}\bab\b|\bstorniere\b|\bverschiebe\b|\bverlege\b",
    re.I,
)


def _kanonische_frage(sit: dict, fid: str) -> str:
    if fid == "slotwahl":
        angebote = "; ".join(_s(x.get("spoken")) for x in (sit.get("offered") or [])[:3])
        return f"Im Angebot sind: {angebote}. Welcher passt Ihnen?" if angebote else "Welcher der genannten Termine passt Ihnen?"
    if fid == "bestaetigung":
        return "Soll ich den Termin so fest eintragen?"
    fid2, frage = gehirn.naechste_frage(sit)
    return frage if fid2 == fid else ""


def _wiederholungs_wache(sit: dict, text: str) -> str:
    """Wiederholungs-Wächter (Chef 27.08.2026: 'nie wieder doppelte
    telefonnummer oder behandler abfragen hören'): dieselbe Frage nie
    zweimal wortgleich — beim zweiten Mal kommt die nächste Formulierung
    (gehirn.FRAGE_VARIANTEN), andere wortgleiche Frage-/Langsätze fliegen.
    sit["messages"] traegt hier immer noch den Stand VOR diesem Zug
    (user_turn arbeitet auf einer Kopie), die letzte Assistenten-Antwort
    dort ist also wirklich der vorige Zug."""
    s = sit.get("sammler") or {}
    fid = _s(s.get("frage"))
    return wiederholung.pruefen(
        sit, text,
        frueher=wiederholung.letzte_antworten(sit.get("messages") or []),
        frage_id=fid,
        frage_kern=_FRAGE_KERN.get(fid, ""),
        varianten=gehirn.FRAGE_VARIANTEN,
    )


_FEHLT_WORT = {
    "schonmal": "ob Sie schon Patient bei uns sind",
    "arzt": "der Behandler",
    "name": "Ihr Name",
    "vorname": "Ihr Vorname",
    "nachname": "der Nachname",
    "grund": "der Grund Ihres Besuchs",
    "wunsch": "Ihr Wunschtermin",
    "buchstabieren": "die Schreibweise des Nachnamens",
    "telefon": "Ihre Handynummer",
    "telefon_alt": "Ihre Entscheidung zur alten Nummer in der Akte",
    "slotwahl": "Ihre Terminwahl",
    "bestaetigung": "Ihr Okay",
    "versicherung": "Ihr Versichertenstatus — privat oder gesetzlich",
    "versicherung_check": "ob sich Ihre Versicherung geändert hat",
}


def _stand_ansage(sit: dict) -> str:
    """Wo stehen wir, was war der Auftrag, was fehlt noch — deterministisch
    aus dem Sammler, nie geraten (Stille-Wächter, Chef 27.08.2026: 'Gehirn
    einschalten und nicht bei null von vorne anfangen')."""
    s = sit.get("sammler") or {}
    modus = _s(s.get("modus"))
    phase = _s(s.get("phase"))
    fid = _s(s.get("frage"))
    if modus in {"absagen", "verschieben"}:
        tun = "abzusagen" if modus == "absagen" else "zu verschieben"
        frage = _s(sit.get("flussFrage")) or "Um welchen Termin geht es denn?"
        return f"Wir waren gerade dabei, Ihren Termin {tun}. {frage}"
    if modus == "buchen" and phase not in {"gebucht", "fertig"}:
        auftrag = "Wir waren mitten in der Terminaufnahme"
        if _s(s.get("grund")):
            auftrag += f" wegen {_s(s.get('grund'))}"
        habe = []
        if _s(s.get("vorname")) or _s(s.get("nachname")):
            habe.append("Ihren Namen habe ich schon.")
        a = s.get("arzt") or {}
        if a.get("calendarId") or _s(a.get("typ")):
            habe.append("Der Behandler ist notiert.")
        fehlt = _FEHLT_WORT.get(fid, "")
        frage = _kanonische_frage(sit, fid) if fid else ""
        teile = [auftrag + "."] + habe
        if fehlt:
            teile.append(f"Mir fehlt noch {fehlt}.")
        if frage:
            teile.append(frage)
        return " ".join(teile)
    return "Kann ich sonst noch etwas für Sie tun?"


def stille_zug(sit: dict) -> dict[str, Any]:
    """Stille-Wächter (Chef 27.08.2026): der Anrufer sagt seit ~4 Sekunden
    nichts — Bianca ergreift selbst das Wort, statt stumm zu warten.

    - Läuft gerade ein Nebenthema (Talk-Floor), knüpft der ERSTE Stups dort
      an; der zweite holt auf die Job-Spur.
    - Auf der Job-Spur kommt der volle Stand (Auftrag, was schon da ist,
      offene Frage) — beim wiederholten Stups nur noch kurz die Frage, den
      Wortlaut variiert der Wiederholungs-Wächter.
    - Nach MAX_STUPSE Stupsen ohne Antwort: Schweigen (leerer Text), bis der
      Anrufer wieder spricht (user_turn setzt den Zähler zurück).
    """
    n = stille.stups_zaehlen(sit)
    if n > stille.MAX_STUPSE:
        return {"text": "", "book": None}
    s = sit.get("sammler") or {}
    fid = _s(s.get("frage"))

    # Nummern-Rückbestätigung bleibt IMMER deterministisch — hier ist die
    # wortgleiche Wiederholung der Nummer ausdrücklich richtig.
    if fid == "telefon_check" and _s(s.get("telefonOffen")):
        text = (f"{stille.anrede(n)} Ich wiederhole die Nummer: "
                f"{telefon.sprechbar(s['telefonOffen'])}. Stimmt das so?")
        stille.anhaengen(sit, text)
        return {"text": text, "book": None}
    if fid == "telefon_alt" and _s(s.get("aktePhone")):
        # Akten-Nummer-Frage genauso: mit der Nummer im Ohr faellt die Wahl
        # leichter — wortgleiches Wiederholen ist hier gewollt (29.08.2026).
        text = f"{stille.anrede(n)} {gehirn.telefon_alt_frage(s)}"
        stille.anhaengen(sit, text)
        return {"text": text, "book": None}

    st = gespraech.stand(sit)
    stack = st.get("stack") or []
    if (n == 1 and stack and gespraech.floor(sit) in (gespraech.TALK, gespraech.BLENDED)):
        thema = _s((stack[-1] or {}).get("thema"))
        if thema:
            text = (f"{stille.anrede(n)} Wir waren gerade beim Thema {thema} — "
                    "erzählen Sie gern weiter.")
            stille.anhaengen(sit, text)
            return {"text": text, "book": None}

    if stille.job_stups_gemerkt(sit):
        # Stand kam schon einmal — jetzt nur kurz die offene Frage neu
        # anstoßen (ohne Begleitsätze); den Wortlaut tauscht der
        # Wiederholungs-Wächter.
        frage = stille.nur_fragesaetze(_kanonische_frage(sit, fid)) if fid else ""
        text = " ".join(x for x in [stille.anrede(n), frage] if x)
    else:
        text = f"{stille.anrede(n)} {_stand_ansage(sit)}"
    text = _wiederholungs_wache(sit, text) or text
    stille.anhaengen(sit, text)
    return {"text": text, "book": None}


def _nachbessern(sit: dict, text: str, melde=None, werkzeug_lief: bool = False,
                 floor: str = gespraech.JOB) -> str:
    """LLM-Antworten auf dem Buchungspfad absichern: erfundene Angebote
    durch echte ersetzen, danach die offene Sammler-Frage wieder verankern."""
    s = sit.get("sammler") or {}
    t = _s(text)
    if not t:
        return text

    def _entdoppelt(aus: str) -> str:
        # Wiederholungs-Wächter als letzte Instanz VOR dem Mund — nie stumm:
        # bleibt nach dem Entdoppeln nichts übrig, spricht der Originaltext.
        return _wiederholungs_wache(sit, aus) or aus

    # 0) Erledigt-Wache: "ich sage den Termin ab" / "ist verschoben" ohne
    #    Werkzeuglauf ist eine leere Behauptung (live 27.08.: beide Termine
    #    standen noch im Kalender). Zurueck zur letzten offenen Fluss-Frage.
    if s.get("modus") in {"absagen", "verschieben"} and not werkzeug_lief and _ERLEDIGT_RE.search(t):
        zurueck = _s(sit.get("flussFrage")) or "Um welchen Termin geht es denn genau?"
        return _entdoppelt("Da will ich nichts falsch machen — das mache ich erst nach Ihrer Bestätigung. " + zurueck)

    if s.get("modus") != "buchen" or s.get("phase") in {"gebucht", "fertig"}:
        return _entdoppelt(t)

    # 1) Angebots-Wache: konkrete Tag/Uhrzeit-Angebote ohne echte Slots.
    if not sit.get("offered") and _ANGEBOT_ZEIT_RE.search(t) and _ANGEBOT_VERB_RE.search(t):
        fid, frage = gehirn.naechste_frage(sit)
        if fid:
            s["frage"] = fid
            return _entdoppelt("Einen Moment — Termine schaue ich lieber direkt im Kalender nach. " + frage)
        ang = flow._angebot(sit, melde)
        if ang and _s(ang.get("text")):
            return ang["text"]
        return "Einen Moment, ich schaue in den Kalender."

    # 2) Wiederhol-Wache: Fragen nach längst gefüllten Feldern fliegen raus
    #    (Chef 27.08.2026: Telefonnummer wurde mehrfach erfragt/bestätigt).
    gestrichen = _gefuellte_fragen_streichen(s, t)
    if gestrichen != t:
        t = gestrichen

    # 3) Frage-Anker: die offene Pflichtfrage muss am Zugende stehen —
    #    ABER nicht auf dem Talk-Floor (Chef 27.08.2026: Abschweifen ohne
    #    den Faden zu verlieren, ohne nervende Wiederholungen). Solange der
    #    Anrufer ein Thema zieht, haelt der Buchungs-Stand im Prompt die
    #    Spur; zurueckgefuehrt wird beim Floor "zurueck"/"blended".
    #    Haengt das Modell die Job-Frage TROTZDEM an (Probe 27.08.2026:
    #    "... alles Liebe. Worum geht es bei Ihrem Besuch?"), wird sie hier
    #    abgeschnitten — im Talk-Zug gehoert der Mund dem Thema.
    #    Leergelaufene Antworten fallen weiter unten in den Frage-Rueckfall.
    if floor == gespraech.TALK and t:
        fid_talk = _s(s.get("frage"))
        kern_talk = _FRAGE_KERN.get(fid_talk)
        if fid_talk and kern_talk:
            saetze = _SATZ_ENDE_RE.split(t)
            while len(saetze) > 1 and saetze[-1].rstrip().endswith("?") \
                    and re.search(kern_talk, saetze[-1], re.I):
                saetze.pop()
            gekuerzt = " ".join(x for x in saetze if x).strip()
            if gekuerzt:
                t = gekuerzt
        return _entdoppelt(t)
    fid = _s(s.get("frage"))
    kern = _FRAGE_KERN.get(fid)
    if fid and kern and not re.search(kern, t, re.I):
        saetze = _SATZ_ENDE_RE.split(t)
        if saetze and saetze[-1].rstrip().endswith("?"):
            saetze = saetze[:-1]  # fremde Frage weicht der offenen Frage
        frage = _kanonische_frage(sit, fid)
        if frage:
            t = " ".join([x for x in saetze if x] + [frage]).strip()
    # Wiederholungs-Wächter: kam genau dieser Wortlaut (Anker ODER Modell)
    # schon in den letzten Antworten vor, wird die Frage umformuliert bzw.
    # der doppelte Satz gestrichen (live 27.08.: "Wie ist Ihre Handynummer?"
    # kam dreimal in Folge).
    t = _wiederholungs_wache(sit, t)
    if not t:
        fid2, frage2 = gehirn.naechste_frage(sit)
        if fid2:
            s["frage"] = fid2
            return frage2
        return "Was kann ich sonst noch für Sie tun?"
    return t


def _fluss_sync(sit: dict, gelaufen: list[str], book: dict | None) -> None:
    """Hat das LLM selbst gebucht/abgesagt/verschoben, zieht die Zustands-
    maschine nach. Live 27.08. 14:53: das LLM buchte (nach 'Jap, bitte'),
    die Maschine blieb auf 'bestaetigen' — fragte NACH der Buchung erneut
    'Soll ich eintragen?' und buchte nach dem 'Ja' ein zweites Mal."""
    if not gelaufen:
        return
    s = sit.get("sammler") or {}
    if "book_slot" in gelaufen and book and (book.get("booked") or book.get("dryRun")):
        s["phase"] = "gebucht"
        s["frage"] = ""
        if _s(book.get("slotIso")):
            s["slotIso"] = _s(book.get("slotIso"))
    if "cancel_appointment" in gelaufen and (sit.get("lastCancel") or {}).get("ok"):
        s["modus"] = ""
        s["phase"] = "fertig"
        s["frage"] = ""
        sit["gefundenKey"] = ""
        sit["offered"] = []
    if "move_appointment" in gelaufen and (sit.get("lastMove") or {}).get("ok"):
        s["modus"] = ""
        s["phase"] = "fertig"
        s["frage"] = ""
        sit["gefundenKey"] = ""
        sit["offered"] = []
        sit["verschiebRichtung"] = ""


def _termine_zeile(sit: dict) -> str:
    up = sit.get("upcoming") or []
    if not up:
        return ""
    return "Kommend: " + "; ".join(x.get("label") or "" for x in up[:4] if isinstance(x, dict))


def _job_aktiv(sit: dict) -> bool:
    """Laeuft gerade eine Buchung/Verwaltung (dann zaehlt Ernte als Task)?"""
    s = sit.get("sammler") or {}
    return (s.get("modus") in {"buchen", "absagen", "verschieben", "auskunft"}
            and s.get("phase") not in {"gebucht", "fertig"})


def _offene_frage(sit: dict) -> str:
    """Die offene Pflichtfrage des Sammlers als Satz — '' wenn keine offen."""
    s = sit.get("sammler") or {}
    fid = _s(s.get("frage"))
    return _kanonische_frage(sit, fid) if fid else ""


def system_prompt_aktuell(sit: dict, plan: str = "") -> str:
    tenant = sit["tenant"]
    return system_prompt(
        praxis=_s(tenant.get("praxisName")),
        behandler=_s(tenant.get("behandler")),
        sprache=_s(tenant.get("sprache")) or "de",
        status=flow.status_zeile(sit),
        termine_text=_termine_zeile(sit),
        slots_text=slots_zeile(sit.get("offered") or []),
        wissen=tenant.get("wissen"),
        plan=plan,
    )


def start_reply(sit: dict) -> dict[str, Any]:
    tenant = sit["tenant"]
    text = begruessung(_s(tenant.get("praxisName")))
    sit["messages"] = [
        {"role": "system", "content": system_prompt_aktuell(sit)},
        {"role": "user", "content": "(Ein Anrufer ist in der Leitung. Du hast dich gerade gemeldet.)"},
        {"role": "assistant", "content": text},
    ]
    return {"text": text, "book": None}


def user_turn(sit: dict, spoken: str, melde=None, vorab=None) -> dict[str, Any]:
    text_in = _s(spoken)
    if not text_in:
        return {"text": "", "book": None}
    stille.reset(sit)  # der Anrufer spricht wieder — Stille-Stupse von vorn
    msgs = list(sit.get("messages") or [])
    if not msgs:
        return start_reply(sit)
    msgs.append({"role": "user", "content": text_in})

    # 1) Deterministischer Buchungsfluss — antwortet ohne Modell, also sofort.
    fl = flow.zug(sit, text_in, melde)
    job_sprach = bool(fl and _s(fl.get("text")))
    # Talk-Schicht hoert JEDEN Satz ab (Themen, Gravity, Floor) — am
    # Sammler/Fluss aendert sie nichts, sie entscheidet nur, wie frei das
    # LLM gleich sprechen darf und ob der Frage-Anker feuert.
    route = gespraech.routen(
        sit, text_in,
        ernte=sit.pop("ernteZuletzt", []) or [],
        job_gesprochen=job_sprach,
        job_aktiv=_job_aktiv(sit),
    )
    if job_sprach:
        # Wiederholungs-Wächter auch für die Maschine: fragt der Fluss die
        # noch offene Frage erneut (z. B. weil der Anrufer erst etwas anderes
        # beantwortet hat), kommt sie in der nächsten Formulierung — nie
        # zweimal wortgleich (Chef 27.08.2026). Nie stumm: bleibt nichts
        # übrig, spricht der Originaltext.
        fl["text"] = _wiederholungs_wache(sit, fl["text"]) or fl["text"]
        if "?" in fl["text"]:
            sit["flussFrage"] = fl["text"].rsplit("?", 1)[0].split(". ")[-1].strip() + "?"
        msgs.append({"role": "assistant", "content": fl["text"]})
        sit["messages"] = msgs
        gespraech.nach_antwort(sit)
        return {"text": fl["text"], "book": fl.get("book")}

    # 2) Modell-Pfad: Stand der Buchung + Gespraechslage frisch in den Prompt.
    plan = gespraech.plan_block(route, offene_frage=_offene_frage(sit), stimme="bianca")
    if msgs and msgs[0].get("role") == "system":
        msgs[0]["content"] = system_prompt_aktuell(sit, plan=plan)
    # Kein Stream-Vorab, solange Buchung ODER Verwaltung offen ist: die Wachen
    # unten (_nachbessern) duerfen den Text noch umbauen — ein schon
    # gesprochener erster Satz waere dann falsch. Nur freies Geplauder streamt.
    s = sit.get("sammler") or {}
    mitten_drin = s.get("modus") in {"buchen", "absagen", "verschieben"} and s.get("phase") not in {"gebucht", "fertig"}
    darf_vorab = vorab is not None and not mitten_drin
    werkzeuge_vorher = len(sit.get("tools") or [])
    # Weg-/Anfahrtsfragen: einzige erlaubte Langtext-Antwort — Limit anheben,
    # sonst reisst der Anfahrtstext mitten im Wort ab (E2E 27.08.2026).
    extra = {"max_tokens": kern_wissen.LANGTEXT_MAX_TOKENS} if kern_wissen.braucht_langtext(text_in) else {}
    # Talk-/Brueckenzuege duerfen laenger und waermer sein als Job-Zuege.
    for k, v in gespraech.budget(route["floor"]).items():
        if k == "max_tokens":
            extra[k] = max(int(extra.get(k) or 0), int(v))
        else:
            extra[k] = v
    if darf_vorab:
        out = llm.chat_stream(msgs, TOOLS, erster_satz=vorab, **extra)
    else:
        out = llm.chat(msgs, TOOLS, **extra)
    if not out.get("ok"):
        return {
            "text": "Entschuldigung, da ist mir gerade etwas dazwischengekommen. Was darf ich für Sie tun?",
            "error": out.get("error"),
            "book": None,
        }
    text, msgs, book = zuege.apply_tools(sit, msgs, out, melde=melde)
    gelaufen = [_s(w.get("name")) for w in (sit.get("tools") or [])[werkzeuge_vorher:]]
    werkzeug_lief = bool(gelaufen)
    _fluss_sync(sit, gelaufen, book)
    bewacht = _nachbessern(sit, text, melde, werkzeug_lief=werkzeug_lief, floor=route["floor"])
    if bewacht != text:
        if msgs and msgs[-1].get("role") == "assistant":
            msgs[-1]["content"] = bewacht
        text = bewacht
    sit["messages"] = msgs
    gespraech.nach_antwort(sit)
    return {"text": text, "book": book}


def hangup(sit: dict) -> dict[str, Any]:
    return zuege.auto_notiz(sit, force=True)
