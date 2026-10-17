import json
import tempfile
import unittest
from pathlib import Path

from breach.llm import complete, list_models

MESSAGES = [{"role": "user", "content": "Which item does a log craft into?"}]
KEY = {"BREACH_LLM_API_KEY": "test-key"}
CRUSOE = {"BREACH_LLM_BASE_URL": "https://api.inference.crusoecloud.com/v1"}
OLLAMA = {"BREACH_LLM_BASE_URL": "http://localhost:11434/v1"}
SAMPLING = {"stream": False, "top_p": 0.95, "seed": 42}


def fake(sent, status=200, reply=None):
    """Transport that records each request and answers with `reply` as JSON."""

    def transport(url, headers, body):
        sent.append((url, headers, json.loads(body)))
        return status, json.dumps(reply or {"choices": [{"message": {"content": "planks"}}]}).encode()

    return transport


def logged(reply, **env):
    """One call against a fake answering `reply`: the returned text and its model_calls.jsonl record."""
    with tempfile.TemporaryDirectory() as run_dir:
        text = complete(
            MESSAGES, transport=fake([], reply=reply), env={**KEY, **env, "BREACH_RUN_DIR": run_dir},
            episode="t1", step=3, purpose="plan",
        )
        record = json.loads((Path(run_dir) / "model_calls.jsonl").read_text(encoding="utf-8"))
    return text, record


class CompleteTests(unittest.TestCase):
    def test_defaults_post_to_build_nvidia_with_thinking_off(self):
        sent = []
        complete(MESSAGES, transport=fake(sent), env=KEY, episode="t1", step=3, purpose="plan")
        self.assertEqual(
            sent,
            [(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                {"Authorization": "Bearer test-key", "Content-Type": "application/json"},
                {
                    "model": "nvidia/nemotron-3-super-120b-a12b", "messages": MESSAGES, **SAMPLING, "temperature": 0.95,
                    "max_tokens": 4096, "chat_template_kwargs": {"enable_thinking": False},
                },
            )],
        )

    def test_crusoe_gets_its_model_id_and_nvidia_style_thinking(self):
        sent = []
        complete(MESSAGES, transport=fake(sent), env={**KEY, **CRUSOE}, episode="t1", step=3, purpose="plan")
        url, headers, body = sent[0]
        self.assertEqual(
            (url, headers["Authorization"], body["model"], body["chat_template_kwargs"]),
            (
                "https://api.inference.crusoecloud.com/v1/chat/completions", "Bearer test-key",
                "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B", {"enable_thinking": False},
            ),
        )

    def test_thinking_on_nvidia_sends_a_top_level_budget_beside_the_schema(self):
        sent = []
        complete(
            MESSAGES, schema={"type": "array"}, thinking=True, budget=1024,
            transport=fake(sent), env=KEY, episode="hc", step=7, purpose="induce",
        )
        self.assertEqual(
            sent[0][2],
            {
                "model": "nvidia/nemotron-3-super-120b-a12b", "messages": MESSAGES, **SAMPLING, "temperature": 1.0,
                "max_tokens": 4096 + 1024,
                "chat_template_kwargs": {"enable_thinking": True},
                "reasoning_budget": 1024,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "rules", "schema": {"type": "array"}, "strict": True},
                },
            },
        )

    def test_ollama_needs_no_key_and_switches_thinking_by_reasoning_effort(self):
        sent = []
        for thinking in (False, True):
            complete(MESSAGES, thinking=thinking, transport=fake(sent), env=OLLAMA, episode="t1", step=3, purpose="plan")
        (url, headers, off), (_, _, on) = sent
        self.assertEqual(
            (url, headers, off, on["reasoning_effort"]),
            (
                "http://localhost:11434/v1/chat/completions",
                {"Content-Type": "application/json"},
                {
                    "model": "nemotron-3-nano:4b", "messages": MESSAGES, **SAMPLING, "temperature": 0.95,
                    "max_tokens": 4096, "reasoning_effort": "none",
                },
                "high",
            ),
        )

    def test_a_rejected_response_format_is_dropped_and_the_call_retried_once(self):
        bodies = []

        def transport(url, headers, body):
            bodies.append(json.loads(body))
            if "response_format" in bodies[-1]:
                return 400, b'{"detail": "Extra inputs are not permitted"}'
            return 200, json.dumps({"choices": [{"message": {"content": "[]"}}]}).encode()

        text = complete(MESSAGES, schema={"type": "array"}, transport=transport, env=KEY, episode="hc", step=7, purpose="induce")
        self.assertEqual((text, ["response_format" in body for body in bodies]), ("[]", [True, False]))

    def test_each_call_logs_its_usage_reply_and_reasoning(self):
        message = {"content": "planks", "reasoning_content": "A log crafts into four planks."}
        text, record = logged({"choices": [{"message": message}], "usage": {"prompt_tokens": 12, "completion_tokens": 3}})
        latency = record.pop("latency_ms")
        self.assertEqual(
            (text, record, type(latency)),
            (
                "planks",
                {
                    "episode": "t1", "step": 3, "model": "nvidia/nemotron-3-super-120b-a12b", "purpose": "plan",
                    "tokens_in": 12, "tokens_out": 3, "reply": "planks", "reasoning": "A log crafts into four planks.",
                },
                int,
            ),
        )

    def test_ollama_reasoning_field_is_logged_as_reasoning(self):
        _, record = logged({"choices": [{"message": {"content": "planks", "reasoning": "Logs make planks."}}]}, **OLLAMA)
        self.assertEqual(record["reasoning"], "Logs make planks.")

    def test_a_failed_call_is_logged_with_zero_tokens_and_its_error(self):
        with tempfile.TemporaryDirectory() as run_dir:
            with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                complete(
                    MESSAGES, transport=fake([], status=401, reply={"detail": "Authentication failed"}),
                    env={**KEY, "BREACH_RUN_DIR": run_dir}, episode="t1", step=3, purpose="plan",
                )
            record = json.loads((Path(run_dir) / "model_calls.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(
            (record["tokens_in"], record["tokens_out"], "Authentication failed" in record["error"]),
            (0, 0, True),
        )

    def test_missing_key_raises_before_any_request(self):
        def transport(url, headers, body):
            raise AssertionError("transport called without a key")

        with self.assertRaisesRegex(RuntimeError, "BREACH_LLM_API_KEY.*api.inference.crusoecloud.com"):
            complete(MESSAGES, transport=transport, env={}, episode="t1", step=3, purpose="plan")


class ListModelsTests(unittest.TestCase):
    def test_lists_the_model_ids_the_endpoint_serves(self):
        sent = []

        def transport(url, headers, body):
            sent.append((url, body))
            return 200, json.dumps({"object": "list", "data": [{"id": "nvidia/b"}, {"id": "nvidia/a"}]}).encode()

        self.assertEqual(
            (list_models(transport=transport, env=KEY), sent),
            (["nvidia/a", "nvidia/b"], [("https://integrate.api.nvidia.com/v1/models", None)]),
        )


if __name__ == "__main__":
    unittest.main()
