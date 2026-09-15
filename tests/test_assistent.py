"""W-STIMME-MANDANT (15.09.2026): Name, Genus und Stimme je Mandant.

Die GEGENPROBEN sind hier der wichtigere Teil. Bianca spricht in drei Praxen
live; jede Zeile, die sich fuer Ben aendert, darf sich fuer MedDent, Thaler
und Blessing NICHT aendern. Deshalb prueft fast jeder Block beides:
was Ben bekommt und dass Bianca byte-identisch bleibt.
"""

import contextvars
import inspect

from bianca import gehirn
from bianca.greeting import begruessung
from bianca.prompt import system_prompt
from kern import assistent, dienst as dienst_mod, tenants, tts

BEN = {"assistentName": "Ben", "assistentGenus": "m", "stimme": "ben"}
MEDDENT = tenants.laden("meddent")


# ---- Name -----------------------------------------------------------------

def test_ohne_mandant_bleibt_bianca():
    assert assistent.name(None) == "Bianca"
    assert assistent.name({}) == "Bianca"
    assert assistent.genus(None) == "f"
    assert not assistent.maennlich(None)
    assert assistent.stimme(None) == ""


def test_live_mandanten_bleiben_bianca_weiblich():
    """MedDent, Thaler, Blessing tragen kein assistentName — nichts dreht."""
    for mid in ("meddent", "thaler", "blessing"):
        t = tenants.laden(mid)
        assert assistent.name(t) == "Bianca", mid
        assert assistent.genus(t) == "f", mid
        assert assistent.stimme(t) == "", mid


def test_ruether_ist_ben_und_maennlich():
    t = tenants.laden("ruether")
    assert assistent.name(t) == "Ben"
    assert assistent.maennlich(t)
    assert assistent.stimme(t) == "ben"


def test_did_4160_fuehrt_zu_ben():
    """Die ganze Kette, die live zaehlt: Dialplan-UUID -> DID -> Mandant ->
    Stimme/Name. Faellt einer der drei Schritte aus, spricht auf Ruethers
    Leitung Bianca."""
    from sip_bridge.server import did_von_uuid

    did = did_von_uuid(bytes.fromhex("b1a2ca000000000000000000" + "00004160"))
    assert did == "+4921154244160"
    t = tenants.von_did(did)
    assert t and t["_id"] == "ruether"
    assert assistent.name(t) == "Ben"
    assert assistent.stimme(t) == "ben"
    # Gegenprobe: die drei Live-Leitungen bleiben bei Bianca.
    for ende, mid in (("00004101", "meddent"), ("00004105", "thaler")):
        andere = tenants.von_did(
            did_von_uuid(bytes.fromhex("b1a2ca000000000000000000" + ende)))
        assert andere and andere["_id"] == mid
        assert assistent.name(andere) == "Bianca"
        assert assistent.stimme(andere) == ""


def test_db_agentname_nur_wenn_er_wie_ein_vorname_aussieht():
    """Die Pickadoc-DB fuehrt im Agent-Namen teils den PRAXIS-Namen — den
    darf die Assistenz sich nie selbst sagen."""
    assert assistent.name({"agentName": "Ben"}) == "Ben"
    for muell in (
        '"Med Dent" Zahnklinik Duesseldorf - Robert',
        "Dr. Pantas",
        "Praxis Ruether",
        "Zahnarztpraxis Mainburg",
        "",
    ):
        assert assistent.name({"agentName": muell}) == "Bianca", muell


def test_mandantenfeld_schlaegt_db():
    assert assistent.name({"agentName": "Klara", "assistentName": "Ben"}) == "Ben"


def test_genus_aus_namen_wenn_nicht_gesetzt():
    assert assistent.genus({"assistentName": "Ben"}) == "m"
    assert assistent.genus({"assistentName": "Lisa"}) == "f"
    # Unbekannter Name: im Zweifel weiblich (Stand vor dem 15.09.2026).
    assert assistent.genus({"assistentName": "Norbert"}) == "f"
    # Ausdrueckliches Feld gewinnt immer.
    assert assistent.genus({"assistentName": "Norbert", "assistentGenus": "m"}) == "m"


# ---- Umschrift ------------------------------------------------------------

