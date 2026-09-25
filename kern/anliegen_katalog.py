"""Praxis-Layer fuer ALLE Anliegen ausser der Terminverwaltung.

Chef 19.09.2026 (woertlich): „mit der maske kann kein kunde etwas anfangen. es
muessen dort alle anliegen aufgefuehrt werden und was sich der kunde fuer eine
reaktion wuenscht. z.b.: rezept: checkbox, versenden wir wenn karte eingelesen
und wiederholungsrezept klar ist. versenden wir nie, braucht eine Vorstellung
beim Arzt und Freigabe in der Praxis. AU: versenden wir automatisch auf
anfrage, wird nie ohne untersuchung versendet ... zu jedem anliegen ausser
terminverwaltende darf jeder arzt seine prosa eingabe machen oder checkboxen
anklicken nach denen sich die KI zu richten hat" — und danach: „terminverwaltung
fest verankern ueberall, restliche anliegen praxislayer erlauben."

Deshalb zwei streng getrennte Ebenen:

* **Terminverwaltung (buchen, absagen, verschieben, Auskunft) ist FEST.** Sie
  steht in keiner Maske, hat keinen Schalter und keine Prosa. Wer einen Termin
  will, laeuft durch den bewaehrten, belegpflichtigen Weg — eine Praxis kann
  ihn weder abschalten noch mit eigenem Text ueberschreiben.
* **Jedes andere Anliegen ist Praxis-Sache.** Hier steht der Katalog: je
  Anliegen eine Handvoll Optionen in Kundensprache (Radio), unabhaengige
  Bedingungen (Haken) und ein freies Antwortfeld. Was die Praxis dort
  schreibt, SPRICHT Bianca woertlich — kein Modell formuliert es um.

Die Folge (was nach dem Satz passiert) kommt NICHT aus der Prosa, sondern aus
der gewaehlten Option: ehrliches Nein, Notiz mit Rueckruf, Termin anbieten,
durchstellen, Notfallweg, reine Auskunft. So bleibt der Satz Praxis-Text und
die HANDLUNG bleibt im Code — eine Praxis kann sich keinen Schreibweg und
keinen Transfer erfinden, den es nicht gibt.

Sicherheitsgrenzen, die keine Praxis aufweichen kann:

1. Terminverwaltung, Buchungs-Belegpflicht und die Wachen bleiben unberuehrt.
2. ``VERBINDEN`` heisst nur „darf durchgestellt werden" — OB durchgestellt
   wird, entscheidet weiter ``bianca/weiterleiten.py`` samt Whitelist und
   Behandler-Sperre. Ohne erlaubtes Ziel fuehrt die Option zur Notiz.
3. Lebensgefahr (112) bleibt im Code. Eine Praxis kann den Notfallweg
   schaerfen, nie abschalten.
4. Prosa wird geklemmt (Laenge, Steuerzeichen) und nie als Tatsache verkauft:
   sie ist die Antwort der Praxis, keine Zusage eines Werkzeugs.

Ohne Eintrag verhaelt sich jeder Mandant byte-identisch wie vorher — der
Katalog liefert dann fuer jedes Anliegen ``None`` und der bisherige Pfad
(Intent, Praxisregeln, Rechnung, Weiterleitung) laeuft unveraendert.

Notaus: ``ANLIEGEN_KATALOG=0``.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any

SCHEMA_VERSION = 1
PROSA_MAX = 600

# Die Terminverwaltung steht bewusst NICHT im Katalog. Diese Kennungen sind
# reserviert: taucht eine davon in einem Praxis-Eintrag auf, wird sie
# verworfen und gewarnt (eine Praxis darf den Terminweg nicht umschreiben).
# Alles, was ein Termin IST: Buchung, Absage, Verschieben, Bestandsauskunft
# und jeder Besuchsgrund (Kontrolle, PZR, Schmerz, …). Die Maske darf das
# weder abschalten noch umformulieren — der V4-Weg bleibt fuer alle Kunden gleich.
FEST_VERANKERT = (
    "buchen", "absagen", "verschieben", "auskunft", "auskunft_bestand",
    "auskunft_wort", "termin", "terminverwaltung",
    "kontrolle", "pzr", "schmerzen", "fuellung", "implantat", "wurzel",
    "kfo", "bleaching", "beratung", "blutabnahme", "fusspflege",
    "schwangerschaft", "akne", "warzen", "atherom", "muttermal",
    "allergie", "impfung", "botox", "etwas_anderes",
)


class Folge(str, Enum):
    """Was NACH dem gesprochenen Satz passiert — kommt nie aus der Prosa."""

    INFO = "info"            # nur Auskunft, kein Nebeneffekt
    NIE = "nie"              # ehrliches Nein, nichts wird geschrieben
    NOTIZ = "notiz"          # Notiz + Rueckruf (Name/Nummer wie bisher)
    TERMIN = "termin"        # dafuer braucht es einen Termin -> fester Weg
    VERBINDEN = "verbinden"  # darf durchgestellt werden (Whitelist gilt)
    SOFORT = "sofort"        # Notfallweg


@dataclass(frozen=True)
class Option:
    """Eine Wahlmoeglichkeit in Kundensprache."""

    id: str
    text: str
    folge: Folge
    satz: str


@dataclass(frozen=True)
class Haken:
    """Eine Bedingung, die die Praxis unabhaengig ankreuzen kann."""

    id: str
    text: str
    satz: str = ""


@dataclass(frozen=True)
class Anliegen:
    """Ein konfigurierbares Anliegen samt Optionen und Bedingungen."""

    id: str
    titel: str
    hinweis: str
    optionen: tuple[Option, ...]
    haken: tuple[Haken, ...] = ()

    @property
    def standard(self) -> Option:
        """Die konservativste Option — gilt, wenn die Wahl fehlt/unbekannt ist."""
        return self.optionen[0]

    def option(self, wahl: str) -> Option | None:
        kennung = _s(wahl)
        return next((o for o in self.optionen if o.id == kennung), None)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


# --------------------------------------------------------------------------
# Der Katalog. Reihenfolge = Reihenfolge in der Maske.
# Die erste Option je Anliegen ist absichtlich die konservativste: eine
# unbekannte oder verbogene Wahl landet dort, nie beim Grosszuegigen.
# --------------------------------------------------------------------------
KATALOG: tuple[Anliegen, ...] = (
    Anliegen(
        id="rezept",
        titel="Rezept / Folgerezept",
        hinweis="Wie gehen Sie mit Rezeptwünschen am Telefon um?",
        optionen=(
            Option(
                "vorstellung",
                "Nur persönliche Ausstellung in der Praxis",
                Folge.TERMIN,
                "Ein Rezept stellen wir nicht am Telefon aus. Dafür müssen Sie "
                "persönlich in die Praxis kommen.",
            ),
            Option(
                "notiz",
                "Rückruf anbieten — die Praxis prüft und ruft zurück",
                Folge.NOTIZ,
                "Ich nehme Ihren Rezeptwunsch auf. Die Praxis prüft das und "
                "ruft Sie zurück.",
            ),
            Option(
                "versand",
                "Online / zuschicken, wenn im selben Quartal schon ein Termin war",
                Folge.NOTIZ,
                "Wenn Sie in diesem Quartal schon bei uns waren, können wir das "
                "Rezept zuschicken. Ich nehme Ihren Wunsch auf.",
            ),
            Option(
                "abholung",
                "Wunsch aufnehmen, Abholung in der Praxis",
                Folge.NOTIZ,
                "Ich nehme Ihren Rezeptwunsch auf. Das Rezept liegt dann zur "
                "Abholung in der Praxis bereit.",
            ),
        ),
        haken=(
            Haken("karte", "Nur wenn die Karte im Quartal eingelesen ist",
                  "Dafür muss Ihre Karte in diesem Quartal bei uns eingelesen "
                  "worden sein."),
            Haken("bekannt", "Nur bei bekanntem Dauermedikament",
                  "Das gilt nur für ein Medikament, das Sie bei uns schon "
                  "verordnet bekommen haben."),
            Haken("freigabe", "Immer erst nach ärztlicher Freigabe",
                  "Der Arzt gibt das vorher frei."),
            Haken("btm", "Betäubungsmittel nie am Telefon",
                  "Betäubungsmittel-Rezepte gibt es grundsätzlich nur "
                  "persönlich."),
        ),
    ),
    Anliegen(
        id="au",
        titel="Krankschreibung (AU)",
        hinweis="Arbeitsunfähigkeit, gelber Schein, Krankmeldung.",
        optionen=(
            Option(
                "untersuchung",
                "Nur nach Untersuchung in der Praxis",
                Folge.TERMIN,
                "Eine Krankschreibung gibt es nicht ohne Untersuchung. Dafür "
                "müssen wir Sie in der Praxis sehen.",
            ),
            Option(
                "notiz",
                "Rückruf anbieten — die Praxis entscheidet und ruft zurück",
                Folge.NOTIZ,
                "Ich nehme das auf. Die Praxis prüft, ob wir krankschreiben "
                "können, und ruft Sie zurück.",
            ),
            Option(
                "nachtrag",
                "Nachtrag, wenn der Besuch in diesem Quartal schon war",
                Folge.NOTIZ,
                "Wenn Sie in diesem Quartal schon bei uns waren, können wir "
                "das prüfen. Ich notiere es für die Praxis.",
            ),
            Option(
                "automatisch",
                "Auf Anfrage ausstellen und zuschicken",
                Folge.NOTIZ,
                "Das können wir auf Anfrage ausstellen und Ihnen zuschicken. "
                "Ich nehme es auf.",
            ),
        ),
        haken=(
            Haken("erstbesuch", "Erstbescheinigung immer nur mit Termin",
                  "Die Erstbescheinigung gibt es nur mit Termin."),
            Haken("verlaengerung", "Verlängerung auch telefonisch möglich",
                  "Eine Verlängerung können wir auch telefonisch klären."),
            Haken("karte", "Nur wenn die Karte im Quartal eingelesen ist",
                  "Dafür muss Ihre Karte in diesem Quartal eingelesen worden "
                  "sein."),
        ),
    ),
    Anliegen(
        id="ueberweisung",
        titel="Überweisung ausstellen",
        hinweis="Der Anrufer möchte eine Überweisung von Ihnen bekommen.",
        optionen=(
            Option(
                "vorstellung",
                "Nur persönliche Ausstellung in der Praxis",
                Folge.TERMIN,
                "Eine Überweisung stellen wir nur nach einer kurzen "
                "Vorstellung in der Praxis aus.",
            ),
            Option(
                "notiz",
                "Rückruf anbieten — die Praxis bereitet sie vor und ruft zurück",
                Folge.NOTIZ,
                "Ich nehme Ihren Wunsch auf. Die Praxis bereitet die "
                "Überweisung vor und ruft Sie zurück.",
            ),
            Option(
                "abholung",
                "Wunsch aufnehmen, Abholung in der Praxis",
                Folge.NOTIZ,
                "Ich notiere das. Die Überweisung liegt dann zur Abholung in "
                "der Praxis bereit.",
            ),
        ),
        haken=(
            Haken("karte", "Nur mit eingelesener Karte im Quartal",
                  "Dafür muss Ihre Karte in diesem Quartal eingelesen worden "
                  "sein."),
            Haken("freigabe", "Immer erst nach ärztlicher Freigabe",
                  "Der Arzt gibt das vorher frei."),
        ),
    ),
    Anliegen(
        id="attest",
        titel="Attest / Bescheinigung",
        hinweis="Schul- und Sportbefreiung, Bescheinigungen, Formulare.",
        optionen=(
            Option(
                "vorstellung",
                "Nur persönliche Ausstellung in der Praxis",
                Folge.TERMIN,
                "Eine Bescheinigung können wir erst nach einer Vorstellung "
                "ausstellen.",
            ),
            Option(
                "notiz",
                "Rückruf anbieten — die Praxis prüft und ruft zurück",
                Folge.NOTIZ,
                "Ich nehme das auf. Die Praxis prüft es und ruft Sie zurück.",
            ),
        ),
        haken=(
            Haken("kosten", "Kostenpflichtig, Selbstzahlerleistung",
                  "Das ist eine Selbstzahlerleistung."),
        ),
    ),
    Anliegen(
        id="befund",
        titel="Befunde / Laborwerte",
        hinweis="Der Anrufer will Ergebnisse oder Werte wissen.",
        optionen=(
            Option(
                "nie",
                "Nur persönlich beim Arzt — am Telefon keine Werte",
                Folge.NIE,
                "Befunde und Werte darf ich am Telefon nicht mitteilen. Das "
                "besprechen Sie bitte mit dem Arzt.",
            ),
            Option(
                "termin",
                "Nur im Besprechungstermin",
                Folge.TERMIN,
                "Befunde besprechen wir im Termin — am Telefon darf ich dazu "
                "nichts sagen.",
            ),
            Option(
                "notiz",
                "Rückruf anbieten — die Praxis ruft zurück",
                Folge.NOTIZ,
                "Am Telefon darf ich dazu nichts sagen. Ich richte einen "
                "Rückruf ein, dann bespricht die Praxis das mit Ihnen.",
            ),
        ),
        haken=(
            Haken("nur_patient", "Nur an den Patienten selbst",
                  "Das geht ausschließlich an Sie persönlich."),
        ),
    ),
    Anliegen(
        id="unterlagen",
        titel="Röntgenbilder / Unterlagen",
        hinweis="Herausgabe von Bildern, Akten, Behandlungsunterlagen.",
        optionen=(
            Option(
                "kollege",
                "Nur auf dem Dienstweg an den anfordernden Arzt",
                Folge.NIE,
                "Bilder und Unterlagen geben wir auf dem gesicherten Dienstweg "
                "direkt an den anfordernden Arzt. Der muss sie bei uns "
                "anfordern.",
            ),
            Option(
                "notiz",
                "Rückruf anbieten — die Praxis bereitet es vor",
                Folge.NOTIZ,
                "Ich nehme die Anfrage auf. Die Praxis bereitet die Unterlagen "
                "vor und ruft Sie zurück.",
            ),
            Option(
                "abholung",
                "Nur persönliche Abholung in der Praxis",
                Folge.NOTIZ,
                "Die Unterlagen können Sie persönlich in der Praxis abholen. "
                "Ich notiere Ihre Anfrage.",
            ),
        ),
        haken=(
            Haken("schriftlich", "Nur mit schriftlicher Einwilligung",
                  "Dafür brauchen wir Ihre schriftliche Einwilligung."),
            Haken("kosten", "Kopien sind kostenpflichtig",
                  "Für Kopien fällt eine Gebühr an."),
        ),
    ),
    Anliegen(
        id="medikament",
        titel="Medikamenten- / Nebenwirkungsfrage",
        hinweis="Fragen zu Einnahme, Dosierung, Nebenwirkungen.",
        optionen=(
            Option(
                "nie",
                "Nur persönlich beim Arzt — am Telefon keine Auskunft",
                Folge.NIE,
                "Zu Medikamenten darf ich am Telefon nichts sagen. Das "
                "beantwortet Ihnen der Arzt.",
            ),
            Option(
                "notiz",
                "Rückruf anbieten — die Praxis ruft zurück",
                Folge.NOTIZ,
                "Dazu darf ich nichts sagen. Ich richte einen Rückruf ein, "
                "dann meldet sich die Praxis bei Ihnen.",
            ),
            Option(
                "termin",
                "Termin in der Praxis anbieten",
                Folge.TERMIN,
                "Das klären wir am besten in der Praxis. Dafür gebe ich Ihnen "
                "einen Termin.",
            ),
        ),
        haken=(
            Haken("akut", "Bei starken Nebenwirkungen sofort in die Praxis",
                  "Wenn die Beschwerden stark sind, kommen Sie bitte direkt in "
                  "die Praxis."),
        ),
    ),
    Anliegen(
        id="arzt_sprechen",
        titel="Arzt persönlich sprechen",
        hinweis="Terminwünsche bleiben davon unberührt — hier geht es nur "
                "darum, ob Sie durchgestellt werden möchten.",
        optionen=(
            Option(
                "nie",
                "Nicht durchstellen — Rückruf anbieten",
                Folge.NOTIZ,
                "Die Ärzte sind in der Behandlung und gehen nicht ans Telefon. "
                "Ich richte einen Rückruf ein.",
            ),
            Option(
                "verbinden",
                "Durchstellen, wenn der Arzt erreichbar ist",
                Folge.VERBINDEN,
                "",
            ),
            Option(
                "termin",
                "Kein Telefonat — Termin in der Praxis anbieten",
                Folge.TERMIN,
                "Am Telefon berät der Arzt nicht. Dafür gebe ich Ihnen einen "
                "Termin.",
            ),
        ),
        haken=(
            Haken("sprechzeit", "Nur in der telefonischen Sprechstunde",
                  "Das geht nur in unserer telefonischen Sprechstunde."),
            Haken("bekannt", "Nur bei bekannten Patienten",
                  "Das machen wir bei Patienten, die bei uns in Behandlung "
                  "sind."),
        ),
    ),
    Anliegen(
        id="mitarbeiter_sprechen",
        titel="Anmeldung / Mitarbeiter sprechen",
        hinweis="Wenn jemand ausdrücklich einen Menschen am Empfang möchte.",
        optionen=(
            Option(
                "selbst",
                "Bianca übernimmt das Anliegen selbst",
                Folge.INFO,
                "Ich bin die Telefonassistentin der Praxis und entlaste die "
                "Anmeldung. Sagen Sie mir einfach, worum es geht.",
            ),
            Option(
                "notiz",
                "Rückruf anbieten — die Anmeldung ruft zurück",
                Folge.NOTIZ,
                "Die Anmeldung ist gerade bei den Patienten. Ich richte einen "
                "Rückruf für Sie ein.",
            ),
            Option(
                "verbinden",
                "Durchstellen, wenn jemand erreichbar ist",
                Folge.VERBINDEN,
                "",
            ),
        ),
    ),
    Anliegen(
        id="notfall",
        titel="Notfall / akute Beschwerden",
        hinweis="Bei Lebensgefahr (Atemnot, Bewusstlosigkeit, schwere Reaktion) "
                "sagt Bianca immer: sofort 112. Das bleibt fest und ist nicht "
                "abschaltbar. Hier legen Sie den Weg für akute, aber nicht "
                "lebensbedrohliche Fälle fest.",
        optionen=(
            Option(
                "sofort",
                "Sofort in die Praxis kommen, Wartezeit mitbringen",
                Folge.SOFORT,
                "Das klingt akut. Kommen Sie bitte jetzt direkt in die Praxis. "
                "Eine feste Uhrzeit gibt es dafür nicht — bringen Sie bitte "
                "Wartezeit mit. Sie werden so schnell wie möglich gesehen.",
            ),
            Option(
                "bereitschaft",
                "Sofort 116 117 anrufen (ärztlicher Bereitschaftsdienst)",
                Folge.SOFORT,
                "Wenden Sie sich bitte jetzt an den ärztlichen "
                "Bereitschaftsdienst unter 116 117. Bei Atemnot oder "
                "Kreislaufproblemen wählen Sie sofort die 112.",
            ),
            Option(
                "akuttermin",
                "Akuttermin im Kalender anbieten",
                Folge.TERMIN,
                "Dafür haben wir Akuttermine. Ich schaue gleich nach einem "
                "Platz für Sie.",
            ),
            Option(
                "rueckruf",
                "Rückruf anbieten — die Praxis ruft schnell zurück",
                Folge.NOTIZ,
                "Ich notiere das als akut. Die Praxis ruft Sie schnellstmöglich "
                "zurück.",
            ),
        ),
        haken=(
            Haken("bereitschaft_ausserhalb",
                  "Außerhalb der Sprechzeit zusätzlich auf 116 117 verweisen",
                  "Außerhalb unserer Sprechzeiten wenden Sie sich bitte an den "
                  "ärztlichen Bereitschaftsdienst unter 116 117."),
        ),
    ),
    Anliegen(
        id="rechnung",
        titel="Rechnung / Abrechnung",
        hinweis="Rechnungsthemen dürfen am Telefon nie inhaltlich besprochen "
                "werden — hier legen Sie nur fest, was stattdessen passiert.",
        optionen=(
            Option(
                "persoenlich",
                "Nur persönlich in der Praxis besprechen",
                Folge.NIE,
                "Rechnungsthemen besprechen wir nur persönlich in der Praxis.",
            ),
            Option(
                "rueckruf",
                "Rückruf anbieten — die Buchhaltung ruft zurück",
                Folge.NOTIZ,
                "Zu Rechnungen darf ich am Telefon nichts sagen. Ich richte "
                "Ihnen einen Rückruf ein.",
            ),
        ),
    ),
    Anliegen(
        id="kosten",
        titel="Kosten / Preisfragen",
        hinweis="Preise nennt Bianca nur, wenn Sie sie hier hinterlegen.",
        optionen=(
            Option(
                "keine_auskunft",
                "Keine Preisauskunft am Telefon — nur in der Praxis",
                Folge.NIE,
                "Zu Kosten kann ich am Telefon keine verbindliche Auskunft "
                "geben. Das besprechen wir in der Praxis.",
            ),
            Option(
                "eigene_auskunft",
                "Eigenen Text eintragen — Bianca spricht ihn wörtlich",
                Folge.INFO,
                "",
            ),
            Option(
                "notiz",
                "Rückruf anbieten — die Praxis erklärt die Kosten",
                Folge.NOTIZ,
                "Ich notiere Ihre Frage zu den Kosten. Die Praxis ruft Sie "
                "zurück.",
            ),
        ),
        haken=(
            Haken("kasse", "Hinweis: Kassenleistung nach Befund",
                  "Was die Kasse übernimmt, hängt vom Befund ab."),
        ),
    ),
    Anliegen(
        id="neupatient",
        titel="Neue Patienten",
        hinweis="Nimmt die Praxis aktuell neue Patienten auf?",
        optionen=(
            Option(
                "ja",
                "Ja — neue Patienten aufnehmen und Termin anbieten",
                Folge.TERMIN,
                "Neue Patienten nehmen wir gerne auf.",
            ),
            Option(
                "warteliste",
                "Nur auf die Warteliste — Rückruf, wenn ein Platz frei wird",
                Folge.NOTIZ,
                "Neue Patienten nehmen wir derzeit nur auf die Warteliste. Ich "
                "notiere Sie gerne.",
            ),
            Option(
                "nein",
                "Nein — aktuell keine neuen Patienten",
                Folge.NIE,
                "Aktuell können wir leider keine neuen Patienten aufnehmen.",
            ),
        ),
        haken=(
            Haken("privat", "Nur Privatpatienten und Selbstzahler",
                  "Das gilt für Privatpatienten und Selbstzahler."),
            Haken("ueberweisung", "Nur mit Überweisung",
                  "Dafür brauchen Sie eine Überweisung."),
        ),
    ),
    Anliegen(
        id="beschwerde",
        titel="Beschwerde / Kritik",
        hinweis="Wenn sich jemand über die Praxis beschwert.",
        optionen=(
            Option(
                "notiz",
                "Rückruf anbieten — die Praxisleitung ruft zurück",
                Folge.NOTIZ,
                "Das tut mir leid. Ich nehme das auf, damit sich die "
                "Praxisleitung bei Ihnen melden kann.",
            ),
            Option(
                "persoenlich",
                "Nur persönlich in der Praxis oder schriftlich",
                Folge.NIE,
                "Das tut mir leid. Am Telefon kann ich das nicht klären — "
                "sprechen Sie es bitte in der Praxis an oder schreiben Sie uns.",
            ),
        ),
    ),
    Anliegen(
        id="rueckruf",
        titel="Rückruf / Nachricht hinterlassen",
        hinweis="Der Anrufer will keinen Termin, sondern dass sich die Praxis meldet.",
        optionen=(
            Option(
                "notiz",
                "Rückruf aufnehmen — Name und Nummer, echte Notiz",
                Folge.NOTIZ,
                "Gerne richte ich einen Rückruf ein.",
            ),
            Option(
                "nie",
                "Kein Rückruf — bitte in der Praxis oder schriftlich",
                Folge.NIE,
                "Einen Rückruf kann ich so nicht einrichten. Bitte kommen Sie "
                "in die Praxis oder schreiben Sie uns.",
            ),
        ),
    ),
    Anliegen(
        id="oeffnungszeiten",
        titel="Öffnungszeiten / Anfahrt",
        hinweis="Entweder liest Bianca die Zeiten und den Weg aus dem "
                "Praxisprofil (Standort / hinterlegte Öffnungszeiten), oder "
                "Sie tragen hier den Satz ein, den sie wörtlich sagt.",
        optionen=(
            Option(
                "standort",
                "Aus dem Praxisprofil vorlesen (Standort und hinterlegte Zeiten)",
                Folge.INFO,
                "",
            ),
            Option(
                "eigene_auskunft",
                "Eigenen Text eintragen — Bianca spricht ihn wörtlich",
                Folge.INFO,
                "",
            ),
        ),
    ),
    Anliegen(
        id="sonstiges",
        titel="Eigene Regel (freies Anliegen)",
        hinweis="Alles, was oben nicht steht: Ihr Text gilt, sobald der "
                "Anrufer eines Ihrer Stichwörter nennt.",
        optionen=(
            Option(
                "notiz",
                "Rückruf anbieten — Anliegen aufnehmen und weitergeben",
                Folge.NOTIZ,
                "Ich nehme das für die Praxis auf.",
            ),
            Option(
                "info",
                "Eigenen Text eintragen — Bianca spricht ihn wörtlich",
                Folge.INFO,
                "",
            ),
        ),
    ),
)

NACH_ID: dict[str, Anliegen] = {a.id: a for a in KATALOG}


def an() -> bool:
    """Notaus ``ANLIEGEN_KATALOG=0``."""
    return _s(os.getenv("ANLIEGEN_KATALOG", "1")).lower() not in (
        "0", "off", "false", "nein",
    )


# --------------------------------------------------------------------------
# Praxis-Eintrag
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Regel:
    """Die fertige Regel eines Anliegens fuer diese Praxis."""

    id: str
    wahl: str
    folge: Folge
    satz: str
    prosa: str
    haken: tuple[str, ...]
    stichworte: tuple[str, ...] = ()

    @property
    def eigener_text(self) -> bool:
        return bool(self.prosa)


def _prosa_klemmen(v: Any) -> str:
    """Praxis-Text saeubern: Steuerzeichen raus, Laenge klemmen, Satzende.

    Der Text wird spaeter WOERTLICH gesprochen — er darf nichts enthalten,
    was die Sprech-Schicht zerlegt (Zeilenumbrueche, Steuerzeichen), und er
    muss auf ein Satzzeichen enden, damit der Satz-Splitter ihn nicht mit dem
    Folgesatz verklebt.
    """
    t = "".join(
        " " if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") else c
        for c in str(v or "")
    )
    t = _s(t)[:PROSA_MAX].strip()
    if not t:
        return ""
    if t[-1] not in ".!?:":
        t += "."
    return t


def _stichworte(v: Any) -> tuple[str, ...]:
    """Eigene Stichwoerter (nur ``sonstiges``): Komma- oder Zeilenliste."""
    if isinstance(v, (list, tuple)):
        teile = [_s(x) for x in v]
    else:
        teile = [_s(x) for x in re.split(r"[,;\n]", str(v or ""))]
    # Zu kurze Fetzen treffen zu viel ("ja", "au" waere ein eigenes Anliegen).
    raus: list[str] = []
    for t in teile:
        if len(t) < 4 or len(t) > 40:
            continue
        if t.lower() not in [x.lower() for x in raus]:
            raus.append(t)
    return tuple(raus[:12])


def parse(roh: Any) -> tuple[dict[str, Regel], list[str]]:
    """Praxis-Eintrag lesen. Wirft NIE — im Zweifel gilt die sichere Option.

    Rueckgabe: ``({anliegen_id: Regel}, warnungen)``. Nicht konfigurierte
    Anliegen fehlen im Dict — dort laeuft der bisherige Pfad weiter.
    """
    warn: list[str] = []
    out: dict[str, Regel] = {}
    if not isinstance(roh, dict) or not roh:
        return out, warn
    daten = roh.get("anliegen") if isinstance(roh.get("anliegen"), dict) else roh
    if not isinstance(daten, dict):
        return out, ["anliegen: unbekannte Form — Eintrag ignoriert."]
    for kennung, wert in daten.items():
        key = _s(kennung).lower()
        if key in FEST_VERANKERT:
            warn.append(
                f"{key}: Terminverwaltung ist fest verankert und nicht "
                f"konfigurierbar — Eintrag ignoriert."
            )
            continue
        spec = NACH_ID.get(key)
        if spec is None:
            warn.append(f"{key}: unbekanntes Anliegen — Eintrag ignoriert.")
            continue
        if wert is False or wert is None:
            continue
        if not isinstance(wert, dict):
            warn.append(f"{key}: unbekannte Form — Eintrag ignoriert.")
            continue
        if wert.get("an") is False:
            continue
        wahl = _s(wert.get("wahl") or wert.get("option"))
        opt = spec.option(wahl)
        if opt is None:
            if wahl:
                warn.append(
                    f"{key}: unbekannte Wahl {wahl!r} — es gilt "
                    f"„{spec.standard.text}“."
                )
            opt = spec.standard
        roh_haken = wert.get("haken")
        if isinstance(roh_haken, dict):
            gesetzt = [k for k, v in roh_haken.items() if v]
        elif isinstance(roh_haken, (list, tuple)):
            gesetzt = [_s(x) for x in roh_haken]
        else:
            gesetzt = []
        bekannt = [h.id for h in spec.haken]
        haken = tuple(h for h in bekannt if h in {_s(g) for g in gesetzt})
        for g in gesetzt:
            if _s(g) and _s(g) not in bekannt:
                warn.append(f"{key}: unbekannter Haken {_s(g)!r} — ignoriert.")
        prosa = _prosa_klemmen(wert.get("prosa") or wert.get("text"))
        if not prosa and not opt.satz:
            # Optionen ohne Standardsatz brauchen Prosa. Ausnahme:
            # Oeffnungszeiten aus dem Praxisprofil — der Satz kommt live.
            profil_ok = key == "oeffnungszeiten" and opt.id == "standort"
            if opt.folge in (Folge.INFO, Folge.NIE) and not profil_ok:
                warn.append(
                    f"{key}: „{opt.text}“ braucht einen eigenen Antworttext — "
                    f"es gilt „{spec.standard.text}“."
                )
                opt = spec.standard
        out[key] = Regel(
            id=key,
            wahl=opt.id,
            folge=opt.folge,
            satz=opt.satz,
            prosa=prosa,
            haken=haken,
            stichworte=_stichworte(wert.get("stichworte")) if key == "sonstiges" else (),
        )
    return out, warn


def aus_tenant(tenant: dict | None) -> dict[str, Regel]:
    """Regeln dieses Mandanten (``tenant["anliegenPolicy"]``)."""
    if not an() or not isinstance(tenant, dict):
        return {}
    regeln, _ = parse(tenant.get("anliegenPolicy"))
    return regeln


def regel(tenant: dict | None, anliegen_id: str) -> Regel | None:
    """Die Regel eines Anliegens — ``None`` = nicht konfiguriert (alter Weg)."""
    return aus_tenant(tenant).get(_s(anliegen_id).lower())


def antwort(r: Regel | None, tenant: dict | None = None) -> str:
    """Der WOERTLICH zu sprechende Satz: Prosa gewinnt, sonst der Standard.

    Die Haken-Saetze haengen hinten dran — sie sind Bedingungen, keine
    eigenen Themen, und stehen deshalb nie vor der Hauptaussage.
    Oeffnungszeiten mit Wahl ``standort`` kommen live aus dem Praxisprofil.
    """
    if r is None:
        return ""
    spec = NACH_ID.get(r.id)
    kern = r.prosa or r.satz
    if (
        r.id == "oeffnungszeiten"
        and r.wahl == "standort"
        and not r.prosa
    ):
        from kern import wissen
        profil = wissen.profil_auskunft(tenant)
        kern = _s(profil.get("satz")) or (
            "Die genauen Öffnungszeiten habe ich hier leider nicht vorliegen "
            "— einen Termin kann ich Ihnen aber gern direkt geben."
        )
    teile = [kern]
    if spec is not None:
        for h in spec.haken:
            if h.id in r.haken and h.satz:
                teile.append(h.satz)
    return _s(" ".join(t for t in teile if _s(t)))


def leer_policy() -> dict[str, Any]:
    """Alle Anliegen auf der ersten (konservativen) Option — fuer die Maske."""
    return as_dict({
        a.id: Regel(
            id=a.id,
            wahl=a.standard.id,
            folge=a.standard.folge,
            satz=a.standard.satz,
            prosa="",
            haken=(),
        )
        for a in KATALOG
    })


# --------------------------------------------------------------------------
# Maske (Studio + Superuser-Portal)
# --------------------------------------------------------------------------
TERMIN_FEST_TEXT = (
    "Termine buchen, absagen, verschieben und nach einem bestehenden Termin "
    "fragen — inklusive aller Besuchsgründe (Kontrolle, Reinigung, Schmerz, "
    "Füllung, Implantat …) — laufen in jeder Praxis über denselben geprüften "
    "Weg. Das ist nicht einstellbar und gilt für jeden Kunden gleich."
)

# Die Beispiele in der Maske muessen zur Fachrichtung passen: Blessing sieht
# keine Zahnreinigung, Ruether kein Melanom. Quelle ist das Kundenkonto
# (fachgebiet / fachtemplate / specialty), sonst der Motivkatalog.
FEST_BEISPIELE = {
    "zahnmedizin": "Kontrolle, Zahnreinigung, Schmerz, Füllung, Implantat",
    "dermatologie": "Kontrolle, Hautscreening, Akne, Muttermal, Warzen",
    "gynaekologie": "Vorsorge, Schwangerschaft, Krebsvorsorge",
    "orthopaedie": "Kontrolle, Schmerz, Nachsorge",
    "allgemein": "Kontrolle, Beratung, Schmerz",
}


def fest_text(fach: str = "") -> str:
    beispiele = FEST_BEISPIELE.get(_s(fach)) or FEST_BEISPIELE["allgemein"]
    if _s(fach) in ("", "zahnmedizin"):
        return TERMIN_FEST_TEXT
    return (
        "Termine buchen, absagen, verschieben und nach einem bestehenden Termin "
        "fragen — inklusive der Besuchsgründe dieser Fachrichtung "
        f"({beispiele}) — laufen über denselben geprüften Weg. Das ist nicht "
        "einstellbar. Eine andere Fachrichtung (Zahnreinigung, Melanom, …) "
        "wird hier weder angeboten noch besprochen."
    )


def _fach_block(tenant: Any) -> dict[str, Any]:
    if not isinstance(tenant, dict) or not tenant:
        return {}
    try:
        from kern import fachprofil
        tmpl = fachprofil.template(tenant)
    except Exception:
        return {}
    quelle = ""
    for key in ("fachtemplate", "fachgebiet", "specialty", "speciality"):
        if _s(tenant.get(key)):
            quelle = key
            break
    return {
        "id": tmpl.get("id") or "allgemein",
        "name": tmpl.get("name") or "Allgemeine Praxis",
        "quelle": quelle or "motivkatalog",
        "schutz": list(tmpl.get("schutz") or []),
    }


def maske(tenant: Any = None) -> dict[str, Any]:
    """Formular-Bauplan fuer die Praxis-Maske (Studio und Portal)."""
    fach = _fach_block(tenant)
    try:
        from kern import wissen
        profil = wissen.profil_auskunft(tenant if isinstance(tenant, dict) else {})
    except Exception:
        profil = {"zeiten": "", "anfahrt": "", "quelle": "fehlt", "satz": "",
                  "fehlt": True}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "fach": fach,
        "profil": profil,
        "fest": {
            "titel": "Terminverwaltung",
            "text": fest_text(fach.get("id") if fach else ""),
            "anliegen": ["Termin buchen", "Termin absagen", "Termin verschieben",
                         "Terminauskunft"],
            "beispiele": FEST_BEISPIELE.get(
                (fach or {}).get("id") or "", FEST_BEISPIELE["allgemein"]),
        },
        "prosaMax": PROSA_MAX,
        "anliegen": [
            {
                "id": a.id,
                "titel": a.titel,
                "hinweis": a.hinweis,
                "optionen": [
                    {"id": o.id, "text": o.text, "folge": o.folge.value,
                     "satz": o.satz, "eigenerTextNoetig": not o.satz}
                    for o in a.optionen
                ],
                "haken": [
                    {"id": h.id, "text": h.text, "satz": h.satz}
                    for h in a.haken
                ],
                "prosa": {
                    "text": "Eigener Antworttext (wird wörtlich gesprochen)",
                    "max": PROSA_MAX,
                },
                "stichworte": a.id == "sonstiges",
            }
            for a in KATALOG
        ],
    }


def as_dict(regeln: dict[str, Regel]) -> dict[str, Any]:
    """Regeln zurueck in die Speicherform (fuer die Ablage/Maske)."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "anliegen": {
            r.id: {
                "wahl": r.wahl,
                "haken": list(r.haken),
                "prosa": r.prosa,
                **({"stichworte": list(r.stichworte)} if r.stichworte else {}),
            }
            for r in regeln.values()
        },
    }


__all__ = [
    "Anliegen", "FEST_VERANKERT", "Folge", "Haken", "KATALOG", "NACH_ID",
    "Option", "PROSA_MAX", "Regel", "SCHEMA_VERSION", "TERMIN_FEST_TEXT",
    "an", "antwort", "as_dict", "aus_tenant", "fest_text", "leer_policy",
    "maske", "parse", "regel",
]
