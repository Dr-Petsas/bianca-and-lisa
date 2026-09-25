"""Rechnungsthemen am Telefon (W-RECHNUNG 14.09.2026 — nicht rueckbauen).

Chef zum Thaler-Anruf 3ad3b6d3 (14.09.2026, woertlich): "Rechnungsreklamation.,
Fehlerhafte Rechnung., Fehler, abrechnungsfehler, Buchhaltung...Rechnung...
diese und aehnliche Worte/Saetze muessen wir nachschaerfen dadurch, dass Bianca
sagt, dass Rechnungsthemen nur persoenlich in der Praxis besprochen werden
koennen, oder sie einen Rueckruf anbietet und einrichtet auf Wunsch. Sie
selbst hat keine Autorisation, ueber Rechnungen zu reden."

Live antwortete Bianca auf "Rechnungsreklamation." und "Fehlerhafte Rechnung."
zweimal mit dem Unklar-Satz ("Ich habe ... verstanden. Was meinen Sie damit?")
— zwei verschenkte Zuege; erst im dritten fand das Modell einen Weg.

Dieses Modul ist die EINE Stelle fuer das Thema:
- ``erkannt(text, sit)``: deterministische Erkennung (0 ms, kein Modell),
- die festen Saetze (Erklaerung, Rueckruf-Frage, Quittungen — vorgewaermt),
- ``saeubern(text)``: die Wache am LLM-Ausgang — das Modell darf ueber
  Rechnungen nichts BEHAUPTEN (weder Betraege noch Zahlungsstaende noch
  "ich kuemmere mich"); der Verweis auf die Praxis bleibt stehen.

Bianca-frei wie kern/fach_wache.py: keine bianca-Imports auf Modulebene. Der
Behandler-Blick (ein NAMENTLICH verlangter Arzt schlaegt die Rechnungs-
Erklaerung — das bleibt Weiterleitung) wird lazy geholt.

Grenzen, bewusst gezogen (ein Fehltreffer kostet einen laufenden Vorgang):
- "Berechnung" ist keine Rechnung; "Was kostet eine Krone?" ist eine
  Preisfrage (Modell/Doktor), keine Reklamation; "Wird die Zahnreinigung
  von der Kasse abgerechnet?" ist die Zuschuss-Frage (kern/pzr_kassen).
- Weiche Woerter (Kosten, Betrag, bezahlt, abgerechnet ...) zaehlen nur mit
  Beschwerde-/Zahlungsstand-Marker im selben Satz und ohne Termin-Aufgabe.
- "Es geht nicht um die Rechnung" / "Ich brauche keine Rechnung" sind keine
  Rechnungsthemen; "Ich habe keine Rechnung bekommen" IST eines.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Harte Rechnungswoerter zaehlen IMMER (auch neben "Termin" im Satz).
# `\b(?!be)\w*rechnung(?:en|s<Kompositum>)?\b` faengt Rechnung(en), Abrechnung,
# Zahnarztrechnung, Privatrechnung, Rechnungsreklamation, Abrechnungsfehler,
# Rechnungskopie — aber nicht "Berechnung" und nicht den NACHNAMEN
# "Rechnungshofer" (nur bekannte Zusammensetzungen nach dem Fugen-s; ein
# unbekanntes Kompositum ohne weiteres Signal ist der billigere Fehler).
_RECHNUNG_KOMPOSITA = (
    r"nummer|betrag|betr(?:ä|ae)ge|kopie|stellung|legung|datum|reklamation|fehler"
    r"|frage|fragen|problem|beschwerde|posten|summe|adresse|anschrift|empf\w*"
    r"|eingang|ausgang|pr(?:ü|ue)fung|korrektur|wesen|abteilung|stelle|h(?:ö|oe)he"
    r"|doppel|duplikat|erkl(?:ä|ae)rung|details?|position\w*|zahlung|inhalt|angaben"
    r"|unterlagen|thema|themen|sache|kram|stellung"
)
_HART_RE = re.compile(
    r"\b(?!be)\w*rechnung(?:en|s(?:" + _RECHNUNG_KOMPOSITA + r")?)?\b"
    r"|\bmahn(?:ung|bescheid|geb(?:ü|ue)hr|verfahren|schreiben|kosten)\w*"
    r"|\bzahlungs(?:erinnerung|aufforderung|eingang|frist|ziel|verzug|r(?:ü|ue)ckstand)\w*"
    r"|\binkasso\w*|\blastschrift\w*|\bquittung\w*|\bbelege?\b"
    r"|\bratenzahlung\w*|\bverrechnungsstelle\w*"
    r"|\bhonorar\w*|\bgeb(?:ü|ue)hrenordnung\w*|\bgoz\b|\bbema\b",
    re.I,
)
# Rollen-Wort: "Buchhaltung" ist ein Rechnungsthema — ausser der Satz traegt
# eine Termin-Aufgabe ("die Buchhaltung meinte, ich soll einen Termin
# machen"): dann zaehlt es nur wie ein weiches Wort (mit Beschwerde-Marker).
_ROLLE_RE = re.compile(r"\bbuchhalt\w*", re.I)

# Weiche Woerter: nur zusammen mit einem Beschwerde-/Zahlungsstand-Marker,
# ohne Termin-Aufgabe und ohne Kassen-/PZR-Kontext im Satz.
_WEICH_RE = re.compile(
    r"\babgerechnet\b|\babrechnen\b|\bzahlung(?:en)?\b|\bbezahl\w*|\bgezahlt\b"
    r"|\b(?:ü|ue)berwiesen\b|\bbetrag\w*|\bbetr(?:ä|ae)ge\b|\bkosten\b"
    r"|\bgeb(?:ü|ue)hr(?:en)?\b|\bpreis\w*|\beuro\b|\babgebucht\b|\babbuchung\w*"
    r"|\bgeld\b",
    re.I,
)
_BESCHWERDE_RE = re.compile(
    r"\bfehler\w*|\bfalsch\w*|\bstimm(?:t|en)\s+(?:so\s+)?nicht\b"
    r"|\bnicht\s+(?:korrekt|richtig|nachvollzieh\w*|einverstanden|bekommen|erhalten"
    r"|bezahlt|gezahlt|(?:ü|ue)berwiesen|angekommen|abgebucht)"
    r"|\b(?:zu|so)\s+(?:hoch|viel|teuer)\b|\bzuviel\b|\bdoppelt\b|\bzweimal\b|\bzwei\s+mal\b"
    r"|\bnochmal\b|\bnoch\s+mal\b|\berneut\b|\breklam\w*|\bbeschwer\w*|\bwiderspr\w*"
    r"|\bunstimmig\w*|\boffen(?:e[rns]?)?\b|\bausstehend\w*"
    r"|\b(?:schon|bereits|l(?:ä|ae)ngst)\s+(?:bezahlt|gezahlt|(?:ü|ue)berwiesen)"
    r"|\berstatt\w*|\bzur(?:ü|ue)ck(?:zahl|(?:ü|ue)berweis|buch|bekomm|erstatt|haben|will|m(?:ö|oe)chte)\w*"
    r"|\babgebucht\b|\bstreit\w*",
    re.I,
)
# Kassen-/Prophylaxe-Kontext: Zuschuss- und Preisfragen zur Zahnreinigung
# beantwortet die bestehende PZR-Strecke — die weichen Woerter zaehlen dort nie.
_KASSEN_KONTEXT_RE = re.compile(
    r"zahnreinigung|prophylaxe|\bpzr\b|bleaching|aufhell\w*|zuschuss|bezuschuss\w*"
    r"|(?:ü|ue)bernimmt|(?:ü|ue)bernommen|(?:ü|ue)bernahme|bonus\w*|krankenkasse|\bkasse\b",
    re.I,
)
_TERMIN_RE = re.compile(r"\btermin\w*|\bbuchen\b|\bvereinbar\w*|\bausmachen\b", re.I)

# Kein Rechnungsthema: der Anrufer grenzt es AB oder will keine Rechnung.
_NICHT_THEMA_RE = re.compile(
    r"\bnicht\s+(?:um|wegen)\s+(?:\w+\s+){0,2}(?:\w*rechnung\w*|mahnung\w*|zahlung\w*|buchhaltung)"
    r"|\b(?:brauche|will|m(?:ö|oe)chte|ben(?:ö|oe)tige)\s+(?:auch\s+)?keine\s+(?:\w+\s+)?rechnung",
    re.I,
)

# Rueckruf ausdruecklich verlangt (dann faellt die Frage weg — direkt Name).
# "Rufen Sie mich wegen der Rechnung zurueck": zwischen "mich" und dem
# Partikel duerfen ein paar Woerter stehen (kein Satzzeichen, keine Negation).
_RUECKRUF_WUNSCH_RE = re.compile(
    r"\br(?:ü|ue)ckruf\w*|\bzur(?:ü|ue)ckrufen\b|\bzur(?:ü|ue)ck\s*rufen\b"
    r"|\bruf(?:en|t)?\s+(?:sie\s+)?(?:mich|uns)(?:\s+(?!nicht\b|kein\w*\b)[\wäöüÄÖÜß]+){0,5}?\s+(?:zur(?:ü|ue)ck|an)\b"
    r"|\bmeld(?:en|et)\s+sich\b|\bsich\s+(?:bei\s+(?:mir|uns)\s+)?meld(?:en|et)\b"
    r"|\bnotier\w*|\bnotiz\w*|\bausrichten\b|\bnachricht\b",
    re.I,
)

# Persoenlich klaeren = kein Rueckruf noetig ("Ich komme dann vorbei").
_PERSOENLICH_RE = re.compile(
    r"\b(?:komme|komm|gehe|schaue|schau)\b[^.!?]{0,30}\b(?:vorbei|pers(?:ö|oe)nlich|hin|rein)\b"
    r"|\bvor\s+ort\b|\bpers(?:ö|oe)nlich\b|\bin\s+der\s+praxis\s+kl(?:ä|ae)r\w*"
    r"|\bkl(?:ä|ae)re?\s+(?:ich\s+)?(?:das\s+)?(?:dann\s+)?(?:vor\s+ort|pers(?:ö|oe)nlich|in\s+der\s+praxis)",
    re.I,
)

# --- feste Saetze (werden ueber gehirn.feste_saetze vorgewaermt) ----------

ERKLAERUNG = (
    "Über Rechnungen darf ich als Telefonassistentin leider nicht sprechen — "
    "Rechnungsthemen klärt die Praxis nur persönlich vor Ort."
)
RUECKRUF_FRAGE = "Soll ich Ihnen dafür einen Rückruf einrichten?"
ERKLAERUNG_WIEDERHOLT = "Wie gesagt: Rechnungsthemen klärt die Praxis nur persönlich."
RUECKRUF_FRAGE_WIEDERHOLT = "Soll ich doch einen Rückruf einrichten?"
RUECKRUF_UNKLAR = "Ein kurzes Ja oder Nein genügt: Soll ich einen Rückruf zur Rechnung einrichten?"
ABGELEHNT = "Alles klar — dann klären Sie das am besten direkt in der Praxis."
ABGELEHNT_KURZ = "Alles klar."
NAME_FRAGE = "Gerne. Für den Rückruf: Wie ist Ihr Name?"
NUMMER_FRAGE = "Danke. Und unter welcher Nummer erreicht die Praxis Sie am besten?"
# Nummer wie W-RUECKRUF-NUMMER: Readback (gehirn.readback_text) -> Ja -> fest.
NUMMER_NOCHMAL = ("Entschuldigung. Dann sagen Sie mir die Nummer bitte noch einmal — "
                  "gern in kleinen Gruppen.")
NUMMER_KEINE_LEITUNG = ("In der Leitung wird mir leider keine Nummer angezeigt. "
                        "Unter welcher Rufnummer erreicht die Praxis Sie?")
NUMMER_UNSICHER = ("Die Nummer bekomme ich am Telefon leider nicht sicher notiert. "
                   "Ihren Rückrufwunsch habe ich mit Ihrem Namen für die Praxis "
                   "festgehalten — am sichersten klären Sie die Rechnung direkt vor Ort.")
# Zwischenfrage/Unklares auf die Nummern-Frage — deterministisch, das Modell
# wuesste auch nicht, WANN die Praxis anruft (W-RUECKRUF-NUMMER).
NUMMER_ZWISCHENFRAGE = ("Das kann ich Ihnen leider nicht genau sagen — die Praxis meldet "
                        "sich, sobald sie Ihren Wunsch sieht. Dafür bräuchte sie noch Ihre "
                        "Nummer: Unter welcher Rufnummer erreicht sie Sie am besten?")
NUMMER_ERINNERUNG = ("Für den Rückruf bräuchte die Praxis noch eine Nummer — "
                     "unter welcher Rufnummer erreicht sie Sie am besten?")
NOTIERT = "Alles notiert — die Praxis meldet sich wegen der Rechnung bei Ihnen."
SONST_NOCH = "Kann ich sonst noch etwas für Sie tun?"
SONST_NOCH_JA = "Gerne — was kann ich noch für Sie tun?"
SONST_NOCH_NEIN = "Sehr gerne. Dann wünsche ich Ihnen einen schönen Tag — auf Wiederhören!"
WACHE_ERSATZ = ERKLAERUNG

SAETZE = (
    ERKLAERUNG, RUECKRUF_FRAGE, ERKLAERUNG_WIEDERHOLT, RUECKRUF_FRAGE_WIEDERHOLT,
    RUECKRUF_UNKLAR, ABGELEHNT, ABGELEHNT_KURZ, NAME_FRAGE, NUMMER_FRAGE,
    NUMMER_NOCHMAL, NUMMER_KEINE_LEITUNG, NUMMER_UNSICHER, NUMMER_ZWISCHENFRAGE,
    NUMMER_ERINNERUNG, NOTIERT, SONST_NOCH, SONST_NOCH_JA, SONST_NOCH_NEIN,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def enabled() -> bool:
    """Notaus RECHNUNG=0 => Erkennung und Flow aus (Verhalten wie vor dem
    14.09.2026: Rechnungssaetze landen im Unklar-Pfad bzw. beim Modell)."""
    return (os.environ.get("RECHNUNG") or "1").strip().lower() not in {"0", "off", "false", "aus"}


def wache_modus() -> str:
    """LLM-Ausgangswache: off | shadow | enforce (Default enforce)."""
    v = (os.environ.get("RECHNUNG_WACHE") or "enforce").strip().lower()
    return v if v in {"off", "shadow", "enforce"} else "enforce"


def _arzt_verlangt(text: str, sit: dict | None) -> bool:
    """Namentlich verlangter Behandler + Sprech-/Verbinde-Verb: das bleibt
    Weiterleitung ("Ich möchte mit Doktor Petsas über die Rechnung sprechen").
    Lazy, damit dieses Modul bianca-frei bleibt."""
    if not isinstance(sit, dict):
        return False
    try:
        from bianca import weiterleiten
        return bool(weiterleiten.arzt_verlangt(text, sit.get("tenant") or {}))
    except Exception:
        return False


# Mitten im Diktat gehoert jedes Zeichen der Erfassung — dort wird kein
# Rechnungsthema eroeffnet, weder vom Fluss noch von der Intent-Schicht
# (ein Wechsel-Verdacht wuerde die Nummern-Frage raeumen und die Buchung
# parken). Namens-/Vornamen-Fragen stehen bewusst NICHT hier: dort ist ein
# Themenwechsel plausibel, und die Namens-Ernte hat ihre eigenen Wachen.
_DIKTAT_FRAGEN = {"telefon", "telefon_check", "telefon_alt", "buchstabieren", "nachname_korr"}


def diktat_laeuft(sit: dict | None) -> bool:
    """Nummer/Buchstabieren gerade in Arbeit (offene Diktat-Frage oder ein
    angefangenes Fragment)?"""
    if not isinstance(sit, dict):
        return False
    s = sit.get("sammler")
    if not isinstance(s, dict):
        return False
    if _s(s.get("frage")) in _DIKTAT_FRAGEN:
        return True
    return bool(s.get("telefonTeil") or s.get("buchstabenTeil") or s.get("vornameTeil"))


def rechnungswort(text: str) -> bool:
    """Traegt der Satz HARTES Rechnungs-Vokabular (Rechnung, Mahnung,
    Buchhaltung, Honorar ...)? Fuer die Ausgangswache — bewusst NUR die
    harten Woerter: Preise darf das Modell nennen (PZR "ungefaehr 120 Euro",
    Bleaching 350 Euro sind Chef-Ansagen, W-PZR-KASSEN/W-BLEACHING); ein
    Satz mit "kostet"/"Euro" ist keine Rechnungs-Behauptung."""
    t = _s(text)
    return bool(t and (_HART_RE.search(t) or _ROLLE_RE.search(t)))


def erkannt(text: str, sit: dict | None = None, *, im_diktat: bool = False) -> bool:
    """Ist der Satz ein Rechnungsthema (Reklamation, Frage zur Rechnung/
    Mahnung/Zahlung, Buchhaltung)? Deterministisch, 0 ms.

    Kein Treffer bei laufendem Diktat (Nummer/Buchstabieren) — ausser der
    Aufrufer fuehrt das Diktat selbst (`im_diktat=True`, Rechnungs-Rueckruf):
    „Rechnungshofer" ist dann ein Nachname, keine Reklamation, und ein
    Wechsel-Verdacht duerfte die Nummern-Frage nicht raeumen."""
    t = _s(text)
    if not t or not enabled():
        return False
    if not im_diktat and diktat_laeuft(sit):
        return False
    if _NICHT_THEMA_RE.search(t):
        return False
    termin = bool(_TERMIN_RE.search(t))
    hart = bool(_HART_RE.search(t)) or (bool(_ROLLE_RE.search(t)) and not termin)
    if not hart:
        if not _WEICH_RE.search(t) or not _BESCHWERDE_RE.search(t):
            return False
        if termin or _KASSEN_KONTEXT_RE.search(t):
            return False
    if _arzt_verlangt(t, sit):
        return False
    return True


def rueckruf_gewuenscht(text: str) -> bool:
    """Verlangt der Satz selbst schon den Rueckruf/die Notiz?"""
    return bool(_RUECKRUF_WUNSCH_RE.search(_s(text)))


def persoenlich_klaeren(text: str) -> bool:
    """'Ich komme dann vorbei' / 'kläre ich vor Ort' = kein Rueckruf."""
    return bool(_PERSOENLICH_RE.search(_s(text)))


# --- Wache am LLM-Ausgang ----------------------------------------------------

_SATZ_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
# Ein Rechnungs-Satz darf stehen bleiben, wenn er auf die Praxis VERWEIST
# (persoenlich, vor Ort, Rueckruf, Notiz) oder die EIGENE Grenze nennt
# ("darf ich nicht", "kann ich keine Auskunft geben") — das ist genau die
# gewuenschte Aussage. Ein blosses "nicht" reicht NICHT: "Die Rechnung ist
# noch nicht bezahlt" ist eine erfundene Zahlungsstand-Behauptung.
_VERWEIS_RE = re.compile(
    r"pers(?:ö|oe)nlich|vor\s+ort|in\s+der\s+praxis|direkt\s+(?:in|mit|bei)\s+der\s+praxis"
    r"|r(?:ü|ue)ckruf\w*|zur(?:ü|ue)ckrufen|meldet\s+sich|notier\w*|notiz|ausrichten"
    r"|weitergeben|praxisteam|die\s+praxis\s+(?:kl(?:ä|ae)rt|pr(?:ü|ue)ft|schaut|meldet|entscheidet)",
    re.I,
)
_GRENZE_RE = re.compile(
    r"\b(?:darf|kann|k(?:ö|oe)nnte)\s+ich\b[^.!?]*\b(?:nicht|leider|keine?)\b"
    r"|\bich\s+(?:darf|kann|k(?:ö|oe)nnte)\b[^.!?]*\b(?:nicht|leider|keine?)\b"
    r"|\bnicht\s+(?:zust(?:ä|ae)ndig|befugt|autorisiert|berechtigt|erlaubt)\b"
    r"|\bkeine\s+(?:auskunft|einsicht|befugnis|berechtigung)\b"
    r"|\b(?:nicht|nichts)\s+am\s+telefon\b|\bam\s+telefon\s+(?:leider\s+)?(?:nicht|nichts)\b",
    re.I,
)


def satz_unbelegt(satz: str) -> bool:
    """Rechnungs-Satz OHNE Verweis auf die Praxis und OHNE eigene Grenze =
    Behauptung/Beratung des Modells (Betrag, Zahlungsstand, 'ich kuemmere
    mich', 'ich pruefe das') -> streichen."""
    st = _s(satz)
    if not st or not rechnungswort(st):
        return False
    return not (_VERWEIS_RE.search(st) or _GRENZE_RE.search(st))


def saeubern(text: str) -> tuple[str, list[str]]:
    """Unbelegte Rechnungs-Saetze aus einer Modell-Antwort streichen.
    Rueckgabe (Text, gestrichene Saetze). Bleibt nichts uebrig, kommt die
    feste Erklaerung — nie Stille."""
    t = _s(text)
    if not t or not rechnungswort(t):
        return text, []
    behalten: list[str] = []
    weg: list[str] = []
    for satz in _SATZ_SPLIT_RE.split(t):
        st = _s(satz)
        if not st:
            continue
        if satz_unbelegt(st):
            weg.append(st)
            continue
        behalten.append(st)
    if not weg:
        return text, []
    neu = " ".join(behalten).strip()
    return (neu or WACHE_ERSATZ), weg


# --- Report ------------------------------------------------------------------

def zusammenfassung_zeile(sit: dict | None) -> str:
    """Eine Zeile fuer den Gedaechtnis-Report (kern/gedaechtnis.zusammenfassung):
    die Praxis soll sehen, dass ein Rechnungsthema angesprochen wurde — auch
    wenn KEIN Rueckruf gewuenscht war (dann steht sonst nichts im Report).
    Den Rueckruf selbst traegt die Rueckruf-Notiz (praxisNotiz) wie gehabt."""
    if not isinstance(sit, dict):
        return ""
    st = sit.get("rechnungStand")
    if not isinstance(st, dict):
        return ""
    status = _s(st.get("status"))
    was = _s(st.get("was"))
    was = f" („{was[:80]}“)" if was else ""
    if status == "notiert":
        return f"Rechnungsthema angesprochen{was} — Rückruf dazu notiert"
    if status == "persoenlich":
        return f"Rechnungsthema angesprochen{was} — Anrufer klärt es persönlich in der Praxis"
    if status == "abgelehnt":
        return f"Rechnungsthema angesprochen{was} — auf persönliche Klärung verwiesen, kein Rückruf gewünscht"
    if status == "rueckruf":
        return f"Rechnungsthema angesprochen{was} — Rückruf gewünscht, Kontaktdaten blieben unvollständig"
    if status == "offen":
        return f"Rechnungsthema angesprochen{was} — Rückruf-Frage blieb ohne Antwort"
    return ""