def test_weiblicher_mandant_laesst_den_text_unangetastet():
    for text in (
        "Du bist Bianca, Empfangsassistentin am Telefon von der Praxis.",
        "Ich bin die Neue! Wie kann ich helfen?",
        "Sie sprechen mit Bianca, der Telefonassistentin der Praxis.",
    ):
        assert assistent.formen(text, MEDDENT) == text
        assert assistent.formen(text, None) == text


def test_maennlicher_assistent_dreht_selbstbezeichnung_und_namen():
    assert (assistent.formen("Du bist Bianca, Empfangsassistentin am Telefon.", BEN)
            == "Du bist Ben, Empfangsassistent am Telefon.")
    assert assistent.formen("Ich bin die Neue!", BEN) == "Ich bin der Neue!"
    assert (assistent.formen("Ich bin die KI-Telefonassistentin der Praxis.", BEN)
            == "Ich bin der KI-Telefonassistent der Praxis.")


def test_dativ_apposition_wird_gebeugt():
    """"Sie sprechen mit Bianca, der Telefonassistentin" — ein blindes
    Ersetzen von "Telefonassistentin" liesse hier "der Telefonassistent"
    stehen (falscher Kasus)."""
    assert (assistent.formen(
        "Sie sprechen mit Bianca, der Telefonassistentin der Praxis.", BEN)
        == "Sie sprechen mit Ben, dem Telefonassistenten der Praxis.")


def test_praxisfakten_und_anreden_bleiben_weiblich():
    """Die Umschrift trifft nur die SELBSTbezeichnung. Behandlerinnen,
    Anruferinnen und Praxis-Fakten sind davon nie betroffen."""
    for text in (
        "Frau Doktor Ruether ist heute in der Praxis.",
        "Ihre Kollegin hat den Termin vereinbart.",
        "Die Patientin war zuletzt im Maerz da.",
        "Doktor Myriam Roerig hat einen eigenen Kalender.",
        "Die Praxisinhaberin entscheidet das im Termin.",
    ):
        assert assistent.formen(text, BEN) == text, text


def test_leerer_text_bleibt_leer():
    assert assistent.formen("", BEN) == ""
    assert assistent.formen(None, BEN) == ""


def test_name_dreht_auch_ohne_genuswechsel():
    """Eine Praxis darf ihre Assistenz "Clara" nennen, ohne dass sich die
    Grammatik dreht."""
    clara = {"assistentName": "Clara"}
    assert (assistent.formen("Mein Name ist Bianca.", clara)
            == "Mein Name ist Clara.")
    assert assistent.formen("Ich bin die Neue!", clara) == "Ich bin die Neue!"


# ---- Begruessung + Prompt -------------------------------------------------

def test_begruessung_nennt_den_richtigen_namen():
    assert "Bianca" in begruessung("der Praxis", MEDDENT)
    assert "Bianca" in begruessung("der Praxis")  # alter Aufruf ohne Mandant
    ben = begruessung("der Praxis Doktor Ruether", tenants.laden("ruether"))
    assert "Ben" in ben and "Bianca" not in ben


def test_prompt_dreht_rolle_und_name():
    p_ben = system_prompt(praxis="Praxis Ruether", behandler="Doktor Ruether",
                          sit={"tenant": BEN})
    assert "Du bist Ben, Empfangsassistent" in p_ben
    assert "Bianca" not in p_ben
    assert "Empfangsassistentin" not in p_ben
    # Gegenprobe: MedDent unveraendert.
    p_bianca = system_prompt(praxis="Praxis MedDent", behandler="Doktor Petsas",
                             sit={"tenant": MEDDENT})
    assert "Du bist Bianca, Empfangsassistentin" in p_bianca


def test_feste_saetze_werden_fuer_ben_maennlich_gewaermt():
    """Der Platten-Cache muss GENAU die Saetze tragen, die der Mund
    spricht — sonst waermt Ben die weiblichen Formen vor und zahlt live
    die Synthese."""
    ben = gehirn.feste_saetze(tenants.laden("ruether"))
    assert not any("Ich bin die Neue" in s for s in ben)
    assert any("Ich bin der Neue" in s for s in ben)
    # Gegenprobe: MedDent waermt weiter die weibliche Form.
    bianca = gehirn.feste_saetze(MEDDENT)
    assert any("Ich bin die Neue" in s for s in bianca)
    assert not any("Ich bin der Neue" in s for s in bianca)


