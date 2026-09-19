"""Meta-Bitten des Anrufers im LIVE-Pfad (W-META-LIVE 19.09.2026).

Chef 19.09.2026: "alles fertig machen nacheinander und verfickt nochmal
endlich live schalten damit ich endlich testen kann." Gemeint sind die drei
Bitten, die im Dialogkern schon fertig sind, am Telefon aber noch ins Leere
liefen — Stille ist als Kern-Ereignis seit dem 29.08.2026 live
(``kern/stille.py``):

  ``wiederholen``  "Wie bitte?", "Können Sie das nochmal sagen?"
  ``abbrechen``    "Vergessen Sie's", "Hat sich erledigt"
  ``auslassen``    "Das möchte ich nicht sagen", "Muss das sein?"

**Erkennung wird NICHT verdoppelt:** sie kommt aus
``bianca/controller/meta.py`` (deterministisch, 0 ms, mit allen Gegenproben).
Hier steht nur die WIRKUNG im Live-Zustand (Sammler, Hirn, Sitzung) — der Kern
arbeitet dafür auf seinem eigenen ``State``. Die Wortlaute sind bewusst
dieselben wie im Renderer des Kerns, damit Studio-Probe und Telefon gleich
klingen.

Was hier NIE passiert (das sind die teuren Fehler):

1. **Kein Schreibweg.** Kein Werkzeug, kein Kalender, keine Notiz. Ein
   Abbruch ist ein ZURÜCKZIEHEN — er darf keine Rückrufbitte erzeugen.
2. **Nichts im Diktat.** Läuft ein Nummern- oder Buchstabier-Diktat, gehört
   jedes Zeichen der Erfassung ("nochmal die Sieben" ist eine Korrektur,
   keine Bitte um Wiederholung). Der Aufrufer prüft das mit
   ``agent._diktat_offen``.
3. **Vor einer Schreibaktion nur harte Formeln.** Auf ein Slot-Angebot, eine
   Rücklese oder eine destruktive Bestätigung heißt "möchte ich doch nicht"
   meist "diesen Termin nicht" — dort gilt ``streng=True`` (s. meta.deute).
4. **Ein geschriebener Termin wird nie stillschweigend zurückgenommen.**
   Es gibt kein Werkzeug "Buchung ungeschehen machen": Bianca sagt ehrlich,
   was steht, und nennt den Weg (absagen).

Notaus: ``META_LIVE=0`` => byte-identisches Verhalten wie vor dem 19.09.2026.
"""

from __future__ import annotations

import os
from typing import Any

from bianca import gehirn
from bianca.controller import meta
from kern import spur, wiederholung

# Wie oft dieselbe Bitte erfüllt wird, bevor Bianca ehrlich wird — gleicher
# Deckel wie im Kern (controller/reducer._WIEDERHOL_DECKEL).
DECKEL = 3
# Einleitungen, wortgleich mit controller/renderer._WIEDERHOLT: nie zweimal
# dieselbe, damit die Wiederholung nicht wie eine Platte klingt.
_VORSATZ: tuple[str, ...] = (
    "Natürlich, gerne noch einmal: ",
    "Ich sage es noch einmal: ",
    "Gerne — in anderen Worten: ",
)
# So viele Assistenten-Sätze werden nach einer wiederholbaren Ansage durchsucht.
_FENSTER = 6
# Presence-/Stups-Sätze sind keine Vorlage: "Sind Sie noch dran?" noch einmal
# zu sagen beantwortet keine Bitte um Wiederholung.
_KEINE_VORLAGE = (
    "sind sie noch dran",
    "ich bin noch da",
)

# Offene Fragen, hinter denen ein Schreibweg bzw. eine Auswahl steht: dort
# zaehlt fuer den Abbruch nur eine harte Formel (streng=True).
_SCHREIBNAH_FRAGEN = frozenset({
    "bestaetigung", "slotwahl", "telefon_check", "termin_ok", "termin_aendern",
    "nachname_check", "vorname_check", "rechnung_rueckruf",
})
_SCHREIBNAH_PHASEN = frozenset({
    "bestaetigen", "wahl", "mehrfach_bestaetigen", "verschieb_angebot",
    "angebot",
})

# Was beim Abbruch im Sammler BLEIBT: wer schon seinen Namen genannt hat, will
# ihn nach "vergessen Sie's" nicht erneut buchstabieren. Alles andere ist
# Anliegen (Grund, Motiv, Wunsch, Slot, Behandler) und faellt weg — gehirn.
# sammler() setzt die Startwerte danach wieder ein.
_BEHALTEN = (
    "vorname", "nachname", "name", "buchstabiert", "bekannt", "patientId",
    "geschlecht", "geschlechtQuelle", "vornameQuelle", "warSchonMal",
    "telefon", "telefonOk", "telefonAkte", "telefonBekannt",
    "kontaktName", "kontaktTelefon", "anruferCheck", "versicherung",
)

