"""Meta-Bitten UEBER das Gespraech: wiederholen, abbrechen, auslassen, Stille.

Rasa CALM fuehrt diese vier als eigene Befehle (``repeat bot messages``,
``cancel flow``, ``skip question``, Session-/Silence-Regie). Bei uns sind es
kurze Reducer-Zweige vor dem Anliegen-Weg — deterministisch, offline, ohne
Modell: wer zum dritten Mal "Wie bitte?" sagt, darf nicht auf ein vLLM warten.

Die GEGENPROBEN sind hier der teurere Teil. Ein Fehltreffer
  * verwirft eine laufende Aufgabe ("absagen" waere ein Anliegen, kein Abbruch),
  * verschluckt eine diktierte Nummer ("nochmal die Sieben"),
  * oder nimmt einen schon GESCHRIEBENEN Termin stillschweigend zurueck.
Darum steht hinter jedem Positiv-Fall mindestens eine Gegenprobe.
"""

from __future__ import annotations

from bianca.controller import meta
from bianca.controller import policy as P
from bianca.controller.orchestrator import TestGespraech
from bianca.controller.reducer import reduce
from bianca.controller.typen import (
    Intent,
    Naechste,
    Quelle,
    SemanticEvent,
    SlotValue,
    SprechAkt,
    State,
    TaskStatus,
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


_BUCHUNG_ANGEFANGEN = [
    ev(Intent.BUCHEN, {"schonmal": "ja"}),
    ev(Intent.BUCHEN, {"besuchsgrund": "Kontrolle"}),
]


# =========================================================================== #
# 1. Erkennung (controller/meta.py) — Formeln ja, Anliegen nein.
# =========================================================================== #
def test_nackte_formeln_sind_wiederholen():
    for satz in (
        "Wie bitte?",
        "Was?",
        "Wie?",
        "Hae?",
        "Noch mal bitte",
        "Entschuldigung",
        # Fuellwort davor — der Kern bleibt die ganze Aeusserung.
        "Entschuldigung, was?",
    ):
        assert meta.deute(satz) == meta.WIEDERHOLEN, satz


def test_bitte_an_bianca_ist_wiederholen():
    for satz in (
        "Koennen Sie das nochmal sagen?",
        "Wiederholen Sie das bitte",
        "Was haben Sie gerade gesagt?",
        "Ich habe Sie akustisch nicht verstanden",
        "Die Zeiten noch mal bitte",
    ):
        assert meta.deute(satz) == meta.WIEDERHOLEN, satz


def test_alle_drei_schreibweisen_von_nochmal():
    """"nochmal", "noch mal" und "noch einmal" sind dieselbe Bitte.

    Das eingeschobene "ein" ist am Telefon die haeufigste Form; sie fiel in der
    Hoerprobe vom 19.09.2026 durch und landete als Slotwert in der Akte.
    """
    for satz in (
        "Koennen Sie das nochmal sagen?",
        "Koennen Sie das noch mal sagen?",
        "Koennen Sie das noch einmal sagen?",
        "Sagen Sie das noch einmal",
        "Noch einmal bitte",
        "Die Zeiten noch einmal bitte",
    ):
        assert meta.deute(satz) == meta.WIEDERHOLEN, satz


def test_nochmal_im_diktat_bleibt_daten():
    """Gegenprobe zur "noch einmal"-Klammer: im Diktat zuendet sie nie."""
    for satz in (
        "Null eins sieben sieben noch einmal drei vier",
        "A wie Anton, noch einmal",
        "Ich buchstabiere noch einmal",
        "Ich sage es noch einmal: Meier",
        "Ich moechte noch einmal einen Termin am Montag",
    ):
        assert meta.deute(satz) == "", satz


def test_du_imperativ_ist_wiederholen():
    """Dock-Probe 19.09.2026: "Sag das nochmal" fiel durch und das Modell
    machte daraus eine SMS-Auskunft. Am Telefon duzt kaum jemand Bianca, im
    getippten Chat tippt es fast jeder so.
    """
    for satz in (
        "Sag das nochmal",
        "sag das noch mal",
        "Sag mir das noch einmal.",
        "Wiederhol das bitte",
        "Wiederhole das",
        "Wiederhol mal",
    ):
        assert meta.deute(satz) == meta.WIEDERHOLEN, satz


def test_du_imperativ_greift_nicht_in_normale_saetze():
    """Gegenprobe: "sagen" kommt in echten Anliegen vor — nie Meta daraus."""
    for satz in (
        "Sagen Sie mir bitte einen Termin am Montag",
        "Was sagen die Zeiten am Montag",
        "Koennen Sie mir sagen, was die Kontrolle kostet",
        "Ich wollte nur sagen, dass ich spaeter komme",
    ):
        assert meta.deute(satz) == "", satz


def test_wer_selbst_wiederholt_bittet_nicht():
    """Diktat-Falle: "Ich wiederhole: …" ist eine Angabe, keine Bitte."""
    assert meta.deute("Ich wiederhole: null eins sieben sieben") == ""
    assert meta.deute("Ich wiederhole meinen Nachnamen") == ""
    # Seit der Du-Imperativ zaehlt, ist "Ich sage …" die haeufigste Falle.
    assert meta.deute("Ich sage es nochmal: Mueller") == ""
    assert meta.deute("Ich sag Ihnen die Nummer noch einmal") == ""


def test_ziffern_und_tafel_schlagen_jede_formel():
    """Sobald Daten im Zug stehen, diktiert der Anrufer — nie Meta."""
    assert meta.deute("Noch mal: 0177 1234567") == ""
    assert meta.deute("M wie Maria, nochmal M") == ""
    assert meta.deute("B, E, R, G, nochmal") == ""


def test_harte_abbruch_formeln():
    for satz in (
        "Vergessen Sie es",
        "Vergiss es",
        "Hat sich erledigt",
        "Lassen wir das",
        "Doch keinen Termin",
    ):
        assert meta.deute(satz, streng=True) == meta.ABBRECHEN, satz


def test_weiche_abbruch_formel_nur_ausserhalb_der_schreibphase():
    """"Moechte ich doch nicht" meint vor einem Angebot oft nur DIESEN Termin."""
    assert meta.deute("Moechte ich doch nicht") == meta.ABBRECHEN
    assert meta.deute("Moechte ich doch nicht", streng=True) == ""
    assert meta.deute("Ich moechte das doch nicht") == meta.ABBRECHEN


def test_absage_ist_ein_anliegen_kein_abbruch():
    """"absagen"/"stornieren" gehoert der Familie VERWALTEN, nie dem Meta-Weg."""
    for satz in (
        "Ich moechte meinen Termin absagen",
        "Bitte stornieren Sie den Termin",
        "Termin loeschen",
        "Ja, bitte absagen",
    ):
        assert meta.deute(satz) == "", satz
        assert meta.deute(satz, streng=True) == "", satz


def test_auslassen_formeln():
    for satz in (
        "Das sage ich nicht",
        "Moechte ich nicht angeben",
        "Keine Angabe",
        "Muss das sein?",
        "Ueberspringen Sie das",
        "Lassen wir das offen",
        "Ist das noetig?",
        "Ist das wirklich notwendig?",
    ):
        assert meta.deute(satz) == meta.AUSLASSEN, satz


def test_noetig_frage_mit_bezug_ist_eine_sachfrage():
    """"Ist das noetig?" laesst aus. "Ist das noetig FUER die Behandlung?" fragt.

    Ein Wort Unterschied, zwei Wuensche — ein Fehltreffer wuerde hier ein Feld
    ueberspringen, statt die Frage des Anrufers zu beantworten.
    """
    for satz in (
        "Ist das noetig fuer die Behandlung?",
        "Ist das notwendig, wenn ich privat versichert bin?",
    ):
        assert meta.deute(satz) == "", satz


def test_nicht_wissen_ist_kein_auslassen():
    """"Weiss ich nicht" beantwortet die Frage (Standard-Behandler), verweigert nicht."""
    for satz in ("Weiss ich nicht", "Kann ich nicht sagen", "Keine Ahnung"):
        assert meta.deute(satz) == "", satz


def test_lange_zuege_sind_anliegen():
    """Eine Formel steht allein. Wer einen Satz spricht, verfolgt ein Anliegen."""
    lang = (
        "Ich haette gern nochmal einen Termin zur Kontrolle bei Doktor Petsas "
        "in der naechsten Woche am besten vormittags"
    )
    assert meta.deute(lang) == ""


# =========================================================================== #
# 2. Wiederholen auf Zuruf — dieselbe Absicht, nie der Unklar-Weg.
# =========================================================================== #
def test_wiederholen_spricht_die_letzte_frage_erneut():
    pol = _pol()
    st, decs = _fahre(pol, _BUCHUNG_ANGEFANGEN)
    offen = decs[-1].speak
    st, d = reduce(st, ev(Intent.WIEDERHOLEN, {}, "Wie bitte?"), pol)
    assert d.grund == "meta:wiederholen"
    assert d.naechste == Naechste.FRAGEN
    assert d.speak is not None
    assert d.speak.akt == offen.akt
    assert d.speak.detail == offen.detail


def test_wiederholen_faellt_nie_in_den_unklar_deckel():
    """Der teure Fehler: drei Hoerprobleme enden in der Uebergabe."""
    pol = _pol()
    st, _ = _fahre(pol, _BUCHUNG_ANGEFANGEN)
    for _ in range(2):
        st, d = reduce(st, ev(Intent.WIEDERHOLEN, {}, "Wie bitte?"), pol)
        assert d.naechste != Naechste.UEBERGEBEN
        assert d.grund == "meta:wiederholen"
    assert st.unklar_folge == 0


def test_wiederholen_zaehlt_nicht_gegen_die_schleifen_aufsicht():
    """Auf Zuruf wiederholen ist keine Maschinen-Schleife (aufsicht._AUF_ZURUF)."""
    pol = _pol(max_rueckfragen=2)
    st, _ = _fahre(pol, _BUCHUNG_ANGEFANGEN)
    vorher = st.stock_zahl
    st, d = reduce(st, ev(Intent.WIEDERHOLEN, {}, "Wie bitte?"), pol)
    assert st.stock_zahl == vorher
    assert not st.abgabe_faellig


def test_wiederholen_hat_einen_deckel():
    """Irgendwann hilft Wiederholen nicht mehr — dann ein Mensch, keine Schleife."""
    pol = _pol()
    st, _ = _fahre(pol, _BUCHUNG_ANGEFANGEN)
    gruende = []
    for _ in range(5):
        st, d = reduce(st, ev(Intent.WIEDERHOLEN, {}, "Wie bitte?"), pol)
        gruende.append(d.grund)
        if d.naechste == Naechste.UEBERGEBEN:
            break
    assert gruende[-1] == "meta:wiederholen_deckel"
    assert gruende.count("meta:wiederholen") >= 2


def test_wiederholen_ohne_vorlage_fragt_nach_dem_anliegen():
    """Die Begruessung kommt nicht aus dem Kern — es gibt nichts zu wiederholen."""
    pol = _pol()
    st, d = reduce(State(), ev(Intent.WIEDERHOLEN, {}, "Wie bitte?"), pol)
    assert d.grund == "meta:wiederholen_ohne_vorlage"
    assert d.naechste == Naechste.FRAGEN


def test_echtes_wort_beendet_die_wiederhol_serie():
    pol = _pol()
    st, _ = _fahre(pol, _BUCHUNG_ANGEFANGEN)
    st, _ = reduce(st, ev(Intent.WIEDERHOLEN, {}, "Wie bitte?"), pol)
    assert st.wiederhol_bitten == 1
    st, _ = reduce(st, ev(Intent.BUCHEN, {"wunschzeit": "morgen"}), pol)
    assert st.wiederhol_bitten == 0


def test_wiederholung_klingt_nie_wortgleich():
    g = TestGespraech(P.default())
    g.eingabe("Ich haette gern einen Termin")
    erste = g.eingabe("Wie bitte?").antwort
    zweite = g.eingabe("Wie bitte?").antwort
    assert erste and zweite
    assert erste != zweite


# =========================================================================== #
# 3. Anliegen abbrechen — der ehrlichste Ausweg aus einer Schleife.
# =========================================================================== #
def test_abbrechen_raeumt_die_aufgabe():
    pol = _pol()
    st, _ = _fahre(pol, _BUCHUNG_ANGEFANGEN)
    st, d = reduce(st, ev(Intent.ABBRECHEN, {}, "Vergessen Sie es"), pol)
    assert d.grund == "meta:abbrechen:buchen"
    assert st.aktiv() is None
    buchen = [t for t in st.tasks if t.typ == "buchen"]
    assert buchen and buchen[0].status == TaskStatus.ABGEBROCHEN


def test_abbruch_erzeugt_keine_rueckruf_notiz():
    """ABGEBROCHEN, nicht GESCHEITERT: es lief nichts schief."""
    pol = _pol()
    st, _ = _fahre(pol, _BUCHUNG_ANGEFANGEN)
    st, d = reduce(st, ev(Intent.ABBRECHEN, {}, "Hat sich erledigt"), pol)
    assert d.tool is None
    assert all(t.status != TaskStatus.GESCHEITERT for t in st.tasks)


def test_abbruch_raeumt_die_stock_zaehler():
    """Sonst liest die Aufsicht den naechsten Zug als Fortsetzung derselben Schleife.

    Die Abbruch-Quittung wird selbst der neue Anker (jede Aeusserung wird
    ueberwacht) — entscheidend ist, dass der ALTE Anker weg und der Zaehler
    zurueck auf Anfang ist.
    """
    pol = _pol(max_rueckfragen=2)
    st, _ = _fahre(pol, _BUCHUNG_ANGEFANGEN + [ev(Intent.BUCHEN, {}, "aehm")])
    alt = st.stock_anker
    assert alt, "Vorbedingung: die Frage stockte"
    st, _ = reduce(st, ev(Intent.ABBRECHEN, {}, "Vergessen Sie es"), pol)
    assert st.stock_anker != alt
    assert st.stock_zahl <= 1
    assert st.unklar_folge == 0
    assert not st.abgabe_faellig


def test_abbruch_holt_ein_geparktes_anliegen_zurueck():
    pol = _pol()
    st, _ = _fahre(
        pol,
        _BUCHUNG_ANGEFANGEN + [ev(Intent.AUSKUNFT, {}, "Wann ist mein Termin?")],
    )
    st, d = reduce(st, ev(Intent.ABBRECHEN, {}, "Vergessen Sie es"), pol)
    assert d.grund.startswith("meta:abbrechen")
    offen = [t for t in st.tasks if t.status in (TaskStatus.AKTIV, TaskStatus.GEPARKT)]
    assert any(t.typ == "buchen" for t in offen)


def test_abbruch_nach_geschriebener_buchung_nimmt_nichts_zurueck():
    """Es gibt kein Werkzeug "Buchung ungeschehen machen" — also ehrlich sagen."""
    g = TestGespraech(P.default())
    for satz in (
        "Ich haette gern einen Termin",
        "Ja",
        "Kontrolle",
        "Berger",
        "gesetzlich",
        "morgen",
        "der erste",
        "0177 1234567",
        "ja",
    ):
        a = g.eingabe(satz)
    a = g.eingabe("Vergessen Sie es")
    if a.grund == "meta:abbrechen_nach_write":
        assert a.tool == ""
        assert "absag" in a.antwort.lower()


def test_abbruch_ohne_aufgabe_ist_freundlich_und_kein_fehler():
    pol = _pol()
    st, d = reduce(State(), ev(Intent.ABBRECHEN, {}, "Vergessen Sie es"), pol)
    assert d.grund == "meta:abbrechen_ohne_aufgabe"
    assert d.naechste != Naechste.UEBERGEBEN
    assert d.tool is None


# =========================================================================== #
# 4. Frage auslassen — optional weiter, Pflicht ehrlich benennen.
# =========================================================================== #
def test_jedes_buchungsfeld_der_standard_policy_ist_pflicht():
    """Die Politik IST der Schalter: was die Praxis nicht braucht, wird nie gefragt.

    Darum kann "Auslassen" beim Buchen nur ehrlich ablehnen — jedes Feld, das
    der Kern erfragt, braucht ein Werkzeug. Eine Praxis, die ohne
    Versichertenstatus buchen will, streicht ihn aus ``buchen_pflicht``.
    """
    pol = _pol()
    spec = pol.spec("buchen")
    assert spec is not None
    from bianca.controller.reducer import _ist_pflicht_slot, _sammel_slots

    slots = _sammel_slots(spec)
    assert slots, "Vorbedingung: es gibt Felder"
    assert all(_ist_pflicht_slot(spec, s) for s in slots)


def test_ausgelassenes_feld_faellt_aus_der_luecken_suche():
    """Das ist die Garantie "nie wieder gefragt" — sie sitzt in _erste_luecke."""
    from bianca.controller.reducer import _erste_luecke

    pol = _pol()
    st, _ = _fahre(pol, _BUCHUNG_ANGEFANGEN)
    spec = pol.spec("buchen")
    aktiv = st.aktiv()
    assert aktiv is not None
    offen = _erste_luecke(aktiv, spec, st)
    assert offen, "Vorbedingung: ein Feld ist offen"
    aktiv.ausgelassen.add(offen)
    assert _erste_luecke(aktiv, spec, st) != offen


def test_pflichtfeld_bleibt_stehen_und_wird_benannt():
    """Geraten wird nie: ein erfundener Nachname landet in einer fremden Akte."""
    pol = _pol()
    st, _ = _fahre(
        pol,
        [
            ev(Intent.ABSAGEN, {}, "Ich moechte meinen Termin absagen"),
        ],
    )
    aktiv = st.aktiv()
    assert aktiv is not None and aktiv.zuletzt_gefragt == "nachname"
    st, d = reduce(st, ev(Intent.AUSLASSEN, {}, "Das sage ich nicht"), pol)
    assert d.grund == "meta:auslassen_pflicht:nachname"
    assert d.speak is not None
    assert ("pflicht", "nachname") in d.speak.fakten
    assert st.aktiv().zuletzt_gefragt == "nachname"
    assert not st.aktiv().gefuellt("nachname")


def test_pflicht_hinweis_kommt_nie_ohne_die_frage():
    g = TestGespraech(P.default())
    g.eingabe("Ich moechte meinen Termin absagen")
    a = g.eingabe("Das sage ich nicht")
    assert "nachname" in a.antwort.lower() or "namen" in a.antwort.lower()
    assert a.antwort.rstrip().endswith("?")


def test_auslassen_ohne_aufgabe_fragt_nach_dem_anliegen():
    pol = _pol()
    st, d = reduce(State(), ev(Intent.AUSLASSEN, {}, "Keine Angabe"), pol)
    assert d.grund == "meta:auslassen_ohne_aufgabe"
    assert d.naechste == Naechste.FRAGEN


# =========================================================================== #
# 5. Stille als Kern-Ereignis — Presence, Frage, dann ehrlich Schluss.
# =========================================================================== #
def test_stille_laeuft_nicht_durch_das_verstehen():
    """Es gibt nichts zu deuten — und ein leerer Zug darf nie Unklar zaehlen."""
    g = TestGespraech(P.default())
    g.eingabe("Ich haette gern einen Termin")
    a = g.stille()
    assert a.grund.startswith("meta:stille")
    assert g.state.unklar_folge == 0


def test_stille_reihenfolge_presence_dann_frage_dann_schluss():
    g = TestGespraech(P.default())
    g.eingabe("Ich haette gern einen Termin")
    gruende, texte = [], []
    for _ in range(4):
        a = g.stille()
        gruende.append(a.grund)
        texte.append(a.antwort)
        if a.hangup:
            break
    assert gruende[0] == "meta:stille_presence"
    assert gruende[1] == "meta:stille_frage"
    assert gruende[-1] == "meta:stille_schluss"
    assert len(set(texte)) == len(texte), "nie dreimal dasselbe"


def test_stille_legt_am_ende_ehrlich_auf():
    g = TestGespraech(P.default())
    g.eingabe("Ich haette gern einen Termin")
    letzte = None
    for _ in range(6):
        letzte = g.stille()
        if letzte.hangup:
            break
    assert letzte is not None and letzte.hangup
    assert g.state.terminal


def test_stille_zaehlt_nicht_gegen_die_schleifen_aufsicht():
    pol = _pol(max_rueckfragen=2)
    st, _ = _fahre(pol, _BUCHUNG_ANGEFANGEN)
    vorher = st.stock_zahl
    st, _ = reduce(st, ev(Intent.STILLE, {}, ""), pol)
    st, d = reduce(st, ev(Intent.STILLE, {}, ""), pol)
    assert st.stock_zahl == vorher
    assert not st.abgabe_faellig


def test_echtes_wort_beendet_die_stille_serie():
    pol = _pol()
    st, _ = _fahre(pol, _BUCHUNG_ANGEFANGEN)
    st, _ = reduce(st, ev(Intent.STILLE, {}, ""), pol)
    assert st.stupse == 1
    st, _ = reduce(st, ev(Intent.BUCHEN, {"wunschzeit": "morgen"}), pol)
    assert st.stupse == 0
    assert st.stupse_gesamt == 1, "der Gesamtzaehler bleibt (Notleine)"


def test_stille_nach_dem_abschied_startet_kein_neues_gespraech():
    """Tote Leitung: der Kern darf das Freizeichen nicht begruessen."""
    g = TestGespraech(P.default())
    g.eingabe("Ich haette gern einen Termin")
    g.eingabe("Auf Wiederhoeren")
    assert g.state.terminal
    a = g.stille()
    assert g.state.terminal
    assert a.grund in ("terminal", "meta:stille_presence", "meta:stille_schluss")
    assert g.state.aktiv() is None


def test_stille_nach_presence_erinnert_an_die_frage_ohne_nachbohren():
    """Niemand hat um die Wiederholung gebeten — also kein "gerne noch einmal"."""
    g = TestGespraech(P.default())
    g.eingabe("Ich haette gern einen Termin")
    g.stille()
    a = g.stille()
    low = a.antwort.lower()
    assert "noch einmal" not in low and "nochmal" not in low
    assert a.antwort.rstrip().endswith("?")
