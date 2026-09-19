"""Zentrale Loop-/Repair-Aufsicht des Dialogkerns (DIALOG_CONTROLLER).

Der Reducer deckelt bereits WERKZEUG-Schleifen (Retry-Zaehler je Tool). Was
fehlt, ist der Schutz gegen die zweite Schleifenklasse: dieselbe INHALTLICHE
Frage wird Zug um Zug erneut gestellt, weil der Anrufer sie nicht (verwertbar)
beantwortet — genau die "keine Schleifen, keine Wiederholungen"-Vorgabe.

Diese Aufsicht ist eine reine Funktion und die LETZTE Station in ``reduce()``:
sie sieht die fertige ``Decision`` und darf sie durch GENAU EINEN von zwei
terminierenden Auswegen ersetzen, wenn eine Frage zu oft in Folge kam:

  1. Rueckblick (nur wenn ``policy.zusammenfassung_bei_stocken``): EINMAL fasst
     Bianca das schon Bekannte zusammen und stellt die Frage frisch — der
     Anrufer bekommt einen Anker, ohne dass die Schleife weiterlaeuft.
  2. Uebergabe/Rueckruf: hilft auch der Rueckblick nicht, endet die Aufgabe
     ehrlich mit einer Rueckruf-Notiz statt in einer Endlosschleife.

Gezaehlt werden NUR inhaltliche Fragen (nicht ``STEUER_FRAGEN`` wie Auswahl/
Anrufer-Check — deren Wiederholung regelt der Reducer selbst). Die Schwelle
kommt aus der Policy (``max_rueckfragen``); alles ist mandantenkonfigurierbar
und beruehrt die Reducer-Invarianten nicht.
"""

from __future__ import annotations

from bianca.controller.typen import (
    STEUER_FRAGEN,
    Decision,
    Naechste,
    Phase,
    Policy,
    SpeakSpec,
    SprechAkt,
    State,
    TaskState,
    TaskStatus,
)

# Sprechbare Kurzlabels fuer den Rueckblick ("Nachname: Meier, Anliegen: ...").
_LABEL: dict[str, str] = {
    "nachname": "Nachname",
    "vorname": "Vorname",
    "behandler": "Behandler",
    "besuchsgrund": "Anliegen",
    "wunschzeit": "Wunschzeit",
    "terminwahl": "Termin",
    "versicherung": "Versicherung",
    "telefon": "Telefonnummer",
    "fuer_wen": "für",
}
# Reihenfolge, in der bekannte Angaben im Rueckblick genannt werden.
_RECAP_ORDER: tuple[str, ...] = (
    "fuer_wen", "nachname", "vorname", "besuchsgrund",
    "behandler", "wunschzeit", "terminwahl", "versicherung",
)


def _recap(task: TaskState) -> str:
    """Kurzer, sprechbarer Rueckblick auf die schon belegten Angaben."""
    teile: list[str] = []
    for slot in _RECAP_ORDER:
        sv = task.slots.get(slot)
        if sv and sv.wert:
            teile.append(f"{_LABEL.get(slot, slot)}: {sv.wert}")
    return ", ".join(teile)


def _ist_unklar(decision: Decision) -> bool:
    """Der "das habe ich nicht verstanden"-Zug OHNE laufende Aufgabe."""
    sp = decision.speak
    return sp is not None and sp.akt == SprechAkt.INFO and sp.detail == "unklar"


def _unklar_aufsicht(
    ns: State, decision: Decision, policy: Policy
) -> tuple[State, Decision]:
    """Deckel fuer die Rueckfrage ohne Aufgabe (zweite Schleifenklasse).

    Ohne Aufgabe gibt es keine Frage-Id zum Zaehlen — der Zaehler haengt darum am
    State. Stufen wie beim Stocken einer Frage:

      <= budget      : die Rueckfrage darf kommen (Wortlaut rotiert ueber den Zug)
      == budget + 1  : EINMAL ausdruecklich zum Neuanfang bitten
      >= budget + 2  : an den Legacy-Pfad uebergeben statt weiter zu fragen
    """
    ns.unklar_folge += 1
    budget = policy.max_rueckfragen if policy.max_rueckfragen > 0 else 1
    if ns.unklar_folge <= budget:
        return ns, decision
    if ns.unklar_folge == budget + 1:
        return ns, Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(
                akt=SprechAkt.INFO,
                detail="unklar_neustart",
                fakten=(("zug", str(ns.zug_nr)),),
            ),
            grund="aufsicht:unklar_neustart",
        )
    # Kein dritter Anlauf mit derselben Bitte: der Legacy-Pfad uebernimmt
    # (dort haengen Stille-Regie, Notleine und Abschied).
    return ns, Decision(naechste=Naechste.UEBERGEBEN, grund="aufsicht:unklar_uebergabe")


