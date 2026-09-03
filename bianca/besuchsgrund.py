"""Besuchsgrund-Mapping: gesprochener Grund -> Besuchsgrund des Behandlers.

Der Patient sagt "ich brauche eine Wurzelbehandlung" oder "meine Prothese ist
gebrochen" — gebucht werden muss aber ein Besuchsgrund AUS DER LISTE des
Behandlers (tenant.visitMotives), damit er im Terminpopup der Plattform richtig
angewählt ist (Chef 27.08.2026). Jedes Konzept trägt dafür eine Muster-Liste
in Prioritätsreihenfolge; gesucht wird im Mandanten-Bestand, nie erfunden.

Regeln vom Chef:
  - "WK klein (immer klein buchen)": gibt es mehrere Varianten (klein/groß),
    gewinnt IMMER die mit "klein" im Namen.
  - Kein passendes Motiv in der Liste => Besprechungs-/Kontrolltermin buchen
    und der WORTLAUT des Patienten wandert in die Terminnotiz (kern/notes).
"""

from __future__ import annotations

import html
import re
from typing import Any

from kern import motive

# (Erkennungs-Muster im Patientensatz, sprechbarer Kern, Motiv-Muster nach Priorität)
# Die Motiv-Muster sind fuer den ECHTEN Standort-Katalog geschaerft
# (30.08.2026: 133 Motive statt 11 in der Mandanten-Datei): Erstkontakt am
# Telefon bucht BESPRECHUNG/Kontrolle, nie direkt eine OP oder Eingliederung —
# sonst gewann z. B. bei "Implantat" die 120-Minuten-OP ueber die klein-Regel.
KONZEPTE: list[tuple[re.Pattern, str, list[str]]] = [
    (re.compile(r"schmerz|zahnweh|\bweh\b|akut|notfall|dick[e]?\s+backe|geschwollen|entzünd|entzuend|pocht|eiter", re.I),
     "akute Beschwerden/Notfall", [r"akut", r"notfall", r"schmerz"]),
    (re.compile(r"wurzelbehandlung|wurzelkanal|wurzelentzünd|wurzelentzuend|\bwurzel\b|endodont|\bendo\b", re.I),
     "Wurzelbehandlung", [r"\bwk\b", r"endo\s+klein", r"wurzel", r"\bendo\b"]),
    # Kaputter Zahnersatz ist eine REPARATUR, keine ZE-Beratung: "meine
    # Prothese ist gebrochen" (Chef-Beispiel) -> Reparatur (klein), sonst ZE.
    (re.compile(r"reparatur|reparieren|(prothese|krone|brücke|bruecke|zahnersatz|gebiss|verblendung)[^.!?]{0,60}(gebrochen|abgebrochen|zerbrochen|kaputt|locker|gelöst|geloest|löst|loest|rausgefallen|herausgefallen)|(gebrochen|abgebrochen|kaputt)[^.!?]{0,40}(prothese|krone|brücke|bruecke|gebiss)", re.I),
     "Reparatur Zahnersatz", [r"ze\s+repar", r"repar", r"zahnersatz", r"\bze\b"]),
    (re.compile(r"zahnreinigung|reinigung|prophylaxe|\bpzr\b|zahnstein", re.I),
     "professionelle Zahnreinigung", [r"\bpzr\b", r"zahnreinigung", r"prophylaxe"]),
    (re.compile(r"aufhellung|bleaching|aufhellen|weißer|weisser", re.I),
     "Zahnaufhellung", [r"aufhellung", r"bleaching"]),
    (re.compile(r"implantat", re.I),
     "Implantat-Beratung", [r"imp\w*\s+besprechung", r"implantat\w*\s+(?:besprechung|beratung)", r"imp\w*\s+kontroll"]),
    # Invisalign VOR dem Schienen-Konzept: "Invisalign-Schienen" ist KFO,
    # nicht Schlafschiene (Baukasten-Test 29.08.2026). Parakeet hoert das
    # Markenwort oft ohne g ("Invisalin") oder als "Wissalein", und
    # "Aligner-Behandlung" kam als "Alleinerbehandlung" an (live 29.08.)
    # — alle realen Verhoerer tolerant matchen.
    (re.compile(r"invisali\w*|invizali\w*|inwisali\w*|wissal[ei]\w*|aligner"
                r"|alleinerbehandlung", re.I),
     "Invisalign-Beratung", [r"kfo\s+besprechung", r"kfo\s+kontroll", r"\bkfo\b", r"spange", r"kieferorthop"]),
    # Ueberweiser-Wissen (Chef 29.08.2026): Doktor Grüger und Doktor Lange
    # ueberweisen aus dem Schlaflabor fuer die Narval-Schiene. "lange" NUR
    # mit Titel davor — "ich warte schon lange" ist keine Ueberweisung.
    (re.compile(r"schnarch|schlafapnoe|apnoe|narval|knirsch|aufbiss|schiene"
                r"|schlaflabor|schlafklinik|gr(?:ü|ue)ger|(?:dr\.?|doktor)\s+lange\b", re.I),
     "Schiene/Schnarchen", [r"slm\s+besprechung", r"schien\w*\s+besprech", r"\bslm\b", r"schien", r"schnarch", r"narval", r"knirsch"]),
    (re.compile(r"zahnspange|spange|kieferorthop|\bkfo\b"
                r"|schief\w*[^.!?]{0,24}z(?:ä|ae)hn|z(?:ä|ae)hn\w*[^.!?]{0,24}(?:schief|gerade|richten|begradig|verschoben)", re.I),
     "Zahnspange/KFO", [r"kfo\s+besprechung", r"kfo\s+kontroll", r"\bkfo\b", r"spange", r"kieferorthop"]),
    (re.compile(r"erstuntersuchung|erstbesuch|neupatient", re.I),
     "Erstuntersuchung/Neupatient", [r"erstuntersuchung", r"neupatient", r"\berst"]),
    # Zahnersatz-WUNSCH (nichts kaputt): Krone/Brücke/Prothese geplant.
    (re.compile(r"krone|brücke|bruecke|prothese|zahnersatz|füllung\s+raus|inlay|veneer", re.I),
     "Zahnersatz-Beratung", [r"ze\s+besprechung", r"zahnersatz\w*\s+(?:besprechung|beratung)", r"prothetik", r"zahnersatz"]),
    (re.compile(r"abgebrochen|abgeplatzt|ecke\s+ab|stück\s+ab|stueck\s+ab", re.I),
     "akute Beschwerden/Notfall", [r"akut", r"notfall", r"repar"]),
    (re.compile(r"kontroll|vorsorge|check|routine|durchsicht|nachschauen|nachsehen|nachgucken|halbjahr|jahresuntersuchung", re.I),
     "Kontrolluntersuchung", [r"kch\s+kontroll", r"kontrolluntersuchung", r"kontroll", r"vorsorge", r"check"]),
]

