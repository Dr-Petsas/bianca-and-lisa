"""Story-Bauer des Baukasten-Tests: Attribute -> Anruf-Drehbuch.

Eine Story ist ein dict aus Attributen (Stimme, Name, Anliegen, Grund,
Wunschtag, Slot-Verhandlung, Abschweifer ...). Der Runner (runner.py) fuehrt
sie gegen den echten Bianca-Dienst: nach jedem Zug liefert die Antwort die
offene Maschinen-Frage (frage/modus, seit W-BK-3) — `naechster_baustein`
mappt sie auf den passenden Katalog-Baustein (saetze.py). Pure Logik,
offline testbar; Audio und HTTP passieren ausschliesslich im Runner.
"""

from __future__ import annotations

import random
from typing import Any

from tests.baukasten import saetze

# Anliegen-Arten: was will der Anrufer?
TERMIN = "termin"
ABSAGEN = "absagen"
VERSCHIEBEN = "verschieben"
AUSKUNFT = "auskunft"
# Dokument-Anliegen (ohne Kalender): Katalog-Schluessel aus saetze.ANLIEGEN.
DOKU_ARTEN = tuple(saetze.ANLIEGEN)

ALLE_ANLIEGEN = (TERMIN, ABSAGEN, VERSCHIEBEN, AUSKUNFT) + DOKU_ARTEN

# An diesen offenen Fragen darf ein Abschweifer die Antwort verdraengen —
# Bianca muss damit umgehen und die Frage danach erneut stellen.
ABSCHWEIF_ANKER = ("schonmal", "grund", "wunsch", "telefon", "versicherung", "slotwahl")

# Behandler-Nachnamen des Test-Mandanten (tenants/meddent.json).
BEHANDLER = ("Petsas", "Nikolaou", "Patrikis")

MAX_SLOT_ZUEGE = 3  # Verhandlungs-Deckel: spaetestens das dritte Angebot wird genommen


# ------------------------------------------------------------------ Story-Bau

def automatik(nr: int, *, tag: str = "Mittwoch", seed: int | None = None) -> dict[str, Any]:
    """Eine zufaellige, aber reproduzierbare Buchungs-Story (Neupatient).

    seed=None nimmt die Story-Nummer — derselbe Aufruf baut immer dieselbe
    Story (Korrekturschleife: ein roter Fall laesst sich exakt wiederholen).
    """
    rnd = random.Random(nr * 7919 if seed is None else seed)
    stimme = rnd.choice(saetze.STIMMEN_M + saetze.STIMMEN_W)
    grund = rnd.choice(list(saetze.GRUENDE))
    themen = rnd.sample(list(saetze.ABSCHWEIFER), k=rnd.choice([0, 1, 1, 2]))
    anker = rnd.sample(ABSCHWEIF_ANKER, k=len(themen))
    story: dict[str, Any] = {
        "nr": nr,
        "id": f"s{nr:02d}-{stimme}-{grund}",
        "stimme": stimme,
        "vorname": saetze.VORNAMEN[stimme],
        "nachname": saetze.NACHNAMEN[nr % len(saetze.NACHNAMEN)],
        "anliegen": TERMIN,
        "grund": grund,
        "tag": tag,
        "schonmal": False,  # Neupatient: braucht keine bestehende Akte
        "behandler": rnd.choice(BEHANDLER + ("",)),  # "" = egal
        "versicherung": rnd.choice(["privat", "gesetzlich"]),
        "slotAnnahme": rnd.choice([1, 2, 2, 3]),
        "slotRichtung": rnd.choice(["frueher", "spaeter"]),
        "abschweifer": list(zip(anker, themen)),
        "zwischenfragePreis": rnd.random() < 0.25,
        "halbsatz": rnd.random() < 0.2,
        "readbackFehler": rnd.random() < 0.15,
        "pzr": rnd.random() < 0.5,
        "wannWeissNicht": False,
        "seed": nr * 7919 if seed is None else seed,
    }
    return story


