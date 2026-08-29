"""Biancas Session-Gehirn: mehrturniger Sammler für die Terminbuchung.

Jeder Anrufer-Satz läuft durch ALLE Deuter (Arzt, Grund, Wunschzeit, Name,
Buchstabierung, Telefon, Ja/Nein) — egal, was gerade gefragt war. Wer alles
in einem Satz sagt ("Müller hier, ich brauche nächste Woche vormittags eine
Kontrolle"), überspringt die Fragen. Was fehlt, wird in fester Reihenfolge
nachgefragt: erst "Waren Sie schon bei uns — und bei wem?", dann Grund,
Wunschzeit, Name (buchstabiert), Handynummer (rückbestätigt).

Rein und ohne Netz: die Kartei-Suche und die Slot-Suche stößt flow/hintergrund
an — hier wird nur Zustand gehalten und die nächste Frage bestimmt.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bianca import arzt as arztmod
from bianca import besuchsgrund, buchstaben, telefon
from kern import motive, vornamen
from kern.patients import arzt_sprechname
from kern.slots import parse_slot_wish

TZ = ZoneInfo("Europe/Berlin")

# --- Versichertenstatus (Chef 29.08.2026) ---------------------------------
# "privat" faengt auch Beihilfe (Beamte) und "Privatpatient"; die Kassen-
# Namen zaehlen als GESETZLICH — genau dadurch bleibt ein Kassenwechsel
# ("jetzt TK statt AOK") folgenlos: beides ist und bleibt "gesetzlich".
_VERS_PRIVAT_RE = re.compile(r"\bprivat|beihilfe", re.I)
_VERS_GESETZLICH_RE = re.compile(
    r"\bgesetzlich|kassenpatient(?:in)?|krankenkasse|familienversichert|"
    r"\b(?:aok|tk|techniker|barmer|dak|ikk|bkk|kkh|hkk|sbk|knappschaft|viactiv)\b",
    re.I,
)
# Spontan-Nennung ausserhalb der Frage ("ich bin uebrigens privat versichert").
_VERS_KONTEXT_RE = re.compile(r"versichert|versicherung|kassenpatient|privatpatient", re.I)
# "hat sich geaendert / ich habe gewechselt" auf die Bestands-Rueckfrage.
_VERS_WECHSEL_RE = re.compile(
    r"gewechselt|geändert|geaendert|umgestiegen|andere\s+versicherung|"
    r"nicht\s+mehr\s+(?:privat|gesetzlich)|inzwischen\s+(?:privat|gesetzlich)",
    re.I,
)

# --- Zahnreinigung-Mitbuchung (Chef 30.08.2026) ----------------------------
# Spontaner Wunsch ("machen Sie doch gleich eine Zahnreinigung mit dazu")
# bzw. klare Ablehnung ("ohne Zahnreinigung"). Die nackte Grund-Nennung
# ("Termin zur Zahnreinigung") bleibt Sache des Besuchsgrund-Deuters.
_PZR_DAZU_RE = re.compile(
    r"(?:zahnreinigung|prophylaxe|\bpzr\b)[^.!?]{0,50}\b(?:dazu|mitbuchen|mit\s*buchen|mitmachen|mit\s*machen|mit\s*einplanen|einplanen|auch\s+noch|gleich\s+mit|dran(?:haengen|hängen))"
    r"|(?:dazu|gleich|auch)\s+(?:noch\s+)?(?:eine\s+|die\s+)?(?:professionelle\s+)?(?:zahnreinigung|prophylaxe|pzr)",
    re.I,
)
_PZR_KEINE_RE = re.compile(
    r"(?:keine?|ohne|nicht)\s+(?:noch\s+)?(?:eine\s+|die\s+)?(?:professionelle\s+)?(?:zahnreinigung|prophylaxe|pzr)",
    re.I,
)

_JA_RE = re.compile(
    r"^\s*(ja|jaja|jap|jep|jup|jupp|jopp|jo|joa|jou|jau|yep|yes|jawohl|jawoll|genau|richtig|korrekt|stimmt|passt|klar|gerne|okay|ok|sicher|natürlich|natuerlich)\b",
    re.I,
)
_NEIN_RE = re.compile(r"^\s*(nein|nee|nö|noe|falsch|stimmt nicht|nicht ganz|leider nicht)\b", re.I)
# Kurz-Verneinungen als GANZE Aeusserung: "Noch nicht." auf "Waren Sie schon
# mal bei uns?" ist ein Nein (live 27.08. 14:53: fiel durch, Frage kam doppelt).
_NEIN_KURZ_RE = re.compile(
    r"^\s*(noch\s+nicht|noch\s+nie|bisher\s+nicht|bis\s+jetzt\s+nicht|"
    r"eigentlich\s+nicht|eher\s+nicht|leider\s+nein)\s*[.!…]*\s*$",
    re.I,
)
# Kurz-Zustimmungen als GANZE Aeusserung ("Stark.", "Super!", "Sehr gut") —
# bewusst nur als Voll-Treffer: "Gut, aber ..." ist KEINE glatte Zustimmung.
_JA_KURZ_RE = re.compile(
    r"^\s*(stark|super|perfekt|prima|top|klasse|wunderbar|bestens|schön|schoen|"
    r"sehr\s+gut|gut|in\s+ordnung|einverstanden|von\s+mir\s+aus|meinetwegen|gebongt)\s*[.!…]*\s*$",
    re.I,
)
# Zwischenfrage/Abschweifung des Anrufers ("Was kostet das?", "Wo parke ich?"):
# geht ans LLM und zaehlt NIE als Leerlauf Richtung Eskalation (Chef 27.08.:
# "Abschweifungen muessen erlaubt sein"). Nackte Fragewoerter zaehlen NUR am
# Satzanfang — "B wie Berta" (Buchstabieren) und "wie gesagt" sind KEINE Fragen.
_ZWISCHENFRAGE_START_RE = re.compile(
    r"^\s*(?:(?:und|aber|ach|ja|sag(?:en)?\s+(?:sie\s+)?mal|mal\s+(?:eine|ne)\s+frage|"
    r"eine\s+frage|kurze\s+frage|noch\s+(?:eine|ne)\s+frage)\b[\s,:—-]*)*"
    r"(?:was|wie(?!\s+(?:gesagt|besprochen|immer|vorhin|üblich|ueblich|abgemacht))|"
    r"wann(?!\s+(?:sie|es|ihr|du)\b)|wo|wohin|woher|wer|warum|wieso|weshalb|wozu|"
    r"welche[rsnm]?|wieviel|wie\s+viele?)\b",
    re.I,
)
_ZWISCHENFRAGE_KERN_RE = re.compile(
    r"\?|"
    r"\b(kostet|kosten|preis|preise|gebühr|gebuehr|gibt\s+es|gibts|"
    r"haben\s+sie|habt\s+ihr|kann\s+ich|könnte\s+ich|koennte\s+ich|darf\s+ich|"
    r"muss\s+ich|müsste\s+ich|muesste\s+ich|sollte?\s+ich|wie\s+lange|dauert|"
    r"parken|parkplatz|parkplätze|parkplaetze|barrierefrei|rollstuhl|aufzug|"
    r"versicherung|krankenkasse|privatpatient|selbstzahler|"
    r"betäubung|betaeubung|nüchtern|nuechtern|mitbringen|unterlagen)\b",
    re.I,
)
# "Äh, nein." / "Also ja" / "Hm, nee" — Füllwörter vor dem Ja/Nein abstreifen
# (live 27.08.2026: "Äh, nein" wurde NICHT als Nein erkannt, die Zustands-
# maschine blieb auf der Frage hängen und das LLM übernahm mit Fantasie).
# "hier"/"naja" gehören dazu: "Äh, hier nein" fiel live (27.08. 18:10) durch
# und die Schonmal-Frage kam doppelt.
_ANLAUF_RE = re.compile(
    r"^\s*(?:(?:äh+m*|aeh+m*|hm+|mh+m*|also|na|naja|nun|tja|ach|och|oh|boah|puh|hier|ähm|öhm)\b[\s,.!—-]*)+",
    re.I,
)

_TERMIN_RE = re.compile(
    r"termin|vorbeikommen|ausmachen|vereinbaren|buchen|kontroll|schmerz|zahnweh|"
    r"zahnreinigung|prophylaxe|reinigung|wurzel|implantat|krone|füllung|fuellung|"
    r"abgebrochen|vorsorge|untersuchung",
    re.I,
)
_ABSAGE_RE = re.compile(
    r"absagen|abzusagen|abgesagt|\babsage\b|stornieren|storniert|stornierung|"
    r"abbestellen|\w*cancel\w*|"
    r"nicht\s+(kommen|wahrnehmen|schaffen|einhalten)|"
    # "der Termin (morgen) fällt aus" / "den Termin platzen lassen" — aber
    # NICHT "mir fällt ein Zahn aus" (Subjekt muss der Termin sein).
    r"termin\w*[^.!?]{0,30}?(?:fällt|faellt)\s+(?:leider\s+|doch\s+)?aus\b|"
    r"ausfallen\s+lassen|platzen\s+lassen|"
    # löschen/streichen/aufheben/rückgängig/entfernen sind Allerwelts-Verben:
    # nur MIT Termin-Bezug im selben Satz ("Nummer löschen" ist keine Absage).
    r"termin\w*[^.!?]{0,50}?(?:löschen|loeschen|gelöscht|geloescht|streichen|gestrichen|aufheben|aufzuheben|rückgängig|rueckgaengig|entfernen|rausnehmen|raus\s+nehmen)|"
    r"(?:löschen|loeschen|streichen|aufheben|rückgängig|rueckgaengig|entfernen)[^.!?]{0,50}?termin\w*|"
    # Trennbares Verb: "ich sage den Termin ab" / "sag ihn bitte ab" — aber
    # NICHT "können Sie mir sagen, ab wann ..." (Auskunftsfrage).
    r"\bsag\w*\s+(?:ich\s+|wir\s+|sie\s+)?(?:den\s+|meinen\s+|diesen\s+|ihn\s+|sie\s+|bitte\s+|doch\s+|wieder\s+|einfach\s+|lieber\s+|gerne\s+|gleich\s+|sofort\s+)*(?:termin\s+)?(?:doch\s+|wieder\s+|bitte\s+|einfach\s+|lieber\s+|gerne\s+|gleich\s+|sofort\s+)*ab\b(?!\s*(?:wann|wie|welch))",
    re.I,
)
_VERSCHIEBEN_RE = re.compile(
    r"verschieben|verschoben|umbuchen|umzubuchen|verlegen|umlegen|vorverlegen|"
    r"nach\s+hinten\s+schieben|anderen\s+tag\s+.{0,16}(statt|als)\b",
    re.I,
)
# Woerter, die im "ich habe ... Termin"-Fenster einen WUNSCH verraten
# (dann ist es eine Neubuchung, keine Bestands-Auskunft).
_KEIN_WUNSCH_TOKEN = (
    r"(?!(?:gern\w*|zeit|urlaub|frei|brauch\w*|bräucht\w*|braucht\w*|"
    r"möcht\w*|moecht\w*|hätt\w*|haett\w*|will|wollte|dringend|"
    r"\w*schmerz\w*|\w*weh)\b)"
)
_AUSKUNFT_RE = re.compile(
    r"wann\s+(ist|war|wäre|waere|hab(e)?\s+ich)\b.{0,30}termin|"
    r"hab(e)?\s+ich\s+(überhaupt\s+|ueberhaupt\s+)?(noch\s+)?(irgend)?einen\s+termin|"
    r"welche[nr]?\s+termin(e)?\s+(hab|steht|stehen)|"
    r"termin\s+(nochmal|noch\s+mal|nochmals)\s*(sagen|nennen|durchgeben)?|"
    r"wann\s+(muss|soll|darf)\s+ich\s+(kommen|da\s+sein|vorbeikommen)|"
    r"wann\s+bin\s+ich\s+(dran|eingetragen)|"
    # "... einen Termin, aber ich weiss nicht mehr(, wann)" — Bestandstermin,
    # Zeitpunkt vergessen (Live-Protokoll 29.08.2026, 09:34).
    r"termin\b[^.!?]{0,60}?\b(?:weiß|weiss|wusste|wüsste|wuesste)\s+(?:\w+\s+){0,2}?nicht|"
    r"\b(?:weiß|weiss|wusste|wüsste|wuesste)\s+(?:\w+\s+){0,2}?nicht\b[^.!?]{0,50}?\btermin|"
    # Feststellung "ich habe <Zeitangabe> ... einen Termin" (ohne Wunsch-Wort
    # wie brauche/hätte/Zeit): der Termin EXISTIERT — Auskunft, nie Neubuchung.
    rf"ich\s+hab(?:e|')?\s+(?:{_KEIN_WUNSCH_TOKEN}[\wäöüß,]+\s+){{0,5}}?"
    rf"(?:am\s+[\wäöüß]+|(?:n[äa]chste|diese|kommende)[nrs]?\s+woche|morgen|übermorgen|uebermorgen|heute|"
    rf"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b"
    rf"\s*(?:{_KEIN_WUNSCH_TOKEN}[\wäöüß,]+\s+){{0,5}}?termin\b",
    re.I,
)
_SCHONMAL_JA_RE = re.compile(
    r"(war|bin|waren)\s+(schon|bereits|öfter|oefter|mal|einmal|früher|frueher)[^.]{0,40}(bei\s+(ihnen|euch)|da|dort|in\s+der\s+praxis)|"
    r"bin\s+(schon\s+)?patient|bin\s+bei\s+ihnen\s+in\s+behandlung",
    re.I,
)
# "bin neu" braucht die Wortgrenze und darf Fuellwoerter tragen: ohne \b traf
# der Ausdruck auch "bin NEUmann" (echter Nachname!), und "bin GANZ neu bei
# euch" fiel durch (live 27.08.2026: "Ich bin neu bei Ihnen" -> "Danke, Neu
# Ihnen").
_SCHONMAL_NEIN_RE = re.compile(
    r"noch\s+nie|zum\s+ersten\s+mal|das\s+erste\s+mal|"
    r"bin\s+(?:ganz\s+|völlig\s+|voellig\s+|hier\s+|noch\s+)*neu\b|"
    r"noch\s+kein\s+patient|noch\s+nicht\s+bei\s+(ihnen|euch)",
    re.I,
)
_ARZT_KONTEXT_RE = re.compile(r"arzt|ärztin|aerztin|behandler|doktor|dr\.|bei\s+wem|zu\s+wem", re.I)
_FUER_WEN_RE = re.compile(
    r"für\s+mein(?:e|en)?\s+(tochter|sohn|mann|frau|mutter|vater|kind|oma|opa)", re.I
)
_NAME_LEADIN_RE = re.compile(
    # Nach dem Leadin folgt bei einem NAMEN nie eine Präposition — "ich bin
    # bei Ihnen in Behandlung" erntete live (29.08.2026) "Bei Behandlung".
    r"(?:mein\s+name\s+ist|ich\s+heiße|ich\s+heisse|hier\s+(?:ist|spricht)|ich\s+bin)\s+"
    r"(?!(?:bei|in|im|an|am|auf|aus|mit|seit|unter|vor|zu|zum|zur|nach|ohne|"
    r"gegen|für|fuer|über|ueber|durch|um)\b)"
    r"([A-Za-zÄÖÜäöüß' -]{2,60})",
    re.I,
)
_NAME_STOP = {
    "und", "der", "die", "das", "ein", "eine", "herr", "frau", "doktor", "dr",
    "mein", "name", "ist", "hier", "spricht", "ich", "bin", "heiße", "heisse",
    "guten", "tag", "morgen", "hallo", "von", "aus", "am", "apparat",
    # "Auch Paul" (Antwort auf die Vornamens-Frage) darf keinen Vornamen
    # "Auch" erzeugen (live 27.08.2026) — dito weitere Füllwörter.
    "auch", "ebenfalls", "genau", "also", "wieder", "nochmal", "eben",
    "ähm", "äh", "aeh", "aehm", "halt", "wie", "gesagt",
    # Korrektur-Einstiege sind NIE Namen: "Nee, der Vorname ist Paul" wurde
    # live (27.08.2026) als "Nee Paul" geerntet.
    "nee", "nein", "nö", "noe", "ne", "doch", "falsch", "moment", "sekunde",
    "vorname", "nachname", "familienname", "lautet",
}
# Gängige Vornamen (nur zur Zuordnung "ein einzelnes Wort = eher Vorname?").
# Live 27.08.2026: die Antwort "Paul?" auf die Namensfrage wurde als NACHNAME
# geführt und der Anrufer als "Herr Paul" angesprochen.
_VORNAMEN = {
    "alexander", "andreas", "anna", "anne", "anja", "antje", "barbara", "bernd",
    "birgit", "brigitte", "carsten", "christian", "christina", "christine",
    "claudia", "daniel", "daniela", "david", "dennis", "dieter", "dirk",
    "dominik", "doris", "elena", "elias", "elke", "emil", "emma", "erik",
    "eva", "felix", "finn", "florian", "frank", "franz", "frieda", "gabriele",
    "georg", "gerhard", "gisela", "hanna", "hannah", "hans", "heike", "heinz",
    "helga", "henry", "holger", "ingrid", "jan", "jana", "jens", "joachim",
    "johann", "johanna", "johannes", "jonas", "julia", "julian", "jürgen",
    "juergen", "kai", "karin", "karl", "katharina", "kathrin", "katja",
    "kerstin", "kevin", "klaus", "kurt", "lara", "laura", "lea", "lena",
    "leon", "leonie", "lisa", "luca", "luis", "luise", "lukas", "manfred",
    "manuela", "marc", "marcel", "marco", "maria", "marie", "mario", "marion",
    "markus", "martin", "martina", "mathias", "matthias", "max", "maximilian",
    "melanie", "mia", "michael", "michaela", "mila", "monika", "moritz",
    "nadine", "nicole", "niklas", "nina", "noah", "nora", "olaf", "oliver",
    "otto", "patrick", "paul", "paula", "peter", "petra", "philipp", "ralf",
    "regina", "renate", "richard", "robert", "rolf", "rudolf", "sabine",
    "sandra", "sara", "sarah", "sebastian", "silke", "simon", "simone",
    "sofia", "sophie", "stefan", "stefanie", "steffen", "susanne", "sven",
    "tanja", "theo", "thomas", "thorsten", "tim", "tobias", "tom", "torsten",
    "ulrich", "ulrike", "ursula", "uwe", "vanessa", "verena", "walter",
    "werner", "wolfgang", "yvonne",
}
# Explizite Zuweisungen schlagen alles: "der Vorname ist Paul", "Panzer ist
# der Nachname". Erfasst wird genau EIN Wort — sonst frisst der Ausdruck
# "Paul und der Nachname ist Panzer" komplett (live 27.08.2026: "Nee Paul").
_TEIL_VOR_RE = re.compile(
    r"(?:der\s+|mein\s+)?vorname\s+(?:ist|lautet|wäre|waere)\s+([A-Za-zÄÖÜäöüß'-]{2,})", re.I)
_TEIL_NACH_RE = re.compile(
    r"(?:der\s+|mein\s+)?(?:nachname|familienname|zuname)\s+(?:ist|lautet|wäre|waere)\s+([A-Za-zÄÖÜäöüß'-]{2,})", re.I)
_TEIL_VOR_UMGEKEHRT_RE = re.compile(
    r"([A-Za-zÄÖÜäöüß'-]{2,})\s+(?:ist|wäre|waere)\s+(?:der\s+|mein\s+)?vorname", re.I)
_TEIL_NACH_UMGEKEHRT_RE = re.compile(
    r"([A-Za-zÄÖÜäöüß'-]{2,})\s+(?:ist|wäre|waere)\s+(?:der\s+|mein\s+)?(?:nachname|familienname|zuname)", re.I)
# Korrekturen ÜBERSCHREIBEN sofort (Chef 27.08.2026: "das war falsch, ich
# heiße Meier nicht Müller" -> Gedächtnis augenblicklich aktualisieren,
# NIE noch einmal fragen). Neu = das Bejahte, Alt = das Verneinte.
_NAME_FALSCH_RE = re.compile(
    r"(?:heiße|heisse|heißen|heissen|schreibt\s+sich|name\s+ist|richtig\s+ist|richtig\s+wäre|richtig\s+waere)\s+"
    r"([A-Za-zÄÖÜäöüß'-]{2,})\s*[,.]?\s*(?:und\s+)?nicht\s+([A-Za-zÄÖÜäöüß'-]{2,})", re.I)
_NAME_SONDERN_RE = re.compile(
    r"nicht\s+([A-Za-zÄÖÜäöüß'-]{2,})\s*[,.]?\s*sondern\s+([A-Za-zÄÖÜäöüß'-]{2,})", re.I)
_KORREKTUR_KONTEXT_RE = re.compile(
    r"falsch|vertan|verhört|verhoert|versprochen|verwechselt|korrigier|irrtum|stimmt\s+nicht|meinte", re.I)
_TEL_FALSCH_RE = re.compile(
    r"(?:nummer|handy|telefon)[^.!?]{0,40}(?:falsch|stimmt\s+nicht|nicht\s+richtig|verkehrt)|"
    r"falsche\s+(?:nummer|handynummer|telefonnummer)", re.I)
# Neupatient-/Schonmal-Floskeln und ZUSTAENDE sind KEINE Namen: "Ich bin neu
# bei Ihnen" wurde live als Name geerntet ("Danke, Neu Ihnen" — 27.08.2026),
# "ich bin ganz aufgeregt" als "Ganz Aufgeregt" (Talk-Probe 27.08.2026). Der
# ganze Floskel-Teilsatz fliegt VOR der Namens-Ernte raus; ein echter Name im
# selben Satz ("..., mein Name ist Paul Neumann") bleibt erhalten, ebenso
# "Ich bin Paul Neumann" und der Nachname "Neu" (Wortgrenze nach "neu").
# Zustandswoerter, die auch Nachnamen sein koennen (Sauer, Krank, Froh),
# stehen BEWUSST nicht in der Liste.
_KEIN_NAME_RE = re.compile(
    r"(?:ich\s+|wir\s+)?(?:bin|war(?:en)?)\s+"
    r"(?:auch\s+|übrigens\s+|uebrigens\s+|leider\s+|ja\s+|gerade\s+|heute\s+)*"
    r"(?:ganz\s+|völlig\s+|voellig\s+|hier\s+|noch\s+|sehr\s+|so\s+|total\s+|"
    r"richtig\s+|echt\s+|etwas\s+|schon\s+|wirklich\s+|erst\s+|frisch\s+|"
    r"kürzlich\s+|kuerzlich\s+|neulich\s+|lange\s+|länger\s+|laenger\s+|"
    r"seit\s+\S+\s+)*"
    r"(?:neu\b|noch\s+nie\b|zum\s+ersten\s+mal\b|das\s+erste\s+mal\b|"
    r"hergezogen|umgezogen|zugezogen|hierhergezogen|"
    r"patient(?:in)?\b|kunde\b|kundin\b|stammpatient(?:in)?\b|"
    r"aufgeregt|nervös|nervoes|gespannt|begeistert|erleichtert|verzweifelt|"
    r"durcheinander|erkältet|erkaeltet|müde|muede|erschöpft|erschoepft|"
    r"gestresst|genervt|verwirrt|unterwegs|beschäftigt|beschaeftigt|"
    r"spät\b|spaet\b|zufrieden|unzufrieden|glücklich|gluecklich|traurig|"
    r"wütend|wuetend|verheiratet|geschieden|schwanger|aufgeschmissen)[^,.!?]*",
    re.I,
)
_AKTE_NUMMER_RE = re.compile(
    r"(nummer|handy|telefon)[^.]{0,50}(akte|hinterlegt|haben\s+sie\s+(ja|doch|schon|bereits))|"
    r"steht\s+(ja\s+|doch\s+)?in\s+der\s+akte|"
    r"(gleiche|selbe|alte)\s+nummer|nummer\s+wie\s+immer",
    re.I,
)
# Akten-Nummer-Konflikt (Chef 29.08.2026): "alte Nummer loeschen und neue
# eintragen" vs. "Bestaetigungs-SMS an die alte Nummer schicken". NEU wird
# ZUERST geprueft — "die alte ist falsch"/"loeschen Sie die alte" traegt
# beide Marker und meint die neue Nummer.
_ALT_NEU_RE = re.compile(
    r"l(ö|oe)sch|ersetz|(ü|ue)berschreib|aktualisier|tausch|"
    r"neue\s+(nummer|eintragen|nehmen|rein)|die\s+neue|"
    r"falsch|stimmt\s+nicht\s+mehr|gilt\s+nicht\s+mehr|nicht\s+mehr\s+aktuell|veraltet",
    re.I,
)
_ALT_AKTE_RE = re.compile(
    r"behalt|bleib|an\s+die\s+alte|alte\s+nummer\s+(schicken|senden|nutzen|nehmen)|"
    r"dahin|dorthin|so\s+lassen|drin\s+lassen|stimmt\s+noch|beide\s+(stimmen|richtig)",
    re.I,
)

# Frei Gesprochenes -> Besuchsgrund aus der Behandler-Liste: bianca/besuchsgrund.py
# (Konzept-Erkennung + Motiv-Suche mit "klein"-Präferenz, Chef 27.08.2026).

FELDER_START = {
    "modus": "",
    "phase": "",
    "frage": "",
    "warSchonMal": None,
    "arzt": None,
    "grund": "",
    "motivId": "",
    "motivName": "",
    "wunsch": None,
    "wunschText": "",
    "vorname": "",
    "nachname": "",
    "buchstabiert": False,
    "grundWortlaut": "",
    "telefon": "",
    "telefonOffen": "",
    "telefonTeil": "",
    "telefonOk": False,
    "telefonAkte": False,
    "patientId": "",
    "bekannt": False,
    "aktePhone": "",
    "telefonAlt": "",
    "gesucht": "",
    "fuerWen": "",
    "slotIso": "",
    # Geschlecht fuer die Anrede (Chef 29.08.2026): aus der Kartei ("akte")
    # oder vom Vornamen-Waechter geschaetzt ("rate"); unklare Vornamen =>
    # Default weiblich + Praxis-Notiz "bitte Geschlecht aktualisieren".
    "geschlecht": "",
    "geschlechtQuelle": "",
    "geschlechtVon": "",
    "geschlechtUnklar": False,
    # Versichertenstatus (Chef 29.08.2026): "privat" | "gesetzlich".
    # Neupatienten werden gefragt; Bestandspatienten nur, wenn der letzte
    # Besuch >6 Monate her ist — und NUR der Wechsel privat<->gesetzlich
    # zaehlt (Kassenwechsel AOK->TK ist egal).
    "versicherung": "",
    "versicherungOk": False,
    "versicherungAkte": "",
    "versicherungWechsel": False,
    "versicherungNotiz": False,
    "letzterBesuch": "",
    # Rueckblick auf den letzten Besuch (Chef 30.08.2026): Grund des letzten
    # Termins aus der Historie; "rueckblick" haelt den Gespraechs-Zustand
    # ("" = noch nicht angesprochen, "gefragt" = Verlaufs-Frage offen,
    # "fertig" = abgehakt/uebersprungen). "pzr" traegt die Mitbuch-Frage
    # zur Zahnreinigung ("" | "gefragt" | "ja" | "nein").
    "letzterGrund": "",
    "rueckblick": "",
    "pzr": "",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def sammler(sit: dict) -> dict:
    s = sit.setdefault("sammler", {})
    for k, v in FELDER_START.items():
        s.setdefault(k, v)
    return s


def _ohne_anlauf(text: str) -> str:
    return _ANLAUF_RE.sub("", _s(text))


def ist_ja(text: str) -> bool:
    k = _ohne_anlauf(text)
    return bool(_JA_RE.search(k) or _JA_KURZ_RE.match(k))


def ist_nein(text: str) -> bool:
    k = _ohne_anlauf(text)
    if _NEIN_RE.search(k) or _NEIN_KURZ_RE.match(k):
        return True
    # Kurze Äußerung mit klarem Nein-Wort irgendwo ("glaube nein", "hier nein"):
    # bei <= 3 Wörtern gibt es keinen Kontext, der das Nein umdrehen könnte.
    toks = re.sub(r"[.,!?…]+", " ", k.lower()).split()
    return len(toks) <= 3 and any(t in {"nein", "nee", "nö", "noe"} for t in toks)


def ist_zwischenfrage(text: str) -> bool:
    """Stellt der Anrufer selbst eine Frage / schweift er ab?"""
    k = _ohne_anlauf(text)
    return bool(_ZWISCHENFRAGE_KERN_RE.search(k) or _ZWISCHENFRAGE_START_RE.match(k))


def _relatives_datum(t: str) -> str:
    heute = datetime.now(TZ).date()
    if re.search(r"\bübermorgen|uebermorgen\b", t):
        return (heute + timedelta(days=2)).isoformat()
    if re.search(r"\bmorgen\b", t):
        return (heute + timedelta(days=1)).isoformat()
    if re.search(r"\bheute\b", t):
        return heute.isoformat()
    return ""


# "Das ist mir egal" auf die Zeitfrage IST eine Antwort (keine Präferenz —
# die nächsten freien Termine zählen). Live 29.08.2026: ohne diese Erkennung
# ging der Satz ans LLM, das eine Kalender-Störung erfand und die Frage
# wiederholte; erst die Eskalation beim zweiten "egal" löste korrekt auf.
_WUNSCH_EGAL_RE = re.compile(
    r"\begal\b|\bganz\s+gleich\b|\bgleichg(?:ü|ue)ltig\b|"
    r"\b(?:ist|is|wär\w*|waer\w*)\s+mir\s+(?:gleich|wurst|wurscht|latte)\b|"
    r"\bwann\s+(?:auch\s+)?immer\b|\bspielt\s+keine\s+rolle\b|"
    r"\bkeine\s+pr(?:ä|ae)ferenz\b|\bhauptsache\b|"
    r"\bwie\s+(?:sie|es)\s+(?:wollen|meinen|passt)\b|\bwei(?:ß|ss)\s+(?:ich\s+)?nicht\b",
    re.I,
)


def _wunsch_deuten(text: str) -> dict | None:
    """parse_slot_wish plus relative Tage — None, wenn der Satz nichts Zeitliches hat."""
    wish = parse_slot_wish(text) or {}
    rel = _relatives_datum(f" {_s(text).lower()} ")
    if rel and not wish.get("date"):
        wish["date"] = rel
    gehaltvoll = any([
        wish.get("date"), wish.get("weekday") is not None, wish.get("hour") is not None,
        wish.get("hourMin") is not None, wish.get("minDaysAhead"),
    ])
    return wish if gehaltvoll else None


def _wunsch_mischen(alt: dict | None, neu: dict) -> dict:
    """Mehrturnig: 'nächste Woche' + später 'vormittags' ergibt EINEN Wunsch."""
    out = dict(alt or {})
    for k, v in neu.items():
        if v not in (None, 0, ""):
            out[k] = v
    for k in ("weekday", "hourMin", "hourMax", "hour", "minDaysAhead", "date"):
        out.setdefault(k, None if k not in ("minDaysAhead",) else 0)
    return out


def _grund_deuten(tenant: dict, text: str, katalog: list[dict] | None = None) -> tuple[str, dict | None]:
    return besuchsgrund.deute(tenant, text, katalog=katalog)


def _name_tokens(text: str) -> list[str]:
    raw = re.sub(r"[^\wäöüßÄÖÜ' -]+", " ", _s(text))
    return [t for t in raw.split() if t.lower() not in _NAME_STOP and len(t) >= 2 and not t.isdigit()]


_NACHSPRECH_STOP = _NAME_STOP | {
    "mal", "kurz", "warte", "warten", "augenblick", "bitte", "langsam",
    "buchstabieren", "gerne", "okay", "gleich", "sofort", "was", "wieso",
}


def _nachgesprochen(text: str) -> str:
    """Auf die Buchstabier-Frage den Namen NOCHMAL gesprochen statt buchstabiert.

    STT zerlegt lange Namen gern in Silbenblöcke ("MATTA VATTA" statt
    Mattavatta, live 27.08.2026). Ein bis zwei reine Wort-Tokens ohne
    Füllwörter werden als Nachname übernommen — alles andere bleibt beim
    LLM bzw. der Eskalation.
    """
    if ist_ja(text) or ist_nein(text) or ist_zwischenfrage(text):
        return ""
    raw = re.sub(r"[^\wäöüßÄÖÜ-]+", " ", _s(text))
    toks = [t for t in raw.split() if t]
    if not 1 <= len(toks) <= 2:
        return ""
    if any(t.lower() in _NACHSPRECH_STOP or t.isdigit() or len(t) < (3 if len(toks) == 2 else 4) for t in toks):
        return ""
    zusammen = "".join(toks)
    if not zusammen.isalpha() or not 4 <= len(zusammen) <= 20:
        return ""
    return zusammen.capitalize()


def _kartei_zuruecksetzen(s: dict) -> None:
    """Nach einer Namens-Korrektur ist der Kartei-Treffer hinfällig —
    die Hintergrund-Suche läuft mit dem richtigen Namen neu an."""
    s["patientId"] = ""
    s["bekannt"] = False
    s["aktePhone"] = ""
    s["telefonAlt"] = ""
    s["gesucht"] = ""
    # Kartei-Wissen faellt mit: Versichertenstatus, letzter Besuch und ein
    # aus der Akte uebernommenes Geschlecht gehoeren zum ALTEN Treffer.
    # (rueckblick/pzr bleiben bewusst stehen: EINE Plauderei pro Anruf.)
    s["versicherungAkte"] = ""
    s["letzterBesuch"] = ""
    s["letzterGrund"] = ""
    if s.get("geschlechtQuelle") == "akte":
        s["geschlecht"] = ""
        s["geschlechtQuelle"] = ""
        s["geschlechtVon"] = ""
        s["geschlechtUnklar"] = False


def _name_korrektur(s: dict, text: str) -> bool:
    """"Ich heiße Meier, nicht Müller" / "nicht Müller, sondern Meier":
    sofort übernehmen — auch wenn der Name längst gespeichert ist."""
    neu_wert, alt_wert = "", ""
    m = _NAME_FALSCH_RE.search(text)
    if m:
        neu_wert, alt_wert = m.group(1), m.group(2)
    else:
        m = _NAME_SONDERN_RE.search(text)
        if m:
            alt_wert, neu_wert = m.group(1), m.group(2)
            # "nicht Patrikis, sondern Petsas" meint den ARZT: nur als
            # Patientenname werten, wenn das Verneinte wirklich einer der
            # gespeicherten Namensteile ist oder es klar um den Namen geht.
            if _ARZT_KONTEXT_RE.search(text):
                gespeichert = {s["vorname"].lower(), s["nachname"].lower()} - {""}
                if alt_wert.lower() not in gespeichert:
                    return False
    if not m or not neu_wert:
        # "Das war falsch — ich heiße Paul Meier": Korrektur-Kontext plus
        # normale Namensnennung überschreibt ebenfalls.
        if _KORREKTUR_KONTEXT_RE.search(text):
            lead = _NAME_LEADIN_RE.search(text)
            toks = _name_tokens(lead.group(1)) if lead else []
            if toks:
                if len(toks) >= 2:
                    s["vorname"] = toks[0].capitalize()
                    alt_nach = s["nachname"]
                    s["nachname"] = toks[-1].capitalize()
                else:
                    alt_nach = s["nachname"]
                    s["nachname"] = toks[0].capitalize()
                if s["nachname"] != alt_nach:
                    s["buchstabiert"] = False
                    _kartei_zuruecksetzen(s)
                return True
        return False
    if neu_wert.lower() in _NAME_STOP or alt_wert.lower() in _NAME_STOP:
        return False
    neu_name = neu_wert.capitalize()
    alt = alt_wert.lower()
    if alt == s["vorname"].lower() and s["vorname"]:
        s["vorname"] = neu_name
        if s["patientId"] or s["bekannt"]:
            _kartei_zuruecksetzen(s)
        return True
    # Standard: der Nachname wird korrigiert (auch wenn "alt" nur ähnlich
    # klingt wie das Gespeicherte — STT hatte ja gerade falsch gehört).
    if s["nachname"] and neu_name != s["nachname"]:
        s["buchstabiert"] = False
        _kartei_zuruecksetzen(s)
    s["nachname"] = neu_name
    return True


def _name_aufnehmen(s: dict, text: str, *, erzwungen: bool) -> bool:
    """Vor-/Nachname aus dem Satz ziehen. erzwungen=True: die Frage war der Name."""
    text = _s(_KEIN_NAME_RE.sub(" ", text))
    if not text:
        return False

    # Explizite Zuweisung gewinnt IMMER und darf Falsches überschreiben:
    # "Nee, der Vorname ist Paul und der Nachname ist Panzer" (live 27.08.2026
    # als "Nee Paul" verbucht). Ein neuer Nachname macht die alte
    # Buchstabierung ungültig.
    getroffen = False
    mv = _TEIL_VOR_RE.search(text) or _TEIL_VOR_UMGEKEHRT_RE.search(text)
    if mv and mv.group(1).lower() not in _NAME_STOP:
        s["vorname"] = mv.group(1).capitalize()
        getroffen = True
    mn = _TEIL_NACH_RE.search(text) or _TEIL_NACH_UMGEKEHRT_RE.search(text)
    if mn and mn.group(1).lower() not in _NAME_STOP:
        neu_nach = mn.group(1).capitalize()
        if s["nachname"] and neu_nach != s["nachname"]:
            s["buchstabiert"] = False
            _kartei_zuruecksetzen(s)
        elif neu_nach != s["nachname"]:
            s["buchstabiert"] = False
        s["nachname"] = neu_nach
        getroffen = True
    if getroffen:
        return True

    m = _NAME_LEADIN_RE.search(text)
    kandidat = m.group(1) if m else (text if erzwungen else "")
    toks = _name_tokens(kandidat)
    if not toks:
        return False
    if m is None and erzwungen and len(toks) > 3:
        # Ganze-Satz-Rueckfall NUR fuer namensartige Antworten: Wer auf die
        # Namensfrage eine Geschichte erzaehlt ("Ach, wissen Sie — meine
        # Tochter heiratet naemlich!"), nennt keinen Namen — das gehoert der
        # Talk-Schicht, nicht der Kartei (Talk-Probe 27.08.2026).
        return False
    if s["frage"] == "vorname" and erzwungen:
        s["vorname"] = toks[0].capitalize()
        return True
    if s["frage"] == "nachname" and erzwungen:
        s["nachname"] = toks[-1].capitalize()
        s["buchstabiert"] = False
        return True
    if len(toks) >= 2:
        s["vorname"] = toks[0].capitalize()
        s["nachname"] = toks[-1].capitalize()
        return True
    if erzwungen:
        # Nur EIN Wort auf die Namensfrage: gängige Vornamen (Paul, Anna …)
        # sind der VORNAME — alles andere führen wir als Nachnamen. Live
        # 27.08.2026 wurde "Paul?" als Nachname geführt ("Herr Paul").
        if toks[0].lower() in _VORNAMEN and not s["vorname"]:
            s["vorname"] = toks[0].capitalize()
        else:
            s["nachname"] = toks[0].capitalize()
        return True
    return False


def einsammeln(sit: dict, text: str) -> set[str]:
    """Alle Deuter über den Satz laufen lassen; liefert die neu gefüllten Felder."""
    s = sammler(sit)
    t = _s(text)
    tl = f" {t.lower()} "
    neu: set[str] = set()
    if not t:
        return neu

    # Anliegen-Modus: absagen/verschieben/auskunft VOR der Buchungs-Erkennung
    # prüfen — "Ich möchte meinen Termin absagen" enthält auch "Termin".
    # Läuft schon ein Angebot im Buchungsfluss, bezieht sich "absagen"/
    # "verschieben" auf das Angebot, nicht auf einen Bestandstermin.
    im_angebot = s["modus"] == "buchen" and s["phase"] in {"angebot", "bestaetigen"}
    if not im_angebot:
        # phase "fertig" = das vorige Anliegen ist abgeschlossen (Storno
        # erledigt ODER ehrlich nicht gefunden). Ein WIEDERHOLTER Wunsch im
        # selben Modus muss dann neu bewaffnen — live 29.08. 08:47 klebte
        # modus auf "absagen" und "Ich möchte meinen Termin absagen." fiel
        # wortlos ans LLM ("Welchen Termin soll ich absagen?").
        if _VERSCHIEBEN_RE.search(t):
            if s["modus"] != "verschieben" or s["phase"] == "fertig":
                s["modus"] = "verschieben"
                s["phase"] = ""
                s["frage"] = ""
                neu.add("modus")
        elif _ABSAGE_RE.search(t):
            if s["modus"] != "absagen" or s["phase"] == "fertig":
                s["modus"] = "absagen"
                s["phase"] = ""
                s["frage"] = ""
                neu.add("modus")
        elif _AUSKUNFT_RE.search(t):
            if (s["modus"] in {"", "buchen"} and s["phase"] in {"", "gebucht", "fertig"}) or (
                s["modus"] in {"absagen", "verschieben"} and s["phase"] == "fertig"
            ):
                s["modus"] = "auskunft"
                s["phase"] = ""
                s["frage"] = ""
                neu.add("modus")
        elif _TERMIN_RE.search(t):
            # Neu buchen: aus dem Leeren — oder nach abgeschlossener
            # Verwaltung ("fertig": Storno erledigt, Auskunft gegeben).
            if s["modus"] == "" or (s["modus"] != "buchen" and s["phase"] == "fertig"):
                s["modus"] = "buchen"
                s["phase"] = ""
                s["frage"] = ""
                neu.add("modus")

    # Schon mal da gewesen?
    if _SCHONMAL_NEIN_RE.search(t):
        if s["warSchonMal"] is not False:
            s["warSchonMal"] = False
            neu.add("warSchonMal")
    elif _SCHONMAL_JA_RE.search(t):
        if s["warSchonMal"] is not True:
            s["warSchonMal"] = True
            neu.add("warSchonMal")
    elif s["frage"] == "schonmal":
        if ist_ja(t):
            s["warSchonMal"] = True
            neu.add("warSchonMal")
        elif ist_nein(t):
            s["warSchonMal"] = False
            neu.add("warSchonMal")

    # Behandler: ein Name zählt immer; "egal"/"weiß nicht" nur im Arzt-Kontext.
    tenant = sit.get("tenant") or {}
    gedeutet = arztmod.deute(t, tenant)
    if gedeutet:
        im_kontext = s["frage"] == "arzt" or _ARZT_KONTEXT_RE.search(t)
        if gedeutet["typ"] == "genannt":
            s["arzt"] = gedeutet
            s["warSchonMal"] = True if s["warSchonMal"] is None and _SCHONMAL_JA_RE.search(t) else s["warSchonMal"]
            neu.add("arzt")
        elif im_kontext and not (s["arzt"] or {}).get("calendarId"):
            s["arzt"] = gedeutet
            neu.add("arzt")

    # Für wen ist der Termin?
    fm = _FUER_WEN_RE.search(t)
    if fm and not s["fuerWen"]:
        s["fuerWen"] = fm.group(1).lower()
        neu.add("fuerWen")

    # Besuchsgrund: auf die Besuchsgrund-Liste des Behandlers mappen; der
    # WORTLAUT des Patienten bleibt für die Terminnotiz erhalten (Chef 27.08.).
    # Gemappt wird gegen den FRISCH geholten Katalog der Sitzung (Chef
    # 30.08.2026: Mapping in jedem Anruf neu); die endgueltige, behandler-
    # spezifische Aufloesung macht flow._ctx_bauen vor Suche und Buchung.
    if not s["grund"]:
        kern_name, vm = _grund_deuten(tenant, t, katalog=motive.katalog(sit))
        if kern_name:
            s["grund"] = kern_name
            s["grundWortlaut"] = t if len(t) <= 120 else t[:117] + "…"
            if vm:
                s["motivId"] = _s(vm.get("id"))
                s["motivName"] = _s(vm.get("name"))
            neu.add("grund")
        elif s["frage"] == "grund" and len(t) >= 3 and not ist_ja(t) and not ist_nein(t):
            # Frei formulierter Grund ("Holzbein absägen"): Wortlaut behalten,
            # gebucht wird der Zweifelsfall-Grund (Kontrolle/Besprechung).
            s["grund"] = t if len(t) <= 90 else t[:87] + "…"
            s["grundWortlaut"] = s["grund"]
            vm = besuchsgrund.fallback_motiv(tenant, katalog=motive.katalog(sit))
            if vm:
                s["motivId"] = _s(vm.get("id"))
                s["motivName"] = _s(vm.get("name"))
            neu.add("grund")

    # Wunschzeit (mehrturnig gemischt)
    wish = _wunsch_deuten(t)
    if wish:
        s["wunsch"] = _wunsch_mischen(s["wunsch"], wish)
        s["wunschText"] = _s(f"{s['wunschText']} {t}") if s["wunschText"] else t
        neu.add("wunsch")
    elif (s["frage"] == "wunsch" and s["wunsch"] is None
          and _WUNSCH_EGAL_RE.search(_ohne_anlauf(t))
          and not _ARZT_KONTEXT_RE.search(t)):
        # "Egal" auf die Zeitfrage: keine Präferenz — nächste freie Termine.
        s["wunsch"] = {}
        s["wunschText"] = t
        neu.add("wunsch")

    # Buchstabierung schlägt den frei gehörten Nachnamen — auch wenn sie ihm
    # WIDERSPRICHT: wer buchstabiert, korrigiert gerade (live 27.08.2026:
    # "MATTA VATTA" gegen gespeichertes "Pidoq" — Bianca beharrte auf Pidoq).
    if _name_korrektur(s, t):
        neu.add("name")
    buch = buchstaben.deute(t)
    if "name" in neu:
        pass  # Korrektur hat Vorrang — nichts erneut ernten.
    elif buch and (s["frage"] in {"buchstabieren", "name", "nachname"} or not s["nachname"]):
        s["nachname"] = buch["name"]
        s["buchstabiert"] = True
        s["bekannt"] = False if s["frage"] == "buchstabieren" and not s["patientId"] else s["bekannt"]
        neu.add("nachname")
        # Im selben Satz kann der Vorname stecken: "… P-A-N-Z-E-R. Der
        # Vorname ist Paul" — nicht verschlucken (live 27.08.2026).
        mv = _TEIL_VOR_RE.search(t) or _TEIL_VOR_UMGEKEHRT_RE.search(t)
        if mv and mv.group(1).lower() not in _NAME_STOP:
            s["vorname"] = mv.group(1).capitalize()
    elif s["frage"] == "buchstabieren":
        nach = _nachgesprochen(t)
        if nach:
            # Statt zu buchstabieren hat der Anrufer den Namen (ggf. in
            # Silben: "MATTA VATTA") noch einmal gesprochen: übernehmen.
            if nach != s["nachname"]:
                s["bekannt"] = False if not s["patientId"] else s["bekannt"]
            s["nachname"] = nach
            s["buchstabiert"] = True
            neu.add("nachname")
        elif _name_aufnehmen(s, t, erzwungen=False):
            # "Der Nachname ist Panzer. P-A-N-Z-E-R. Der Vorname ist Paul":
            # explizite Zuweisungen zählen auch auf die Buchstabier-Frage.
            neu.add("name")
    elif s["frage"] in {"name", "vorname", "nachname"}:
        if _name_aufnehmen(s, t, erzwungen=True):
            neu.add("name")
    elif not s["nachname"] and _name_aufnehmen(s, t, erzwungen=False):
        neu.add("name")

    # Akten-Nummer-Konflikt: Entscheidung des Anrufers deuten (Chef 29.08.2026).
    # Diktiert der Satz zugleich eine NEUE Nummer ("die neue ist falsch,
    # richtig ist 0163…"), gewinnt der Nummern-Pfad — erst rueckbestaetigen,
    # die Konflikt-Frage kommt danach von selbst wieder.
    if s["frage"] == "telefon_alt" and not s["telefonAlt"] and not telefon.aus_satz(t):
        if _ALT_NEU_RE.search(t):
            s["telefonAlt"] = "neu"
            neu.add("telefonAlt")
        elif _ALT_AKTE_RE.search(t):
            s["telefonAlt"] = "akte"
            neu.add("telefonAlt")

    # Telefonnummer: gehört -> erst rückbestätigen, dann fest.
    if s["frage"] == "telefon_check":
        if ist_ja(t) and s["telefonOffen"]:
            s["telefon"] = s["telefonOffen"]
            s["telefonOk"] = True
            s["telefonOffen"] = ""
            neu.add("telefon")
        elif ist_nein(t):
            s["telefonOffen"] = ""
            neu.add("telefonKorrektur")
    d = telefon.aus_satz(t)
    if d and d != s["telefon"]:
        s["telefonOffen"] = d
        s["telefonTeil"] = ""
        s["telefonOk"] = False
        neu.add("telefonOffen")
    elif not d and s["frage"] in {"telefon", "telefon_check"} and not s["telefonOk"]:
        # Stückweise diktierte Nummer ("null eins sieben sieben" … Pause …
        # "sechshundert …"): Fragmente sammeln, bis die Kette plausibel ist.
        stueck = telefon.ziffern(t).replace("+", "")
        if 2 <= len(stueck) <= 13:
            if stueck.startswith("0") and len(stueck) >= 4:
                # Neue Nummer beginnt — der Anrufer setzt neu an.
                zusammen = stueck
            else:
                zusammen = (s["telefonTeil"] + stueck)[:16]
            if telefon.plausibel(zusammen):
                s["telefonOffen"] = telefon.normaliert(zusammen)
                s["telefonTeil"] = ""
                s["telefonOk"] = False
                neu.add("telefonOffen")
            else:
                s["telefonTeil"] = zusammen
                neu.add("telefonTeil")
    if (not d and s["frage"] != "telefon_alt"
            and (s["telefon"] or s["telefonOffen"]) and _TEL_FALSCH_RE.search(t)):
        # "Die Nummer war falsch": sofort verwerfen und neu erfragen —
        # ohne dass der Anrufer erst durch eine Rückbestätigung muss.
        # Bei offener Akten-Nummer-Frage meint "falsch" die ALTE Nummer aus
        # der Akte — die frisch bestaetigte bleibt unangetastet (29.08.2026).
        s["telefon"] = ""
        s["telefonOk"] = False
        s["telefonOffen"] = ""
        s["telefonTeil"] = ""
        neu.add("telefonKorrektur")
    if not d and not s["telefonOk"] and not s["telefonAkte"] and _AKTE_NUMMER_RE.search(t):
        # "Meine Nummer haben Sie ja in der Akte" — nicht darauf beharren,
        # die Akten-Nummer (oder die Praxis-Nachpflege) übernimmt das.
        s["telefonAkte"] = True
        neu.add("telefonAkte")

    # Versichertenstatus (Chef 29.08.2026): in der offenen Frage zaehlt das
    # nackte Wort ("privat"), ausserhalb nur mit Kontext ("ich bin privat
    # versichert"). Verneinte Nennungen ("nicht mehr privat") werden vor dem
    # Schluesselwort-Blick neutralisiert — sie bedeuten das GEGENTEIL und
    # laufen unten ueber den Wechsel-Zweig.
    if not s["versicherungOk"]:
        in_frage = s["frage"] in {"versicherung", "versicherung_check"}
        t_vers = re.sub(r"nicht\s+mehr\s+(?:privat\w*|gesetzlich\w*)", " ", tl)
        privat = bool(_VERS_PRIVAT_RE.search(t_vers))
        gesetzlich = bool(_VERS_GESETZLICH_RE.search(t_vers))
        if privat and gesetzlich:
            privat = gesetzlich = False  # beides im Satz: unklar, nicht raten
        if (privat or gesetzlich) and (in_frage or _VERS_KONTEXT_RE.search(t)):
            wert = "privat" if privat else "gesetzlich"
            s["versicherung"] = wert
            s["versicherungOk"] = True
            s["versicherungWechsel"] = bool(s["versicherungAkte"] and s["versicherungAkte"] != wert)
            neu.add("versicherung")
        elif s["frage"] == "versicherung_check" and s["versicherungAkte"]:
            if _VERS_WECHSEL_RE.search(t) or ist_nein(t):
                # Es gibt nur zwei Zustaende — "hat sich geaendert" heisst
                # deterministisch das Gegenteil des Kartei-Stands.
                s["versicherung"] = "gesetzlich" if s["versicherungAkte"] == "privat" else "privat"
                s["versicherungOk"] = True
                s["versicherungWechsel"] = True
                neu.add("versicherung")
            elif ist_ja(t):
                s["versicherung"] = s["versicherungAkte"]
                s["versicherungOk"] = True
                s["versicherungWechsel"] = False
                neu.add("versicherungCheck")

    # Zahnreinigung-Mitbuchung (Chef 30.08.2026): Antwort auf die offene
    # PZR-Frage oder spontaner Wunsch. Nur wenn der Termin-Grund selbst
    # keine Zahnreinigung ist — sonst deutet der Satz den HAUPTGRUND.
    if s["pzr"] in {"", "gefragt"} and s["grund"] and not ist_pzr_grund(s):
        if _PZR_KEINE_RE.search(t):
            if s["pzr"] == "gefragt":
                s["pzr"] = "nein"
                neu.add("pzr")
        elif _PZR_DAZU_RE.search(t):
            s["pzr"] = "ja"
            neu.add("pzr")
        elif s["frage"] == "pzr":
            if ist_ja(t):
                s["pzr"] = "ja"
                neu.add("pzr")
            elif ist_nein(t):
                s["pzr"] = "nein"
                neu.add("pzr")

    # Vornamen-Waechter (Chef 29.08.2026): Anrede-Geschlecht aus dem Vornamen,
    # sobald er da ist oder korrigiert wurde. Ein Kartei-Geschlecht (Quelle
    # "akte", gesetzt vom Hintergrund-Treffer) wird NIE ueberschrieben.
    if s["vorname"] and s["geschlechtQuelle"] != "akte" and s["geschlechtVon"] != s["vorname"]:
        g = vornamen.geschlecht(s["vorname"])
        s["geschlecht"] = g or "f"  # Chef: unklarer Vorname -> weiblich + Notiz
        s["geschlechtUnklar"] = not g
        s["geschlechtQuelle"] = "rate"
        s["geschlechtVon"] = s["vorname"]

    return neu


# Formulierungs-Varianten je Pflichtfrage für den Wiederholungs-Wächter
# (kern/wiederholung.py): muss dieselbe Frage erneut gestellt werden, kommt
# die nächste Form — nie zweimal derselbe Wortlaut (Chef 27.08.2026: "nie
# wieder doppelte telefonnummer oder behandler abfragen"). JEDE Variante
# trägt die Kern-Wörter aus agent._FRAGE_KERN, damit Anker/Wachen sie
# weiter als die offene Frage erkennen. telefon_check hat BEWUSST keine
# Varianten — die Rückbestätigung bleibt deterministisch.
FRAGE_VARIANTEN: dict[str, tuple[str, ...]] = {
    "schonmal": (
        "Waren Sie schon einmal bei uns?",
        "Kurz zur Einordnung: Waren Sie schon mal in unserer Praxis?",
    ),
    "arzt": (
        "Bei welchem Behandler waren Sie zuletzt?",
        "Wissen Sie den Namen Ihres Behandlers noch?",
    ),
    "name": (
        "Sagen Sie mir bitte noch Ihren Namen — Vor- und Nachname?",
        "Auf welchen Namen darf ich das aufnehmen?",
    ),
    "vorname": (
        "Wie ist Ihr Vorname?",
        "Welchen Vornamen darf ich notieren?",
    ),
    "nachname": (
        "Wie lautet der Nachname?",
        "Welchen Nachnamen darf ich eintragen?",
    ),
    "grund": (
        "Was ist denn der Grund für Ihren Besuch?",
        "Um welches Anliegen geht es denn?",
    ),
    "wunsch": (
        "Wann würde es Ihnen denn gut passen — eher vormittags oder nachmittags?",
        "Ab welchem Tag passt es Ihnen — und lieber vormittags oder nachmittags?",
    ),
    "buchstabieren": (
        "Buchstabieren Sie mir den Nachnamen bitte einmal?",
        "Mögen Sie den Nachnamen kurz buchstabieren?",
    ),
    "telefon": (
        "Welche Handynummer darf ich eintragen?",
        "Sagen Sie mir bitte noch Ihre Handynummer?",
    ),
    "slotwahl": (
        "Welcher davon passt Ihnen?",
        "Welcher der Termine passt Ihnen am besten?",
    ),
    "bestaetigung": (
        "Darf ich den Termin so eintragen?",
        "Soll ich es so festhalten?",
    ),
    "versicherung": (
        "Sind Sie privat oder gesetzlich versichert?",
        "Wie sind Sie versichert — privat oder gesetzlich?",
    ),
    "versicherung_check": (
        "Hat sich an Ihrer Versicherung etwas geändert — privat oder gesetzlich?",
        "Sind Sie noch genauso versichert wie bei Ihrem letzten Besuch — privat oder gesetzlich?",
    ),
    "pzr": (
        "Möchten Sie eine professionelle Zahnreinigung mit dazu?",
        "Soll die Zahnreinigung mit auf den Termin?",
    ),
}

# Behandler-WAHL fuer Neupatienten (Chef 29.08.2026: "es muss zu beginn
# geklaert werden in welchem kalender und bei welchem arzt du suchen sollst").
# Eigene Formen, weil die "arzt"-Varianten oben nach dem LETZTEN Behandler
# fragen — das waere bei jemandem, der noch nie da war, sachlich falsch.
# agent._wiederholungs_wache tauscht sie bei warSchonMal=False ein.
# Kern-Wort-Regel gilt auch hier: jede Form traegt "Behandler" (_FRAGE_KERN).
ARZTWAHL_VARIANTEN: tuple[str, ...] = (
    "Zu welchem unserer Behandler darf ich den Termin legen?",
    "Haben Sie einen Wunsch-Behandler — oder soll ich einfach schauen, wo der nächste freie Termin ist?",
)


def arztwahl_frage(tenant: dict | None) -> str:
    """Behandler-Frage fuer Neupatienten MIT den Namen zur Auswahl.

    Die Namen kommen aus den Tenant-Kalendern (jeder Behandler hat seinen
    eigenen Kalender samt Id) in Sprechform ("Doktor Petsas" — Vorname faellt
    weg, kern.patients.arzt_sprechname). "Egal" bleibt eine gueltige Antwort:
    einsammeln setzt dann typ=egal und die Slot-Suche nimmt den Praxis-Default.
    """
    namen: list[str] = []
    for c in (tenant or {}).get("calendars") or []:
        n = arzt_sprechname(_s((c or {}).get("name")))
        if n and n not in namen:
            namen.append(n)
    if len(namen) < 2:
        return ARZTWAHL_VARIANTEN[0]
    liste = ", ".join(namen[:-1]) + " oder " + namen[-1]
    return f"Zu welchem unserer Behandler möchten Sie — {liste}?"


def readback_text(nummer: str) -> str:
    """Nummern-Rückbestätigung als DREI eigenständige Sätze (P1 Readback-
    Parallelisierung 29.08.2026): Vorsatz und Schlussfrage sind vorgewärmt
    (feste_saetze) und spielen SOFORT aus dem Pin-Cache, während der
    Ziffern-Satz im stimme_stream-Feeder blocking gerendert und vom
    Nachhör-Wächter verifiziert wird — gefühlte Wartezeit nahe null,
    Sicherheit unverändert. Der Ziffern-Satz beginnt GROSS, sonst trennt
    der Satz-Split ihn nicht vom Vorsatz ab."""
    z = telefon.sprechbar(nummer)
    z = z[:1].upper() + z[1:]
    return f"Ich wiederhole die Nummer. {z}. Stimmt das so?"


def feste_saetze(tenant: dict | None = None) -> list[str]:
    """Alle festen Maschinen-Sätze für den TTS-Platten-Cache (28.08.2026).

    Die Buchungs-Maschine spricht diese Fragen wörtlich (naechste_frage
    unten, plus die Wiederholungs-Varianten). Sie tragen NIE Patientendaten
    und dürfen deshalb wie Füller und Begrüßung dauerhaft gecacht werden —
    aus dem Cache antwortet die Maschine in ~0,2 s statt einer vollen
    lokalen Synthese (~1,2 s). Bei Textänderungen in naechste_frage HIER
    mitziehen; ein vergessener Satz ist nur langsamer, nie falsch.
    """
    erstformen = [
        "Waren Sie denn schon einmal bei uns in der Praxis?",
        "Wissen Sie noch, bei welchem Behandler Sie zuletzt waren?",
        "Und der Nachname, bitte?",
        "Damit ich Sie in der Kartei finde: Wie ist Ihr Vor- und Nachname?",
        "Dann nehme ich Sie einmal auf: Wie ist Ihr Vor- und Nachname?",
        "Und der Vorname?",
        "Worum geht es denn — eine Kontrolle, Schmerzen, oder etwas anderes?",
        "Wann passt es Ihnen am besten — eher vormittags oder nachmittags? Und ab welchem Tag?",
        "Ich will nichts falsch schreiben: Buchstabieren Sie mir den Nachnamen bitte einmal kurz?",
        "Damit ich nichts falsch schreibe: Buchstabieren Sie den Nachnamen bitte einmal kurz?",
        "Da fehlt noch ein Stück von der Nummer — sagen Sie sie bitte einmal komplett, Ziffer für Ziffer.",
        "Und unter welcher Handynummer erreichen wir Sie?",
        "Und unter welcher Handynummer erreichen wir Sie? Die brauche ich für die Terminbestätigung.",
        "Und sind Sie privat oder gesetzlich versichert?",
        "Kurz für unsere Unterlagen: Sind Sie privat oder gesetzlich versichert?",
        ("Ihr letzter Besuch ist ja schon eine Weile her — kurz für unsere "
         "Unterlagen: Sind Sie weiterhin privat versichert, oder hat sich da etwas geändert?"),
        ("Ihr letzter Besuch ist ja schon eine Weile her — kurz für unsere "
         "Unterlagen: Sind Sie weiterhin gesetzlich versichert, oder hat sich da etwas geändert?"),
        "Soll ich Ihnen direkt eine professionelle Zahnreinigung mit dazu buchen?",
        ("Ihr letzter Besuch ist ja schon eine Weile her — soll ich Ihnen "
         "direkt eine professionelle Zahnreinigung mit dazu buchen?"),
        # P1 Readback-Parallelisierung: Vorsatz + Schlussfrage der Nummern-
        # Rückbestätigung (readback_text) — gewärmt spielt der Vorsatz
        # sofort, während der Ziffern-Satz rendert und nachgehört wird.
        "Ich wiederhole die Nummer.",
        "Stimmt das so?",
    ]
    out = list(erstformen)
    # Kirri-Zettel (gesprochene Zeile nach dem Verbinden-Jingle) mitwaermen —
    # Import in der Funktion, weil weiterleiten selbst gehirn importiert.
    from bianca import weiterleiten as _wl
    out.append(_wl.ANSAGE_PLATZHALTER)
    # Behandler-Wahl fuer Neupatienten: die Erstform traegt die Namen aus
    # dem Tenant (nur mit Tenant baubar), die Varianten sind statisch.
    if tenant:
        out.append(arztwahl_frage(tenant))
    out.extend(ARZTWAHL_VARIANTEN)
    for varianten in FRAGE_VARIANTEN.values():
        for v in varianten:
            if v not in out:
                out.append(v)
    return out


_HERR = {"m", "male", "herr", "mann", "männlich", "maennlich"}
_FRAU = {"f", "w", "female", "frau", "weiblich"}


def anrede(s: dict, patient: dict | None = None, *, beugen: bool = False) -> str:
    """Geschlechts-Anrede 'Frau Müller' / 'Herr Müller' (beugen: 'Herrn Müller').

    Kartei-Geschlecht schlaegt die Vornamen-Schaetzung. Der Vornamen-Waechter
    setzt bei unklaren Namen ohnehin den Chef-Default weiblich — faellt
    trotzdem alles aus, bleibt der volle Name (nie falsch raten)."""
    last = _s(s.get("nachname"))
    if not last:
        return ""
    g = (_s((patient or {}).get("gender")) or _s(s.get("geschlecht"))).lower()
    if g in _HERR:
        return f"{'Herrn' if beugen else 'Herr'} {last}"
    if g in _FRAU:
        return f"Frau {last}"
    return f"{_s(s.get('vorname'))} {last}".strip()


def telefon_alt_frage(s: dict) -> str:
    """Konflikt-Frage MIT der Alt-Nummer aus der Akte (Chef 29.08.2026:
    'Ich habe hier noch eine andere Nummer stehen …'). Bewusst wortgleich
    wiederholbar — der Anrufer darf sie mehrfach vorgelesen bekommen; der
    Wiederholungs-Wächter lässt Ziffern-Sätze grundsätzlich in Ruhe."""
    return (
        "Ich habe hier in Ihrer Akte noch eine andere Nummer stehen: "
        f"{telefon.sprechbar(s.get('aktePhone') or '')}. "
        "Soll ich die alte Nummer löschen und Ihre neue eintragen — "
        "oder die Bestätigungs-SMS an die alte Nummer schicken?"
    )


# Adaptive Stille-Schwelle fuers Dock (W-TEMPO 29.08.2026, Chef: "ich will
# 300 ms schneller werden"): Die Maschine WEISS, was sie gefragt hat — nach
# einer Ja/Nein- oder Wahlfrage kommt eine kurze Antwort (350 ms Ruhe
# reichen als Zugende), beim Ziffern-/Buchstabier-Diktat sind Denkpausen
# normal (650 ms, NIE mitten in der Nummer abschneiden). Default bleiben
# die bewaehrten 500 ms (27.08.2026: "nicht in Denkpausen hineinreden").
_STILLE_KURZ = {"schonmal", "arzt", "slotwahl", "bestaetigung", "versicherung",
                "versicherung_check", "pzr", "telefon_alt", "telefon_check",
                "rueckblick"}
_STILLE_DIKTAT = {"telefon", "buchstabieren"}


def stille_ms(s: dict) -> int:
    """Wie viel Ruhe gilt fuer die NAECHSTE Antwort als Zugende?"""
    fid = _s((s or {}).get("frage"))
    if fid in _STILLE_KURZ:
        return 350
    if fid in _STILLE_DIKTAT:
        return 650
    return 500


def naechste_frage(sit: dict) -> tuple[str, str]:
    """Welches Pflichtfeld fehlt als nächstes — und wie fragt Bianca danach?"""
    s = sammler(sit)

    # Eine gehörte Nummer wird IMMER erst rückbestätigt (Chef: sicher aufnehmen).
    if s["telefonOffen"] and not s["telefonOk"]:
        return "telefon_check", readback_text(s["telefonOffen"])

    # Akte gefunden, traegt aber eine ANDERE Nummer als die gerade
    # rueckbestaetigte: der Anrufer entscheidet (Chef 29.08.2026) — alte
    # Nummer loeschen/ersetzen oder die Bestaetigungs-SMS an die alte.
    if (s["telefonOk"] and s["telefon"] and s["patientId"] and s["aktePhone"]
            and not s["telefonAlt"]
            and telefon.normaliert(s["telefon"]) != telefon.normaliert(s["aktePhone"])):
        return "telefon_alt", telefon_alt_frage(s)

    if s["warSchonMal"] is None:
        return "schonmal", "Waren Sie denn schon einmal bei uns in der Praxis?"

    if s["warSchonMal"]:
        if not s["arzt"]:
            return "arzt", "Wissen Sie noch, bei welchem Behandler Sie zuletzt waren?"
        # Name früh: dann läuft die Kartei-Suche im Hintergrund, während wir
        # Grund und Wunschzeit klären — genau das macht das Tempo.
        if not s["nachname"]:
            if s["vorname"]:
                return "nachname", "Und der Nachname, bitte?"
            wen = f"Wie heißt {'Ihr' if s['fuerWen'] in {'sohn', 'mann', 'vater', 'opa'} else 'Ihre'} {s['fuerWen']}?" if s["fuerWen"] else "Damit ich Sie in der Kartei finde: Wie ist Ihr Vor- und Nachname?"
            return "name", wen
        if not s["vorname"]:
            return "vorname", "Und der Vorname?"
        if not s["grund"]:
            return "grund", "Worum geht es denn — eine Kontrolle, Schmerzen, oder etwas anderes?"
        if s["wunsch"] is None:
            return "wunsch", "Wann passt es Ihnen am besten — eher vormittags oder nachmittags? Und ab welchem Tag?"
        if not s["bekannt"] and not s["buchstabiert"]:
            return "buchstabieren", "Ich will nichts falsch schreiben: Buchstabieren Sie mir den Nachnamen bitte einmal kurz?"
        if not s["telefonOk"] and not s["telefonAkte"] and not (s["bekannt"] and s["aktePhone"]):
            if s["telefonTeil"]:
                return "telefon", "Da fehlt noch ein Stück von der Nummer — sagen Sie sie bitte einmal komplett, Ziffer für Ziffer."
            return "telefon", "Und unter welcher Handynummer erreichen wir Sie?"
        fid_v, frage_v = _versicherung_frage(s)
        if fid_v:
            return fid_v, frage_v
        return "", ""

    # Neu bei uns: erst den Behandler klaeren (Chef 29.08.2026 — sonst
    # landet alles still im Default-Kalender von Doktor Petsas), dann
    # Anliegen und Zeit, dann sauber aufnehmen. Bei nur EINEM Kalender
    # gibt es nichts zu waehlen — dann bleibt der Default richtig.
    if not s["arzt"]:
        cals = [c for c in (sit.get("tenant") or {}).get("calendars") or []
                if _s((c or {}).get("id"))]
        if len(cals) >= 2:
            return "arzt", arztwahl_frage(sit.get("tenant"))
    if not s["grund"]:
        return "grund", "Worum geht es denn — eine Kontrolle, Schmerzen, oder etwas anderes?"
    if s["wunsch"] is None:
        return "wunsch", "Wann passt es Ihnen am besten — eher vormittags oder nachmittags? Und ab welchem Tag?"
    if not s["nachname"]:
        if s["vorname"]:
            return "nachname", "Und der Nachname, bitte?"
        wen = f"Wie heißt {'Ihr' if s['fuerWen'] in {'sohn', 'mann', 'vater', 'opa'} else 'Ihre'} {s['fuerWen']}?" if s["fuerWen"] else "Dann nehme ich Sie einmal auf: Wie ist Ihr Vor- und Nachname?"
        return "name", wen
    if not s["vorname"]:
        return "vorname", "Und der Vorname?"
    if not s["buchstabiert"] and not s["bekannt"]:
        return "buchstabieren", "Damit ich nichts falsch schreibe: Buchstabieren Sie den Nachnamen bitte einmal kurz?"
    if not s["telefonOk"] and not s["telefonAkte"]:
        if s["telefonTeil"]:
            return "telefon", "Da fehlt noch ein Stück von der Nummer — sagen Sie sie bitte einmal komplett, Ziffer für Ziffer."
        return "telefon", "Und unter welcher Handynummer erreichen wir Sie? Die brauche ich für die Terminbestätigung."
    fid_v, frage_v = _versicherung_frage(s)
    if fid_v:
        return fid_v, frage_v
    return "", ""


def besuch_lange_her(s: dict, tage: int = 183) -> bool:
    """Liegt der letzte Besuch mehr als ~6 Monate zurück? Ohne Datum: False."""
    iso = _s(s.get("letzterBesuch"))[:10]
    if not iso:
        return False
    try:
        d = datetime.strptime(iso, "%Y-%m-%d").date()
    except ValueError:
        return False
    return (datetime.now(TZ).date() - d).days > tage


def versicherung_check_frage(s: dict) -> str:
    """Bestands-Rückfrage MIT dem Kartei-Stand (nur privat<->gesetzlich zählt)."""
    art = "privat" if _s(s.get("versicherungAkte")) == "privat" else "gesetzlich"
    return (
        "Ihr letzter Besuch ist ja schon eine Weile her — kurz für unsere "
        f"Unterlagen: Sind Sie weiterhin {art} versichert, oder hat sich da "
        "etwas geändert?"
    )


def _versicherung_frage(s: dict) -> tuple[str, str]:
    """Versichertenstatus-Frage, wenn sie dran ist — sonst ('', '').

    Neupatient (war noch nie da): immer fragen, der Wert geht in die neue
    Kartei. Bestandsakte: NUR wenn der letzte Besuch >6 Monate her ist (Chef
    29.08.2026), mit bekanntem Kartei-Stand als Ja/Nein-Rückfrage. Bestand
    OHNE Kartei-Treffer: nicht fragen — nicht auf Verdacht verhören."""
    if s["versicherungOk"]:
        return "", ""
    if s["bekannt"]:
        if not besuch_lange_her(s):
            return "", ""
        if s["versicherungAkte"]:
            return "versicherung_check", versicherung_check_frage(s)
        return "versicherung", "Kurz für unsere Unterlagen: Sind Sie privat oder gesetzlich versichert?"
    if s["warSchonMal"]:
        return "", ""
    return "versicherung", "Und sind Sie privat oder gesetzlich versichert?"


# --- Rueckblick auf den letzten Besuch + Zahnreinigung-Mitbuchung (30.08.2026) ---

_PZR_GRUND_RE = re.compile(r"zahnreinigung|prophylaxe|\bpzr\b|zahnstein", re.I)
_AKUT_GRUND_RE = re.compile(r"akut|notfall|schmerz|zahnweh|\bweh\b", re.I)
# "PAR 1 Besprechung" / "KCH Kontrolluntersuchung": Fachkuerzel + Ziffer weg.
_MOTIV_KUERZEL_RE = re.compile(r"^[A-ZÄÖÜ]{2,4}\s*\d?\s+")

_ZAHL_WORT = {2: "zwei", 3: "drei", 4: "vier", 5: "fünf", 6: "sechs", 7: "sieben",
              8: "acht", 9: "neun", 10: "zehn", 11: "elf"}


def _besuch_tage(s: dict) -> int:
    """Tage seit dem letzten Besuch — -1 ohne (lesbares) Datum."""
    iso = _s(s.get("letzterBesuch"))[:10]
    if not iso:
        return -1
    try:
        d = datetime.strptime(iso, "%Y-%m-%d").date()
    except ValueError:
        return -1
    return (datetime.now(TZ).date() - d).days


def abstand_worte(tage: int) -> str:
    """Sprechbarer Abstand: 'über zwei Jahre', 'etwa acht Monate', 'ein paar Wochen'."""
    if tage >= 365:
        jahre = tage // 365
        if jahre >= 2:
            return f"über {_ZAHL_WORT.get(jahre, str(jahre))} Jahre"
        if tage >= 548:
            return "über anderthalb Jahre"
        return "über ein Jahr"
    if tage >= 60:
        monate = max(2, round(tage / 30.44))
        return f"etwa {_ZAHL_WORT.get(monate, str(monate))} Monate"
    return "ein paar Wochen"


def grund_sprechbar(name: str) -> str:
    """Motivname in sprechbare Form: Kuerzel weg, Slash-Alternative gekappt.

    'KCH akute Beschwerden/Notfall' -> 'akute Beschwerden' — die TTS liest
    sonst Kuerzel und Schraegstrich vor."""
    roh = _MOTIV_KUERZEL_RE.sub("", _s(name))
    return _s(roh.split("/")[0]) or _s(name)


def ist_pzr_grund(s: dict) -> bool:
    """Ist der NEUE Termin selbst schon eine Zahnreinigung? (Chef: dann nie fragen.)"""
    return bool(_PZR_GRUND_RE.search(f"{s.get('motivName') or ''} {s.get('grund') or ''} {s.get('grundWortlaut') or ''}"))


def _ist_akut(s: dict) -> bool:
    return bool(_AKUT_GRUND_RE.search(f"{s.get('grund') or ''} {s.get('grundWortlaut') or ''}"))


def verlaufs_frage(letzter_grund: str) -> str:
    """Verlaufs-Frage passend zur letzten Behandlung (Chef 30.08.2026).

    OP/Chirurgie -> verheilt? Zahnersatz-Eingliederung -> zufrieden?
    Narval-/Schnarchschiene -> Werte im Schlaflabor kontrolliert?
    Wurzelbehandlung -> Ruhe? Besprechungen/Kontrollen -> allgemein."""
    n = _s(letzter_grund).lower()
    if re.search(r"besprechung|beratung|planerstellung|kontroll|untersuchung|aufklärung|aufklaerung", n):
        return "Ist damals alles gut verlaufen?"
    if re.search(r"narval|schien|schnarch|apnoe|protrusion|\bslm\b", n):
        return "Wurden die Werte im Schlaflabor mit der Schiene schon einmal kontrolliert — und gab es eine Besserung?"
    if re.search(r"eingliederung|zahnersatz|prothes|krone|brück|brueck|teleskop|\bze\b|verblendung", n):
        return "Sind Sie mit dem Zahnersatz denn zufrieden?"
    if re.search(r"\bop\b|operation|chirurg|extrakt|weisheit|osteotomie|wurzelspitzen|implantat|aufbau|augmentation", n):
        return "Ist denn alles gut verheilt?"
    if re.search(r"wurzel|endo|\bwk\b", n):
        return "Ist der Zahn seitdem denn ruhig geblieben?"
    return "Ist damals alles gut verlaufen?"


def rueckblick_faellig(s: dict) -> bool:
    """Steht die Ansprache des letzten Besuchs an? EINMAL pro Anruf.

    Nur Bestandsakte mit Historie (Datum + Grund), nur im Sammel-Teil der
    Buchung, nie bei akuten Beschwerden (Schmerzpatienten plaudert man
    nicht voll) und nie, wenn der Besuch erst wenige Tage her ist."""
    if s.get("modus") != "buchen" or not s.get("bekannt") or s.get("rueckblick"):
        return False
    if s.get("phase") in {"angebot", "bestaetigen", "gebucht", "fertig"}:
        return False
    if not s.get("letzterGrund") or _ist_akut(s):
        return False
    return _besuch_tage(s) > 7


def rueckblick_text(s: dict) -> str:
    """Die Rueckblick-Ansprache: Abstand + letzter Grund + Verlaufs-Frage."""
    tage = _besuch_tage(s)
    grund = grund_sprechbar(s.get("letzterGrund") or "")
    if tage >= 730:
        vorsatz = (f"Ich sehe gerade: Ihr letzter Besuch ist ja schon {abstand_worte(tage)} her — "
                   f"damals ging es um {grund}. ")
    else:
        # "ist ... her" statt "war vor ...": die Abstands-Woerter stehen im
        # Nominativ ("etwa acht Monate") — nach "vor" braeuchte es den Dativ.
        vorsatz = (f"Ich sehe gerade: Ihr letzter Besuch ist {abstand_worte(tage)} her — "
                   f"da ging es um {grund}. ")
    return vorsatz + verlaufs_frage(s.get("letzterGrund") or "")


_RB_SCHLECHT_RE = re.compile(
    r"schlecht|\bweh\b|schmerz|problem|leider|entzünd|entzuend|kompliziert|schwierig|"
    r"nicht\s+(?:gut|zufrieden|verheilt|so\s+toll|wirklich)|unzufrieden|beschwerden",
    re.I,
)
_RB_GUT_RE = re.compile(
    r"\bgut\b|super|prima|bestens|wunderbar|\btop\b|zufrieden|verheilt|problemlos|"
    r"keine\s+(?:probleme|beschwerden)|alles\s+(?:gut|bestens|okay|ok|prima|glatt)|passt",
    re.I,
)


def rueckblick_reaktion(text: str) -> str:
    """Deterministische Mini-Empathie NUR bei klar positiver Kurzantwort.

    Alles andere (negativ, erzaehlend, Gegenfrage) geht ans LLM — Chef
    30.08.2026: 'LLM-Antworten auf das sich vielleicht entwickelnde
    Gespraech'."""
    t = _s(text)
    if _RB_SCHLECHT_RE.search(t):
        return ""
    if _RB_GUT_RE.search(t) or (ist_ja(t) and len(t) <= 40):
        return "Das freut mich zu hören! "
    return ""


