"""W-ID-EINMAL (07.10.2026): die Identitaetsfrage kommt genau einmal.

Live 06.10.2026 (Blessing b7508465, 3b57b62d, 9fc1f105): "Habe ich Sie
richtig erkannt?" kam zwei- bis viermal — nach einer klaren Bestaetigung
hinter "Sind Sie noch dran?", nach einer Fortsetzung und mit doppeltem
Vorsatz.
"""

import pytest

from bianca import agent, flow, gehirn
from kern import hirn, stille
from kern.tenants import laden


def _sit() -> dict:
    sit = {
        "id": "id-einmal",
        "stimme": "Bianca",
        "tenant": laden("meddent"),
        "messages": [
            {"role": "system", "content": "test"},
            {"role": "assistant", "content": "Was kann ich für Sie tun?"},
        ],
        "booking": {},
        "tools": [],
        "zuege": [],
        "anrufer": {
            "vorname": "Julia", "nachname": "Berger", "patientId": "pat-7",
            "geschlecht": "female", "telefon": "+4915253904756",
        },
    }
    hirn.init(sit)
    gehirn.sammler(sit)
    return sit


@pytest.fixture
def ohne_hintergrund(monkeypatch):
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    monkeypatch.setenv("INTENT_NACHZUG", "0")
    monkeypatch.setattr(
        agent.llm, "chat",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("Identitaetsantwort braucht kein LLM")),
    )


def _bis_anrufer_check(sit) -> None:
    hirn.anwenden(sit, {
        "kanal": "ok", "zug": "wechseln", "handlung": "ANLEGEN",
        "gegenstand": "VORGANG", "spiegel": "neuer Termin",
    })
    sit.pop("hirnModusNeu", None)
    flow.zug(sit, "Guten Tag, ich hätte gern einen Termin.")
    assert gehirn.sammler(sit)["frage"] == "anrufer_check"


# --- Bestaetigung hinter "Sind Sie noch dran?" -----------------------------

def test_live_satz_nach_presence_bestaetigt_identitaet(ohne_hintergrund):
    """b7508465 z06 wortgleich: die Antwort beantwortet BEIDE Fragen."""
    sit = _sit()
    _bis_anrufer_check(sit)
    sit["messages"].append({"role": "assistant", "content": "Sind Sie noch dran?"})

    antwort = agent.user_turn(
        sit, "Ja, ich bin noch dran, Sie haben es richtig erkannt.")

    assert gehirn.sammler(sit)["anruferCheck"] == "ja"
    assert "richtig erkannt" not in (antwort or {}).get("text", "")


def test_nacktes_ja_nach_presence_bleibt_presence(ohne_hintergrund):
    """W-MISCHZUG bleibt: ein nacktes Ja bestaetigt nur die Leitung."""
    sit = _sit()
    _bis_anrufer_check(sit)
    sit["messages"].append({"role": "assistant", "content": "Sind Sie noch dran?"})

    agent.user_turn(sit, "Ja.")

    assert not gehirn.sammler(sit).get("anruferCheck")


def test_noch_dran_ohne_identitaet_bleibt_presence(ohne_hintergrund):
    sit = _sit()
    _bis_anrufer_check(sit)
    sit["messages"].append({"role": "assistant", "content": "Sind Sie noch dran?"})

    agent.user_turn(sit, "Ja, ich bin noch dran.")

    assert not gehirn.sammler(sit).get("anruferCheck")


@pytest.mark.parametrize("satz", [
    "Sie haben mich richtig erkannt.",
    "Ja, das bin ich.",
    "Genau, ich bin's.",
    "Ja, Sie haben mich richtig erkannt.",
])
def test_ausdrueckliche_identitaet(satz):
    assert gehirn.ist_identitaet_ausdruecklich(satz)
    assert gehirn.ja_nein_entscheidung(satz, "anrufer_check") == "ja"


@pytest.mark.parametrize("satz", [
    "Das bin ich nicht.",
    "Nein, Sie haben mich nicht richtig erkannt.",
    "Da haben Sie mich falsch erkannt.",
    "Ja, das bin ich nicht.",
])
def test_verneinte_identitaet_bleibt_nein(satz):
    assert not gehirn.ist_identitaet_ausdruecklich(satz)
    assert gehirn.ja_nein_entscheidung(satz, "anrufer_check") == "nein"


# --- Fortsetzung nach eingeschobenem Anliegen ------------------------------

