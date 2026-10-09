"""W-ZWEI-MERKMALE (08.10.2026): gelesen oder geschrieben wird in der
Terminverwaltung nur, wenn die Zielakte ZWEI unabhaengige Identitaets-Merkmale
trifft. Das ersetzt die frueheren harten Einzel-Grenzen (eine bestaetigte
patientId/Rufnummer allein, ein 60-Prozent-Name allein).

Rein, ohne Netz, ohne Bianca-Import (vermeidet Zyklen). Die Merkmale:

- ``telefon``       bestaetigte Rufnummer des Anrufers == Nummer der Akte
- ``geburtsdatum``  genanntes Geburtsdatum == Geburtsdatum der Akte
- ``name``          starker Name: voller Name >= 0,85 ODER gleicher Nachname
                    plus Vorname >= 0,80
- ``zeit``          vom Anrufer GENANNTER Termintag bzw. GENANNTE Uhrzeit
                    trifft den Kandidaten

``reicht(set)`` ist True ab zwei Merkmalen. Notaus ``ZWEI_MERKMALE=0`` stellt
die alte harte Grenze byte-identisch wieder her (die Aufrufer fragen
``aktiv()`` ab).
"""

from __future__ import annotations

import os
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any


def aktiv() -> bool:
    return (os.getenv("ZWEI_MERKMALE", "1") or "1").strip().lower() not in {
        "0", "false", "off", "no", "nein",
    }


def _s(v: Any) -> str:
    return str(v or "").strip()


# Zeit-/Termin-Paraphrasen zaehlen nie als Namensteil (Spiegel von
# verwalten._VERW_NAME_STOP — hier lokal, damit das Modul rein bleibt).
_STOP = {
    "am", "an", "bei", "beim", "der", "den", "die", "einen", "einem",
    "gegen", "im", "ist", "mein", "meine", "meinen", "termin", "termine",
    "uhr", "um", "vom", "war", "wäre", "waere",
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag",
    "sonntag", "heute", "morgen", "übermorgen", "uebermorgen",
    "januar", "februar", "märz", "maerz", "april", "mai", "juni", "juli",
    "august", "september", "oktober", "november", "dezember",
}


def _norm(v: Any, *, zeitwoerter: bool = True) -> str:
    roh = unicodedata.normalize("NFKD", _s(v).casefold())
    roh = "".join(c for c in roh if not unicodedata.combining(c))
    toks = [
        t for t in re.sub(r"[^a-z0-9ß]+", " ", roh).split()
        if (not zeitwoerter or t not in _STOP) and not t.isdigit()
    ]
    return "".join(toks).replace("ß", "ss")


def _tel(v: Any) -> str:
    d = "".join(c for c in _s(v) if c.isdigit())
    return d.removeprefix("00").removeprefix("49").lstrip("0")


def _kandidat_name(k: dict) -> tuple[str, str]:
    """(Vorname, Nachname) — egal ob Termin-Snapshot oder Akten-Datensatz."""
    vor = _s(k.get("patientFirstName") or k.get("firstName"))
    nach = _s(k.get("patientLastName") or k.get("lastName"))
    if not (vor or nach):
        voll = _s(k.get("patientName"))
        if voll:
            teile = voll.split()
            nach = teile[-1]
            vor = " ".join(teile[:-1])
    return vor, nach


def _kandidat_phone(k: dict) -> str:
    for key in ("patientPhone", "mobilePhoneNumber", "phone",
                "patientMobile", "mobile"):
        d = _tel(k.get(key))
        if d:
            return d
    return ""


def _kandidat_geburt(k: dict) -> str:
    return _s(k.get("patientBirthDate") or k.get("birthDate"))[:10]


def _kandidat_iso(k: dict) -> str:
    return _s(k.get("iso") or k.get("startIso") or k.get("start")).replace(
        " ", "T")


