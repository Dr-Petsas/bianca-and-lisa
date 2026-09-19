"""Meta-Bitten des Anrufers UEBER das Gespraech — nicht ueber sein Anliegen.

Drei kurze, formelhafte Bitten, die am Telefon jeder stellt und die ein reines
Anliegen-Verstehen nicht abbildet (Rasa CALM fuehrt sie als eigene Befehle
``repeat bot messages`` / ``cancel flow`` / ``skip question``):

  ``wiederholen``  "Wie bitte?", "Koennen Sie das nochmal sagen?"
  ``abbrechen``    "Vergessen Sie's", "Hat sich erledigt"
  ``auslassen``    "Das moechte ich nicht sagen", "Muss das sein?"

Bewusst DETERMINISTISCH (0 ms, kein Modell, nur stdlib): es sind Formeln, keine
Semantik — und sie muessen auch dann greifen, wenn kein Modell erreichbar ist.
Ein Anrufer, der zum dritten Mal "Wie bitte?" sagt, darf nicht auf ein vLLM
warten.

Die GEGENPROBEN sind hier der teurere Teil: ein Fehltreffer verwirft eine
laufende Aufgabe oder verschluckt eine diktierte Nummer. Darum vier Wachen:

  1. **Wer selbst wiederholt, bittet nicht.** "Ich wiederhole: null eins sieben
     …" ist Diktat, keine Bitte. Eine Wiederholungsbitte spricht Bianca an
     (Sie/Imperativ) oder ist die nackte Formel ("Wie bitte?").
  2. **Ziffern oder Buchstabiertafel im Zug = Daten.** Dann nie ein Meta-Wunsch,
     egal welche Formel sonst noch im Satz steht.
  3. **Nur kurze Zuege.** Eine Formel steht allein oder mit knapper Begruendung.
     Wer einen ganzen Satz spricht, verfolgt ein Anliegen.
  4. **Vor einer Schreibaktion nur harte Formeln** (``streng=True``): auf ein
     Slot-Angebot oder eine Ruecklese heisst "moechte ich doch nicht" oft nur
     "dieser Termin nicht" — den Abbruch des ganzen Anliegens loest dort
     ausschliesslich ein unmissverstaendliches "Vergessen Sie's" aus.

Keine Absage-Woerter: "absagen", "stornieren", "loeschen" sind ein ANLIEGEN
(Familie VERWALTEN) und tauchen hier nirgends auf.
"""

from __future__ import annotations

import re

WIEDERHOLEN = "wiederholen"
ABBRECHEN = "abbrechen"
AUSLASSEN = "auslassen"

# Eine Formel steht allein oder mit knapper Begruendung. Alles Laengere ist ein
# Anliegen — dort entscheidet das Verstehen, nicht diese Tabelle.
_MAX_WOERTER = 12

# Daten-Wachen: sobald Ziffern, eine Buchstabiertafel ("A wie Anton") oder eine
# Einzelbuchstaben-Kette im Zug stehen, diktiert der Anrufer.
_ZIFFER_RE = re.compile(r"\d")
_TAFEL_RE = re.compile(r"\b[a-zäöüß]\s+wie\s+[a-zäöüß]", re.I)
_BUCHSTABEN_RE = re.compile(r"(?:\b[a-zäöüß]\b[\s.,-]+){2,}\b[a-zäöüß]\b", re.I)

# --------------------------------------------------------------------------- #
# Wiederholen.
# --------------------------------------------------------------------------- #
# "nochmal", "noch mal" UND "noch einmal" — die drei Schreibweisen derselben
# Bitte. Das eingeschobene "ein" ist am Telefon die haeufigste Form; ohne diese
# Klammer fiel "Koennen Sie das noch einmal sagen?" durch (Hoerprobe 19.09.).
_NOCHMAL = r"noch\s*(?:ein)?mal"

