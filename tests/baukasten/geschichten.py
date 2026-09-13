"""Story-Bauer des Baukasten-Tests: Attribute -> Anruf-Drehbuch.

Eine Story ist ein dict aus Attributen (Stimme, Name, Anliegen, Grund,
Wunschtag, Slot-Verhandlung, Abschweifer ...). Der Runner (runner.py) fuehrt
sie gegen den echten Bianca-Dienst: nach jedem Zug liefert die Antwort die
offene Maschinen-Frage (frage/modus, seit W-BK-3) — `naechster_baustein`
mappt sie auf den passenden Katalog-Baustein (saetze.py). Pure Logik,
offline testbar; Audio und HTTP passieren ausschliesslich im Runner.
"""

from __future__ import annotations

import hashlib
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

def einzelwoerter_liste(behandler: list[str] | tuple[str, ...] | None = None) -> list[str]:
    """Hot-30: feste Stichworte plus Behandler der gewaehlten Praxis."""
    out = list(saetze.EINZELWOERTER)
    for name in behandler or []:
        n = " ".join(str(name or "").split())
        if not n:
            continue
        last = n.split()[-1]
        for w in (last, n):
            if w and w not in out:
                out.append(w)
    return out


def automatik(nr: int, *, tag: str = "Mittwoch", seed: int | None = None,
              tenant: str = "", behandler: list[str] | tuple[str, ...] | None = None,
              gruende: list[str] | None = None) -> dict[str, Any]:
    """Eine zufaellige, aber reproduzierbare Buchungs-Story (Neupatient).

    seed=None nimmt die Story-Nummer — derselbe Aufruf baut immer dieselbe
    Story (Korrekturschleife: ein roter Fall laesst sich exakt wiederholen).
    Extra-Felder (tenant/Praxis-Gruende) nur wenn gesetzt — sonst bleibt
    der Dict byte-gleich zu den Runner-Regressionen.
    """
    rnd = random.Random(nr * 7919 if seed is None else seed)
    stimme = rnd.choice(saetze.STIMMEN_M + saetze.STIMMEN_W)
    grund_pool = list(gruende) if gruende else list(saetze.GRUENDE)
    grund = rnd.choice(grund_pool)
    themen = rnd.sample(list(saetze.ABSCHWEIFER), k=rnd.choice([0, 1, 1, 2]))
    anker = rnd.sample(ABSCHWEIF_ANKER, k=len(themen))
    aerzte = tuple(behandler) if behandler is not None else BEHANDLER
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
        "behandler": rnd.choice(tuple(aerzte) + ("",)),  # "" = egal
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
    if tenant:
        story["tenant"] = tenant
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
    key_seed = int.from_bytes(
        hashlib.blake2s(key.encode("utf-8"), digest_size=4).digest(), "big",
    )
    rnd = random.Random((story.get("seed") or 0) * 31 + key_seed)
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
        lage["rueckkehrFrage"] = fid
        lage["rueckkehrModus"] = str(lage.get("modus") or "")
        return {"text": frei, "baustein": "abschweifer_frei"}
    for anker, thema in story.get("abschweifer") or []:
        schluessel = f"abschweif:{thema}"
        if anker == fid and schluessel not in lage["gemacht"]:
            lage["gemacht"].add(schluessel)
            lage["rueckkehrFrage"] = fid
            lage["rueckkehrModus"] = str(lage.get("modus") or "")
            return {"text": _wahl(story, lage, schluessel, saetze.ABSCHWEIFER[thema]),
                    "baustein": f"abschweifer_{thema}"}
    return None


_EINZELWORT_SPERRE = frozenset({
    "telefon", "telefon_check", "buchstabieren", "name", "vorname", "nachname",
})


def einzelwort_anzahl(story: dict) -> int:
    """Wie oft einstreuen. Explizite Zahl gewinnt, sonst einmal je Wort."""
    roh = story.get("einzelwortAnzahl")
    if roh is None or roh == "":
        return len([str(w).strip() for w in (story.get("einzelwoerter") or []) if str(w).strip()])
    try:
        n = int(roh)
    except (TypeError, ValueError):
        n = 0
    return max(0, min(12, n))


