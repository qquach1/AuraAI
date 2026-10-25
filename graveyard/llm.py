"""Thin wrapper over the Anthropic SDK for agents that need structured JSON back.

Every call is logged with token counts and an estimated cost so the team can quote a
cost per report. When no API key is set (or GS_OFFLINE=1) `structured` returns None and
agents use their rule-based fallback.
"""

import json
import re
import time

import anthropic

from . import config

# USD per million tokens for claude-opus-5-5; web search is billed per search
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ = 4.00, 20.00, 0.20
PRICE_WEB_SEARCH = 0.01

_client = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=180.0, max_retries=3)
    return _client


class Usage:
    def __init__(self):
        self.calls: list[dict] = []

    def add(self, agent: str, resp, seconds: float):
        u = resp.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        searches = getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0
        cost = (u.input_tokens * PRICE_IN + u.output_tokens * PRICE_OUT + cache_read * PRICE_CACHE_READ) / 1e6
        cost += searches * PRICE_WEB_SEARCH
        self.calls.append({
            "agent": agent, "model": resp.model, "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens, "cache_read_tokens": cache_read,
            "cost_usd": round(cost, 5), "seconds": round(seconds, 1),
        })

    @property
    def total_cost(self) -> float:
        return round(sum(c["cost_usd"] for c in self.calls), 4)


def structured(agent: str, system: str, user: str, schema: dict, usage: Usage | None = None,
               effort: str = "medium", max_tokens: int = 16000) -> dict | None:
    """One Claude call constrained to a JSON schema. Returns the parsed object or None."""
    if not config.llm_available():
        return None
    t0 = time.monotonic()
    try:
        resp = client().beta.messages.create(
            model=config.MODEL,
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
        print(f"[llm] {agent} call failed: {type(e).__name__}: {e}")
        return None
    if usage is not None:
        usage.add(agent, resp, time.monotonic() - t0)
    if resp.stop_reason in ("refusal", "max_tokens"):
        print(f"[llm] {agent} stopped: {resp.stop_reason}")
        return None
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"[llm] {agent} returned invalid JSON")
        return None


def web_research(agent: str, system: str, user: str, usage: Usage | None = None, max_uses: int = 5,
                 effort: str = "low") -> str | None:
    """One Claude turn with the server-side web search tool. Returns the final text, or None."""
    if not config.llm_available():
        return None
    messages = [{"role": "user", "content": user}]
    text_parts = []
    for _ in range(3):  # resume if the server pauses a long search turn
        t0 = time.monotonic()
        try:
            resp = client().beta.messages.create(
                model=config.MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system,
                messages=messages,
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}],
                output_config={"effort": effort},
            )
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            print(f"[llm] {agent} web search failed: {type(e).__name__}: {e}")
            return None
        if usage is not None:
            usage.add(agent, resp, time.monotonic() - t0)
        text_parts += [b.text for b in resp.content if b.type == "text"]
        if resp.stop_reason != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": resp.content}]
    if resp.stop_reason == "refusal":
        return None
    return "".join(text_parts) or None


def extract_json(text: str | None) -> dict | None:
    """Last JSON object in a free-text answer (```json fenced or bare)."""
    if not text:
        return None
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S) or re.findall(r"(\{.*\})", text, re.S)
    for b in reversed(blocks):
        try:
            return json.loads(b)
        except json.JSONDecodeError:
            continue
    return None


def obj(props: dict, required: list[str] | None = None) -> dict:
    """JSON-schema object helper: all properties required, no extras (structured output rules)."""
    return {"type": "object", "properties": props, "required": required or list(props),
            "additionalProperties": False}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


STR = {"type": "string"}
CONF = {"type": "string", "enum": ["high", "medium", "low"]}
