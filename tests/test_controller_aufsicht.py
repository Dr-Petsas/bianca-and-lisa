"""Loop-/Repair-Aufsicht: keine Frage-Schleifen (DIALOG_CONTROLLER).

Der Reducer deckelt Werkzeug-Schleifen (Retry je Tool). Die Aufsicht
(``bianca/controller/aufsicht.py``) deckelt die ZWEITE Klasse: dieselbe
INHALTLICHE Frage Zug um Zug, weil der Anrufer sie nicht verwertbar
beantwortet. Diese Tests nageln die "keine Schleifen, keine Wiederholungen"-
Garantie fest — konfigurierbar ueber ``max_rueckfragen`` /
``zusammenfassung_bei_stocken``, deterministisch, offline.
"""

from __future__ import annotations

from bianca.controller import policy as P
from bianca.controller.reducer import reduce
from bianca.controller.typen import (
    Intent,
    Naechste,
    Quelle,
    SemanticEvent,
    SlotValue,
    SprechAkt,
    State,
)


# --------------------------------------------------------------------------- #
# Bau-Helfer.
# --------------------------------------------------------------------------- #
def ev(intent, slots=None, roh=""):
    sv = {k: SlotValue(wert=v, quelle=Quelle.GESAGT) for k, v in (slots or {}).items()}
    return SemanticEvent(intent=intent, slots=sv, roh=roh)


def _pol(**tenant):
    base = {
        "clientId": "demo",
        "calendars": [{"id": "c1"}],
        "nachnameReadbackNachBuchstabieren": True,
    }
    base.update(tenant)
    return P.aus_tenant(base)


def _fahre(policy, schritte, *, start=None):
    st = start or State()
    decs = []
    for e in schritte:
        st, d = reduce(st, e, policy)
        decs.append(d)
    return st, decs


def _bis_nachname_stockt(n_stuck):
    """Pflicht bis auf Nachname beantworten, dann ``n_stuck`` Nicht-Antworten."""
    seq = [
        ev(Intent.BUCHEN, {"schonmal": "ja"}),
        ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle"}),
        ev(Intent.BUCHEN, {"wunschzeit": "morgen"}),
    ]
    seq += [ev(Intent.BUCHEN, {}, "aehm") for _ in range(n_stuck)]
    return seq


def _gruende(decs):
    return [d.grund for d in decs]


# --------------------------------------------------------------------------- #
# Kernverhalten: Wiederholung -> Rueckblick -> ehrliche Uebergabe.
# --------------------------------------------------------------------------- #
def test_wiederholte_frage_fuehrt_zu_rueckblick_dann_uebergabe():
    # Default max_rueckfragen=2: Frage darf bis stock_zahl 2 kommen, bei 3 EIN
    # Rueckblick, ab 4 terminale Uebergabe.
    _, decs = _fahre(_pol(), _bis_nachname_stockt(6))
    gr = _gruende(decs)
    assert any(g.startswith("aufsicht:rueckblick:nachname") for g in gr), gr
    assert any(g.startswith("aufsicht:uebergabe:nachname") for g in gr), gr
    # Der Rueckblick kommt VOR der Uebergabe.
    i_rb = next(i for i, g in enumerate(gr) if g.startswith("aufsicht:rueckblick"))
    i_ub = next(i for i, g in enumerate(gr) if g.startswith("aufsicht:uebergabe"))
    assert i_rb < i_ub


def test_rueckblick_kommt_pro_stau_genau_einmal():
    # Innerhalb EINER stockenden Frage (nachname) gibt es genau EINEN Rueckblick,
    # danach die Uebergabe — nie zwei Zusammenfassungen fuer dieselbe Frage.
    _, decs = _fahre(_pol(), _bis_nachname_stockt(8))
    rb_nn = [d for d in decs if d.grund == "aufsicht:rueckblick:nachname"]
    assert len(rb_nn) == 1, _gruende(decs)


def test_uebergabe_ist_terminal_rueckruf():
    st, decs = _fahre(_pol(), _bis_nachname_stockt(6))
    ueb = next(d for d in decs if d.grund.startswith("aufsicht:uebergabe"))
    assert ueb.naechste == Naechste.SPRECHEN
    assert ueb.speak is not None and ueb.speak.akt == SprechAkt.RUECKRUF
    assert ueb.speak.detail == "stocken"


