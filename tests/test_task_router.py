"""Semantischer Task-Handoff: Bedeutung vom LLM, Ausführung vom Flow."""

import json
import os

from bianca import agent, flow, gehirn
from kern import gespraech, hirn, task_router
from kern.tenants import laden


def _sit() -> dict:
    sit = {
        "id": "task-test",
        "stimme": "Bianca",
        "tenant": laden("meddent"),
        "messages": [
            {"role": "system", "content": "test"},
            {"role": "assistant", "content": "Was kann ich für Sie tun?"},
        ],
        "booking": {},
        "tools": [],
        "zuege": [],
    }
    hirn.init(sit)
    gehirn.sammler(sit)
    return sit


def _out(operation: str = "buchen", reason: str = "Kontrolle") -> dict:
    return {
        "ok": True,
        "text": "",
        "tool_calls": [{
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "select_task",
                "arguments": json.dumps({"operation": operation, "reason": reason}),
            },
        }],
    }


def test_task_schema_deckt_natuerlichen_terminwunsch_ab():
    beschreibung = task_router.TOOLS[0]["function"]["description"]
    assert "ich möchte zur Kontrolle" in beschreibung
    assert "terminauskunft" in beschreibung
    assert "NIEMALS selbst nach Name" in task_router.PROMPT


def test_task_auswahl_verwirft_unbekannte_operation():
    assert task_router.auswahl(_out("erfinde_termin")) == {}
    assert task_router.auswahl(_out("buchen"))["operation"] == "buchen"


def test_llm_bekommt_keine_direkten_kalenderaktionen():
    sit = _sit()
    namen = {
        tool["function"]["name"] for tool in task_router.werkzeuge_fuer(sit)
    }
    assert namen == {"select_task"}
    sit["sammler"]["phase"] = "gebucht"
    sit["booking"]["appointmentId"] = "termin-1"
    namen = {
        tool["function"]["name"] for tool in task_router.werkzeuge_fuer(sit)
    }
    assert namen == {"select_task", "note_appointment"}
    assert not namen & {
        "book_slot", "cancel_appointment", "move_appointment",
        "offer_slots", "list_appointments", "create_patient",
    }


def test_prompt_unterscheidet_laufende_aufgabe_vom_neuen_task():
    sit = _sit()
    assert "noch keine sichere Fachaufgabe" in task_router.prompt(sit)
    hirn.anwenden(sit, {
        "kanal": "ok", "zug": "wechseln", "handlung": "ANLEGEN",
        "gegenstand": "VORGANG", "spiegel": "Kontrolle",
    })
    sit["sammler"]["frage"] = "wunsch"
    text = task_router.prompt(sit)
    assert "Aufgabe buchen" in text
    assert "Offener Dialogschritt: wunsch" in text
    assert "klar anderen Anliegen" in text


def test_task_handoff_schaltet_nur_den_sicheren_maschinenmodus():
    sit = _sit()
    wahl = task_router.auswahl(_out("buchen", "Kontrolltermin gewünscht"))
    assert task_router.anwenden(sit, wahl, original="Ich möchte zur Kontrolle.")
    assert sit["sammler"]["modus"] == "buchen"
    assert sit["hirn"]["anliegen"][0]["handlung"] == "ANLEGEN"
    assert sit["taskRouter"][0]["quelle"] == "haupt_llm"
    assert not sit["tools"]  # select_task ist keine Kalenderaktion


def test_live_satz_landet_nach_handoff_in_erster_pflichtfrage():
    sit = _sit()
    text = "Ich möchte zur Kontrolle, der Behandler ist mir egal."
    # Der bisherige Flow erntet Grund/Standard-Behandler, erkennt aber ohne
    # Termin-Schlüsselwort noch keine sichere Aufgabe.
    assert flow.zug(sit, text) is None
    assert task_router.anwenden(
        sit, {"operation": "buchen", "reason": "Kontrolle gewünscht"}, original=text
    )
    antwort = flow.zug(sit, text)
    assert antwort and "schon einmal" in antwort["text"]
    assert sit["sammler"]["modus"] == "buchen"
    assert sit["sammler"]["frage"] == "schonmal"