def _alt_bestaetigt(sit) -> dict:
    s = gehirn.sammler(sit)
    s.update({
        "anruferCheck": "ja", "warSchonMal": True, "vorname": "Julia",
        "nachname": "Berger", "patientId": "pat-7", "bekannt": True,
        "buchstabiert": True, "frage": "grund",
    })
    sit["patient"] = {"id": "pat-7", "lastName": "Berger"}
    return s


def test_checkpoint_vor_dem_ja_holt_identitaet_mit(monkeypatch):
    """3b57b62d/9fc1f105: der Checkpoint stammte von VOR dem Ja."""
    monkeypatch.delenv("ID_MITNEHMEN", raising=False)
    sit = _sit()
    _alt_bestaetigt(sit)
    cp = {"sammler": {"modus": "buchen", "frage": "anrufer_check",
                      "anruferCheck": ""}}

    hirn._checkpoint_zuruecklegen(sit, cp)

    s = sit["sammler"]
    assert s["anruferCheck"] == "ja"
    assert s["nachname"] == "Berger" and s["patientId"] == "pat-7"
    assert s["frage"] == ""
    assert sit["patient"]["id"] == "pat-7"
    assert gehirn.naechste_frage(sit) != "anrufer_check"


def test_checkpoint_mit_drittem_holt_keine_identitaet(monkeypatch):
    """Termin fuer den Sohn: die Akte des Anrufers darf nicht hinein."""
    monkeypatch.delenv("ID_MITNEHMEN", raising=False)
    sit = _sit()
    _alt_bestaetigt(sit)
    cp = {"sammler": {"modus": "buchen", "fuerWen": "sohn", "anruferCheck": ""}}

    hirn._checkpoint_zuruecklegen(sit, cp)

    s = sit["sammler"]
    assert not s.get("nachname") and not s.get("patientId")


def test_fremde_akte_des_eingeschobenen_anliegens_wandert_nie(monkeypatch):
    """Absage fuer den Bruder (Stallone-Fall): dessen Name bleibt draussen."""
    monkeypatch.delenv("ID_MITNEHMEN", raising=False)
    sit = _sit()
    s = _alt_bestaetigt(sit)
    s.update({"nachname": "Stallone", "vorname": "Sylvester",
              "patientId": "pat-99"})
    cp = {"sammler": {"modus": "buchen", "anruferCheck": ""}}

    hirn._checkpoint_zuruecklegen(sit, cp)

    neu = sit["sammler"]
    assert not neu.get("nachname") and not neu.get("patientId")


def test_verneinte_identitaet_wandert_ebenfalls(monkeypatch):
    monkeypatch.delenv("ID_MITNEHMEN", raising=False)
    sit = _sit()
    gehirn.sammler(sit)["anruferCheck"] = "nein"
    cp = {"sammler": {"modus": "buchen", "frage": "anrufer_check",
                      "anruferCheck": ""}}

    hirn._checkpoint_zuruecklegen(sit, cp)

    assert sit["sammler"]["anruferCheck"] == "nein"
    assert sit["sammler"]["frage"] == ""


def test_notaus_id_mitnehmen(monkeypatch):
    monkeypatch.setenv("ID_MITNEHMEN", "0")
    sit = _sit()
    _alt_bestaetigt(sit)
    cp = {"sammler": {"modus": "buchen", "frage": "anrufer_check",
                      "anruferCheck": ""}}

    hirn._checkpoint_zuruecklegen(sit, cp)

    assert sit["sammler"]["anruferCheck"] == ""
    assert sit["sammler"]["frage"] == "anrufer_check"


def test_tote_identitaetsfrage_wird_geraeumt():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"frage": "anrufer_check", "anruferCheck": "ja"})
    sit["flussFrage"] = "Habe ich Sie richtig erkannt?"

    agent._tote_identitaetsfrage_raeumen(sit)

    assert s["frage"] == "" and "flussFrage" not in sit


def test_offene_identitaetsfrage_bleibt_stehen():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"frage": "anrufer_check", "anruferCheck": ""})

    agent._tote_identitaetsfrage_raeumen(sit)

    assert s["frage"] == "anrufer_check"


# --- Kein doppelter Vorsatz ------------------------------------------------

@pytest.mark.parametrize("frage", [
    "Entschuldigung, kurz zur Kontrolle: Habe ich Sie richtig erkannt?",
    "Kurz zur Sicherheit: Stimmt die Nummer so?",
    "Entschuldigung — ein kurzes Ja oder Nein genügt. Kurz zur Einordnung: "
    "Waren Sie schon mal in unserer Praxis?",
])
def test_vorsatz_der_variante_wird_nicht_doppelt_gesprochen(frage):
    kern = stille.kern_frage(frage)
    assert "kurz zur" not in kern.lower()
    assert "Entschuldigung" not in kern