def _einzelwort(story: dict, lage: dict) -> dict[str, Any] | None:
    """Ein isoliertes Stichwort — Themenwechsel, danach weiter die offene Frage.

    Unabhaengig vom Anker der Abschweifer: nach der ersten echten Antwort,
    nie zwei Worte hintereinander, nie mitten im Namens- oder Nummern-Diktat.
    Die Anzahl kommt aus einzelwortAnzahl, der Wortvorrat aus einzelwoerter.
    """
    woerter = [str(w).strip() for w in (story.get("einzelwoerter") or []) if str(w).strip()]
    budget = einzelwort_anzahl(story)
    if not woerter or budget <= 0:
        return None
    if lage.get("frage") in _EINZELWORT_SPERRE:
        return None
    if str(lage.get("letzterBaustein") or "").startswith("einzelwort"):
        return None
    if lage["zaehler"].get("antworten", 0) < 1:
        return None
    gemacht = lage.setdefault("einzelwortGemacht", [])
    if len(gemacht) >= budget:
        return None
    rest = [w for w in woerter if w not in gemacht]
    if not rest:
        rest = list(woerter)
        letzter = gemacht[-1] if gemacht else ""
        ohne = [w for w in rest if w != letzter]
        if ohne:
            rest = ohne
    rnd = random.Random((story.get("seed") or 0) + 101 * len(gemacht)
                        + lage["zaehler"].get("antworten", 0))
    wort = rest[rnd.randrange(len(rest))]
    gemacht.append(wort)
    lage["letzterBaustein"] = f"einzelwort:{wort}"
    lage["rueckkehrFrage"] = str(lage.get("frage") or "")
    lage["rueckkehrModus"] = str(lage.get("modus") or "")
    return {"text": wort, "baustein": f"einzelwort:{wort}"}


def _grund_text(story: dict, lage: dict) -> str:
    frei = str(story.get("grundText") or "").strip()
    if frei:
        return frei
    key = story.get("grund") or "kontrolle"
    if key not in saetze.GRUENDE:
        return f"Ich hätte gerne einen Termin wegen {key}."
    varianten, _erwartet = saetze.GRUENDE[key]
    return _wahl(story, lage, "grund", varianten)


def _anliegen_satz(story: dict, lage: dict) -> str:
    """Antwort auf Biancas Task-Router ('Termin, Auskunft oder Mitarbeiter?')."""
    art = str(story.get("anliegen") or TERMIN)
    if art == TERMIN:
        return _grund_text(story, lage)
    if art == ABSAGEN:
        return "Ich möchte meinen bestehenden Termin absagen."
    if art == VERSCHIEBEN:
        return "Ich möchte meinen bestehenden Termin verschieben."
    if art == AUSKUNFT:
        return "Ich möchte wissen, wann mein bestehender Termin ist."
    muster = saetze.ANLIEGEN.get(art) or []
    if muster:
        return str(muster[0])
    return _rueckkehr_text(story)


def _rueckkehr_text(story: dict) -> str:
    """Der Testanrufer verliert sein Hauptanliegen nach einer Stoerung nie."""
    art = str(story.get("anliegen") or TERMIN)
    if art == TERMIN:
        grund = str(story.get("grundErwartet") or story.get("grund") or "").strip()
        wegen = f" wegen {grund}" if grund and grund != "frei" else ""
        return f"Danke. Ich möchte aber noch meinen Termin{wegen} vereinbaren."
    if art == ABSAGEN:
        return "Danke. Ich möchte aber noch meinen bestehenden Termin absagen."
    if art == VERSCHIEBEN:
        return "Danke. Ich möchte aber noch meinen bestehenden Termin verschieben."
    if art == AUSKUNFT:
        return "Danke. Ich möchte aber noch wissen, wann mein bestehender Termin ist."
    muster = saetze.ANLIEGEN.get(art) or []
    konkret = str(muster[0] if muster else art).strip()
    return f"Danke. Mein eigentliches Anliegen ist noch offen: {konkret}"


_FRAGE_LEER_MAX = 3  # Zuege ohne offene Frage, bevor der Anrufer sich verabschiedet

