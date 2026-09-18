"""W-BUCHUNG-ABBRUCH: der Anrufer will den Termin doch NICHT (17.09.2026).

Befund aus der Auswertung aller Bianca-Anrufe 14.-17.09.2026
(`docs/BEFUND-BIANCA-ALLE-ANRUFE-2026-09-17.md`, A4): 23 Readbacks ("Soll ich
das so eintragen?") ohne Buchung. In 05a5dd55 sagte der Anrufer "Ich mache den
Termin online aus. Danke.", in 31b8842d "Nein." / "Oh ne.", in 4dfc81be "Nein,
danke." — und Bianca fragte bis zu DREIMAL "Was darf ich aendern — Zeitpunkt,
Name, Nummer oder Besuchsgrund?" und liess nicht los. In 66913eb8 kam mitten im
Slot-Angebot "Ich moechte das Telefon beenden, Termin nicht buchen." und die
Antwort war "Ganz kurz bitte. Im Angebot sind: ...".

Ursache: `bianca/flow._aenderung_zug` kannte nur die vier Felder; Ablehnung,
Abschied, "online" und "nicht buchen" waren KEIN Ausgang. `kern/abschied.py`
erkennt bewusst nur Schlussfloskeln, `unterbrechung.ist_abbruch` nur
"hoer auf"-Befehle fuer die Wiedergabe.

Dieses Modul ist nur der ERKENNER (pur, ohne Bianca-Wissen): will der Satz die
laufende Buchung beenden — und auf welche Art? Der Fluss (`bianca/flow.py`)
raeumt dann Slot und Frage, spricht EINEN ehrlichen Schlusssatz und legt bei
einem klaren Ende auf; sonst folgt genau eine registrierte Abschlussfrage.

Bewusst eng: ein falscher Treffer wirft eine halb fertige Buchung weg — das
ist der teurere Fehler. Deshalb:
- FRAGEN sind kein Abbruch ("Kann ich das auch online machen?" will eine
  Antwort, keinen Abbruch).
- "online geht nicht / klappt nicht / nicht online" ist das GEGENTEIL (der
  Anrufer will gerade deshalb am Telefon buchen).
- "doch nicht" allein gilt nur als kurzer Satz (<= 6 Woerter, nur auf die
  Bestaetigungsfrage) — "Ach, doch nicht Dienstag" ist eine Korrektur.
- "noch keinen Termin" / "habe keinen Termin" ist BESITZ, kein Wunsch.
- Absagen/Verschieben eines BESTANDstermins ("Termin absagen") ist kein
  Abbruch der Buchung, sondern ein eigenes Anliegen (Intent/verwalten).

Arten (Rueckgabe von `erkannt`):
- ``"beenden"``  — "Telefon/Gespraech beenden", "ich lege auf": klares Ende.
- ``"online"``   — der Anrufer bucht selbst online.
- ``"spaeter"``  — "ich melde mich", "ich ueberlege es mir", "rufe nochmal an".
- ``"kein_termin"`` — "keinen Termin", "nicht buchen", "lassen Sie es",
  "hat sich erledigt", "kein Interesse", "Nein, danke" (nur auf die
  Bestaetigungsfrage — `auf_bestaetigung=True`).
- ``""`` — kein Abbruch.

Notaus: `BUCHUNG_ABBRUCH=0` => `erkannt` liefert immer "" (Verhalten wie vor
dem 17.09.2026). Tests: `tests/test_buchung_abbruch.py`.
"""

from __future__ import annotations

import os
import re
from typing import Any

_AE = r"(?:ä|ae|a)"

# --- Fragen sind kein Abbruch -------------------------------------------------
# Fragezeichen ODER Fragewort am Anfang ODER Verb-Inversion mit Pronomen
# ("Kann ich ...", "Geht das ..."). "Ist gut, dann online." ist KEINE Frage.
_FRAGE_RE = re.compile(
    r"^\s*(?:(?:ja|nein|nee|ne|ach|hm+|oh|okay|ok|und|aber)\s*,?\s*)*"
    r"(?:wie|wo|wann|was|welche[rsn]?|warum|wieso|weshalb|wof(?:ü|ue)r)\b|"
    r"^\s*(?:(?:ja|nein|nee|ne|ach|hm+|oh|okay|ok|und|aber)\s*,?\s*)*"
    r"(?:kann|k(?:ö|oe)nnte|k(?:ö|oe)nnen|darf|d(?:ü|ue)rfte|geht|ginge|ist|w(?:ä|ae)re|"
    r"gibt|muss|m(?:ü|ue)sste|soll|sollte|haben|hat|w(?:ü|ue)rde|w(?:ü|ue)rden)"
    r"\s+(?:ich|man|es|das|sie|wir|du|der|die|denn)\b",
    re.I,
)