def folge_story(basis: dict[str, Any], art: str, *, nr: int | None = None) -> dict[str, Any]:
    """Zweit-Anruf derselben Persona: absagen/verschieben/erfahren des eben
    gebuchten Termins (gleicher Name, gleiche Nummer, gleicher Zieltag)."""
    if art not in (ABSAGEN, VERSCHIEBEN, AUSKUNFT):
        raise ValueError(f"unbekannte Folge-Art: {art}")
    rnd = random.Random((basis.get("seed") or 0) + 13)
    story = dict(basis)
    story["nr"] = basis["nr"] if nr is None else nr
    story["id"] = f"s{story['nr']:02d}-{basis['stimme']}-{art}"
    story["anliegen"] = art
    story["schonmal"] = True  # die Buchung hat die Akte angelegt
    story["abschweifer"] = []
    story["zwischenfragePreis"] = False
    story["halbsatz"] = False
    story["readbackFehler"] = False
    story["wannWeissNicht"] = rnd.random() < 0.3
    story["folgeVon"] = basis.get("id") or ""
    return story


def doku_story(nr: int, art: str, *, seed: int | None = None) -> dict[str, Any]:
    """Dokument-Anliegen (Rezept, Ueberweisung, Rechnungskopie, Unterlagen)."""
    if art not in DOKU_ARTEN:
        raise ValueError(f"unbekanntes Doku-Anliegen: {art}")
    story = automatik(nr, seed=seed)
    story["id"] = f"s{nr:02d}-{story['stimme']}-{art}"
    story["anliegen"] = art
    story["abschweifer"] = story["abschweifer"][:1]
    story["zwischenfragePreis"] = False
    story["halbsatz"] = False
    return story


# --------------------------------------------------------------- Drehbuch-Lage

def lage_neu() -> dict[str, Any]:
    """Laufzustand des Runners zwischen den Zuegen."""
    return {
        "eroeffnet": False,
        "frage": "",
        "modus": "",
        "biancaText": "",
        "gebucht": False,
        "fertig": False,
        "slotZuege": 0,
        "gemacht": set(),   # einmalige Bausteine: Themen, "zwischenfrage", ...
        "zaehler": {},      # Varianten-Rotation je Baustein
    }


def lage_update(lage: dict, antwort: dict[str, Any]) -> None:
    """Nach jedem Bianca-Zug: offene Frage, Modus und Buchungsstand mitfuehren."""
    lage["frage"] = str(antwort.get("frage") or "")
    lage["modus"] = str(antwort.get("modus") or "")
    lage["biancaText"] = str(antwort.get("text") or "")
    book = antwort.get("book") or {}
    if isinstance(book, dict) and (book.get("booked") or book.get("cancelled") or book.get("moved")):
        lage["gebucht"] = True


def _wahl(story: dict, lage: dict, key: str, liste: list[str]) -> str:
    """Reproduzierbare Variante: Story-Seed + Rotationszaehler je Baustein."""
    z = lage["zaehler"].get(key, 0)
    lage["zaehler"][key] = z + 1
    rnd = random.Random((story.get("seed") or 0) * 31 + hash(key) % 997)
    start = rnd.randrange(len(liste))
    return liste[(start + z) % len(liste)]


def _eroeffnung(story: dict, lage: dict) -> dict[str, Any]:
    lage["eroeffnet"] = True
    frei = str(story.get("eroeffnungText") or "").strip()
    if frei:
        return {"text": frei, "baustein": "eroeffnung_frei"}
    art = story.get("anliegen") or TERMIN
    if art == TERMIN and story.get("halbsatz"):
        teil1, teil2 = saetze.HALBSATZ_PAARE[(story.get("seed") or 0) % len(saetze.HALBSATZ_PAARE)]
        return {"text": teil1, "baustein": "eroeffnung_halbsatz", "halbsatzRest": teil2}
    if art == TERMIN:
        return {"text": _wahl(story, lage, "eroeffnung", saetze.EROEFFNUNG_MACHEN), "baustein": "eroeffnung"}
    if art == ABSAGEN:
        return {"text": _wahl(story, lage, "eroeffnung", saetze.EROEFFNUNG_ABSAGEN), "baustein": "eroeffnung_absagen"}
    if art == VERSCHIEBEN:
        return {"text": _wahl(story, lage, "eroeffnung", saetze.EROEFFNUNG_VERSCHIEBEN), "baustein": "eroeffnung_verschieben"}
    if art == AUSKUNFT:
        return {"text": _wahl(story, lage, "eroeffnung", saetze.EROEFFNUNG_ERFAHREN), "baustein": "eroeffnung_erfahren"}
    return {"text": _wahl(story, lage, "eroeffnung", saetze.ANLIEGEN[art]), "baustein": f"eroeffnung_{art}"}


