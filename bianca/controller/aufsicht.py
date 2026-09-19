"""Zentrale Loop-/Repair-Aufsicht des Dialogkerns (DIALOG_CONTROLLER).

Der Reducer deckelt bereits WERKZEUG-Schleifen (Retry-Zaehler je Tool). Was
fehlt, ist der Schutz gegen die zweite Schleifenklasse: dieselbe INHALTLICHE
Aeusserung kommt Zug um Zug erneut, weil der Anrufer sie nicht (verwertbar)
beantwortet — genau die "keine Schleifen, keine Wiederholungen"-Vorgabe.

Gedeckelt wird JEDE Aeusserung, die eine Reaktion erwartet (``_ANKER_AKTE``),
nicht nur die Frage: der Audit vom 19.09.2026 ueber 538 echte Anrufe zeigte,
dass 96 % der wortgleichen Wiederholungen Ruecklesen, Slot-Angebote und
"da finde ich nichts" waren — die alte, nur auf ``FRAGE`` schauende Aufsicht
sah davon nichts (ein Angebot lief 13x wortgleich durch).

Diese Aufsicht ist eine reine Funktion und die LETZTE Station in ``reduce()``:
sie sieht die fertige ``Decision`` und darf sie durch GENAU EINEN von zwei
terminierenden Auswegen ersetzen, wenn eine Frage zu oft in Folge kam:

  1. Rueckblick (nur wenn ``policy.zusammenfassung_bei_stocken``): EINMAL fasst
     Bianca das schon Bekannte zusammen und stellt die Frage frisch — der
     Anrufer bekommt einen Anker, ohne dass die Schleife weiterlaeuft.
  2. Uebergabe/Rueckruf: hilft auch der Rueckblick nicht, endet die Aufgabe
     ehrlich mit einer Rueckruf-Notiz statt in einer Endlosschleife.

Bei Fragen zaehlen NUR inhaltliche (nicht ``STEUER_FRAGEN`` wie Auswahl/
Anrufer-Check — deren Wiederholung regelt der Reducer selbst). Die Schwelle
kommt aus der Policy (``max_rueckfragen``); alles ist mandantenkonfigurierbar
und beruehrt die Reducer-Invarianten nicht.
"""

from __future__ import annotations

from hashlib import blake2s

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
        return ns, _mit_nochmal(decision, ns.unklar_folge)
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


# Aeusserungen, die eine Reaktion des Anrufers erwarten und deshalb genauso
# stocken koennen wie eine Frage (Audit 19.09.2026 ueber 538 Echt-Anrufe: die
# wortgleichen Wiederholungen waren zu 96 % KEINE Fragen, sondern Ruecklesen
# 745x, Slot-Angebot 321x, "da finde ich nichts" 96x). ERFOLG/RUECKRUF/
# UEBERGEBEN/ABSCHIED/NOTFALL/WARTEN stehen bewusst nicht drin: sie beenden
# den Vorgang oder halten nur die Leitung.
_ANKER_AKTE: frozenset[SprechAkt] = frozenset({
    SprechAkt.RUECKLESEN, SprechAkt.ANGEBOT, SprechAkt.EHRLICH_KEIN, SprechAkt.INFO,
    # RUECKRUF beendet den Vorgang NICHT (die Leitung bleibt offen): live lief
    # "Ich habe eine Notiz fuer die Praxis gemacht" 3x in Folge. Zweimal ist die
    # ehrliche Wiederholung, danach gehoert der Anruf abgegeben.
    SprechAkt.RUECKRUF,
})
# Fakten, die je Zug wechseln, ohne den Inhalt der Aeusserung zu aendern
# (Variantenrotation, eingehaengter Rueckblick, Bezug auf das gerade Gehoerte,
# Plan-Vorsatz, letzter Besuch). Sie gehoeren NICHT in den Fingerabdruck:
# sonst waere jede wortgleiche Wiederholung "neu" und der Deckel griffe nie
# (Audit 19.09.2026, Anruf 2dcdbebefb03: dieselbe Ruecklese 7x, weil ein
# ``gehoert_*``-Fakt je Zug anders war).
_FLUECHTIGE_FAKTEN: frozenset[str] = frozenset({
    "zug", "rueckblick", "nochmal",
    # Wiederholung auf Zuruf bzw. nach Stille: faerbt nur die Einleitung.
    "wiederholt", "still",
})
_FLUECHTIGE_PRAEFIXE: tuple[str, ...] = ("gehoert_", "plan_", "letzter_")
# Steuerfragen fallen NICHT unter das inhaltliche Frage-Budget (ihre
# Wiederholung regelt der Reducer), brauchen aber eine harte Obergrenze: live
# lief "Rueckruf einrichten - ja oder nein?" 8x in Folge (nur der Wortlaut
# rotierte). Bewusst grosszuegig, damit legitime Steuerung nie beschnitten wird.
_STEUER_DECKEL = 4
# Gruende, bei denen die Wiederholung GEWOLLT ist (Bitte des Anrufers, Stille).
# Siehe ``ueberwachen``.
_AUF_ZURUF: tuple[str, ...] = ("meta:wiederholen", "meta:stille")


