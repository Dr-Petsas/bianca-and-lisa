"""TurnPlanV1: validierter LLM-Plan, ausschließlich offline/im Shadow.

Der Plan formuliert keine Patientenfakten und führt nichts aus. Er beschreibt
nur die semantische Lesart, den nächsten Dialogschritt und vorgeschlagene
Werkzeuge. Jeder Fakt muss auf einen Pfad im TurnContextV1 zeigen; Kalender-
und Motiv-IDs müssen aus dessen Registern stammen. Schreibwerkzeuge brauchen
immer ein explizites Bestätigungs-Gate.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from kern import turn_context
from kern.werkzeuge import TOOLS

VERSION = 1
SCHEMA = "pickadoc.turn-plan/v1"

INTENTS = {
    "buchen", "absagen", "verschieben", "terminauskunft", "verbinden",
    "praxisinfo", "rueckruf", "dokument", "smalltalk", "korrektur", "unklar",
}
MODI = {"job", "talk", "blend"}
NAECHSTE = {"fragen", "erklaeren", "werkzeug", "warten", "uebergeben", "antworten"}
FRAGE_SLOTS = {
    "", "identitaet", "nachname", "vorname", "behandler", "besuchsgrund",
    "wunschzeit", "telefon", "terminwahl", "bestaetigung", "fuer_wen",
}
TOOL_NAMEN = {
    str((x.get("function") or {}).get("name") or "")
    for x in TOOLS if isinstance(x, dict)
}
TOOL_NAMEN.discard("")
TOOL_SCHEMAS = {
    str((x.get("function") or {}).get("name") or "").strip(): (
        (x.get("function") or {}).get("parameters") or {}
    )
    for x in TOOLS if isinstance(x, dict)
}
SCHREIB_TOOLS = {
    "create_patient", "book_slot", "cancel_appointment",
    "move_appointment", "note_appointment",
}
GATES = {"keins", "fakten_bereit", "anrufer_bestaetigt"}
_QUELLEN = {
    "sitzung": "gespraech",
    "praxis": "pickadoc_konfiguration",
    "patient": "bestaetigte_identitaet",
    "anliegen": "sammler",
    "angebot": "kalender",
    "mas": "mas_gefiltert",
    "werkzeuge": "tool_ledger",
    "fachtemplate": "fachtemplate",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _json_aus_text(text: str) -> dict[str, Any]:
    roh = str(text or "").strip()
    if roh.startswith("```"):
        roh = re.sub(r"^```(?:json)?\s*", "", roh, flags=re.I)
        roh = re.sub(r"\s*```$", "", roh)
    try:
        obj = json.loads(roh)
    except (TypeError, ValueError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _pfadwert(ctx: dict[str, Any], pfad: str) -> Any:
    wert: Any = ctx
    for teil in _s(pfad).split("."):
        if not isinstance(wert, dict) or teil not in wert:
            return None
        wert = wert[teil]
    return wert


def _quelle_fuer_pfad(pfad: str) -> str:
    return _QUELLEN.get(_s(pfad).split(".", 1)[0], "")


def prompt(ctx: dict[str, Any]) -> list[dict[str, str]]:
    """Statischer Planner-Prompt; keine Werkzeuge und keine Ausführung."""
    regeln = {
        "schema": SCHEMA,
        "observeOnly": True,
        "intent.id": sorted(INTENTS),
        "conversation.mode": sorted(MODI),
        "conversation.next": sorted(NAECHSTE),
        "conversation.questionSlot": sorted(FRAGE_SLOTS),
        "actions.name": sorted(TOOL_NAMEN),
        "actions.gate": sorted(GATES),
        "factsUsed.source je Pfadwurzel": _QUELLEN,
        "ausgabe": {
            "intent": {"id": "…", "confidence": 0.0, "evidence": ["…"]},
            "conversation": {
                "mode": "job", "acknowledgement": "kurz",
                "next": "fragen", "questionSlot": "", "returnTask": "",
            },
            "actions": [{
                "name": "offer_slots", "arguments": {"wish": "…"},
                "bindings": {"calendarId": "…", "visitMotiveId": "…"},
                "gate": "fakten_bereit", "reason": "…",
            }],
            "factsUsed": [{"path": "sitzung.letzterNutzertext", "source": "gespraech"}],
            "uncertainties": [],
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "Du bist der Offline-Dialogplaner einer medizinischen Telefonassistenz. "
                "Du führst NICHTS aus und schreibst KEINEN Antworttext. Analysiere den "
                "TurnContext semantisch. Nutze ausschließlich vorhandene Faktenpfade. "
                "Gib exakt ein JSON-Objekt nach den REGELN zurück. Schreibwerkzeuge "
                "dürfen nur mit gate=anrufer_bestaetigt vorgeschlagen werden. "
                "Bei Unsicherheit: intent=unklar und questionSlot passend setzen.\n"
                f"REGELN={json.dumps(regeln, ensure_ascii=False, separators=(',', ':'))}"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(ctx, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _basis() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "observeOnly": True,
        "intent": {"id": "unklar", "confidence": 0.0, "evidence": []},
        "conversation": {
            "mode": "job",
            "acknowledgement": "kurz",
            "next": "fragen",
            "questionSlot": "",
            "returnTask": "",
        },
        "actions": [],
        "factsUsed": [],
        "uncertainties": [],
        "valid": False,
        "errors": [],
    }


def validieren(raw: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    """LLM-JSON normalisieren und gegen TurnContextV1 verriegeln."""
    obj = _json_aus_text(raw) if isinstance(raw, str) else raw
    plan = _basis()
    fehler: list[str] = []
    if not isinstance(obj, dict):
        plan["errors"] = ["kein_json_objekt"]
        return plan
    if ctx.get("schema") != turn_context.SCHEMA:
        plan["errors"] = ["falscher_turn_context"]
        return plan

    intent = obj.get("intent") if isinstance(obj.get("intent"), dict) else {}
    iid = _s(intent.get("id"))
    if iid not in INTENTS:
        fehler.append("intent_unbekannt")
        iid = "unklar"
    try:
        confidence = max(0.0, min(1.0, float(intent.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
        fehler.append("confidence_ungueltig")
    evidence = [_s(x)[:160] for x in (intent.get("evidence") or []) if _s(x)][:3]
    plan["intent"] = {"id": iid, "confidence": confidence, "evidence": evidence}

    conv = obj.get("conversation") if isinstance(obj.get("conversation"), dict) else {}
    mode = _s(conv.get("mode"))
    nxt = _s(conv.get("next"))
    slot = _s(conv.get("questionSlot"))
    if mode not in MODI:
        fehler.append("dialogmodus_unbekannt")
        mode = "job"
    if nxt not in NAECHSTE:
        fehler.append("naechster_schritt_unbekannt")
        nxt = "fragen"
    if slot not in FRAGE_SLOTS:
        fehler.append("frageslot_unbekannt")
        slot = ""
    plan["conversation"] = {
        "mode": mode,
        "acknowledgement": (
            _s(conv.get("acknowledgement")) if _s(conv.get("acknowledgement"))
            in {"keins", "kurz", "empathisch"} else "kurz"
        ),
        "next": nxt,
        "questionSlot": slot,
        "returnTask": _s(conv.get("returnTask"))[:80],
    }

    ids_cal = {
        _s(x.get("id")) for x in ((ctx.get("praxis") or {}).get("anbieter") or [])
        if isinstance(x, dict)
    }
    ids_motiv = {
        _s(x.get("id"))
        for x in (((ctx.get("praxis") or {}).get("katalogregeln") or {}).get("motive") or [])
        if isinstance(x, dict)
    }
    angebot = {_s(x.get("iso")) for x in (ctx.get("angebot") or []) if isinstance(x, dict)}
    actions: list[dict[str, Any]] = []
    for a in (obj.get("actions") or [])[:4]:
        if not isinstance(a, dict):
            fehler.append("aktion_ungueltig")
            continue
        name = _s(a.get("name"))
        gate = _s(a.get("gate")) or "keins"
        args = a.get("arguments") if isinstance(a.get("arguments"), dict) else {}
        bindings = a.get("bindings") if isinstance(a.get("bindings"), dict) else {}
        if name not in TOOL_NAMEN:
            fehler.append(f"werkzeug_unbekannt:{name or '-'}")
            continue
        if gate not in GATES:
            fehler.append(f"gate_unbekannt:{name}")
            continue
        if name in SCHREIB_TOOLS and gate != "anrufer_bestaetigt":
            fehler.append(f"schreibwerkzeug_ohne_bestaetigung:{name}")
            continue
        schema = TOOL_SCHEMAS.get(name) or {}
        erlaubt = set((schema.get("properties") or {}).keys())
        unbekannt = sorted(set(args.keys()) - erlaubt)
        if unbekannt:
            fehler.append(f"argument_unbekannt:{name}:{','.join(unbekannt)}")
            continue
        fehlt = [
            str(k) for k in (schema.get("required") or [])
            if _s(args.get(k)) == ""
        ]
        if fehlt:
            fehler.append(f"argument_fehlt:{name}:{','.join(fehlt)}")
            continue
        cid = _s(bindings.get("calendarId"))
        mid = _s(bindings.get("visitMotiveId"))
        iso = _s(args.get("slot_iso"))
        if cid and cid not in ids_cal:
            fehler.append(f"calendarId_nicht_im_register:{cid}")
            continue
        if mid and mid not in ids_motiv:
            fehler.append(f"motiveId_nicht_im_katalog:{mid}")
            continue
        if name == "book_slot" and (not iso or iso not in angebot):
            fehler.append("book_slot_nicht_angeboten")
            continue
        actions.append({
            "name": name,
            "arguments": args,
            "bindings": bindings,
            "gate": gate,
            "reason": _s(a.get("reason"))[:180],
            "mode": "write" if name in SCHREIB_TOOLS else "read",
        })
    plan["actions"] = actions

    facts: list[dict[str, str]] = []
    for f in (obj.get("factsUsed") or [])[:12]:
        if not isinstance(f, dict):
            continue
        pfad = _s(f.get("path"))
        quelle = _s(f.get("source"))
        soll = _quelle_fuer_pfad(pfad)
        if not soll or quelle != soll or _pfadwert(ctx, pfad) in (None, "", [], {}):
            fehler.append(f"fakt_unbelegt:{pfad or '-'}")
            continue
        facts.append({"path": pfad, "source": quelle})
    plan["factsUsed"] = facts
    plan["uncertainties"] = [
        _s(x)[:180] for x in (obj.get("uncertainties") or []) if _s(x)
    ][:6]
    plan["errors"] = fehler
    plan["valid"] = not fehler
    return plan


def planen(
    ctx: dict[str, Any],
    *,
    llm_call: Callable[[list[dict[str, str]]], Any],
) -> dict[str, Any]:
    """Expliziter Offline-Einstieg; ohne übergebenen Call gibt es keinen Lauf."""
    try:
        antwort = llm_call(prompt(ctx))
    except Exception as exc:
        plan = _basis()
        plan["errors"] = [f"planner_fehler:{type(exc).__name__}"]
        return plan
    if isinstance(antwort, dict) and "text" in antwort:
        antwort = antwort.get("text")
    return validieren(antwort, ctx)