def _abschweifer(story: dict, lage: dict) -> dict[str, Any] | None:
    """Ist an der gerade offenen Frage ein Abschweifer geplant und noch offen?"""
    fid = lage["frage"]
    frei = str(story.get("abschweiferText") or "").strip()
    if frei and fid in ABSCHWEIF_ANKER and "abschweif:frei" not in lage["gemacht"]:
        lage["gemacht"].add("abschweif:frei")
        return {"text": frei, "baustein": "abschweifer_frei"}
    for anker, thema in story.get("abschweifer") or []:
        schluessel = f"abschweif:{thema}"
        if anker == fid and schluessel not in lage["gemacht"]:
            lage["gemacht"].add(schluessel)
            return {"text": _wahl(story, lage, schluessel, saetze.ABSCHWEIFER[thema]),
                    "baustein": f"abschweifer_{thema}"}
    return None


def _grund_text(story: dict, lage: dict) -> str:
    frei = str(story.get("grundText") or "").strip()
    if frei:
        return frei
    key = story.get("grund") or "kontrolle"
    if key not in saetze.GRUENDE:
        return str(key)
    varianten, _erwartet = saetze.GRUENDE[key]
    return _wahl(story, lage, "grund", varianten)


_FRAGE_LEER_MAX = 3  # Zuege ohne offene Frage, bevor der Anrufer sich verabschiedet


