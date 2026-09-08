"""Weiterleitungs-Wunsch am Patiententelefon — deterministisch, ohne LLM.

Zwei Faelle, streng getrennt:

  1. NAMENTLICH genannter Arzt ("Kann ich bitte mit Doktor Patrikis
     sprechen?"): KEINE Personalfrei-Ansage, KEINE Rueckfrage — direkt
     "Einen Moment, ich stelle die Verbindung her", Jingle, verbinden.
  2. Mitarbeiter/Abteilung (Mensch, Empfang, Rezeption, Buchhaltung,
     Patientenannahme, Verwaltung ...): Bianca erklaert ihre Aufgabe als
     Telefonassistentin und uebernimmt zuerst das konkrete Anliegen. Nur
     wenn der Anrufer danach weiter auf einem Menschen besteht, darf ein
     EXAKT fuer diese Rolle eingerichtetes Ziel verbunden werden; sonst
     wird auf Wunsch ein Rueckrufwunsch aufgenommen.

Doppelte Fragen bleiben verboten: ist der Behandler aus dem Gespraech oder
der Akte bekannt (Sammler -> Angebots-Kalender -> arzt.letzter_behandler),
wird er angeboten statt erfragt.

Das Verbinden selbst (W-VERBINDEN-ECHT 31.08.2026): Ansage + Jingle, dann
zwei Wege. Hat der CLIENT eine Weiterleitung eingerichtet (DB-Agent:
callForwardingToolEnabled + callForwardings -> tenant["weiterleitungen"],
kern/agentprofil.py), traegt die Antwort ``transfer`` ({nummer, name}) —
die SIP-Bruecke merkt sich die Nummer je Anruf-UUID, der Asterisk-Dialplan
holt sie NACH dem AudioSocket-Ende per CURL ab und waehlt selbst zu Zaluma
raus (extensions_bianca.conf). Ohne eingerichtete Weiterleitung bleibt der
alte Platzhalter-Weg (Jingle + Kirri-Zettel + hangup, Marke:
ZALUMA_TRANSFER_PLATZHALTER).
"""

from __future__ import annotations

import re
from typing import Any, Callable

from bianca import arzt as arztmod
from bianca import besuchsgrund, gehirn
from kern import hirn as session_hirn, wiederholung
from kern.leitung import ist_leitung_check
from kern.patients import arzt_sprechname

# Kurze Quittung auf „Bin ich mit der Praxis … verbunden?“ — kein Jingle.
LEITUNG_OK = "Ja, Sie sind richtig verbunden. Was kann ich für Sie tun?"

Melde = Callable[[str], None] | None

# Festes Audio fuer die Filler-Kette des Clients: bianca/server.py legt
# bianca_web/verbinden.mp3 unter diesem Namen im Dienst ab.
JINGLE_NAME = "verbinden"
JINGLE_EVENT = f"audio:{JINGLE_NAME}"

ENTLASTUNG = (
    "Ich bin die Telefonassistentin der Praxis und entlaste die Anmeldung. "
    "Vieles kann ich direkt für Sie erledigen. Worum geht es denn?"
)
# Rückwärtskompatibler Name für bestehende Importe; die alte Behauptung
# „niemand geht ran“ darf nirgends mehr gesprochen werden.
WAHRHEIT = ENTLASTUNG

SELBST_HILFE = "Ja, gern. Sagen Sie mir einfach, worum es geht."
RUECKRUF_ANGEBOT = (
    "Eine direkte Verbindung zur Anmeldung ist nicht eingerichtet. "
    "Ich kann einen Rückrufwunsch für das Praxisteam aufnehmen. Soll ich das tun?"
)

# Die Antwort, wenn KEINE echte Weiterleitung eingerichtet ist. Chef
# 03.09.2026: der alte Kirri-Spassatz ("... du Lappen") MUSS ueberall
# verschwinden, und Rueckrufe werden NIE angeboten, nur auf Verlangen —
# darum: ehrlich absagen, Gespraech offen halten (kein Jingle, kein
# Auflegen). Der Verbinden-Jingle spielt nur noch vor ECHTEM Durchstellen.
ANSAGE_PLATZHALTER = (
    "Die direkte Verbindung ist im Moment leider nicht möglich. "
    "Kann ich sonst etwas für Sie tun?"
)

_MENSCH_WORT = (
    r"(?:mensch(?:en)?|mitarbeiter\w*|angestellte\w*|personal\b|empfang|rezeption|"
    r"sekretariat|sekretär\w*|sekretaer\w*|sprechstundenhilfe|kolleg\w*|"
    r"buchhaltung|patientenannahme|annahme|anmeldung|verwaltung|abrechnung|"
    r"chef\w*|inhaber\w*|praxisleitung|boss)"
)