# Chef 27.08.2026: "im Zweifelsfall Besprechungs- oder Kontrolltermine".
# "KCH Kontroll…" zuerst (Allgemein-Zahnheilkunde) — sonst gewann im grossen
# Katalog der KUERZESTE Kontroll-Name, und das war "VID OP Kontrolle" (Video).
FALLBACK_MUSTER = [r"kch\s+kontroll", r"kontrolluntersuchung", r"kontroll", r"besprechung"]

# Verneinte Erwaehnungen zaehlen nicht als Konzept-Treffer: "es ist NICHTS
# Akutes, nur die normale Kontrolle" lief sonst auf Notfall (Baukasten-Fund
# 29.08.2026). Die Phrase wird vor dem Matching entfernt — der Rest des
# Satzes ("normale Kontrolle") traegt die echte Aussage.
_VERNEINT_RE = re.compile(
    r"(nichts|nix|nicht|kein\w*)\s+(akut\w*|notfall\w*|schlimm\w*|dringend\w*)",
    re.I,
)


def _ohne_verneintes(text: str) -> str:
    return _VERNEINT_RE.sub(" ", text or "")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def motiv_suchen(tenant: dict, muster: list[str], *, katalog: list[dict] | None = None,
                 calendar_id: str = "") -> dict | None:
    """Bestes Motiv aus dem Katalog (Default: tenant.visitMotives) für die Muster.

    Erstes Muster mit Treffern gewinnt; unter mehreren Treffern gewinnt
    "klein" im Namen (Chef: "immer klein buchen"), danach der kürzeste Name.
    Mit calendar_id werden NUR Motive des Ziel-Behandlers betrachtet
    (visitMotive.calendarIds; leer = überall — Chef 30.08.2026: das Mapping
    ist behandlerspezifisch und passiert in jedem Anruf frisch).
    """
    if katalog is None:
        katalog = tenant.get("visitMotives") if isinstance(tenant.get("visitMotives"), list) else []
    vms = motive.fuer_kalender(katalog, calendar_id)

    def _suche(pool: list[dict]) -> dict | None:
        for m in muster:
            cre = re.compile(m, re.I)
            treffer = [v for v in pool if cre.search(_s(v.get("name")))]
            if not treffer:
                continue
            kleine = [v for v in treffer if "klein" in _s(v.get("name")).lower()]
            return min(kleine or treffer, key=lambda v: len(_s(v.get("name"))))
        return None

    # Online-buchbare Motive zuerst: interne Termine (Labor, Video,
    # Teambesprechung) stehen im Katalog, gehoeren aber nicht ans Telefon.
    # Findet sich dort nichts, gilt der volle Pool (nie leer laufen).
    buchbar = [v for v in vms if v.get("allowOnlineBooking") is not False]
    if len(buchbar) < len(vms):
        return _suche(buchbar) or _suche(vms)
    return _suche(vms)