def test_rueckblick_traegt_bekannte_angaben_als_fakt():
    _, decs = _fahre(_pol(), _bis_nachname_stockt(6))
    rb = next(d for d in decs if d.grund.startswith("aufsicht:rueckblick"))
    fakten = dict(rb.speak.fakten)
    assert "rueckblick" in fakten
    recap = fakten["rueckblick"]
    # Schon Bekanntes taucht auf (Anliegen/Wunschzeit), die offene Frage bleibt.
    assert "Kontrolle" in recap and "morgen" in recap
    assert rb.speak.frage_id == "nachname"
    assert rb.speak.detail == "rueckblick"


# --------------------------------------------------------------------------- #
# Konfigurierbarkeit ueber die Policy.
# --------------------------------------------------------------------------- #
def test_zusammenfassung_aus_fuehrt_direkt_zur_uebergabe():
    pol = _pol(dialogPolicy={"rueckfrage": {
        "max_rueckfragen": 2, "zusammenfassung_bei_stocken": False,
    }})
    _, decs = _fahre(pol, _bis_nachname_stockt(6))
    gr = _gruende(decs)
    assert not any(g.startswith("aufsicht:rueckblick") for g in gr), gr
    assert any(g.startswith("aufsicht:uebergabe") for g in gr), gr


def test_hoehere_schwelle_stellt_die_frage_oefter():
    # max_rueckfragen=3 (die harte Obergrenze) -> Frage bis stock_zahl 3 ohne Eingriff.
    pol = _pol(dialogPolicy={"rueckfrage": {"max_rueckfragen": 3}})
    _, decs = _fahre(pol, _bis_nachname_stockt(3))
    # Bei nur 3 Nicht-Antworten (stock 1..3) greift die Aufsicht noch nicht.
    assert not any(d.grund.startswith("aufsicht:") for d in decs), _gruende(decs)


# --------------------------------------------------------------------------- #
# Abgrenzung: keine falschen Positiven.
# --------------------------------------------------------------------------- #
def test_beantwortete_frage_bricht_die_serie():
    # Zwei Nicht-Antworten auf Nachname, dann die echte Antwort: kein Eingriff.
    seq = _bis_nachname_stockt(2)
    seq.append(ev(Intent.BUCHEN, {"nachname": "Meier"}))
    _, decs = _fahre(_pol(), seq)
    assert not any(d.grund.startswith("aufsicht:") for d in decs), _gruende(decs)


def test_glatter_buchungsfluss_ohne_aufsicht():
    seq = [
        ev(Intent.BUCHEN),
        ev(Intent.BUCHEN, {"schonmal": "ja"}),
        ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle"}),
        ev(Intent.BUCHEN, {"wunschzeit": "morgen"}),
        ev(Intent.BUCHEN, {"nachname": "Meier"}),
    ]
    _, decs = _fahre(_pol(), seq)
    assert not any(d.grund.startswith("aufsicht:") for d in decs), _gruende(decs)


def test_steuerfrage_wird_nie_als_schleife_gezaehlt():
    # Eine Auswahl-/Steuerfrage darf beliebig oft kommen, ohne Repair.
    from bianca.controller.aufsicht import _ist_stockfrage
    from bianca.controller.typen import Decision, SpeakSpec

    for fid in ("auswahl", "anrufer_check", "ziel", "aenderung"):
        d = Decision(
            naechste=Naechste.FRAGEN,
            speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id=fid),
        )
        assert _ist_stockfrage(d) == ""


def test_inhaltsfrage_wird_erkannt():
    from bianca.controller.aufsicht import _ist_stockfrage
    from bianca.controller.typen import Decision, SpeakSpec

    d = Decision(
        naechste=Naechste.FRAGEN,
        speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id="nachname"),
    )
    assert _ist_stockfrage(d) == "nachname"


def test_determinismus_gleicher_eingang_gleicher_ausgang():
    seq = _bis_nachname_stockt(6)
    _, a = _fahre(_pol(), seq)
    _, b = _fahre(_pol(), seq)
    assert _gruende(a) == _gruende(b)


# --------------------------------------------------------------------------- #
# Zweite Schleifenklasse: die Rueckfrage OHNE Aufgabe ("nicht verstanden").
# Ohne Aufgabe gibt es keine Frage-Id — der Deckel haengt am State
# (``unklar_folge``): Rueckfrage, EINMAL Neustart-Bitte, dann Uebergabe.
# --------------------------------------------------------------------------- #
def _unklar(n):
    return [ev(Intent.UNKLAR, {}, "haeh?") for _ in range(n)]