# --- klares Ende des Telefonats ----------------------------------------------
_BEENDEN_RE = re.compile(
    r"\b(?:telefon(?:at)?|gespr{0}ch|anruf|verbindung)\s+(?:jetzt\s+)?(?:bitte\s+)?"
    r"(?:beenden|abbrechen|schlie(?:ß|ss)en)\b|"
    r"\b(?:ich\s+)?(?:lege?|leg)\s+(?:ich\s+)?(?:jetzt\s+|dann\s+|gleich\s+|mal\s+|einfach\s+)*auf\b|"
    r"\b(?:ich\s+)?(?:m(?:ö|oe)chte|will|werde|muss)\s+(?:jetzt\s+|dann\s+)?"
    r"(?:auflegen|schluss\s+machen)\b|"
    r"\bschluss\s+machen\b|\bauflegen\b".format(_AE),
    re.I,
)
_NICHT_AUFLEGEN_RE = re.compile(r"\bnicht\s+(?:gleich\s+|sofort\s+)?auflegen\b", re.I)

# --- der Anrufer bucht selbst online -----------------------------------------
_ONLINE_WORT_RE = re.compile(
    r"\b(?:online|im\s+internet|(?:ü|ue)ber\s+(?:die\s+|das\s+|ihre\s+|eure\s+)?"
    r"(?:webseite|website|homepage|internetseite|internet|app)|"
    r"(?:ü|ue)ber\s+doctolib|bei\s+doctolib|(?:ü|ue)ber\s+pickadoc|bei\s+pickadoc)\b",
    re.I,
)
_ONLINE_TUN_RE = re.compile(
    r"\b(?:mach\w*|buch\w*|ausmach\w*|vereinbar\w*|erledig\w*|reservier\w*|"
    r"eintrag\w*|regel\w*|selbst|selber|lieber|dann|eher|einfach|doch)\b",
    re.I,
)
# Das GEGENTEIL: online ging nicht / klappt nicht — deshalb ruft der Anrufer an.
_ONLINE_GEGEN_RE = re.compile(
    r"\b(?:nicht|nich|kein\w*|nie|niemals|fehler|problem\w*|versucht|probiert|"
    r"gescheitert|leider)\b",
    re.I,
)
# "schon online gemacht/gebucht" = der Termin steht bereits — Buchung eruebrigt sich.
_ONLINE_SCHON_RE = re.compile(
    r"\b(?:schon|bereits)\b.*\b(?:gemacht|gebucht|ausgemacht|vereinbart|reserviert|eingetragen)\b|"
    r"\b(?:gemacht|gebucht|ausgemacht|vereinbart|reserviert|eingetragen)\b.*\b(?:schon|bereits)\b",
    re.I,
)

# --- spaeter / ueberlegen ----------------------------------------------------
_SPAETER_RE = re.compile(
    r"\bich\s+(?:melde|meld)\s+mich\b|"
    r"\b(?:ich\s+)?(?:rufe?|ruf)\s+(?:dann\s+|einfach\s+|lieber\s+|sie\s+)?"
    r"(?:sp{0}ter|nochmal|noch\s+mal|noch\s+einmal|wieder|ein\s+anderes\s+mal|"
    r"morgen|n{0}chste\s+woche|die\s+n{0}chsten\s+tage|in\s+den\s+n{0}chsten\s+tagen)"
    r"(?:\s+(?:noch\s*mal|nochmal|wieder))?\s+(?:noch\s*mal\s+|nochmal\s+)?an\b|"
    r"\bich\s+(?:ü|ue)berleg\w*\s+(?:es\s+|das\s+|mir\s+)*(?:noch|erst|nochmal|noch\s+mal|mal|in\s+ruhe)?\b|"
    r"\bmuss\s+(?:ich\s+)?(?:das\s+|es\s+)?(?:mir\s+)?(?:erst\s+|noch\s+|vorher\s+)+(?:mal\s+)?"
    r"(?:(?:mit|zu\s*hause)\s+\S+(?:\s+\S+)?\s+)?(?:besprechen|abkl{0}ren|kl{0}ren|absprechen|"
    r"(?:ü|ue)berlegen|anschauen|ansehen)\b|"
    r"\b(?:m(?:ö|oe)chte|will)\s+(?:das\s+|es\s+)?(?:mir\s+)?(?:erst\s+|noch\s+|vorher\s+)+(?:mal\s+)?"
    r"(?:(?:mit|zu\s*hause)\s+\S+(?:\s+\S+)?\s+)?(?:besprechen|abkl{0}ren|kl{0}ren|absprechen|"
    r"(?:ü|ue)berlegen|anschauen|ansehen)\b|"
    r"\bich\s+(?:schaue|schau|gucke|guck)\s+(?:erst\s+)?(?:noch\s*mal|nochmal|zuhause|zu\s+hause|in\s+den\s+kalender)\b".format(_AE),
    re.I,
)