def deute(tenant: dict, text: str, *, katalog: list[dict] | None = None,
          calendar_id: str = "") -> tuple[str, dict | None]:
    """(sprechbarer Kern, Motiv aus der Behandler-Liste) — ("", None) wenn nichts passt.

    Wird ein Konzept erkannt, dessen Motiv der Behandler nicht führt, fällt
    die Buchung auf Kontrolle/Besprechung zurück — der Kern bleibt trotzdem
    der erkannte (für Rückfrage und Notiz-Wortlaut).
    """
    text = _ohne_verneintes(text)
    for cre, kern, muster in KONZEPTE:
        if cre.search(text):
            vm = (motiv_suchen(tenant, muster, katalog=katalog, calendar_id=calendar_id)
                  or motiv_suchen(tenant, FALLBACK_MUSTER, katalog=katalog, calendar_id=calendar_id))
            return kern, vm
    # W-MOTIV-KATALOG (03.09.2026): kein kuratiertes Konzept — den Grund
    # generisch gegen den frischen Katalog mappen (Namen + Erklärtexte).
    # So treffen auch kundeneigene Besuchsgründe ("Füllung", "Botox").
    kat = katalog
    if kat is None:
        kat = tenant.get("visitMotives") if isinstance(tenant.get("visitMotives"), list) else []
    vm = katalog_treffer(text, katalog=kat, calendar_id=calendar_id)
    if vm is not None:
        return sprechname(vm), vm
    return "", None


def fallback_motiv(tenant: dict, *, katalog: list[dict] | None = None,
                   calendar_id: str = "") -> dict | None:
    """Für frei formulierte Gründe ohne erkennbares Konzept ("Holzbein absägen")."""
    return motiv_suchen(tenant, FALLBACK_MUSTER, katalog=katalog, calendar_id=calendar_id)