def test_unklar_endet_in_uebergabe_statt_endlos():
    _, decs = _fahre(_pol(), _unklar(8))
    gr = _gruende(decs)
    assert "aufsicht:unklar_neustart" in gr, gr
    assert "aufsicht:unklar_uebergabe" in gr, gr
    assert gr.index("aufsicht:unklar_neustart") < gr.index("aufsicht:unklar_uebergabe")
    # Ab der Uebergabe kommt keine Rueckfrage mehr zurueck.
    ab = gr[gr.index("aufsicht:unklar_uebergabe"):]
    assert all(g == "aufsicht:unklar_uebergabe" for g in ab), gr


def test_unklar_neustart_kommt_genau_einmal():
    _, decs = _fahre(_pol(), _unklar(8))
    gr = _gruende(decs)
    assert gr.count("aufsicht:unklar_neustart") == 1, gr


def test_unklar_uebergabe_geht_an_den_legacy_pfad():
    _, decs = _fahre(_pol(), _unklar(8))
    ueb = next(d for d in decs if d.grund == "aufsicht:unklar_uebergabe")
    # Kein erfundener Abschied: der bisherige Pfad uebernimmt (Stille-Regie dort).
    assert ueb.naechste == Naechste.UEBERGEBEN
    assert ueb.speak is None and not ueb.hangup


def test_unklar_schwelle_kommt_aus_der_policy():
    eng = _pol(dialogPolicy={"rueckfrage": {"max_rueckfragen": 1}})
    _, a = _fahre(eng, _unklar(3))
    weit = _pol(dialogPolicy={"rueckfrage": {"max_rueckfragen": 3}})
    _, b = _fahre(weit, _unklar(3))
    assert "aufsicht:unklar_uebergabe" in _gruende(a)
    # Mit weiter Schwelle darf die Rueckfrage dreimal kommen.
    assert not any(g.startswith("aufsicht:") for g in _gruende(b)), _gruende(b)


def test_unklar_serie_bricht_bei_verstandenem_zug():
    # Zwei unklare Zuege (Zaehler 2), dann ein echtes Anliegen: der Zaehler faellt
    # auf null. Ab da laeuft die Frage-Aufsicht der Aufgabe (stock_zahl), die
    # Unklar-Eskalation faengt bei einer spaeteren Serie frisch an.
    st, decs = _fahre(_pol(), _unklar(2))
    assert st.unklar_folge == 2, _gruende(decs)
    st, decs = _fahre(_pol(), [ev(Intent.BUCHEN, {"schonmal": "ja"})], start=st)
    assert st.unklar_folge == 0, _gruende(decs)
    assert not any(g.startswith("aufsicht:unklar") for g in _gruende(decs))


def test_unklar_rueckfragen_sind_nicht_wortgleich():
    from bianca.controller.renderer import rendern

    _, decs = _fahre(_pol(dialogPolicy={"rueckfrage": {"max_rueckfragen": 3}}), _unklar(3))
    saetze = [rendern(d.speak) for d in decs if d.speak is not None]
    assert len(set(saetze)) == len(saetze), saetze


# --------------------------------------------------------------------------- #
# Der Anrufer-Check ist eine STEUER_FRAGE (die Aufsicht zaehlt ihn nicht) —
# sein Deckel sitzt im Reducer: unklare Antworten verwerfen lieber den Treffer.
# --------------------------------------------------------------------------- #
def _mit_anrufer(**tenant):
    st = State()
    st.anrufer = {"vorname": "Anna", "nachname": "Meier", "geschlecht": "f"}
    return _pol(**tenant), st


def test_anrufer_check_wird_nicht_endlos_gefragt():
    pol, st = _mit_anrufer()
    seq = [ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle"})] + _unklar(6)
    st, decs = _fahre(pol, seq, start=st)
    checks = [d for d in decs
              if d.speak is not None and d.speak.frage_id == "anrufer_check"]
    assert len(checks) <= (pol.max_rueckfragen or 1), _gruende(decs)
    # Treffer verworfen: danach wird klassisch nach dem Namen gefragt.
    assert st.anrufer_ok is False and not st.anrufer
