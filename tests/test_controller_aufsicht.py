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


def test_steuerfrage_faellt_nicht_unter_das_inhaltliche_budget():
    # Eine Auswahl-/Steuerfrage darf oefter kommen als eine inhaltliche Frage
    # (ihre Wiederholung regelt der Reducer) — sie tragen darum den Praefix
    # ``steuer:`` und ein eigenes, grosszuegigeres Budget.
    from bianca.controller.aufsicht import _anker
    from bianca.controller.typen import Decision, SpeakSpec

    for fid in ("auswahl", "anrufer_check", "ziel", "aenderung"):
        d = Decision(
            naechste=Naechste.FRAGEN,
            speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id=fid),
        )
        assert _anker(d) == f"steuer:{fid}"


def test_steuerfrage_laeuft_in_den_harten_deckel():
    # Live lief "Rueckruf einrichten - ja oder nein?" 8x in Folge (nur der
    # Wortlaut rotierte). Beliebig oft darf auch eine Steuerfrage nicht kommen.
    from bianca.controller.aufsicht import _STEUER_DECKEL, ueberwachen
    from bianca.controller.typen import Decision, SpeakSpec

    pol = _pol()
    st = State()
    frage = Decision(
        naechste=Naechste.FRAGEN,
        speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id="rueckruf_ja"),
    )
    gruende: list[str] = []
    for _ in range(_STEUER_DECKEL + 2):
        st, d = ueberwachen(st, frage, pol)
        gruende.append(d.grund)
    # Innerhalb des Deckels unangetastet, danach greift die Aufsicht.
    assert all(not g.startswith("aufsicht:") for g in gruende[:_STEUER_DECKEL]), gruende
    assert any(g.startswith("aufsicht:") for g in gruende[_STEUER_DECKEL:]), gruende


def test_inhaltsfrage_wird_erkannt():
    from bianca.controller.aufsicht import _anker
    from bianca.controller.typen import Decision, SpeakSpec

    d = Decision(
        naechste=Naechste.FRAGEN,
        speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id="nachname"),
    )
    assert _anker(d) == "nachname"


# --------------------------------------------------------------------------- #
# Audit 19.09.2026 (538 echte Anrufe): 96 % der wortgleichen Wiederholungen
# waren KEINE Fragen — Ruecklesen 745x, Slot-Angebot 321x, "finde ich nichts"
# 96x. Ein Angebot lief 13x wortgleich durch, weil die Aufsicht nur auf
# SprechAkt.FRAGE schaute. Diese Akte muessen denselben Deckel haben.
# --------------------------------------------------------------------------- #


def _spec_angebot(*slots: str) -> SpeakSpec:
    from bianca.controller.typen import SpeakSpec as S

    return S(akt=SprechAkt.ANGEBOT, fakten=tuple(("slot", s) for s in slots))


def test_reaktionsakte_bekommen_einen_anker():
    from bianca.controller.aufsicht import _anker
    from bianca.controller.typen import Decision, SpeakSpec

    for akt in (SprechAkt.RUECKLESEN, SprechAkt.ANGEBOT, SprechAkt.EHRLICH_KEIN):
        d = Decision(naechste=Naechste.SPRECHEN, speak=SpeakSpec(akt=akt))
        assert _anker(d), akt


def test_terminale_akte_bekommen_nie_einen_anker():
    # Erfolg/Abschied/Uebergabe/Notfall/Warten beenden oder halten — nie deckeln.
    # RUECKRUF steht bewusst NICHT hier: die Notiz beendet den Anruf nicht, und
    # live kam sie 3x wortgleich in Folge (Audit 19.09.2026) — sie wird gedeckelt.
    from bianca.controller.aufsicht import _anker
    from bianca.controller.typen import Decision, SpeakSpec

    for akt in (
        SprechAkt.ERFOLG, SprechAkt.ABSCHIED,
        SprechAkt.UEBERGEBEN, SprechAkt.NOTFALL, SprechAkt.WARTEN,
    ):
        d = Decision(naechste=Naechste.SPRECHEN, speak=SpeakSpec(akt=akt))
        assert _anker(d) == "", akt