def starker_name(vor_s: Any, nach_s: Any, vor_k: Any, nach_k: Any) -> bool:
    """Voller Name >= 0,85 ODER gleicher Nachname plus Vorname >= 0,80.

    Nur der Nachname genannt (kein Vorname) ist NIE ein starker Name —
    bei gleichem Nachnamen mit anderem Vornamen (Familie) muss erst der
    Vorname (plus Geburtsdatum) erfragt werden.
    """
    nn_s, nn_k = _norm(nach_s, zeitwoerter=False), _norm(nach_k, zeitwoerter=False)
    if not nn_s or not nn_k:
        return False
    vn_s, vn_k = _norm(vor_s, zeitwoerter=False), _norm(vor_k, zeitwoerter=False)
    if not vn_s or not vn_k:
        return False
    voll = SequenceMatcher(None, vn_s + nn_s, vn_k + nn_k).ratio()
    if voll >= 0.85:
        return True
    if nn_s == nn_k and SequenceMatcher(None, vn_s, vn_k).ratio() >= 0.80:
        return True
    return False


def bestaetigte_nummer(sit: dict) -> str:
    """Nur eine SICHER dem Anrufer zugeordnete Rufnummer — nie die bloss
    uebermittelte, solange die Identitaet nicht bestaetigt ist, und nie die
    Kontaktnummer eines Dritttermins."""
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if s.get("fuerWen") or s.get("anruferCheck") == "nein":
        return ""
    an = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
    # Eine Ziffer fuer Ziffer rueckbestaetigte, gesprochene Nummer zaehlt.
    if s.get("telefonOk"):
        d = _tel(s.get("telefon"))
        if d:
            return d
    # Akten-/Leitungsnummer nur bei bestaetigter Identitaet.
    if s.get("anruferCheck") == "ja" or s.get("bekannt"):
        for roh in (s.get("aktePhone"), s.get("telefonBekannt"),
                    an.get("telefon"), sit.get("callerPhone")):
            d = _tel(roh)
            if d:
                return d
    return ""


def _zeit_trifft(sit: dict, k: dict) -> bool:
    """Der vom Anrufer GENANNTE Tag bzw. die genannte Uhrzeit trifft den
    Kandidaten. Nur was der Anrufer selbst nannte (verwHinweis), nie ein
    stillschweigend uebernommenes Datum."""
    w = sit.get("verwHinweis") if isinstance(sit.get("verwHinweis"), dict) else {}
    iso = _kandidat_iso(k)
    datum = _s(k.get("date")) or iso[:10]
    getroffen = False
    tag = _s(w.get("date"))[:10]
    if tag:
        if not datum or datum != tag:
            return False
        getroffen = True
    if len(iso) >= 16 and (iso[11:13].isdigit() and iso[14:16].isdigit()):
        minuten = int(iso[11:13]) * 60 + int(iso[14:16])
        if w.get("minuteOfDay") is not None:
            if abs(minuten - int(w["minuteOfDay"])) > 20:
                return False
            getroffen = True
        elif w.get("hour") is not None:
            if abs(minuten - int(w["hour"]) * 60) > 60:
                return False
            getroffen = True
    elif w.get("minuteOfDay") is not None or w.get("hour") is not None:
        # Uhrzeit genannt, aber der Kandidat traegt keine -> nicht belegt.
        if not tag:
            return False
    return getroffen


def merkmale(sit: dict, kandidat: dict) -> set[str]:
    """Die unabhaengigen Identitaets-Merkmale, die ``kandidat`` trifft."""
    if not isinstance(sit, dict) or not isinstance(kandidat, dict):
        return set()
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    out: set[str] = set()

    conf = bestaetigte_nummer(sit)
    if conf and conf == _kandidat_phone(kandidat):
        out.add("telefon")

    geb = _s(s.get("geburtsdatum") or s.get("birthDate"))[:10]
    kg = _kandidat_geburt(kandidat)
    if geb and kg and geb == kg:
        out.add("geburtsdatum")

    vor_k, nach_k = _kandidat_name(kandidat)
    if starker_name(s.get("vorname"), s.get("nachname"), vor_k, nach_k):
        out.add("name")

    if _zeit_trifft(sit, kandidat):
        out.add("zeit")

    return out


def reicht(m: set[str]) -> bool:
    """Zwei unabhaengige Merkmale genuegen fuer Lesen/Schreiben."""
    return len(m) >= 2
