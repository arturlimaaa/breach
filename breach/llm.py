"""OpenAI-compatible chat completions: build.nvidia.com by default, Crusoe or Ollama through BREACH_LLM_BASE_URL."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
_OLLAMA = {"model": "nemotron-3-nano:4b", "key": False, "thinking": "reasoning_effort"}
# What differs per endpoint. An unknown base URL is treated like NVIDIA's.
PROVIDERS: dict[str, dict[str, Any]] = {
    DEFAULT_BASE_URL: {"model": "nvidia/nemotron-3-super-120b-a12b", "key": True, "thinking": "chat_template_kwargs"},
    # Crusoe's docs and ai-sdk.dev disagree on this id: confirm it with list_models() before a run.
    "https://api.inference.crusoecloud.com/v1": {"model": "nvidia/Nemotron-3-Super-120B-A12B", "key": True, "thinking": "chat_template_kwargs"},
    "http://127.0.0.1:11434/v1": _OLLAMA,
    "http://localhost:11434/v1": _OLLAMA,
}

Transport = Callable[[str, dict[str, str], bytes | None], tuple[int, bytes]]


def send(url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
    """POST `body`, or GET when it is None. An HTTP error comes back as its status and body."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def complete(
    messages: list[dict[str, str]],
    *,
    episode: str,
    step: int,
    purpose: str,
    schema: dict[str, Any] | None = None,
    thinking: bool = False,
    budget: int = 2048,
    transport: Transport | None = None,
    env: Mapping[str, str] = os.environ,
) -> str:
    """Return the assistant text. Every call appends one line to $BREACH_RUN_DIR/model_calls.jsonl."""
    base, provider = _provider(env)
    model = env.get("BREACH_LLM_MODEL") or provider["model"]
    record: dict[str, Any] = {"episode": episode, "step": step, "model": model, "purpose": purpose, "tokens_in": 0, "tokens_out": 0}
    start = time.perf_counter()
    try:
        headers = _headers(provider, env)
        # NVIDIA documents temperature in (0, 1] and recommends 1.0 with top_p 0.95 for Super.
        # Reasoning tokens likely count against max_tokens, so the answer keeps 4096 after a full budget.
        body: dict[str, Any] = {
            "model": model, "messages": messages, "stream": False, "temperature": 1.0, "top_p": 0.95, "seed": 42,
            "max_tokens": 4096 + (budget if thinking else 0),
        }
        if provider["thinking"] == "reasoning_effort":
            body["reasoning_effort"] = "high" if thinking else "none"
        else:
            body["chat_template_kwargs"] = {"enable_thinking": thinking}
            if thinking:
                body["reasoning_budget"] = budget
        if schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "rules", "schema": schema, "strict": True}}
        url = f"{base}/chat/completions"
        status, raw = (transport or send)(url, headers, json.dumps(body).encode())
        if status in (400, 422) and schema is not None:
            # NVIDIA's hosted request schema omits response_format; callers parse the reply text either way.
            record["schema_rejected"] = _excerpt(status, raw)
            del body["response_format"]
            status, raw = (transport or send)(url, headers, json.dumps(body).encode())
        if status != 200:
            raise RuntimeError(f"{url} returned {_excerpt(status, raw)}")
        data = json.loads(raw)
        message = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        text = message.get("content") or ""
        record.update(
            tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0),
            reply=text, reasoning=message.get("reasoning_content") or message.get("reasoning"),
        )
        return text
    except Exception as exc:
        record["error"] = repr(exc)
        raise
    finally:
        record["latency_ms"] = round((time.perf_counter() - start) * 1000)
        if run_dir := env.get("BREACH_RUN_DIR"):
            with (Path(run_dir) / "model_calls.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")


def list_models(*, transport: Transport | None = None, env: Mapping[str, str] = os.environ) -> list[str]:
    """Model ids served at BREACH_LLM_BASE_URL, to check BREACH_LLM_MODEL before a run."""
    base, provider = _provider(env)
    status, raw = (transport or send)(f"{base}/models", _headers(provider, env), None)
    if status != 200:
        raise RuntimeError(f"{base}/models returned {_excerpt(status, raw)}")
    return sorted(entry["id"] for entry in json.loads(raw)["data"])


def _provider(env: Mapping[str, str]) -> tuple[str, dict[str, Any]]:
    base = (env.get("BREACH_LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    return base, PROVIDERS.get(base, PROVIDERS[DEFAULT_BASE_URL])


def _headers(provider: dict[str, Any], env: Mapping[str, str]) -> dict[str, str]:
    key = env.get("BREACH_LLM_API_KEY")
    if provider["key"] and not key:
        raise RuntimeError("BREACH_LLM_API_KEY is not set: export a build.nvidia.com or Crusoe key (Ollama needs none)")
    return {"Content-Type": "application/json"} | ({"Authorization": f"Bearer {key}"} if key else {})


def _excerpt(status: int, raw: bytes) -> str:
    return f"HTTP {status}: {raw[:500].decode(errors='replace')}"