def naechster_baustein(story: dict, lage: dict) -> dict[str, Any]:
    """Der naechste Anrufer-Zug zur offenen Frage.

    Rueckgabe: {"text", "baustein", optional "halbsatzRest", "auflegen"}.
    Leerer Text + auflegen=True beendet den Anruf ohne weiteren Zug.
    """
    if not lage["eroeffnet"]:
        return _eroeffnung(story, lage)

    fid = lage["frage"]

    # Verabschiedet? Nach dem Abschied ist Schluss (Runner legt auf).
    if "abschied" in lage["gemacht"]:
        return {"text": "", "baustein": "", "auflegen": True}

    # Geplante Stoerungen: Abschweifer und Preis-Zwischenfrage verdraengen
    # die Antwort GENAU EINMAL — die Maschine muss die Frage erneut stellen.
    stoer = _abschweifer(story, lage)
    if stoer:
        return stoer
    if (story.get("zwischenfragePreis") and fid == "telefon"
            and "zwischenfrage" not in lage["gemacht"]):
        lage["gemacht"].add("zwischenfrage")
        return {"text": _wahl(story, lage, "zwischenfrage", saetze.ZWISCHENFRAGE_PREIS),
                "baustein": "zwischenfrage_preis"}

    if fid == "schonmal":
        liste = saetze.SCHONMAL_JA if story.get("schonmal") else saetze.SCHONMAL_NEIN
        return {"text": _wahl(story, lage, "schonmal", liste), "baustein": "schonmal"}
    if fid == "arzt":
        arzt = str(story.get("behandler") or "")
        if not arzt:
            return {"text": _wahl(story, lage, "arzt", saetze.ARZT_EGAL), "baustein": "arzt_egal"}
        nr = lage["zaehler"].get("arzt_m", 0)
        lage["zaehler"]["arzt_m"] = nr + 1
        return {"text": saetze.arzt_satz(arzt, (story.get("seed") or 0) + nr), "baustein": "arzt"}
    if fid == "name":
        nr = lage["zaehler"].get("name_m", 0)
        lage["zaehler"]["name_m"] = nr + 1
        return {"text": saetze.name_satz(story["vorname"], story["nachname"], (story.get("seed") or 0) + nr),
                "baustein": "name"}
    if fid == "vorname":
        return {"text": _wahl(story, lage, "vorname", saetze.VORNAME_NUR).format(vorname=story["vorname"]),
                "baustein": "vorname"}
    if fid == "nachname":
        return {"text": _wahl(story, lage, "nachname", saetze.NACHNAME_NUR).format(nachname=story["nachname"]),
                "baustein": "nachname"}
    if fid == "grund":
        return {"text": _grund_text(story, lage), "baustein": f"grund_{story.get('grund')}"}
    if fid == "wunsch":
        frei = str(story.get("wunschText") or "").strip()
        if frei:
            return {"text": frei, "baustein": "wunsch_frei"}
        nr = lage["zaehler"].get("wunsch_m", 0)
        lage["zaehler"]["wunsch_m"] = nr + 1
        return {"text": saetze.wunsch_satz(story["tag"], (story.get("seed") or 0) + nr), "baustein": "wunsch"}
    if fid == "buchstabieren":
        return {"text": saetze.buchstabier_satz(story["nachname"], story.get("seed") or 0),
                "baustein": "buchstabieren"}
    if fid == "telefon":
        return {"text": _wahl(story, lage, "telefon", saetze.TELEFON), "baustein": "telefon"}
    if fid == "telefon_check":
        if story.get("readbackFehler") and "readback_nein" not in lage["gemacht"]:
            lage["gemacht"].add("readback_nein")
            return {"text": _wahl(story, lage, "readback_nein", saetze.READBACK_NEIN),
                    "baustein": "readback_nein"}
        return {"text": _wahl(story, lage, "readback_ja", saetze.READBACK_JA), "baustein": "readback_ja"}
    if fid == "telefon_alt":
        return {"text": _wahl(story, lage, "telefon_alt", saetze.TELEFON_ALT_NEU), "baustein": "telefon_alt"}
    if fid == "versicherung":
        frei = str(story.get("versicherungText") or "").strip()
        if frei:
            return {"text": frei, "baustein": "versicherung_frei"}
        nr = lage["zaehler"].get("vers_m", 0)
        lage["zaehler"]["vers_m"] = nr + 1
        return {"text": saetze.versicherung_satz(story.get("versicherung") == "privat",
                                                 (story.get("seed") or 0) + nr),
                "baustein": "versicherung"}
    if fid == "versicherung_check":
        return {"text": _wahl(story, lage, "vers_gleich", saetze.VERSICHERUNG_GLEICH),
                "baustein": "versicherung_gleich"}
    if fid == "pzr":
        liste = saetze.PZR_JA if story.get("pzr") else saetze.PZR_NEIN
        return {"text": _wahl(story, lage, "pzr", liste), "baustein": "pzr"}
    if fid == "slotwahl":
        if "keinen freien termin" in (lage["biancaText"] or "").lower():
            # Leeres Angebot ("die Praxis meldet sich"): nichts zu waehlen,
            # nicht schieben — sauber abschliessen (Batch s09 29.08.2026).
            lage["gemacht"].add("nichts_mehr")
            return {"text": _wahl(story, lage, "nichts_mehr", saetze.NICHTS_MEHR),
                    "baustein": "nichts_mehr"}
        lage["slotZuege"] += 1
        if lage["slotZuege"] < min(int(story.get("slotAnnahme") or 1), MAX_SLOT_ZUEGE):
            liste = saetze.SLOT_FRUEHER if story.get("slotRichtung") == "frueher" else saetze.SLOT_SPAETER
            return {"text": _wahl(story, lage, "slot_schieben", liste), "baustein": "slot_schieben"}
        # Eine pauschale Annahme ("buchen Sie den bitte") ist bei einer
        # MEHRFACH-Liste zu Recht mehrdeutig — fragt Bianca "welcher?" oder
        # kam die Annahme schon, wird konkret der erste Vorschlag gewaehlt
        # (live 29.08.2026: Liste wurde erneut vorgelesen, Runner loopte).
        mehrfach = "welcher" in (lage["biancaText"] or "").lower()
        if "slot_angenommen" in lage["gemacht"] or mehrfach:
            return {"text": _wahl(story, lage, "terminwahl", saetze.TERMINWAHL_ERSTER),
                    "baustein": "terminwahl"}
        lage["gemacht"].add("slot_angenommen")
        frei = str(story.get("slotText") or "").strip()
        if frei:
            return {"text": frei, "baustein": "slot_frei"}
        return {"text": _wahl(story, lage, "slot_annahme", saetze.SLOT_ANNAHME), "baustein": "slot_annahme"}
    if fid == "bestaetigung":
        return {"text": _wahl(story, lage, "bestaetigung", saetze.BESTAETIGUNG_JA), "baustein": "bestaetigung"}
    if fid == "rueckblick":
        return {"text": _wahl(story, lage, "rueckblick", saetze.RUECKBLICK_GUT), "baustein": "rueckblick"}
    if fid == "wann":
        if story.get("wannWeissNicht"):
            return {"text": _wahl(story, lage, "wann_unklar", saetze.WANN_WEISS_NICHT), "baustein": "wann_unklar"}
        nr = lage["zaehler"].get("wann_m", 0)
        lage["zaehler"]["wann_m"] = nr + 1
        return {"text": saetze.wann_hinweis_satz(story["tag"], (story.get("seed") or 0) + nr),
                "baustein": "wann"}
    if fid == "behandlung":
        return {"text": _grund_text(story, lage), "baustein": "behandlung"}
    if fid == "neubuchung":
        return {"text": _wahl(story, lage, "neubuchung", saetze.NEUBUCHUNG_NEIN), "baustein": "neubuchung_nein"}
    if fid in ("absage_ok", "verschieb_ok"):
        return {"text": _wahl(story, lage, "verwalten_ja", saetze.VERWALTEN_JA), "baustein": "verwalten_ja"}
    if fid == "terminwahl":
        return {"text": _wahl(story, lage, "terminwahl", saetze.TERMINWAHL_ERSTER), "baustein": "terminwahl"}

    # Keine offene Maschinen-Frage: LLM-Zug oder Abschluss.
    text = (lage["biancaText"] or "").lower()
    if "sonst noch" in text or "noch etwas" in text or lage["gebucht"]:
        if "nichts_mehr" not in lage["gemacht"] and ("sonst noch" in text or "noch etwas" in text):
            lage["gemacht"].add("nichts_mehr")
            return {"text": _wahl(story, lage, "nichts_mehr", saetze.NICHTS_MEHR), "baustein": "nichts_mehr"}
        lage["gemacht"].add("abschied")
        return {"text": _wahl(story, lage, "abschied", saetze.ABSCHIED), "baustein": "abschied", "auflegen": True}
    # Heuristik fuer LLM-Zuege ohne Sammler-Frage (Doku-Anliegen u. ae.):
    if "name" in text and "?" in text:
        nr = lage["zaehler"].get("name_m", 0)
        lage["zaehler"]["name_m"] = nr + 1
        return {"text": saetze.name_satz(story["vorname"], story["nachname"], (story.get("seed") or 0) + nr),
                "baustein": "name"}
    if ("nummer" in text or "erreichen" in text) and "?" in text:
        return {"text": _wahl(story, lage, "telefon", saetze.TELEFON), "baustein": "telefon"}
    leer = lage["zaehler"].get("frage_leer", 0) + 1
    lage["zaehler"]["frage_leer"] = leer
    if "?" in text and leer <= _FRAGE_LEER_MAX:
        return {"text": _wahl(story, lage, "ja_generisch", ["Ja, gerne.", "Ja, das passt.", "Gerne, ja."]),
                "baustein": "ja_generisch"}
    lage["gemacht"].add("abschied")
    return {"text": _wahl(story, lage, "abschied", saetze.ABSCHIED), "baustein": "abschied", "auflegen": True}