def _fluechtig(schluessel: str) -> bool:
    return schluessel in _FLUECHTIGE_FAKTEN or schluessel.startswith(_FLUECHTIGE_PRAEFIXE)


def _inhalt_fp(spec: SpeakSpec) -> str:
    """Fingerabdruck dessen, was der Anrufer HOERT — nicht der Buchfuehrung.

    Gezaehlt wird der gesprochene Satz, kanonisch gerendert: fluechtige Fakten
    (Bezug aufs Gehoerte, Rueckblick, Plan) fallen weg und die Variantenrotation
    wird auf ``zug=0`` festgenagelt. Damit ist "dieselbe Aeusserung" genau das,
    was auch der Anrufer als Wiederholung erlebt.

    Grund (Audit 19.09.2026, Anruf d7f485d7a3ba): dasselbe Slot-Angebot lief 9x
    wortgleich durch, weil der Reducer es abwechselnd als frisches Angebot und
    als ``wiederholen:angebot_offen`` baute — zwei Fakten-Saetze, EIN Satz im
    Ohr. Ueber die Fakten gezaehlt wechselten die Schluessel im A-B-A-B-Muster
    und der Zaehler sprang staendig auf 1 zurueck.
    """
    kanon = SpeakSpec(
        akt=spec.akt,
        frage_id=spec.frage_id,
        detail=spec.detail,
        fakten=tuple((k, v) for k, v in spec.fakten if not _fluechtig(k)) + (("zug", "0"),),
    )
    try:
        from bianca.controller import renderer as _renderer  # reine Praesentation

        schluessel = _renderer.rendern(kanon)
    except Exception:  # pragma: no cover — Fingerabdruck darf nie werfen
        schluessel = "|".join(sorted(f"{k}={v}" for k, v in kanon.fakten))
    return blake2s(schluessel.encode("utf-8"), digest_size=4).hexdigest()


def _anker(decision: Decision) -> str:
    """Stabiler Schluessel der Aeusserung, oder "" wenn sie nie stocken kann.

    Inhaltliche Fragen zaehlen ueber ihre ``frage_id``. Steuerfragen bekommen
    den Praefix ``steuer:`` — sie fallen nicht unter das inhaltliche Budget
    (ihre Wiederholung regelt der Reducer), laufen aber in den harten Deckel
    ``_STEUER_DECKEL``. Andere reaktionserwartende Akte zaehlen ueber Akt +
    Detail + Inhalt: ein GEAENDERTER Inhalt (neue Slots, anderer Ruecklese-Wert)
    ist Fortschritt und setzt den Zaehler zurueck — nur das wortgleiche
    Wiederholen laeuft in den Deckel.
    """
    sp = decision.speak
    if sp is None:
        return ""
    if sp.akt == SprechAkt.FRAGE:
        fid = sp.frage_id or ""
        if not fid:
            return ""
        return f"steuer:{fid}" if fid in STEUER_FRAGEN else fid
    if sp.akt not in _ANKER_AKTE:
        return ""
    # Die Unklar-Rueckfrage hat ihren eigenen Deckel (_unklar_aufsicht).
    if sp.akt == SprechAkt.INFO and (sp.detail or "").startswith("unklar"):
        return ""
    return f"{sp.akt.value}:{sp.detail or '-'}#{_inhalt_fp(sp)}"


