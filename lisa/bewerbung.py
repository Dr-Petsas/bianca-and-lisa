"""Kampagnen-Lisa: bewirbt sich als Telefonistin. Keine Termine, kein Kalender.

Eigenes Gehirn, eigene Begrüßung, keine Werkzeuge. Die Patienten-Lisa
(lisa/agent.py) bleibt unberührt. Später ruft diese Stimme echte Praxen an.
"""

from __future__ import annotations

import re
from typing import Any

from kern import stille, wiederholung
from lisa import llm

ART = "bewerbung"

DEFAULT_AUFTRAG = (
    "Du rufst spontan in einer Praxis an und fragst, ob sie noch Personal "
    "für die Rezeption suchen. Du bist Lisa von Pickadoc. "
    "Kein Patiententermin, keine Legende. Ein Nein reicht."
)

GREETING = (
    "Hallo, mein Name ist Lisa von Pickadoc, und ich wollte nachfragen, "
    "ob Sie noch Personal für die Rezeption suchen. "
    "Ich hab einfach mal spontan angerufen, ich hoffe, ich störe Sie nicht gerade."
)

_KEIN_KALENDER = (
    "book_slot", "cancel_appointment", "move_appointment", "offer_slots",
    "list_appointments", "create_patient", "note_appointment",
)

ABSCHIED = "Oh, tut mir leid. Alles gut, dann störe ich nicht weiter."