def pzr_faellig(s: dict) -> bool:
    """Zahnreinigung anbieten? Sobald die Kartei den Vortermin hergibt
    (Chef 29.08.2026: "vortermin zwar gefunden aber keine zahnreinigung mit
    angeboten!! das solltest du tun") — Bestand im Sammel-Teil der Buchung,
    der NEUE Termin ist selbst keine Zahnreinigung, kein Schmerz-/Notfall-
    Termin, EINMAL pro Anruf. Einzige Zeitschranke: war der LETZTE Besuch
    selbst eine Zahnreinigung und liegt er keine 6 Monate zurueck, ist die
    Reinigung frisch — dann nicht noch eine anbieten."""
    if s.get("modus") != "buchen" or not s.get("bekannt") or s.get("pzr"):
        return False
    if s.get("phase") in {"angebot", "bestaetigen", "gebucht", "fertig"}:
        return False
    if not s.get("grund") or ist_pzr_grund(s) or _ist_akut(s):
        return False
    if _PZR_GRUND_RE.search(_s(s.get("letzterGrund"))) and not besuch_lange_her(s):
        return False
    return True


def pzr_frage(s: dict) -> str:
    """Die Mitbuch-Frage — der Zeitbezug ("schon eine Weile her") kommt nur,
    wenn er WAHR ist und der Rueckblick ihn nicht schon gesprochen hat
    (Chef-Fall 29.08.: Besuch erst sechs Wochen her — da waere "eine Weile
    her" gelogen). Beide Formen sind statisch und liegen im TTS-Platten-
    Cache (feste_saetze)."""
    if s.get("rueckblick") or not besuch_lange_her(s):
        return "Soll ich Ihnen direkt eine professionelle Zahnreinigung mit dazu buchen?"
    return ("Ihr letzter Besuch ist ja schon eine Weile her — soll ich Ihnen "
            "direkt eine professionelle Zahnreinigung mit dazu buchen?")


