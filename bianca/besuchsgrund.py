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
    # Pourianmehr 08.09.2026: „Zahnschienen abholen“ ist KEINE Erstberatung
    # und kein Scan — die Schiene liegt fertig, gebucht wird Eingliederung.
    # Steht VOR dem allgemeinen Schienen-Konzept, sonst gewinnt Besprechung.
    (re.compile(
        r"(?:zahn)?schien\w*.{0,48}abhol|abhol\w*.{0,48}(?:zahn)?schien|"
        r"narval.{0,32}abhol|abhol\w*.{0,32}narval|"
        r"schnarchschien\w*.{0,32}abhol|schlaf\s*schien\w*.{0,32}abhol",
        re.I,
     ),
     "Schiene abholen / Eingliederung",
     [r"slm\s+einglieder", r"einglieder\w*.{0,28}(narval|schien)",
      r"(narval|schien)\w*.{0,28}einglieder", r"narval",
      r"slm\s+besprechung", r"\bslm\b"]),
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
    # "Zahnarztbesprechung" ist der STT-Verhörer von "Zahnersatzbesprechung"
    # (Thaler 08.09.2026).
    (re.compile(
        r"krone|brücke|bruecke|prothese|zahnersatz|zahnarztbesprech|"
        r"füllung\s+raus|inlay|veneer",
        re.I,
     ),
     "Zahnersatz-Beratung", [r"ze\s+besprechung", r"ze\s+beratung",
                             r"zahnersatz\w*\s+(?:besprechung|beratung)",
                             r"prothetik", r"zahnersatz"]),
    (re.compile(r"abgebrochen|abgeplatzt|ecke\s+ab|stück\s+ab|stueck\s+ab", re.I),
     "akute Beschwerden/Notfall", [r"akut", r"notfall", r"repar"]),
    (re.compile(r"kontroll|vorsorge|check|routine|durchsicht|nachschauen|nachsehen|nachgucken|halbjahr|jahresuntersuchung", re.I),
     "Kontrolluntersuchung", [r"kch\s+kontroll", r"kontrolluntersuchung", r"kontroll", r"vorsorge", r"check"]),
]

# Nur bei Zahn-Katalog. Kontrolle/Erst/Akut bleiben fachneutral.
_DENTAL_KERNE = {
    "Wurzelbehandlung",
    "Reparatur Zahnersatz",
    "professionelle Zahnreinigung",
    "Zahnaufhellung",
    "Implantat-Beratung",
    "Invisalign-Beratung",
    "Schiene abholen / Eingliederung",
    "Schiene/Schnarchen",
    "Zahnspange/KFO",
    "Zahnersatz-Beratung",
}
_DENTAL_WUNSCH_RE = re.compile(
    r"\bzahn\w*|\bkiefer\w*|\bimplantat\w*|\bkrone\w*|\bbrücke\w*|"
    r"\bbruecke\w*|\bprothese\w*|\binvisali\w*|\baligner\w*|"
    r"\bschiene\w*|\bpzr\b|\bprophylaxe\b|\bbleach\w*|"
    r"\baufhellung\b|\bwurzel(?:behandlung|kanal)?\b",
    re.I,
)
_DENTAL_VERNEINT_RE = re.compile(
    r"\b(?:nicht|kein\w*|ohne)\s+(?:(?:zum|zur|beim)\s+)?"
    r"(?:(?:professionelle|neue)\s+)?"
    r"(?:zahn\w*|kiefer\w*|implantat\w*|krone\w*|brücke\w*|bruecke\w*|"
    r"prothese\w*|invisali\w*|aligner\w*|schiene\w*|pzr|prophylaxe|"
    r"bleach\w*|aufhellung|wurzel(?:behandlung|kanal)?)\b",
    re.I,
)

# Chef 27.08.2026: "im Zweifelsfall Besprechungs- oder Kontrolltermine".
# "KCH Kontroll…" zuerst (Allgemein-Zahnheilkunde) — sonst gewann im grossen
# Katalog der KUERZESTE Kontroll-Name, und das war "VID OP Kontrolle" (Video).
FALLBACK_MUSTER = [r"kch\s+kontroll", r"kontrolluntersuchung", r"kontroll", r"besprechung"]

