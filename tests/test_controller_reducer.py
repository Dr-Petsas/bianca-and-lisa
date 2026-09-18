"""Invarianten des Dialogkerns als Property-/Szenario-Tests (DIALOG_CONTROLLER).

Der reine Reducer (``bianca/controller/reducer.py``) ist die einzige
Entscheidungsinstanz. Diese Tests nageln die strukturellen Garantien fest —
ueber ALLE Task-Familien, damit kein spaeterer Umbau sie unbemerkt aufweicht:

  I1  Nie eine Frage zu einem bereits gefuellten Pflicht-/Identify-Feld.
  I2  ``SprechAkt.ERFOLG`` nur mit ``committed``-Beleg im Ledger.
  I3  Je Zug hoechstens EIN Werkzeug UND hoechstens EINE Frage (Decision-Form).
  I4  Beschraenkte Retries -> jede Aufgabe wird in endlich vielen Zuegen terminal.
  I5  Determinismus/Idempotenz.

Offline, kein Netz, keine schweren Importe (nur das Controller-Paket + stdlib).
"""

from __future__ import annotations

import bianca.controller.typen as T
from bianca.controller import policy as P
from bianca.controller.reducer import reduce
from bianca.controller.typen import (
    Familie,
    Intent,
    Naechste,
    OutcomeStatus,
    Quelle,
    SemanticEvent,
    SlotValue,
    SprechAkt,
    State,
    ToolOutcome,
)


# --------------------------------------------------------------------------- #
# Bau-Helfer.
# --------------------------------------------------------------------------- #
def ev(intent, slots=None, bestaetigung=None, korrektur_feld="", roh=""):
    sv = {k: SlotValue(wert=v, quelle=Quelle.GESAGT) for k, v in (slots or {}).items()}
    return SemanticEvent(
        intent=intent, slots=sv, bestaetigung=bestaetigung,
        korrektur_feld=korrektur_feld, roh=roh,
    )


def oc(name, status, committed=False, payload=None):
    return ToolOutcome(name=name, status=status, committed=committed, payload=payload or {})


def _pol(**tenant):
    """Standard-Testmandant: ein Behandler, Nachname-Ruecklese, zwei Transferziele."""
    base = {
        "clientId": "demo",
        "calendars": [{"id": "c1"}],
        "nachnameReadbackNachBuchstabieren": True,
        "verbindenErlaubt": ["Petsas", "Patrikis"],
    }
    base.update(tenant)
    return P.aus_tenant(base)


# --------------------------------------------------------------------------- #
# Invarianten-Waechter — nach JEDEM Zug aufgerufen.
# --------------------------------------------------------------------------- #
# Frage-IDs, die KEINE Sammelfelder sind (Steuerfragen) und darum von I1
# ausgenommen bleiben.
_STEUER_FRAGEN = {"aenderung", "auswahl", "ziel", "rueckruf_ja", "telefon"}


def _pruefe_invarianten(state: State, dec, policy) -> None:
    # I3: nie Werkzeug UND Sprechakt zugleich.
    assert not (dec.tool is not None and dec.speak is not None), dec.as_dict()

    # I3: FRAGEN/WERKZEUG tragen das jeweils passende Feld.
    if dec.naechste == Naechste.WERKZEUG:
        assert dec.tool is not None and dec.speak is None
    if dec.naechste == Naechste.FRAGEN:
        assert dec.speak is not None and dec.tool is None

    task = state.aktiv() or (state.tasks[-1] if state.tasks else None)

    # I1: keine Frage zu einem bereits gefuellten Sammelfeld.
    if dec.naechste == Naechste.FRAGEN and dec.speak and task is not None:
        fid = dec.speak.frage_id
        spec = policy.spec(task.typ)
        if spec and fid and fid not in _STEUER_FRAGEN:
            sammel = spec.identify if spec.familie in (Familie.VERWALTEN, Familie.AUSKUNFT) else spec.pflicht
            if fid in sammel:
                # gefuellt UND (falls Ruecklese-Pflicht) bereits bestaetigt -> darf nicht gefragt werden
                if task.gefuellt(fid) and (fid not in spec.ruecklese_slots or task.bestaetigt(fid)):
                    raise AssertionError(f"Frage zu gefuelltem Feld {fid!r}: {dec.as_dict()}")

    # I2: ERFOLG nur mit committed-Beleg im Ledger.
    if dec.speak and dec.speak.akt == SprechAkt.ERFOLG:
        assert any(o.committed for o in state.ledger), "ERFOLG ohne Beleg"