# Klassifikation: kommt im Satz ueberhaupt ein Mitarbeiter-/Abteilungs-Wort vor?
# Nur DANN gibt es die Personalfrei-Ansage (Chef 27.08.2026, zweite Fassung).
_MENSCH_NUR_RE = re.compile(_MENSCH_WORT, re.I)
_MENSCH_BESTEHT_RE = re.compile(
    rf"(?:trotzdem|wirklich|unbedingt|ausdrücklich|ausdruecklich|besteh\w*)"
    rf"[^.!?]{{0,45}}{_MENSCH_WORT}|"
    rf"{_MENSCH_WORT}[^.!?]{{0,45}}(?:trotzdem|wirklich|unbedingt|besteh\w*)",
    re.I,
)
_SELBST_HELFEN_RE = re.compile(
    r"\b(?:kannst|können|koennen)\s+(?:du|sie)\s+mir\s+(?:denn\s+)?"
    r"(?:selbst\s+)?helfen\b|"
    r"\b(?:hilf|helfen)\s+(?:du|sie)\s+mir\b",
    re.I,
)
_ZURUECK_RE = re.compile(
    r"\b(?:machen|gehen)\s+wir\b[^.!?]{0,35}\bweiter\b|"
    r"\b(?:mit|beim)\s+(?:dem|meinem|unserem)?\s*termin\b[^.!?]{0,20}\bweiter\b|"
    r"\bzurück\s+(?:zum|zur)\s+termin\b|\bzurueck\s+(?:zum|zur)\s+termin\b",
    re.I,
)

_ROLLEN_GRUPPEN = {
    "anmeldung": re.compile(
        r"\banmeldung\b|\bempfang\b|\brezeption\b|\bpatientenannahme\b|"
        r"\bannahme\b|\bsekretariat\b|\bsprechstundenhilfe\b",
        re.I,
    ),
    "buchhaltung": re.compile(r"\bbuchhaltung\b|\babrechnung\b", re.I),
    "verwaltung": re.compile(r"\bverwaltung\b", re.I),
    "leitung": re.compile(
        r"\bchef\w*\b|\binhaber\w*\b|\bpraxisleitung\b|\bboss\b", re.I,
    ),
}

# Ausdruecklicher Verbinde-/Durchstell-Wunsch. Die "verbunden"-Formen ohne
# mich/uns stammen aus dem Live-Gespraech 29.08.2026 08:44: "Könnte ich bitte
# mit Doktor Petzers verbunden?" und "Ich möchte verbunden." rutschten durch,
# das LLM erfand daraufhin eine Ablehnung ("Hier spricht man nicht mit den
# Ärzten"). "Ist das mit Kosten/Schmerzen verbunden?" bleibt bewusst draussen
# (Preisfrage!): die neuen Formen verlangen Doktor-Wort oder "ich möchte/will".
# Der nackte Imperativ "Verbinde mich mit Dr. X jetzt." (live 31.08.2026
# 14:11) fiel durch ALLE Formen — das LLM fragte zum x-ten Mal "Zu welchem
# unserer Ärzte...", der Anrufer legte entnervt auf.
_VERBINDEN_RE = re.compile(
    r"verbinden?\s+sie\s+(?:mich|uns)|"
    r"\bverbinde\s+(?:mich|uns)\b|"
    r"(?:mich|uns)\s+(?:[\wäöüß.\-, ]{0,40}?\s+)?(?:verbinden|verbunden|durchstellen|durchgestellt|weiterleiten|weitergeleitet)|"
    r"stell\w*\s+(?:sie\s+)?(?:mich|uns)\s+(?:bitte\s+)?durch\b|"
    r"durchstellen|durchgestellt|weiterleiten|weitergeleitet|weiterverbinden|durchverbinden|"
    r"verbunden\s+werden|"
    r"(?:ja\s+(?:bitte\s+)?)?bitte\s+verbinden\b|"
    r"\bja\s+(?:bitte\s+)?verbinden\b|"
    r"^\s*verbinden(?:\s+sie)?(?:\s+bitte)?\s*[.!]?\s*$|"
    r"ich\s+(?:möchte|moechte|will|würde|wuerde)\s+(?:bitte\s+|gerne?\s+|auch\s+)*verbunden\b|"
    r"mit\s+(?:dem\s+|der\s+|herrn\s+|frau\s+)?(?:doktor|dr\.?|prof\w*|arzt|ärztin|aerztin|zahnarzt|behandler(?:in)?)\b[^.!?]{0,40}?\bverbunden\b",
    re.I,
)

