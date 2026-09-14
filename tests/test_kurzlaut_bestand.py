"""B5 (14.09.2026, Anrufe 9dd61a59 / 5aa87268) — offline, ohne LLM.

W-KURZLAUT: "Oh." / "Puff." / "Uff." sind ein Luftholen, kein Schweigen.
Live liefen solche Ausrufe direkt auf den Stille-Stups ("Sind Sie noch
dran?") — der Anrufer hatte gerade erst Luft geholt. Die ersten Ausrufe in
Folge sind jetzt ein stiller Warte-Zug (die Bruecke haelt den Stups 8 s
zurueck); erst eine Serie ohne Inhalt laeuft wieder auf den Stups, damit
Leitungs-Artefakte ("Hm. Hm. Hm.") das Gespraech nicht einfrieren.

W-SCHONMAL-DOPPELT: "Nein, noch nicht das erste Mal" ist ein BESTANDS-
patient (doppelte Verneinung) — live wurde daraus ein Neupatient, und die
Kette fragte den Behandler zur Wahl statt "bei wem waren Sie zuletzt".
"""

from __future__ import annotations

import pytest

from bianca import agent, flow, gehirn
from kern import llm
from kern.tenants import laden


def _knall(*a, **k):
    raise AssertionError("LLM darf hier nicht laufen")


def _ohne_llm(fn):
    echt_chat, echt_stream = llm.chat, llm.chat_stream
    echt_anstossen = flow.hintergrund.anstossen
    llm.chat = _knall
    llm.chat_stream = _knall
    flow.hintergrund.anstossen = lambda sit: None
    try:
        return fn()
    finally:
        llm.chat, llm.chat_stream = echt_chat, echt_stream
        flow.hintergrund.anstossen = echt_anstossen


def _sit() -> dict:
    sit = {"tenant": laden("meddent"), "stimme": "Bianca",
           "messages": [{"role": "system", "content": "x"},
                        {"role": "assistant", "content": "Guten Tag, hier ist Bianca."},
                        {"role": "user", "content": "Ich hätte gern einen Termin."},
                        {"role": "assistant", "content": "Gerne. Waren Sie schon einmal bei uns?"}]}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "schonmal", "phase": ""})
    return sit


# --- W-KURZLAUT ----------------------------------------------------------------

@pytest.mark.parametrize("laut", ["Oh.", "Puff.", "Uff.", "Hoppla.", "Ach so.", "Boah.", "Aha.",
                                  "Hm.", "Mhm.", "Äh.", "Tja.", "Oh je."])
def test_kurzlaute_werden_erkannt(laut):
    assert agent._NUR_LAUT_RE.match(laut), laut


@pytest.mark.parametrize("satz", ["Oh, ich brauche einen Termin.", "Ja.", "Nein.", "Petsas.",
                                  "0177 1234567", "Ach so, dann Dienstag.", "Hm, eher nachmittags."])
def test_saetze_mit_inhalt_sind_keine_kurzlaute(satz):
    assert not agent._NUR_LAUT_RE.match(satz), satz


def test_erste_ausrufe_sind_warte_zug_kein_stups_kein_modell():
    def lauf():
        sit = _sit()
        sit["stupse"] = 1
        vorher = list(sit["messages"])
        for i in (1, 2):
            aus = agent.user_turn(sit, "Oh.")
            assert aus.get("warte") is True and aus.get("text") == ""
            assert aus.get("stilleMs") == agent._KURZLAUT_WARTE_MS
            assert sit["kurzlautSerie"] == i
        assert sit["messages"] == vorher       # nichts im Verlauf
        assert sit["stupse"] == 1              # stille.reset lief NICHT (Deckel bleibt)
        assert gehirn.sammler(sit)["frage"] == "schonmal"
    _ohne_llm(lauf)


def test_serie_ohne_inhalt_laeuft_auf_den_stups():
    """Leitungs-Artefakt 'Hm. Hm. Hm.': der dritte Ausruf holt den Stups —
    das Gespraech friert nie ein."""
    def lauf():
        sit = _sit()
        agent.user_turn(sit, "Hm.")
        agent.user_turn(sit, "Hm.")
        aus = agent.user_turn(sit, "Hm.")
        assert not aus.get("warte")
        assert aus.get("text")  # Presence oder offene Frage — jedenfalls Ton
    _ohne_llm(lauf)


def test_echter_satz_setzt_die_serie_zurueck():
    def lauf():
        sit = _sit()
        agent.user_turn(sit, "Oh.")
        agent.user_turn(sit, "Puff.")
        aus = agent.user_turn(sit, "Ja, ich war schon mal da.")
        assert "kurzlautSerie" not in sit
        assert gehirn.sammler(sit)["warSchonMal"] is True
        assert aus.get("text")
    _ohne_llm(lauf)


# --- W-SCHONMAL-DOPPELT ----------------------------------------------------------

@pytest.mark.parametrize("satz", [
    "Nein, noch nicht das erste Mal.",
    "Nicht das erste Mal, nein.",
    "Nein, ich bin kein Neupatient.",
    "Nein, nicht zum ersten Mal.",
])
def test_doppelte_verneinung_ist_bestand(satz):
    sit = _sit()
    s = gehirn.sammler(sit)
    gehirn.einsammeln(sit, satz)
    assert s["warSchonMal"] is True, satz


@pytest.mark.parametrize("satz", [
    "Nein, ich war noch nie da.",
    "Nein, das ist das erste Mal.",
    "Nein, ich bin neu hier.",
    "Nein.",
])
def test_einfache_verneinung_bleibt_neupatient(satz):
    sit = _sit()
    s = gehirn.sammler(sit)
    gehirn.einsammeln(sit, satz)
    assert s["warSchonMal"] is False, satz


def test_bestand_nach_doppelter_verneinung_bekommt_die_bestandsfrage():
    """Kette: kein 'Behandler zur Wahl' fuer jemanden, der schon da war."""
    def lauf():
        sit = _sit()
        aus = agent.user_turn(sit, "Nein, noch nicht das erste Mal.")
        s = gehirn.sammler(sit)
        assert s["warSchonMal"] is True
        assert "zuletzt" in (aus.get("text") or "").lower() or s["frage"] in {"arzt", "nachname", "grund"}
    _ohne_llm(lauf)
