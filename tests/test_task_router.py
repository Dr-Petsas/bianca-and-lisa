"""Semantischer Task-Handoff: Bedeutung vom LLM, Ausführung vom Flow."""

import json

from bianca import agent, flow, gehirn
from kern import hirn, task_router
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


def test_task_auswahl_verwirft_unbekannte_operation():
    assert task_router.auswahl(_out("erfinde_termin")) == {}
    assert task_router.auswahl(_out("buchen"))["operation"] == "buchen"


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
