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
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"

Transport = Callable[[str, dict[str, str], bytes], tuple[int, bytes]]


def post(url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
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
    """Return the assistant text. Every attempt appends one line to $BREACH_RUN_DIR/model_calls.jsonl."""
    model = env.get("BREACH_LLM_MODEL") or DEFAULT_MODEL
    record: dict[str, Any] = {"episode": episode, "step": step, "model": model, "purpose": purpose, "tokens_in": 0, "tokens_out": 0}
    start = time.perf_counter()
    try:
        key = env.get("BREACH_LLM_API_KEY")
        if not key:
            raise RuntimeError(
                "BREACH_LLM_API_KEY is not set: export a build.nvidia.com or Crusoe key (Ollama accepts any value)"
            )
        # Reasoning tokens count against max_tokens, so the answer keeps 2048 after a full thinking budget.
        body: dict[str, Any] = {
            "model": model, "messages": messages, "temperature": 0, "max_tokens": 2048 + (budget if thinking else 0),
        }
        if schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "rules", "schema": schema, "strict": True}}
        body["chat_template_kwargs"] = {"enable_thinking": True, "reasoning_budget": budget} if thinking else {"enable_thinking": False}
        url = (env.get("BREACH_LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        status, raw = (transport or post)(url, headers, json.dumps(body).encode())
        if status != 200:
            raise RuntimeError(f"{url} returned HTTP {status}: {raw[:500].decode(errors='replace')}")
        data = json.loads(raw)
        usage = data.get("usage") or {}
        record.update(tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0))
        return data["choices"][0]["message"]["content"] or ""
    except Exception as exc:
        record["error"] = repr(exc)
        raise
    finally:
        record["latency_ms"] = round((time.perf_counter() - start) * 1000)
        if run_dir := env.get("BREACH_RUN_DIR"):
            with (Path(run_dir) / "model_calls.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