# Bianca arbeitet am Anliegen — kein Themenwechsel und kein Abschied.
_ARBEITET_MARKEN = (
    "suche jetzt", "ich suche", "schaue nach", "ich schaue",
    "passenden termin", "freien terminen", "wiederhole die nummer",
    "ich habe ihre daten", "ich habe den nachname",
    "im kalender", "am apparat bleiben",
)

_DOKU_ERLEDIGT = (
    "nicht ausstellen", "nicht telefonisch ausstellen",
    "kann ich am telefon nicht", "kann ich selbst nicht",
    "persönlich vorsprechen", "persoenlich vorsprechen",
    "persönlicher vorsprach", "persoenlicher vorsprach",
    "persönlich abholen", "persoenlich abholen",
    "persönlich in der praxis", "persoenlich in der praxis",
    "in der praxis abholen", "nicht telefonisch bestellen",
    "nicht am telefon", "nicht per telefon", "nicht direkt per telefon",
    "nicht direkt am telefon", "nicht per e-mail", "nicht per email",
    "datenschutzrichtlini", "direkt an die praxis",
    "praxis selbst erledigen", "keine dokumente",
    "keine rechnungen", "rechnung",
)

_VERABSCHIEDET = (
    "auf wiederhören", "auf wiederhoeren", "auf wiedersehen",
    "schönen tag", "schoenen tag", "schönen rest",
)


def _doku_text_erledigt(text: str) -> bool:
    t = " ".join(str(text or "").lower().split())
    if not t:
        return False
    if any(x in t for x in (
            "nicht ausstellen", "nicht telefonisch", "nicht am telefon",
            "nicht per telefon", "nicht direkt per telefon",
            "nicht direkt am telefon", "nicht per e-mail", "nicht per email",
            "persönlich vorsprechen", "persoenlich vorsprechen",
            "persönlich abholen", "persoenlich abholen",
            "persönlich in der praxis", "persoenlich in der praxis",
            "in der praxis abholen", "datenschutzrichtlini",
            "direkt an die praxis", "praxis selbst",
            "keine dokumente")):
        return True
    return ("rechnung" in t and any(
        x in t for x in ("kann ich", "kann keine", "nicht", "leider")
    ))


def _bianca_verabschiedet(text: str) -> bool:
    t = " ".join(str(text or "").lower().split())
    return any(x in t for x in _VERABSCHIEDET)


def _frage_aus_text(text: str) -> str:
    """Fallback für natürliche LLM-Fragen ohne maschinenlesbares ``frage``.

    Der Last-/Story-Runner darf auf „Um welchen Arzt geht es?“ nicht mit
    einem generischen „Ja“ antworten. Eng geordnete Marker halten den
    simulierten Anrufer auf seinem ursprünglichen Formularfaden.
    """
    t = " ".join(str(text or "").lower().split())
    if not t:
        return ""
    if "schon einmal" in t or "schon mal" in t or "erstmals" in t:
        return "schonmal"
    if any(x in t for x in ("welchen arzt", "welche ärztin", "welchem arzt",
                            "welcher ärztin", "welchen behandler",
                            "welchem behandler", "arzt oder welche",
                            "bestimmten arzt", "arzt im blick", "ärzte suchen",
                            "arzt suchen", "arzt frei lassen")):
        return "arzt"
    if any(x in t for x in (
            "termin, eine auskunft", "termin eine auskunft",
            "auskunft oder möchten", "auskunft oder wollen",
            "mit einem mitarbeiter", "mitarbeiter sprechen")):
        return "anliegen"
    if "nachname" in t:
        return "nachname"
    if any(x in t for x in ("langsam aus", "buchstabieren sie",
                            "wenn sie buchstabieren", "ende einfach fertig")):
        return "buchstabieren"
    if "vorname" in t:
        return "vorname"
    if "name" in t and any(x in t for x in ("wie ", "lautet", "sagen sie", "nennen sie")):
        return "name"
    if any(x in t for x in ("telefonnummer", "rufnummer", "handynummer",
                            "welche nummer", "erreichen kann")):
        return "telefon"
    if "krankenkasse" in t:
        return "versicherung"
    if "versicher" in t:
        return "versicherung"
    if any(x in t for x in ("grund für ihren besuch", "grund ihres besuch",
                            "worum geht es", "weshalb möchten", "behandlungsgrund",
                            "wobei ich helfen", "was genau möchten",
                            "kontrolle oder zahnreinigung", "akute schmerzen")):
        return "grund"
    if any(x in t for x in ("welchen termin", "welcher termin", "ersten oder",
                            "zweiten oder", "welche uhrzeit davon")):
        return "slotwahl"
    if any(x in t for x in ("so eintragen", "fest eintragen", "verbindlich buchen",
                            "soll ich den termin", "darf ich den termin")):
        return "bestaetigung"
    if "zahnreinigung" in t and "?" in t:
        return "pzr"
    if any(x in t for x in ("wunschtermin", "wann passt", "wann es ihnen",
                            "welche woche", "tageszeit", "vormittag oder",
                            "nachmittag oder")):
        return "wunsch"
    return ""


