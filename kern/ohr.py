"""Parakeet-Hotwords je Frage. Ersetzt die Liste, wo Behandlernamen schaden.

Beim Buchstabieren nur die DIN-Tafel, beim Nummern-Diktat nur Ziffernwörter,
auf dem Readback Ja/Nein zuerst. Sonst Praxisnamen plus ein bestätigter
Kartei-Nachname und die häufigen Anliegen. Qwen darf Namen und Ziffern
nicht live überschreiben und keine Auftragswörter lernen.
"""

from __future__ import annotations

import os
import re

_NAMEN = {
    "name", "nachname", "vorname", "buchstabieren",
    "nachname_check", "vorname_check", "aenderung", "nachname_korr",
}
_TELEFON = {"telefon"}
_CHECK = {"telefon_check", "sms_empfaenger", "telefon_alt"}
_ZEIT = {"wunsch", "slotwahl"}
_ZIFFER = (
    "null", "eins", "zwei", "zwo", "drei", "vier", "fünf", "fuenf",
    "sechs", "sieben", "acht", "neun",
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "doppel", "hundert", "fertig",
)
_JA_NEIN = (
    "ja", "nein", "nee", "jawohl", "genau", "richtig", "stimmt",
    "korrekt", "passt", "falsch",
)
_NUR_NEUN_RE = re.compile(r"^\W*(?:neun|nine)\W*$", re.I)
_KLAR_RE = re.compile(r"mitarbeiterverb\w*", re.I)
_JOB = {
    "termin", "termine", "absage", "absagen", "verschieben", "buchen",
    "kontrolle", "vorsorge", "schmerzen", "rezept", "überweisung",
    "ueberweisung", "rückruf", "rueckruf", "anmeldung", "rezeption",
    "privat", "gesetzlich", "versichert", "versicherung", "muttermal",
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag",
    "vormittag", "nachmittag", "mittags",
}
_ERWARTET = {
    "schonmal": {"ja", "nein", "nee", "erste", "erstes", "neu", "nie"},
    "versicherung": {"privat", "gesetzlich", "versichert", "kasse"},
    "versicherung_check": {"ja", "nein", "nee", "privat", "gesetzlich"},
    "telefon_check": {"ja", "nein", "nee", "richtig", "falsch", "stimmt"},
    "sms_empfaenger": {"ja", "nein", "nee"},
    "anrufer_check": {"ja", "nein", "nee"},
    "fuer_wen_check": {"ja", "nein", "nee"},
    "slotwahl": {"erste", "zweite", "dritte", "früher", "frueher", "später", "spaeter"},
    "bestaetigung": {"ja", "nein", "nee", "richtig", "stimmt"},
}


def _sammler(sit: dict) -> dict:
    s = sit.get("sammler") if isinstance(sit, dict) else None
    return s if isinstance(s, dict) else {}


def check_ist_nein(text: str) -> bool:
    """Nacktes 'neun'/'nine' auf dem Nummern-Readback ist ein verhörtes Nein."""
    return bool(_NUR_NEUN_RE.match(str(text or "").strip()))


def klartext(text: str) -> str:
    """Ein bekannter Hörfehler der Anliegen-Liste, sonst der Satz selbst."""
    return _KLAR_RE.sub("Mitarbeitern", str(text or ""))


def _namen_liste(sit: dict) -> list[str]:
    try:
        from bianca import buchstaben
        namen = list(buchstaben.stt_hotwords())
    except Exception:
        namen = []
    extra = _bestaetigter_nachname(sit)
    if extra and extra not in namen:
        namen.append(extra)
    return namen


def _ziffer_liste(*, check: bool) -> list[str]:
    ziffern = [w for w in _ZIFFER if not (check and w == "nine")]
    if check:
        return list(_JA_NEIN) + ziffern
    return ziffern + ["nine"]


def _jobwort(wort: str) -> bool:
    return str(wort or "").casefold() in _JOB