# Die nackte Formel: sie ist der haeufigste Fall und braucht keine Anrede.
# Fuellwoerter davor ("Entschuldigung, was?") gehoeren dazu — der Kern muss
# trotzdem die GANZE Aeusserung sein, sonst wird jedes "was" zur Bitte.
_WIEDERHOLEN_NACKT_RE = re.compile(
    r"^\s*(?:(?:entschuldigung|verzeihung|sorry)[,\s]+)?(?:"
    r"wie\s+bitte"
    r"|bitte"
    r"|was"
    r"|wie"
    r"|h(?:ae|ä)\?*"
    rf"|(?:und\s+)?{_NOCHMAL}(?:\s+bitte)?"
    r"|entschuldigung|verzeihung|sorry"
    r")\s*[.!?]*\s*$",
    re.I,
)
# Mit Anrede/Imperativ — hier darf die Formel im Satz stehen.
_WIEDERHOLEN_BITTE_RE = re.compile(
    r"(?:"
    r"(?:k(?:oe|ö)nn(?:en|ten)\s+sie|w(?:ue|ü)rden\s+sie)"
    rf".{{0,32}}(?:{_NOCHMAL}|wiederhol)"
    r"|wiederhol(?:en\s+sie|e?\s+(?:das|es|mal|bitte)|en\s+bitte)\b"
    rf"|sagen\s+sie\s+(?:das\s+|es\s+)?(?:bitte\s+)?{_NOCHMAL}"
    # Du-Imperativ ohne Anrede: "Sag das nochmal", "Sag mir das noch einmal".
    # Am Telefon duzt kaum jemand Bianca, im Dock-Chat tippt es aber jeder so.
    # Die Selbst-Wache unten haelt "Ich sage es nochmal: Mueller" davon fern.
    rf"|sag(?:e|en)?\s+(?:mir\s+)?(?:das\s+|es\s+)?(?:bitte\s+)?{_NOCHMAL}"
    r"|was\s+haben\s+sie\s+(?:gerade\s+|eben\s+)?gesagt"
    r"|ich\s+habe\s+sie\s+(?:akustisch\s+)?nicht\s+(?:geh(?:oe|ö)rt|verstanden)"
    r"|das\s+habe\s+ich\s+(?:akustisch\s+)?nicht\s+(?:mitbekommen|geh(?:oe|ö)rt)"
    rf"|{_NOCHMAL}\s+(?:bitte|die\s+(?:zeiten|termine|uhrzeit|nummer))"
    rf"|die\s+(?:zeiten|termine)\s+{_NOCHMAL}"
    r")",
    re.I,
)
# Wer selbst wiederholt, bittet nicht (Diktat-Falle). "Ich sage es nochmal" ist
# die haeufigste Form davon, seit der Du-Imperativ oben mitzaehlt.
_SELBST_RE = re.compile(r"\bich\s+(?:wiederhol|sag)", re.I)

# --------------------------------------------------------------------------- #
# Abbrechen.
# --------------------------------------------------------------------------- #
# HART: unmissverstaendlich, gilt in jeder Phase (auch vor einer Schreibaktion).
_ABBRECHEN_HART_RE = re.compile(
    r"(?:"
    r"vergess(?:en\s+sie(?:'s|\s+es|\s+das)?|\s+es)\b"
    r"|vergiss\s+(?:es|das)\b"
    # "Lassen wir das" bricht ab, "Lassen wir das OFFEN/weg/aus" laesst nur die
    # Frage aus — ein Wort Unterschied, zwei ganz verschiedene Wuensche.
    r"|lassen\s+(?:wir|sie)\s+(?:das|es)(?!\s+(?:offen|weg|aus)\b)\s*(?:sein|bleiben)?\b"
    r"|hat\s+sich\s+erledigt"
    r"|(?:ist|hat)\s+sich\s+(?:schon\s+)?erledigt"
    r"|(?:bitte\s+)?abbrechen\b"
    r"|\babbruch\b"
    r"|doch\s+kein(?:en|e)?\s+termin"
    r")",
    re.I,
)
# WEICH: plausibel, aber vor einer Schreibaktion doppeldeutig ("diesen Termin
# nicht" statt "das Anliegen nicht"). Nur ausserhalb der kritischen Phasen.
_ABBRECHEN_WEICH_RE = re.compile(
    r"(?:"
    # Beide Wortstellungen: "ich moechte doch nicht" UND "moechte ich doch nicht".
    r"(?:ich\s+)?(?:m(?:oe|ö)chte|will)\s+(?:ich\s+)?(?:das\s+)?doch\s+nicht(?:\s+mehr)?\b"
    r"|brauche\s+ich\s+(?:doch\s+)?nicht\s+mehr"
    r"|(?:ich\s+)?(?:mache|regle)\s+das\s+(?:sp(?:ae|ä)ter|selbst|anders)"
    r"|(?:ich\s+)?melde\s+mich\s+(?:sp(?:ae|ä)ter|noch\s*mal)\s+(?:wieder|selbst)"
    r")",
    re.I,
)