# Verneinte Erwaehnungen zaehlen nicht als Konzept-Treffer: "es ist NICHTS
# Akutes, nur die normale Kontrolle" lief sonst auf Notfall (Baukasten-Fund
# 29.08.2026). Die Phrase wird vor dem Matching entfernt — der Rest des
# Satzes ("normale Kontrolle") traegt die echte Aussage.
_VERNEINT_RE = re.compile(
    r"(nichts|nix|nicht|kein\w*)\s+"
    r"(akut\w*|notfall\w*|schlimm\w*|dringend\w*)"
    r"(?:\s+beschwerden)?",
    re.I,
)
_AKUT_WORT_RE = re.compile(
    r"schmerz|zahnweh|\bweh\b|akut|notfall|dick[e]?\s+backe|geschwollen|"
    r"entzünd|entzuend|pocht|eiter|abgebrochen|abgeplatzt",
    re.I,
)

# W-BLESSING-MOTIVKLARHEIT (15.09.2026): Im allgemeinen Zahn-Konzept steht
# historisch ``eiter`` ohne Wortgrenze. Dadurch wurden ausgerechnet
# „WEITERbehandlung“ und „WEITERE Medikamentenkontrolle“ zum Notfall-Motiv.
# Der engere Dermatologiepfad ist bewusst Tenant-Opt-in: andere Praxen
# behalten bis zu einem eigenen Arbeitspaket ihr bisheriges Mapping.
_DERMA_AKUT_RE = re.compile(
    r"\bakut\w*|\bnotfall\w*|\bschmerz\w*|\bweh\b|"
    r"\bblut(?:et|en|end|ung|ig)\w*|"
    r"\bgeschwollen\w*|\bentz(?:ü|ue)nd\w*|\beiter\w*|\beitrig\w*",
    re.I,
)
_DERMA_FOLGE_RE = re.compile(
    r"\bweiter(?:e|er|es|en)?\s*(?:behand\w*|medikament\w*\s*kontroll\w*)|"
    r"\bweiterbehand\w*|\bmedikament\w*\s*kontroll\w*|"
    r"\bnachkontroll\w*|\bnachsorge\w*",
    re.I,
)
_DERMA_BESCHWERDE_RE = re.compile(
    r"\bhautproblem\w*|\bhautbeschwerd\w*|\bausschlag\w*|\bjuck\w*|"
    r"\bwund\w*|\bn(?:ä|ae)gel\w*|\bnagel\w*|"
    r"\bf(?:u(?:ß|ss)|ue(?:ß|ss))\w*|"
    r"\bkopfhaut\w*|\bpustel\w*|\bpickel\w*|\bwarze\w*|\bfleck\w*|"
    r"\br(?:ö|oe)t\w*|\bschupp\w*|\bbl(?:ä|ae)s\w*",
    re.I,
)
_DERMA_KONZEPTE: list[tuple[re.Pattern, str, list[str]]] = [
    (
        re.compile(r"\bneurodermit\w*", re.I),
        "Neurodermitis",
        [r"^neurodermitis$"],
    ),
    (
        re.compile(r"\brosacea\w*|\bakne\w*|\bekzem\w*", re.I),
        "Akne / Rosacea / Ekzeme",
        [r"akne.*rosacea.*ekzem", r"rosacea", r"akne", r"ekzem"],
    ),
    (
        re.compile(r"\ballerg\w*", re.I),
        "Beratung Allergie",
        [r"beratung.*allerg", r"allerg"],
    ),
    (
        re.compile(r"\bbotox\w*|\bfiller\w*", re.I),
        "Beratung Botox / Filler",
        [r"beratung.*botox.*filler", r"botox", r"filler"],
    ),
    (
        re.compile(r"\bkosmetik\w*|\bfruchts(?:ä|ae)ure\w*|\bfußpflege\w*|"
                   r"\bfusspflege\w*", re.I),
        "Beratung Kosmetik",
        [r"beratung.*kosmetik", r"kosmetik", r"fruchts", r"fußpflege", r"fusspflege"],
    ),
    (
        re.compile(r"\bvene\w*|\bsklerotherap\w*", re.I),
        "Venensprechstunde",
        [r"venensprechstunde", r"vene", r"sklerotherap"],
    ),
    (
        re.compile(r"\bnagelpilz\w*", re.I),
        "Nagelpilz",
        [r"^nagelpilz$"],
    ),
    (
        re.compile(r"\bhautkrebs\w*|\bscreening\w*", re.I),
        "Hautkrebs-Screening",
        [r"hautkrebs.*screening", r"hautkrebs", r"screening"],
    ),
    (
        re.compile(
            r"\ba(?:t|tt|th)erom\w*|\bgr(?:ü|ue)tzbeutel\w*|"
            r"\bhautver(?:ä|ae)nder\w*|"
            r"\b(?:pustel|muttermal)\w*[^.!?]{0,28}\bentfern\w*",
            re.I,
        ),
        "Beratung Entfernung einer Hautveränderung",
        [r"beratung.*entfernung.*hautver", r"entfernung.*hautver"],
    ),
]
_BERATUNG_PUR_RE = re.compile(
    r"^\s*(?:(?:(?:ich\s+)?(?:m(?:ö|oe)chte|h(?:ä|ae)tte|brauche|will)"
    r"(?:\s+gern(?:e)?)?|(?:das\s+)?w(?:ä|ae)re|"
    r"es\s+geht\s+um|dann)\s+)?(?:(?:eine|die)\s+)?"
    r"beratung(?:\s+bitte)?[\s.!?]*$",
    re.I,
)
_ETWAS_ANDERES_PUR_RE = re.compile(
    r"^\s*(?:(?:dann|es\s+ist|ich\s+habe)\s+)?"
    r"(?:(?:et|irgend)?was|was)\s+ander(?:e|es|en)[\s.!?]*$",
    re.I,
)
_BERATUNG_LABELS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"allerg", re.I), "Allergie"),
    (re.compile(r"kosmetik|fruchts|fußpflege|fusspflege", re.I), "Kosmetik"),
    (re.compile(r"botox|filler", re.I), "Botox/Filler"),
    (re.compile(r"entfernung.*hautver", re.I), "eine störende Hautveränderung"),
]


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