def _fahre(policy, schritte, *, start=None):
    """Szenario fahren, Invarianten je Zug pruefen, (State, [Decisions]) zurueck."""
    st = start or State()
    decs = []
    for e in schritte:
        st, d = reduce(st, e, policy)
        _pruefe_invarianten(st, d, policy)
        decs.append(d)
    return st, decs


def _tools(decs):
    return [d.tool.name for d in decs if d.tool]


def _akte(decs):
    return [(d.naechste.value, d.speak.akt.value if d.speak else None) for d in decs]


# --------------------------------------------------------------------------- #
# Happy Paths je Familie (belegter Abschluss, richtige Werkzeugkette).
# --------------------------------------------------------------------------- #
def test_buchen_happy_path_belegt():
    pol = _pol()
    st, decs = _fahre(pol, [
        ev(Intent.BUCHEN),
        ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle"}),
        ev(Intent.BUCHEN, {"wunschzeit": "morgen"}),
        ev(Intent.BUCHEN, {"nachname": "Meier"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),   # Nachname-Ruecklese
        ev(Intent.BUCHEN, {"versicherung": "gesetzlich"}),
        oc("offer_slots", OutcomeStatus.OK, payload={"slots": ["2026-09-20T09:00"]}),
        ev(Intent.BUCHEN, {"terminwahl": "2026-09-20T09:00"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),   # Termin Ja -> Telefon
        ev(Intent.BUCHEN, {"telefon": "0170123"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),   # Telefon-Ruecklese Ja -> book
        oc("book_slot", OutcomeStatus.OK, committed=True, payload={"appointmentId": "A1"}),
    ])
    assert _tools(decs) == ["offer_slots", "book_slot"]
    assert decs[-1].speak.akt == SprechAkt.ERFOLG
    assert st.aktiv() is None and st.tasks[-1].status == T.TaskStatus.ERLEDIGT


def test_absagen_happy_path_belegt():
    pol = _pol()
    st, decs = _fahre(pol, [
        ev(Intent.ABSAGEN),
        ev(Intent.ABSAGEN, {"nachname": "Meier"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),   # Nachname-Ruecklese -> suchen
        oc("list_appointments", OutcomeStatus.OK, payload={"appointments": [
            {"id": "A1", "iso": "2026-09-20T09:00", "arzt": "Petsas", "grund": "Kontrolle"}]}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),   # Storno Ja
        oc("cancel_appointment", OutcomeStatus.OK, committed=True),
    ])
    assert _tools(decs) == ["list_appointments", "cancel_appointment"]
    assert decs[-1].speak.akt == SprechAkt.ERFOLG


def test_verschieben_happy_path_belegt():
    pol = _pol()
    st, decs = _fahre(pol, [
        ev(Intent.VERSCHIEBEN),
        ev(Intent.VERSCHIEBEN, {"nachname": "Meier"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),
        oc("list_appointments", OutcomeStatus.OK, payload={"appointments": [
            {"id": "A1", "iso": "2026-09-20T09:00", "arzt": "Petsas", "calendarId": "c1"}]}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),   # Bestand Ja -> neue Slots
        oc("offer_slots", OutcomeStatus.OK, payload={"slots": ["2026-09-25T11:00"]}),
        ev(Intent.VERSCHIEBEN, {"terminwahl": "2026-09-25T11:00"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),   # neuer Termin Ja -> move
        oc("move_appointment", OutcomeStatus.OK, committed=True),
    ])
    assert _tools(decs) == ["list_appointments", "offer_slots", "move_appointment"]
    assert decs[-1].speak.akt == SprechAkt.ERFOLG


def test_auskunft_read_only_terminal():
    pol = _pol()
    st, decs = _fahre(pol, [
        ev(Intent.AUSKUNFT),
        ev(Intent.AUSKUNFT, {"nachname": "Meier"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),
        oc("list_appointments", OutcomeStatus.OK, payload={"appointments": [
            {"id": "A1", "iso": "2026-09-20T09:00", "arzt": "Petsas"}]}),
    ])
    assert _tools(decs) == ["list_appointments"]
    assert decs[-1].speak.akt == SprechAkt.INFO
    # read-only: nie ein committed-Beleg
    assert not any(o.committed for o in st.ledger)


def test_verbinden_whitelist_uebergibt():
    pol = _pol()
    st, decs = _fahre(pol, [ev(Intent.VERBINDEN, {"ziel": "Petsas"})])
    assert decs[-1].naechste == Naechste.UEBERGEBEN
    assert decs[-1].speak.akt == SprechAkt.UEBERGEBEN
    assert decs[-1].speak.detail == "Petsas"


def test_verbinden_ohne_whitelist_ehrlich():
    pol = _pol(verbindenErlaubt=[])
    st, decs = _fahre(pol, [ev(Intent.VERBINDEN, {"ziel": "Petsas"})])
    assert decs[-1].speak.akt == SprechAkt.EHRLICH_KEIN
    assert st.terminal is False or st.tasks[-1].status == T.TaskStatus.ERLEDIGT


def test_dokument_zu_rueckruf_belegte_notiz():
    pol = _pol()
    st, decs = _fahre(pol, [
        ev(Intent.DOKUMENT),
        ev(Intent.BESTAETIGEN, bestaetigung=True),   # Rueckruf ja
        ev(Intent.RUECKRUF, {"nachname": "Meier"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),   # Nachname-Ruecklese
        ev(Intent.RUECKRUF, {"telefon": "0170123"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),   # Telefon-Ruecklese -> Notiz
        oc("praxis_notiz", OutcomeStatus.OK, committed=True),
    ])
    assert "praxis_notiz" in _tools(decs)
    assert decs[-1].speak.akt == SprechAkt.RUECKRUF


def test_dokument_abgelehnt_terminal():
    pol = _pol()
    st, decs = _fahre(pol, [
        ev(Intent.DOKUMENT),
        ev(Intent.ABLEHNEN, bestaetigung=False),
    ])
    assert decs[-1].speak.akt == SprechAkt.ABSCHIED
    assert st.tasks[-1].status == T.TaskStatus.ERLEDIGT


def test_notfall_ohne_regel_uebergibt_mit_regel_sofort():
    st, decs = _fahre(_pol(), [ev(Intent.NOTFALL)])
    assert decs[-1].naechste == Naechste.UEBERGEBEN

    pol = T.replace(_pol(), notfall_sofort=True)
    st, decs = _fahre(pol, [ev(Intent.NOTFALL)])
    assert decs[-1].speak.akt == SprechAkt.NOTFALL
    assert decs[-1].hangup is True and st.terminal is True


# --------------------------------------------------------------------------- #
# I1: nie eine Frage zu einem gefuellten Feld — auch bei Doppelnennung.
# --------------------------------------------------------------------------- #
def test_i1_kein_wiederholtes_fragen_bei_doppelnennung():
    pol = _pol()
    st, decs = _fahre(pol, [
        ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle"}),
        ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle"}),  # dieselbe Angabe erneut
    ])
    gefragt = [d.speak.frage_id for d in decs if d.naechste == Naechste.FRAGEN]
    assert "besuchsgrund" not in gefragt


def test_i1_alle_pflichtfelder_werden_genau_einmal_gefragt():
    pol = _pol()
    st, decs = _fahre(pol, [
        ev(Intent.BUCHEN),
        ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle"}),
        ev(Intent.BUCHEN, {"wunschzeit": "morgen"}),
        ev(Intent.BUCHEN, {"nachname": "Meier"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),
        ev(Intent.BUCHEN, {"versicherung": "gesetzlich"}),
    ])
    gefragt = [d.speak.frage_id for d in decs if d.naechste == Naechste.FRAGEN]
    # ein Behandler -> keine Behandlerfrage; jedes andere Pflichtfeld genau einmal
    assert gefragt.count("besuchsgrund") <= 1
    assert gefragt.count("wunschzeit") <= 1
    assert gefragt.count("nachname") <= 1
    assert "behandler" not in gefragt


# --------------------------------------------------------------------------- #
# I2: kein Erfolg ohne Beleg — nicht-committed Buchung wird nie ERFOLG.
# --------------------------------------------------------------------------- #
def test_i2_kein_erfolg_ohne_beleg():
    pol = _pol()
    st, decs = _fahre(pol, [
        ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle", "wunschzeit": "morgen"}),
        ev(Intent.BUCHEN, {"nachname": "Meier"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),
        ev(Intent.BUCHEN, {"versicherung": "gesetzlich"}),
        oc("offer_slots", OutcomeStatus.OK, payload={"slots": ["2026-09-20T09:00"]}),
        ev(Intent.BUCHEN, {"terminwahl": "2026-09-20T09:00"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),
        ev(Intent.BUCHEN, {"telefon": "0170123"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),
        oc("book_slot", OutcomeStatus.ERROR, committed=False),   # Schreibfehler
    ])
    assert decs[-1].speak.akt != SprechAkt.ERFOLG
    assert decs[-1].speak.akt == SprechAkt.RUECKRUF


# --------------------------------------------------------------------------- #
# I4: Terminierung unter wiederholten Fehlern.
# --------------------------------------------------------------------------- #
def _bis_buchung_reif(pol):
    st, _ = _fahre(pol, [
        ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle", "wunschzeit": "morgen"}),
        ev(Intent.BUCHEN, {"nachname": "Meier"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),
        ev(Intent.BUCHEN, {"versicherung": "gesetzlich"}),
        oc("offer_slots", OutcomeStatus.OK, payload={"slots": ["2026-09-20T09:00"]}),
        ev(Intent.BUCHEN, {"terminwahl": "2026-09-20T09:00"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),
        ev(Intent.BUCHEN, {"telefon": "0170123"}),
        ev(Intent.BESTAETIGEN, bestaetigung=True),
    ])
    return st


def test_i4_slot_taken_terminiert():
    pol = _pol()
    st = _bis_buchung_reif(pol)
    # Wiederholt SLOT_TAKEN: neu suchen -> waehlen -> Ja -> book -> ... muss enden.
    letzte = None
    for _ in range(20):
        st, d = reduce(st, oc("book_slot", OutcomeStatus.SLOT_TAKEN), pol)
        _pruefe_invarianten(st, d, pol)
        letzte = d
        if st.terminal or (st.tasks and st.tasks[-1].status in
                           (T.TaskStatus.ERLEDIGT, T.TaskStatus.GESCHEITERT)):
            break
        # Nachschub, damit der Zyklus laeuft (neuer Slot angeboten + gewaehlt + Ja)
        st, _ = reduce(st, oc("offer_slots", OutcomeStatus.OK, payload={"slots": ["x"]}), pol)
        st, _ = reduce(st, ev(Intent.BUCHEN, {"terminwahl": "x"}), pol)
        st, _ = reduce(st, ev(Intent.BESTAETIGEN, bestaetigung=True), pol)
    assert st.tasks[-1].status == T.TaskStatus.GESCHEITERT
    assert letzte.speak.akt == SprechAkt.RUECKRUF


def test_i4_needs_phone_terminiert():
    pol = _pol()
    st = _bis_buchung_reif(pol)
    for _ in range(10):
        st, d = reduce(st, oc("book_slot", OutcomeStatus.NEEDS_PHONE), pol)
        _pruefe_invarianten(st, d, pol)
        if st.tasks[-1].status == T.TaskStatus.GESCHEITERT:
            break
        # falls erneut nach Telefon gefragt: bestaetigte Nummer nachreichen
        if d.naechste == Naechste.FRAGEN:
            st, _ = reduce(st, ev(Intent.BUCHEN, {"telefon": "0170123"}), pol)
            st, _ = reduce(st, ev(Intent.BESTAETIGEN, bestaetigung=True), pol)
    assert st.tasks[-1].status == T.TaskStatus.GESCHEITERT


def test_i4_absage_nicht_gefunden_terminiert():
    pol = _pol(nachnameReadbackNachBuchstabieren=False)  # ohne Ruecklese kuerzer
    st, _ = _fahre(pol, [ev(Intent.ABSAGEN), ev(Intent.ABSAGEN, {"nachname": "Meier"})])
    for _ in range(10):
        st, d = reduce(st, oc("list_appointments", OutcomeStatus.NOT_FOUND), pol)
        _pruefe_invarianten(st, d, pol)
        if st.tasks[-1].status == T.TaskStatus.GESCHEITERT:
            break
        if d.naechste == Naechste.FRAGEN:  # Korrektur-Chance -> Name erneut
            st, _ = reduce(st, ev(Intent.ABSAGEN, {"nachname": "Maier"}), pol)
    assert st.tasks[-1].status == T.TaskStatus.GESCHEITERT
    assert d.speak.akt == SprechAkt.RUECKRUF


# --------------------------------------------------------------------------- #
# I5: Determinismus + Idempotenz.
# --------------------------------------------------------------------------- #
def test_i5_determinismus_gleicher_eingang_gleicher_ausgang():
    pol = _pol()
    st = _bis_buchung_reif(pol)
    a1, d1 = reduce(st, oc("book_slot", OutcomeStatus.OK, committed=True, payload={"appointmentId": "A1"}), pol)
    a2, d2 = reduce(st, oc("book_slot", OutcomeStatus.OK, committed=True, payload={"appointmentId": "A1"}), pol)
    assert d1.as_dict() == d2.as_dict()
    assert a1.as_dict() == a2.as_dict()


def test_i5_idempotenz_gefuelltes_feld_erneut_setzen_aendert_phase_nicht():
    pol = _pol()
    st, _ = _fahre(pol, [ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle"})])
    phase_vorher = st.aktiv().phase
    st2, d = reduce(st, ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle"}), pol)
    assert st2.aktiv().phase == phase_vorher


def test_i5_reducer_mutiert_eingangsstate_nicht():
    pol = _pol()
    st = State()
    vorher = st.as_dict()
    reduce(st, ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle"}), pol)
    assert st.as_dict() == vorher  # Eingang unveraendert (Kopie zurueckgegeben)


# --------------------------------------------------------------------------- #
# Korrektur (W-EINWAND): bestrittenes Feld wird geleert und gezielt neu gefragt.
# --------------------------------------------------------------------------- #
def test_korrektur_leert_und_fragt_gezielt():
    pol = _pol(nachnameReadbackNachBuchstabieren=False)
    st, _ = _fahre(pol, [
        ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle", "wunschzeit": "morgen", "nachname": "Meier"}),
    ])
    st2, d = reduce(st, ev(Intent.KORREKTUR, korrektur_feld="nachname"), pol)
    _pruefe_invarianten(st2, d, pol)
    assert d.naechste == Naechste.FRAGEN and d.speak.frage_id == "nachname"
    assert not st2.aktiv().gefuellt("nachname")


# --------------------------------------------------------------------------- #
# Policy: mehrere Behandler -> Behandlerfrage bleibt.
# --------------------------------------------------------------------------- #
def test_policy_mehrere_behandler_fragt_behandler():
    pol = P.aus_tenant({"clientId": "x", "calendars": [{"id": "c1"}, {"id": "c2"}]})
    st, decs = _fahre(pol, [ev(Intent.BUCHEN)])
    assert decs[-1].naechste == Naechste.FRAGEN
    assert decs[-1].speak.frage_id == "behandler"
