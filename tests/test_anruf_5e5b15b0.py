"""MedDent 19.09.2026 (Anruf 5e5b15b0) — Tempo und der SMS-Fehlgriff.

Live gehoert wurde wortgleich: auf "Ja, verstimmt." (die Bestaetigung der
Identitaet) antwortete Bianca mit der SMS-Auskunft "Ja — eine Bestaetigung geht
per SMS …". Das Wort stand NUR in der Umschrift des Modells (``verstanden``),
nie im Satz des Anrufers. Dazu die Latenz: 3,0 s / 4,3 s / 10,2 s je Zug, weil
jeder Satz ans Modell ging — auch das nackte "Petsas" auf die Behandlerfrage.

Vier Wachen, und die Gegenproben sind der teurere Teil: ein echter SMS-Wunsch
muss weiter beantwortet werden, und ein Satz mit zweitem Anliegen muss weiter
ans Modell gehen.
"""

import time

import pytest

from bianca.controller import renderer, verstehen
from bianca.controller.reducer import _klingt_sms
from bianca.controller.typen import (
    Intent,
    Quelle,
    SemanticEvent,
    SlotValue,
    SpeakSpec,
    SprechAkt,
)


def _ev(roh: str, *, verstanden: str = "", **kw) -> SemanticEvent:
    return SemanticEvent(
        intent=kw.pop("intent", Intent.BESTAETIGEN),
        roh=roh,
        verstanden=verstanden,
        **kw,
    )


# --------------------------------------------------------------------------- #
# 1. SMS: nur der Anrufer macht sie zum Thema.
# --------------------------------------------------------------------------- #
def test_paraphrase_zuendet_keine_sms_auskunft():
    ev = _ev(
        "Ja, verstimmt.",
        verstanden="Der Anrufer bestaetigt, dass er Herr Petsas ist.",
    )
    assert _klingt_sms(ev) is False


def test_anrufer_fragt_nach_sms():
    assert _klingt_sms(_ev("Kommt da noch eine SMS?")) is True


def test_anrufer_fragt_nach_bestaetigung():
    assert _klingt_sms(_ev("Bekomme ich eine Bestaetigung?")) is True


def test_ausdruecklicher_sms_slot_zaehlt_weiter():
    ev = _ev("Ja.", slots={"sms": SlotValue(wert="ja", quelle=Quelle.GESAGT)})
    assert _klingt_sms(ev) is True


def test_rezept_ohne_sms_bleibt_kein_sms_thema():
    assert _klingt_sms(_ev("Ich brauche ein Rezept.")) is False


# --------------------------------------------------------------------------- #
# 2. Tempo: Formular-Antwort mit Ja-Kopf braucht kein Modell.
# --------------------------------------------------------------------------- #
def _llm_zaehler():
    """Zaehlt Modell-Aufrufe. Bewusst kein ``raise``: ``deuten`` faengt jeden
    Fehler des Modells ab, ein geworfener Testbruch waere unsichtbar."""
    box: list[str] = []

    def llm(text, *, lage):  # noqa: ANN001, ARG001
        box.append(text)
        return SemanticEvent(intent=Intent.UNKLAR, roh=text, deutung="hirn")

    return llm, box


def test_ja_mit_anhang_auf_geschlossene_frage_ohne_modell():
    llm, box = _llm_zaehler()
    ev = verstehen.deuten(
        "Ja, verstimmt.",
        offene_frage="anrufer_check",
        erwartet_janein=True,
        llm=llm,
    )
    assert box == []
    assert ev.deutung == "formular"
    assert ev.bestaetigung is True


def test_nein_mit_anhang_auf_geschlossene_frage_ohne_modell():
    llm, box = _llm_zaehler()
    ev = verstehen.deuten(
        "Nein, leider nicht.",
        offene_frage="anrufer_check",
        erwartet_janein=True,
        llm=llm,
    )
    assert box == []
    assert ev.deutung == "formular"
    assert ev.bestaetigung is False


