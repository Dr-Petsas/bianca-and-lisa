"""Biancas Zug-Logik: Zustandsmaschine zuerst, Sprachmodell nur als Beifahrer.

Jeder Anrufer-Satz geht durch flow.zug() — deterministisch, ohne Modell-Latenz.
Nur wenn der Fluss abgibt (Zwischenfrage, Absage/Verschieben, Smalltalk),
übernimmt das Modell mit dem Buchungs-Stand im Prompt und denselben
Kalender-Werkzeugen wie Lisa (kern.zuege).
"""

from __future__ import annotations

import re
import time
from typing import Any

from bianca import anstand, flow, gehirn, session, tasks, telefon
from bianca.greeting import begruessung, gruss_saeubern
from bianca.prompt import TOOLS, system_prompt
from kern import antwort_wache, fakten_wache, gedaechtnis, gespraech, hirn, intent, llm, stille, task_router, tenants, wiederholung, zuege
from kern import spur
from kern import wissen as kern_wissen
from kern.calendar import slots_zeile
from kern.patients import arzt_sprechname


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


# Denk-Pause: Anrufer signalisiert Nachdenken — Stups kurz unterdrücken
# (phone_agent skip_turn, W-STUPS-PRESENCE 01.09.2026).
_DENK_RE = re.compile(
    r"^\s*(?:(?:einen?\s+)?moment|augenblick|"
    r"(?:lassen?\s+(?:sie\s+)?mich\s+)?(?:kurz\s+)?(?:überleg\w*|ueberleg\w*)|"
    r"warte(?:n)?(?:\s+(?:sie|mal|kurz))*|"
    r"ich\s+(?:muss|will)\s+(?:kurz\s+)?(?:nach)?denk\w*|"
    r"kurz(?:\s+mal)?)"
    r"(?:\s+\w+){0,4}[\s.,!?…]*$",
    re.I,
)
_DENK_PAUSE_S = 7.0

# --- Wachen für den LLM-Pfad -------------------------------------------------
# Live 27.08.2026: Das Modell ERFAND Terminangebote ("Mittwoch, den 24. Juli,
# um 09:30 Uhr" — in der Vergangenheit!), obwohl kein einziger echter Slot
# geladen war, und stellte eigene Fragen statt der offenen Sammler-Frage.

_ANGEBOT_VERB_RE = re.compile(
    r"\bbiete|\banbieten|\bhätte\b|\bhaette\b|\bfrei\b|\bvorschlag|\bschlage\b|"
    # Live 29.08.2026: "Ich habe hier gerade einen Termin am Mittwoch ...
    # Passt das für Sie?" umging die Wache ("habe" statt "hätte", "passt
    # das" statt "passt Ihnen") — der Slot war erfunden.
    r"\bhabe\s+(?:hier\s+|gerade\s+|noch\s+|da\s+)*einen?\s+termin|"
    r"\bpasst\s+(?:ihnen|das|der|er|es)\b|"
    r"\bw(?:ä|ae)re\b[^.!?]{0,40}?(?:m(?:ö|oe)glich|verf(?:ü|ue)gbar)",
    re.I,
)
# Kurz-Laut ohne Inhalt ("Hm.", "Ähm", "Well." als STT-Artefakt): kein
# Gesprächszug — statt einer langen LLM-Grundsatzrede kommt der Stille-Stups
# (Stand + offene Frage, gedeckelt). Live 29.08.2026: zwei "Hm."/"Well."
# ergaben zwei fast identische ~4-s-Meta-Reden. "Ja"/"Nein"/"Okay" bleiben
# echte Antworten und stehen hier bewusst NICHT drin.
_NUR_LAUT_RE = re.compile(
    r"^\s*(?:hm+|mhm+|hmm+|ähm*|aehm*|äh+|aeh+|ehm+|öhm*|oehm*|"
    r"tja+|na\s*ja|well|puh+|hach+|oh(?:je)?)"
    r"[\s.,!?…]*$",
    re.I,
)
# Nach „Sind Sie noch dran?“: Ja / „ich bin noch dran“ ist KEIN Buchungs-Ja
# (Thaler 08.09.2026: Presence-Schleife statt offener Änderungsfrage).
_PRESENCE_ANTWORT_RE = re.compile(
    r"ich\s+bin\s+noch\s+(?:da|dran)|noch\s+dran|sind\s+sie\s+noch",
    re.I,
)
_NUR_JA_RE = re.compile(r"^\s*ja[\s.,!?…]*$", re.I)
_TERMIN_EINWORT_RE = re.compile(
    r"^\s*(?:ein(?:en)?\s+)?termine?[\s.,!?…]*$",
    re.I,
)
_TERMIN_EINWORT_AKTIONEN: tuple[tuple[re.Pattern, str], ...] = (
    (
        re.compile(r"\b(?:neu\w*|buch\w*|vereinbar\w*|ausmach\w*)\b", re.I),
        "Ich möchte einen neuen Termin vereinbaren.",
    ),
    (
        re.compile(r"\b(?:verschieb\w*|verleg\w*|änder\w*|aender\w*)\b", re.I),
        "Ich möchte meinen Termin verschieben.",
    ),
    (
        re.compile(r"\b(?:absag\w*|storn\w*|lösch\w*|loesch\w*|streich\w*)\b", re.I),
        "Ich möchte meinen Termin absagen.",
    ),
    (
        re.compile(r"\b(?:auskunft|nachseh\w*|prüf\w*|pruef\w*|wann)\b", re.I),
        "Ich möchte wissen, wann mein Termin ist.",
    ),
)
TERMIN_EINWORT_FRAGE = (
    "Gerne. Möchten Sie einen neuen Termin vereinbaren, "
    "einen Termin verschieben oder einen Termin absagen?"
)
TERMIN_EINWORT_NACHFRAGE = (
    "Was möchten Sie mit dem Termin tun: neu vereinbaren, verschieben oder absagen?"
)
_TERMIN_EINWORT_UNKLAR_RE = re.compile(
    r"^\s*(?:ja|nein|okay|ok|weiß\s+nicht|weiss\s+nicht|keine\s+ahnung|"
    r"(?:ein(?:en)?\s+)?termine?)[\s.,!?…]*$",
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
    "arzt": r"behandler|arzt|ärztin|aerztin|doktor|prophylaxe|thaler",
    # auch "Vor- und Nachname": dort steht kein alleinstehendes "Name"
    "name": r"\bnamen?\b|vorname|nachname",
    "vorname": r"vorname",
    "nachname": r"nachname",
    "grund": r"worum|grund|anliegen|kontrolle",
    "wunsch": r"\bwann\b|vormittag|nachmittag|uhrzeit",
    # Verwaltungs-Fragen (W-SAMMELN): Wann-/Behandlungs-Frage zum Bestandstermin.
    "wann": r"\bwann\b|uhrzeit|wochentag",
    "behandlung": r"behandlung|kontrolle|zahnreinigung",
    "neubuchung": r"neuen?\s+termin",
    "buchstabieren": r"buchstabier",
    "telefon": r"nummer|handy|telefon",
    "telefon_check": r"nummer|stimmt",
    # Erkannte Identität und Terminempfänger sind getrennte Ja/Nein-Schritte.
    "anrufer_check": r"erkannt|richtige\s+person",
    "fuer_wen_check": r"selbst|persönlich|persoenlich",
    "arzt_check": r"zuletzt|behandler|richtig",
    "telefon_alt": r"nummer|alte|akte|löschen",
    "slotwahl": r"\buhr\b|termin.{0,30}passt|welcher",
    "bestaetigung": r"eintragen|so\s+buchen|festhalten",
    "aenderung": r"ändern|aendern|korrigier|zeitpunkt|name|nummer|grund|besuchsgrund",
    "versicherung": r"privat|gesetzlich|versichert",
    "versicherung_check": r"privat|gesetzlich|versichert|geändert|geaendert",
    "pzr": r"zahnreinigung|prophylaxe|\bpzr\b",
    "pzr_kasse": r"krankenkasse|versichert|kasse",
    "termin_anbieten": r"termin|zahnreinigung|brauchen",
    "arzt_notiz": r"notiz|doktor|besondere\s+frage|eingehen",
    "arzt_notiz_diktat": r"doktor|mitgeben|notiz",
    # W-BLEACHING (Chef 03.09.2026): Aufhellungs-Angebot + Zahnersatz-Check.
    "bleaching": r"aufhell|bleach|zahnaufhellung",
    "bleaching_check": r"krone|brücke|bruecke|veneer|implantat|zahnersatz",
    "rueckblick": r"seither|beruhigt|ergangen|zufrieden|verheilt|immer\s+noch|letzten?\s+besuch|letztes\s+mal",
    "folge_kontrolle": r"kontrolle\s+buch|kontrolle\s+eintrag",
    "frisch_absage_ok": r"absagen|stornier|wirklich",
    "absage_ok": r"absagen|stornier|wirklich",
}
_SATZ_ENDE_RE = re.compile(r"(?<=[.!?…])\s+")