# --- gar keinen Termin -------------------------------------------------------
# Besitz-/Zustandsformen ("noch keinen Termin", "habe keinen Termin gefunden")
# sind ausgeschlossen: Lookbehind auf das Wort davor, Lookahead auf das Wort
# danach.
_BESITZ_DAVOR = (
    r"(?<!noch )(?<!bisher )(?<!hab )(?<!habe )(?<!hatte )(?<!haben )(?<!hatten )"
    r"(?<!leider )(?<!derzeit )(?<!aktuell )(?<!sie )(?<!ihr )(?<!wir )(?<!heute )"
    r"(?<!gibt )(?<!gab )(?<!auch )"
)
_BESITZ_DANACH = (
    r"(?!\s*(?:frei|mehr\s+frei|gefunden|bekommen|gekriegt|gehabt|haben|habe|hatte|"
    r"hatten|gebucht|vereinbart|ausgemacht|eingetragen|gemacht|offen|stehen|drin|"
    r"im\s+kalender|dabei|gesehen|angezeigt|verf(?:ü|ue)gbar|mehr\b|da\b|zu\s+haben|"
    r"gekommen|erhalten|bei\s+(?:doktor|dr\b|frau|herrn?|dem|der|ihm|ihr)\b|sondern|"
    # "keinen Termin FUER die Zahnreinigung / ZUR Kontrolle / DAFUER" = Teil-Nein
    r"f(?:ü|ue)r\b|zur\b|zum\b|wegen\b|daf(?:ü|ue)r\b|dazu\b|am\s+(?!telefon)|um\s+\d))"
)
# Verfuegbarkeits-Rede ("es gibt keinen Termin", "haben Sie keinen Termin") —
# das ist der Kalender, nicht der Wunsch des Anrufers.
_VERFUEGBAR_RE = re.compile(
    r"\b(?:gibt|gab|g(?:ä|ae)be|haben\s+sie|hast\s+du|habt\s+ihr|ihr\s+habt|sie\s+haben|"
    r"verf(?:ü|ue)gbar|ausgebucht|voll)\b",
    re.I,
)
_KEIN_TERMIN_RE = re.compile(
    # "moechte/will/brauche ... keinen Termin", "dann/doch/lieber keinen Termin"
    r"\b(?:m(?:ö|oe)chte|will|wollte|brauche?|braucht|dann|doch|lieber|erst\s*mal|erstmal|"
    r"jetzt|momentan|vorerst|also|eigentlich|im\s+moment|zur\s+zeit)\s+"
    r"(?:doch\s+|jetzt\s+|lieber\s+|erst\s*mal\s+|erstmal\s+|gar\s+|momentan\s+|vorerst\s+|"
    r"eigentlich\s+|auch\s+|wirklich\s+)*kein(?:en)?\s+termin\b" + _BESITZ_DANACH + r"|"
    # nackt "keinen Termin" — nur ohne Besitz-Woerter davor/danach
    + _BESITZ_DAVOR + r"\bkein(?:en)?\s+termin\b" + _BESITZ_DANACH + r"|"
    r"\bkein(?:en)?\s+termin\s+(?:mehr\s+)?(?:buchen|machen|ausmachen|vereinbaren|eintragen|"
    r"brauchen|reservieren|festmachen)\b|"
    r"\btermin\s+(?:doch\s+)?(?:jetzt\s+)?(?:bitte\s+)?nicht\s+(?:mehr\s+)?(?:buchen|machen|ausmachen|"
    r"eintragen|vereinbaren|reservieren|festmachen|festhalten)\b|"
    r"\b(?:nichts|nix)\s+(?:eintragen|buchen|reservieren|festmachen|festhalten)\b|"
    r"\bnicht\s+(?:eintragen|buchen|reservieren|festmachen|festhalten)\b(?!\s*(?:lassen|k(?:ö|oe)nnen|kann))|"
    r"\btragen\s+sie\s+(?:bitte\s+)?nichts\s+ein\b|"
    r"\bbrauch\w*\s+(?:ich\s+)?(?:den\s+termin\s+|das\s+)?(?:doch\s+|dann\s+|jetzt\s+)?"
    r"(?:keinen|nicht\s+mehr|gar\s+nicht|nicht)\b(?!\s*(?:nur|mehr\s+als|so|unbedingt\s+heute|"
    r"termin\s+(?:bei|f(?:ü|ue)r|am|um|im)\b))|"
    r"\b(?:lass|lassen)\s+(?:sie\s+)?(?:es|das|den\s+termin)(?:\s+(?:sein|gut|lieber|erst\s*mal|bleiben|"
    r"einfach|weg|mal))?\s*[.!,]?\s*(?:$|\bdanke|\bauf\s+wieder|\btsch)|"
    r"\b(?:vergessen|vergiss)\s+sie\s+(?:es|das|den\s+termin)\b|"
    r"\bhat\s+sich\s+(?:erledigt|er(?:ü|ue)brigt)\b|\berledigt\s+sich\b|"
    r"\bkein\s+interesse\b|\bich\s+verzichte\b|"
    r"\b(?:m(?:ö|oe)chte|will|wollte)\s+(?:doch\s+|jetzt\s+|lieber\s+)?(?:nichts?|keinen\s+termin)\s+"
    r"(?:mehr\s+)?(?:buchen|eintragen|machen|ausmachen|reservieren)\b|"
    r"\b(?:m(?:ö|oe)chte|will)\s+(?:das|den\s+termin|ihn)\s+(?:doch\s+)?nicht\s+mehr\b|"
    r"\bdoch\s+(?:lieber\s+)?nicht\s+(?:buchen|eintragen|machen|reservieren)\b",
    re.I,
)
# Harter Termin-Bezug: nur damit zaehlt ein Abbruch auch auf eine NEBENFRAGE
# der Buchung (PZR, SMS-Nummer, Versicherung ...) — dort meint "Nein, danke" /
# "kein Interesse" / "lieber nicht" die Nebenfrage, nicht den Termin.
_TERMIN_BEZUG_RE = re.compile(
    r"\btermin\w*\b|\b(?:buchen|buchung|eintragen|reservier\w*|festmachen|festhalten)\b",
    re.I,
)
# Nur als KURZER Satz (<= 6 Woerter): "Doch nicht.", "Nein, doch nicht.",
# "Lieber nicht.", "Dann lieber nicht.", "Gar keinen.", "Lieber keinen Termin."
# — Antworten auf die Readback-/Aenderungsfrage. Bewusst nur "keinen" (Termin),
# nicht "keine": "Nein, keine Aenderung" hiesse das Gegenteil.
_KURZ_DOCH_NICHT_RE = re.compile(
    r"^\s*(?:(?:nein|nee|ne|ach|hm+|oh|okay|ok|dann|also)\s*,?\s*)*(?:doch\s+)?(?:dann\s+)?(?:lieber\s+|eher\s+)?(?:doch\s+)?nicht\s*[.!]*\s*$|"
    r"^\s*(?:(?:nein|nee|ne|ach|oh)\s*,?\s*)*doch\s+nicht\s*[.!]*\s*$|"
    r"^\s*(?:(?:nein|nee|ne|ach|oh|dann)\s*,?\s*)*(?:lieber\s+|eher\s+|dann\s+)?(?:gar\s+)?keinen(?:\s+termin)?\s*[.!]*\s*$",
    re.I,
)
# "Nein, danke." / "Danke, nein." / "Nein danke, nicht noetig." — hoefliche
# Ablehnung. NUR auf die Bestaetigungsfrage ("Soll ich das so eintragen?").
_NICHT_NOETIG = (
    r"(?:(?:das\s+)?(?:ist\s+)?nicht\s+n(?:ö|oe)tig|"
    r"(?:das\s+)?(?:brauch\w*|will|m(?:ö|oe)chte)\s+ich\s+nicht)"
)
_NEIN_DANKE_RE = re.compile(
    r"^\s*(?:"
    # "Nein, danke." / "Nein danke, nicht noetig."
    r"(?:nein|nee|ne|n(?:ö|oe))\s*,?\s*(?:danke(?:sch(?:ö|oe)n)?|vielen\s+dank)"
    r"(?:\s*,?\s*" + _NICHT_NOETIG + r")?|"
    # "Nein, nicht noetig." / "Nein, das brauche ich nicht."
    r"(?:nein|nee|ne|n(?:ö|oe))\s*,?\s*" + _NICHT_NOETIG + r"|"
    r"danke\s*,?\s*(?:nein|nee|ne))"
    r"[\s.!,]*(?:auf\s+wiederh(?:ö|oe)ren|tsch(?:ü|ue)ss?|ciao)?[\s.!]*$",
    re.I,
)
# Kurze reine Verneinung ("Nein.", "Oh ne.", "Nee.", "Nö.") — als Antwort auf
# "Was darf ich aendern?" heisst das: nichts, ich will den Termin nicht.
_KURZ_NEGATION_RE = re.compile(
    r"^\s*(?:(?:ach|hm+|oh|okay|ok|also|nein|nee|ne)\s*,?\s*)*"
    r"(?:nein|nee|ne|n(?:ö|oe)|nope|no)\s*[.!,]*\s*"
    r"(?:(?:danke|dankesch(?:ö|oe)n|vielen\s+dank|nichts|nix|gar\s+nichts|"
    r"eigentlich\s+nichts|lassen\s+sie|ist\s+gut|passt\s+schon|schon\s+gut)\s*[.!,]*\s*)*$",
    re.I,
)