def test_zeitwunsch_auf_die_wunschfrage_ohne_modell():
    llm, box = _llm_zaehler()
    ev = verstehen.deuten(
        "Am Mittwoch vormittags",
        offene_frage="wunschzeit",
        llm=llm,
    )
    assert box == []
    assert ev.deutung == "regel"
    assert ev.slots["wunschzeit"].wert


def test_behandler_mit_titel_ohne_modell():
    llm, box = _llm_zaehler()
    ev = verstehen.deuten(
        "Bei Doktor Petsas",
        offene_frage="behandler",
        llm=llm,
    )
    assert box == []
    assert ev.deutung == "regel"
    assert ev.slots["behandler"].wert == "Petsas"


# --------------------------------------------------------------------------- #
# 2b. Gegenproben: ein zweites Anliegen oder eine Rueckfrage gehoert dem Modell.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "satz",
    [
        "Ja, aber ich moechte den Termin absagen.",
        "Ja, und bitte noch ein Rezept.",
        "Ja, warum rufen Sie eigentlich an?",
        "Ja, das ist richtig, aber der Termin passt mir doch nicht mehr so gut.",
    ],
)
def test_mischzug_geht_weiter_ans_modell(satz):
    llm, box = _llm_zaehler()
    verstehen.deuten(
        satz,
        offene_frage="anrufer_check",
        erwartet_janein=True,
        llm=llm,
    )
    assert box, f"Modell haette laufen muessen: {satz!r}"


def test_offene_frage_ohne_treffer_geht_ans_modell():
    llm, box = _llm_zaehler()
    verstehen.deuten("Muellhausen", offene_frage="versicherung", llm=llm)
    assert box


# --------------------------------------------------------------------------- #
# 3. Zeitdeckel: lieber die Regel als zehn Sekunden Stille.
# --------------------------------------------------------------------------- #
def test_langsames_modell_faellt_auf_die_regel(monkeypatch):
    monkeypatch.setenv("KERN_HIRN_BUDGET_S", "0.2")

    def langsam(text, *, lage):  # noqa: ANN001, ARG001
        time.sleep(2.0)
        return SemanticEvent(intent=Intent.BUCHEN, roh=text)

    t0 = time.monotonic()
    # Bewusst KEIN klares Anliegen-Wort: sonst greift der Regex-Schnellweg
    # und der Deckel waere unsichtbar.
    ev = verstehen.deuten("Das mit dem Zahn ist kompliziert.", llm=langsam)
    dauer = time.monotonic() - t0
    assert dauer < 1.5
    assert ev.deutung == "nlu"
    assert "ueber" in ev.llm


def test_schnelles_modell_gewinnt_weiter(monkeypatch):
    monkeypatch.setenv("KERN_HIRN_BUDGET_S", "2.0")

    def flott(text, *, lage):  # noqa: ANN001, ARG001
        return SemanticEvent(intent=Intent.BUCHEN, roh=text, deutung="hirn")

    ev = verstehen.deuten("Das mit dem Zahn ist kompliziert.", llm=flott)
    assert ev.intent is Intent.BUCHEN
    assert ev.deutung == "hirn"


def test_modellfehler_faellt_weiter_auf_die_regel():
    def wirft(text, *, lage):  # noqa: ANN001, ARG001
        raise RuntimeError("vLLM weg")

    ev = verstehen.deuten("Ich braeuchte mal einen Termin.", llm=wirft)
    assert ev.deutung == "nlu"
    assert "Hirn-Fehler" in ev.llm