def test_kataloggrund_plus_ausdruecklicher_wunsch_startet_sicheren_task():
    sit = _sit()
    text = "Ich möchte eine Besprechung für eine neue Prothese."
    assert flow.zug(sit, text) is None
    assert sit["sammler"]["grund"] == "Zahnersatz-Beratung"
    wahl = task_router.aus_sicherer_ernte(
        sit, text, sit.get("ernteZuletzt") or [],
    )
    assert wahl["operation"] == "buchen"

    assert task_router.anwenden(
        sit, wahl, original=text, quelle="sichere_ernte",
    )
    antwort = flow.zug(sit, text)
    assert antwort and "schon einmal" in antwort["text"]
    assert sit["sammler"]["modus"] == "buchen"
    assert sit["taskRouter"][-1]["quelle"] == "sichere_ernte"


def test_kataloggrund_allein_macht_aus_preisfrage_keine_buchung():
    sit = _sit()
    s = sit["sammler"]
    s.update({
        "grund": "Zahnersatz-Beratung",
        "grundWortlaut": "Was kostet eine neue Prothese?",
    })
    assert task_router.aus_sicherer_ernte(
        sit,
        "Ich möchte wissen, was eine neue Prothese kostet.",
        ["grund"],
    ) == {}
    assert task_router.aus_sicherer_ernte(
        sit,
        "Ich möchte keine neue Prothese.",
        ["grund"],
    ) == {}


def test_live_prothesen_satz_braucht_keinen_llm_und_eroeffnet_flow():
    sit = _sit()

    def niemals_llm(*_a, **_k):
        raise AssertionError("Der sichere Katalog-Handoff darf kein LLM brauchen")

    chat_alt = agent.llm.chat
    stream_alt = agent.llm.chat_stream
    hg_alt = agent.flow.hintergrund.anstossen
    env_alt = os.environ.get("INTENT_NACHZUG")
    try:
        agent.llm.chat = niemals_llm
        agent.llm.chat_stream = niemals_llm
        agent.flow.hintergrund.anstossen = lambda _sit: None
        os.environ["INTENT_NACHZUG"] = "0"
        antwort = agent.user_turn(
            sit, "Ich möchte eine Besprechung für eine neue Prothese."
        )
    finally:
        agent.llm.chat = chat_alt
        agent.llm.chat_stream = stream_alt
        agent.flow.hintergrund.anstossen = hg_alt
        if env_alt is None:
            os.environ.pop("INTENT_NACHZUG", None)
        else:
            os.environ["INTENT_NACHZUG"] = env_alt
    assert "schon einmal" in antwort["text"]
    assert sit["sammler"]["modus"] == "buchen"
    assert sit["sammler"]["frage"] == "schonmal"
    assert sit["taskRouter"][-1]["quelle"] == "sichere_ernte"


def test_nacktes_terminwort_wird_ohne_llm_nach_aktion_gefragt():
    """Ein „Termin“ ist akustisch klar, semantisch aber nicht eindeutig."""
    sit = _sit()

    def niemals_llm(*_a, **_k):
        raise AssertionError("Einwort-Klaerung darf kein LLM brauchen")

    chat_alt = agent.llm.chat
    stream_alt = agent.llm.chat_stream
    try:
        agent.llm.chat = niemals_llm
        agent.llm.chat_stream = niemals_llm
        antwort = agent.user_turn(sit, "Termin")
    finally:
        agent.llm.chat = chat_alt
        agent.llm.chat_stream = stream_alt

    text = antwort["text"].lower()
    assert "vereinbaren" in text and "verschieben" in text and "absagen" in text
    assert sit["einwortTerminOffen"] is True
    assert not sit["sammler"]["modus"]