# =============================================================================
# W-MOTIV-KATALOG (Chef 03.09.2026): "bianca muss den besuchsgrund besser
# mappen lernen auf die realen besuchsgründe in der Praxis. die besuchsgründe
# müssen auf jeden fall parat stehen in einem RAG oder ähnlichem, weil viele
# user eigene besuchsgründe editieren oder erstellen."
#
# Der Katalog steht pro Anruf frisch in der Sitzung (kern/motive.anstossen —
# das IST unser "RAG": parat, ohne Netz-Roundtrip pro Zug). Diese Stufe mappt
# den gesprochenen Grund GENERISCH gegen Namen UND Erklärtexte der Motive
# (patientInfo von der Einstellungsseite, Landingpage-Headline/-Beschreibung —
# masVisitMotives liefert sie seit 03.09.2026 mit). Sie greift NACH den
# kuratierten KONZEPTEN und VOR dem Kontrolle-Fallback — so funktionieren
# auch kundeneigene Gründe ("Füllung", "Funktionsanalyse", "Botox-Beratung"),
# die kein Zahnarzt-Konzept kennt. Klein/gross-Regel gilt auch hier.
# =============================================================================

# Füllwörter des Anrufersatzes und der Erklärtexte — tragen keine Bedeutung.
_MATCH_STOP = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "einer", "ich", "wir", "sie", "ihr", "mir", "mich", "uns", "mein", "meine",
    "meinen", "meinem", "meiner", "und", "oder", "aber", "auch", "noch", "mal",
    "bitte", "gern", "gerne", "danke", "hallo", "guten", "tag", "morgen",
    "termin", "terminwunsch", "brauche", "braeuchte", "haette", "moechte",
    "will", "wollte", "wuerde", "koennte", "kann", "muss", "soll", "lassen",
    "machen", "kommen", "vorbeikommen", "haben", "sein", "ist", "sind", "war",
    "waren", "wird", "werden", "fuer", "wegen", "zum", "zur", "bei", "beim",
    "mit", "ohne", "auf", "aus", "nach", "vor", "ueber", "unter", "von", "als",
    "wie", "was", "wann", "ganz", "sehr", "schon", "wieder", "neu", "neue",
    "neuen", "ihnen", "ihre", "ihren", "praxis", "zahnarzt", "arzt", "doktor",
    "frau", "herr", "uhr", "woche", "diese", "dieser", "dieses", "denn",
    "dann", "dass", "nicht", "kein", "keine", "etwas", "gemacht", "gehabt",
    # Groessen-Marker entscheiden NIE das Matching — nur die Klein-Regel am
    # Ende ("bei xy klein oder xy gross nehmen wir grundsaetzlich klein").
    "klein", "kleine", "kleinen", "kleiner", "kleines",
    "gross", "grosse", "grossen", "grosser", "grosses",
    # Allerweltsverben aus Anrufersaetzen ("stellen Sie Taxischeine aus?").
    "stellen", "stelle", "stellt", "geben", "gibt", "geht", "gehen",
}


def _match_norm(text: str) -> str:
    t = html.unescape(_s(text)).lower()
    t = (t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
          .replace("ß", "ss"))
    return re.sub(r"[^a-z0-9]+", " ", t)


def _match_tokens(text: str) -> set[str]:
    return {w for w in _match_norm(text).split()
            if len(w) >= 3 and w not in _MATCH_STOP and not w.isdigit()}


def _stamm(w: str) -> str:
    """Deutsche Endungen light strippen: reparieren/Reparatur -> repar."""
    for suf in ("ierung", "ieren", "ungen", "ung", "atur", "en", "e", "n"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: len(w) - len(suf)]
    return w


def _token_passt(a: str, b: str) -> bool:
    """Wortstamm-tolerant: 'reparieren' trifft 'Reparatur', 'Kontrolle'
    trifft 'Kontrolluntersuchung' — aber 'zahn' (zu kurz) trifft nichts."""
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and (a in b or b in a):
        return True
    sa, sb = _stamm(a), _stamm(b)
    if sa == sb:
        return True
    # Stamm-Vergleich NUR als Praefix-Beziehung ("versiegel"/"versiegelung"),
    # nie mitten im Wort — sonst traf "stellen" die "Planerstellung"
    # (Taxi-Abschweifer, Baukasten 03.09.2026).
    if len(sa) >= 5 and len(sb) >= 5 and (sa.startswith(sb) or sb.startswith(sa)):
        return True
    # Gemeinsamer Praefix >= 6: deutsche Flexion/Komposita.
    p = 0
    for x, y in zip(a, b):
        if x != y:
            break
        p += 1
    return p >= 6


