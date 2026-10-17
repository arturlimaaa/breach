import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from breach.export import export
from tests.test_proof import ROOT, step, write_run

NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
PROMPT = [{"role": "user", "content": "Server grid/stick-count-2 contradicted a rule the agent had certified."}]
PLANKS = {"log": -1, "planks": 4}
STICK, STICK_2 = {"planks": -2, "stick": 4}, {"planks": -2, "stick": 2}
TORCH, TORCH_2 = {"coal": -1, "stick": -1, "torch": 4}, {"coal": -1, "stick": -1, "torch": 2}
LADDER, LADDER_2 = {"stick": -7, "ladder": 3}, {"stick": -7, "ladder": 2}
REPLY = '[{"action": "craft", "target": "stick", "delta": {"planks": -2, "stick": 2}}]'


def call(episode, at, purpose="induce", **extra):
    return {
        "episode": episode, "step": at, "model": NANO, "purpose": purpose, "messages": PROMPT,
        "tokens_in": 900, "tokens_out": 120, "latency_ms": 2100, "reply": REPLY, "reasoning": None, **extra,
    }


def failed(episode, at):
    """A call the endpoint refused, which llm.complete logs with its error and no reply."""
    record = call(episode, at, error="RuntimeError('HTTP 429: rate limited')")
    del record["reply"], record["reasoning"]
    return record


def episode(episode_id, server):
    return {"id": episode_id, "server": server}


def rewards(records):
    return [(r["episode"], r["step"], r["reward"], r["candidate"]) for r in records]


# The count change: the refuting craft itself confirms the revision, which is then used as a test step.
COUNT_HC = episode("stick-count-2-hc-s1", "grid/stick-count-2")
COUNT_LOGS = {COUNT_HC["id"]: [
    step("craft", "planks", "craft:planks", PLANKS, PLANKS, "match"),
    step("craft", "stick", "craft:stick", STICK, STICK_2, "mismatch"),
    step("craft", "planks", "craft:planks", PLANKS, PLANKS, "match"),
    step("craft", "stick", "craft:stick@grid/stick-count-2", STICK_2, STICK_2, "match", test=True),
]}

# An unusable reply, its retry, then a second round, all asked about the same refuting mine.
DROP_HC = episode("stone-drop-nothing-hc-s1", "grid/stone-drop-nothing")
DROP_LOGS = {DROP_HC["id"]: [
    step("mine", "stone", "mine:stone", {"cobblestone": 1}, {}, "mismatch"),
    step("move", "east", None, {}, {}, "match"),
    step("mine", "stone", "mine:stone@grid/stone-drop-nothing", {}, {}, "match", test=True),
]}
DROP_CALLS = [call(DROP_HC["id"], 1, reply="no idea"), call(DROP_HC["id"], 1), call(DROP_HC["id"], 1)]


class ExportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_a_recovered_count_change_exports_its_prompt_reply_and_the_revision_that_passed(self):
        run = write_run(self.tmp / "run", "D", [COUNT_HC], COUNT_LOGS, [call(COUNT_HC["id"], 2, reasoning="Two sticks came out.")])
        self.assertEqual(
            export(run),
            [{
                "responses_create_params": {"input": PROMPT},
                "response": {
                    "id": "stick-count-2-hc-s1-0", "created_at": 0.0, "model": NANO, "object": "response",
                    "output": [
                        {"id": "rs_0", "type": "reasoning", "summary": [{"type": "summary_text", "text": "Two sticks came out."}]},
                        {
                            "id": "msg_0", "type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": REPLY, "annotations": []}],
                        },
                    ],
                    "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
                },
                "reward": 1.0, "candidate": "craft:stick@grid/stick-count-2", "episode": "stick-count-2-hc-s1", "step": 2,
            }],
        )

    def test_only_the_last_call_about_a_refuting_step_is_credited(self):
        run = write_run(self.tmp / "run", "D", [DROP_HC], DROP_LOGS, DROP_CALLS)
        self.assertEqual(
            rewards(export(run)),
            [
                (DROP_HC["id"], 1, 0.0, None), (DROP_HC["id"], 1, 0.0, None),
                (DROP_HC["id"], 1, 1.0, "mine:stone@grid/stone-drop-nothing"),
            ],
        )

    def test_a_revision_that_first_passes_in_the_next_episode_on_the_server_is_credited(self):
        hc, hs = episode("torch-count-2-hc-s1", "grid/torch-count-2"), episode("torch-count-2-hs-s1", "grid/torch-count-2")
        logs = {
            hc["id"]: [step("craft", "torch", "craft:torch", TORCH, TORCH_2, "mismatch")],
            hs["id"]: [
                step("move", "east", None, {}, {}, "match"),
                step("probe", "torch", "craft:torch@grid/torch-count-2", {"torch": 2}, {"torch": 2}, "match", test=True),
            ],
        }
        run = write_run(self.tmp / "run", "D", [hc, hs], logs, [call(hc["id"], 1)])
        self.assertEqual(rewards(export(run)), [(hc["id"], 1, 1.0, "craft:torch@grid/torch-count-2")])

    def test_a_later_call_on_the_server_closes_the_window_of_the_one_before(self):
        hc, hs = episode("ladder-count-2-hc-s1", "grid/ladder-count-2"), episode("ladder-count-2-hs-s1", "grid/ladder-count-2")
        logs = {
            hc["id"]: [step("craft", "ladder", "craft:ladder", LADDER, LADDER_2, "mismatch")],
            hs["id"]: [
                step("craft", "ladder", "craft:ladder@grid/ladder-count-2#1", {"stick": -7, "ladder": 1}, LADDER_2, "mismatch", test=True),
                step("probe", "ladder", "craft:ladder@grid/ladder-count-2#2", {"ladder": 2}, {"ladder": 2}, "match", test=True),
            ],
        }
        run = write_run(self.tmp / "run", "D", [hc, hs], logs, [call(hc["id"], 1), call(hs["id"], 1)])
        self.assertEqual(
            rewards(export(run)),
            [(hc["id"], 1, 0.0, None), (hs["id"], 1, 1.0, "craft:ladder@grid/ladder-count-2#2")],
        )

    def test_a_failed_step_under_an_empty_revision_passes_nothing(self):
        logs = {DROP_HC["id"]: [
            *DROP_LOGS[DROP_HC["id"]][:2],
            step("mine", "stone", "mine:stone@grid/stone-drop-nothing", {}, {}, "match", test=True, ok=False),
        ]}
        run = write_run(self.tmp / "run", "D", [DROP_HC], logs, [call(DROP_HC["id"], 1)])
        self.assertEqual(rewards(export(run)), [(DROP_HC["id"], 1, 0.0, None)])

    def test_a_failed_call_is_kept_as_a_masked_sample_that_no_later_revision_credits(self):
        run = write_run(self.tmp / "run", "D", [COUNT_HC], COUNT_LOGS, [failed(COUNT_HC["id"], 2)])
        self.assertEqual(
            export(run),
            [{
                "responses_create_params": {"input": PROMPT},
                "response": {
                    "id": "stick-count-2-hc-s1-0", "created_at": 0.0, "model": NANO, "object": "response", "output": [],
                    "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
                },
                "reward": 0.0, "candidate": None, "episode": "stick-count-2-hc-s1", "step": 2,
                "mask_sample": True, "failure_reason": "RuntimeError('HTTP 429: rate limited')",
            }],
        )

    def test_a_run_tree_gives_one_record_per_induction_call_and_none_for_plan_calls(self):
        write_run(self.tmp / "tree" / "A", "A", [COUNT_HC], COUNT_LOGS, [call(COUNT_HC["id"], 0, purpose="plan")])
        write_run(self.tmp / "tree" / "D" / "stick-count-2-s1", "D", [COUNT_HC], COUNT_LOGS, [call(COUNT_HC["id"], 2)])
        write_run(self.tmp / "tree" / "D" / "stone-drop-nothing-s1", "D", [DROP_HC], DROP_LOGS, DROP_CALLS)
        self.assertEqual(len(export(self.tmp / "tree")), 1 + len(DROP_CALLS))

    def test_a_run_an_inducer_error_stopped_still_exports_the_episode_in_progress(self):
        """run_jobs lists an episode only once it ends, so the error leaves it out of the manifest, or leaves no manifest."""
        hc, hs = episode("ladder-count-2-hc-s1", "grid/ladder-count-2"), episode("ladder-count-2-hs-s1", "grid/ladder-count-2")
        logs = {
            hc["id"]: [step("craft", "ladder", "craft:ladder", LADDER, LADDER_2, "mismatch")],
            hs["id"]: [step("craft", "ladder", "craft:ladder@grid/ladder-count-2#1", {"stick": -7, "ladder": 1}, LADDER_2, "mismatch", test=True)],
        }
        ladder = write_run(self.tmp / "tree" / "D" / "ladder-count-2-s1", "D", [hc, hs], logs, [call(hc["id"], 1), failed(hs["id"], 1)])
        (ladder / "manifest.json").write_text(json.dumps({"system": "D", "episodes": [hc]}))
        stone_logs = {DROP_HC["id"]: DROP_LOGS[DROP_HC["id"]][:1]}
        stone = write_run(self.tmp / "tree" / "D" / "stone-drop-nothing-s1", "D", [DROP_HC], stone_logs, [DROP_CALLS[0], failed(DROP_HC["id"], 1)])
        (stone / "manifest.json").unlink()
        self.assertEqual(
            [(r["episode"], r["step"], r["reward"], r.get("mask_sample", False)) for r in export(self.tmp / "tree")],
            [(hc["id"], 1, 0.0, False), (hs["id"], 1, 0.0, True), (DROP_HC["id"], 1, 0.0, False), (DROP_HC["id"], 1, 0.0, True)],
        )

    def test_a_call_logged_without_its_prompt_is_refused(self):
        old = call(COUNT_HC["id"], 2)
        del old["messages"]
        run = write_run(self.tmp / "run", "D", [COUNT_HC], COUNT_LOGS, [old])
        with self.assertRaisesRegex(ValueError, "stick-count-2-hc-s1/2 has no messages"):
            export(run)

    def test_cli_writes_one_json_line_per_record(self):
        run = write_run(self.tmp / "run", "D", [DROP_HC], DROP_LOGS, DROP_CALLS)
        out = self.tmp / "induction.jsonl"
        result = subprocess.run([sys.executable, "-m", "breach.export", str(run), str(out)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(
            (result.returncode, result.stdout, [json.loads(line) for line in out.read_text().splitlines()]),
            (0, f"3 induction calls, 1 with a revision that passed, written to {out}\n", export(run)),
        )


if __name__ == "__main__":
    unittest.main()
