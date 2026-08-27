"""Qwen über vLLM (OpenAI-kompatibel). Kein Ollama, kein stiller Fallback."""

from __future__ import annotations

import re
from typing import Any

import httpx

from lisa.config import LLM_API_KEY, LLM_BASE, LLM_MODEL

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


def chat(messages: list[dict], tools: list[dict] | None = None, *, temperature: float = 0.3, max_tokens: int = 90) -> dict[str, Any]:
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
    try:
        r = _client().post("/chat/completions", json=body)
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