def naechster_baustein(story: dict, lage: dict) -> dict[str, Any]:
    """Der naechste Anrufer-Zug zur offenen Frage.

    Rueckgabe: {"text", "baustein", optional "halbsatzRest", "auflegen"}.
    Leerer Text + auflegen=True beendet den Anruf ohne weiteren Zug.
    """
    if not lage["eroeffnet"]:
        return _eroeffnung(story, lage)

    antwort_text = " ".join(str(lage.get("biancaText") or "").lower().split())
    art = str(story.get("anliegen") or TERMIN)
    if art in DOKU_ARTEN and _doku_text_erledigt(antwort_text):
        lage["fachlichErledigt"] = "doku_auskunft"
        lage["gemacht"].add("abschied")
        return {
            "text": "Verstanden, dann komme ich persönlich vorbei. Vielen Dank und auf Wiederhören.",
            "baustein": "doku_abschied",
            "auflegen": True,
        }
    if _bianca_verabschiedet(antwort_text):
        lage["gemacht"].add("abschied")
        if art in DOKU_ARTEN:
            lage["fachlichErledigt"] = lage.get("fachlichErledigt") or "doku_auskunft"
            return {
                "text": _wahl(story, lage, "abschied", saetze.ABSCHIED),
                "baustein": "doku_abschied",
                "auflegen": True,
            }
        if lage.get("fachlichErledigt"):
            return {
                "text": _wahl(story, lage, "abschied", saetze.ABSCHIED),
                "baustein": "abschied",
                "auflegen": True,
            }
        return {
            "text": _wahl(story, lage, "abschied", saetze.ABSCHIED),
            "baustein": "abschied",
            "auflegen": True,
        }
    if any(x in antwort_text for x in (
            "keinen freien termin", "keine freien termine",
            "leider keinen termin", "leider keine termine",
            "rückrufbitte", "rueckrufbitte", "praxis meldet sich")):
        lage["fachlichErledigt"] = "kein_slot"
        if "nichts_mehr" not in lage["gemacht"]:
            lage["gemacht"].add("nichts_mehr")
            return {
                "text": _wahl(story, lage, "nichts_mehr", saetze.NICHTS_MEHR),
                "baustein": "nichts_mehr",
            }
        lage["gemacht"].add("abschied")
        return {
            "text": _wahl(story, lage, "abschied", saetze.ABSCHIED),
            "baustein": "abschied",
            "auflegen": True,
        }

    fid = lage["frage"]
    if fid == "telefon_check" and not any(x in antwort_text for x in (
            "stimmt das", "wiederhole", "null eins", "ist das korrekt",
            "habe die nummer", "habe Ihre nummer", "habe ihre nummer")):
        fid = ""
        lage["frage"] = ""
    if not fid:
        fid = _frage_aus_text(lage.get("biancaText") or "")
        if fid:
            lage["frage"] = fid

    # Verabschiedet? Nach dem Abschied ist Schluss (Runner legt auf).
    if "abschied" in lage["gemacht"]:
        return {"text": "", "baustein": "", "auflegen": True}

    # Nach einem Abschweifer/Stichwort hat das Hauptgespraech Vorrang. Hat
    # Bianca die vorher offene Frage wieder aufgenommen, beantwortet der
    # Anrufer sie sofort. Ist Bianca auf eine Nebenaufgabe abgebogen, holt
    # der Anrufer das urspruengliche Anliegen explizit zurueck.
    rueckkehr_frage = lage.get("rueckkehrFrage")
    direkt_antworten = False
    if rueckkehr_frage is not None:
        lage.pop("rueckkehrFrage", None)
        lage.pop("rueckkehrModus", None)
        # Dieselbe oder eine spätere Formular-Pflichtfrage führt den
        # Hauptfaden fort. Ein neues Zusatzthema (z. B. PZR statt Behandler)
        # darf das ursprüngliche Anliegen dagegen nicht verdrängen.
        hauptfragen = {
            "schonmal", "arzt", "name", "vorname", "nachname", "grund",
            "wunsch", "buchstabieren", "telefon", "telefon_check",
            "telefon_alt", "versicherung", "versicherung_check",
            "slotwahl", "bestaetigung", "wann", "behandlung",
        }
        gleicher_faden = bool(fid) and (
            fid == rueckkehr_frage or fid in hauptfragen
        )
        if not gleicher_faden:
            lage["letzterBaustein"] = "rueckkehr_hauptanliegen"
            return {"text": _rueckkehr_text(story),
                    "baustein": "rueckkehr_hauptanliegen"}
        direkt_antworten = True

    wort = None if direkt_antworten else _einzelwort(story, lage)
    if wort:
        return wort
    lage["letzterBaustein"] = ""
    lage["zaehler"]["antworten"] = lage["zaehler"].get("antworten", 0) + 1

    # Geplante Stoerungen: Abschweifer und Preis-Zwischenfrage verdraengen
    # die Antwort GENAU EINMAL — die Maschine muss die Frage erneut stellen.
    stoer = None if direkt_antworten else _abschweifer(story, lage)
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
        if "name_gesagt" in lage["gemacht"]:
            return {"text": f"Mein Nachname ist {story['nachname']}.",
                    "baustein": "nachname_klar"}
        lage["gemacht"].add("name_gesagt")
        return {"text": _wahl(story, lage, "nachname", saetze.NACHNAME_NUR).format(nachname=story["nachname"]),
                "baustein": "nachname"}
    if fid == "anliegen":
        return {"text": _anliegen_satz(story, lage), "baustein": "anliegen"}
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
        if "name_gesagt" in lage["gemacht"]:
            return {"text": f"Mein Nachname ist {story['nachname']}. Fertig.",
                    "baustein": "nachname_klar"}
        lage["gemacht"].add("name_gesagt")
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
            lage["fachlichErledigt"] = "kein_slot"
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
        if story.get("lasttestKeinSchreiben"):
            return {
                "text": "Nein, bitte nicht eintragen. Das war nur ein Test. Vielen Dank und auf Wiederhören.",
                "baustein": "lasttest_keine_buchung",
                "auflegen": True,
            }
        return {"text": _wahl(story, lage, "bestaetigung", saetze.BESTAETIGUNG_JA), "baustein": "bestaetigung"}
    if fid == "arzt_notiz":
        frei = str(story.get("arztNotizText") or "").strip()
        if frei:
            return {"text": frei, "baustein": "arzt_notiz"}
        return {"text": "Nein, danke.", "baustein": "arzt_notiz_nein"}
    if fid == "arzt_notiz_diktat":
        return {"text": str(story.get("arztNotizText") or "Nichts Besonderes."),
                "baustein": "arzt_notiz_diktat"}
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
    art = str(story.get("anliegen") or TERMIN)
    if art in DOKU_ARTEN and any(x in text for x in (
            "nicht ausstellen", "nicht telefonisch ausstellen",
            "kann ich am telefon nicht", "kann ich selbst nicht",
            "persönlich vorsprechen", "persoenlich vorsprechen",
            "persönlicher vorsprach", "persoenlicher vorsprach",
            "nicht telefonisch bestellen", "nur persönlich")):
        lage["fachlichErledigt"] = "doku_auskunft"
    if lage.get("fachlichErledigt") == "doku_auskunft" and (
            "nichts_mehr" in lage["gemacht"]):
        lage["gemacht"].add("abschied")
        return {
            "text": _wahl(story, lage, "abschied", saetze.ABSCHIED),
            "baustein": "doku_abschied",
            "auflegen": True,
        }
    if lage.get("fachlichErledigt") == "doku_auskunft" and not any(
            x in text for x in ("sonst noch", "noch etwas")):
        lage["gemacht"].add("abschied")
        return {
            "text": _wahl(story, lage, "abschied", saetze.ABSCHIED),
            "baustein": "doku_abschied",
            "auflegen": True,
        }
    if any(x in text for x in (
            "116 117", "116117", "ärztlichen bereitschaftsdienst",
            "aerztlichen bereitschaftsdienst", "wählen sie sofort die 112",
            "waehlen sie sofort die 112")):
        lage["fachlichErledigt"] = "notfall_auskunft"
        lage["gemacht"].add("abschied")
        return {
            "text": "Verstanden, vielen Dank für die klare Auskunft. Auf Wiederhören.",
            "baustein": "notfall_abschied",
            "auflegen": True,
        }
    if any(x in text for x in (
            "persönlich vorsprechen", "persoenlich vorsprechen",
            "nicht telefonisch bestellen", "nur persönlich")):
        lage["gemacht"].add("abschied")
        return {
            "text": "Verstanden, dann komme ich persönlich vorbei. Vielen Dank und auf Wiederhören.",
            "baustein": "doku_abschied",
            "auflegen": True,
        }
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
    if any(x in text for x in _ARBEITET_MARKEN):
        suche = lage["zaehler"].get("suche", 0) + 1
        lage["zaehler"]["suche"] = suche
        if suche <= 2:
            return {"text": "Ja, gerne, ich warte.", "baustein": "warte_suche"}
        return {
            "text": _rueckkehr_text(story),
            "baustein": "rueckkehr_hauptanliegen",
        }
    leer = lage["zaehler"].get("frage_leer", 0) + 1
    lage["zaehler"]["frage_leer"] = leer
    if "?" in text and leer <= _FRAGE_LEER_MAX:
        return {"text": _anliegen_satz(story, lage), "baustein": "anliegen"}
    if leer <= _FRAGE_LEER_MAX:
        return {
            "text": _rueckkehr_text(story),
            "baustein": "rueckkehr_hauptanliegen",
        }
    lage["gemacht"].add("abschied")
    return {"text": _wahl(story, lage, "abschied", saetze.ABSCHIED), "baustein": "abschied", "auflegen": True}