# Absagen/Verschieben eines Bestandstermins: eigenes Anliegen, kein Abbruch.
_BESTAND_RE = re.compile(
    r"\b(?:absagen|abzusagen|stornier\w*|cancel\w*|verschieben|verlegen|"
    r"umbuchen|bestehenden|gebuchten|vereinbarten|alten\s+termin)\b",
    re.I,
)

# Ende-Woerter, die den Zug SCHLIESSEN ("... Danke.", "... Tschuess."): nach
# dem Abbruch dann kein "Sonst noch etwas?" mehr, sondern Abschied.
_ENDE_WORT_RE = re.compile(
    r"\b(?:danke(?:sch(?:ö|oe)n)?|vielen\s+dank|dankesch(?:ö|oe)n|tsch(?:ü|ue)ss?|"
    r"ciao|tschau|auf\s+wiederh(?:ö|oe)ren|wiederh(?:ö|oe)ren|auf\s+wiedersehen|"
    r"sch(?:ö|oe)nen\s+tag|bis\s+dann|bis\s+bald|machs\s+gut|machen\s+sie(?:'s|\s+es)\s+gut)\b",
    re.I,
)

# Der Anrufer will nach einem Abbruch DOCH buchen.
_DOCH_BUCHEN_RE = re.compile(
    r"^\s*(?:(?:ach|hm+|oh|okay|ok|also|ja|nein|warten\s+sie|moment)\s*,?\s*)*doch\b|"
    r"\bdoch\s+(?:einen\s+)?termin\b|\bdoch\s+(?:buchen|eintragen|machen|ausmachen)\b|"
    r"\b(?:tragen|trag)\s+sie\s+(?:es|das|ihn|den\s+termin)\s+(?:doch\s+|bitte\s+)*(?:ein|fest)\b|"
    r"\b(?:m(?:ö|oe)chte|will|h(?:ä|ae)tte)\s+(?:den\s+termin\s+|ihn\s+)?doch\b",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def enabled() -> bool:
    return (os.environ.get("BUCHUNG_ABBRUCH") or "1").strip().lower() not in (
        "0", "false", "no", "off")


def _ist_frage(t: str) -> bool:
    return "?" in t or bool(_FRAGE_RE.search(t))


def _online(t: str) -> bool:
    if not _ONLINE_WORT_RE.search(t):
        return False
    if _ONLINE_GEGEN_RE.search(t):
        return False
    if _ONLINE_SCHON_RE.search(t):
        return True
    return bool(_ONLINE_TUN_RE.search(t)) or len(t.split()) <= 4


def erkannt(text: str, *, auf_bestaetigung: bool = False,
            nebenfrage: bool = False) -> str:
    """Will dieser Satz die laufende BUCHUNG beenden? Liefert die Art oder "".

    ``auf_bestaetigung``: der Satz antwortet auf "Soll ich das so eintragen?"
    bzw. "Was darf ich aendern?" — dann zaehlt auch das hoefliche "Nein,
    danke." und ein kurzes "Doch nicht." als Ablehnung des Termins.

    ``nebenfrage``: der Satz antwortet auf eine Ja/Nein-NEBENFRAGE der Buchung
    (Zahnreinigung mitbuchen? SMS an diese Nummer? privat versichert?). Dort
    heisst "Nein, danke" / "kein Interesse" / "ich ueberlege es mir" NEIN zur
    Nebenfrage — ein Abbruch braucht dann ein klares Ende ("Telefon beenden")
    oder harten Termin-Bezug ("dann doch keinen Termin").
    """
    if not enabled():
        return ""
    t = _s(text)
    if not t:
        return ""

    # Klares Ende zuerst — "Ich moechte das Telefon beenden, Termin nicht
    # buchen." (66913eb8) ist auch dann ein Ende, wenn noch etwas folgt.
    if _BEENDEN_RE.search(t) and not _NICHT_AUFLEGEN_RE.search(t):
        return "beenden"

    if _BESTAND_RE.search(t):
        return ""
    if _ist_frage(t):
        return ""

    if nebenfrage:
        if _TERMIN_BEZUG_RE.search(t):
            if _online(t):
                return "online"
            if _KEIN_TERMIN_RE.search(t) and not _VERFUEGBAR_RE.search(t):
                return "kein_termin"
        return ""

    if _online(t):
        return "online"
    if _SPAETER_RE.search(t):
        return "spaeter"
    if _KEIN_TERMIN_RE.search(t) and not _VERFUEGBAR_RE.search(t):
        return "kein_termin"
    if auf_bestaetigung:
        if _NEIN_DANKE_RE.match(t):
            return "kein_termin"
        if _KURZ_DOCH_NICHT_RE.match(t) and len(t.split()) <= 6:
            return "kein_termin"
    return ""


def ist_ablehnung(text: str) -> bool:
    """Kurze reine Verneinung ("Nein.", "Oh ne.", "Nee, danke.") — als Antwort
    auf "Was darf ich aendern?" die Ablehnung des Termins. NICHT fuer
    Saetze mit Inhalt ("Nein, der Name.")."""
    if not enabled():
        return False
    t = _s(text)
    return bool(t) and bool(_KURZ_NEGATION_RE.match(t))


def ist_ende_wort(text: str) -> bool:
    """Traegt der Satz eine Schlussfloskel (Danke/Tschuess/Wiederhoeren)?
    Dann folgt nach dem Abbruch kein "Sonst noch etwas?", sondern Abschied."""
    return bool(_ENDE_WORT_RE.search(_s(text)))


def doch_buchen(text: str) -> bool:
    """Nach einem Abbruch: will der Anrufer den Termin DOCH?"""
    t = _s(text)
    return bool(t) and bool(_DOCH_BUCHEN_RE.search(t)) and not re.search(
        r"\bdoch\s+(?:lieber\s+)?nicht\b", t, re.I)


_SCHLUSS = {
    "beenden": "Alles klar — dann trage ich nichts ein.",
    "online": "Alles klar — dann bleibt es bei der Online-Buchung, hier trage ich nichts ein.",
    "spaeter": "Alles klar — dann trage ich jetzt nichts ein. Melden Sie sich einfach wieder, wenn es passt.",
    "kein_termin": "Alles klar — dann trage ich nichts ein.",
}


def schlusssatz(art: str) -> str:
    """EIN ehrlicher Satz zum Abbruch — ohne Frage (die haengt der Fluss an)."""
    return _SCHLUSS.get(art) or _SCHLUSS["kein_termin"]
