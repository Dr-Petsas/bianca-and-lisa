from __future__ import annotations

from typing import Any

from kern import gedaechtnis, gespraech, stille, tenants, wiederholung, zuege
from kern import wissen as kern_wissen
from lisa import calendar, identitaet, llm, nummer, session
from lisa.greeting import begruessung
from lisa.prompt import TOOLS, system_prompt


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _termine_zeile(past: list, upcoming: list) -> str:
    teile = []
    if upcoming:
        teile.append("Kommend: " + "; ".join(x.get("label") or "" for x in upcoming[:4]))
    if past:
        teile.append("Zuletzt: " + "; ".join(x.get("label") or "" for x in past[-3:]))
    return " | ".join(teile)


def start_reply(session_doc: dict) -> dict[str, Any]:
    tenant = session_doc["tenant"]
    patient = session_doc.get("patient") or {}
    # W-GEDAECHTNIS: Lisa weiss schon beim Waehlen, WEN sie anruft — das
    # Praxisgedaechtnis (MAS) parallel abfragen, bevor der erste Zug faellt.
    gedaechtnis.kontext_anstossen(session_doc)
    text = begruessung(
        tenants.praxis_von(tenant),
        _s(session_doc.get("auftrag")),
        patient=patient,
        behandler=_s(tenant.get("behandler")),
    )
    msgs = [
        {
            "role": "system",
            "content": system_prompt(
                praxis=_s(tenant.get("praxisName")),
                praxis_von=tenants.praxis_von(tenant),
                behandler=_s(tenant.get("behandler")),
                auftrag=_s(session_doc.get("auftrag")),
                patient=_s(patient.get("name")),
                sprache=_s(tenant.get("sprache")) or "de",
                termine_text=_termine_zeile(session_doc.get("past") or [], session_doc.get("upcoming") or []),
                slots_text=calendar.slots_zeile(session_doc.get("offered") or []),
                wissen=tenant.get("wissen"),
                kontext=gedaechtnis.kontext_block(session_doc),
                unterlage=_s((session_doc.get("vorbereitung") or {}).get("briefing")),
            ),
        },
        {
            "role": "user",
            "content": "(Der Angerufene hat abgehoben. Beginne jetzt mit Begrüßung und Auftrag.)",
        },
        {"role": "assistant", "content": text},
    ]
    session_doc["messages"] = msgs
    # Identitaetscheck laeuft deterministisch, bevor das Modell dran ist.
    session_doc["idCheck"] = (
        identitaet.FRAGE if identitaet.moeglich(patient) else identitaet.FERTIG
    )
    return {"text": text, "book": None}


def stille_zug(session_doc: dict) -> dict[str, Any]:
    """Stille-Wächter (Chef 27.08.2026): der Angerufene sagt seit ~4 Sekunden
    nichts — Lisa ergreift das Wort und knüpft am Stand an: Identitätsfrage
    bzw. Auftrag plus zuletzt gestellte Frage (mit Präfix, nie wortgleich —
    Wiederholungs-Wächter-Regel). Nach MAX_STUPSE Stupsen: Schweigen, bis
    wieder gesprochen wird (user_turn setzt den Zähler zurück)."""
    n = stille.stups_zaehlen(session_doc)
    if n > stille.MAX_STUPSE:
        return {"text": "", "book": None}
    if nummer.sucht(session_doc):
        text = "Kein Stress — ich warte, bis Sie die Nummer haben."
        stille.anhaengen(session_doc, text)
        return {"text": text, "book": None}
    teile = [stille.anrede(n)]
    if _s(session_doc.get("idCheck")) in {identitaet.FRAGE, identitaet.HOLEN, identitaet.WARTEN}:
        teile.append(stille.frage_praefix(identitaet.frage_satz(session_doc.get("patient") or {})))
    elif nummer.aktiv(session_doc):
        teile.append("Sagen Sie die Nummer, wenn Sie soweit sind. Ich warte.")
    else:
        auftrag = _s(session_doc.get("auftrag"))
        if auftrag:
            teile.append(f"Es geht um Folgendes: {auftrag}.")
        offene = stille.letzte_frage(session_doc.get("messages") or [])
        if offene:
            teile.append(stille.frage_praefix(offene))
    text = " ".join(x for x in teile if x).strip()
    ent = wiederholung.pruefen(
        session_doc, text,
        frueher=wiederholung.letzte_antworten(session_doc.get("messages") or []),
    )
    text = ent or text
    stille.anhaengen(session_doc, text)
    return {"text": text, "book": None}


