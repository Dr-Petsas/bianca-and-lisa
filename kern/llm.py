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
            timeout=httpx.Timeout(12.0, connect=2.0),
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


def _erster_satz_von(text: str) -> str:
    """Erster abgeschlossener Satz — '' solange keiner bestätigt ist."""
    for m in re.finditer(r"[.!?…]", text):
        i = m.end()
        if i >= len(text):
            return ""  # Satzende noch nicht bestätigt (Stream läuft)
        if i < 25 or text[i] not in " \n\t":
            continue
        if m.group() == ".":
            davor = text[: m.start()]
            wort = re.search(r"([A-Za-zÄÖÜäöüß]+)$", davor)
            if (wort and wort.group(1).lower() in _ABKUERZ) or re.search(r"\d$", davor):
                continue
        return text[:i].strip()
    return ""


def chat_stream(
    messages: list[dict],
    tools: list[dict] | None = None,
    *,
    temperature: float = 0.3,
    max_tokens: int = 90,
    erster_satz: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Wie chat(), aber per Stream: erster_satz(satz) feuert genau einmal,
    sobald der erste Satz steht UND bis dahin kein Werkzeug-Aufruf kam."""
    body = _body(messages, tools, temperature, max_tokens)
    body["stream"] = True
    text = ""
    vorab = ""
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
                    if erster_satz and not vorab and not tool_gesehen and "<think" not in text:
                        satz = _erster_satz_von(text)
                        if satz:
                            vorab = _sauber(satz)
                            try:
                                erster_satz(vorab)
                            except Exception:
                                pass
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"vllm_unreachable: {e}"}
    return {
        "ok": True,
        "text": _sauber(text),
        "tool_calls": [calls[i] for i in sorted(calls)],
        "vorab": vorab if not tool_gesehen else "",
    }
