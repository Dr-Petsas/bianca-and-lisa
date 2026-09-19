"""W-BEFEHLSLISTE: ein Satz, mehrere Auftraege (19.09.2026).

Chef: "Befehlsliste — ordnen gibt statt EINEM SemanticEvent eine Liste zurueck,
der Reducer legt mehrere Tasks auf den Stapel. Das ist die eine Aenderung, die
mehrteilige Anliegen erst moeglich macht."

Live sagte der Anrufer "Ich habe einen Termin und will ihn absagen ... okay,
dann moechte ich einen buchen" in ZWEI Zuegen, weil der erste Satz nur den
ersten Auftrag trug. Wer beides in EINEM Satz sagt, soll beides bekommen:
der erste Auftrag laeuft, der zweite wartet geparkt und wird danach von selbst
aufgenommen (``_naechste_geparkte`` — dieselbe Mechanik wie beim Dritttermin).

Die Gegenproben sind der wichtigere Teil: ein falscher Nachtrag faengt spaeter
von SELBST eine Absage oder Buchung an, die niemand wollte.
"""

from __future__ import annotations

from dataclasses import replace

from bianca.controller import anliegen, policy as P, verstehen
from bianca.controller.orchestrator import TestGespraech
from bianca.controller.reducer import nachtragen
from bianca.controller.typen import (
    Intent,
    SemanticEvent,
    State,
    TaskState,
    TaskStatus,
)


# ------------------------------------------------------------ Erkennung


def test_absagen_und_neu_buchen_ist_zwei_auftraege():
    assert anliegen.befehlsfolge(
        "Ich moechte meinen Termin absagen und einen neuen ausmachen"
    ) == ["absagen", "buchen"]


def test_reihenfolge_folgt_dem_satz():
    assert anliegen.befehlsfolge(
        "Erst einen neuen Termin vereinbaren, den alten dann verschieben"
    ) == ["buchen", "verschieben"]


def test_ein_einzelner_auftrag_bleibt_einer():
    assert anliegen.befehlsfolge("Ich moechte meinen Termin absagen") == ["absagen"]
    assert anliegen.befehlsfolge("Ich haette gern einen Termin") == []


def test_dieselbe_familie_zweimal_zaehlt_einmal():
    assert anliegen.befehlsfolge(
        "Den Termin absagen, und den anderen auch absagen"
    ) == ["absagen"]


# ------------------------------------------------------------ Nachtraege


def _ev(intent: Intent) -> SemanticEvent:
    return SemanticEvent(intent=intent, deutung="hirn")


def test_nachtrag_nur_fuer_die_weiteren_familien():
    aus = verstehen.nachtraege(
        "Termin absagen und einen neuen ausmachen", ev=_ev(Intent.ABSAGEN)
    )
    assert [e.intent for e in aus] == [Intent.BUCHEN]
    assert all(e.deutung == "nachtrag" for e in aus)


def test_kein_nachtrag_auf_einer_offenen_janein_frage():
    # "Ja, und den anderen absagen" gehoert der offenen Frage — ein geparkter
    # Auftrag daraus waere geraten.
    assert verstehen.nachtraege(
        "Ja, und den anderen absagen und einen neuen buchen",
        erwartet_janein=True,
        ev=_ev(Intent.BESTAETIGEN),
    ) == []


def test_kein_nachtrag_auf_einer_offenen_wahl():
    assert verstehen.nachtraege(
        "Den frueheren, und dann den anderen absagen und neu buchen",
        erwartet_wahl=True,
        ev=_ev(Intent.BESTAETIGEN),
    ) == []


def test_kein_nachtrag_aus_einer_meta_bitte():
    assert verstehen.nachtraege(
        "Wie bitte?", ev=SemanticEvent(intent=Intent.WIEDERHOLEN, deutung="meta")
    ) == []


def test_nachtrag_kappt_bei_zwei():
    aus = verstehen.nachtraege(
        "Termin absagen, einen neuen ausmachen und den dritten verschieben",
        ev=_ev(Intent.ABSAGEN),
    )
    assert len(aus) <= 2


# ------------------------------------------------------------ Reducer


def _mit_aktiv(typ: str) -> State:
    s = State()
    s.tasks.append(TaskState(typ=typ, status=TaskStatus.AKTIV))
    return s


def test_reducer_parkt_den_nachtrag():
    s = nachtragen(_mit_aktiv("absagen"), [_ev(Intent.BUCHEN)], P.default())
    assert [(t.typ, t.status) for t in s.tasks] == [
        ("absagen", TaskStatus.AKTIV),
        ("buchen", TaskStatus.GEPARKT),
    ]


def test_reducer_parkt_nie_die_laufende_art():
    s = nachtragen(_mit_aktiv("absagen"), [_ev(Intent.ABSAGEN)], P.default())
    assert len(s.tasks) == 1


def test_reducer_parkt_nicht_doppelt():
    s = _mit_aktiv("absagen")
    s.tasks.append(TaskState(typ="buchen", status=TaskStatus.GEPARKT))
    aus = nachtragen(s, [_ev(Intent.BUCHEN)], P.default())
    assert [t.typ for t in aus.tasks] == ["absagen", "buchen"]


def test_reducer_parkt_nichts_ohne_laufende_aufgabe():
    # Ist der ERSTE Auftrag noch nicht verstanden, gibt es keinen zweiten.
    aus = nachtragen(State(), [_ev(Intent.BUCHEN)], P.default())
    assert aus.tasks == []


def test_reducer_parkt_nichts_nach_dem_auflegen():
    s = _mit_aktiv("absagen")
    s.terminal = True
    assert len(nachtragen(s, [_ev(Intent.BUCHEN)], P.default()).tasks) == 1


def test_reducer_parkt_nur_was_der_mandant_im_kern_fuehrt():
    pol = replace(P.default(), eigene_tasks=frozenset({"absagen"}))
    s = nachtragen(_mit_aktiv("absagen"), [_ev(Intent.BUCHEN)], pol)
    assert [t.typ for t in s.tasks] == ["absagen"]


# ------------------------------------------------------------ Ende zu Ende


def test_gespraech_nimmt_den_zweiten_auftrag_von_selbst_auf():
    g = TestGespraech(P.default())
    g.eingabe("Ich moechte meinen Termin absagen und einen neuen ausmachen")
    assert [t.typ for t in g.state.geparkt()] == ["buchen"]
    # Die Absage laeuft ganz normal weiter — der Nachtrag spricht nichts.
    assert g.verlauf[-1]["bianca"]


def test_ein_auftrag_legt_nichts_auf_den_stapel():
    g = TestGespraech(P.default())
    g.eingabe("Ich moechte meinen Termin absagen")
    assert g.state.geparkt() == []