def test_erlaubte_wiederholung_klingt_nicht_wortgleich():
    """Die zweite Ruecklese darf kommen — aber nicht im selben Wortlaut.

    Audit 19.09.2026: 153 der 298 wortgleichen Wiederholungen waren genau diese
    eine erlaubte Wiederholung vor dem Rueckblick. Der Deckel bleibt unberuehrt
    (``nochmal`` ist ein fluechtiger Fakt), nur die Einleitung wechselt.
    """
    from bianca.controller import renderer
    from bianca.controller.aufsicht import _anker, ueberwachen
    from bianca.controller.typen import Decision, Policy, SpeakSpec, State

    st = State()
    pol = Policy()
    spec = SpeakSpec(
        akt=SprechAkt.RUECKLESEN,
        fakten=(("nachname", "Tannis"), ("zug", "1")),
    )
    d = Decision(naechste=Naechste.SPRECHEN, speak=spec)

    st, erst = ueberwachen(st, d, pol)
    st, zweit = ueberwachen(st, d, pol)

    t1, t2 = renderer.rendern(erst.speak), renderer.rendern(zweit.speak)
    assert t1 and t2 and t1 != t2, (t1, t2)
    assert "noch einmal" in t2.lower()
    # Der Zaehler zaehlt weiter dieselbe Aeusserung: gleicher Anker, Stufe 2.
    assert _anker(erst) == _anker(zweit)
    assert st.stock_zahl == 2


def test_wiederholte_rueckruf_notiz_wird_gedeckelt():
    """Dieselbe Notiz-Ansage laeuft in den Deckel statt endlos zu kommen."""
    from bianca.controller.aufsicht import ueberwachen
    from bianca.controller.typen import Decision, Policy, SpeakSpec, State

    st = State()
    pol = Policy(max_rueckfragen=2)
    d = Decision(
        naechste=Naechste.SPRECHEN,
        speak=SpeakSpec(akt=SprechAkt.RUECKRUF, fakten=(("nachname", "Meier"),)),
    )
    gruende: list[str] = []
    for _ in range(5):
        st, out = ueberwachen(st, d, pol)
        gruende.append(out.grund)
    assert any(g.startswith("aufsicht:") for g in gruende), gruende


def test_gleiches_angebot_hat_gleichen_anker_geaendertes_nicht():
    # Derselbe Wortlaut = Schleife. Ein GEAENDERTES Angebot ist Fortschritt und
    # muss den Zaehler zuruecksetzen, sonst deckelt die Aufsicht echte Arbeit.
    from bianca.controller.aufsicht import _anker
    from bianca.controller.typen import Decision

    a = Decision(naechste=Naechste.SPRECHEN, speak=_spec_angebot("Mo 9:00", "Mo 10:00"))
    b = Decision(naechste=Naechste.SPRECHEN, speak=_spec_angebot("Mo 9:00", "Mo 10:00"))
    c = Decision(naechste=Naechste.SPRECHEN, speak=_spec_angebot("Di 8:00"))
    assert _anker(a) == _anker(b)
    assert _anker(a) != _anker(c)


def test_variantenrotation_bricht_den_anker_nicht():
    # Der ``zug``-Fakt wechselt jeden Zug (Wortlaut-Rotation). Wuerde er in den
    # Fingerabdruck eingehen, waere jede Wiederholung "neu" und der Deckel tot.
    from bianca.controller.aufsicht import _anker
    from bianca.controller.typen import Decision, SpeakSpec

    def d(zug: str) -> Decision:
        return Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(
                akt=SprechAkt.ANGEBOT,
                fakten=(("slot", "Mo 9:00"), ("zug", zug)),
            ),
        )

    assert _anker(d("3")) == _anker(d("7"))


def test_gleicher_satz_aus_zwei_bauwegen_hat_denselben_anker():
    # Audit 19.09.2026, Anruf d7f485d7a3ba: dasselbe Slot-Angebot lief 9x
    # wortgleich durch, weil der Reducer es abwechselnd als frisches Angebot und
    # als Wiederholung baute (unterschiedliche Buchfuehrungs-Fakten, EIN Satz im
    # Ohr). Gezaehlt wird, was der Anrufer hoert.
    from bianca.controller.aufsicht import _anker
    from bianca.controller.typen import Decision, SpeakSpec

    slots = (("slot", "Mo 9:00"), ("slot", "Di 10:00"))
    frisch = Decision(
        naechste=Naechste.SPRECHEN,
        speak=SpeakSpec(akt=SprechAkt.ANGEBOT, fakten=slots),
    )
    nochmal = Decision(
        naechste=Naechste.SPRECHEN,
        speak=SpeakSpec(
            akt=SprechAkt.ANGEBOT,
            fakten=slots + (("gehoert_wunschzeit", "nachmittag"), ("zug", "4")),
        ),
    )
    assert _anker(frisch) == _anker(nochmal)