# "Ich will einen Menschen/Mitarbeiter/jemanden vom Empfang" — auch als Frage
# ("Gibt es da kein Personal?", "Kann ich mit der Buchhaltung sprechen?").
_MENSCH_RE = re.compile(
    rf"mit\s+(?:einem|einer|nem|ner|der|dem)?\s*(?:echten|richtigen)?\s*{_MENSCH_WORT}\s+(?:sprechen|reden)|"
    rf"{_MENSCH_WORT}\s+(?:sprechen|erreichen|ans?\s+telefon)|"
    rf"jemand\w*\s+vo[nm]\s+(?:der\s+|dem\s+)?(?:{_MENSCH_WORT}|team|praxisteam)|"
    rf"kein(?:e|en)?\s+(?:echten\s+|richtigen\s+|menschlichen\s+)?{_MENSCH_WORT}",
    re.I,
)

# Info-/Bestandsfrage ("Gibt es auch Doktor Patrikis bei euch?", "Welche
# Ärzte arbeiten da?"): der Anrufer will eine AUSKUNFT, kein Durchstellen.
# Live 29.08.2026: der blosse Namens-Treffer gewann vor der Frage-Erkennung
# und Bianca "verband" mitten in der Frage. Solche Saetze gehen ans LLM.
_INFOFRAGE_RE = re.compile(
    r"\b(?:gibt\s+es|gibts|habt\s+ihr|haben\s+sie|arbeite[tn]|"
    r"wer\s+(?:ist|sind)|welche[rsnm]?)\b",
    re.I,
)

# Direkter Behandlerwunsch: "Kann ich mit Doktor Petsas sprechen?"
_ARZT_SPRECHEN_RE = re.compile(
    r"mit\s+(?:dem\s+|der\s+|herrn\s+|frau\s+)?(?:doktor|dr\.?|prof\w*|arzt|ärztin|aerztin|zahnarzt|behandler(?:in)?)\b"
    r"[^.!?]{0,40}?\b(?:sprechen|reden)|"
    r"\b(?:doktor|dr\.?)\s+[\wäöüß-]+\s+(?:selbst\s+|persönlich\s+|persoenlich\s+)?(?:sprechen|erreichen)|"
    r"herrn?\s+(?:doktor|dr\.?)\s+[\wäöüß-]+\s+(?:sprechen|reden|erreichen)|"
    r"\b(?:doktor|dr\.?|prof\w*|arzt|ärztin|aerztin|zahnarzt|behandler(?:in)?)\b[^.!?]{0,40}?\ban(?:s|\s+den)\s+(?:telefon|apparat)",
    re.I,
)

# Sprech-/Verbinde-Verben fuer den Namens-Weg: "Kann ich Herrn Petsas
# sprechen?" traegt keinen Doktor-Titel und faellt durch _ARZT_SPRECHEN_RE —
# der Behandler-Name (fuzzy ueber arzt.deute) plus so ein Verb zaehlt
# trotzdem als Weiterleitungs-Wunsch.
_SPRECH_VERB_RE = re.compile(
    r"\b(?:sprechen|reden|erreichen|verbind\w*|verbunden|durchstellen|durchgestellt|"
    r"weiterleiten|weitergeleitet|durchverbinden|weiterverbinden)\b|"
    r"\ban(?:s|\s+den)\s+(?:telefon|apparat)\b",
    re.I,
)

# LLM-Backstop-Rueckfrage (Prompt-Leitplanke WEITERLEITEN): hat die VORIGE
# Assistentin-Zeile "Zu welchem unserer Ärzte darf ich Sie verbinden?"
# gefragt, zaehlt der blosse Behandler-Name im naechsten Zug als Zielangabe.
_RUECKFRAGE_RE = re.compile(r"(?:verbind|durchstell)\w*[^.!?]*\?", re.I)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def erkannt(text: str) -> bool:
    """Will der Anrufer verbunden werden / einen Menschen sprechen?"""
    t = _s(text)
    if not t or ist_leitung_check(t):
        return False
    # Pourianmehr 08.09.: „Schiene abholen und darüber mit einem Arzt
    # sprechen“ ist Buchung zur Eingliederung, kein Durchstellen.
    if besuchsgrund.ist_schiene_abholen(t):
        return False
    return bool(_VERBINDEN_RE.search(t) or _MENSCH_RE.search(t) or _ARZT_SPRECHEN_RE.search(t))


