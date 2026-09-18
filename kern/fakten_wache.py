"""Evidenzbasierter Fakten-/Erledigt-Waechter (W-FAKTEN-WACHE 09.09.2026).

Vorbild ist Claras UNVERIFIED_ACTION_FALLBACK: eine gesprochene Erledigt-
Behauptung ("Ihr Termin ist gebucht/abgesagt/verschoben", "ich habe eine Notiz
gemacht") darf nur raus, wenn das passende Werkzeug im Sitzungs-Ledger
ERFOLGREICH gelaufen ist. Wahrheit ist das Tool-Ledger (`sit["tools"]` bzw. die
gefalteten Marken lastBook/lastCancel/lastMove/lastNote/lastCreate aus
`kern/sitzung.merke_tool`), NICHT der LLM-Text.

Dieses Modul ist reine, bianca-freie Erkennung (kern-Schicht). Der Umgang mit
einer unbelegten Behauptung (Shadow-Log vs. Enforce-Umschreiben) liegt beim
Aufrufer (`bianca/agent`), damit dort die vorhandenen Frage-Formulierungen
wiederverwendet werden.

Notaus/Stufen `FAKTEN_WACHE=off|shadow|enforce` (Default off = kein Eingriff).
Tests: `tests/test_fakten_wache.py`.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable

_SATZ = re.compile(r"(?<=[.!?…])\s+")
# Eine echte Frage am Satzanfang behauptet keine erledigte Aktion. Ein
# angehängtes „passt das?“ entschärft dagegen keine vorausgehende Lüge
# („Ich habe reserviert, passt das?“).
_REINE_FRAGE = re.compile(
    r"^(?:soll(?:en)?\s+(?:ich|wir)|m(?:ö|oe)chten\s+sie|darf\s+ich|"
    r"wollen\s+sie|kann\s+ich|haben\s+sie|ist\s+ihr|bekommen\s+sie)\b",
    re.I,
)

_CLAIM_BUCHEN = re.compile(
    r"\b(?:gebucht|eingebucht|reserviert|fest\s+(?:ein)?getragen|"
    r"ist\s+(?:jetzt\s+)?(?:im|in\s+dem)\s+kalender|"
    r"hab(?:e)?\s+(?:ihn(?:en)?\s+|den\s+termin\s+)?(?:jetzt\s+|so\s+)?eingetragen|"
    # "Dann ist alles fuer Sie eingetragen." (Blessing 15.09., Anruf a8fcbcb4 —
    # es war NICHTS eingetragen). Die Fuellwoerter stehen einzeln da, damit eine
    # ehrliche VERNEINUNG ("ist noch nicht eingetragen") nie als Behauptung gilt.
    r"ist\s+(?:jetzt\s+|alles\s+|damit\s+|somit\s+|dann\s+)*"
    r"(?:f(?:ü|ue)r\s+sie\s+)?(?:alles\s+)?eingetragen|"
    r"termin\s+steht)\b|"
    # C1 (17.09.2026, Blessing-Anruf 53986f42): das Modell "buchte" im PRAESENS
    # — "Ich trage für Sie morgen, Mittwoch, den sechzehnten September, um neun
    # Uhr dreißig bei Frau Doktor Blessing ein.", "Ich buche Ihnen den Termin",
    # "Dann reserviere ich das" — book_slot lief nie; der Anrufer glaubte, er
    # habe einen Termin. Die alten Formen kannten nur das Perfekt. Erlaubt
    # bleiben Fragen ("Soll ich Sie eintragen?" — _REINE_FRAGE) und Verneinungen
    # ("kann ich nicht eintragen" — kein "ich trage/buche" davor).
    r"\b(?:ich\s+(?:trage|buche|reserviere|blocke|blockiere)|"
    r"(?:trage|buche|reserviere|blocke|blockiere)\s+ich)\b"
    r"(?:[^.!?]*?\b(?:ein|fest)\b(?=\s*(?:[,;—–-]|[.!?…]*\s*$))|"
    r"[^.!?]{0,40}\b(?:termin|platz|slot)\b)",
    re.I,
)
# Eine Nummer/Akten-Aenderung ist ein SCHREIBVORGANG — im selben Atemzug wie
# die Phantom-Buchung behauptete das Modell live auch "die Nummer ist
# gespeichert", ohne dass masUpdatePatientPhone je lief.
_CLAIM_NUMMER = re.compile(
    r"\b(?:handy|ruf|telefon)?nummer\b[^.!?]{0,30}\b"
    r"(?:gespeichert|hinterlegt|aktualisiert|"
    r"(?:ü|ue)bernommen|ge(?:ä|ae)ndert)\b|"
    r"\bhab(?:e)?\s+(?:ihre\s+|die\s+)?(?:handy|ruf|telefon)?nummer\b"
    r"[^.!?]{0,20}\b(?:eingetragen|gespeichert|hinterlegt)\b",
    re.I,
)
_CLAIM_ABSAGEN = re.compile(r"\b(abgesagt|storniert|gestrichen|gel(?:ö|oe)scht)\b", re.I)
_CLAIM_VERSCHIEBEN = re.compile(r"\b(verschoben|verlegt|umgebucht)\b", re.I)
_CLAIM_TRANSFER = re.compile(
    r"\bich\s+(?:werde\s+|habe\s+|kann\s+)?(?:sie\s+)?(?:jetzt\s+)?"
    r"(?:zu\s+[^.!?]{1,40}\s+)?(?:durchstell\w*|verbind\w*|weiterleit\w*)\b|"
    r"\bich\s+stell\w*\s+sie\s+(?:jetzt\s+)?(?:zu\s+[^.!?]{1,40}\s+)?durch\b|"
    r"\bich\s+leit\w*\s+(?:die\s+verbindung|sie)\s+(?:jetzt\s+)?ein\b|"
    r"\bich\s+stell\w*\s+(?:die\s+)?verbindung\s+(?:jetzt\s+)?her\b|"
    r"\bsie\s+(?:werden|sind)\s+(?:jetzt\s+)?(?:durchgestellt|verbunden|weitergeleitet)\b",
    re.I,
)
_CLAIM_NOTIZ = re.compile(
    r"\b(?:notiz|vermerk)\w*\b[^.!?]{0,60}\b"
    r"(?:gemacht|hinterlegt|geschrieben|erstellt|angelegt|notiert|vermerkt|"
    r"ausgerichtet|weitergeleitet|weitergegeben)\b|"
    r"\bde[mr]\s+(?:team|doktor|arzt|ärztin|aerztin|praxis)\b[^.!?]{0,30}"
    r"\b(?:vorleg\w*|weitergeb\w*|ausricht\w*)|"
    # C1 (17.09.2026, Blessing-Anruf 53986f42): "Ich habe alles notiert." /
    # "Das habe ich mir notiert." / "Ihren Wunsch habe ich festgehalten." /
    # "Ich gebe das an die Praxis weiter." — ohne Notiz-Werkzeug; der Anrufer
    # legte auf und wartete auf einen Termin, den niemand kannte. Bewusst NUR
    # das Anliegen als Objekt (alles/das/es/Wunsch/Anliegen): "Ich habe Ihre
    # Nummer vermerkt" ist Datenaufnahme (test_kurzes_notiert_…) und bleibt.
    r"\bhab(?:e)?\s+(?:ich\s+)?(?:mir\s+)?(?:das|es|alles|"
    r"ihren?\s+(?:wunsch|anliegen|termin\w*)|den\s+(?:termin)?wunsch|das\s+anliegen)"
    r"\s+(?:so\s+|jetzt\s+)?(?:notiert|vermerkt|festgehalten|aufgeschrieben)\b|"
    r"\b(?:das|es|alles|ihren?\s+(?:wunsch|anliegen)|den\s+(?:termin)?wunsch)\s+hab(?:e)?\s+ich\s+"
    r"(?:mir\s+)?(?:so\s+|jetzt\s+)?(?:notiert|vermerkt|festgehalten|aufgeschrieben)\b|"
    r"\b(?:gebe|leite|reiche|richte)\s+(?:ich\s+)?(?:das|es|ihr\w*\s+\w+|alles|den\s+wunsch)"
    r"[^.!?]{0,30}\b(?:an\s+die\s+praxis|ans\s+team|an\s+das\s+team|"
    r"an\s+(?:den|die)\s+(?:doktor|arzt|ärztin|aerztin)|dem\s+team|der\s+praxis)"
    r"[^.!?]{0,15}\b(?:weiter|aus)\b",
    re.I,
)
_CLAIM_ANLEGEN = re.compile(
    r"\b(?:akte|patient(?:enakte)?|kartei)\b[^.!?]{0,30}\b"
    r"(?:angelegt|aufgenommen|erfasst)\b|"
    r"\b(?:angelegt|aufgenommen|erfasst)\b[^.!?]{0,30}\b"
    r"(?:als\s+patient|in\s+(?:unsere[rm]?\s+)?kartei)\b",
    re.I,
)

_STUNDEN_WORT = (
    r"(?:ein|eins|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn|elf|"
    r"zwölf|zwoelf|dreizehn|vierzehn|fünfzehn|fuenfzehn|sechzehn|siebzehn|"
    r"achtzehn|neunzehn|zwanzig)"
)
_ZEIT_MARK = re.compile(
    r"\b(?:heute|morgen|übermorgen|uebermorgen|montag|dienstag|mittwoch|"
    r"donnerstag|freitag|samstag|sonntag|januar|februar|märz|maerz|april|"
    r"mai|juni|juli|august|september|oktober|november|dezember)\b|"
    r"\b\d{1,2}(?::\d{2})?\s*uhr\b|\b\d{1,2}\.\d{1,2}\.|\b\d{4}-\d{2}-\d{2}\b|"
    # Gesprochene Uhrzeit ("um neun Uhr dreißig", "halb zehn") — das Modell
    # schreibt Zahlwoerter, nicht nur Ziffern (C1, Anruf 53986f42).
    r"\b(?:halb\s+)?" + _STUNDEN_WORT + r"\s+uhr\b|"
    r"\b(?:um|gegen)\s+(?:halb\s+|viertel\s+(?:vor|nach)\s+)?" + _STUNDEN_WORT + r"\b",
    re.I,
)
_CLAIM_SLOT_POSITIV = re.compile(
    r"\b(?:frei|verfügbar|verfuegbar|möglich|moeglich|offen)\b|"
    # C1 (17.09.2026, Blessing-Anruf 53986f42): "Ich habe für morgen,
    # Mittwoch, den sechzehnten September, einen Termin um neun Uhr dreißig."
    # — getFreeTimeSlots lief nie. Die volle Datumsphrase (Wochentag +
    # Ordinalzahl + Monat) liegt jenseits der alten 50 Zeichen; 90 reichen.
    r"\b(?:habe|hätte|haette|sehe|finde|biete|schlage)\b[^.!?]{0,90}"
    r"\b(?:termin|slot|platz|zeit)\b|"
    r"\b(?:termin|slot|platz)\b[^.!?]{0,35}\b(?:anbieten|vorschlagen)\b|"
    # "Ich kann Ihnen morgen um neun Uhr dreißig anbieten." — Uhrzeit +
    # Angebotsverb, ohne dass das Wort Termin faellt.
    r"\buhr\b[^.!?]{0,30}\b(?:anbieten|vorschlagen|freihalten|reservieren)\b|"
    r"\b(?:anbieten|anbiete|vorschlagen)\b[^.!?]{0,30}\buhr\b|"
    # getrennte Partikel: "Ich schlage Ihnen Donnerstag um halb zehn vor."
    r"\bschlage\b[^.!?]{0,60}\bvor\b|\bbiete\b[^.!?]{0,60}\ban\b",
    re.I,
)
# Echo statt Behauptung: das Modell spiegelt den WUNSCH des Anrufers ("Sie
# möchten morgen um neun — ich schaue nach", "Verstanden: Termin am Montag").
# Das ist eine Aussage ueber das Gehoerte, nicht ueber den Kalender. Gilt nur
# ohne Frei-Wort im Satz: "Ich schaue nach: morgen um neun ist frei" bleibt
# eine Behauptung — und ein nacktes "Ich habe morgen um neun einen Termin fuer
# Sie" ebenso, auch wenn der Anrufer genau das gewuenscht hatte.
_SLOT_ECHO = re.compile(
    r"\b(?:verstanden|verstehe|gewünscht|gewuenscht|wünschen|wuenschen|"
    r"möchten|moechten|hätten\s+sie\s+gern|haetten\s+sie\s+gern|wollen\s+sie|"
    r"schau(?:e|en|t)?|prüf(?:e|en)?|pruef(?:e|en)?|such(?:e|en)?|guck(?:e|en)?|"
    r"sie\s+(?:sagten|meinten|hatten|nannten))\b",
    re.I,
)
_FREI_WORT = re.compile(
    r"\b(?:frei|verfügbar|verfuegbar|buchbar|möglich|moeglich|offen)\b", re.I)
# C1 (53986f42): "Wir sehen uns morgen — bis dann!" / "Bis morgen um neun!" /
# "Dann bis Mittwoch." — der Abschied setzt einen Termin voraus, den es ohne
# Buchung nicht gibt. Der Anrufer legt auf und kommt. Ein nacktes "Bis dann!"
# oder "Auf Wiederhören" traegt keinen Zeitanker und bleibt Abschied.
_CLAIM_WIEDERSEHEN = re.compile(
    r"\b(?:(?:wir\s+)?sehen\s+(?:wir\s+)?(?:uns|sie)\s+(?:dann\s+|also\s+|ja\s+)?(?:am\s+|um\s+)?|"
    r"(?:dann\s+|also\s+|und\s+|na\s+)?bis\s+(?:dann\s+)?(?:am\s+|zum\s+)?|"
    r"(?:wir\s+)?erwarten\s+sie\s+(?:dann\s+)?(?:am\s+|um\s+)?|"
    r"freuen\s+uns\s+auf\s+(?:sie\s+)?(?:am\s+|um\s+)?)"
    r"(?:morgen|übermorgen|uebermorgen|montag|dienstag|mittwoch|donnerstag|freitag|"
    r"samstag|sonnabend|sonntag|nächste\s+woche|naechste\s+woche|"
    r"\d{1,2}(?::\d{2})?\s*uhr|(?:halb\s+)?" + _STUNDEN_WORT + r"\s+uhr)\b",
    re.I,
)
# C1 (53986f42): "Ich habe Sie gefunden." / "Sie sind bei uns hinterlegt." /
# "Ich habe Ihre Akte hier." — ohne Patientensuche, ohne erkannten Anrufer.
# Die Kartei-FRAGEN ("Waren Sie schon einmal bei uns?", "Habe ich Sie richtig
# erkannt?") bleiben Fragen; Verneinungen faengt _GEFUNDEN_NEIN.
_CLAIM_GEFUNDEN = re.compile(
    r"\bhab(?:e)?\s+(?:ich\s+)?(?:sie|ihre\s+(?:akte|kartei|daten|karteikarte)|ihren\s+datensatz)\s+"
    r"(?:jetzt\s+|hier\s+|schon\s+|bereits\s+|auch\s+|im\s+system\s+|in\s+der\s+kartei\s+)*"
    r"(?:gefunden|vorliegen|da|hier)\b|"
    r"\b(?:sie|ihre\s+(?:akte|daten))\s+(?:sind|ist)\s+(?:bei\s+uns\s+)?"
    r"(?:im\s+system\s+|in\s+der\s+kartei\s+|als\s+patient\w*\s+)?"
    r"(?:hinterlegt|gespeichert|angelegt|erfasst|bekannt|vorhanden)\b|"
    r"\bich\s+sehe\s+(?:sie|ihre\s+akte|ihre\s+daten)\s+(?:hier|im\s+system|in\s+der\s+kartei)\b|"
    r"\bda\s+hab(?:e)?\s+ich\s+sie\b|"
    # Inversion: "Ihre Akte habe ich hier vorliegen."
    r"\b(?:ihre\s+(?:akte|kartei|karteikarte|daten)|ihren\s+datensatz)\s+hab(?:e)?\s+ich\s+"
    r"(?:hier\s+|jetzt\s+|schon\s+|bereits\s+|auch\s+)*(?:gefunden|vorliegen|da|hier|offen)\b",
    re.I,
)
_GEFUNDEN_NEIN = re.compile(
    r"\b(?:nicht|leider|nirgends|kein\w*|noch\s+nicht)\b", re.I)
_CLAIM_SLOT_NEGATIV = re.compile(
    r"\b(?:kein(?:e[rmn]?|en)?|nicht\s+ein)\s+(?:weiterer?\s+|freie[rmn]?\s+)?"
    r"(?:termin|slot|platz)\b|"
    r"\b(?:nichts|kein(?:e[rmn]?|en)?)\s+(?:mehr\s+)?frei\b|"
    r"\bkalender\b[^.!?]{0,30}\b(?:voll|ausgebucht)\b",
    re.I,
)
_CLAIM_BESTAND_NEGATIV = re.compile(
    r"\b(?:sie|du)\s+hab(?:en|t)\s+(?:aktuell\s+|derzeit\s+|noch\s+)?"
    r"kein(?:en|e)?\s+(?:kommenden\s+|weiteren\s+|anderen\s+)?termin\b|"
    # Inversion nach Zeitangabe: "Im Oktober haben Sie keinen Termin" (9dd61a59).
    r"\bhab(?:en|t)\s+(?:sie|du)\s+(?:aktuell\s+|derzeit\s+|noch\s+|da\s+|dann\s+)?"
    r"kein(?:en|e)?\s+(?:kommenden\s+|weiteren\s+|anderen\s+)?termin\b|"
    r"\bich\s+(?:sehe|finde)\b[^.!?]{0,45}\bkein(?:en|e)?\s+"
    r"(?:kommenden\s+|weiteren\s+|anderen\s+)?termin\b|"
    r"\b(?:sehe|finde)\s+ich\b[^.!?]{0,45}\bkein(?:en|e)?\s+"
    r"(?:kommenden\s+|weiteren\s+|anderen\s+)?termin\b|"
    r"\bkein(?:e|en)?\s+(?:weiteren?|anderen?|kommenden?)\s+termine?\b",
    re.I,
)
_CLAIM_BESTAND_POSITIV = re.compile(
    r"\b(?:ihr|der)\s+(?:nächste[rn]?|naechste[rn]?|andere[rn]?|kommende[rn]?)\s+"
    r"termin\b[^.!?]{0,45}\b(?:ist|steht|findet)\b|"
    r"\bich\s+sehe\b[^.!?]{0,50}\b(?:ihren|einen)\s+(?:kommenden\s+)?termin\b",
    re.I,
)
_CLAIM_SMS = re.compile(
    r"\b(?:bestätigungs|bestaetigungs)?-?sms\b[^.!?]{0,55}\b"
    r"(?:kommt|geht|erhalten|bekommen|geschickt|gesendet|verschickt)\b|"
    r"\b(?:geschickt|gesendet|verschickt)\b[^.!?]{0,35}\b"
    r"(?:bestätigungs|bestaetigungs)?-?sms\b|"
    r"\b(?:sie|du)\s+(?:bekommen|erhalten)\b[^.!?]{0,35}\b"
    r"(?:bestätigungs|bestaetigungs)?-?sms\b",
    re.I,
)
_CLAIM_RUECKRUF = re.compile(
    r"\b(?:praxis|team|arzt|ärztin|aerztin|doktor)\b[^.!?]{0,45}"
    r"\b(?:meldet\s+sich|ruft\s+(?:sie\s+)?zurück|ruft\s+(?:sie\s+)?zurueck)\b|"
    r"\bich\s+rufe\s+sie\s+(?:zurück|zurueck)\b|"
    r"\brückruf\w*\b[^.!?]{0,45}\b(?:angelegt|eingetragen|notiert|"
    r"weitergegeben|vermerkt|veranlasst)\b",
    re.I,
)
_TRANSFER_WUNSCH = re.compile(
    r"\b(?:verbind\w*|durchstell\w*|weiterleit\w*|ans?\s+telefon|"
    r"an\s+den\s+apparat)\b|"
    r"\bmit\s+(?!(?:ihnen|dir|euch|bianca)\b)[^.!?]{1,45}\bsprechen\b|"
    r"\b(?:doktor|arzt|ärztin|aerztin|frau|herr|mitarbeiter\w*|"
    r"anmeldung|empfang|praxisleitung)\b[^.!?]{0,35}\bsprechen\b",
    re.I,
)


def _ok(ein: Any) -> bool:
    return bool(isinstance(ein, dict) and (ein.get("ok") or ein.get("booked")))


def _ev_buchen(sit: dict) -> bool:
    return _ok(sit.get("lastBook"))


def _ev_absagen(sit: dict) -> bool:
    return _ok(sit.get("lastCancel"))


def _ev_verschieben(sit: dict) -> bool:
    return _ok(sit.get("lastMove"))


def _ev_transfer(sit: dict) -> bool:
    ziel = sit.get("weiterleitungZiel")
    return bool(isinstance(ziel, dict) and str(ziel.get("nummer") or "").strip())


def _ev_notiz(sit: dict) -> bool:
    if _ok(sit.get("lastNote")):
        return True
    return any(
        isinstance(ein, dict)
        and ein.get("name") in {"note_appointment", "praxis_notiz"}
        and _ok(ein)
        for ein in (sit.get("tools") or [])
    )


def _ev_anlegen(sit: dict) -> bool:
    return _ok(sit.get("lastCreate")) or _ok(sit.get("lastBook"))  # book legt Neupatient mit an


def _nur_ziffern(wert: Any) -> str:
    """Nummer auf vergleichbare Ziffern bringen (+49 177… == 0177…)."""
    d = "".join(c for c in str(wert or "") if c.isdigit())
    if d.startswith("0049"):
        d = d[4:]
    elif d.startswith("49") and len(d) >= 11:
        d = d[2:]
    return d.lstrip("0")


def _ev_nummer(sit: dict) -> bool:
    """Nur ein gelaufener Schreibvorgang belegt eine gespeicherte Nummer:
    masUpdatePatientPhone (update_phone), eine neue Akte (die traegt die
    Nummer) oder eine geglueckte Buchung (Neupatient wird mit angelegt).

    Belegt ist die Aussage ausserdem, wenn in der Akte schon eine Nummer
    steht und es genau die ist, die Bianca in der Hand hat — dann ist
    "Ihre Nummer ist hinterlegt" keine Behauptung, sondern der Kartei-Stand
    (Bianca fragt selbst nach der "hinterlegten Nummer")."""
    if _ok(sit.get("lastCreate")) or _ok(sit.get("lastBook")):
        return True
    if any(
        isinstance(ein, dict)
        and str(ein.get("name") or "") in {"update_phone", "masUpdatePatientPhone"}
        and _ok(ein)
        for ein in (sit.get("tools") or [])
    ):
        return True
    s = sit.get("sammler")
    if not isinstance(s, dict):
        return False
    akte = _nur_ziffern(s.get("aktePhone"))
    if not akte:
        return False
    gesagt = _nur_ziffern(s.get("telefon"))
    return not gesagt or gesagt == akte


def _letztes_tool(sit: dict, namen: set[str]) -> dict:
    for ein in reversed(sit.get("tools") or []):
        if isinstance(ein, dict) and str(ein.get("name") or "") in namen:
            return ein
    return {}


def _ev_slot_positiv(sit: dict) -> bool:
    # Eine geglueckte Buchung/Verschiebung belegt den genannten Termin ebenso:
    # danach ist `offered` bewusst geleert (flow._buchen), und "Ich habe Ihnen
    # morgen um neun den Termin eingetragen" waere sonst ein Phantom-Slot.
    if _ev_buchen(sit) or _ev_verschieben(sit):
        return True
    tool = _letztes_tool(sit, {"getFreeTimeSlots", "offer_slots"})
    return bool(_ok(tool) and int(tool.get("resultCount") or 0) > 0 and sit.get("offered"))


def _ev_gefunden(sit: dict) -> bool:
    """Ein 'Ich habe Sie gefunden' ist belegt, wenn irgendein ECHTER Weg den
    Patienten geliefert hat: Kartei-Treffer im Sammler (patientId/bekannt aus
    Suche, Anrufer-Check oder Terminliste), der per Rufnummer erkannte Anrufer
    (CF-pre, solange die Identitaet nicht verneint wurde), die im Hintergrund
    geladene Anruferkartei, ein Patienten-Objekt oder gefundene Termine."""
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if _s(s.get("patientId")) or s.get("bekannt"):
        return True
    if s.get("anruferCheck") != "nein":
        anr = sit.get("anrufer")
        if isinstance(anr, dict) and (_s(anr.get("patientId")) or _s(anr.get("nachname"))):
            return True
        kartei = sit.get("anruferKartei")
        if isinstance(kartei, dict) and kartei:
            return True
    pat = sit.get("patient")
    if isinstance(pat, dict) and (_s(pat.get("id")) or _s(pat.get("patientId")) or _s(pat.get("lastName"))):
        return True
    if sit.get("gefunden"):
        return True
    return False


def _ev_wiedersehen(sit: dict) -> bool:
    """'Bis morgen um neun!' setzt einen Termin voraus: geglueckte Buchung/
    Verschiebung oder ein wirklich gefundener Bestandstermin (Auskunft)."""
    if _ev_buchen(sit) or _ev_verschieben(sit):
        return True
    # sit['gefunden'] / 'upcoming' fuellen nur echte Kalender-Lesewege
    # (agentFindPatientAppointments, Tagesabfrage, Anruferkartei).
    return bool(_termin_isos(sit))


def _ev_slot_negativ(sit: dict) -> bool:
    tool = _letztes_tool(sit, {"getFreeTimeSlots", "offer_slots"})
    return bool(
        _ok(tool)
        and "resultCount" in tool
        and int(tool.get("resultCount") or 0) == 0
    )


def _ev_bestand(sit: dict, *, leer: bool) -> bool:
    tool = _letztes_tool(
        sit, {"agentFindPatientAppointments", "list_appointments"})
    if not _ok(tool) or tool.get("notFound") or tool.get("mehrdeutig"):
        return False
    if "resultCount" not in tool:
        return False
    anzahl = int(tool.get("resultCount") or 0)
    return anzahl == 0 if leer else anzahl > 0


def _termin_isos(sit: dict) -> list[str]:
    """ISO-Startzeiten der zuletzt GEFUNDENEN Bestandstermine (verwalten legt
    sie in sit['gefunden'] ab; Rueckfall: upcoming)."""
    aus: list[str] = []
    for a in (sit.get("gefunden") or sit.get("upcoming") or []):
        if isinstance(a, dict):
            iso = str(a.get("iso") or a.get("start") or a.get("startIso") or "")
        else:
            iso = str(a or "")
        if iso:
            aus.append(iso)
    return aus


def _iso_im_zeitraum(iso: str, w: dict) -> bool:
    """Faellt der Termin in den im Satz genannten Zeitraum (Datum, von..bis,
    Wochentag)? Konservativ: bei unlesbarem ISO gilt 'ja' (Behauptung bleibt
    unbelegt)."""
    try:
        from kern.slots import _weekday_of
        tag = str(iso)[:10]
        if len(tag) != 10:
            return True
        if w.get("date") and tag != str(w["date"])[:10]:
            return False
        if w.get("von") and tag < str(w["von"])[:10]:
            return False
        if w.get("bis") and tag > str(w["bis"])[:10]:
            return False
        if w.get("weekday") is not None and _weekday_of(tag) != int(w["weekday"]):
            return False
        return True
    except Exception:
        return True


def _zeitraum_negativ_belegt(sit: dict, satz: str) -> bool:
    """W-BESTAND-ANSAGE (Anruf 9dd61a59): 'Im Oktober haben Sie keinen Termin'
    ist WAHR, wenn die Terminsuche lief und KEINER der gefundenen Termine in den
    genannten Zeitraum faellt — auch wenn es andere Termine gibt. Ohne Zeitbezug
    im Satz gilt weiter die harte Regel (leer=True)."""
    tool = _letztes_tool(
        sit, {"agentFindPatientAppointments", "list_appointments"})
    if not _ok(tool) or tool.get("notFound") or tool.get("mehrdeutig"):
        return False
    if "resultCount" not in tool:
        return False
    try:
        from kern.slots import parse_slot_wish
        w = parse_slot_wish(satz) or {}
    except Exception:
        return False
    if not (w.get("date") or w.get("von") or w.get("bis") or w.get("weekday") is not None):
        return False
    if w.get("date") and w.get("weekday") is not None and not (w.get("von") or w.get("bis")):
        # Wochentag + daraus abgeleitetes Datum: das Datum reicht.
        w = dict(w, weekday=None)
    return not any(_iso_im_zeitraum(iso, w) for iso in _termin_isos(sit))


def _ev_sms(sit: dict) -> bool:
    buch = sit.get("lastBook")
    return bool(_ok(buch) and not (buch or {}).get("verificationFailed"))


# (Name, Behauptungs-Regex, Evidenz-Praedikat)
AKTIONEN: list[tuple[str, re.Pattern, Callable[[dict], bool]]] = [
    ("buchen", _CLAIM_BUCHEN, _ev_buchen),
    ("absagen", _CLAIM_ABSAGEN, _ev_absagen),
    ("verschieben", _CLAIM_VERSCHIEBEN, _ev_verschieben),
    ("transfer", _CLAIM_TRANSFER, _ev_transfer),
    ("notiz", _CLAIM_NOTIZ, _ev_notiz),
    ("anlegen", _CLAIM_ANLEGEN, _ev_anlegen),
    ("nummer", _CLAIM_NUMMER, _ev_nummer),
    ("gefunden", _CLAIM_GEFUNDEN, _ev_gefunden),
]


def modus() -> str:
    v = (os.environ.get("FAKTEN_WACHE") or "off").strip().lower()
    return v if v in {"off", "shadow", "enforce"} else "off"


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def unbelegte_behauptung(
    sit: dict, text: str, *, nutzertext: str | None = None
) -> str:
    """Erste Erledigt-Behauptung ohne passende Tool-Evidenz — sonst ''.

    Reine Fragen ('soll ich eintragen?') zaehlen nicht. Konkrete
    Slotangebote und Tatsachenbehauptungen mit angehängter Frage schon.
    """
    t = _s(text)
    if not t:
        return ""
    for satz in _SATZ.split(t):
        st = satz.strip()
        if not st:
            continue
        st_slot = st
        if _CLAIM_BESTAND_NEGATIV.search(st):
            if (not _ev_bestand(sit, leer=True)
                    and not _zeitraum_negativ_belegt(sit, st)):
                return "bestand"
            # Belegte Bestands-Aussage ("Im Oktober haben Sie keinen Termin"):
            # ihr "keinen Termin" ist KEIN Slot-Claim — sonst schlug die
            # Slot-Wache ohne Slotsuche zu (Anruf 9dd61a59, W-BESTAND-ANSAGE).
            st_slot = _CLAIM_BESTAND_NEGATIV.sub(" ", st)
        if (_CLAIM_BESTAND_POSITIV.search(st)
                and not _ev_bestand(sit, leer=False)
                and not _ev_buchen(sit) and not _ev_verschieben(sit)):
            # Eine eben geglueckte Buchung/Verschiebung IST der Bestandstermin.
            return "bestand"
        if (_CLAIM_SLOT_NEGATIV.search(st_slot) and not _ev_slot_negativ(sit)):
            return "slots"
        # Echo des Wunsches ("Verstanden: Termin am Montag — ich schaue nach")
        # ist keine Kalender-Aussage, solange kein Frei-Wort dabeisteht.
        echo = bool(_SLOT_ECHO.search(st_slot)) and not _FREI_WORT.search(st_slot)
        if (not echo and _ZEIT_MARK.search(st_slot)
                and _CLAIM_SLOT_POSITIV.search(st_slot)
                and not _ev_slot_positiv(sit)):
            return "slots"
        if _CLAIM_SMS.search(st) and not _ev_sms(sit):
            return "sms"
        if _CLAIM_RUECKRUF.search(st) and not _ev_notiz(sit):
            return "rueckruf"
        # "Bis morgen um neun!" / "Wir sehen uns Montag" setzt einen Termin
        # voraus — ohne Buchung/Verschiebung/gefundenen Bestandstermin ist der
        # Abschied selbst die Erfindung (Anruf 53986f42: verabschiedet mit
        # Termin, nie gesucht, nie gebucht).
        if _CLAIM_WIEDERSEHEN.search(st) and not _ev_wiedersehen(sit):
            return "wiedersehen"
        if _REINE_FRAGE.search(st):
            continue
        for name, cre, ev in AKTIONEN:
            if not cre.search(st):
                continue
            if name == "transfer" and nutzertext is not None:
                if not _TRANSFER_WUNSCH.search(_s(nutzertext)):
                    return "transfer"
            if name == "gefunden" and _GEFUNDEN_NEIN.search(st):
                # "Ich habe Sie leider nicht gefunden" ist ehrlich — keine Behauptung.
                continue
            if not ev(sit):
                return name
    return ""