# Pflicht-Saetze wortgleich mit controller/renderer._PFLICHT — am Telefon ist
# JEDES Buchungsfeld Pflicht (die Standard-Policy fuehrt kein optionales Feld).
_PFLICHT: dict[str, str] = {
    "name": "Ohne den Namen finde ich die Akte leider nicht — geraten wird hier nichts. ",
    "nachname": "Ohne den Namen finde ich die Akte leider nicht — geraten wird hier nichts. ",
    "vorname": "Ohne den Namen finde ich die Akte leider nicht — geraten wird hier nichts. ",
    "buchstabieren": "Ohne den Namen finde ich die Akte leider nicht — geraten wird hier nichts. ",
    "telefon": "Ohne Rufnummer kann die Praxis Sie nicht erreichen. ",
    "sms_empfaenger": "Ohne Rufnummer kann die Praxis Sie nicht erreichen. ",
    "slotwahl": "Einen Termin kann ich nur eintragen, wenn Sie einen auswählen. ",
}
_PFLICHT_ALLGEMEIN = "Diese Angabe brauche ich leider, sonst kann ich nichts eintragen. "

# Der Abschluss-Satz ist wortgleich mit flow._SONST_NOCH: er wird als offene
# Frage registriert und von _abgeben_sonst_noch beantwortet.
SONST_NOCH = "Kann ich sonst noch etwas für Sie tun?"
ABBRUCH = f"Alles klar, dann lassen wir das. {SONST_NOCH}"
ABBRUCH_LEER = "Kein Problem. Sagen Sie einfach, wenn ich etwas für Sie tun kann."
ABBRUCH_GEBUCHT = (
    "Der Termin ist allerdings schon eingetragen. Soll ich ihn wieder absagen?"
)
# Der Deckel ist erreicht: nicht noch einmal dasselbe, sondern ehrlich werden.
DECKEL_SATZ = (
    "Ich glaube, die Leitung ist gerade schlecht. "
    "Sie erreichen die Praxis zu den Sprechzeiten auch direkt."
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def an() -> bool:
    """Notaus ``META_LIVE=0``."""
    return _s(os.getenv("META_LIVE", "1")).lower() not in ("0", "off", "false", "nein")


def streng(sit: dict) -> bool:
    """Steht eine Auswahl, eine Ruecklese oder eine Bestaetigung offen?"""
    s = sit.get("sammler") or {}
    if _s(s.get("frage")) in _SCHREIBNAH_FRAGEN:
        return True
    if _s(s.get("phase")) in _SCHREIBNAH_PHASEN:
        return True
    return bool(sit.get("offered")) and not _s(s.get("frage"))


def _letzte_ansage(sit: dict, msgs: list[dict]) -> str:
    """Die letzte WIEDERHOLBARE Ansage — Presence/Stups/Begruessung uebersprungen.

    Die Begruessung ist bewusst keine Vorlage: sie noch einmal zu sprechen
    waere ein zweites Hallo mitten im Gespraech — genau das streicht die
    Regreeting-Wache hinterher, und der Zug bliebe stumm. Lag nur sie vor,
    gehoert der Satz dem normalen Weg (kurze Frage nach dem Anliegen).
    """
    gruss = _s(sit.get("begruessungText")).casefold()
    for satz in wiederholung.letzte_antworten(msgs, _FENSTER):
        klein = satz.casefold()
        if any(k in klein for k in _KEINE_VORLAGE):
            continue
        if gruss and _s(satz).casefold() == gruss:
            continue
        return satz
    return ""


def _gebucht(sit: dict) -> bool:
    """Wurde in DIESEM Anruf wirklich geschrieben (Tool-Ledger)?"""
    for w in sit.get("tools") or []:
        name = _s(w.get("name"))
        if name in ("book_slot", "masBookAppointment") and w.get("ok"):
            return True
    return bool(sit.get("lastBook"))


def _laeuft_etwas(sit: dict) -> bool:
    from kern import hirn as kern_hirn

    s = sit.get("sammler") or {}
    if _s(s.get("modus")) or _s(s.get("frage")) or _s(s.get("phase")):
        return True
    if sit.get("rueckrufNummer") or sit.get("offered"):
        return True
    try:
        return kern_hirn.aktiv(sit) is not None
    except Exception:
        return False


def _wiederholen(sit: dict, msgs: list[dict], offene: str) -> dict | None:
    vorlage = _letzte_ansage(sit, msgs) or offene
    if not vorlage:
        # Es gibt nichts zu wiederholen (erster Zug, nur die Begruessung lag
        # vor): der Satz gehoert dem normalen Unklar-Weg, der kurz und
        # mandantenscharf nach dem Anliegen fragt. Hier eine eigene Floskel zu
        # bauen hiess live, sie hinterher von der Regreeting-Wache streichen zu
        # lassen — der Zug blieb stumm (Blessing-Gegenprobe "Wie bitte?").
        spur.merken(sit, "meta-live", "wiederholen-ohne-vorlage")
        return None
    n = int(sit.get("metaWiederhol") or 0) + 1
    sit["metaWiederhol"] = n
    if n > DECKEL:
        spur.merken(sit, "meta-live", f"wiederholen-deckel:{n}")
        text = f"{DECKEL_SATZ} {offene}".strip() if offene else DECKEL_SATZ
        return {"text": text, "book": None, "_wiederholungErlaubt": True}
    spur.merken(sit, "meta-live", f"wiederholen:{n}")
    return {
        "text": _VORSATZ[(n - 1) % len(_VORSATZ)] + vorlage,
        "book": None,
        # Ausdrueckliche Bitte: der Entdoppler darf den Inhalt nicht streichen.
        "_wiederholungErlaubt": True,
    }


def _abbrechen(sit: dict) -> dict:
    from kern import hirn as kern_hirn

    sit.pop("metaWiederhol", None)
    if _gebucht(sit):
        # Kein Werkzeug macht eine Buchung ungeschehen: ehrlich sagen, was
        # steht. Der Zustand bleibt, damit "ja, absagen" den normalen Weg geht.
        spur.merken(sit, "meta-live", "abbrechen-nach-write")
        return {"text": ABBRUCH_GEBUCHT, "book": None,
                "_wiederholungErlaubt": True}
    if not _laeuft_etwas(sit):
        spur.merken(sit, "meta-live", "abbrechen-leer")
        return {"text": ABBRUCH_LEER, "book": None,
                "_wiederholungErlaubt": True}

    alt = dict(sit.get("sammler") or {})
    neu = {k: alt[k] for k in _BEHALTEN if k in alt}
    sit["sammler"] = neu
    gehirn.sammler(sit)  # Startwerte wieder einsetzen
    for k in ("offered", "slotVorrat", "vorratFuer", "gefundenKey", "flussFrage",
              "slotGesperrt", "verschiebRichtung", "upcoming", "past",
              "rueckrufNummer", "buchIntent", "verwAbschlussOffen"):
        sit.pop(k, None)
    try:
        if kern_hirn.aktiv(sit) is not None:
            kern_hirn.erledigt(sit, naechstes=False)
        kern_hirn.geparktes_zurueckholen(sit)
    except Exception:
        pass
    # Die Abschluss-Frage REGISTRIEREN: nur so beantwortet _abgeben_sonst_noch
    # den naechsten Zug deterministisch ("Nein" legt auf, "Ja" laedt ein).
    gehirn.sammler(sit)["frage"] = "sonst_noch"
    sit["flussFrage"] = SONST_NOCH
    sit["abgebenSonstNoch"] = True
    sit["sonstNochGefragt"] = True
    spur.merken(sit, "meta-live", "abbrechen")
    return {"text": ABBRUCH, "book": None, "_wiederholungErlaubt": True}


def _auslassen(sit: dict, offene: str) -> dict | None:
    fid = _s((sit.get("sammler") or {}).get("frage"))
    if not fid or not offene:
        # Keine Frage offen: es gibt nichts auszulassen — der normale Weg
        # (Talk/Fluss) soll den Satz sehen.
        return None
    spur.merken(sit, "meta-live", f"auslassen-pflicht:{fid}")
    return {
        "text": _PFLICHT.get(fid, _PFLICHT_ALLGEMEIN) + offene,
        "book": None,
        "_wiederholungErlaubt": True,
    }


def zug(sit: dict, text: str, msgs: list[dict], *, offene: str = "") -> dict | None:
    """Meta-Bitte beantworten, oder ``None`` (dann gehoert der Satz dem Fluss).

    ``offene`` = die offene Pflichtfrage als Satz (agent._offene_frage) — sie
    haengt hinter der Pflicht-Auskunft bzw. hinter dem Deckel-Satz, damit der
    Faden nicht reisst.
    """
    if not an():
        return None
    art = meta.deute(text, streng=streng(sit))
    if not art:
        # Ein inhaltlicher Zug beendet die Wiederhol-Serie: der Deckel soll
        # spaeter im Anruf nicht aus einer alten Serie heraus zuschlagen.
        sit.pop("metaWiederhol", None)
        return None
    if art == meta.WIEDERHOLEN:
        if streng(sit):
            # Ruecklese, Slot-Auswahl, destruktive Bestaetigung: dort hat der
            # Fluss seit Monaten seine EIGENE Reparatur (Nummer/Namen erneut
            # buchstabiert vorlesen, beim zweiten Mal die Schreibweise frisch
            # aufnehmen). Eine Kopie davon hier hiesse, diese Eskalation zu
            # verlieren — der Anrufer hoerte dieselbe Ruecklese endlos.
            spur.merken(sit, "meta-live", "wiederholen-fluss")
            return None
        return _wiederholen(sit, msgs, offene)
    if art == meta.ABBRECHEN:
        return _abbrechen(sit)
    if art == meta.AUSLASSEN:
        return _auslassen(sit, offene)
    return None


__all__ = ["an", "streng", "zug", "DECKEL"]