def _letzter_genannter_arzt(sit: dict) -> dict | None:
    """Behandler aus früheren Anrufer-Sätzen — Live Schnorbus 08.09.:
    „Herr Dr. Patrikis sprechen“ / „Dr. Patrikis“, danach nur noch
    „Ja bitte verbinden“ ohne Namen. Ohne diesen Rückgriff fragt die
    Maschine erneut und das LLM sagt „ich verbinde Sie“ ohne Transfer."""
    tenant = sit.get("tenant") or {}
    for m in reversed(sit.get("messages") or []):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        d = arztmod.deute(_s(m.get("content")), tenant)
        if d and d.get("typ") == "genannt":
            return {
                "calendarId": _s(d.get("calendarId")),
                "calendarName": _s(d.get("calendarName")),
            }
    return None


def _arzt_merken(s: dict, ziel: dict) -> None:
    """Doppelte Fragen sind verboten: ein hier geklaerter Behandler zaehlt
    auch fuer eine spaetere Buchung im selben Anruf."""
    if ziel.get("calendarId") and not (s.get("arzt") or {}).get("calendarId"):
        s["arzt"] = {
            "typ": "genannt",
            "calendarId": ziel["calendarId"],
            "calendarName": ziel.get("calendarName") or "",
        }


def _ziel_finden(sit: dict, melde: Melde = None) -> dict | None:
    """Ziel-Behandler aus dem GEDAECHTNIS bestimmen (nicht aus dem Satz —
    das erledigt zug() via arzt.deute): erst Sitzungsgedaechtnis, dann
    Patientenakte. None = wirklich nichts bekannt."""
    tenant = sit.get("tenant") or {}
    s = gehirn.sammler(sit)

    # 1) Sammler: Behandler wurde im Gespraech schon geklaert.
    a = s.get("arzt") or {}
    if a.get("calendarId") or a.get("calendarName"):
        return {"calendarId": _s(a.get("calendarId")), "calendarName": _s(a.get("calendarName"))}

    # 2) Frueher erwaehnt: ein Angebot lief schon in einem konkreten Kalender.
    bind = sit.get("angebotKalender") or {}
    if bind.get("calendarId") or bind.get("calendarName"):
        return {"calendarId": _s(bind.get("calendarId")), "calendarName": _s(bind.get("calendarName"))}
    if _s(sit.get("angebotArzt")):
        name = _s(sit.get("angebotArzt"))
        d2 = arztmod.deute(name, tenant)
        if d2 and d2.get("typ") == "genannt":
            return {"calendarId": _s(d2.get("calendarId")), "calendarName": _s(d2.get("calendarName"))}
        return {"calendarId": "", "calendarName": name}

    # 3) Patientenakte: letzter Behandler (gleicher Weg wie bianca/hintergrund).
    if s.get("patientId"):
        if melde:
            melde("list_appointments")  # Fueller: "Ganz kurz, ich schaue in Ihre Akte."
        info = arztmod.letzter_behandler(tenant, s["patientId"])
        if info.get("ok") and (info.get("calendarId") or info.get("calendarName")):
            return {
                "calendarId": _s(info.get("calendarId")),
                "calendarName": _s(info.get("calendarName")) or _s(info.get("doctorName")),
            }
    return None


def _angebot_text(ziel: dict, tenant: dict | None = None) -> str:
    wer = arzt_sprechname(_s(ziel.get("calendarName")), tenant) or "Ihrem Behandler"
    return f"Soll ich Sie zu {wer} weiterleiten?"


def _rollen_weiterleitung(tenant: dict, text: str) -> dict:
    """Nur ein EXAKT zur verlangten Abteilung passendes DB-Ziel liefern.

    Die Ein-Ziel-Rückfallregel von ``weiterleitungs_ziel`` ist für Ärzte
    sinnvoll, für „Anmeldung“ aber gefährlich: Ein einzelnes Arztziel darf
    niemals still zur Anmeldung umgedeutet werden.
    """
    verlangt = {
        gruppe for gruppe, muster in _ROLLEN_GRUPPEN.items()
        if muster.search(_s(text))
    }
    if not verlangt:
        return {}
    for eintrag in tenant.get("weiterleitungen") or []:
        if not isinstance(eintrag, dict) or not _s(eintrag.get("nummer")):
            continue
        beschreibung = f"{_s(eintrag.get('name'))} {_s(eintrag.get('hinweis'))}"
        vorhanden = {
            gruppe for gruppe, muster in _ROLLEN_GRUPPEN.items()
            if muster.search(beschreibung)
        }
        if verlangt & vorhanden:
            return {
                "name": _s(eintrag.get("name")) or sorted(verlangt)[0],
                "nummer": _s(eintrag.get("nummer")),
            }
    return {}