def frei_saetze(story: dict) -> list[str]:
    """Nur manuell eingegebene Werte fuer gezieltes Audio-Vorwaermen.

    Freitext wird dabei einmal so normalisiert, wie er spaeter gesprochen
    wird. Eigene Namen und Behandler zaehlen ebenfalls als Freitext; die
    eingebauten Schnellwahlen nicht.
    """
    out: list[str] = []

    def add(text: Any) -> None:
        norm = " ".join(str(text or "").split())
        if norm and norm not in out:
            out.append(norm)

    for feld in (
        "eroeffnungText", "grundText", "wunschText", "versicherungText",
        "slotText", "abschweiferText", "arztNotizText",
    ):
        norm = " ".join(str(story.get(feld) or "").split())
        if norm:
            story[feld] = norm
            add(norm)

    stimme = str(story.get("stimme") or "")
    vorname = " ".join(str(story.get("vorname") or "").split())
    nachname = " ".join(str(story.get("nachname") or "").split())
    eigener_name = (
        (vorname and vorname != saetze.VORNAMEN.get(stimme, ""))
        or (nachname and nachname not in saetze.NACHNAMEN)
    )
    if eigener_name and vorname and nachname:
        add(saetze.name_satz(vorname, nachname, int(story.get("seed") or 0)))
        add(nachname)

    behandler = " ".join(str(story.get("behandler") or "").split())
    bekannte = {str(x).casefold() for x in BEHANDLER}
    if behandler and behandler.casefold() not in bekannte:
        add(saetze.arzt_satz(behandler, int(story.get("seed") or 0)))
        add(behandler)
    return out


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
    for w in story.get("einzelwoerter") or []:
        add(w)

    lg = lage_neu()
    add(_eroeffnung(story, lg).get("text"))
    for fid in ("schonmal", "arzt", "name", "vorname", "nachname", "grund",
                "wunsch", "buchstabieren", "telefon", "telefon_check",
                "versicherung", "pzr", "bestaetigung", "arzt_notiz",
                "arzt_notiz_diktat", "wann", "behandlung"):
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