def _ist_stockfrage(decision: Decision) -> str:
    """Inhaltliche Frage-Id der Entscheidung, oder "" (Steuerfragen zaehlen nie)."""
    sp = decision.speak
    if sp is None or sp.akt != SprechAkt.FRAGE:
        return ""
    fid = sp.frage_id or ""
    if not fid or fid in STEUER_FRAGEN:
        return ""
    return fid


def _rueckblick_decision(
    ns: State, task: TaskState, fid: str, basis: SpeakSpec
) -> tuple[State, Decision]:
    """EINE Zusammenfassung + dieselbe Frage frisch (Anker gegen die Schleife)."""
    fakten = list(basis.fakten)
    recap = _recap(task)
    if recap:
        fakten.append(("rueckblick", recap))
    return ns, Decision(
        naechste=Naechste.FRAGEN,
        speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id=fid, fakten=tuple(fakten), detail="rueckblick"),
        task=task.typ,
        grund=f"aufsicht:rueckblick:{fid}",
    )


def _uebergabe_decision(
    ns: State, task: TaskState, fid: str
) -> tuple[State, Decision]:
    """Terminaler, ehrlicher Ausweg: Rueckruf-Notiz statt Endlosschleife."""
    task.status = TaskStatus.GESCHEITERT
    task.phase = Phase.ABGESCHLOSSEN
    fakten: list[tuple[str, str]] = []
    for slot in ("nachname", "telefon"):
        sv = task.slots.get(slot)
        if sv and sv.wert:
            fakten.append((slot, sv.wert))
    return ns, Decision(
        naechste=Naechste.SPRECHEN,
        speak=SpeakSpec(akt=SprechAkt.RUECKRUF, fakten=tuple(fakten), detail="stocken"),
        task=task.typ,
        grund=f"aufsicht:uebergabe:{fid}",
    )


def ueberwachen(ns: State, decision: Decision, policy: Policy) -> tuple[State, Decision]:
    """Letzte Station in ``reduce()``: Frage-Schleifen erkennen und aufloesen.

    Mutiert nur die Zaehler der aktiven Aufgabe im (bereits kopierten) ``ns``.
    Gibt die urspruengliche Entscheidung zurueck, solange die Schwelle
    (``policy.max_rueckfragen``) nicht ueberschritten ist.
    """
    if _ist_unklar(decision):
        return _unklar_aufsicht(ns, decision, policy)
    # Jeder verwertbare Zug bricht die Unklar-Serie.
    ns.unklar_folge = 0

    task = ns.aktiv()
    if task is None:
        return ns, decision

    fid = _ist_stockfrage(decision)
    if not fid:
        # Jeder andere Zug (Werkzeug, Angebot, Erfolg, andere Frage) bricht die
        # Serie und gibt einen kuenftigen Rueckblick wieder frei.
        if task.stock_frage:
            task.stock_frage = ""
            task.stock_zahl = 0
            task.merker.pop("rueckblick_gesagt", None)
        return ns, decision

    if task.stock_frage == fid:
        task.stock_zahl += 1
    else:
        task.stock_frage = fid
        task.stock_zahl = 1

    # Eskalation allein am persistenten Zaehler festgemacht (``merker`` gehoert dem
    # Reducer und kann je Zug geleert werden — hier also bewusst NICHT benutzt):
    #   <= budget            : normal weiter (die Frage darf so oft kommen)
    #   == budget + 1        : EIN Rueckblick (wenn erlaubt), sonst schon Uebergabe
    #   >= budget + 2        : terminale Uebergabe/Rueckruf
    budget = policy.max_rueckfragen if policy.max_rueckfragen > 0 else 1
    if task.stock_zahl <= budget:
        return ns, decision
    if (
        policy.zusammenfassung_bei_stocken
        and task.stock_zahl == budget + 1
    ):
        return _rueckblick_decision(ns, task, fid, decision.speak)
    return _uebergabe_decision(ns, task, fid)