def _rolle_verbinden(sit: dict, ziel: dict, melde: Melde = None) -> dict:
    """Bereits rollenvalidiertes Ziel wirklich verbinden."""
    sit["weiterleiten"] = {}
    name = _s(ziel.get("name")) or "Anmeldung"
    if melde:
        melde("sag:Ok, einen Moment bitte — ich stelle die Verbindung zur gewünschten Stelle her.")
        melde(JINGLE_EVENT)
    sit["weiterleitungZiel"] = dict(ziel)
    return {
        "text": "",
        "jingle": JINGLE_EVENT,
        "ziel": {"calendarId": "", "calendarName": name},
        "transfer": {"nummer": _s(ziel.get("nummer")), "name": name},
        "hangup": True,
    }


# Fuell-/Titelwoerter, die beim Abgleich Kalendername <-> Weiterleitungs-
# Eintrag nichts beweisen ("Dr." steht in JEDEM Eintrag).
_TITEL_WORTE = {
    "doktor", "professor", "prof", "med", "dent", "praxis", "herr", "frau",
    "zahnarzt", "zahnaerztin", "zahnärztin", "arzt", "aerztin", "ärztin",
    "kalender", "termin", "sprechstunde",
}


def weiterleitungs_ziel(tenant: dict, ziel: dict) -> dict:
    """Eingerichtete Weiterleitung des Clients zum Ziel-Behandler.

    tenant["weiterleitungen"] kommt aus der DB (kern/agentprofil.py:
    callForwardings, nur mit callForwardingToolEnabled) oder aus einer
    lokalen tenants/*.json. Abgleich: ein Namens-Wort des Kalenders
    ("Petsas") muss im Eintrag (name/hinweis) vorkommen; ohne Treffer
    gilt ein EINZELNER Eintrag als Praxis-Ziel fuer alle Behandler.
    {} = nichts eingerichtet -> Platzhalter-Weg."""
    eintraege = [
        e for e in (tenant.get("weiterleitungen") or [])
        if isinstance(e, dict) and _s(e.get("nummer"))
    ]
    if not eintraege:
        return {}
    tokens = [
        w for w in re.split(r"[^\wäöüß]+", _s(ziel.get("calendarName")).lower())
        if len(w) >= 3 and w not in _TITEL_WORTE
    ]
    for e in eintraege:
        text = f"{_s(e.get('name'))} {_s(e.get('hinweis'))}".lower()
        if tokens and any(tok in text for tok in tokens):
            return {"name": _s(e.get("name")), "nummer": _s(e.get("nummer"))}
    if len(eintraege) == 1:
        e = eintraege[0]
        return {"name": _s(e.get("name")), "nummer": _s(e.get("nummer"))}
    return {}


