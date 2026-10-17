import json
import unittest

from breach.rmalde import JEV_URL, relay

CRUSOE = {"BREACH_LLM_BASE_URL": "https://api.inference.crusoecloud.com/v1", "BREACH_LLM_API_KEY": "test-key"}
# The bodies models.mjs sends: plan() to the chat completions path, decide() to the decisions path.
PLAN = {
    "model": "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B",
    "messages": [{"role": "system", "content": "You are the high-level planner."}, {"role": "user", "content": "{}"}],
    "reasoning": {"effort": "low"}, "max_tokens": 1800, "response_format": {"type": "json_object"},
}
DECIDE = {"model": "typesafe/jev-1.13", "state": "{}",
          "questions": {"action": {"type": "choice", "instructions": "Control the Minecraft player.", "criteria": {"a0": "Wait"}}}}
PLANNED = {"choices": [{"message": {"content": '{"objective": "Collect logs"}'}}], "usage": {"prompt_tokens": 9, "completion_tokens": 3}}
CHOSEN = {"answers": {"action": {"choice": "a0"}}}


def fake(sent, *answers):
    """Transport that records each request and answers with the next (status, reply)."""
    replies = iter(answers)

    def transport(url, headers, body):
        sent.append((url, headers, json.loads(body)))
        status, reply = next(replies)
        return status, json.dumps(reply).encode()

    return transport


class RelayTests(unittest.TestCase):
    def test_sends_the_planner_to_nemotron_with_thinking_off(self):
        sent = []
        status, reply = relay("/api/v1/chat/completions", PLAN, CRUSOE, fake(sent, (200, PLANNED)))
        body = {k: v for k, v in PLAN.items() if k != "reasoning"} | {"chat_template_kwargs": {"enable_thinking": False}}
        headers = {"Content-Type": "application/json", "Authorization": "Bearer test-key"}
        self.assertEqual(
            (status, reply["data"], sent),
            (200, PLANNED, [("https://api.inference.crusoecloud.com/v1/chat/completions", headers, body)]),
        )

    def test_asks_again_without_a_rejected_response_format(self):
        sent = []
        status, _ = relay("/api/v1/chat/completions", PLAN, CRUSOE, fake(sent, (400, {"detail": "response_format"}), (200, PLANNED)))
        self.assertEqual((status, ["response_format" in body for *_, body in sent]), (200, [True, False]))

    def test_passes_jev_decisions_to_openrouter_only_with_a_key(self):
        sent = []
        refused, _ = relay("/api/alpha/decisions", DECIDE, CRUSOE, fake(sent))
        status, reply = relay("/api/alpha/decisions", DECIDE, CRUSOE | {"JEV_API_KEY": "jev-key"}, fake(sent, (200, CHOSEN)))
        headers = {"Content-Type": "application/json", "Authorization": "Bearer jev-key"}
        self.assertEqual((refused, status, reply["data"], sent), (502, 200, CHOSEN, [(JEV_URL, headers, DECIDE)]))


if __name__ == "__main__":
    unittest.main()