def test_einwort_terminauswahl_startet_den_sicheren_flow():
    """Auch die Antwort auf die Auswahl darf wieder nur ein Wort sein."""
    faelle = [
        ("Neu", "buchen", "schon"),
        ("Verschieben", "verschieben", "nachname"),
        ("Absage", "absagen", "nachname"),
    ]
    hg_alt = agent.flow.hintergrund.anstossen
    chat_alt = agent.llm.chat
    stream_alt = agent.llm.chat_stream

    def niemals_llm(*_a, **_k):
        raise AssertionError("Einwort-Auswahl muss deterministisch bleiben")

    try:
        agent.flow.hintergrund.anstossen = lambda _sit: None
        agent.llm.chat = niemals_llm
        agent.llm.chat_stream = niemals_llm
        for antwortwort, modus, antwortanker in faelle:
            sit = _sit()
            agent.user_turn(sit, "Termin")
            antwort = agent.user_turn(sit, antwortwort)
            assert sit["sammler"]["modus"] == modus, antwortwort
            assert antwortanker in antwort["text"].lower(), antwortwort
            assert "einwortTerminOffen" not in sit
    finally:
        agent.flow.hintergrund.anstossen = hg_alt
        agent.llm.chat = chat_alt
        agent.llm.chat_stream = stream_alt


def test_mitarbeiter_einwort_bleibt_deterministisch():
    sit = _sit()

    def niemals_llm(*_a, **_k):
        raise AssertionError("Mitarbeiter muss der sichere Weiterleitungsweg sein")

    chat_alt = agent.llm.chat
    stream_alt = agent.llm.chat_stream
    try:
        agent.llm.chat = niemals_llm
        agent.llm.chat_stream = niemals_llm
        antwort = agent.user_turn(sit, "Mitarbeiter")
    finally:
        agent.llm.chat = chat_alt
        agent.llm.chat_stream = stream_alt

    assert "Telefonassistentin" in antwort["text"]
    assert "Worum geht es" in antwort["text"]
    assert sit["weiterleiten"]["frage"] == "anliegen"


def test_mitarbeiter_darf_offene_termin_klaerung_ueberstimmen():
    sit = _sit()
    agent.user_turn(sit, "Termin")
    antwort = agent.user_turn(sit, "Mitarbeiter")
    assert "Telefonassistentin" in antwort["text"]
    assert sit["weiterleiten"]["frage"] == "anliegen"
    assert "einwortTerminOffen" not in sit


def test_ganzsatz_bitte_nur_einmal_danach_konkrete_auswahl():
    sit = _sit()
    env_alt = os.environ.get("INTENT_NACHZUG")
    try:
        os.environ["INTENT_NACHZUG"] = "0"
        erste = agent.user_turn(sit, "Füsebte")
        zweite = agent.user_turn(sit, "Dornenze")
    finally:
        if env_alt is None:
            os.environ.pop("INTENT_NACHZUG", None)
        else:
            os.environ["INTENT_NACHZUG"] = env_alt

    assert "ganzen Satz" in erste["text"]
    assert zweite["text"] == gespraech.UNKLAR_AUSWAHL_ANTWORT
    assert "ganzen Satz" not in zweite["text"]
    assert sit["ganzsatzHinweisGegeben"] is True


def test_einwort_klaerung_greift_nie_in_offene_formularfrage():
    sit = _sit()
    s = sit["sammler"]
    s.update({"modus": "buchen", "phase": "", "frage": "nachname"})
    arbeits_text, frage = agent._einwort_termin_vorbereiten(sit, "Termin")
    assert arbeits_text == "Termin"
    assert frage == ""
    assert "einwortTerminOffen" not in sit