def zaluma_weiterleitung(sit: dict, ziel: dict, melde: Melde = None) -> dict:
    """Anrufer zum Behandler weiterleiten: Ansage, Jingle — dann echt oder
    Platzhalter.

    W-VERBINDEN-ECHT (31.08.2026): hat der Client eine Weiterleitung
    eingerichtet (weiterleitungs_ziel), traegt die Antwort ``transfer``
    ({nummer, name}) — die SIP-Bruecke merkt die Nummer je Anruf-UUID,
    der Asterisk-Dialplan waehlt nach dem AudioSocket-Ende wirklich raus.
    Ohne Einrichtung: hoerbare Kette + Kirri-Zettel wie bisher."""
    sit["weiterleiten"] = {}  # Anliegen ist bedient
    ziel_arzt = {
        "calendarId": _s(ziel.get("calendarId")),
        "calendarName": _s(ziel.get("calendarName")),
    }
    wl = weiterleitungs_ziel(sit.get("tenant") or {}, ziel_arzt)
    if wl:
        if melde:
            # Erst die Ansage, DANN der Jingle: beides ueber die Filler-Kette
            # (Client spielt strikt nacheinander, Abschied-Audio danach).
            wer = arzt_sprechname(
                ziel_arzt["calendarName"],
                sit.get("tenant") if isinstance(sit.get("tenant"), dict) else None,
            )
            zu = f" zu {wer}" if wer else ""
            melde(f"sag:Ok, einen Moment bitte — ich stelle die Verbindung{zu} her.")
            melde(JINGLE_EVENT)
        # Echte Weiterleitung: Ansage + Jingle liefen als Filler, die Antwort
        # selbst bleibt stumm (text="") — nach dem Jingle klingelt es beim
        # Behandler. Das Ziel steht in der Sitzung fuer Nacharbeit/Report.
        sit["weiterleitungZiel"] = dict(wl)
        print(f"bianca-weiterleitung ziel={ziel_arzt!r} nummer={wl['nummer']} "
              f"sit={sit.get('id')!r}", flush=True)
        return {
            "text": "",
            "jingle": JINGLE_EVENT,
            "ziel": ziel_arzt,
            "transfer": {"nummer": wl["nummer"],
                         "name": wl["name"] or ziel_arzt["calendarName"]},
            "hangup": True,
        }
    # =====================================================================
    # ZALUMA_TRANSFER_PLATZHALTER: Rueckfall, wenn der Client KEINE
    # Weiterleitung eingerichtet hat (DB: callForwardingToolEnabled aus
    # oder keine callForwardings). KEIN Jingle, KEIN Auflegen, KEIN
    # Rueckruf-Angebot (Chef 03.09.2026: "keine Rueckrufe anbieten, es sei
    # denn, sie werden verlangt") — ehrlich sagen, dass es nicht geht, und
    # das Gespraech offen halten. Verlangt der Anrufer daraufhin selbst
    # einen Rueckruf, uebernimmt der ABGEBEN-Fluss.
    # =====================================================================
    print(f"bianca-zaluma-platzhalter ziel={ziel_arzt!r} sit={sit.get('id')!r}",
          flush=True)
    return {
        "text": ANSAGE_PLATZHALTER,
        "ziel": ziel_arzt,
    }