def grund_klaerungsfrage(
    tenant: dict,
    text: str,
    *,
    katalog: list[dict] | None = None,
    calendar_id: str = "",
) -> str:
    """Offene Blessing-Menüoption konkretisieren, niemals als Leistung ablehnen."""
    if tenant.get("dermaMotivKlarheit") is not True:
        return ""
    if _ETWAS_ANDERES_PUR_RE.match(text or ""):
        return "Gern. Was genau soll sich die Ärztin ansehen?"
    if not _BERATUNG_PUR_RE.match(text or ""):
        return ""

    kat = katalog
    if kat is None:
        kat = tenant.get("visitMotives") if isinstance(
            tenant.get("visitMotives"), list) else []
    namen = " ".join(
        _s(vm.get("name"))
        for vm in motive.fuer_kalender(kat or [], calendar_id)
        if vm.get("allowOnlineBooking") is not False
        and re.search(r"\bberatung\b", _s(vm.get("name")), re.I)
    )
    optionen = [label for muster, label in _BERATUNG_LABELS if muster.search(namen)]
    if not optionen:
        return "Gern. Worum geht es bei der Beratung genau?"
    if len(optionen) == 1:
        auswahl = optionen[0]
    else:
        auswahl = ", ".join(optionen[:-1]) + " oder " + optionen[-1]
    return f"Gern. Welche Beratung ist gemeint: {auswahl}?"


def _derma_deute(
    tenant: dict,
    text: str,
    *,
    katalog: list[dict],
    calendar_id: str = "",
) -> tuple[str, dict | None] | None:
    """Blessing-Opt-in: echte Dermatologiegründe vor dem alten Dental-Muster."""
    if tenant.get("dermaMotivKlarheit") is not True:
        return None
    bereinigt = _ohne_verneintes(text)
    if _DENTAL_WUNSCH_RE.search(_DENTAL_VERNEINT_RE.sub(" ", bereinigt)):
        return None
    if _DERMA_AKUT_RE.search(bereinigt):
        vm = motiv_suchen(
            tenant,
            [r"notfall.*akute.*beschwerden", r"akute.*beschwerden", r"notfall"],
            katalog=katalog,
            calendar_id=calendar_id,
        )
        return ("akute Beschwerden/Notfall", vm) if vm else None

    for cre, kern, muster in _DERMA_KONZEPTE:
        if cre.search(bereinigt):
            vm = motiv_suchen(
                tenant,
                muster,
                katalog=katalog,
                calendar_id=calendar_id,
            )
            return (kern, vm) if vm else None

    if _DERMA_FOLGE_RE.search(bereinigt):
        vm = motiv_suchen(
            tenant,
            [r"^kontrolle$", r"^kontrolluntersuchung$"],
            katalog=katalog,
            calendar_id=calendar_id,
        )
        return ("Kontrolle", vm) if vm else None

    if _DERMA_BESCHWERDE_RE.search(bereinigt):
        vm = motiv_suchen(
            tenant,
            [r"^sprechstunde$"],
            katalog=katalog,
            calendar_id=calendar_id,
        )
        return ("Sprechstunde", vm) if vm else None
    return None