def test_bezug_aufs_gehoerte_bricht_den_anker_nicht():
    # Audit 19.09.2026, Anruf 2dcdbebefb03: dieselbe Ruecklese lief 7x durch,
    # weil der ``gehoert_*``-Bezug je Zug anders war. Der Satz war wortgleich.
    from bianca.controller.aufsicht import _anker
    from bianca.controller.typen import Decision, SpeakSpec

    def d(bezug: tuple[str, str]) -> Decision:
        return Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(
                akt=SprechAkt.RUECKLESEN,
                detail="nachname",
                fakten=(("nachname", "Meier"), bezug),
            ),
        )

    assert _anker(d(("gehoert_terminwahl", "Montag"))) == _anker(
        d(("gehoert_wunschzeit", "Oktober"))
    )


def test_wiederholtes_angebot_laeuft_in_rueckblick_und_dann_terminal():
    from bianca.controller.aufsicht import ueberwachen
    from bianca.controller.typen import Decision

    pol = _pol()
    budget = pol.max_rueckfragen
    # Aufgabe echt ueber den Reducer entstehen lassen (keine Handbau-Attrappe).
    st, _ = _fahre(pol, [ev(Intent.BUCHEN, {"schonmal": "ja"})])
    assert st.aktiv() is not None
    gruende: list[str] = []
    for _ in range(budget + 2):
        d = Decision(
            naechste=Naechste.SPRECHEN,
            speak=_spec_angebot("Mo 9:00"),
            task=st.aktiv().typ,
        )
        st, d = ueberwachen(st, d, pol)
        gruende.append(d.grund)
    # Innerhalb des Budgets unveraendert, dann EIN Rueckblick, dann terminal.
    assert all(not g.startswith("aufsicht:") for g in gruende[:budget]), gruende
    assert gruende[budget].startswith("aufsicht:rueckblick:angebot"), gruende
    assert gruende[budget + 1].startswith("aufsicht:uebergabe:angebot"), gruende


def test_wiederholung_ohne_aufgabe_wird_gedeckelt():
    """Anruf 357236c8edfa (Thaler): die Absage war gescheitert, also gab es keine
    aktive Aufgabe mehr — "Zu Ihrem Namen sehe ich keinen Termin" lief danach
    13x wortgleich durch, weil der Zaehler nur an der Aufgabe hing. Jetzt haengt
    er am State: Neustart-Bitte, dann Uebergabe."""
    from bianca.controller.aufsicht import ueberwachen
    from bianca.controller.typen import Decision, SpeakSpec

    pol = _pol()
    budget = pol.max_rueckfragen
    st = State()  # bewusst OHNE Aufgabe
    gruende: list[str] = []
    for _ in range(budget + 2):
        d = Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(akt=SprechAkt.EHRLICH_KEIN, detail="filter_kein_termin"),
        )
        st, d = ueberwachen(st, d, pol)
        gruende.append(d.grund)
        letzte = d
    assert all(not g.startswith("aufsicht:") for g in gruende[:budget]), gruende
    assert gruende[budget].startswith("aufsicht:neustart:"), gruende
    assert gruende[budget + 1].startswith("aufsicht:uebergabe:"), gruende
    assert letzte.naechste is Naechste.UEBERGEBEN


def test_rueckblick_wird_bei_jedem_akt_gesprochen():
    # Der Anker-Satz darf nicht nur an Fragen haengen (Renderer-Vertrag).
    from bianca.controller import renderer
    from bianca.controller.typen import SpeakSpec

    for akt in (SprechAkt.ANGEBOT, SprechAkt.RUECKLESEN, SprechAkt.FRAGE):
        spec = SpeakSpec(
            akt=akt,
            frage_id="nachname" if akt is SprechAkt.FRAGE else "",
            detail="rueckblick" if akt is SprechAkt.FRAGE else "",
            fakten=(("slot", "Mo 9:00"), ("rueckblick", "Nachname: Meier")),
        )
        text = renderer.rendern(spec)
        assert "fasse kurz zusammen" in text, (akt, text)
        assert "Nachname: Meier" in text, (akt, text)


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