# ---- TTS-Stimme -----------------------------------------------------------

def test_stimme_jetzt_ist_ohne_override_der_prozess_default():
    assert tts.stimme_jetzt() == tts._VOICE_NAME


def test_stimme_kontext_wirkt_und_raeumt_auf():
    vorher = tts.stimme_jetzt()
    with tts.stimme("ben"):
        assert tts.stimme_jetzt() == "ben"
    assert tts.stimme_jetzt() == vorher


def test_leerer_override_faellt_auf_prozess_zurueck():
    """Ein Mandant OHNE Stimme-Feld darf die Prozess-Stimme nicht loeschen."""
    with tts.stimme(""):
        assert tts.stimme_jetzt() == tts._VOICE_NAME


def test_cache_schluessel_traegt_die_stimme():
    """Ben und Bianca teilen RAM- und Platten-Cache, duerfen sich aber
    nie hoeren."""
    satz = "Einen Moment."
    with tts.stimme("ben"):
        ben = tts._lokal_schluessel(satz)
    with tts.stimme("bianca"):
        bianca = tts._lokal_schluessel(satz)
    assert ben != bianca
    assert "ben" in ben and "bianca" in bianca


def test_payload_traegt_die_anruf_stimme(monkeypatch):
    """Der Container bekommt die Stimme DIESES Anrufs, nicht die des
    Prozesses — sonst antwortet Ben mit Biancas Stimme."""
    gesehen: list[dict] = []

    class FakeAntwort:
        status_code = 200
        content = b"\x01\x00" * 4000
        text = ""

    class FakeClient:
        def post(self, pfad, json=None, timeout=None):
            gesehen.append(dict(json or {}))
            return FakeAntwort()

    monkeypatch.setattr(tts, "_lokal_client", lambda: FakeClient())
    monkeypatch.setattr(tts, "TTS_BASE", "http://test")
    mund = tts.LokalTts()
    with tts.stimme("ben"):
        mund.speak("Guten Tag, hier ist Ben.")
    assert gesehen and gesehen[-1]["voice"] == "ben"
    gesehen.clear()
    with tts.stimme("bianca"):
        mund.speak("Guten Tag, hier ist Bianca.")
    assert gesehen and gesehen[-1]["voice"] == "bianca"


# ---- Faeden ---------------------------------------------------------------

def test_faden_nimmt_die_stimme_mit():
    """Ein frischer threading.Thread startet mit LEEREM Kontext — dann
    antwortete Bens Fueller/Vorab-Satz mit Biancas Stimme."""
    gehoert: list[str] = []
    with tts.stimme("ben"):
        t = dienst_mod.faden(lambda: gehoert.append(tts.stimme_jetzt()))
        t.start()
    t.join(5)
    assert gehoert == ["ben"]


def test_faden_ohne_override_spricht_den_prozess():
    gehoert: list[str] = []
    t = dienst_mod.faden(lambda: gehoert.append(tts.stimme_jetzt()))
    t.start()
    t.join(5)
    assert gehoert == [tts._VOICE_NAME]


def test_kontext_ist_pro_faden_getrennt():
    """Zwei Anrufe gleichzeitig: Ben darf Bianca die Stimme nicht
    unter den Fuessen wegziehen."""
    raus: dict[str, str] = {}

    def lauf(wer: str) -> None:
        with tts.stimme(wer):
            raus[wer] = tts.stimme_jetzt()

    import threading
    faeden = [threading.Thread(target=contextvars.copy_context().run,
                               args=(lauf, w)) for w in ("ben", "bianca")]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join(5)
    assert raus == {"ben": "ben", "bianca": "bianca"}


# ---- Vorgerenderte Saetze je Stimme ---------------------------------------

def _dienst() -> dienst_mod.Dienst:
    return dienst_mod.Dienst(name="t", start_fn=lambda sit: {},
                             turn_fn=lambda sit, t, **k: {})


def test_fueller_ablage_trennt_die_stimmen():
    d = _dienst()
    with tts.stimme("bianca"):
        d.vorab_ablegen("Einen Moment.", "/api/audio/bianca")
    with tts.stimme("ben"):
        d.vorab_ablegen("Einen Moment.", "/api/audio/ben")
        assert d.vorab_url("Einen Moment.") == "/api/audio/ben"
    with tts.stimme("bianca"):
        assert d.vorab_url("Einen Moment.") == "/api/audio/bianca"


