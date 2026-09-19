# -*- coding: utf-8 -*-
"""Read-only: ALLE Anliegen aus ALLEN Anrufer-Zuegen der Live-Manifeste.

Laeuft im Container gegen /app/.data/anrufe/bianca. Schreibt JSON nach
stdout (letzte Zeile = #JSON-Pfad) und nach /tmp/anliegen_alle.json.
Kein Kalender-Write, kein Live-Umschalten.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("ANLIEGEN_ROOT", "/app/.data/anrufe/bianca"))
OUT = Path(os.environ.get("ANLIEGEN_OUT", "/tmp/anliegen_alle.json"))


def _falt(s: str) -> str:
    s = (s or "").lower().replace("ß", "ss")
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _text_von_zug(z: dict) -> str:
    """Nur Anrufer-Text. ``text`` im Manifest ist Biancas Mund — nie lesen."""
    if not isinstance(z, dict):
        return ""
    v = z.get("textIn")
    if isinstance(v, str) and v.strip():
        return v.strip()
    stt = z.get("stt")
    if isinstance(stt, dict):
        par = stt.get("parakeet")
        if isinstance(par, dict):
            t = par.get("text")
            if isinstance(t, str) and t.strip():
                return t.strip()
        if isinstance(par, str) and par.strip():
            return par.strip()
    return ""


_GRUSS = re.compile(
    r"hallo,?\s+(hautarztpraxis|praxis doktor|thaler|zahnaerzte|"
    r"zahnarztpraxis)|sie sprechen mit|wie kann ich (ihnen )?helfen|"
    r"digitalen? assistent",
    re.I,
)
_ANSAGE = re.compile(
    r"einen kleinen augenblick|wir sind gleich persoenlich|"
    r"bleiben sie (bitte )?in der leitung|ihr anruf ist uns wichtig|"
    r"alle leitungen sind besetzt|online finden sie uns|"
    r"www\.|danke fuer ihren anruf",
    re.I,
)
_FORM = re.compile(
    r"^(ja|nein|jo|nee|ok|okay|genau|richtig|stimmt|klar|gut|"
    r"danke|dankeschoen|bitte|hm+|mhm+|aha|ach so|oh|"
    r"ja bitte|ja genau|ja ja|nein danke|nein danke sehr|"
    r"erster|zweite[rns]?|dritte[rns]?|die erste|die zweite|"
    r"privat|gesetzlich|kasse|beide|alle|"
    r"nachmittag[s]?|vormittag[s]?|egal|"
    r"thank you|nice|mm hmm|mhm|"
    r"gesetzlich versichert|privat versichert|"
    r"hallo|hallo hallo|hi|guten tag|guten nachmittag|"
    r"vielen dank|dankeschoen|okay danke|ja gerne|ja danke|"
    r"ja ich bin (auch )?dran|ich bin noch da|"
    r"keiner|ist egal|besuchsgrund|falsch|"
    r"frau doktor \w+|herr doktor \w+|doktor \w+)\.?$",
    re.I,
)
_NUR_NAME = re.compile(
    r"^[a-zäöüß\- ]{2,24}$",
    re.I,
)
_DIGITS = re.compile(r"^[\d\s./+-]{4,}$")
_BUCHSTAB = re.compile(r"^(?:[a-z]\s*[-\s,])+[a-z]\.?$", re.I)
_BIANCA_LECK = re.compile(
    r"meine frage war:|sind sie noch dran|kann ich sonst noch|"
    r"ich komme hier gerade nicht weiter|worum geht es denn",
    re.I,
)


def _ist_rauschen(t: str) -> bool:
    f = _falt(t)
    if not f or len(f) < 2:
        return True
    if _GRUSS.search(t) and len(t) > 40:
        return True
    if _ANSAGE.search(t) or _BIANCA_LECK.search(t):
        return True
    if _FORM.match(f):
        return True
    if _DIGITS.match(t.strip()):
        return True
    if _BUCHSTAB.match(t.strip()):
        return True
    if _NUR_NAME.match(t.strip()) and "termin" not in f:
        return True
    return False


# Reihenfolge: enger/spezifischer zuerst. Ein Satz darf MEHRERE treffen.
# Jede Regel: (id, label, gruppe, regex auf gefaltetem Text)
REGELN: list[tuple[str, str, str, re.Pattern[str]]] = [
    (
        "rezept",
        "Rezept bestellen / abholen / Rueckfrage",
        "dokument",
        re.compile(r"\brezept(?!ion)\w*"),
    ),
    (
        "ueberweisung",
        "Ueberweisung",
        "dokument",
        re.compile(r"\bueberweis"),
    ),
    (
        "krankmeldung",
        "Krankmeldung / AU",
        "dokument",
        re.compile(r"\bkrank(?:en)?meldung|\barbeitsunfaeh|\bau beschein"),
    ),
    (
        "befund",
        "Befunde (Mail / Abholung / Einsicht)",
        "dokument",
        re.compile(
            r"\bbefund\w*|\bbeh?nad?lungsunterlagen|"
            r"\bbehandlungs\w*unterlagen|\bpatientenunterlagen|"
            r"\bmeine ergebnisse|\bergebnisse von"
        ),
    ),
    (
        "roentgen",
        "Roentgenbilder",
        "dokument",
        re.compile(r"\br(?:oe|o)?n?t?gen"),
    ),
    (
        "unterlagen",
        "Akte / Unterlagen / Einsicht",
        "dokument",
        re.compile(
            r"\bunterlagen\b|\bakte einsehen|\bkrankenakte|"
            r"\bpatientenakte|\beinsicht|\bkopie der|\bmeine akte"
        ),
    ),
    (
        "email_dokument",
        "Unterlagen per E-Mail",
        "dokument",
        re.compile(
            r"(befund|unterlagen|bilder|akte|roentgen|rontgen).{0,28}"
            r"(e ?mail|mailen|per mail)|"
            r"(e ?mail|mailen|per mail).{0,28}"
            r"(befund|unterlagen|bilder|akte|roentgen|rontgen)"
        ),
    ),
    (
        "labor",
        "Labor / Blutwerte / Ergebnisse",
        "dokument",
        re.compile(r"\blabor\b|\bblutwerte|\bergebnisse\b"),
    ),
    (
        "rechnung",
        "Rechnung / Buchhaltung",
        "rechnung",
        re.compile(
            r"\brechnung|\breklamation|\bmahnung|\bhonorar|"
            r"\bbuchhaltung|\binkasso|\babrechnungsfehler|"
            r"zu viel bezahlt|doppelt abgebucht"
        ),
    ),
    (
        "verbinden_arzt",
        "Mit Arzt / namentlich verbinden",
        "erreichen",
        re.compile(
            r"\b(?:dr|doktor|herrn?|frau)\b.{0,28}\b(?:sprech|verbind|"
            r"durchstell|weiterleit)|"
            r"\bverbind\w*.{0,24}\b(?:doktor|dr|arzt|blessing|petsas|"
            r"patrikis|thaler|ruether)|"
            r"mit (?:dem |der )?(?:doktor|arzt|aerztin).{0,16}sprech|"
            r"\barzt sprechen|\baerztin sprechen|"
            r"kann ich (?:frau|herrn?) doktor"
        ),
    ),
    (
        "anmeldung",
        "Anmeldung / Mitarbeiter / Mensch",
        "erreichen",
        re.compile(
            r"\banmeldung\b|\bempfang\b|\brezeption\b|"
            r"\bmitarbeiter\w*|\bpersonal\b|\barzthelfer\w*|"
            r"\bpraxisteam|\bechte[nr]? mensch|\brichtige[nr]? mensch|"
            r"\bjemanden sprechen|\bmit jemandem sprechen|"
            r"persoenlich(?:en)? mitarbeiter"
        ),
    ),
    (
        "rueckruf",
        "Rueckruf / Nachricht hinterlassen",
        "erreichen",
        re.compile(
            r"\brueckruf|\bzurueckruf|\bruft mich|\bmeldet sich|"
            r"\bnachricht hinterlass|\bausricht|\bcallback|"
            r"ich wurde angerufen|warum (?:wurde ich |habt ihr )angerufen"
        ),
    ),
    (
        "absagen",
        "Termin absagen",
        "bestand",
        re.compile(
            r"\babsag|\bstornier|\babbestell|\bcancel|"
            r"termin.{0,24}(?:loesch|streich|entfern|aufheb|rueckgaeng)|"
            r"nicht (?:kommen|wahrnehmen|schaffen|einhalten)|"
            r"termin faellt aus"
        ),
    ),
    (
        "verschieben",
        "Termin verschieben",
        "bestand",
        re.compile(
            r"\bverschieb|\bumbuch|\bverleg|\bumleg|\bvorverleg|"
            r"anderen (?:tag|termin)|auf einen anderen|"
            r"terminverschieb"
        ),
    ),
    (
        "auskunft_bestand",
        "Bestehenden Termin nachfragen",
        "bestand",
        re.compile(
            r"habe ich .{0,20}termin|wann ist .{0,16}termin|"
            r"wann war .{0,16}termin|welchen termin|welche termine|"
            r"mein(?:en)? termin|termin vergessen|termin verpennt|"
            r"weiss (?:den tag|die uhrzeit|nicht mehr).{0,20}termin|"
            r"termin.{0,24}(?:vergessen|weiss ich nicht)|"
            r"bestehend\w* termin|gebucht\w* termin|"
            r"schon (?:einen |mal )?termin"
        ),
    ),
    (
        "auskunft_wort",
        "nacktes Wort Auskunft",
        "bestand",
        re.compile(
            r"^\s*auskunft\s*$|\bterminauskunft\b|\bnur auskunft\b|"
            r"\beine auskunft\b|\bum eine auskunft\b"
        ),
    ),
    (
        "mehrere_termine",
        "Zwei / mehrere Termine",
        "mehrfach",
        re.compile(
            r"\b(?:zwei|beide|alle|mehrere|zweiten?|dritten?)\b.{0,20}\btermin"
            r"|\btermin.{0,20}\b(?:zwei|beide|alle|mehrere)"
            r"|\bund (?:dann |auch )?(?:noch )?(?:einen |einen zweiten )"
            r"termin"
        ),
    ),
    (
        "drittperson",
        "Termin fuer Dritte (Kind, Partner, Nachbar)",
        "dritte",
        re.compile(
            r"\bfuer (?:mein(?:en)?|meine[n]?|den|die)\s+"
            r"(?:sohn|tochter|kind|enkel|mann|frau|partner|"
            r"freundin|freund|mutter|vater|bruder|schwester|nachbar|"
            r"kollegen?|oma|opa)|"
            r"\bmein(?:en)? (?:sohn|tochter|kind|mann|nachbar)|"
            r"\bnicht fuer mich|\bim auftrag|\bfuer jemand"
        ),
    ),
    (
        "buchen",
        "Neuen Termin vereinbaren",
        "buchen",
        re.compile(
            r"\btermin (?:haben|machen|vereinbaren|bekommen|kriegen|"
            r"brauchen|buchen|nehmen|ausmachen)|"
            r"(?:haette|hatte|wuerde|moechte|will|brauche|brauch)\w*"
            r".{0,24}\btermin|"
            r"\bneuen? termin|\bersttermin|\bneupatient|"
            r"\bkontrolltermin|\bvorsorgetermin|"
            r"gerne (?:einen )?termin|\bneu vereinbaren\b|"
            r"neuen (?:legen|eintragen|finden)|"
            r"\beinen termin\b|"
            r"(?:moechte|will|brauche|brauchte|haette|gerne).{0,40}\btermin"
        ),
    ),
    (
        "schmerzen",
        "Schmerzen / akut / Notfall",
        "klinisch",
        re.compile(
            r"\bschmerz|\btut weh|\bdicke backe|"
            r"\bnotfall|\bakute?\b|\bgeschwollen|\beiter\b"
        ),
    ),
    (
        "pzr",
        "Zahnreinigung / PZR",
        "klinisch",
        re.compile(r"\bzahnreinig|\bpzr\b|\bprophylaxe"),
    ),
    (
        "bleaching",
        "Bleaching / Aufhellung",
        "klinisch",
        re.compile(r"\bbleach|\baufhell"),
    ),
    (
        "implantat",
        "Implantat / ZE-Besprechung",
        "klinisch",
        re.compile(r"\bimplantat|\bzahnersatz|\bkrone|\bbruecke|\bprothese"),
    ),
    (
        "fuellung",
        "Fuellung / Loch",
        "klinisch",
        re.compile(r"\bfuell\w*|\bloch im zahn"),
    ),
    (
        "wurzel",
        "Wurzelbehandlung",
        "klinisch",
        re.compile(r"\bwurzelbehand|\bwkb\b"),
    ),
    (
        "kfo",
        "Kieferorthopaedie / schiefe Zaehne",
        "klinisch",
        re.compile(r"\bkfo\b|\bkieferortho|\bschiefe zaehne|\bspange\b|\binvisalign"),
    ),
    (
        "kontrolle",
        "Kontrolle / Vorsorge / Screening",
        "klinisch",
        re.compile(
            r"\bkontrolle\b|\bvorsorge|\bscreening|\bhautkrebs|"
            r"\bhautkontrolle|\bcheck.?up|\bnachsorge|\bforsabe"
        ),
    ),
    (
        "neupatient",
        "Neupatient / Erstvorstellung",
        "klinisch",
        re.compile(r"\bneupatient|\berstvorstell|\berste[ns]? mal (?:hier|da)|"
                   r"noch nie (?:hier|da) gewesen"),
    ),
    (
        "beratung",
        "Beratung (ohne konkreten Grund)",
        "klinisch",
        re.compile(r"\bberatung\b|\bbesprechung\b"),
    ),
    (
        "etwas_anderes",
        "Etwas anderes (Grund offen)",
        "klinisch",
        re.compile(r"\betwas anderes\b"),
    ),
    (
        "muttermal",
        "Muttermal",
        "klinisch",
        re.compile(r"\bmuttermal|\bleberfleck"),
    ),
    (
        "warzen",
        "Warzen / Dornwarzen",
        "klinisch",
        re.compile(r"\bwarze|\bdornwarze"),
    ),
    (
        "atherom",
        "Atherom / Gruetzbeutel",
        "klinisch",
        re.compile(r"\batherom|\batterom|\bgruetzbeutel|\btalg"),
    ),
    (
        "botox",
        "Botox / Filler",
        "klinisch",
        re.compile(r"\bbotox|\bfiller\b"),
    ),
    (
        "blutabnahme",
        "Blutabnahme",
        "klinisch",
        re.compile(r"\bblutabnahme|\bblut abnehmen"),
    ),
    (
        "fusspflege",
        "Fusspflege / Podologie",
        "klinisch",
        re.compile(r"\bfusspflege|\bpodolog"),
    ),
    (
        "impfung",
        "Impfung",
        "klinisch",
        re.compile(r"\bimpfung|\bimpfen\b"),
    ),
    (
        "allergie",
        "Allergie / Hyposensibilisierung",
        "klinisch",
        re.compile(r"\bhyposensibil|\ballergi"),
    ),
    (
        "schwangerschaft",
        "Schwangerschaft / Vorsorge Gyn",
        "klinisch",
        re.compile(r"\bschwanger|\bspirale\b|\bhormonstatus|\bhormonstase"),
    ),
    (
        "akne",
        "Akne / Ekzem / Psoriasis / Haut",
        "klinisch",
        re.compile(r"\bakne\b|\bekzem|\bpsoriasis|\brosacea|\bausschlag|"
                   r"\bhautbeschwerd|\bhautveraenderung|"
                   r"probleme mit der haut|\bnagelpilz"),
    ),
    (
        "preis",
        "Preis- / Kostfrage",
        "wissen",
        re.compile(r"was kostet|\bpreis\b|\bwie teuer|\bwie lange dauert"),
    ),
    (
        "oeffnungszeiten",
        "Oeffnungszeiten",
        "wissen",
        re.compile(
            r"\boeffnungszeit|\bsprechzeit|\bwann (?:habt|haben) (?:ihr|sie) "
            r"(?:auf|offen|geoeffnet)|\bist .{0,12}offen"
        ),
    ),
    (
        "anfahrt",
        "Anfahrt / Adresse / Parken",
        "wissen",
        re.compile(r"\banfahrt|\bparkplatz|\bwie komme ich|\badresse|"
                   r"\bwo liegt|\bwo sind sie"),
    ),
    (
        "versicherung",
        "Versicherung / Kasse (als Anliegen, nicht Formular)",
        "wissen",
        re.compile(r"\bprivat versichert|\bkassenpatient|\bversicherung|"
                   r"kasse (?:uebernimmt|zahlt)|hautkrebsvorsorge gesetzlich"),
    ),
    (
        "kein_handy",
        "Kein Handy / Festnetz",
        "lage",
        re.compile(r"kein handy|keine handy|festnetz"),
    ),
    (
        "beschwerde",
        "Beschwerde / Unzufriedenheit",
        "lage",
        re.compile(
            r"\bbeschwerde\b|\breklami|\bunfreundlich|\bwartezeit|"
            r"\baerger|\bnicht nett|\bbeschissen"
        ),
    ),
    (
        "abschied",
        "Auflegen / Tschuess",
        "lage",
        re.compile(
            r"\bauf wiederhoeren|\bauf wiedersehen|\btsch(?:ue|u)ss|"
            r"\bciao\b|\bbis denn|\bschoenen tag|\bdas war.?s\b|"
            r"telefon beenden"
        ),
    ),
]


def deute_satz(t: str) -> list[str]:
    f = _falt(t)
    if _ist_rauschen(t):
        return []
    hits: list[str] = []
    for key, _label, _grp, rx in REGELN:
        if rx.search(f) and key not in hits:
            hits.append(key)
    # Befundbesprechung / Roentgentermin sind Termine, keine Dokumente
    if re.search(r"befund\w*besprech|roentgen\w*termin|rontgen\w*termin", f):
        hits = [h for h in hits if h not in {"befund", "roentgen", "unterlagen"}]
        if "buchen" not in hits:
            hits.append("buchen")
    if "verschieben" in hits or "absagen" in hits:
        if "buchen" in hits and not re.search(
            r"neu(?:en)? termin|noch (?:einen )?termin|neu vereinbaren", f
        ):
            hits = [h for h in hits if h != "buchen"]
        hits = [h for h in hits if h != "auskunft_bestand"]
    if not hits:
        if re.search(r"\btermin", f):
            hits.append("termin_unklar")
        elif re.search(
            r"^\d{1,2}(?:\s*uhr)?$|^\d{1,2}\.\d{1,2}|montag|dienstag|"
            r"mittwoch|donnerstag|freitag|samstag|sonntag|"
            r"januar|februar|maerz|april|mai|juni|juli|august|"
            r"september|oktober|november|dezember",
            f,
        ):
            return []
        else:
            hits.append("sonst")
    return hits


LABEL = {k: lab for k, lab, _g, _r in REGELN}
LABEL["termin_unklar"] = "Terminwort ohne Richtung"
LABEL["sonst"] = "sonst / noch nicht klassifiziert"
GRUPPE = {k: g for k, _l, g, _r in REGELN}
GRUPPE["termin_unklar"] = "unklar"
GRUPPE["sonst"] = "unklar"


_TENANT = {
    "uujnpzoypa4yyyzcaglm": "blessing",
    "awdfedldr81p3jmiq869": "ruether",
    "mee4zqhezopzlcexyhdt": "meddent",
    "7ttnjzfjkb801r2rmyed": "thaler",
}


def _praxis(m: dict) -> str:
    tid = str(m.get("tenantId") or m.get("clientId") or "").strip()
    mapped = _TENANT.get(tid.lower())
    if mapped:
        return mapped
    raw = " ".join(
        str(m.get(k) or "")
        for k in ("tenant", "mandant", "praxis", "clientName", "agentName")
    ).lower()
    if "bless" in raw:
        return "blessing"
    if "rueth" in raw or "rüth" in raw:
        return "ruether"
    if "thaler" in raw:
        return "thaler"
    if "meddent" in raw or "medical center" in raw:
        return "meddent"
    did = str(m.get("did") or m.get("calledNumber") or "")
    if did.endswith("4120"):
        return "blessing"
    if did.endswith("4160"):
        return "ruether"
    if did.endswith("4101") or did.endswith("4110"):
        return "meddent"
    if tid:
        return tid
    return "?"


def _ergebnis(m: dict) -> list[str]:
    out = []
    if m.get("lastBook"):
        out.append("gebucht")
    if m.get("lastCancel"):
        out.append("abgesagt")
    if m.get("lastMove"):
        out.append("verschoben")
    if m.get("lastNote") or m.get("praxisNotiz"):
        out.append("notiz")
    if m.get("weiterleitungZiel") or m.get("lastTransfer"):
        out.append("transfer")
    return out


def scan() -> dict:
    anrufe = 0
    test = 0
    leer = 0
    zaehl_anrufe: Counter[str] = Counter()
    zaehl_saetze: Counter[str] = Counter()
    belege: dict[str, list[str]] = defaultdict(list)
    sonst_saetze: Counter[str] = Counter()
    pro_praxis: dict[str, Counter[str]] = defaultdict(Counter)
    mehrfach_anrufe = 0
    erste_anliegen: Counter[str] = Counter()

    for pfad in sorted(ROOT.glob("*/anruf.json")):
        try:
            m = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict):
            continue
        anrufe += 1
        if m.get("testAnruf"):
            test += 1
            continue
        praxis = _praxis(m).lower()
        saetze: list[str] = []
        for z in m.get("zuege") or []:
            t = _text_von_zug(z if isinstance(z, dict) else {})
            if t:
                saetze.append(t)
        if not saetze:
            leer += 1
            continue
        found: set[str] = set()
        erst: list[str] = []
        for t in saetze:
            keys = deute_satz(t)
            if not keys:
                continue
            if not erst:
                erst = keys
            for k in keys:
                zaehl_saetze[k] += 1
                if k not in found:
                    found.add(k)
                    if len(belege[k]) < 6 and t not in belege[k]:
                        belege[k].append(re.sub(r"\s+", " ", t)[:160])
                if k == "sonst":
                    sonst_saetze[re.sub(r"\s+", " ", t)[:140]] += 1
        # Ledger-Nachzug: was wirklich passierte, falls Text den Intent verpasste
        real = found - {"sonst", "abschied", "kein_handy"}
        if "sonst" in found and real:
            found.discard("sonst")
        for k in found:
            zaehl_anrufe[k] += 1
            pro_praxis[praxis][k] += 1
        if len(found - {"abschied", "sonst", "termin_unklar"}) >= 2:
            mehrfach_anrufe += 1
        for k in erst:
            erste_anliegen[k] += 1

    gewertet = anrufe - test
    rows = []
    for k, n in zaehl_anrufe.most_common():
        rows.append(
            {
                "id": k,
                "label": LABEL.get(k, k),
                "gruppe": GRUPPE.get(k, "?"),
                "anrufe": n,
                "saetze": zaehl_saetze.get(k, 0),
                "anteil": round(100.0 * n / gewertet, 1) if gewertet else 0,
                "erst": erste_anliegen.get(k, 0),
                "belege": belege.get(k, []),
            }
        )
    return {
        "anrufe": anrufe,
        "test": test,
        "gewertet": gewertet,
        "leer": leer,
        "mehrfach": mehrfach_anrufe,
        "anliegen": rows,
        "sonst_top": [
            {"n": n, "text": t} for t, n in sonst_saetze.most_common(80)
        ],
        "praxis": {
            p: dict(c) for p, c in sorted(pro_praxis.items())
        },
    }


def main() -> None:
    report = scan()
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Anrufe={report['anrufe']} Test={report['test']} Gewertet={report['gewertet']} Mehrfach={report['mehrfach']}")
    for z in report["anliegen"]:
        print(f"{z['anrufe']:4d}  {z['id']:18s}  {z['label']}")
        for b in z["belege"][:2]:
            print(f"      · {b}")
    print("--- SONST (Top) ---")
    for s in report["sonst_top"][:25]:
        print(f"{s['n']:4d}  {s['text']}")
    print(f"#JSON {OUT}", flush=True)


if __name__ == "__main__":
    main()