def anker_label(anker: str) -> str:
    """Sprechbarer Teil eines Ankers (ohne Inhalts-Fingerabdruck) — fuer Anzeige."""
    return anker.split("#", 1)[0]


def _rueckblick_decision(
    ns: State, task: TaskState, anker: str, decision: Decision
) -> tuple[State, Decision]:
    """EINE Zusammenfassung, dann dieselbe Aeusserung frisch (Anker gegen die Schleife).

    Der Rueckblick haengt als Fakt ``rueckblick`` an der Aeusserung; den Vorsatz
    setzt der Renderer fuer JEDEN Akt (``rendern``), damit nicht nur Fragen,
    sondern auch Angebot und Ruecklesen einen Anker bekommen.
    """
    basis = decision.speak
    assert basis is not None  # _anker() liefert nur mit speak einen Schluessel
    fakten = list(basis.fakten)
    recap = _recap(task)
    if recap:
        fakten.append(("rueckblick", recap))
    # Fragen behalten ihr bisheriges Detail-Signal (Vertrag der Bestandstests),
    # alle anderen Akte ihr inhaltliches Detail — es steuert dort das Rendern.
    detail = "rueckblick" if basis.akt == SprechAkt.FRAGE else basis.detail
    return ns, Decision(
        naechste=decision.naechste,
        speak=SpeakSpec(
            akt=basis.akt,
            frage_id=basis.frage_id,
            fakten=tuple(fakten),
            detail=detail,
        ),
        task=task.typ,
        grund=f"aufsicht:rueckblick:{anker_label(anker)}",
    )


def _mit_nochmal(decision: Decision, zahl: int) -> Decision:
    """Wiederholung als Wiederholung kennzeichnen (Einleitung im Renderer)."""
    sp = decision.speak
    if sp is None or zahl < 2 or any(k == "nochmal" for k, _ in sp.fakten):
        return decision
    return Decision(
        naechste=decision.naechste,
        speak=SpeakSpec(
            akt=sp.akt,
            frage_id=sp.frage_id,
            detail=sp.detail,
            fakten=sp.fakten + (("nochmal", str(zahl)),),
        ),
        tool=decision.tool,
        task=decision.task,
        grund=decision.grund,
        hangup=decision.hangup,
    )


def _uebergabe_decision(
    ns: State, task: TaskState, anker: str
) -> tuple[State, Decision]:
    """Terminaler, ehrlicher Ausweg: Rueckruf-Notiz statt Endlosschleife."""
    task.status = TaskStatus.GESCHEITERT
    task.phase = Phase.ABGESCHLOSSEN
    # Nach der Notiz ist der Kern fertig — der naechste Zug geht an Legacy.
    ns.abgabe_faellig = True
    fakten: list[tuple[str, str]] = []
    for slot in ("nachname", "telefon"):
        sv = task.slots.get(slot)
        if sv and sv.wert:
            fakten.append((slot, sv.wert))
    return ns, Decision(
        naechste=Naechste.SPRECHEN,
        speak=SpeakSpec(akt=SprechAkt.RUECKRUF, fakten=tuple(fakten), detail="stocken"),
        task=task.typ,
        grund=f"aufsicht:uebergabe:{anker_label(anker)}",
    )