def test_quittungen_und_notfall_je_mandant():
    d = _dienst()
    d.quittung_urls = {"": ["/q/bianca"], "ben": ["/q/ben"]}
    d.notfall_urls = {"": ["/n/bianca"], "ben": ["/n/ben"]}
    assert d.quittungen_fuer({"tenant": BEN}) == ["/q/ben"]
    assert d.notfall_fuer({"tenant": BEN}) == ["/n/ben"]
    # Gegenprobe: MedDent und ein Dock-Aufruf ohne Sitzung bekommen
    # weiter die Prozess-Stimme.
    assert d.quittungen_fuer({"tenant": MEDDENT}) == ["/q/bianca"]
    assert d.quittungen_fuer(None) == ["/q/bianca"]
    assert d.notfall_fuer(None) == ["/n/bianca"]


def test_unbekannte_mandanten_stimme_faellt_auf_prozess_zurueck():
    """Eine Praxis mit Stimme-Feld, die noch nicht vorgerendert ist, darf
    nicht stumm bleiben."""
    d = _dienst()
    d.quittung_urls = {"": ["/q/bianca"]}
    assert d.quittungen_fuer({"tenant": {"stimme": "neu"}}) == ["/q/bianca"]


def test_stimmen_im_haus_kennt_ben_und_den_prozess():
    stimmen = _dienst().stimmen_im_haus()
    assert stimmen[0] == ""       # Prozess-Default zuerst
    assert "ben" in stimmen       # aus tenants/ruether.json
    assert len(stimmen) == len(set(stimmen))


# ---- Sprechende Pfade: keiner darf die Stimme vergessen -------------------

def test_stimme_aus_sitzung_setzt_und_faellt_zurueck():
    token = dienst_mod.stimme_aus_sitzung({"tenant": tenants.laden("ruether")})
    try:
        assert tts.stimme_jetzt() == "ben"
    finally:
        tts.stimme_zuruecksetzen(token)
    # Gegenprobe: MedDent und eine Sitzung ohne Mandant bleiben Prozess.
    for sit in ({"tenant": MEDDENT}, {}, None):
        token = dienst_mod.stimme_aus_sitzung(sit)
        try:
            assert tts.stimme_jetzt() == tts._VOICE_NAME
        finally:
            tts.stimme_zuruecksetzen(token)


def test_stups_pfad_setzt_die_anruf_stimme():
    """/api/stille spricht ueber DIENST.stimme() direkt — am
    json_antwort-Pfad vorbei. Ohne stimme_aus_sitzung() stupste Biancas
    Stimme mitten in Bens Anruf (live nie passiert, weil hier gefangen)."""
    from bianca import server as bianca_server

    quelle = inspect.getsource(bianca_server.api_stille)
    assert "stimme_aus_sitzung(sit)" in quelle
    # ... und zwar VOR dem ersten Sprechen.
    assert (quelle.index("stimme_aus_sitzung(sit)")
            < quelle.index("DIENST.json_antwort"))


def test_sprechende_dienst_pfade_setzen_die_stimme():
    """Jeder Eingang, der eine Antwort vertont, muss die Mandanten-Stimme
    setzen. Eine neue Sitzung anzulegen, ohne das zu tun, ist der Fehler,
    der live als fremde Stimme auffaellt."""
    for fn in (dienst_mod.Dienst.json_antwort, dienst_mod.Dienst.zug_stream,
               dienst_mod.Dienst.weiter_sprechen):
        assert "stimme_aus_sitzung(sit)" in inspect.getsource(fn), fn.__name__


def test_alle_faeden_in_dienst_nehmen_den_kontext_mit():
    """``threading.Thread`` direkt waere ein stiller Stimm-Verlust —
    sprechende Faeden laufen ausschliesslich ueber faden(). Die EINE
    erlaubte Stelle ist faden() selbst."""
    quelle = inspect.getsource(dienst_mod)
    ohne_faden = quelle.replace(inspect.getsource(dienst_mod.faden), "")
    assert "threading.Thread(" not in ohne_faden
