"""Qwen über vLLM (OpenAI-kompatibel). Kein Ollama, kein stiller Fallback."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

import httpx

from kern.config import LLM_API_KEY, LLM_BASE, LLM_MODEL

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CLIENT: httpx.Client | None = None


def _client() -> httpx.Client:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(
            base_url=LLM_BASE.rstrip("/"),
            headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
            # 20 s Lesezeit: Talk-Zuege (bis 240 Tokens) + kalter Prompt-Cache
            # liefen mit 12 s in den Timeout (Talk-Probe 27.08.2026). Der
            # Fueller ueberbrueckt Wartezeit — die Reissleine bleibt Reissleine.
            timeout=httpx.Timeout(20.0, connect=2.0),
        )
    return _CLIENT


def health(timeout: float = 2.0) -> dict[str, Any]:
    try:
        r = _client().get("/models", timeout=timeout)
        ids = []
        if r.status_code == 200:
            data = r.json()
            ids = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
        return {
            "ok": r.status_code == 200,
            "base": LLM_BASE,
            "model": LLM_MODEL,
            "models": ids,
            "status": r.status_code,
        }
    except httpx.HTTPError as e:
        return {"ok": False, "base": LLM_BASE, "model": LLM_MODEL, "error": str(e)}


def _sauber(text: str) -> str:
    return " ".join(_THINK.sub("", text or "").split()).strip()


def _body(messages: list[dict], tools: list[dict] | None, temperature: float, max_tokens: int) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
        "enable_thinking": False,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    return body


def chat(messages: list[dict], tools: list[dict] | None = None, *, temperature: float = 0.3, max_tokens: int = 90) -> dict[str, Any]:
    try:
        r = _client().post("/chat/completions", json=_body(messages, tools, temperature, max_tokens))
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"vllm_unreachable: {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"vllm_http_{r.status_code}: {r.text[:400]}"}
    data = r.json()
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    return {
        "ok": True,
        "text": _sauber(msg.get("content") or ""),
        "tool_calls": msg.get("tool_calls") or [],
    }


# --- Streaming mit Erster-Satz-Rückruf ---------------------------------------
# Latenz (Chef 27.08.2026 "speed speed speed"): Der erste fertige Satz wird
# sofort gemeldet und vertont, während das Modell den Rest noch schreibt.

_ABKUERZ = {"dr", "st", "ca", "bzw", "z", "b", "nr", "inkl", "ggf", "evtl", "usw", "min", "prof", "med"}

# Hart-Deckel (P2, 29.08.2026): Prompt sagt "höchstens zwei kurze Sätze plus
# EINE Frage", Qwen hält sich nicht immer dran. Nach dem zweiten Satz plus
# offener Frage (sonst nach drei Sätzen) schließen wir den Stream — ganze
# Sätze, nichts Abgehacktes. ~20-25 Tokens/s, jeder überflüssige Satz ~1 s.
# Notaus: LLM_SATZ_DECKEL=0.
SATZ_DECKEL = 3


def _satz_ende(text: str, start: int = 0) -> int:
    """Index HINTER dem nächsten bestätigten Satzende, sonst -1.

    Bestätigt = Satzzeichen plus Whitespace danach (Stream läuft noch, wenn
    das Satzende das letzte Zeichen ist). Abkürzungen und Ziffern-Punkte
    (13:00 / Dr.) zählen nicht."""
    for m in re.finditer(r"[.!?…]", text[start:]):
        i = start + m.end()
        if i >= len(text):
            return -1
        if text[i] not in " \n\t":
            continue
        if m.group() == ".":
            davor = text[start: start + m.start()]
            wort = re.search(r"([A-Za-zÄÖÜäöüß]+)$", davor)
            if (wort and wort.group(1).lower() in _ABKUERZ) or re.search(r"\d$", davor):
                continue
        return i
    return -1


def _saetze_bis(text: str, *, min_len: int = 0) -> list[str]:
    """Abgeschlossene Sätze — der unfertige Rest bleibt draußen."""
    out: list[str] = []
    start = 0
    while True:
        ende = _satz_ende(text, start)
        if ende < 0:
            break
        if ende - start < min_len:
            start = ende
            continue
        satz = text[start:ende].strip()
        if satz:
            out.append(satz)
        start = ende
    return out


def _erster_satz_von(text: str) -> str:
    """Erster abgeschlossener Satz — '' solange keiner bestätigt ist.

    Die 25-Zeichen-Schwelle gilt vom Textanfang: ein bloßes „Ja." allein
    ist kein Vorab (zu kurz zum Vertonen), „Ja. Das mache ich sehr gerne."
    zählt als EIN Vorab-Block, sobald der zweite Schlusspunkt bestätigt ist.
    """
    ende = 0
    while True:
        ende = _satz_ende(text, ende)
        if ende < 0:
            return ""
        if ende >= 25:
            return text[:ende].strip()


def _deckel_text(text: str) -> str:
    """Hart-Deckel: zwei Aussagen plus eine Frage, sonst drei Sätze.
    '' = noch offen (ein Satz plus Frage darf noch wachsen)."""
    saetze = _saetze_bis(text)
    if not saetze:
        return ""
    if len(saetze) >= SATZ_DECKEL:
        return " ".join(saetze[:SATZ_DECKEL])
    fragen = sum(1 for s in saetze if s.endswith("?"))
    if (len(saetze) - fragen) >= 2 and fragen >= 1:
        return " ".join(saetze)
    return ""


def _deckel_an() -> bool:
    import os
    return os.environ.get("LLM_SATZ_DECKEL", "1").strip() != "0"


def _neue_stream_saetze(text: str, n_schon: int) -> tuple[list[str], int]:
    """P5: neue abgeschlossene Sätze nach n_schon bereits gemeldeten.

    Der erste Block folgt der 25-Zeichen-Regel von _erster_satz_von
    (ein bloßes „Ja." allein ist kein Vorab — der Block darf mehrere
    Kurz-Sätze enthalten). Danach jeder weitere bestätigte Satz —
    ganze Sätze, nichts Abgehacktes (Genuschel-Lektion 28.08.2026).
    Rückgabe: (neue_bloecke, neuer_zaehler)."""
    if n_schon <= 0:
        erster = _erster_satz_von(text)
        if not erster:
            return [], 0
        return [erster], max(1, len(_saetze_bis(erster)))
    alle = _saetze_bis(text)
    neu = alle[n_schon:]
    return neu, n_schon + len(neu)


def _satz_stream_an() -> bool:
    import os
    return os.environ.get("LLM_SATZ_STREAM", "1").strip() != "0"


def chat_stream(
    messages: list[dict],
    tools: list[dict] | None = None,
    *,
    temperature: float = 0.3,
    max_tokens: int = 90,
    erster_satz: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Wie chat(), aber per Stream: erster_satz(satz) feuert je fertigem
    Satz (P5, 29.08.2026 — satzweises LLM→TTS), sobald kein Werkzeug-
    Aufruf kam. Der erste Block hält die alte 25-Zeichen-Regel; weitere
    Sätze folgen, sobald sie bestätigt sind. Notaus LLM_SATZ_STREAM=0
    => nur der erste Satz wie vor P5."""
    body = _body(messages, tools, temperature, max_tokens)
    body["stream"] = True
    text = ""
    vorab = ""
    n_saetze = 0
    calls: dict[int, dict] = {}
    tool_gesehen = False
    try:
        with _client().stream("POST", "/chat/completions", json=body) as r:
            if r.status_code != 200:
                fehler = r.read().decode("utf-8", "ignore")[:400]
                return {"ok": False, "error": f"vllm_http_{r.status_code}: {fehler}"}
            for roh in r.iter_lines():
                zeile = (roh or "").strip()
                if not zeile.startswith("data:"):
                    continue
                daten = zeile[5:].strip()
                if daten == "[DONE]":
                    break
                try:
                    obj = json.loads(daten)
                except ValueError:
                    continue
                delta = ((obj.get("choices") or [{}])[0].get("delta")) or {}
                for tc in delta.get("tool_calls") or []:
                    tool_gesehen = True
                    idx = int(tc.get("index") or 0)
                    ein = calls.setdefault(idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    if tc.get("id"):
                        ein["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        ein["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        ein["function"]["arguments"] += fn["arguments"]
                stueck = delta.get("content")
                if stueck:
                    text += stueck
                    if erster_satz and not tool_gesehen and "<think" not in text:
                        # P5: jeden fertigen Satz sofort an die Stimme —
                        # Satz 2 spricht, während Satz 3 noch generiert.
                        # Notaus LLM_SATZ_STREAM=0: nur der erste Block.
                        neu, n_neu = _neue_stream_saetze(text, n_saetze)
                        if neu and not _satz_stream_an() and n_saetze > 0:
                            neu = []
                        elif neu:
                            n_saetze = n_neu
                            if not _satz_stream_an():
                                neu = neu[:1]
                            for satz in neu:
                                sauber = _sauber(satz)
                                if not sauber:
                                    continue
                                vorab = (vorab + " " + sauber).strip() if vorab else sauber
                                try:
                                    erster_satz(sauber)
                                except Exception:
                                    pass
                    # P2 Satz-Deckel: sobald zwei Sätze plus Frage (sonst
                    # drei Sätze) stehen, den Stream schließen — der Rest
                    # würde nur Tokens und ~1 s je Satz kosten. Werkzeug-
                    # Züge bleiben unangetastet (Argumente laufen weiter).
                    if (_deckel_an() and not tool_gesehen
                            and "<think" not in text):
                        gedeckelt = _deckel_text(text)
                        if gedeckelt:
                            text = gedeckelt
                            print(f"llm-deckel: {len(_saetze_bis(text))} Saetze",
                                  flush=True)
                            break
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"vllm_unreachable: {e}"}
    return {
        "ok": True,
        "text": _sauber(text),
        "tool_calls": [calls[i] for i in sorted(calls)],
        "vorab": vorab if not tool_gesehen else "",
    }