_USER_ENDE = re.compile(
    r"(?<!nicht )stör(e|st|t|en)\b(?! nicht)|"
    r"keine zeit|kein interesse|nicht interess|nicht jetzt|"
    r"passt (gerade )?nicht|falsch verbunden|"
    r"\b(tschüss|tschus|ciao|bye|auf wiedersehen|wiederhören)\b",
    re.I,
)
_LISA_ENDE = re.compile(
    r"störe ich nicht|dann störe ich nicht|schönen (guten )?tag|"
    r"\btschüss\b|\bciao\b",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def begruessung(*, praxis_name: str = "") -> str:
    """Fester Einstieg — erst NACH der Meldung der Praxis, nicht beim Abheben."""
    return GREETING


def system_prompt(*, auftrag: str = "", praxis_name: str = "") -> str:
    ziel = _s(praxis_name)
    an = f"Du bist bei {ziel} in der Leitung.\n" if ziel else ""
    job = _s(auftrag) or DEFAULT_AUFTRAG
    return f"""Du bist Lisa. Du rufst von Pickadoc aus in einer Praxis an.
Du bist die Anruferin. Die andere Seite ist die Rezeption.
Du machst keine Patiententermine und öffnest keinen Kalender.
Du tust nicht so, als wärst du von dieser Praxis.
{an}
SO KLINGST DU
Wie jemand, der spontan durchwählt — locker, kurz, nicht wie ein Callcenter.
Kein Pitch, kein Lebenslauf, kein „KI-Telefonistin“-Vortrag, außer sie fragen wer du bist.
Ein Zug = ein Gedanke, höchstens zwei Sätze, dann zuhören.
Nicht jedes Mal denselben Satz. Nicht steif, nicht förmlich („Personalentscheidungen“, „Unterlagen senden“).
Wenn sie unwirsch sind: kurz entschuldigen, nicht weitermachen als wär nichts.

ERSTER SATZ IST SCHON GESPROCHEN
Deine Begrüßung steht oben im Verlauf. Nicht nochmal hallo, nicht nochmal Pickadoc, nicht nochmal Rezeption — außer sie haben nicht verstanden.
Reagiere auf DAS, was sie gerade gesagt haben.

WENN JA / INTERESSE
Ganz klein weiter: ob du kurz sagen darfst, worum es geht, oder wen du dazu erreichen kannst.
Kein Monolog über Produkte.

WENN NEIN / KEINE ZEIT
„Alles gut, dann störe ich nicht weiter.“ Auflegen. Nicht nachhaken.

EHRLICHKEIT
Wenn sie fragen, wer Pickadoc ist oder ob du ein Mensch bist: ehrlich, ein Satz. Keine Legende.

WERKZEUGE
Keine.

AUFTRAG
{job}
"""


def start_reply(session_doc: dict) -> dict[str, Any]:
    """Leitung steht — Lisa schweigt, bis sich jemand gemeldet hat."""
    session_doc["lisaArt"] = ART
    session_doc["idCheck"] = "fertig"
    session_doc["booking"] = {}
    session_doc["wartetAufMeldung"] = True
    session_doc["ttsGanz"] = True
    praxis = _praxis(session_doc)
    auftrag = _s(session_doc.get("auftrag")) or DEFAULT_AUFTRAG
    session_doc["auftrag"] = auftrag
    session_doc["messages"] = [
        {"role": "system", "content": system_prompt(auftrag=auftrag, praxis_name=praxis)},
    ]
    return {"text": "", "book": None}


def user_turn(session_doc: dict, spoken: str, melde=None, vorab=None) -> dict[str, Any]:
    text_in = _s(spoken)
    if not text_in:
        return {"text": "", "book": None}
    stille.reset(session_doc)
    msgs = list(session_doc.get("messages") or [])
    if not msgs:
        start_reply(session_doc)
        msgs = list(session_doc.get("messages") or [])
    if session_doc.get("wartetAufMeldung"):
        text = begruessung(praxis_name=_praxis(session_doc))
        session_doc["wartetAufMeldung"] = False
        msgs.append({"role": "user", "content": text_in})
        msgs.append({"role": "assistant", "content": text})
        session_doc["messages"] = msgs
        return {"text": text, "book": None}
    if _user_will_ende(text_in):
        letzte = ""
        for m in reversed(msgs):
            if m.get("role") == "assistant":
                letzte = _s(m.get("content"))
                break
        text = "Tschüss." if _lisa_verabschiedet(letzte) else ABSCHIED
        msgs.append({"role": "user", "content": text_in})
        msgs.append({"role": "assistant", "content": text})
        session_doc["messages"] = msgs
        return {"text": text, "book": None, "hangup": True}
    msgs.append({"role": "user", "content": text_in})
    out = llm.chat(msgs, None, max_tokens=90, temperature=0.4)
    if not out.get("ok"):
        return {
            "text": "Einen Moment, ich habe Sie gerade nicht ganz verstanden. Darf ich das noch einmal sagen?",
            "error": out.get("error"),
            "book": None,
        }
    text = _s(out.get("text"))
    if any(w in text for w in _KEIN_KALENDER):
        text = "Nee, nicht wegen eines Termins — mir gings um die Rezeption. Wen kann ich dazu kurz sprechen?"
    ent = wiederholung.pruefen(
        session_doc, text,
        frueher=wiederholung.letzte_antworten(session_doc.get("messages") or []),
    )
    if ent:
        text = ent
    if text:
        msgs.append({"role": "assistant", "content": text})
    session_doc["messages"] = msgs
    return {"text": text, "book": None, "hangup": _lisa_verabschiedet(text)}


def stille_zug(session_doc: dict) -> dict[str, Any]:
    n = stille.stups_zaehlen(session_doc)
    if n > stille.MAX_STUPSE:
        return {"text": "", "book": None}
    if session_doc.get("wartetAufMeldung"):
        text = "Hallo?"
        stille.anhaengen(session_doc, text)
        return {"text": text, "book": None}
    text = stille.anrede(n)
    if n == 1:
        text = f"{text} Ich bin noch dran — passt es ganz kurz?"
    else:
        text = f"{text} Soll ich später nochmal anrufen?"
    ent = wiederholung.pruefen(
        session_doc, text,
        frueher=wiederholung.letzte_antworten(session_doc.get("messages") or []),
    )
    text = ent or text
    stille.anhaengen(session_doc, text)
    return {"text": text, "book": None}


def hangup(session_doc: dict) -> dict[str, Any]:
    """Kein Kalender, keine Terminnotiz."""
    return {}


def _user_will_ende(text: str) -> bool:
    return bool(_USER_ENDE.search(_s(text)))


def _lisa_verabschiedet(text: str) -> bool:
    return bool(_LISA_ENDE.search(_s(text)))


def _praxis(sit: dict) -> str:
    km = sit.get("kampagne") if isinstance(sit.get("kampagne"), dict) else {}
    pat = sit.get("patient") if isinstance(sit.get("patient"), dict) else {}
    return _s(
        sit.get("praxisName")
        or km.get("praxisName")
        or pat.get("praxis")
        or ""
    )