def ueberwachen(ns: State, decision: Decision, policy: Policy) -> tuple[State, Decision]:
    """Letzte Station in ``reduce()``: Frage-Schleifen erkennen und aufloesen.

    Mutiert nur die Zaehler der aktiven Aufgabe im (bereits kopierten) ``ns``.
    Gibt die urspruengliche Entscheidung zurueck, solange die Schwelle
    (``policy.max_rueckfragen``) nicht ueberschritten ist.
    """
    if ns.abgabe_faellig:
        # Die ehrliche Notiz ist gesprochen; alles weitere gehoert Legacy.
        return ns, Decision(naechste=Naechste.UEBERGEBEN, grund="aufsicht:nach_notiz")
    if decision.grund.startswith(_AUF_ZURUF):
        # Der Anrufer hat selbst um die Wiederholung gebeten ("Wie bitte?") oder
        # geschwiegen. Das ist keine Schleife der Maschine, und beide Wege haben
        # ihren eigenen Deckel im Reducer — hier weder zaehlen noch eskalieren,
        # sonst bestraft die Aufsicht genau das Nachfragen, das sie verhindern
        # soll. Der Zaehler bleibt stehen: die naechste echte Wiederholung derselben
        # Aeusserung laeuft normal weiter in den Deckel.
        return ns, decision
    if _ist_unklar(decision):
        return _unklar_aufsicht(ns, decision, policy)
    # Jeder verwertbare Zug bricht die Unklar-Serie.
    ns.unklar_folge = 0

    task = ns.aktiv()
    # Zwischenschritte OHNE Aeusserung (Werkzeugaufruf, stiller Halte-Zug) sind
    # Teil DESSELBEN Zuges und brechen die Serie nicht. Sonst zaehlt der Deckel
    # nie hoch, wenn zwischen zwei wortgleichen Saetzen ein Tool laeuft — genau
    # daran lief "Zu Ihrem Namen sehe ich keinen Termin" 13x durch (Audit
    # 19.09.2026, Anruf 357236c8edfa).
    if decision.speak is None or decision.speak.akt == SprechAkt.WARTEN:
        return ns, decision

    anker = _anker(decision)
    if not anker:
        # Eine andere ECHTE Aeusserung (Erfolg, Rueckruf, Abschied) ist
        # Fortschritt: Serie brechen und einen kuenftigen Rueckblick freigeben.
        ns.stock_anker, ns.stock_zahl = "", 0
        if task is not None and task.stock_frage:
            task.stock_frage = ""
            task.stock_zahl = 0
            task.merker.pop("rueckblick_gesagt", None)
        return ns, decision

    # Autoritativ am State zaehlen — eine beendete Aufgabe darf die Wiederholung
    # nicht ungedeckelt lassen (Audit 19.09.2026).
    if ns.stock_anker == anker:
        ns.stock_zahl += 1
    else:
        ns.stock_anker, ns.stock_zahl = anker, 1
    if task is not None:  # Spiegel fuer Anzeige/Replay
        task.stock_frage, task.stock_zahl = anker, ns.stock_zahl

    # Eskalation allein am persistenten Zaehler festgemacht (``merker`` gehoert dem
    # Reducer und kann je Zug geleert werden — hier also bewusst NICHT benutzt):
    #   <= budget            : normal weiter (die Aeusserung darf so oft kommen)
    #   == budget + 1        : EIN Rueckblick (wenn erlaubt), sonst schon Uebergabe
    #   >= budget + 2        : terminale Uebergabe/Rueckruf
    budget = policy.max_rueckfragen if policy.max_rueckfragen > 0 else 1
    if anker.startswith("steuer:"):
        # Steuerfragen (Auswahl, Anrufer-Check, Rueckruf ja/nein) duerfen oefter
        # kommen als eine inhaltliche Frage — aber nicht endlos.
        budget = max(budget, _STEUER_DECKEL)
    if ns.stock_zahl <= budget:
        # Die erlaubte Wiederholung darf nicht WORTGLEICH klingen (Audit
        # 19.09.2026: 153x dieselbe Ruecklese, 54x dasselbe Slot-Angebot).
        # ``nochmal`` ist ein fluechtiger Fakt — er faerbt nur die Einleitung,
        # der Fingerabdruck (und damit der Deckel) bleibt derselbe.
        return ns, _mit_nochmal(decision, ns.stock_zahl)
    if policy.zusammenfassung_bei_stocken and ns.stock_zahl == budget + 1:
        if task is not None:
            return _rueckblick_decision(ns, task, anker, decision)
        # Ohne Aufgabe gibt es nichts zusammenzufassen: EINMAL ausdruecklich
        # zum Neuanfang bitten, statt denselben Satz noch einmal zu sagen.
        return ns, Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(
                akt=SprechAkt.INFO,
                detail="unklar_neustart",
                fakten=(("zug", str(ns.zug_nr)),),
            ),
            grund=f"aufsicht:neustart:{anker_label(anker)}",
        )
    if task is not None:
        return _uebergabe_decision(ns, task, anker)
    return ns, Decision(
        naechste=Naechste.UEBERGEBEN, grund=f"aufsicht:uebergabe:{anker_label(anker)}"
    )