def keywords(sit: dict, basis: list[str] | None = None) -> list[str]:
    """Hotword-Liste für diesen Zug. Name und Nummer ersetzen die Basis."""
    sit = sit if isinstance(sit, dict) else {}
    s = _sammler(sit)
    frage = str(s.get("frage") or "")
    if frage in _NAMEN or s.get("buchstabenTeil") or s.get("vornameTeil"):
        return _namen_liste(sit)
    if frage in _CHECK:
        return _ziffer_liste(check=True)
    if frage in _TELEFON or s.get("telefonTeil"):
        return _ziffer_liste(check=False)
    out: list[str] = []
    for wort in basis or []:
        if wort and wort not in out and not _jobwort(wort):
            out.append(wort)
    if frage in _ZEIT:
        try:
            from kern.slots import zeit_stt_hotwords
            for wort in zeit_stt_hotwords():
                if wort not in out:
                    out.append(wort)
        except Exception:
            pass
    from kern.anliegen_hoeren import HOTWORDS
    for wort in HOTWORDS:
        if wort not in out:
            out.append(wort)
    extra = _bestaetigter_nachname(sit)
    if extra and extra not in out:
        out.append(extra)
    return out


def anhaengen(liste: list[str], sit: dict) -> None:
    """Ersetzt den Inhalt durch die fragen-scharfe Liste.

    Der alte Name bleibt, damit Vorab-Ohr und Zug dieselbe Stelle rufen.
    """
    neu = keywords(sit, liste)
    liste[:] = neu


def _bestaetigter_nachname(sit: dict) -> str:
    """Genau ein Kartei-Nachname nach dem Identitäts-Ja. Nie bei Drittterminen."""
    s = _sammler(sit)
    if s.get("fuerWen"):
        return ""
    if str(s.get("anruferCheck") or "") != "ja":
        return ""
    anrufer = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
    teile = [t for t in str(anrufer.get("nachname") or "").split() if t]
    if len(teile) != 1 or len(teile[0]) < 4:
        return ""
    return teile[0]


def _woerter(text: str) -> set[str]:
    return {w.casefold() for w in re.findall(r"[^\W\d_]+", str(text or ""), flags=re.UNICODE)}


def qwen_live_sperre(sit: dict, lokal: str) -> str:
    """Leer = Qwen darf diesen Zug live übernehmen. Sonst der Sperrgrund."""
    flag = os.environ.get("QWEN_LIVE_SPERRE", "1").strip().lower()
    if flag in {"0", "off", "aus", "false"}:
        return ""
    s = _sammler(sit if isinstance(sit, dict) else {})
    frage = str(s.get("frage") or "")
    if s.get("buchstabenTeil") or s.get("vornameTeil") or frage in _NAMEN:
        return f"namensfrage:{frage or 'diktat'}"
    if s.get("telefonTeil") or frage in _TELEFON or frage in _CHECK:
        return f"diktat:{frage or 'telefon'}"
    erwartet = _ERWARTET.get(frage)
    if erwartet:
        treffer = sorted(_woerter(lokal) & erwartet)
        if treffer:
            return f"erwartet:{frage}:{treffer[0]}"
    return ""


def lernen_sperren(info: dict, sit: dict) -> dict:
    """Namens- und Ziffernzüge sind keine Lernquelle für das Zweit-Ohr."""
    grund = qwen_live_sperre(sit, str((info or {}).get("parakeet") or ""))
    if not grund:
        return info
    neu = dict(info or {})
    neu["authoritative"] = False
    neu["reason"] = f"live_gesperrt:{grund}"
    return neu


def jobwoerter_vergessen(sit: dict) -> None:
    """Auftrags-, Antwort- und Zeitwörter wieder aus dem gelernten Wörterbuch."""
    if not isinstance(sit, dict):
        return
    woerter = sit.get("qwenWoerter")
    if isinstance(woerter, dict):
        weg = [
            k for k, v in woerter.items()
            if _jobwort(k) or _jobwort(v) or any(_jobwort(t) for t in str(k).split())
            or any(_jobwort(t) for t in str(v).split())
        ]
        quelle = sit.get("qwenWoerterZug")
        for k in weg:
            woerter.pop(k, None)
            if isinstance(quelle, dict):
                quelle.pop(k, None)
    hot = sit.get("qwenHotwords")
    if isinstance(hot, list):
        sit["qwenHotwords"] = [w for w in hot if not _jobwort(w)]