# Wiederhol-Wache (Chef 27.08.2026: "wenn der String Behandler im Gehirn
# gefüllt ist, ist der Wert halt da — fertig"): Fragen des Modells nach
# Feldern, die der Sammler LÄNGST hat, werden gestrichen. Der Frage-Anker
# hängt danach die wirklich offene Frage an.
_GEFUELLT_WACHEN: list[tuple[re.Pattern, Any]] = [
    (re.compile(r"handynummer|telefonnummer|welcher\s+nummer|ihre\s+nummer", re.I),
     lambda s: bool(s.get("telefonOk") or s.get("telefonAkte"))),
    (re.compile(r"bei\s+(welchem|wem)|welche[rm]?\s+(behandler|arzt|ärztin|aerztin)|zu\s+welchem\s+(arzt|behandler)|frau\s+thaler\s+oder|zur\s+prophylaxe", re.I),
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
    if fid == "pzr":
        # Weiche Zusatzfrage (30.08.2026) — naechste_frage kennt sie nicht,
        # der Anker soll sie nach einer LLM-Antwort trotzdem zurueckholen.
        return gehirn.pzr_frage(sit.get("sammler") or {})
    if fid == "pzr_kasse":
        from kern import pzr_kassen
        return pzr_kassen.KASSE_FRAGE
    if fid == "folge_kontrolle":
        return gehirn.folge_kontrolle_frage()
    if fid == "rueckblick":
        return gehirn.rueckblick_text(sit.get("sammler") or {}, sit)
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
    varianten = gehirn.FRAGE_VARIANTEN
    if fid == "arzt":
        from kern import zimmer_map
        if zimmer_map.aktiv(sit.get("tenant") or {}):
            varianten = {**varianten, "arzt": gehirn.THALER_SPUR_VARIANTEN}
        elif s.get("warSchonMal") is False:
            # Neupatient: die Behandler-WAHL wiederholen, nicht "bei wem waren
            # Sie zuletzt?" — der Anrufer war ja noch nie da.
            varianten = {**varianten, "arzt": gehirn.ARZTWAHL_VARIANTEN}
    return wiederholung.pruefen(
        sit, text,
        frueher=wiederholung.letzte_antworten(sit.get("messages") or []),
        frage_id=fid,
        frage_kern=_FRAGE_KERN.get(fid, ""),
        varianten=varianten,
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
    "aenderung": "was ich ändern soll — Zeitpunkt, Name, Nummer oder Besuchsgrund",
    "pzr": "ob die Zahnreinigung mit dazu soll",
    "bleaching": "ob die Zähne mit aufgehellt werden sollen",
    "bleaching_check": "ob Sie vorne Zahnersatz haben — Kronen, Brücken, Veneers oder Implantate",
    "versicherung": "Ihr Versichertenstatus — privat oder gesetzlich",
    "versicherung_check": "ob sich Ihre Versicherung geändert hat",
    "anrufer_check": "ob ich Sie richtig erkannt habe",
    "fuer_wen_check": "ob der Termin für Sie selbst ist",
    "rueckblick": "wie es nach dem letzten Besuch war",
    "folge_kontrolle": "ob eine Kontrolle gebucht werden soll",
}


def _wiederholung_oder_presence(sit: dict, text: str) -> str:
    """Wiederholungs-Wächter ohne wortgleiches Restore (W-REPEAT 01.09.2026).

    phone_agent stellte nie dieselbe Frage erneut; wenn Varianten verbrannt
    sind, bleibt Presence statt dem Original — nie `or text`.
    """
    raus = _wiederholungs_wache(sit, text)
    if raus:
        return antwort_wache.saeubern(sit, raus)
    # Alles war Wiederholung und keine Variante frei: Presence, nicht Original.
    if _s(text):
        return stille.anrede(1)
    return ""


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
        if fehlt and not frage:
            # "Mir fehlt noch X. Welche X ...?" ist doppelt gemoppelt —
            # der Fehlt-Satz kommt nur, wenn keine Frage folgt (W-STUPS-KURZ).
            teile.append(f"Mir fehlt noch {fehlt}.")
        if frage:
            teile.append(frage)
        return " ".join(teile)
    return "Kann ich sonst noch etwas für Sie tun?"


def stille_zug(sit: dict) -> dict[str, Any]:
    """Stille-Wächter (Chef 27.08.2026): der Anrufer sagt seit ~4 Sekunden
    nichts — Bianca ergreift selbst das Wort, statt stumm zu warten.

    - W-STUPS-PRESENCE (01.09.2026, phone_agent): der ERSTE Stups ist nur
      Presence („Sind Sie noch dran?“) — keine Pflichtfrage. Der ZWEITE
      bringt die kurze Frage-Variante. Kein Stand-Sermon auf dem Stups-Pfad
      (außer telefon_check #2 mit Ziffern).
    - Denk-Cue („Moment“, „überlegen“): kurze Pause ohne Stups.
    - Nach MAX_STUPSE Stupsen ohne Antwort: Schweigen, bis der Anrufer
      wieder spricht (user_turn setzt den Zähler zurück).
    """
    if time.time() < float(sit.get("denkPauseBis") or 0):
        return {"text": "", "book": None}

    n = stille.stups_zaehlen(sit)
    if n > stille.MAX_STUPSE:
        return {"text": "", "book": None}
    s = sit.get("sammler") or {}
    fid = _s(s.get("frage"))

    # Nummern-Rückbestätigung bleibt IMMER deterministisch. Aber die Ziffern
    # kamen erst Sekunden vorher — der erste Stups fragt nur kurz nach, erst
    # der zweite wiederholt die komplette Nummer (W-STUPS-KURZ).
    if fid == "telefon_check" and _s(s.get("telefonOffen")):
        if n <= 1:
            text = f"{stille.anrede(n)} Stimmt die Nummer so, wie ich sie vorgelesen habe?"
        else:
            text = f"{stille.anrede(n)} {gehirn.readback_text(s['telefonOffen'])}"
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

    if n <= 1:
        # Presence only — phone_agent hat auf Silence nie die Pflichtfrage
        # wiederholt (W-STUPS-PRESENCE 01.09.2026).
        text = stille.anrede(n)
        stille.anhaengen(sit, text)
        return {"text": text, "book": None}

    # Zweiter Stups: kurze offene Frage (Variante), kein Stand-Sermon.
    frage = stille.nur_fragesaetze(_kanonische_frage(sit, fid)) if fid else ""
    if not frage and _s(sit.get("flussFrage")):
        frage = stille.nur_fragesaetze(sit["flussFrage"])
    if not frage:
        frage = "Kann ich sonst noch etwas für Sie tun?"
    text = " ".join([stille.anrede(n), frage])
    ent = _wiederholungs_wache(sit, text)
    if ent and "?" in ent:
        text = antwort_wache.saeubern(sit, ent)
    elif frage:
        # Frage war schon wortgleich da — mit Präfix, nie Original-Restore.
        text = f"{stille.anrede(n)} {stille.frage_praefix(frage)}"
    else:
        text = stille.anrede(n)
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
        # Wiederholungs-Wächter als letzte Instanz VOR dem Mund — nie das
        # Original zurückholen, wenn alles gestrichen wurde (W-REPEAT).
        return _wiederholung_oder_presence(sit, aus)

    # 0) Erledigt-Wache: "ich sage den Termin ab" / "ist verschoben" ohne
    #    Werkzeuglauf ist eine leere Behauptung (live 27.08.: beide Termine
    #    standen noch im Kalender). Zurueck zur letzten offenen Fluss-Frage.
    if not werkzeug_lief and _ERLEDIGT_RE.search(t):
        if s.get("modus") in {"absagen", "verschieben"}:
            zurueck = _s(sit.get("flussFrage")) or "Um welchen Termin geht es denn genau?"
            return _entdoppelt("Da will ich nichts falsch machen — das mache ich erst nach Ihrer Bestätigung. " + zurueck)
        # Frisch gebucht: LLM behauptet "Der Termin ist storniert" ohne Tool
        # (live 02.09. Tzannis) — Rueckfrage, beim Ja cancel_appointment.
        if s.get("phase") == "gebucht" and flow._frisch_termin(sit):
            s["frage"] = "frisch_absage_ok"
            return _entdoppelt(
                "Da will ich nichts falsch machen — soll ich den Termin wirklich absagen?"
            )

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


def _einwort_termin_vorbereiten(sit: dict, text: str) -> tuple[str, str]:
    """Mehrdeutiges „Termin“ klaeren, ohne das LLM eine Absicht raten zu lassen.

    Rueckgabe: (Text fuer Intent/Flow, direkte Rueckfrage). Eine Antwort auf
    die Rueckfrage wird in einen eindeutigen Satz erweitert. Offene Formular-
    schritte bleiben unangetastet: Dort kann ein einzelnes Wort die erwartete
    Antwort sein und darf nie von dieser allgemeinen Klaerung ueberholt werden.
    """
    t = _s(text)
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    offen = bool(_s(s.get("frage")) or _job_aktiv(sit))

    if sit.get("einwortTerminOffen"):
        if offen:
            sit.pop("einwortTerminOffen", None)
            return t, ""
        treffer = [satz for muster, satz in _TERMIN_EINWORT_AKTIONEN if muster.search(t)]
        if len(treffer) == 1:
            sit.pop("einwortTerminOffen", None)
            spur.merken(sit, "einwort-termin", t[:40])
            return treffer[0], ""
        if _TERMIN_EINWORT_UNKLAR_RE.match(t):
            return t, TERMIN_EINWORT_NACHFRAGE
        # Ein anderes belastbares Einzelwort („Mitarbeiter“,
        # „Zahnreinigung“ ...) ist ein Themenwechsel und geht normal durch
        # Intent/Flow. Die alte Terminfrage darf es nicht festhalten.
        sit.pop("einwortTerminOffen", None)
        return t, ""

    if not offen and _TERMIN_EINWORT_RE.match(t):
        sit["einwortTerminOffen"] = True
        spur.merken(sit, "einwort-termin-unklar", t[:40])
        return t, TERMIN_EINWORT_FRAGE
    return t, ""


def _offene_frage(sit: dict) -> str:
    """Die offene Pflichtfrage des Sammlers als Satz — '' wenn keine offen."""
    s = sit.get("sammler") or {}
    fid = _s(s.get("frage"))
    return _kanonische_frage(sit, fid) if fid else ""


def _behandler_alle(tenant: dict) -> str:
    """Alle Behandler des Standorts (Kalender-Namen), Haupt-Behandler zuerst —
    fuer Auskunftsfragen ("Welche Ärzte arbeiten da?"). Live 29.08.2026:
    das LLM kannte nur den einen behandler-Eintrag und verschwieg den Rest.
    Reihenfolge seit 03.09.2026: kern.tenants.behandler_reihe (Chef:
    "Dr. Petsas, Dr. Patrikis oder Dr. Nikolaou" — nie andersherum)."""
    haupt = arzt_sprechname(_s(tenant.get("behandler")), tenant)
    namen = [haupt] if haupt else []
    for k in tenants.behandler_reihe(tenant):
        n = arzt_sprechname(_s((k or {}).get("name")), tenant)
        if n and n not in namen:
            namen.append(n)
    return ", ".join(namen)


def system_prompt_aktuell(sit: dict, plan: str = "") -> str:
    tenant = sit["tenant"]
    return system_prompt(
        praxis=_s(tenant.get("praxisName")),
        behandler=_s(tenant.get("behandler")),
        behandler_alle=_behandler_alle(tenant),
        sprache=_s(tenant.get("sprache")) or "de",
        status=flow.status_zeile(sit),
        termine_text=_termine_zeile(sit),
        slots_text=slots_zeile(sit.get("offered") or []),
        wissen=tenant.get("wissen"),
        sit=sit,
        plan=plan,
        kontext=gedaechtnis.kontext_block(sit),
        # W-MANDANT: Agent-Prompt aus der Pickadoc-DB (Praxis-Fakten) —
        # mehrzeilig, deshalb NICHT durch _s (das wuerde die Absaetze platten).
        db_prompt=str(tenant.get("dbPrompt") or ""),
    )


def _letzte_war_presence(sit: dict) -> bool:
    for m in reversed(sit.get("messages") or []):
        if m.get("role") != "assistant":
            continue
        t = _s(m.get("content")).casefold()
        return "noch dran" in t or "ich bin noch da" in t
    return False


def start_reply(sit: dict) -> dict[str, Any]:
    tenant = sit["tenant"]
    # W-MANDANT: CF-Mandanten ohne kuratierte Datei melden sich mit der in
    # der Pickadoc-DB gepflegten Begruessung (agent.firstMessage).
    text = _s(tenant.get("begruessungText")) or begruessung(tenants.praxis_melde(tenant))
    # W-MEDDENT (04.09.2026): Live-Bug „Wem kann ich für Sie tun?“ — TTS/DB.
    text = gruss_saeubern(text)
    # Fast-Pfad: Name aus der Rufnummer ist oft schon da. Hallo waermen
    # und letzten Besuch/Behandler nachziehen — parallel zur Begruessung,
    # nie auf dem Mund-Pfad.
    from bianca import hintergrund as _hg
    _hg.gespraech_von_anrufer(sit)
    _hg.hallo_waermen(sit)
    _hg.kartei_von_anrufer(sit)
    # Praxisgedächtnis schon zur Begrüßung — der Rückrufer fragt oft im
    # ersten Satz nach dem Grund (Herbst 08.09.: Notiz lag 2 min vorher).
    gedaechtnis.kontext_anstossen(sit)
    sit["messages"] = [
        {"role": "system", "content": system_prompt_aktuell(sit)},
        {"role": "user", "content": "(Ein Anrufer ist in der Leitung. Du hast dich gerade gemeldet.)"},
        {"role": "assistant", "content": text},
    ]
    return {"text": text, "book": None}


def _fakten_wache_anwenden(
    sit: dict, text: str, *, nutzertext: str | None = None
) -> str:
    """W-FAKTEN-WACHE (09.09.2026): evidenzbasierte Erledigt-Wache auf dem
    LLM-Pfad. off: nichts. shadow: nur Waechterspur. enforce: unbelegte
    Erledigt-Behauptung durch eine ehrliche Absicherung + offene Frage
    ersetzen (Wahrheit = Tool-Ledger, nicht LLM-Text)."""
    m = fakten_wache.modus()
    if m == "off" or not _s(text):
        return text
    unbelegt = fakten_wache.unbelegte_behauptung(
        sit, text, nutzertext=nutzertext)
    if not unbelegt:
        return text
    if m == "shadow":
        spur.merken(sit, "fakten-wache-shadow", unbelegt)
        return text
    spur.merken(sit, "fakten-wache", unbelegt)
    s = sit.get("sammler") or {}
    fid, frage = gehirn.naechste_frage(sit)
    if fid:
        s["frage"] = fid
    hedge = {
        "slots": "Das kann ich ohne eine echte Kalendersuche nicht sicher sagen.",
        "bestand": "Ob ein Termin besteht, sage ich erst nach einer echten Kalendersuche.",
        "sms": "Eine Bestätigungs-SMS kann ich erst nach einer bestätigten Buchung zusagen.",
        "rueckruf": "Einen Rückruf habe ich noch nicht angelegt.",
        "transfer": "Eine Weiterleitung habe ich noch nicht gestartet.",
    }.get(
        unbelegt,
        "Da will ich nichts falsch machen — das ist noch nicht erledigt.",
    )
    return _wiederholung_oder_presence(sit, " ".join(x for x in [hedge, frage] if x).strip())


def _auto_resume_anhaengen(sit: dict, fl: dict) -> dict:
    """W-HIRN-AUTORESUME (09.09.2026): hat die Maschine gerade ein
    eingeschobenes Anliegen abgeschlossen und liegt ein geparktes davor,
    EINMAL kurz zurueckfuehren — Rueckkehrbruecke + gespeicherte Pflichtfrage.

    off: nichts. shadow: nur die Waechterspur, kein Verhaltenswechsel.
    enforce: Checkpoint des geparkten Anliegens zurueck, Bruecke + Frage.
    Nie mitten in Buchung/Transfer/Diktat (book/hangup/transfer/warte).
    """
    if "hirn" not in sit or not intent.enabled():
        return fl
    modus = hirn.auto_resume_modus()
    if modus == "off":
        return fl
    if fl.get("book") or fl.get("hangup") or fl.get("transfer") or fl.get("warte"):
        return fl
    if modus == "shadow":
        ziel = hirn.wuerde_zuruecksprigen(sit)
        if ziel:
            spur.merken(sit, "auto-resume-shadow", _s(ziel.get("id")))
        return fl
    resumed = hirn.abschluss_ruecksprung_live(sit)
    if not resumed:
        return fl
    spur.merken(sit, "auto-resume", _s(resumed.get("id")))
    s = sit.get("sammler") or {}
    fid = _s(s.get("frage"))
    frage = _kanonische_frage(sit, fid) if fid else ""
    if not frage:
        fid2, frage2 = gehirn.naechste_frage(sit)
        if fid2:
            s["frage"] = fid2
            frage = frage2
    bruecke = hirn.rueckkehr_bruecke(resumed)
    fl = dict(fl)
    fl["text"] = " ".join(x for x in [_s(fl.get("text")), bruecke, frage] if x)
    return fl


def _maschinen_antwort(sit: dict, fl: dict, msgs: list[dict]) -> dict[str, Any]:
    """Einheitlicher Abschluss für direkten Flow und semantischen Handoff."""
    fl = _auto_resume_anhaengen(sit, fl)
    if _s(fl.get("text")):
        if fl.pop("_wiederholungErlaubt", False):
            # Explizite Nutzerbitte „Wiederhole den Termin“: Datum/Uhrzeit
            # muessen erneut hoerbar sein. Nur die allgemeinen Antwort-Wachen
            # bleiben aktiv; der Entdoppler darf diesen Inhalt nicht streichen.
            fl["text"] = antwort_wache.saeubern(sit, fl["text"])
        else:
            fl["text"] = _wiederholung_oder_presence(sit, fl["text"])
        if "?" in fl["text"]:
            sit["flussFrage"] = fl["text"].rsplit("?", 1)[0].split(". ")[-1].strip() + "?"
        msgs.append({"role": "assistant", "content": fl["text"]})
        wiederholung.gesagt_merken(sit, fl["text"])
    sit["messages"] = msgs
    gespraech.nach_antwort(sit)
    gedaechtnis.kontext_anstossen(sit)
    aus: dict[str, Any] = {"text": _s(fl.get("text")), "book": fl.get("book")}
    if fl.get("warte"):
        # Verwertetes Diktatfragment: Zustand ist fortgeschrieben, aber der
        # Anrufer hat den Turn noch nicht abgegeben. Kein Assistenten-Text,
        # kein LLM und kein Audio — der Dienst reicht nur „weiterhören“ durch.
        aus["warte"] = True
        aus["stilleMs"] = int(fl.get("stilleMs") or 1500)
    if fl.get("hangup"):
        aus["hangup"] = True
    if isinstance(fl.get("transfer"), dict) and fl["transfer"].get("nummer"):
        aus["transfer"] = fl["transfer"]
    return aus


def user_turn(sit: dict, spoken: str, melde=None, vorab=None) -> dict[str, Any]:
    text_in = _s(spoken)
    if not text_in:
        return {"text": "", "book": None}
    if _NUR_LAUT_RE.match(text_in):
        # Kurz-Laut ohne Inhalt: wie Funkstille behandeln (Stups statt
        # LLM-Rede) — bewusst VOR stille.reset, damit der Stups-Deckel
        # (MAX_STUPSE) auch eine "Hm."-Serie beendet.
        return stille_zug(sit)
    stille.reset(sit)  # der Anrufer spricht wieder — Stille-Stupse von vorn
    if _DENK_RE.match(text_in):
        # phone_agent skip_turn: nachdenkende Anrufer nicht anstupsen.
        sit["denkPauseBis"] = time.time() + _DENK_PAUSE_S
        return {"text": "", "book": None}
    sit.pop("denkPauseBis", None)
    # W-GEDAECHTNIS: falls inzwischen Name/Nummer bekannt sind, parallel im
    # Praxisgedaechtnis nachsehen (key-gesichert, no-op ohne neue Fakten).
    gedaechtnis.kontext_anstossen(sit)
    msgs = list(sit.get("messages") or [])
    if not msgs:
        return start_reply(sit)
    msgs.append({"role": "user", "content": text_in})

    # W-HALLO-PAUSE (10.09.2026): Hat Bianca wirklich „Wie geht es Ihnen?“
    # gefragt, war der vorherige Zug absichtlich NUR diese Frage. Jetzt erst
    # den dort geparkten Originalwunsch in die Maschine geben und nach der
    # Wohlseinsantwort mit der fachlichen Pflichtfrage fortfahren.
    if sit.pop("anruferHalloFrageOffen", False):
        original = _s(sit.pop("anruferHalloOffenerText", ""))
        einwort_frage = _s(sit.pop("anruferHalloEinwortFrage", ""))
        identitaet_nein = gehirn.ist_anrufer_identitaet_nein(text_in)
        fl = (
            {"text": einwort_frage, "book": None}
            if einwort_frage
            else (tasks.zug(sit, original, melde) if original else None)
        )
        if (identitaet_nein
                and _s((sit.get("sammler") or {}).get("frage")) == "anrufer_check"):
            # Live 10.09.: Auf „Wie geht es Ihnen?“ kam die wichtigere
            # Korrektur „Ich bin nicht Phoebe Rose Kellner.“. Nicht erst
            # mit „Danke. Habe ich Sie richtig erkannt?“ nachfragen, sondern
            # den falschen DB-Treffer sofort sicher verwerfen.
            ablehnung = tasks.zug(sit, "Nein.", melde)
            if ablehnung:
                fl = ablehnung
        if not fl or not (
            _s(fl.get("text")) or fl.get("hangup")
            or fl.get("transfer") or fl.get("warte")
        ):
            fl = {"text": "Was kann ich für Sie tun?", "book": None}
        else:
            fl = dict(fl)
        quittung = "" if identitaet_nein else gehirn.anrufer_wohl_quittung(text_in)
        fl["text"] = " ".join(x for x in (quittung, _s(fl.get("text"))) if x)
        spur.merken(
            sit,
            "anrufer-hallo-identitaet-nein" if identitaet_nein
            else "anrufer-hallo-pause",
            text_in[:80],
        )
        return _maschinen_antwort(sit, fl, msgs)

    # W-PRAXISAUSKUNFT (09.09.2026): Öffnungszeiten und Wegbeschreibung
    # kommen deterministisch aus dem Mandanten, auch wenn STT Schlüsselwörter
    # verhört ("Pflungszeiten", "wie ich die praktisch erreiche"). Solche
    # Praxisfakten dürfen nie als freies Talk-Thema beim LLM landen — dort
    # entstand live der erfundene Gärtnerei-Witz statt der echten Auskunft.
    praxis_text, praxis_themen = kern_wissen.praxis_antwort(
        sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {},
        text_in,
    )
    if praxis_text:
        offene = _offene_frage(sit)
        if offene:
            praxis_text = f"{praxis_text} {offene}"
        spur.merken(sit, "praxis-auskunft", ",".join(sorted(praxis_themen)))
        sit.pop("unklarFolge", None)
        return _maschinen_antwort(sit, {"text": praxis_text, "book": None}, msgs)

    # Gemischter Zug: „Ja, aber …“ enthält ZWEI Handlungen. Bei wenigen
    # ausdrücklich sicheren Fragen erntet der bisherige Flow zuerst das
    # Ja/Nein; nur der Zusatz geht danach durch Intent und Task-Router.
    # Transaktionskritische Fragen werden in intent.py niemals geteilt.
    arbeits_text = text_in
    # Nach einem Presence-Stups beantwortet das führende „Ja“ nur
    # „Sind Sie noch dran?“ und darf keine Identität bestätigen.
    gemischt = (
        None if _letzte_war_presence(sit)
        else intent.formularantwort_mit_zusatz(sit, text_in)
    )
    if gemischt:
        kurzantwort, zusatz = gemischt
        vorfrage = _s((sit.get("sammler") or {}).get("frage"))
        praefix = flow.zug(sit, kurzantwort, None)
        if praefix is not None and not (
            praefix.get("book") or praefix.get("hangup") or praefix.get("transfer")
        ):
            arbeits_text = zusatz
            spur.merken(sit, "mischzug", f"{vorfrage}: {kurzantwort} + Zusatz")

    arbeits_text, einwort_frage = _einwort_termin_vorbereiten(
        sit, arbeits_text,
    )

    if _letzte_war_presence(sit) and (
        _PRESENCE_ANTWORT_RE.search(text_in) or _NUR_JA_RE.match(text_in)
    ):
        # Presence bestätigt — die offene Pflichtfrage zurück, nie buchen.
        s = gehirn.sammler(sit)
        fid = _s(s.get("frage"))
        frage = _kanonische_frage(sit, fid) if fid else ""
        if not frage and fid:
            formen = gehirn.FRAGE_VARIANTEN.get(fid) or ()
            frage = formen[0] if formen else ""
        if frage:
            msgs.append({"role": "assistant", "content": frage})
            sit["messages"] = msgs
            return {"text": frage, "book": None}

    # 0) Intent-Schicht (W-HIRN/W-INTENT 03.09.2026, Chef: "erst erkennen,
    #    dann handeln"): das Session-Hirn deutet JEDEN Satz, BEVOR eine
    #    Maschine laeuft — synchron IMMER in 0 ms (Fast-Paths + Heuristik).
    #    Das LLM prueft mehrdeutige Saetze im Hintergrund nach; sein
    #    Nachzug vom VORIGEN Satz wird hier zuerst eingearbeitet.
    if "hirn" in sit and intent.enabled() and not einwort_frage:
        hirn.sync_nach_zug(sit)  # Maschinen-Stand vom VORIGEN Zug abgleichen
        spaet = intent.nachzug(sit)
        if spaet is not None:
            hirn.anwenden(sit, spaet)
        deutung = intent.erkennen(sit, arbeits_text)
        hirn.anwenden(sit, deutung)

    # W-ANRUFER-HALLO: den verspielten Satz SOFORT als Vorab-Füller
    # sprechen, während flow + Ziffern-TTS im Hintergrund laufen.
    # Seriell (Hallo, Stille, Nummer) war der hörbare Hänger.
    hallo_fragt = False
    if vorab:
        hallo = gehirn.anrufer_hallo_jetzt(sit, text_in)
        if hallo:
            # Vorab ging am Wächter vorbei (Live 08.09.: Hallo jeden Zug).
            # Kurze Sätze ohne ? sind sonst Quittungen — hier streichen.
            hallo = wiederholung.pruefen(
                sit, hallo,
                frueher=wiederholung.letzte_antworten(sit.get("messages") or []),
                auch_kurz=True,
            )
        if hallo:
            hallo_fragt = gehirn.anrufer_hallo_fragt(hallo)
            vorab(hallo)
            # Die alleinstehende Frage wird gleich über _maschinen_antwort
            # protokolliert. Vorheriges Merken würde denselben Text dort als
            # unerlaubte Wiederholung wieder entfernen.
            if not hallo_fragt:
                wiederholung.gesagt_merken(sit, hallo)
            gehirn.anrufer_hallo_merken(sit)
    if hallo_fragt:
        # Den Fachwunsch nicht verlieren: Intent ist oben bereits gesetzt,
        # der Originalsatz wird nach der Wohlseinsantwort in tasks.zug
        # nachgereicht. Jetzt darf akustisch nichts mehr folgen.
        sit["anruferHalloFrageOffen"] = True
        sit["anruferHalloOffenerText"] = arbeits_text
        if einwort_frage:
            sit["anruferHalloEinwortFrage"] = einwort_frage
        spur.merken(sit, "anrufer-hallo-fragt", hallo)
        return _maschinen_antwort(
            sit, {"text": hallo, "book": None}, msgs,
        )

    if einwort_frage:
        sit.pop("unklarFolge", None)
        return _maschinen_antwort(
            sit, {"text": einwort_frage, "book": None}, msgs,
        )

    # 1) Deterministischer Buchungsfluss — antwortet ohne Modell, also sofort.
    #    W-TASK-GRENZE: transparenter Adapter (bianca/tasks) vor flow.zug —
    #    gleiche Antwort/Werkzeuge, nur ein Task-Ledger obendrauf.
    fl = tasks.zug(sit, arbeits_text, melde)
    if fl is None:
        # Live 08.09.2026: Der Motivkatalog verstand „Besprechung für eine
        # neue Prothese“, aber Intent/LLM eröffneten keinen Buchungs-Task.
        # Das Modell bot daraufhin einen Termin an und fragte frei nach dem
        # Namen — der Namenssammler kannte diese Frage nicht: Endlosschleife.
        # Ein frisch geernteter Praxisgrund PLUS ausdrücklicher Wunsch ist
        # bereits belastbare Evidenz; direkt an den sicheren Flow übergeben.
        sichere_wahl = task_router.aus_sicherer_ernte(
            sit, arbeits_text, sit.get("ernteZuletzt") or [],
        )
        if sichere_wahl and task_router.anwenden(
            sit, sichere_wahl, original=text_in, quelle="sichere_ernte",
        ):
            spur.merken(sit, "task-sichere-ernte", _s(sichere_wahl.get("reason"))[:80])
            fl = flow.zug(sit, arbeits_text, melde)
    if fl is None and not gespraech.wirkt_unklar(text_in):
        # W-ANSTAND (Chef 03.09.2026): Beschimpfung/Fluchen ohne Fach-Anliegen
        # bekommt einen kurzen, charmanten Konter statt des LLM — ein Satz
        # mit echtem Anliegen hat den Fluss oben schon gewonnen.
        # W-MEDDENT: STT-Muell ("Seht, seht!") nie als Beleidigung werten.
        fl = anstand.zug(sit, arbeits_text)
    # W-VERBINDEN-ECHT (31.08.2026): eine echte Weiterleitung spricht ihre
    # Ansage als Filler und traegt text="" — sie ZAEHLT trotzdem als
    # Maschinen-Zug, sonst wuerfe das LLM das transfer-Reply weg (live
    # erlebt: "Zu welchem unserer Ärzte..." statt Durchstellen).
    job_sprach = bool(fl and (_s(fl.get("text")) or fl.get("hangup")
                              or fl.get("transfer") or fl.get("warte")))
    if job_sprach and "Ich bin die Neue!" in _s(fl.get("text")):
        gehirn.anrufer_hallo_merken(sit)
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
        sit.pop("unklarFolge", None)
        return _maschinen_antwort(sit, fl, msgs)

    # W-MEDDENT (04.09.2026): kurzer STT-Muell → nachfragen, kein LLM-Plaudern.
    if route.get("unklar"):
        unklar_folge = int(sit.get("unklarFolge") or 0) + 1
        sit["unklarFolge"] = unklar_folge
        if unklar_folge >= 2:
            # Zweite unverständliche Antwort darf NIE dieselbe Schleife
            # fortsetzen. Liegt aus dem vorherigen Gespräch bereits ein
            # kataloggestützter Besuchsgrund vor, startet jetzt der sichere
            # Task und stellt seine echte Pflichtfrage.
            rettung = task_router.aus_gesammeltem_grund(sit)
            if rettung and task_router.anwenden(
                sit, rettung,
                original=_s((sit.get("sammler") or {}).get("grundWortlaut")),
                quelle="schleifen_ausstieg",
            ):
                spur.merken(sit, "task-schleifen-ausstieg", _s(rettung.get("reason"))[:80])
                talk = sit.get("talk")
                if isinstance(talk, dict):
                    talk.update({
                        "gravity": {}, "woerter": {}, "stack": [],
                        "floor": gespraech.JOB, "bruecke": "", "frisch": [],
                    })
                fl = flow.zug(
                    sit,
                    _s((sit.get("sammler") or {}).get("grundWortlaut")) or text_in,
                    melde,
                )
                if fl and (
                    _s(fl.get("text")) or fl.get("hangup")
                    or fl.get("transfer") or fl.get("warte")
                ):
                    sit.pop("unklarFolge", None)
                    return _maschinen_antwort(sit, fl, msgs)
        if not sit.get("ganzsatzHinweisGegeben"):
            sit["ganzsatzHinweisGegeben"] = True
            text = gespraech.UNKLAR_ANTWORT
        else:
            text = gespraech.UNKLAR_AUSWAHL_ANTWORT
        msgs.append({"role": "assistant", "content": text})
        sit["messages"] = msgs
        wiederholung.gesagt_merken(sit, text)
        gespraech.nach_antwort(sit)
        return {"text": text, "book": None}
    sit.pop("unklarFolge", None)

    # 2) Modell-Pfad: Stand der Buchung + Gespraechslage frisch in den Prompt.
    plan = gespraech.plan_block(route, offene_frage=_offene_frage(sit), stimme="bianca")
    # W-HIRN: das erkannte Anliegen steht im Prompt — das Modell antwortet
    # passend zur Handlung (ERREICHEN/WISSEN/ABGEBEN ...) statt zu buchen.
    anliegen_stand = hirn.stand_block(sit)
    if anliegen_stand:
        plan = f"{plan}\n\n{anliegen_stand}" if plan else anliegen_stand
    task_auswahl = task_router.braucht_auswahl(sit)
    if task_auswahl:
        task_plan = task_router.prompt(sit)
        plan = f"{plan}\n\n{task_plan}" if plan else task_plan
    if msgs and msgs[0].get("role") == "system":
        msgs[0]["content"] = system_prompt_aktuell(sit, plan=plan)
    # Kein Stream-Vorab, solange Buchung ODER Verwaltung offen ist: die Wachen
    # unten (_nachbessern) duerfen den Text noch umbauen — ein schon
    # gesprochener erster Satz waere dann falsch. Nur freies Geplauder streamt.
    s = sit.get("sammler") or {}
    mitten_drin = s.get("modus") in {"buchen", "absagen", "verschieben", "auskunft"} and s.get("phase") not in {"gebucht", "fertig"}
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
    llm_tools = task_router.werkzeuge_fuer(sit) if task_auswahl else TOOLS
    if darf_vorab:
        # P5 spricht Sätze bereits während der Generierung. Die finale Wache
        # unten käme für eine Halluzination zu spät; deshalb wird ein
        # unbelegter Kalender-/Erledigt-Satz samt aller Folge-Sätze schon am
        # Streaming-Ausgang zurückgehalten.
        vorab_blockiert = False

        def sicherer_vorab(satz: str) -> None:
            nonlocal vorab_blockiert
            if vorab_blockiert:
                return
            unbelegt = fakten_wache.unbelegte_behauptung(
                sit, satz, nutzertext=text_in)
            if fakten_wache.modus() == "enforce" and unbelegt:
                vorab_blockiert = True
                spur.merken(sit, "fakten-wache-vorab", unbelegt)
                return
            vorab(satz)

        out = llm.chat_stream(
            msgs, llm_tools, erster_satz=sicherer_vorab, **extra)
    else:
        out = llm.chat(msgs, llm_tools, **extra)
    if not out.get("ok"):
        return {
            "text": "Entschuldigung, da ist mir gerade etwas dazwischengekommen. Was darf ich für Sie tun?",
            "error": out.get("error"),
            "book": None,
        }
    if task_auswahl:
        wahl = task_router.auswahl(out)
        if wahl and task_router.anwenden(sit, wahl, original=text_in):
            # Das LLM hat nur semantisch zugeordnet. Der sichere Flow
            # verarbeitet denselben Nutzersatz nun mit seinem neuen Modus;
            # kein zweiter Modelllauf und kein Kalenderwerkzeug dazwischen.
            fl = flow.zug(sit, text_in, melde)
            if fl and (_s(fl.get("text")) or fl.get("hangup") or fl.get("transfer")):
                return _maschinen_antwort(sit, fl, msgs)
            return {
                "text": "Gerne. Erzählen Sie mir bitte noch kurz, worum es genau geht.",
                "book": None,
            }
    text, msgs, book = zuege.apply_tools(sit, msgs, out, melde=melde)
    gelaufen = [_s(w.get("name")) for w in (sit.get("tools") or [])[werkzeuge_vorher:]]
    werkzeug_lief = bool(gelaufen)
    _fluss_sync(sit, gelaufen, book)
    bewacht = _nachbessern(sit, text, melde, werkzeug_lief=werkzeug_lief, floor=route["floor"])
    bewacht = _fakten_wache_anwenden(
        sit, bewacht, nutzertext=text_in)
    if bewacht != text:
        if msgs and msgs[-1].get("role") == "assistant":
            msgs[-1]["content"] = bewacht
        text = bewacht
    sit["messages"] = msgs
    if _s(text):
        wiederholung.gesagt_merken(sit, text)
    gespraech.nach_antwort(sit)
    # W-GEDAECHTNIS: auch LLM-Zuege koennen Fakten geerntet haben.
    gedaechtnis.kontext_anstossen(sit)
    return {"text": text, "book": book}


def hangup(sit: dict) -> dict[str, Any]:
    return zuege.auto_notiz(sit, force=True)