def user_turn(session_doc: dict, spoken: str, melde=None, vorab=None) -> dict[str, Any]:
    text_in = _s(spoken)
    if not text_in:
        return {"text": "", "book": None}
    stille.reset(session_doc)  # es wird wieder gesprochen — Stupse von vorn
    # W-GEDAECHTNIS: key-gesichert — laeuft nur, wenn neue Fakten da sind.
    gedaechtnis.kontext_anstossen(session_doc)
    msgs = list(session_doc.get("messages") or [])
    if not msgs:
        return start_reply(session_doc)
    msgs.append({"role": "user", "content": text_in})
    # Solange nicht geklaert ist, WER am Telefon sitzt, antwortet die
    # Zustandsmaschine — ohne Modell, also ohne Wartezeit und ohne Abweichen.
    id_zug = identitaet.naechster_zug(session_doc, text_in)
    if not id_zug:
        id_zug = nummer.naechster_zug(session_doc, text_in)
    # Talk-Schicht (kern/gespraech.py): hoert jeden Satz ab und entscheidet,
    # wie frei das Modell gleich sprechen darf — der Auftrag bleibt Gesetz.
    route = gespraech.routen(
        session_doc, text_in,
        job_gesprochen=bool(id_zug),
        job_aktiv=True,
    )
    if id_zug:
        msgs.append({"role": "assistant", "content": id_zug["text"]})
        session_doc["messages"] = msgs
        gespraech.nach_antwort(session_doc)
        return {"text": id_zug["text"], "book": None}
    # Gespraechslage frisch in den Systemprompt (Talk-/Brueckenzuege).
    plan = gespraech.plan_block(route, stimme="lisa")
    if msgs and msgs[0].get("role") == "system":
        msgs[0]["content"] = system_prompt_aktuell(session_doc, plan=plan)
    # Stream: der erste fertige Satz geht sofort an die Stimme (vorab),
    # waehrend das Modell den Rest schreibt — halbiert die gefuehlte Latenz.
    # Weg-/Anfahrtsfragen: einzige erlaubte Langtext-Antwort — Limit anheben.
    extra = {"max_tokens": kern_wissen.LANGTEXT_MAX_TOKENS} if kern_wissen.braucht_langtext(text_in) else {}
    # Talk-/Brueckenzuege duerfen laenger und waermer sein als Job-Zuege.
    for k, v in gespraech.budget(route["floor"]).items():
        if k == "max_tokens":
            extra[k] = max(int(extra.get(k) or 0), int(v))
        else:
            extra[k] = v
    if vorab is not None:
        out = llm.chat_stream(msgs, TOOLS, erster_satz=vorab, **extra)
    else:
        out = llm.chat(msgs, TOOLS, **extra)
    if not out.get("ok"):
        return {
            "text": "Einen Moment, ich komme gerade nicht an den Kalender. Darf ich später noch einmal anrufen?",
            "error": out.get("error"),
            "book": None,
        }
    # Werkzeug-Schleife und Wachen liegen im gemeinsamen Kern (kern.zuege) —
    # dieselbe Mechanik traegt auch Bianca.
    text, msgs, book = zuege.apply_tools(session_doc, msgs, out, melde=melde)
    # Wiederholungs-Wächter (Chef 27.08.2026): wortgleich wiederholte Frage-/
    # Langsätze gegen die letzten Antworten streichen — nie stumm werden.
    # session_doc["messages"] traegt hier noch den Stand VOR diesem Zug.
    entdoppelt = wiederholung.pruefen(
        session_doc, text,
        frueher=wiederholung.letzte_antworten(session_doc.get("messages") or []),
    )
    if entdoppelt and entdoppelt != text:
        text = entdoppelt
        if msgs and msgs[-1].get("role") == "assistant":
            msgs[-1]["content"] = text
    session_doc["messages"] = msgs
    gespraech.nach_antwort(session_doc)
    # W-GEDAECHTNIS: Werkzeuge koennen den Patienten nachgeladen haben.
    gedaechtnis.kontext_anstossen(session_doc)
    return {"text": text, "book": book}


def system_prompt_aktuell(session_doc: dict, plan: str = "") -> str:
    tenant = session_doc["tenant"]
    patient = session_doc.get("patient") or {}
    return system_prompt(
        praxis=_s(tenant.get("praxisName")),
        praxis_von=tenants.praxis_von(tenant),
        behandler=_s(tenant.get("behandler")),
        auftrag=_s(session_doc.get("auftrag")),
        patient=_s(patient.get("name")),
        sprache=_s(tenant.get("sprache")) or "de",
        termine_text=_termine_zeile(session_doc.get("past") or [], session_doc.get("upcoming") or []),
        slots_text=calendar.slots_zeile(session_doc.get("offered") or []),
        wissen=tenant.get("wissen"),
        plan=plan,
        kontext=gedaechtnis.kontext_block(session_doc),
        unterlage=_s((session_doc.get("vorbereitung") or {}).get("briefing")),
    )


def hangup(session_doc: dict) -> dict[str, Any]:
    return zuege.auto_notiz(session_doc, force=True)
