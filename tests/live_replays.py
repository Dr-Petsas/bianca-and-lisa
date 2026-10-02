"""Anonymisierte, wortgleiche Live-Replays vom 02.10.2026 (Paket 3).

Grundlage: der read-only Scorer-/`anruf_anliegen`-Lauf gegen die echten
Tagesmanifeste (58 gewertet, 0 % super, 27,6 % fehlerhaft). Jede Fehlerklasse
bekommt EINEN wortgleichen Auslöser-Satz (PII ersetzt: Namen/Nummern/
Geburtsdaten sind FREI ERFUNDEN, der strukturelle Auslöser bleibt erhalten)
und — wo sinnvoll — eine Gegenprobe, die NICHT anschlagen darf.

Dieses Modul trägt NUR Daten. Die Verhaltens-Assertions liegen in den Paketen,
die die jeweilige Klasse reparieren (4–9): sie importieren `REPLAYS` /
`replays_der_klasse` und machen den roten Replay grün, ohne die Gegenprobe zu
brechen. So bleibt jede Fehlerklasse an einem echten Gespräch verankert.

Keine echten Patientendaten im Repo: Telefonnummern, Klarnamen und
Geburtsdaten sind ausgetauscht. Nicht-PII-Auslöser („Terminauskunft“,
„für zwei Personen“, „Sprechstunde“, „Nenne mir einen Alternativtermin“)
bleiben wortgleich, weil genau sie das Verhalten auslösen.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Replay:
    sid: str                      # anonymisiertes Sitzungs-Kürzel
    tenant: str                   # blessing | meddent | thaler
    klasse: str                   # Fehlerklasse (Schlüssel, s. KLASSEN)
    paket: str                    # Todo-/Paket-Id, das die Klasse repariert
    anrufer: tuple[str, ...]      # wortgleiche (anonymisierte) Auslöser-Sätze
    fehlverhalten: str            # was Bianca live falsch gemacht hat
    soll: str                     # erwartetes korrektes Verhalten
    gegenprobe: tuple[str, ...] = field(default_factory=tuple)
    gegenprobe_soll: str = ""


# Fehlerklassen des 02.10.2026 → reparierendes Paket.
KLASSEN: dict[str, str] = {
    "nachname_fusion": "harden-names-search",
    "presence_im_diktat": "separate-noise-silence",
    "einzelslot_alternative_schleife": "stabilize-dialog-state",
    "mehrpersonen_termin": "support-multiple-patients",
    "sprechstunde_kein_erreichen": "tighten-intents",
    "dringlichkeit_kontext": "tighten-intents",
    "negativaussage_ohne_suche": "enforce-grounded-claims",
    "platzhalter_anrede_leak": "enforce-grounded-claims",
    "auskunft_menue_schleife": "stabilize-dialog-state",
    "sonst_noch_schleife": "stabilize-dialog-state",
}


REPLAYS: tuple[Replay, ...] = (
    # --- Nachnamen-Fusion (buchstaben.deute) -------------------------------
    Replay(
        sid="blessing-fusion",
        tenant="blessing",
        klasse="nachname_fusion",
        paket="harden-names-search",
        anrufer=(
            "Der Nachname heißt Maier.",
            "M wie Martha, A wie Anton, I wie Ida, E wie Emil, R wie Richard, fertig.",
        ),
        fehlverhalten=(
            "Gesprochener Name und Buchstabierkette verschmolzen zu "
            "„Maiermaier“ (live: „Grafgrafgras“, „Bayerbayerr“)."
        ),
        soll=(
            "Der buchstabierte Nachname lautet genau „Maier“ — die "
            "gesprochene Vorerwähnung wird NICHT an die Kette geklebt."
        ),
        gegenprobe=(
            "M wie Martha, A wie Anton, I wie Ida, E wie Emil, R wie Richard, fertig.",
        ),
        gegenprobe_soll="Eine einzelne saubere Kette bleibt „Maier“.",
    ),
    # --- Presence-Stups mitten im Diktat -----------------------------------
    Replay(
        sid="blessing-presence-diktat",
        tenant="blessing",
        klasse="presence_im_diktat",
        paket="separate-noise-silence",
        anrufer=(
            "G wie Gustav, R wie Richard, A wie Anton, F wie Friedrich",
            "weiter",
        ),
        fehlverhalten=(
            "„Sind Sie noch dran?“ feuerte, während der Anrufer noch "
            "buchstabierte (Teilstück-Pause als Stille gewertet)."
        ),
        soll=(
            "Ein Buchstabier-Teilstück ist ein stiller warte-Zug — kein "
            "Presence-Stups, der Anrufer wird nicht unterbrochen."
        ),
        gegenprobe=(),
    ),
    # --- Einzel-Slot: Anrufer bittet um Alternative, Bianca loopt ----------
    Replay(
        sid="blessing-einzelslot",
        tenant="blessing",
        klasse="einzelslot_alternative_schleife",
        paket="stabilize-dialog-state",
        anrufer=(
            "Ich habe ja nur einen. Nenne mir bitte einen Alternativtermin.",
            "Ich habe Sie nicht verstanden, nennen Sie mir einen Alternativtermin.",
        ),
        fehlverhalten=(
            "Bianca wiederholte denselben einzigen Slot als „Im Angebot "
            "sind: … Welcher passt Ihnen?“ statt die Bitte zu beantworten."
        ),
        soll=(
            "Auf die Bitte um eine Alternative sucht Bianca die nächste "
            "freie Zeit ODER sagt ehrlich, dass es im Fenster nur diesen "
            "einen Termin gibt — nie dieselbe Angebotsfrage in Schleife."
        ),
        gegenprobe=(),
    ),
    # --- Mehrpersonen-Termin in EINEM Satz ---------------------------------
    Replay(
        sid="blessing-zweipersonen",
        tenant="blessing",
        klasse="mehrpersonen_termin",
        paket="support-multiple-patients",
        anrufer=(
            "Ich bräuchte einen Termin bei Ihnen, für zwei Personen, "
            "ich und meine Mutter, Anton Beispiel und Eva Beispiel.",
        ),
        fehlverhalten=(
            "Bianca buchte nur EINE Person (den Erstgenannten) und "
            "verlor den zweiten Termin komplett."
        ),
        soll=(
            "Zwei Buchungsaufgaben: die erste läuft, die zweite wird "
            "geparkt und nach Abschluss der ersten per Auto-Resume "
            "fortgesetzt — beide Personen bekommen einen Termin."
        ),
        gegenprobe=(
            "Ich bräuchte einen Termin für meine Mutter.",
        ),
        gegenprobe_soll=(
            "Ein einzelner Dritt-Termin bleibt EINE Aufgabe (W-FUER-WEN), "
            "kein zweiter Task."
        ),
    ),
    # --- „Sprechstunde“ ist KEIN Verbinden-Wunsch --------------------------
    Replay(
        sid="blessing-sprechstunde",
        tenant="blessing",
        klasse="sprechstunde_kein_erreichen",
        paket="tighten-intents",
        anrufer=(
            "Ich brauche einen Termin in der Sprechstunde.",
        ),
        fehlverhalten=(
            "`_FB_ERREICHEN_RE` (\\bsprech\\w*) matcht „Sprechstunde“ und "
            "würde zum Durchstell-/Verbinden-Dialog führen."
        ),
        soll=(
            "„Sprechstunde“ als Besuchsgrund bleibt eine BUCHUNG (ANLEGEN) "
            "— kein ERREICHEN, kein Transfer."
        ),
        gegenprobe=(
            "Kann ich bitte mit Doktor Blessing sprechen?",
        ),
        gegenprobe_soll=(
            "Ein echter Sprech-/Verbinden-Wunsch bleibt ERREICHEN."
        ),
    ),
    # --- Kontextuelle Dringlichkeit ----------------------------------------
    Replay(
        sid="blessing-dringlich",
        tenant="blessing",
        klasse="dringlichkeit_kontext",
        paket="tighten-intents",
        anrufer=(
            "Ich müsste kurz vorbeikommen, weil meine Wunde wieder blutet.",
            "So schnell wie möglich einen Termin, es ist dringend.",
        ),
        fehlverhalten=(
            "Akut-/Dringlichkeits-Signal wurde ignoriert; es kam ein "
            "regulärer, weit entfernter Slot ohne Akut-Behandlung."
        ),
        soll=(
            "Die Dringlichkeit im Kontext (Blutung/akut) steuert das "
            "Motiv/Zeitfenster — kein stiller Standard-Slot Monate später."
        ),
        gegenprobe=(
            "Ich hätte gern irgendwann einen Kontrolltermin.",
        ),
        gegenprobe_soll="Ohne Akut-Signal bleibt es ein normaler Termin.",
    ),
    # --- Negative Terminaussage ohne echte Suche ---------------------------
    Replay(
        sid="thaler-negativ",
        tenant="thaler",
        klasse="negativaussage_ohne_suche",
        paket="enforce-grounded-claims",
        anrufer=(
            "Wann habe ich meinen Termin?",
            "Monika Beispielfrau.",
        ),
        fehlverhalten=(
            "„Ich habe hier aktuell keine Termine für eine gefunden“ ohne "
            "belegte Kalender-/Patientensuche."
        ),
        soll=(
            "Eine negative Terminaussage braucht eine erfolgreiche "
            "Lese-Evidenz (agentFindPatientAppointments). Ohne Suche sagt "
            "Bianca ehrlich, dass sie noch nachsehen muss (vgl. die gute "
            "Zeile „ohne echte Kalendersuche nicht sicher sagen“)."
        ),
        gegenprobe=(),
    ),
    # --- Platzhalter-Name als Anrede (Folge des Namenslink-P0) -------------
    Replay(
        sid="meddent-platzhalter",
        tenant="meddent",
        klasse="platzhalter_anrede_leak",
        paket="enforce-grounded-claims",
        anrufer=(
            "Ich hätte gerne gewusst, wann mein nächster Termin ist.",
            "Mein Name ist Stefan Beispiel.",
        ),
        fehlverhalten=(
            "Anrufer über die geteilte Platzhalter-Akte als „Frau SMS“ "
            "angesprochen, dazu der Floskel-Satz „Ich bin die Neue!“."
        ),
        soll=(
            "Ein Platzhalter-Name (ist_platzhalter_name) wird NIE als "
            "Anrede gesprochen; „Ich bin die Neue“ fällt ganz weg."
        ),
        gegenprobe=(),
    ),
    # --- Intent-Menü akzeptiert die klare Antwort nicht --------------------
    Replay(
        sid="blessing-auskunft-menue",
        tenant="blessing",
        klasse="auskunft_menue_schleife",
        paket="stabilize-dialog-state",
        anrufer=(
            "Auskunft.",
            "Terminauskunft",
            "Ja, Auskunft.",
        ),
        fehlverhalten=(
            "„Geht es um einen Termin, eine Absage, eine Verschiebung oder "
            "eine Terminauskunft?“ loopte 6×, obwohl der Anrufer wortgleich "
            "„Terminauskunft“ sagte."
        ),
        soll=(
            "„Auskunft“/„Terminauskunft“ wird als Antwort erkannt und "
            "führt in den Auskunftszweig — nie dieselbe Menüfrage erneut."
        ),
        gegenprobe=(),
    ),
    # --- „Sonst noch?“-Schleife --------------------------------------------
    Replay(
        sid="blessing-sonst-noch",
        tenant="blessing",
        klasse="sonst_noch_schleife",
        paket="stabilize-dialog-state",
        anrufer=(
            "Okay, passt schon.",
            "Chop.",
        ),
        fehlverhalten=(
            "Nach dem Verschieben fiel „Kann ich sonst noch etwas für Sie "
            "tun?“ in den Intent-Zweig zurück und loopte."
        ),
        soll=(
            "„Sonst noch?“ ist genau einmal eine registrierte Formularfrage; "
            "unklare Antwort fällt nicht in eine neue Menüschleife."
        ),
        gegenprobe=(),
    ),
)


def replays_der_klasse(klasse: str) -> tuple[Replay, ...]:
    return tuple(r for r in REPLAYS if r.klasse == klasse)


def replay(sid: str) -> Replay:
    for r in REPLAYS:
        if r.sid == sid:
            return r
    raise KeyError(sid)