# Hoerfehler, die NUR in einer Zahnarztpraxis eindeutig sind (Chef 13.09.2026
# zum Anruf 1fbda5db: "ich weiss nicht ob sie im kalender auf kieferorthopaedie
# gemappt haette"). Live kam "Ich habe schiefe ZEHEN, ich moechte die gerade
# haben" aus dem STT — kein Katalogwort passte und der Termin lief auf
# Kontrolle statt "KFO Besprechung". Eine Zahnarztpraxis behandelt keine Zehen.
# Nur fuer die MAPPING-Sicht: der gesprochene Wortlaut bleibt unveraendert im
# Sammler und in der Termin-Notiz (die Praxis liest also weiter, was der
# Anrufer wirklich gesagt hat).
_ZAHN_HOERFEHLER = (
    (re.compile(r"\bzehen\b", re.I), "Zähne"),
    (re.compile(r"\bzehe\b", re.I), "Zahn"),
    (re.compile(r"\bzeh\b", re.I), "Zahn"),
)


def _zahn_hoerfehler(text: str) -> str:
    for cre, ersatz in _ZAHN_HOERFEHLER:
        text = cre.sub(ersatz, text)
    return text


def deute(tenant: dict, text: str, *, katalog: list[dict] | None = None,
          calendar_id: str = "") -> tuple[str, dict | None]:
    """(sprechbarer Kern, Motiv aus der Behandler-Liste) — ("", None) wenn nichts passt.

    Wird ein Konzept erkannt, dessen Motiv der Behandler nicht führt, fällt
    die Buchung auf Kontrolle/Besprechung zurück — der Kern bleibt trotzdem
    der erkannte (für Rückfrage und Notiz-Wortlaut).
    """
    text = _ohne_verneintes(text)
    kat = katalog
    if kat is None:
        kat = tenant.get("visitMotives") if isinstance(tenant.get("visitMotives"), list) else []
    from kern import zimmer_map
    if zimmer_map.klar_nicht_buchbar(tenant, text):
        return "", None
    zahn = motive.ist_zahn(kat)
    if zahn:
        text = _zahn_hoerfehler(text)
    # Praxis-Kataloge dürfen sich nicht gegenseitig überlagern. Exakter
    # Katalogname gewinnt vor Zahnarzt-Konzepten und vor generischen Wörtern
    # wie "Sprechstunde" oder "Kontrolle".
    vm = katalog_exakt(text, katalog=kat, calendar_id=calendar_id)
    if vm is not None:
        return sprechname(vm), vm
    derma = _derma_deute(
        tenant,
        text,
        katalog=kat,
        calendar_id=calendar_id,
    )
    if derma is not None:
        return derma
    for cre, kern, muster in KONZEPTE:
        if not cre.search(text):
            continue
        if kern in _DENTAL_KERNE and not zahn:
            continue
        vm = (motiv_suchen(tenant, muster, katalog=katalog, calendar_id=calendar_id)
              or motiv_suchen(tenant, FALLBACK_MUSTER, katalog=katalog, calendar_id=calendar_id))
        return kern, vm
    # W-MOTIV-KATALOG (03.09.2026): kein kuratiertes Konzept — den Grund
    # generisch gegen den frischen Katalog mappen (Namen + Erklärtexte).
    # So treffen auch kundeneigene Besuchsgründe ("Füllung", "Botox").
    vm = katalog_treffer(text, katalog=kat, calendar_id=calendar_id)
    if vm is not None:
        return sprechname(vm), vm
    return "", None


def fachfremder_zahngrund(tenant: dict, text: str,
                          *, katalog: list[dict] | None = None) -> bool:
    """Zahnwunsch in einem nachweislich nicht-zahnärztlichen Katalog."""
    kat = katalog
    if kat is None:
        kat = tenant.get("visitMotives") if isinstance(
            tenant.get("visitMotives"), list) else []
    bereinigt = _DENTAL_VERNEINT_RE.sub(" ", _ohne_verneintes(text))
    return bool(
        kat and not motive.ist_zahn(kat)
        and _DENTAL_WUNSCH_RE.search(bereinigt)
    )