def saetze_fuer_audio(story: dict) -> list[str]:
    """Alle Anrufer-Saetze, die dieser Story wahrscheinlich spricht —
    zum Vorwaermen (TTS) BEVOR der Anruf startet."""
    out: list[str] = []

    def add(t: Any) -> None:
        s = " ".join(str(t or "").split())
        if s and s not in out:
            out.append(s)

    for feld in ("eroeffnungText", "grundText", "wunschText",
                 "versicherungText", "slotText", "abschweiferText"):
        add(story.get(feld))

    lg = lage_neu()
    add(_eroeffnung(story, lg).get("text"))
    for fid in ("schonmal", "arzt", "name", "vorname", "nachname", "grund",
                "wunsch", "buchstabieren", "telefon", "telefon_check",
                "versicherung", "pzr", "bestaetigung", "wann", "behandlung"):
        lg = lage_neu()
        lg["eroeffnet"] = True
        lg["frage"] = fid
        try:
            add(naechster_baustein(story, lg).get("text"))
        except (KeyError, TypeError):
            continue
    lg = lage_neu()
    lg["eroeffnet"] = True
    lg["frage"] = "slotwahl"
    lg["biancaText"] = "Frei ist morgen um neun oder um zehn."
    try:
        add(naechster_baustein(story, lg).get("text"))
        add(naechster_baustein(story, lg).get("text"))
    except (KeyError, TypeError):
        pass
    return out