def test_zweite_unklare_namensantwort_zieht_aus_zustandsluecke_zurueck():
    """Wortgleicher Live-Super-GAU: freie Namensfrage darf nie endlos loopen."""
    sit = _sit()
    s = sit["sammler"]
    s.update({
        "grund": "Zahnersatz-Beratung",
        "grundWortlaut": "Ich möchte eine Besprechung für eine neue Prothese.",
        "fuerWen": "sohn",
    })
    hg_alt = agent.flow.hintergrund.anstossen
    env_alt = os.environ.get("INTENT_NACHZUG")
    try:
        agent.flow.hintergrund.anstossen = lambda _sit: None
        os.environ["INTENT_NACHZUG"] = "0"
        z1 = agent.user_turn(sit, "Hrisovalanis Charalampopoulos")
        z2 = agent.user_turn(sit, "Matthias Jäger")
    finally:
        agent.flow.hintergrund.anstossen = hg_alt
        if env_alt is None:
            os.environ.pop("INTENT_NACHZUG", None)
        else:
            os.environ["INTENT_NACHZUG"] = env_alt
    assert z1["text"] == agent.gespraech.UNKLAR_ANTWORT
    assert "schon einmal" in z2["text"]
    assert "Ihr Sohn" in z2["text"]
    assert s["modus"] == "buchen"
    assert sit["taskRouter"][-1]["quelle"] == "schleifen_ausstieg"


def test_agent_reicht_unklaren_buchungswunsch_semantisch_an_flow():
    sit = _sit()
    flow_alt = agent.flow.zug
    chat_alt = agent.llm.chat
    enabled_alt = agent.intent.enabled
    aufrufe: list[str] = []

    def flow_fake(sitzung, text, melde=None):
        aufrufe.append(sitzung["sammler"].get("modus") or "")
        if sitzung["sammler"].get("modus") == "buchen":
            sitzung["sammler"]["frage"] = "anrufer_check"
            return {"text": "Der Termin ist für Sie selbst, richtig?"}
        return None

    def chat_fake(messages, tools=None, **kwargs):
        assert tools == task_router.TOOLS
        assert "TASK-AUSWAHL" in messages[0]["content"]
        return _out("buchen", "Kontrolle gewünscht")

    try:
        agent.flow.zug = flow_fake
        agent.llm.chat = chat_fake
        agent.intent.enabled = lambda: False
        antwort = agent.user_turn(
            sit, "Ich möchte zur Kontrolle, der Behandler ist mir egal."
        )
    finally:
        agent.flow.zug = flow_alt
        agent.llm.chat = chat_alt
        agent.intent.enabled = enabled_alt

    assert aufrufe == ["", "buchen"]
    assert antwort["text"] == "Der Termin ist für Sie selbst, richtig?"
    assert sit["sammler"]["frage"] == "anrufer_check"
    assert not sit["tools"]


def test_agent_parkt_laufende_buchung_bei_semantischem_taskwechsel():
    sit = _sit()
    hirn.anwenden(sit, {
        "kanal": "ok", "zug": "wechseln", "handlung": "ANLEGEN",
        "gegenstand": "VORGANG", "spiegel": "neuer Termin",
    })
    sit.pop("hirnModusNeu", None)
    sit["sammler"]["frage"] = "wunsch"
    flow_alt = agent.flow.zug
    chat_alt = agent.llm.chat
    enabled_alt = agent.intent.enabled
    aufrufe: list[str] = []

    def flow_fake(sitzung, text, melde=None):
        modus = sitzung["sammler"].get("modus") or ""
        aufrufe.append(modus)
        if modus == "absagen":
            sitzung["sammler"]["frage"] = "nachname"
            return {"text": "Wie ist Ihr Nachname?"}
        return None

    def chat_fake(messages, tools=None, **kwargs):
        namen = {tool["function"]["name"] for tool in tools or []}
        assert namen == {"select_task"}
        assert "Aktuell läuft die Aufgabe buchen" in messages[0]["content"]
        return _out("absagen", "Der bestehende Termin wird nicht mehr benötigt")

    try:
        agent.flow.zug = flow_fake
        agent.llm.chat = chat_fake
        agent.intent.enabled = lambda: False
        antwort = agent.user_turn(
            sit, "Den vorhandenen brauche ich dann doch nicht mehr."
        )
    finally:
        agent.flow.zug = flow_alt
        agent.llm.chat = chat_alt
        agent.intent.enabled = enabled_alt

    assert aufrufe == ["buchen", "absagen"]
    assert antwort["text"] == "Wie ist Ihr Nachname?"
    assert [a["status"] for a in sit["hirn"]["anliegen"]] == ["geparkt", "aktiv"]
    assert not sit["tools"]


