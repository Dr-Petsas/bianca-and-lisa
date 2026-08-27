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

import re
from typing import Any

# (Erkennungs-Muster im Patientensatz, sprechbarer Kern, Motiv-Muster nach Priorität)
KONZEPTE: list[tuple[re.Pattern, str, list[str]]] = [
    (re.compile(r"schmerz|zahnweh|\bweh\b|akut|notfall|dick[e]?\s+backe|geschwollen|entzünd|entzuend|pocht|eiter", re.I),
     "akute Beschwerden/Notfall", [r"akut", r"notfall", r"schmerz"]),
    (re.compile(r"wurzelbehandlung|wurzelkanal|wurzelentzünd|wurzelentzuend|\bwurzel\b|endodont|\bendo\b", re.I),
     "Wurzelbehandlung", [r"\bwk\b", r"wurzel", r"endo"]),
    # Kaputter Zahnersatz ist eine REPARATUR, keine ZE-Beratung: "meine
    # Prothese ist gebrochen" (Chef-Beispiel) -> Reparatur (klein), sonst ZE.
    (re.compile(r"reparatur|reparieren|(prothese|krone|brücke|bruecke|zahnersatz|gebiss|verblendung)[^.!?]{0,60}(gebrochen|abgebrochen|zerbrochen|kaputt|locker|gelöst|geloest|löst|loest|rausgefallen|herausgefallen)|(gebrochen|abgebrochen|kaputt)[^.!?]{0,40}(prothese|krone|brücke|bruecke|gebiss)", re.I),
     "Reparatur Zahnersatz", [r"repar", r"zahnersatz", r"\bze\b"]),
    (re.compile(r"zahnreinigung|reinigung|prophylaxe|\bpzr\b|zahnstein", re.I),
     "professionelle Zahnreinigung", [r"\bpzr\b", r"zahnreinigung", r"prophylaxe"]),
    (re.compile(r"aufhellung|bleaching|aufhellen|weißer|weisser", re.I),
     "Zahnaufhellung", [r"aufhellung", r"bleaching"]),
    (re.compile(r"implantat", re.I),
     "Implantat-Beratung", [r"implantat", r"\bimp\b"]),
    (re.compile(r"schnarch|schlafapnoe|apnoe|narval|knirsch|aufbiss|schiene", re.I),
     "Schiene/Schnarchen", [r"\bslm\b", r"schien", r"schnarch", r"narval", r"knirsch"]),
    (re.compile(r"zahnspange|spange|kieferorthop|\bkfo\b", re.I),
     "Zahnspange/KFO", [r"\bkfo\b", r"spange", r"kieferorthop"]),
    (re.compile(r"erstuntersuchung|erstbesuch|neupatient", re.I),
     "Erstuntersuchung/Neupatient", [r"erstuntersuchung", r"neupatient", r"\berst"]),
    # Zahnersatz-WUNSCH (nichts kaputt): Krone/Brücke/Prothese geplant.
    (re.compile(r"krone|brücke|bruecke|prothese|zahnersatz|füllung\s+raus|inlay|veneer", re.I),
     "Zahnersatz-Beratung", [r"zahnersatz", r"\bze\b", r"prothetik"]),
    (re.compile(r"abgebrochen|abgeplatzt|ecke\s+ab|stück\s+ab|stueck\s+ab", re.I),
     "akute Beschwerden/Notfall", [r"akut", r"notfall", r"repar"]),
    (re.compile(r"kontroll|vorsorge|check|routine|durchsicht|nachschauen|halbjahr|jahresuntersuchung", re.I),
     "Kontrolluntersuchung", [r"kontroll", r"vorsorge", r"check"]),
]

# Chef 27.08.2026: "im Zweifelsfall Besprechungs- oder Kontrolltermine".
FALLBACK_MUSTER = [r"kontroll", r"besprechung"]


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def motiv_suchen(tenant: dict, muster: list[str]) -> dict | None:
    """Bestes Motiv aus tenant.visitMotives für die Muster-Liste.

    Erstes Muster mit Treffern gewinnt; unter mehreren Treffern gewinnt
    "klein" im Namen (Chef: "immer klein buchen"), danach der kürzeste Name.
    """
    vms = tenant.get("visitMotives") if isinstance(tenant.get("visitMotives"), list) else []
    for m in muster:
        cre = re.compile(m, re.I)
        treffer = [v for v in vms if cre.search(_s(v.get("name")))]
        if not treffer:
            continue
        kleine = [v for v in treffer if "klein" in _s(v.get("name")).lower()]
        pool = kleine or treffer
        return min(pool, key=lambda v: len(_s(v.get("name"))))
    return None


def deute(tenant: dict, text: str) -> tuple[str, dict | None]:
    """(sprechbarer Kern, Motiv aus der Behandler-Liste) — ("", None) wenn nichts passt.

    Wird ein Konzept erkannt, dessen Motiv der Behandler nicht führt, fällt
    die Buchung auf Kontrolle/Besprechung zurück — der Kern bleibt trotzdem
    der erkannte (für Rückfrage und Notiz-Wortlaut).
    """
    for cre, kern, muster in KONZEPTE:
        if cre.search(text):
            vm = motiv_suchen(tenant, muster) or motiv_suchen(tenant, FALLBACK_MUSTER)
            return kern, vm
    return "", None


def fallback_motiv(tenant: dict) -> dict | None:
    """Für frei formulierte Gründe ohne erkennbares Konzept ("Holzbein absägen")."""
    return motiv_suchen(tenant, FALLBACK_MUSTER)