def fallback_motiv(tenant: dict, *, katalog: list[dict] | None = None,
                   calendar_id: str = "") -> dict | None:
    """Für frei formulierte Gründe ohne erkennbares Konzept ("Holzbein absägen")."""
    from kern.tenants import ist_akut_motiv
    vm = motiv_suchen(tenant, FALLBACK_MUSTER, katalog=katalog, calendar_id=calendar_id)
    if vm and ist_akut_motiv(vm):
        return None
    return vm


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


_GENERIC_MOTIV_TOKENS = {
    "beratung", "behandlung", "beschwerden", "kontrolle",
    "kontrolluntersuchung", "sprechstunde", "termin", "untersuchung",
}


def katalog_exakt(text: str, *, katalog: list[dict],
                  calendar_id: str = "") -> dict | None:
    """Exakter Motivname vor Fuzzy-Mapping; spezifisch schlägt generisch."""
    roh = _match_norm(_ohne_verneintes(text))
    kompakt = roh.replace(" ", "")
    if not roh:
        return None
    treffer: list[tuple[int, int, dict]] = []
    for vm in motive.fuer_kalender(katalog or [], calendar_id):
        for wert in (vm.get("nameForPatient"), vm.get("name")):
            name = _match_norm(_s(wert))
            if not name:
                continue
            toks = [w for w in name.split() if len(w) >= 3]
            nur_generisch = bool(toks) and all(
                w in _GENERIC_MOTIV_TOKENS for w in toks)
            rang = 0
            if roh == name or kompakt == name.replace(" ", ""):
                rang = 4
            elif not nur_generisch and re.search(
                    rf"(?<!\w){re.escape(name)}(?!\w)", roh):
                rang = 3
            elif (
                not nur_generisch
                and set(roh.split()).issubset(set(name.split()))
                and not any(w in _GENERIC_MOTIV_TOKENS for w in roh.split())
            ):
                rang = 2
            if rang:
                treffer.append((rang, len(name), vm))
    if not treffer:
        return None
    top = max(x[0] for x in treffer)
    kandidaten = [(laenge, vm) for rang, laenge, vm in treffer if rang == top]
    buchbar = [x for x in kandidaten if x[1].get("allowOnlineBooking") is not False]
    return min(buchbar or kandidaten, key=lambda x: x[0])[1]


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
    roh = _ohne_verneintes(text)
    if motive.ist_zahn(katalog or []):
        roh = _zahn_hoerfehler(roh)
    worte = _match_tokens(roh)
    if not worte:
        return None
    from kern.tenants import ist_akut_motiv
    pool = motive.fuer_kalender(katalog or [], calendar_id)
    # Notfall nur, wenn der Anrufer Schmerz/Akut/Notfall gesagt hat —
    # sonst gewann bei Blessing/Thaler das erste Akut-Motiv über ein
    # einzelnes Restwort ("Beschwerden") nach "keine akuten …".
    if not _AKUT_WORT_RE.search(roh or ""):
        pool = [v for v in pool if not ist_akut_motiv(v)]
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
            if w in name_toks:
                score += 2 if w in _GENERIC_MOTIV_TOKENS else 5
            elif any(_token_passt(w, n) for n in name_toks):
                score += 1 if w in _GENERIC_MOTIV_TOKENS else 3
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


_SCHIENE_ABHOL_RE = re.compile(
    r"(?:zahn)?schien\w*.{0,48}abhol|abhol\w*.{0,48}(?:zahn)?schien|"
    r"narval.{0,32}abhol|abhol\w*.{0,32}narval|"
    r"schnarchschien\w*.{0,32}abhol|schlaf\s*schien\w*.{0,32}abhol",
    re.I,
)


def ist_schiene_abholen(text: str) -> bool:
    """Fertige Schiene abholen — Eingliederung, kein Scan, kein Durchstellen."""
    return bool(_SCHIENE_ABHOL_RE.search(_s(text)))


def konzept_muster(text: str) -> list[str]:
    """Motiv-Muster des erkannten Konzepts — [] wenn keines passt.

    Für die behandlerspezifische NEU-Auflösung beim Kontext-Bau: derselbe
    gesprochene Grund, aber gegen den Katalog des ZIEL-Kalenders gesucht."""
    text = _ohne_verneintes(text)
    for cre, _kern, muster in KONZEPTE:
        if cre.search(text):
            return muster
    return []
