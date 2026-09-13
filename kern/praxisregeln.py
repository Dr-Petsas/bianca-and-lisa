"""Kompakte, DB-gesteuerte Praxisregeln fuer kritische Sonderwege.

Die Pickadoc-CF liefert aktuell nur einen Teil der Agent-Promptfelder an
TelefonKI. Kritische Praxisregeln tragen deshalb einen kurzen Marker in einem
tatsaechlich uebertragenen Promptfeld. Der feste Flow erkennt den Marker und
setzt die Regel deterministisch um; ohne Marker bleibt jede andere Praxis
byte-identisch.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from kern import fachprofil


NOTFALL_MARKER = "NOTFALL-SOFORTREGEL"
DOKUMENT_MARKER = "DOKUMENT-VORSPRACHEREGEL"
TZ = ZoneInfo("Europe/Berlin")

_LEBENSGEFAHR_RE = re.compile(
    r"\batemnot\b|pfeifende?\s+atmung|enge\s+im\s+hals|"
    r"(?:zunge|mund|hals)[^.!?]{0,30}geschwollen|"
    r"kreislauf(?:kollaps|zusammenbruch)|bewusstlos|krampf(?:artig|anfall)|"
    r"gro(?:ß|ss)fl(?:ä|ae)chige?\s+hautabl(?:ö|oe)sung|"
    r"blutige?\s+lippen|schleimhaut[^.!?]{0,30}(?:blutig|abl(?:ö|oe)s)|"
    r"schwere?\s+(?:arzneimittel|medikamenten)(?:reaktion|allergie)",
    re.I,
)
# Fix 3 (13.09.2026, Feldtest-Analyse): „dringend"/„sofort"/„heute
# unbedingt" standen hier als eigenstaendige Notfall-Marker. Damit wurde
# „Ich brauche dringend einen Termin", „Ich muss den Termin sofort absagen"
# oder „Stellen Sie mich sofort durch" zum Akutfall: Buchung/Absage
# abgebrochen, „Kommen Sie jetzt direkt in die Praxis". Dringlichkeit
# zaehlt jetzt NUR zusammen mit einem Beschwerde-Wort im selben Satz
# (_DRINGLICHKEIT_RE + _BESCHWERDE_RE in akut()). Die Symptom-Muster unten
# und notfall/akut bleiben unveraendert eigenstaendig.
_DRINGLICHKEIT_RE = re.compile(
    r"\bdringend\w*|\bsofort\b|heute\s+unbedingt|schnellstm(?:ö|oe)glich|"
    r"so\s+schnell\s+wie\s+m(?:ö|oe)glich|\beilig\b|ganz\s+schnell|umgehend",
    re.I,
)
_BESCHWERDE_RE = re.compile(
    r"\bhaut(?!arzt|(?:ä|ae)rzt)\w*|ausschlag|ekzem|\bfleck\w*|pustel\w*|pickel|"
    r"quaddel\w*|\bblasen?\b|juck\w*|brenn\w*|schmerz\w*|\bweh\b|wehtut|"
    r"tut\s+(?:\w+\s+)?weh|schwell\w*|geschwollen|entz(?:ü|ue)nd\w*|eiter\w*|"
    r"\bblut(?:et|en|ung\w*|ig\w*)\b|wunde\w*|n(?:ä|ae)ssend\w*|offene?\s+stelle|"
    r"fieber|allergi\w*|reaktion|muttermal\w*|leberfleck\w*|"
    r"(?:fleck|muttermal|stelle|haut)\w*[^.!?]{0,30}(?:ver(?:ä|ae)nder|w(?:ä|ae)chst|gr(?:ö|oe)(?:ß|ss)er)|"
    r"g(?:ü|ue)rtelrose|herpes|zecke\w*|sonnenbrand|verbrenn\w*|verbr(?:ü|ue)h\w*|"
    r"\b(?:insekten|m(?:ü|ue)cken|wespen|bienen)?stich(?:e|es|en)?\b|gestochen|"
    r"gebissen|\bbiss\b|infekt\w*|beschwerden|symptom\w*|"
    r"breitet\s+sich\s+aus|ausgebreitet",
    re.I,
)
_AKUT_RE = re.compile(
    r"\bnotfall\b|\bakut\w*|"
    r"pl(?:ö|oe)tzlich[^.!?]{0,50}(?:haut|ausschlag|fleck|ver(?:ä|ae)nder)|"
    r"schnell[^.!?]{0,30}(?:schlimmer|ausbreit)|"
    r"starke?\s+(?:schmerz|brennen|juckreiz)|nicht\s+aus(?:zu)?halten|"
    r"(?:gesicht|lippe|augenlid|hals)[^.!?]{0,30}(?:schwell|geschwollen)|"
    r"\bblasen\b|n(?:ä|ae)ssende?\s+fl(?:ä|ae)che|offene?\s+stelle|eitrig|"
    r"hautausschlag[^.!?]{0,40}(?:fieber|kreislauf|krankheitsgef(?:ü|ue)hl)|"
    r"g(?:ü|ue)rtelrose|akute?\s+allergische?\s+reaktion|"
    r"(?:wunde|infektion)[^.!?]{0,40}(?:eingriff|operation|praxis)|"
    r"kind[^.!?]{0,40}(?:ausgedehnt|ganze[rm]?\s+k(?:ö|oe)rper)[^.!?]{0,30}ausschlag",
    re.I,
)
_VERNEINT_RE = re.compile(
    r"\b(?:kein|keine|nicht)\s+(?:akut\w*|notfall|dringend)\b", re.I)
_UHRFRAGE_RE = re.compile(
    r"\bwann\b|welche\s+uhrzeit|um\s+wie\s+viel\s+uhr|feste?\s+uhrzeit",
    re.I,
)
_REZEPT_UEBERWEISUNG_RE = re.compile(
    r"\b(?:(?:folge|dauer|privat|kassen)[-\s]?)?rezept(?:e|es|en)?\b|"
    r"\brezept(?:wunsch|bestell\w*|abhol\w*|verlänger\w*|verlaenger\w*)\b|"
    r"\b(?:ü|ue)berweisung\w*|(?:ü|ue)berweisen",
    re.I,
)
# Zahnaerztliche Unterlagen, die HERAUSGEGEBEN werden koennten (Dienstweg):
# Roentgenbilder/-aufnahmen, Befundberichte, Behandlungsunterlagen. Bewusst
# NICHT „Befundbesprechung"/„Roentgentermin" — das sind Termine (Fix 1,
# 13.09.2026: die alte Form `befund\w*` fing jede Befundbesprechung ab).
_DENTAL_UNTERLAGEN_RE = re.compile(
    r"\b(?:r(?:ö|oe)ntgen(?:bild\w*|aufnahme\w*|unterlagen|befund\w*)?"
    r"|befund(?:e|s|es|bericht\w*|unterlagen|bilder?|kopie\w*)?"
    r"|behandlungsunterlagen|unterlagen|patientenakte|krankenakte)\b",
    re.I,
)

# Der Anrufer WILL ein Dokument bekommen/ausgestellt/geschickt haben. Ohne
# ein solches Anforderungs-Verb ist die blosse Nennung („Rezept", „Roentgen")
# kein Dokumentwunsch — z. B. „Termin zum Roentgen", „Befundbesprechung".
_ANFORDERUNG_RE = re.compile(
    r"\b(?:brauch\w*|br(?:ä|ae)uchte\w*|ben(?:ö|oe)tig\w*"
    r"|h(?:ä|ae)tte?n?\s+(?:\w+\s+){0,3}?gern\w*"
    r"|m(?:ö|oe)chte\w*|will|wollte\w*|wollen|bitte\s+um|bestell\w*"
    r"|abhol\w*|verl(?:ä|ae)nger\w*|ausstell\w*|ausgestellt|verschreib\w*|aufschreib\w*"
    r"|(?:zu|r(?:ü|ue)ber|zur(?:ü|ue)ck|nach)?schick\w*|(?:zu)?send\w*|(?:zu)?mail\w*"
    r"|fax\w*|bekomm\w*|krieg\w*|erhalt\w*|mitgeb\w*|mitnehm\w*|hinterleg\w*"
    r"|fertig\s*mach\w*|bereitleg\w*|kopie\w*|anforder\w*|beantrag\w*"
    r"|abgelaufen|aufgebraucht|alle\b|leer\b"
    r"|neue[sn]?\s+(?:rezept|(?:ü|ue)berweisung|verordnung|attest)"
    r"|noch\s+(?:ein\w*|mal)\s+(?:ein\w*\s+)?(?:rezept|(?:ü|ue)berweisung|verordnung))",
    re.I,
)

# Der Anrufer HAT eine Ueberweisung (vom Hausarzt/Kollegen) — das ist ein
# Buchungsgrund, kein Dokumentwunsch. Gewinnt gegen die Anforderung.
_HAT_UEBERWEISUNG_RE = re.compile(
    r"(?:ü|ue)berwiesen"
    r"|(?:ü|ue)berweisung\w*\s+(?:von|vom|durch|des|der|meine[rs]|aus|liegt|dabei|mitgebracht)\b"
    r"|\b(?:hab(?:e|en)?|hatte|hat|liegt|bring\w*)\s+(?:\w+\s+){0,3}?"
    r"(?:eine|die|ne|meine|schon\s+eine|bereits\s+eine|so\s+eine)\s+(?:ü|ue)berweisung"
    r"|\bmit\s+(?:einer\s+|der\s+|meiner\s+)?(?:ü|ue)berweisung"
    r"|(?:ü|ue)berweisung\w*\s+(?:\w+\s+){0,2}?(?:dabei|mitgebracht|in\s+der\s+hand|vorliegen)",
    re.I,
)

# Terminbezug im Satz — beim Zahnarzt sind „Roentgen"/„Befund" dann Termine
# (Roentgentermin, Befundbesprechung, Aufnahmen machen lassen).
_TERMIN_KONTEXT_RE = re.compile(
    r"\btermin\w*|besprech\w*|kontroll\w*|untersuch\w*|aufnahmen?\s+machen"
    r"|r(?:ö|oe)ntgen\s+(?:lassen|machen)|zum\s+r(?:ö|oe)ntgen|ger(?:ö|oe)ntgt"
    r"|r(?:ö|oe)ntgentermin|vorbeikommen",
    re.I,
)
_WOCHENTAGE = {
    0: "montag", 1: "dienstag", 2: "mittwoch", 3: "donnerstag",
    4: "freitag", 5: "samstag", 6: "sonntag",
}
_ZEIT_RE = re.compile(
    r"(\d{1,2})(?:[:.](\d{2}))?\s*(?:uhr\s*)?(?:-|bis)\s*"
    r"(\d{1,2})(?:[:.](\d{2}))?",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _prompt(tenant: dict | None) -> str:
    return str((tenant or {}).get("dbPrompt") or "")


def notfall_sofort_aktiv(tenant: dict | None) -> bool:
    return NOTFALL_MARKER in _prompt(tenant)


def dokument_vorsprache_aktiv(tenant: dict | None) -> bool:
    return DOKUMENT_MARKER in _prompt(tenant)


def lebensgefahr(text: str) -> bool:
    return bool(_LEBENSGEFAHR_RE.search(_s(text)))


def akut(text: str) -> bool:
    t = _s(text)
    if not t or _VERNEINT_RE.search(t):
        return False
    if lebensgefahr(t) or _AKUT_RE.search(t):
        return True
    # Fix 3: Dringlichkeit allein ist kein Notfall — nur mit Beschwerde-Wort.
    return bool(_DRINGLICHKEIT_RE.search(t) and _BESCHWERDE_RE.search(t))


def praxis_offen(tenant: dict | None, jetzt: datetime | None = None) -> bool | None:
    """Sprechzeiten aus dem DB-Prompt lesen; None, wenn dort keine stehen."""
    now = jetzt or datetime.now(TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    tag = _WOCHENTAGE[now.weekday()]
    prompt = _prompt(tenant)
    zeile = next(
        (z for z in prompt.splitlines() if re.search(rf"\b{tag}\b", z, re.I)),
        "",
    )
    if not zeile:
        # Sind andere Wochentage mit Zeiten gepflegt, ist ein fehlender Tag
        # (typisch Samstag/Sonntag) geschlossen — nie versehentlich "jetzt
        # kommen" sagen. Nur bei ganz fehlendem Stundenplan bleibt es unbekannt.
        hat_plan = any(
            _ZEIT_RE.search(z) and any(
                re.search(rf"\b{wt}\b", z, re.I)
                for wt in _WOCHENTAGE.values()
            )
            for z in prompt.splitlines()
        )
        return False if hat_plan else None
    fenster = list(_ZEIT_RE.finditer(zeile))
    if not fenster:
        return None
    minute = now.hour * 60 + now.minute
    for m in fenster:
        start = int(m.group(1)) * 60 + int(m.group(2) or 0)
        ende = int(m.group(3)) * 60 + int(m.group(4) or 0)
        if start <= minute <= ende:
            return True
    return False


def notfall_antwort(
    tenant: dict | None,
    text: str,
    *,
    jetzt: datetime | None = None,
    bereits_akut: bool = False,
) -> str:
    """Feste, kurze Notfallantwort oder ""."""
    if not notfall_sofort_aktiv(tenant):
        return ""
    t = _s(text)
    if lebensgefahr(t):
        return (
            "Das ist ein medizinischer Notfall. Wählen Sie bitte jetzt die "
            "112."
        )
    if not (akut(t) or (bereits_akut and _UHRFRAGE_RE.search(t))):
        return ""
    offen = praxis_offen(tenant, jetzt)
    if offen is False:
        return (
            "Die Praxis ist gerade geschlossen. Wenden Sie sich bitte an den "
            "ärztlichen Bereitschaftsdienst unter 116 117. Bei Atemnot oder "
            "Kreislaufproblemen wählen Sie sofort die 112."
        )
    return (
        "Das klingt akut. Kommen Sie bitte jetzt direkt in die Praxis. "
        "Dafür gibt es keine feste Uhrzeit; bringen Sie bitte Wartezeit mit. "
        "Sie werden auf jeden Fall so schnell wie möglich gesehen und versorgt."
    )


def dokument_antwort() -> str:
    return (
        "Rezepte und Überweisungen werden nur nach einer Kontrolle oder kurzen "
        "Besprechung mit dem Arzt bereitgestellt. Dafür müssen Sie persönlich "
        "in die Praxis kommen und die Unterlagen persönlich abholen. Eine "
        "dritte Person kann sie grundsätzlich nicht abholen. Bei "
        "schwerwiegenden Umständen, zum Beispiel fehlender Mobilität, muss "
        "die Praxis den Einzelfall vorher prüfen."
    )


def hat_ueberweisung(text: str) -> bool:
    """Der Anrufer HAT eine Ueberweisung / ist ueberwiesen worden — das ist
    ein Buchungsgrund, kein Dokumentwunsch (Fix 1/2, 13.09.2026)."""
    return bool(_HAT_UEBERWEISUNG_RE.search(_s(text)))


def dokument_anforderung(text: str) -> bool:
    """Will der Anrufer ein Rezept/eine Ueberweisung BEKOMMEN (nicht: er hat
    eine und will deshalb einen Termin)? Fix 1, 13.09.2026."""
    t = _s(text)
    if not _REZEPT_UEBERWEISUNG_RE.search(t):
        return False
    if _HAT_UEBERWEISUNG_RE.search(t):
        return False
    return bool(_ANFORDERUNG_RE.search(t))


def unterlagen_antwort(tenant: dict | None, text: str) -> str:
    """Fachsichere Dokumentauskunft; Zahnregeln nie in Derma ausgeben.

    Fix 1 (13.09.2026, Feldtest-Analyse): Vor dem Fix feuerte diese Antwort
    fuer JEDEN Mandanten und bei jeder Nennung von „Rezept"/„Ueberweisung"/
    „Befund" — MedDent/Thaler sprachen Blessings festen Vorsprache-Text
    („Rezepte ... nur persoenlich in der Praxis"), obwohl dort der
    Rueckruf-/Notiz-Weg gilt, und „Ich bin vom Hausarzt ueberwiesen" oder
    „Termin zur Befundbesprechung" wurden mitten in der Buchung als
    Dokumentwunsch abgefangen. Jetzt gilt:

    - Rezept/Ueberweisung-Vorsprache NUR fuer Mandanten mit DB-Marker
      (`dokument_vorsprache_aktiv`, Blessing) und NUR bei echter
      ANFORDERUNG (bekommen/ausstellen/schicken ...); „ich habe eine
      Ueberweisung" ist ein Buchungsgrund und faellt durch.
    - Zahnaerztlicher Dienstweg (Roentgenbilder/Befunde) NUR bei Anforderung
      und OHNE Terminbezug im Satz (Befundbesprechung/Roentgentermin sind
      Termine).
    - Alles andere -> "" -> der normale Weg (Intent/Hirn/ABGEBEN-Notiz).
    """
    t = _s(text)
    if not t:
        return ""
    if _REZEPT_UEBERWEISUNG_RE.search(t):
        if dokument_vorsprache_aktiv(tenant) and dokument_anforderung(t):
            return dokument_antwort()
        # Ueberweisung/Rezept ohne Marker-Mandant oder ohne Anforderung:
        # kein fester Text — Hirn/Flow entscheiden (Notiz, Buchung).
        return ""
    if (
        fachprofil.fach_id(tenant) == "zahnmedizin"
        and _DENTAL_UNTERLAGEN_RE.search(t)
        and _ANFORDERUNG_RE.search(t)
        and not _TERMIN_KONTEXT_RE.search(t)
    ):
        return (
            "Röntgenbilder und Befundunterlagen werden normalerweise über "
            "einen gesicherten Dienstweg direkt an den anfordernden Zahnarzt "
            "versandt. Der nachbehandelnde oder konsiliarisch tätige Zahnarzt "
            "muss sie ausdrücklich anfordern."
        )
    return ""