# --------------------------------------------------------------------------- #
# Auslassen.
# --------------------------------------------------------------------------- #
_AUSLASSEN_RE = re.compile(
    r"(?:"
    r"(?:das\s+)?sage\s+ich\s+(?:lieber\s+)?nicht\b"
    r"|m(?:oe|ö)chte\s+ich\s+(?:lieber\s+)?nicht\s+(?:sagen|angeben|nennen|verraten)"
    r"|will\s+ich\s+(?:lieber\s+)?nicht\s+(?:sagen|angeben|nennen|verraten)"
    r"|(?:das\s+)?(?:gebe|geb)\s+ich\s+nicht\s+(?:an|raus|bekannt)"
    r"|keine\s+angabe"
    r"|muss\s+das\s+(?:wirklich\s+|denn\s+)?sein"
    # "Ist das noetig?" NUR als ganze Aeusserung: "Ist das noetig fuer die
    # Behandlung?" ist eine echte Sachfrage und darf kein Feld ueberspringen.
    r"|^(?:und\s+)?ist\s+(?:das|es)\s+(?:wirklich\s+|denn\s+)?"
    r"(?:n(?:oe|ö)tig|notwendig|erforderlich|pflicht)\s*[.!?]*$"
    r"|brauchen\s+sie\s+das\s+(?:wirklich|denn|ueberhaupt|überhaupt)"
    r"|(?:das\s+)?lassen\s+(?:wir|sie)\s+(?:das\s+)?(?:offen|weg|aus)"
    r"|(?:das\s+)?(?:ueber|über)springen"
    r"|(?:frage\s+)?(?:ueber|über)spring"
    r")",
    re.I,
)
# "Weiss ich nicht" / "kann ich nicht sagen" ist NICHT-WISSEN, keine
# Verweigerung — das behandelt der normale Weg (z. B. Standard-Behandler).
_NICHT_WISSEN_RE = re.compile(
    r"wei(?:ss|ß)\s+ich\s+nicht|kann\s+ich\s+nicht\s+sagen|keine\s+ahnung",
    re.I,
)


def _hat_daten(text: str) -> bool:
    """Ziffern, Buchstabiertafel oder Buchstabenkette = Diktat, kein Meta-Wunsch."""
    return bool(
        _ZIFFER_RE.search(text)
        or _TAFEL_RE.search(text)
        or _BUCHSTABEN_RE.search(text)
    )


def deute(text: str, *, streng: bool = False) -> str:
    """Meta-Bitte im Zug, oder "". ``streng`` = vor einer Schreibaktion.

    ``streng=True`` setzt der Aufrufer, solange ein Slot-Angebot, eine Ruecklese
    oder eine destruktive Bestaetigung offen ist: dort zaehlt fuer den Abbruch
    nur eine harte Formel, weil "moechte ich doch nicht" dann meist den
    angebotenen TERMIN meint und nicht das Anliegen.
    """
    t = " ".join(str(text or "").split())
    if not t:
        return ""
    if len(t.split()) > _MAX_WOERTER:
        return ""
    if _hat_daten(t):
        return ""

    if _ABBRECHEN_HART_RE.search(t):
        return ABBRECHEN
    if not streng and _ABBRECHEN_WEICH_RE.search(t):
        return ABBRECHEN

    if not _SELBST_RE.search(t) and (
        _WIEDERHOLEN_NACKT_RE.match(t) or _WIEDERHOLEN_BITTE_RE.search(t)
    ):
        return WIEDERHOLEN

    if _AUSLASSEN_RE.search(t) and not _NICHT_WISSEN_RE.search(t):
        return AUSLASSEN

    return ""


__all__ = ["deute", "WIEDERHOLEN", "ABBRECHEN", "AUSLASSEN"]