# --------------------------------------------------------------------------- #
# 4. Nicht-Werte: "keine Ahnung" ist keine Angabe.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("wert", ["unbekannt", "keine Ahnung", "weiss nicht", "-"])
def test_nicht_werte_fallen_aus_den_slots(wert):
    def llm(text, *, lage):  # noqa: ANN001, ARG001
        return SemanticEvent(
            intent=Intent.BUCHEN,
            roh=text,
            slots={
                "wunschzeit": SlotValue(wert=wert, quelle=Quelle.GESAGT),
                "besuchsgrund": SlotValue(wert=wert, quelle=Quelle.GESAGT),
            },
        )

    ev = verstehen.deuten("Was der vorbereiten soll, keine Ahnung.", llm=llm)
    assert "wunschzeit" not in ev.slots
    assert "besuchsgrund" not in ev.slots


def test_egal_bleibt_eine_angabe():
    def llm(text, *, lage):  # noqa: ANN001, ARG001
        return SemanticEvent(
            intent=Intent.BUCHEN,
            roh=text,
            slots={"behandler": SlotValue(wert="egal", quelle=Quelle.GESAGT)},
        )

    ev = verstehen.deuten("Mir ist der Behandler eigentlich egal.", llm=llm)
    assert ev.slots["behandler"].wert == "egal"


# --------------------------------------------------------------------------- #
# 5. Renderer: kein Nicht-Wert im Mund, kein Arzt-Vorname.
# --------------------------------------------------------------------------- #
def test_ruecklese_spricht_den_arzt_ohne_vornamen():
    spec = SpeakSpec(
        akt=SprechAkt.RUECKLESEN,
        fakten=(
            ("terminwahl", "2026-09-23T09:00"),
            ("behandler", "Dr. Michael Petsas, M.Sc."),
            ("besuchsgrund", "Kontrolle"),
        ),
    )
    text = renderer.rendern(spec)
    assert "Doktor Petsas" in text
    assert "Michael" not in text
    assert "2026-09-23" not in text


def test_ruecklese_laesst_nicht_werte_weg():
    spec = SpeakSpec(
        akt=SprechAkt.RUECKLESEN,
        fakten=(
            ("terminwahl", "2026-09-23T09:00"),
            ("besuchsgrund", "unbekannt"),
        ),
    )
    text = renderer.rendern(spec)
    assert "unbekannt" not in text.lower()


def test_frage_traegt_keinen_nicht_wert_als_vorbezug():
    spec = SpeakSpec(
        akt=SprechAkt.FRAGE,
        frage_id="wunschzeit",
        fakten=(("gehoert_wunsch", "keine Ahnung"),),
    )
    text = renderer.rendern(spec)
    assert "keine ahnung" not in text.lower()


# --------------------------------------------------------------------------- #
# 6. Live-Saetze des 92-Sekunden-Anrufs 34979221 (MedDent 19.09. 23:40).
# --------------------------------------------------------------------------- #
def test_erster_terminwunsch_ohne_modell():
    llm, box = _llm_zaehler()
    ev = verstehen.deuten("Hallo, ich hätte gern einen Termin.", llm=llm)
    assert box == []
    assert ev.deutung == "anliegen"
    assert ev.intent is Intent.BUCHEN


def test_keine_ahnung_auf_besuchsgrund_ohne_modell():
    llm, box = _llm_zaehler()
    ev = verstehen.deuten(
        "Was der vorbereiten soll, keine Ahnung.",
        offene_frage="besuchsgrund",
        llm=llm,
    )
    assert box == []
    assert ev.intent is Intent.AUSLASSEN
    assert ev.slots["nicht_wissen"].wert == "besuchsgrund"


def test_hallo_auf_offener_frage_ist_wiederholen():
    llm, box = _llm_zaehler()
    ev = verstehen.deuten("Hallo?", offene_frage="wunschzeit", llm=llm)
    assert box == []
    assert ev.deutung == "meta"
    assert ev.intent is Intent.WIEDERHOLEN


def test_hallo_am_anfang_ist_kein_wiederholen():
    llm, box = _llm_zaehler()
    ev = verstehen.deuten("Hallo, ich hätte gern einen Termin.", llm=llm)
    assert ev.intent is Intent.BUCHEN
    assert ev.deutung == "anliegen"
    assert box == []