def test_agent_verliert_bei_ja_aber_weder_antwort_noch_task(monkeypatch):
    """Die Antwort gilt noch dem alten Zustand, der Zusatz dem neuen Task."""
    sit = _sit()
    hirn.anwenden(sit, {
        "kanal": "ok", "zug": "wechseln", "handlung": "ANLEGEN",
        "gegenstand": "VORGANG", "spiegel": "neuer Termin",
    })
    sit.pop("hirnModusNeu", None)
    sit["sammler"]["frage"] = "anrufer_check"
    aufrufe: list[tuple[str, str]] = []

    def flow_fake(sitzung, text, melde=None):
        modus = sitzung["sammler"].get("modus") or ""
        aufrufe.append((modus, text))
        if text == "Ja":
            sitzung["sammler"]["anruferCheck"] = "ja"
            sitzung["sammler"]["frage"] = "grund"
            return {"text": "Worum geht es bei dem neuen Termin?"}
        if modus == "absagen":
            sitzung["sammler"]["frage"] = "nachname"
            return {"text": "Wie ist Ihr Nachname?"}
        return None

    monkeypatch.setattr(agent.flow, "zug", flow_fake)
    monkeypatch.setattr(
        agent.llm, "chat",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("Klarer Mischzug braucht keinen LLM-Aufruf")
        ),
    )
    monkeypatch.setenv("INTENT_NACHZUG", "0")

    antwort = agent.user_turn(
        sit, "Ja, aber ich möchte meinen bestehenden Termin absagen."
    )

    assert aufrufe == [
        ("buchen", "Ja"),
        ("absagen", "ich möchte meinen bestehenden Termin absagen."),
    ]
    assert sit["sammler"]["anruferCheck"] == "ja"
    assert antwort["text"] == "Wie ist Ihr Nachname?"
    assert [a["status"] for a in sit["hirn"]["anliegen"]] == ["geparkt", "aktiv"]
    assert any(w.get("w") == "mischzug" for w in sit.get("_spur") or [])


def test_presence_ja_bestaetigt_keine_patientenidentitaet(monkeypatch):
    sit = _sit()
    hirn.anwenden(sit, {
        "kanal": "ok", "zug": "wechseln", "handlung": "ANLEGEN",
        "gegenstand": "VORGANG", "spiegel": "neuer Termin",
    })
    sit.pop("hirnModusNeu", None)
    sit["sammler"]["frage"] = "anrufer_check"
    sit["messages"].append({"role": "assistant", "content": "Sind Sie noch dran?"})
    aufrufe: list[tuple[str, str]] = []

    def flow_fake(sitzung, text, melde=None):
        modus = sitzung["sammler"].get("modus") or ""
        aufrufe.append((modus, text))
        if modus == "absagen":
            return {"text": "Wie ist Ihr Nachname?"}
        raise AssertionError("Presence-Ja darf nicht separat geerntet werden")

    monkeypatch.setattr(agent.flow, "zug", flow_fake)
    monkeypatch.setenv("INTENT_NACHZUG", "0")

    antwort = agent.user_turn(
        sit, "Ja, aber ich möchte meinen bestehenden Termin absagen."
    )

    assert aufrufe == [(
        "absagen", "Ja, aber ich möchte meinen bestehenden Termin absagen."
    )]
    assert not sit["sammler"].get("anruferCheck")
    assert antwort["text"] == "Wie ist Ihr Nachname?"
