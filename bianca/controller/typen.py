"""Geschlossene, JSON-kompatible Typen des Dialogkerns (DIALOG_CONTROLLER).

Dieses Modul ist ABSICHTLICH abhaengigkeitsfrei (nur stdlib). Es beschreibt die
gesamte Sprache, in der Reducer, NLU und Tool-Gateway miteinander reden:

  Eingang  : ``SemanticEvent`` (Anrufer-Zug, gedeutet) ODER ``ToolOutcome``
             (normalisiertes Werkzeug-Ergebnis).
  Zustand  : ``State`` mit einem Task-Stapel aus ``TaskState``.
  Ausgang  : ``Decision`` — hoechstens EIN Werkzeug UND hoechstens EINE Frage
             (strukturell erzwungen: je genau ein Feld ``tool`` bzw. ``speak``).

Warum das die heutigen Fehlklassen strukturell verhindert:
  - "Frage zu bereits gefuelltem Feld": Fragen entstehen NUR aus der ersten
    unbefuellten Pflicht-Slot-Position (siehe reducer). Ein SprechAkt traegt
    genau eine ``frage_id``.
  - "Erfolg ohne Beleg": ``SprechAkt.ERFOLG`` darf der Reducer nur setzen, wenn
    im Ledger ein ``ToolOutcome`` mit ``committed=True`` fuer die Schreibaktion
    liegt. Der Sprechakt traegt keine Prosa, nur belegte Fakten.
  - "Endlosschleife": jeder Task fuehrt Retry-Zaehler; ist die Obergrenze
    erreicht, ist der einzige erlaubte Ausgang ein terminaler Sprechakt
    (Rueckruf-Notiz / ehrliche Absage / Uebergabe).

Alle Typen sind ueber ``as_dict()`` JSON-serialisierbar (Enums sind ``str``),
damit Shadow-Laeufe Zustaende und Entscheidungen protokollieren koennen.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping


# --------------------------------------------------------------------------- #
# Herkunft eines Fakts — eine Angabe wird NIE erfunden.
# --------------------------------------------------------------------------- #
class Quelle(str, Enum):
    GESAGT = "gesagt"          # der Anrufer hat es in diesem Gespraech gesagt
    AKTE = "akte"              # Patientenkartei
    ANRUFER_CF = "anrufer_cf"  # Rufnummernerkennung (Cloud Function)
    KALENDER = "kalender"      # Kalender-/Slot-Antwort
    KATALOG = "katalog"        # Besuchsgrund-Katalog der Praxis
    LEDGER = "tool_ledger"     # belegtes Werkzeug-Ergebnis
    ABGELEITET = "abgeleitet"  # deterministisch aus anderem Fakt gefolgert


@dataclass(frozen=True)
class SlotValue:
    """Ein einzelner Fakt mit Herkunft und Bestaetigungsstand."""

    wert: str
    quelle: Quelle
    bestaetigt: bool = False   # per Ruecklese vom Anrufer bestaetigt
    confidence: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "wert": self.wert,
            "quelle": self.quelle.value,
            "bestaetigt": self.bestaetigt,
            "confidence": round(float(self.confidence), 3),
        }


# --------------------------------------------------------------------------- #
# Eingang 1: gedeuteter Anrufer-Zug.
# --------------------------------------------------------------------------- #
class Intent(str, Enum):
    BUCHEN = "buchen"
    ABSAGEN = "absagen"
    VERSCHIEBEN = "verschieben"
    AUSKUNFT = "auskunft"
    VERBINDEN = "verbinden"
    RUECKRUF = "rueckruf"
    DOKUMENT = "dokument"
    ANMELDUNG = "anmeldung"
    PRAXISINFO = "praxisinfo"
    KORREKTUR = "korrektur"
    BESTAETIGEN = "bestaetigen"
    ABLEHNEN = "ablehnen"
    ABSCHIED = "abschied"
    SMALLTALK = "smalltalk"
    NOTFALL = "notfall"
    UNKLAR = "unklar"


@dataclass(frozen=True)
class SemanticEvent:
    """Das EINZIGE, was ein Anrufer-Zug in den Reducer traegt.

    ``slots`` sind geerntete Feld-Updates; ``bestaetigung`` ist die Ja/Nein-
    Antwort auf eine offene Frage (``None`` = weder noch). ``korrektur_feld``
    benennt bei Intent ``KORREKTUR`` das bestrittene Feld (W-EINWAND).
    ``roh`` dient NUR dem Protokoll und darf nie als Fakt verwendet werden.
    """

    intent: Intent
    slots: Mapping[str, SlotValue] = field(default_factory=dict)
    bestaetigung: bool | None = None
    korrektur_feld: str = ""
    roh: str = ""
    deutung: str = ""  # hirn | formular | nlu — wer das Event gebaut hat
    llm: str = ""  # Rohtext des Modells (Dock-Anzeige); nie als Fakt lesen
    verstanden: str = ""  # freier Verstehensvorlauf; Vorbezug, keine Schublade

    def as_dict(self) -> dict[str, Any]:
        return {
            "art": "event",
            "intent": self.intent.value,
            "slots": {k: v.as_dict() for k, v in self.slots.items()},
            "bestaetigung": self.bestaetigung,
            "korrektur_feld": self.korrektur_feld,
            "roh": self.roh,
            "deutung": self.deutung,
            "llm": self.llm,
            "verstanden": self.verstanden,
        }


@dataclass(frozen=True)
class Verstand:
    """Freier Verstehensvorlauf — noch keine Schublade.

    Das Modell sagt in eigenen Worten, was der Anrufer will, plus konkret
    Genanntes. ``ordnen`` macht daraus erst das SemanticEvent.
    """

    verstanden: str = ""
    janein: bool | None = None
    genannt: Mapping[str, str] = field(default_factory=dict)
    korrektur_feld: str = ""
    hint: str = ""
    roh: str = ""
    llm: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "art": "verstand",
            "verstanden": self.verstanden,
            "janein": self.janein,
            "genannt": dict(self.genannt),
            "korrektur_feld": self.korrektur_feld,
            "hint": self.hint,
            "roh": self.roh,
            "llm": self.llm,
        }


# --------------------------------------------------------------------------- #
# Werkzeuge: Befehl raus, normalisiertes Ergebnis rein.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ToolCommand:
    """Ein einziger Werkzeug-Befehl. Bindungen (Kalender/Motiv) getrennt von Args."""

    name: str
    args: Mapping[str, str] = field(default_factory=dict)
    bindings: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "args": dict(self.args), "bindings": dict(self.bindings)}


class OutcomeStatus(str, Enum):
    OK = "ok"
    NEEDS_PHONE = "needs_phone"
    SLOT_TAKEN = "slot_taken"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    EMPTY = "empty"                # z. B. keine Slots im Fenster
    CALENDAR_ERROR = "calendar_error"
    DENIED = "denied"             # z. B. telefonisch nicht buchbar
    ERROR = "error"


@dataclass(frozen=True)
class ToolOutcome:
    """Normalisiertes Werkzeug-Ergebnis. ``committed`` ist der EINZIGE Erfolgsbeweis.

    ``committed`` steht nur auf True, wenn ein Schreibvorgang durch Read-after-
    write bestaetigt ist (Buchung/Storno/Verschiebung/Notiz). Lesewerkzeuge
    (offer_slots, list_appointments) sind nie ``committed``; ihr Nutzen liegt in
    ``payload`` (z. B. angebotene Slots).
    """

    name: str
    status: OutcomeStatus
    committed: bool = False
    payload: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "art": "outcome",
            "name": self.name,
            "status": self.status.value,
            "committed": self.committed,
            "payload": dict(self.payload),
        }


Event = SemanticEvent | ToolOutcome


# --------------------------------------------------------------------------- #
# Ausgang: strukturierte Sprech-Absicht (NIE Prosa).
# --------------------------------------------------------------------------- #
class SprechAkt(str, Enum):
    FRAGE = "frage"            # genau eine offene Frage (frage_id)
    RUECKLESEN = "ruecklesen"  # Rueckbestaetigung vor Schreibaktion
    ANGEBOT = "angebot"        # Slot-Angebot vorlesen
    ERFOLG = "erfolg"          # belegten Schreiberfolg bestaetigen
    EHRLICH_KEIN = "ehrlich_kein"  # ehrlich "geht telefonisch/aktuell nicht"
    RUECKRUF = "rueckruf"      # terminaler Rueckruf-Vermerk
    UEBERGEBEN = "uebergeben"  # Weiterleitung ankuendigen
    NOTFALL = "notfall"        # Notfall-Sofortregel
    INFO = "info"              # Praxis-Auskunft aus belegten Fakten
    WARTEN = "warten"          # stiller Halte-Zug (Halbsatz/Ansage)
    ABSCHIED = "abschied"      # freundlicher Abschluss


# Steuer-/Ablauffragen: sie treiben den Dialog, sind aber keine inhaltlichen
# Pflicht-Slots. Sie werden NICHT in ``State.gefragt`` verbucht und von der
# Loop-Aufsicht (controller/aufsicht.py) NICHT als "stockende" Frage gezaehlt —
# ihre Wiederholung regelt der Reducer selbst (Angebot/Auswahl/Anrufer-Check).
STEUER_FRAGEN: frozenset[str] = frozenset({
    "aenderung", "auswahl", "ziel", "rueckruf_ja", "anmeldung_rueckruf",
    "anrufer_check", "auskunft_klar", "fach_weiter",
    "arzt_notiz", "termin_hinweis", "mehrfach_ok",
})


@dataclass(frozen=True)
class SpeakSpec:
    """Was gesagt werden soll — als Absicht, nicht als Satz.

    Der Renderer (spaeterer Baustein) formt daraus deutschen Text. Weil hier nur
    Absicht + belegte Fakten stehen, kann keine Ausgabewache mehr noetig sein:
    ein Feld kann nicht "erfunden" werden, das nicht in ``fakten`` steht.
    """

    akt: SprechAkt
    frage_id: str = ""
    fakten: tuple[tuple[str, str], ...] = ()
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "akt": self.akt.value,
            "frage_id": self.frage_id,
            "fakten": [list(x) for x in self.fakten],
            "detail": self.detail,
        }


class Naechste(str, Enum):
    FRAGEN = "fragen"
    WERKZEUG = "werkzeug"
    SPRECHEN = "sprechen"
    WARTEN = "warten"
    UEBERGEBEN = "uebergeben"
    AUFLEGEN = "auflegen"


@dataclass(frozen=True)
class Decision:
    """Die eine Entscheidung eines Zugs. Hoechstens ein Werkzeug, eine Frage."""

    naechste: Naechste
    speak: SpeakSpec | None = None
    tool: ToolCommand | None = None
    task: str = ""
    hangup: bool = False
    grund: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "naechste": self.naechste.value,
            "speak": self.speak.as_dict() if self.speak else None,
            "tool": self.tool.as_dict() if self.tool else None,
            "task": self.task,
            "hangup": self.hangup,
            "grund": self.grund,
        }


# --------------------------------------------------------------------------- #
# Zustand: Task-Stapel + belegtes Ledger.
# --------------------------------------------------------------------------- #
class Phase(str, Enum):
    SAMMELN = "sammeln"          # Pflicht-Slots erfragen
    ANGEBOT = "angebot"          # Slots angeboten, Wahl offen
    BESTAETIGEN = "bestaetigen"  # Rueckgelesen, Ja/Nein offen
    ABGESCHLOSSEN = "abgeschlossen"


class TaskStatus(str, Enum):
    AKTIV = "aktiv"
    GEPARKT = "geparkt"
    ERLEDIGT = "erledigt"
    GESCHEITERT = "gescheitert"


@dataclass
class TaskState:
    """Der Stand EINER Aufgabe (buchen/absagen/...)."""

    typ: str
    status: TaskStatus = TaskStatus.AKTIV
    phase: Phase = Phase.SAMMELN
    slots: dict[str, SlotValue] = field(default_factory=dict)
    retries: dict[str, int] = field(default_factory=dict)
    zuletzt_gefragt: str = ""
    # Reducer-interne Etappenmarker (JSON-sicher), z. B. Ruecklese-Stand.
    merker: dict[str, bool] = field(default_factory=dict)
    # Loop-/Repair-Aufsicht: welche inhaltliche Frage haengt gerade fest und
    # wie oft in Folge wurde sie schon gestellt? (siehe controller/aufsicht.py)
    stock_frage: str = ""
    stock_zahl: int = 0

    def gefuellt(self, slot: str) -> bool:
        v = self.slots.get(slot)
        return bool(v and v.wert)

    def bestaetigt(self, slot: str) -> bool:
        v = self.slots.get(slot)
        return bool(v and v.wert and v.bestaetigt)

    def kopie(self) -> "TaskState":
        return TaskState(
            typ=self.typ,
            status=self.status,
            phase=self.phase,
            slots=dict(self.slots),
            retries=dict(self.retries),
            zuletzt_gefragt=self.zuletzt_gefragt,
            merker=dict(self.merker),
            stock_frage=self.stock_frage,
            stock_zahl=self.stock_zahl,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "typ": self.typ,
            "status": self.status.value,
            "phase": self.phase.value,
            "slots": {k: v.as_dict() for k, v in self.slots.items()},
            "retries": dict(self.retries),
            "zuletzt_gefragt": self.zuletzt_gefragt,
            "merker": dict(self.merker),
            "stock_frage": self.stock_frage,
            "stock_zahl": self.stock_zahl,
        }


# --------------------------------------------------------------------------- #
# Mandanten-Politik: Verhalten ist DATEN, nicht Code.
#
# Der Reducer ist mandantenAGNOSTISCH. Jeder mandantenspezifische Unterschied
# (Slot-Reihenfolge, Retry-Grenzen, Transfer-Whitelist, Notfall-Regel,
# Buchstabier-/Ruecklese-Politik) lebt HIER als typisierter Wert und wird pro
# Zug in den Reducer hineingereicht. So aendert ein Mandanten-Fix nur dessen
# Policy — der Reducer und seine Invarianten bleiben unberuehrt.
# --------------------------------------------------------------------------- #
class Familie(str, Enum):
    """Ablauf-Form einer Aufgabe. Bestimmt, welche Reducer-Maschine greift."""

    BUCHEN = "buchen"        # sammeln -> offer_slots -> wahl -> ruecklese -> book_slot
    VERWALTEN = "verwalten"  # identify -> suchen -> waehlen -> (destruktiv) commit
    AUSKUNFT = "auskunft"    # identify -> suchen -> vorlesen (read-only)
    VERBINDEN = "verbinden"  # Policy-Whitelist -> Uebergabe ODER ehrlich nein
    DOKUMENT = "dokument"    # ehrlich "nicht am Telefon" -> optional Rueckruf
    RUECKRUF = "rueckruf"    # sammeln (Name/Telefon) -> Notiz (belegt)
    NOTFALL = "notfall"      # Sofortregel (Policy) -> terminal


@dataclass(frozen=True)
class TaskSpec:
    """Ablauf-Spezifikation EINER Aufgabe — pro Mandant gebaut (Verhalten = DATEN)."""

    typ: str
    familie: Familie = Familie.BUCHEN
    # Buchen: geordnete Pflicht-Slots der Sammelphase (Telefon separat, zuletzt).
    pflicht: tuple[str, ...] = ()
    # Verwalten/Auskunft: Mindest-Angaben zur Termin-/Patientensuche.
    identify: tuple[str, ...] = ("nachname",)
    such_tool: str = ""       # z. B. list_appointments
    offer_tool: str = ""      # z. B. offer_slots (buchen, verschieben-neu)
    commit_tool: str = ""     # book_slot | cancel_appointment | move_appointment
    notiz_tool: str = "praxis_notiz"
    telefon_slot: str = "telefon"
    # Felder, die vor Verwendung eine Ruecklese-Bestaetigung brauchen
    # (z. B. Ruether/Blessing: Nachname buchstabieren + rueckbestaetigen).
    ruecklese_slots: tuple[str, ...] = ()
    destruktiv: bool = False  # Schreibaktion braucht ausdrueckliches Ja (Storno/Move)
    neue_zeit: bool = False   # Verschieben: nach Identify neuen Slot suchen
    max_commit_retries: int = 2
    max_phone_retries: int = 1
    max_such_retries: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "typ": self.typ,
            "familie": self.familie.value,
            "pflicht": list(self.pflicht),
            "identify": list(self.identify),
            "such_tool": self.such_tool,
            "offer_tool": self.offer_tool,
            "commit_tool": self.commit_tool,
            "notiz_tool": self.notiz_tool,
            "telefon_slot": self.telefon_slot,
            "ruecklese_slots": list(self.ruecklese_slots),
            "destruktiv": self.destruktiv,
            "neue_zeit": self.neue_zeit,
            "max_commit_retries": self.max_commit_retries,
            "max_phone_retries": self.max_phone_retries,
            "max_such_retries": self.max_such_retries,
        }


@dataclass(frozen=True)
class Policy:
    """Alles, was der Reducer ueber DIESEN Mandanten wissen muss — als Daten."""

    mandant: str = ""
    fach_id: str = "allgemein"
    specs: Mapping[str, TaskSpec] = field(default_factory=dict)
    # Aufgaben, die der Kern selbst fuehrt (Rest -> Uebergabe an Legacy).
    eigene_tasks: frozenset[str] = frozenset()
    # Weiterleitung nur an diese Ziele; leer = telefonisch nie durchstellen.
    transfer_erlaubt: tuple[str, ...] = ()
    # Notfall-Sofortregel aktiv (DB-Marker); sonst kein Notfall-Sonderweg.
    notfall_sofort: bool = False

    # --- Konfigurierbare Gespraechs-Projektion (aus DialogPolicyV1) ---------- #
    # Alle Defaults reproduzieren das bisherige Verhalten byte-genau: ein neues
    # Feld aendert nie etwas, solange keine Policy es setzt.
    knapp: bool = False
    ein_thema: bool = True
    presence_einmal: bool = True
    eingehen: bool = True
    max_stupse: int = 2
    mehrfach_absage: bool = True
    termin_zuerst: bool = True
    antwort_knapp: bool = False
    sonst_noch_nur_nach_erfolg: bool = False
    max_rueckfragen: int = 2
    zusammenfassung_bei_stocken: bool = True
    # Herkunft/Version der eingelesenen Policy (nur fuer Protokoll/Shadow).
    policy_revision: int = 0

    def spec(self, typ: str) -> TaskSpec | None:
        return self.specs.get(typ)

    def fuehrt(self, typ: str) -> bool:
        return typ in self.eigene_tasks

    def transfer_ziel(self, wunsch: str) -> str:
        """Erlaubtes Transfer-Ziel zum Wunsch, oder "". Leere Whitelist -> nie."""
        w = " ".join(str(wunsch or "").lower().split())
        if not w or not self.transfer_erlaubt:
            return ""
        for ziel in self.transfer_erlaubt:
            z = str(ziel).lower()
            if z and (z in w or w in z):
                return ziel
        # Genau EIN erlaubtes Ziel und ein Verbinde-Wunsch ohne Namen -> dieses Ziel.
        if len(self.transfer_erlaubt) == 1:
            return self.transfer_erlaubt[0]
        return ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "mandant": self.mandant,
            "fach_id": self.fach_id,
            "specs": {k: v.as_dict() for k, v in self.specs.items()},
            "eigene_tasks": sorted(self.eigene_tasks),
            "transfer_erlaubt": list(self.transfer_erlaubt),
            "notfall_sofort": self.notfall_sofort,
            "knapp": self.knapp,
            "ein_thema": self.ein_thema,
            "presence_einmal": self.presence_einmal,
            "eingehen": self.eingehen,
            "max_stupse": self.max_stupse,
            "mehrfach_absage": self.mehrfach_absage,
            "termin_zuerst": self.termin_zuerst,
            "antwort_knapp": self.antwort_knapp,
            "sonst_noch_nur_nach_erfolg": self.sonst_noch_nur_nach_erfolg,
            "max_rueckfragen": self.max_rueckfragen,
            "zusammenfassung_bei_stocken": self.zusammenfassung_bei_stocken,
            "policy_revision": self.policy_revision,
        }


@dataclass
class State:
    """Autoritativer Controller-Zustand. Der Reducer gibt IMMER eine Kopie zurueck."""

    tasks: list[TaskState] = field(default_factory=list)
    ledger: list[ToolOutcome] = field(default_factory=list)
    terminal: bool = False
    zug_nr: int = 0
    anmeldung_gesagt: int = 0
    # Zweites Bestehen auf Anmeldung: naechstes Ja oeffnet den Rueckruf.
    anmeldung_rueckruf_offen: bool = False
    # Gespraechsgedaechtnis: belegte Angaben und schon gestellte Fragen.
    bekannt: dict[str, SlotValue] = field(default_factory=dict)
    gefragt: set[str] = field(default_factory=set)
    # Erkannter Anrufer (CF-pre / Dock-Szenario). None = noch nicht geprueft.
    anrufer: dict[str, str] = field(default_factory=dict)
    anrufer_ok: bool | None = None
    anrufer_gefragt: bool = False
    letzter_besuch: dict[str, str] = field(default_factory=dict)
    bezug_gesagt: bool = False
    auskunft_klar_offen: bool = False
    fach_thema: str = ""
    fach_weiter_offen: bool = False
    letzte_termine: list[dict[str, Any]] = field(default_factory=list)

    # -- Aktive Aufgabe -------------------------------------------------- #
    def aktiv(self) -> TaskState | None:
        for t in reversed(self.tasks):
            if t.status == TaskStatus.AKTIV:
                return t
        return None

    def geparkt(self) -> list[TaskState]:
        return [t for t in self.tasks if t.status == TaskStatus.GEPARKT]

    def letzter_write(self) -> str:
        """Belegte Schreibaktion, auf die sich Folgefragen beziehen."""
        for t in reversed(self.tasks):
            if t.status == TaskStatus.ERLEDIGT and t.typ in (
                "absagen", "verschieben", "buchen",
            ):
                return t.typ
        namen = {
            "cancel_appointment": "absagen",
            "book_slot": "buchen",
            "move_appointment": "verschieben",
        }
        for o in reversed(self.ledger):
            art = namen.get(o.name)
            if art and o.committed:
                return art
        return ""

    # -- Belege ---------------------------------------------------------- #
    def hat_beleg(self, tool_name: str) -> bool:
        return any(o.name == tool_name and o.committed for o in self.ledger)

    def letztes_ergebnis(self, tool_name: str) -> ToolOutcome | None:
        for o in reversed(self.ledger):
            if o.name == tool_name:
                return o
        return None

    def kopie(self) -> "State":
        return State(
            tasks=[t.kopie() for t in self.tasks],
            ledger=list(self.ledger),
            terminal=self.terminal,
            zug_nr=self.zug_nr,
            anmeldung_gesagt=self.anmeldung_gesagt,
            anmeldung_rueckruf_offen=self.anmeldung_rueckruf_offen,
            bekannt=dict(self.bekannt),
            gefragt=set(self.gefragt),
            anrufer=dict(self.anrufer),
            anrufer_ok=self.anrufer_ok,
            anrufer_gefragt=self.anrufer_gefragt,
            letzter_besuch=dict(self.letzter_besuch),
            bezug_gesagt=self.bezug_gesagt,
            auskunft_klar_offen=self.auskunft_klar_offen,
            fach_thema=self.fach_thema,
            fach_weiter_offen=self.fach_weiter_offen,
            letzte_termine=[dict(a) for a in self.letzte_termine],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "tasks": [t.as_dict() for t in self.tasks],
            "ledger": [o.as_dict() for o in self.ledger],
            "terminal": self.terminal,
            "zug_nr": self.zug_nr,
            "anmeldung_gesagt": self.anmeldung_gesagt,
            "anmeldung_rueckruf_offen": self.anmeldung_rueckruf_offen,
            "bekannt": {k: v.as_dict() for k, v in self.bekannt.items()},
            "gefragt": sorted(self.gefragt),
            "anrufer": dict(self.anrufer),
            "anrufer_ok": self.anrufer_ok,
            "anrufer_gefragt": self.anrufer_gefragt,
            "letzter_besuch": dict(self.letzter_besuch),
            "bezug_gesagt": self.bezug_gesagt,
            "auskunft_klar_offen": self.auskunft_klar_offen,
            "fach_thema": self.fach_thema,
            "fach_weiter_offen": self.fach_weiter_offen,
            "letzte_termine": [dict(a) for a in self.letzte_termine],
        }


__all__ = [
    "Quelle", "SlotValue",
    "Intent", "SemanticEvent",
    "ToolCommand", "OutcomeStatus", "ToolOutcome", "Event",
    "SprechAkt", "SpeakSpec", "Naechste", "Decision",
    "Phase", "TaskStatus", "TaskState", "State",
    "Familie", "TaskSpec", "Policy",
    "replace",
]
