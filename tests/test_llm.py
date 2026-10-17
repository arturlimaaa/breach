import json
import tempfile
import unittest
from pathlib import Path

from breach.llm import complete

MESSAGES = [{"role": "user", "content": "Which item does a log craft into?"}]
KEY = {"BREACH_LLM_API_KEY": "test-key"}


def fake(sent, status=200, reply=None):
    """Transport that records each request and answers with `reply` as JSON."""

    def post(url, headers, body):
        sent.append((url, headers, json.loads(body)))
        return status, json.dumps(reply or {"choices": [{"message": {"content": "planks"}}]}).encode()

    return post


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
                    "model": "nvidia/nemotron-3-super-120b-a12b",
                    "messages": MESSAGES,
                    "temperature": 0,
                    "max_tokens": 2048,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )],
        )

    def test_schema_and_thinking_add_response_format_and_reasoning_budget(self):
        sent = []
        env = {**KEY, "BREACH_LLM_BASE_URL": "http://127.0.0.1:11434/v1/", "BREACH_LLM_MODEL": "nemotron-3-nano:4b"}
        complete(
            MESSAGES, schema={"type": "array"}, thinking=True, budget=1024,
            transport=fake(sent), env=env, episode="hc", step=7, purpose="induce",
        )
        url, _, body = sent[0]
        self.assertEqual(
            (url, body),
            (
                "http://127.0.0.1:11434/v1/chat/completions",
                {
                    "model": "nemotron-3-nano:4b",
                    "messages": MESSAGES,
                    "temperature": 0,
                    "max_tokens": 2048 + 1024,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "rules", "schema": {"type": "array"}, "strict": True},
                    },
                    "chat_template_kwargs": {"enable_thinking": True, "reasoning_budget": 1024},
                },
            ),
        )

    def test_each_call_appends_its_usage_to_model_calls_jsonl(self):
        reply = {"choices": [{"message": {"content": "planks"}}], "usage": {"prompt_tokens": 12, "completion_tokens": 3}}
        with tempfile.TemporaryDirectory() as run_dir:
            text = complete(
                MESSAGES, transport=fake([], reply=reply), env={**KEY, "BREACH_RUN_DIR": run_dir},
                episode="t1", step=3, purpose="plan",
            )
            record = json.loads((Path(run_dir) / "model_calls.jsonl").read_text(encoding="utf-8"))
        latency = record.pop("latency_ms")
        self.assertEqual(
            (text, record, type(latency)),
            (
                "planks",
                {
                    "episode": "t1", "step": 3, "model": "nvidia/nemotron-3-super-120b-a12b",
                    "purpose": "plan", "tokens_in": 12, "tokens_out": 3,
                },
                int,
            ),
        )

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
        def post(url, headers, body):
            raise AssertionError("transport called without a key")

        with self.assertRaisesRegex(RuntimeError, "BREACH_LLM_API_KEY"):
            complete(MESSAGES, transport=post, env={}, episode="t1", step=3, purpose="plan")


if __name__ == "__main__":
    unittest.main()