def katalog_treffer(text: str, *, katalog: list[dict],
                    calendar_id: str = "") -> dict | None:
    """Bestes Motiv fuer den gesprochenen Grund — ueber Namen UND Erklärtexte.

    Score je Motiv: Treffer im Namen (name/nameForPatient) zaehlen 3, Treffer
    in den Erklärtexten (patientInfo, Landingpage) zaehlen 1. Unter 3 Punkten
    kein Treffer (mindestens EIN Namens-Treffer oder drei Text-Indizien).
    Unter den Besten: "klein" schlaegt "gross" (Chef: immer klein buchen),
    online-buchbare vor internen, dann der kuerzeste Name.
    """
    worte = _match_tokens(text)
    if not worte:
        return None
    pool = motive.fuer_kalender(katalog or [], calendar_id)
    beste: list[tuple[int, dict]] = []
    top = 0
    for vm in pool:
        name_toks = _match_tokens(f"{vm.get('name')} {vm.get('nameForPatient')}")
        text_toks = _match_tokens(
            f"{vm.get('patientInfo')} {vm.get('landingPageHeadline')} "
            f"{vm.get('landingPageDescription')}"
        ) - name_toks
        score = 0
        for w in worte:
            if any(_token_passt(w, n) for n in name_toks):
                score += 3
            elif any(_token_passt(w, x) for x in text_toks):
                score += 1
        if score > top:
            beste = [(score, vm)]
            top = score
        elif score == top and score > 0:
            beste.append((score, vm))
    if top < 3:
        return None
    kandidaten = [vm for _, vm in beste]
    buchbar = [v for v in kandidaten if v.get("allowOnlineBooking") is not False]
    if buchbar:
        kandidaten = buchbar
    kleine = [v for v in kandidaten if "klein" in _s(v.get("name")).lower()]
    return min(kleine or kandidaten, key=lambda v: len(_s(v.get("name"))))


def deckt_ab(motiv_text: str, o_ton: str) -> bool:
    """True, wenn ALLE bedeutenden O-Ton-Worte im Motiv-/Grundtext aufgehen.

    Fuer die Kurznotiz am Termin (Chef 03.09.2026: "entsprechende
    kurznotizen bitte nicht vergessen"): deckt der gebuchte Besuchsgrund
    den Wortlaut nicht ab, bekommt die Praxis den O-Ton ans Terminpopup."""
    wl = _match_tokens(o_ton)
    nm = _match_tokens(motiv_text)
    return bool(wl) and all(any(_token_passt(w, n) for n in nm) for w in wl)


def sprechname(vm: dict) -> str:
    """Sprechbarer Kern eines Motivs: Patientenname vor internem Kuerzel-Namen."""
    schoen = _s(vm.get("nameForPatient"))
    if schoen:
        return schoen
    name = _s(vm.get("name"))
    # Interne Kuerzel-Praefixe ("KCH ", "PRO ", "SLM ") nicht mit ansagen.
    return re.sub(r"^[A-ZÄÖÜ]{2,4}\s+", "", name) or name


def konzept_muster(text: str) -> list[str]:
    """Motiv-Muster des erkannten Konzepts — [] wenn keines passt.

    Für die behandlerspezifische NEU-Auflösung beim Kontext-Bau: derselbe
    gesprochene Grund, aber gegen den Katalog des ZIEL-Kalenders gesucht."""
    text = _ohne_verneintes(text)
    for cre, _kern, muster in KONZEPTE:
        if cre.search(text):
            return muster
    return []