def motiv_fuer_kalender(sit: dict, calendar_id: str) -> dict | None:
    """Besuchsgrund fuer den ZIEL-Kalender frisch aufloesen (Chef 30.08.2026).

    Das Mapping passiert in jedem Anruf neu und BEHANDLERSPEZIFISCH: gleiche
    Motive sind je Kalender unterschiedlich sichtbar (calendarIds). Gesucht
    wird das erkannte Konzept im frischen Katalog, gefiltert auf den Ziel-
    Kalender; danach das bereits gewaehlte Motiv (wenn der Ziel-Kalender es
    fuehrt); zuletzt der Zweifelsfall Kontrolle/Besprechung. None = nichts
    Passendes, der Aufrufer laesst den alten Stand stehen."""
    s = sammler(sit)
    tenant = sit.get("tenant") or {}
    kat = motive.katalog(sit)
    if not kat:
        return None
    muster = besuchsgrund.konzept_muster(f"{s['grundWortlaut']} {s['grund']}")
    vm = None
    if muster:
        vm = besuchsgrund.motiv_suchen(tenant, muster, katalog=kat, calendar_id=calendar_id)
    if not vm and s["motivId"]:
        aktuell = next((v for v in kat if _s(v.get("id")) == s["motivId"]), None)
        if aktuell and motive.erlaubt(aktuell, calendar_id):
            vm = aktuell
    if not vm and s["grund"]:
        vm = besuchsgrund.fallback_motiv(tenant, katalog=kat, calendar_id=calendar_id)
    return vm


def start_datum(s: dict) -> str:
    """Ab wann suchen? Wunschdatum > 'nächste Woche' > sofort."""
    w = s.get("wunsch") or {}
    if w.get("date"):
        return str(w["date"])
    tage = int(w.get("minDaysAhead") or 0)
    if tage:
        return (datetime.now(TZ).date() + timedelta(days=tage)).isoformat()
    return ""
