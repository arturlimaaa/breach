import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from breach.convert_rmalde import convert
from breach.log import Transition
from breach.proof import proof, read_log
from breach.tasks import T1
from breach.world import Task

ROOT = Path(__file__).resolve().parents[1]
# agent.mjs's events for T1 on a server where wooden_pickaxe also needs coal; written from its log() calls.
EVENTS = ROOT / "tests" / "golden" / "rmalde-events.jsonl"
CHANGE = "wooden_pickaxe-add-coal"
SERVER = "mc/127.0.0.1:25565/world"
PICKAXE = {"planks": -3, "stick": -2, "wooden_pickaxe": 1}


class ConvertTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name) / "run"

    def entry(self, task):
        convert(EVENTS, self.run_dir, task, CHANGE)
        [entry] = json.loads((self.run_dir / "manifest.json").read_text(encoding="utf-8"))["episodes"]
        return entry, read_log(self.run_dir / f"{task.task_id}.jsonl")

    def test_the_proof_reads_the_converted_run(self):
        subprocess.run(
            [sys.executable, "-m", "breach.convert_rmalde", EVENTS, self.run_dir, "--task", "T1", "--change", CHANGE],
            cwd=ROOT, check=True, capture_output=True,
        )
        self.assertEqual(proof(self.run_dir)["episodes"], [{
            "id": "t1", "task": "t1", "server": SERVER, "change": CHANGE, "seed": None, "goal": "wooden_pickaxe",
            "count": 1, "inventory": {}, "success": False, "actions": 14, "reason": "development_trial_ended",
            "system": "B", "contradictions": 2, "actions_after_contradiction": 1, "immediate_repeat": 1,
            "recovery_latency": None, "text_model_calls": 2, "tokens": 3216,
        }])

    def test_the_log_has_one_transition_per_action_and_none_per_wait(self):
        events = [json.loads(line) for line in EVENTS.read_text(encoding="utf-8").splitlines()]
        actions = sum(e["type"] == "decision" and e["selected"] != "wait" for e in events)
        entry, log = self.entry(T1)
        self.assertEqual((len(log), entry["actions"], [t for t in log if t.action == "wait"]), (actions, actions, []))

    def test_a_refused_craft_is_an_exact_mismatch(self):
        _, log = self.entry(T1)
        refused = next(t for t in log if not t.ok)
        self.assertEqual(
            replace(refused, obs_hash="-"),
            Transition("t1", 13, SERVER, "-", "craft", "wooden_pickaxe", "bundled:craft:wooden_pickaxe", PICKAXE, {},
                       "exact", "mismatch", ok=False),
        )

    def test_each_menu_key_maps_to_our_action_and_bundled_rule(self):
        _, log = self.entry(T1)
        mine = ("mine", "log", "bundled:mine:log", "exact", "match")
        planks = ("craft", "planks", "bundled:craft:planks", "exact", "match")
        stick = ("craft", "stick", "bundled:craft:stick", "exact", "match")
        refused = ("craft", "wooden_pickaxe", "bundled:craft:wooden_pickaxe", "exact", "mismatch")
        self.assertEqual([(t.action, t.target, t.rule_id, t.cls, t.verdict) for t in log], [
            mine, mine, mine, planks,
            ("craft", "crafting_table", "bundled:craft:crafting_table", "exact", "match"),
            ("place", "crafting_table", None, "tolerant", "match"),
            stick, stick, mine,
            ("move", "approach_table", None, "tolerant", "match"),
            planks,
            ("craft", "oak_boat", None, "ignored", "ignored"),
            refused, refused,
        ])

    def test_waits_spend_the_budget_like_any_decision_of_b_on_the_grid(self):
        # The fifteenth decision is the second wait after the refused craft.
        entry, log = self.entry(replace(T1, budget=15))
        self.assertEqual((entry["actions"], entry["success"], entry["reason"], len(log)), (13, False, "budget", 13))

    def test_the_episode_ends_at_the_first_action_that_holds_the_goal(self):
        entry, log = self.entry(Task("sticks", "stick"))
        self.assertEqual((entry["actions"], entry["success"], entry["reason"], len(log)), (7, True, "goal", 7))


if __name__ == "__main__":
    unittest.main()