def zug(sit: dict, gesagt: str, melde: Melde = None) -> dict | None:
    """Ein Anrufer-Satz durch den Weiterleitungs-Zweig. None => andere Fluesse."""
    s = gehirn.sammler(sit)
    t = _s(gesagt)
    if not t:
        return None
    # Live 08.09.2026: „Bin ich mit der Praxis Dr. Petsas verbunden?“
    # ist Leitung prüfen, nicht durchstellen — auch wenn das Hirn
    # ERREICHEN geraten hat (Wort „verbunden“ + Name Petsas).
    if ist_leitung_check(t):
        sit.pop("hirnVerbinden", None)
        return {"text": LEITUNG_OK}
    # Offene Weiterleitung darf eine Abholung nicht verschlucken
    # (Live Pourianmehr: frage=arzt, dann „Zahnschienen abholen“).
    if besuchsgrund.ist_schiene_abholen(t):
        sit["weiterleiten"] = {}
        sit.pop("hirnVerbinden", None)
        return None
    # W-HIRN (03.09.2026): das Session-Hirn hat ERREICHEN erkannt — auch wenn
    # keine der Verbinde-Regexes den Satz fasst ("Ich haette gern Doktor X",
    # "I want to talk to him", "Mitarbeiter, bitte"). Der Zettel bewaffnet
    # diesen Zweig genau einmal.
    hirn_wunsch = sit.pop("hirnVerbinden", None)
    w = sit.get("weiterleiten") or {}

    # Globales Anliegen Anmeldung/Empfang: Nach der ersten Erklärung hört
    # Bianca auf das eigentliche Problem. Eine erneute Menschenforderung
    # darf nur an ein exakt passendes DB-Ziel gehen — niemals ersatzweise
    # an den einzigen Arzt-Forwarding-Eintrag.
    if w.get("frage") == "anliegen":
        d = arztmod.deute(t, sit.get("tenant") or {})
        if d and d.get("typ") == "genannt":
            sit["weiterleiten"] = {}
            ziel = {
                "calendarId": _s(d.get("calendarId")),
                "calendarName": _s(d.get("calendarName")),
            }
            _arzt_merken(s, ziel)
            return zaluma_weiterleitung(sit, ziel, melde)
        if _MENSCH_NUR_RE.search(t) and (
            erkannt(t) or _MENSCH_BESTEHT_RE.search(t)
        ):
            rollen_ziel = _rollen_weiterleitung(sit.get("tenant") or {}, t)
            if rollen_ziel:
                return _rolle_verbinden(sit, rollen_ziel, melde)
            sit["weiterleiten"] = {
                "frage": "rueckruf",
                "rolle": _s(w.get("rolle")) or "Anmeldung",
            }
            return {"text": RUECKRUF_ANGEBOT}
        if _SELBST_HELFEN_RE.search(t):
            return {"text": SELBST_HILFE}
        if gehirn.ist_nein(t):
            sit["weiterleiten"] = {}
            return {"text": "Alles klar. Was kann ich sonst für Sie tun?"}
        if _ZURUECK_RE.search(t):
            rueck = session_hirn.anwenden(sit, {"kanal": "ok", "zug": "zurueck"})
            sit["weiterleiten"] = {}
            if rueck.get("zug") == "zurueck":
                return None
            return {"text": SELBST_HILFE}
        # Das konkrete Anliegen übernimmt ab hier der passende sichere Flow
        # oder das Haupt-LLM. Der Frontdesk-Dialog darf es nicht verschlucken.
        sit["weiterleiten"] = {}
        return None

    if w.get("frage") == "rueckruf":
        if gehirn.ist_ja(t):
            sit["weiterleiten"] = {}
            session_hirn.anwenden(sit, {
                "kanal": "ok",
                "zug": "wechseln",
                "handlung": "ABGEBEN",
                "gegenstand": "SACHE",
                "spiegel": "Rückrufwunsch für die Anmeldung",
            })
            return None
        if gehirn.ist_nein(t):
            sit["weiterleiten"] = {}
            return {
                "text": "Alles klar. Dann helfe ich Ihnen gern direkt. Worum geht es?"
            }
        return {
            "text": "Soll ich einen Rückrufwunsch für das Praxisteam aufnehmen?"
        }

    # Offenes Weiterleitungs-Angebot ("Soll ich Sie zu Doktor X weiterleiten?")
    if w.get("frage") == "anbieten":
        if gehirn.ist_ja(t) or erkannt(t):
            # W-MEDDENT (04.09.2026): Ja / erneuter Verbinde-Wunsch → sofort
            # durchstellen, keine zweite Arztfrage.
            return zaluma_weiterleitung(sit, w.get("ziel") or {}, melde)
        if _INFOFRAGE_RE.search(t) and not erkannt(t):
            # Auskunftsfrage statt Zielangabe — LLM antwortet, Angebot bleibt.
            return None
        d = arztmod.deute(t, sit.get("tenant") or {})
        if d and d.get("typ") == "genannt":
            # "Nein, lieber zu Doktor Nikolaou" — namentlich genannt heisst
            # direkt verbinden (Chef 27.08.), nicht noch einmal anbieten.
            ziel = {"calendarId": _s(d.get("calendarId")), "calendarName": _s(d.get("calendarName"))}
            _arzt_merken(s, ziel)
            return zaluma_weiterleitung(sit, ziel, melde)
        if gehirn.ist_nein(t):
            sit["weiterleiten"] = {}
            return {"text": "Alles klar, dann bleibe ich gern für Sie dran. Kann ich sonst noch etwas für Sie tun?"}
        # Unklar/Zwischenfrage: unten neu pruefen (Wiederholung des Wunschs),
        # sonst uebernimmt das LLM.

    # Offene Arzt-Rueckfrage ("Zu welchem unserer Ärzte darf ich Sie verbinden?")
    elif w.get("frage") == "arzt":
        if _INFOFRAGE_RE.search(t) and not erkannt(t):
            # "Gibt es auch Doktor X?" ist eine Auskunftsfrage, keine
            # Zielangabe — nicht verbinden, das LLM beantwortet sie.
            return None
        d = arztmod.deute(t, sit.get("tenant") or {})
        if d and d.get("typ") == "genannt":
            # Arzt genannt -> direkt verbinden, keine weitere Rueckfrage.
            ziel = {"calendarId": _s(d.get("calendarId")), "calendarName": _s(d.get("calendarName"))}
            _arzt_merken(s, ziel)
            return zaluma_weiterleitung(sit, ziel, melde)
        # „Ja bitte verbinden“ / „können Sie mich verbinden“ nach einem
        # schon genannten Namen: nicht erneut fragen, durchstellen.
        if erkannt(t):
            alt = _ziel_finden(sit) or _letzter_genannter_arzt(sit)
            if alt:
                _arzt_merken(s, alt)
                return zaluma_weiterleitung(sit, alt, melde)
        if gehirn.ist_nein(t) or (d and d.get("typ") in {"egal", "unbekannt"}):
            sit["weiterleiten"] = {}
            return {"text": "Kein Problem — dann helfe ich Ihnen einfach direkt weiter. Was kann ich für Sie tun?"}
        if gehirn.ist_zwischenfrage(t):
            return None
        zaehler = int(w.get("leer") or 0) + 1
        if zaehler >= 2:
            # Nie im Kreis fragen (Chef 27.08.: keine Schleifen).
            sit["weiterleiten"] = {}
            return {"text": "Machen wir es anders: Ich helfe Ihnen einfach direkt. Was kann ich für Sie tun?"}
        w["leer"] = zaehler
        sit["weiterleiten"] = w
        return {"text": "Entschuldigung — zu welchem unserer Ärzte darf ich Sie denn verbinden?"}

    # Neuer (oder wiederholter) Weiterleitungs-Wunsch?
    if not erkannt(t) and not hirn_wunsch:
        # Buchungs-/Verwaltungssaetze ("Termin bei Doktor Petsas ...")
        # gehoeren den anderen Fluessen — kein Namens-Kurzschluss.
        if "termin" in t.lower():
            return None
        d0 = arztmod.deute(t, sit.get("tenant") or {})
        genannt = d0 if (d0 and d0.get("typ") == "genannt") else None
        if genannt:
            ziel0 = {"calendarId": _s(genannt.get("calendarId")), "calendarName": _s(genannt.get("calendarName"))}
            # (a) Behandler-Name + Sprech-/Verbinde-Verb ohne Doktor-Titel:
            #     "Kann ich Herrn Petsas sprechen?" — live 29.08.2026
            #     verneinte das LLM solche Saetze frei erfunden.
            if _SPRECH_VERB_RE.search(t):
                _arzt_merken(s, ziel0)
                return zaluma_weiterleitung(sit, ziel0, melde)
            # (b) Rueckweg der Prompt-Leitplanke: das LLM hat "Zu welchem
            #     unserer Ärzte darf ich Sie verbinden?" gefragt — der blosse
            #     Name ist die Zielangabe (die Maschine war nicht bewaffnet).
            letzte = wiederholung.letzte_antworten(sit.get("messages") or [], 1)
            if letzte and _RUECKFRAGE_RE.search(letzte[0]):
                _arzt_merken(s, ziel0)
                return zaluma_weiterleitung(sit, ziel0, melde)
        return None

    # Fall 1: Arzt NAMENTLICH im Satz ("Kann ich mit Doktor Patrikis
    # sprechen?") -> direkt verbinden. KEINE Personalfrei-Ansage, keine Frage.
    d = arztmod.deute(t, sit.get("tenant") or {})
    if (not d or d.get("typ") != "genannt") and isinstance(hirn_wunsch, dict) \
            and _s(hirn_wunsch.get("person")):
        # Der Name stand in einem frueheren Satz — das Hirn traegt ihn nach.
        d = arztmod.deute(_s(hirn_wunsch["person"]), sit.get("tenant") or {})
    if d and d.get("typ") == "genannt":
        ziel = {"calendarId": _s(d.get("calendarId")), "calendarName": _s(d.get("calendarName"))}
        _arzt_merken(s, ziel)
        return zaluma_weiterleitung(sit, ziel, melde)

    # Fall 2: Mitarbeiter/Abteilung gewuenscht (Mensch, Empfang, Buchhaltung,
    # Patientenannahme ...). Steht im selben Satz bereits ein konkretes
    # Termin-Anliegen, hat das Session-Hirn dessen sicheren Flow freigegeben;
    # dann darf die vermeintliche Wunsch-Abteilung die Aufgabe nicht überholen.
    mensch = bool(_MENSCH_NUR_RE.search(t))
    if mensch:
        if _s(s.get("modus")) in {"buchen", "absagen", "verschieben", "auskunft"} \
                and sit.get("hirnModusNeu"):
            sit["weiterleiten"] = {}
            return None
        sit["weiterleiten"] = {"frage": "anliegen", "rolle": t[:80]}
        return {"text": ENTLASTUNG}
    # Fall 3: Verbinde-Wunsch ohne Namen und ohne Mitarbeiter-Wort
    # ("Können Sie mich bitte weiterleiten?"): bekannten Behandler anbieten,
    # sonst wie bisher nach dem Arzt fragen.
    ziel = _ziel_finden(sit, melde)
    if ziel:
        _arzt_merken(s, ziel)
        sit["weiterleiten"] = {"frage": "anbieten", "ziel": ziel}
        return {"text": _angebot_text(ziel, sit.get("tenant"))}
    sit["weiterleiten"] = {"frage": "arzt"}
    return {"text": "Sehr gern — zu welchem unserer Ärzte darf ich Sie verbinden?"}
