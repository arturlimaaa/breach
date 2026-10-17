import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from breach.proof import proof

ROOT = Path(__file__).resolve().parents[1]

LOG = {"log": 1}
PLANKS = {"log": -1, "planks": 4}
STICK = {"planks": -2, "stick": 4}
STICK_2 = {"planks": -2, "stick": 2}

CONTRADICTED = {
    "id": "stick-count-2-hc-s1", "task": "hc", "server": "grid/stick-count-2", "change": "stick-count-2", "seed": 1,
    "goal": "wooden_pickaxe", "count": 1, "inventory": {}, "success": False, "actions": 8, "reason": "budget",
}
DROPPED = {
    "id": "stone-drop-nothing-hc-s1", "task": "hc", "server": "grid/stone-drop-nothing", "change": "stone-drop-nothing", "seed": 1,
    "goal": "stone_pickaxe", "count": 1, "inventory": {"wooden_pickaxe": 1}, "success": False, "actions": 4, "reason": "budget",
}
CLEAN = {
    "id": "t1-s1", "task": "t1", "server": "grid/vanilla", "change": None, "seed": 1,
    "goal": "stick", "count": 5, "inventory": {"stick": 1}, "success": True, "actions": 4, "reason": "goal",
}


def step(action, target, rule_id, predicted, observed, verdict, **extra):
    cls = {"move": "tolerant", "look": "ignored"}.get(action, "exact")
    return {"action": action, "target": target, "rule_id": rule_id, "predicted": predicted, "observed": observed,
            "cls": cls, "verdict": verdict, "test": False, **extra}


LOGS = {
    # The plan goes on, reuses the refuted stick rule, then a revision recovers five actions later.
    CONTRADICTED["id"]: [
        step("mine", "log", "mine:log", LOG, LOG, "match"),
        step("craft", "planks", "craft:planks", PLANKS, PLANKS, "match"),
        step("craft", "stick", "craft:stick", STICK, STICK_2, "mismatch"),
        step("move", "east", None, {}, {}, "match", ok=True, events=[], message="moved east"),
        step("mine", "log", "mine:log", LOG, LOG, "match"),
        step("craft", "planks", "craft:planks", PLANKS, PLANKS, "match"),
        step("craft", "stick", "craft:stick", STICK, STICK_2, "mismatch"),
        step("craft", "stick", "craft:stick@grid/stick-count-2#1", STICK_2, STICK_2, "match"),
    ],
    # A look and a move between two mines of the same block do not hide the repeat. It never recovers.
    DROPPED["id"]: [
        step("mine", "stone", "mine:stone", {"cobblestone": 1}, {}, "mismatch"),
        step("look", None, None, {}, {}, "ignored"),
        step("move", "east", None, {}, {}, "match"),
        step("mine", "stone", "mine:stone", {"cobblestone": 1}, {}, "mismatch"),
    ],
    # A failed hypothesis test and a quarantined step are not contradictions.
    CLEAN["id"]: [
        step("mine", "log", "mine:log", LOG, LOG, "match"),
        step("craft", "planks", "craft:planks", PLANKS, PLANKS, "match"),
        step("craft", "stick", "craft:stick", {"planks": -2, "stick": 3}, STICK, "mismatch", test=True),
        step("mine", "stone", "mine:stone", {"cobblestone": 1}, {}, "quarantined"),
    ],
}

CALLS = [
    {"episode": CONTRADICTED["id"], "step": 3, "model": "nemotron-3-super", "purpose": "induce",
     "tokens_in": 900, "tokens_out": 300, "latency_ms": 1800},
    {"episode": CONTRADICTED["id"], "step": 3, "model": "nemotron-3-super", "purpose": "induce",
     "tokens_in": 1000, "tokens_out": 200, "latency_ms": 1500},
]

TABLE = """\
| system | set | episodes | success | actions/success | contradicted | after contradiction | immediate repeat | recovery mean | recovery worst | model calls/episode | tokens/episode |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D | worst | 3 | 0% | 4 | 2 | 1 | 100% | 5 | never | 2 | 2400 |
| D | HC | 2 | 0% | - | 2 | 1 | 50% | 5 | never | 1 | 1200 |
| D | T1 | 1 | 100% | 4 | 0 | - | - | - | - | 0 | 0 |
"""

# The contradicting craft completes the goal, so the revision's first use comes in the next episode on that server.
HELD = {"coal": 1, "stick": 1}
TORCH_2 = {"coal": -1, "stick": -1, "torch": 2}
ENDS_ON_IT = {
    "id": "torch-count-2-hc-s1", "task": "hc", "server": "grid/torch-count-2", "change": "torch-count-2", "seed": 1,
    "goal": "torch", "count": 1, "inventory": HELD, "success": True, "actions": 1, "reason": "contradiction at craft:torch",
}
ELSEWHERE = {
    "id": "ladder-count-2-hc-s1", "task": "hc", "server": "grid/ladder-count-2", "change": "ladder-count-2", "seed": 1,
    "goal": "torch", "count": 1, "inventory": HELD, "success": True, "actions": 2, "reason": "goal",
}
RETURN = {
    "id": "torch-count-2-hs-s1", "task": "hs", "server": "grid/torch-count-2", "change": "torch-count-2", "seed": 1,
    "goal": "torch", "count": 1, "inventory": HELD, "success": False, "actions": 2, "reason": "budget",
}
LATER_LOGS = {
    ENDS_ON_IT["id"]: [step("craft", "torch", "craft:torch", {"coal": -1, "stick": -1, "torch": 4}, TORCH_2, "mismatch")],
    ELSEWHERE["id"]: [
        step("craft", "torch", "craft:torch@grid/ladder-count-2#1", TORCH_2, TORCH_2, "match"),
        step("move", "east", None, {}, {}, "match"),
    ],
    RETURN["id"]: [
        step("move", "east", None, {}, {}, "match"),
        step("probe", "torch", "craft:torch@grid/torch-count-2#1", {"torch": 2}, {"torch": 2}, "match", test=True),
    ],
}


def write_run(run_dir: Path, system: str, episodes: list[dict], logs: dict[str, list[dict]], calls: list[dict]) -> Path:
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps({"system": system, "episodes": episodes}))
    for entry in episodes:
        lines = [{"episode": entry["id"], "step": n, "server": entry["server"], "obs_hash": "0", **t}
                 for n, t in enumerate(logs[entry["id"]], 1)]
        (run_dir / f"{entry['id']}.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    (run_dir / "model_calls.jsonl").write_text("".join(json.dumps(call) + "\n" for call in calls))
    return run_dir


class ProofTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.run_dir = write_run(self.tmp / "run", "D", [CONTRADICTED, DROPPED, CLEAN], LOGS, CALLS)

    def test_per_episode_metrics_follow_the_first_contradiction(self):
        self.assertEqual(
            proof(self.run_dir)["episodes"],
            [
                {**CONTRADICTED, "system": "D", "contradictions": 2, "actions_after_contradiction": 1,
                 "immediate_repeat": 0, "recovery_latency": 5, "text_model_calls": 2, "tokens": 2400},
                {**DROPPED, "system": "D", "contradictions": 2, "actions_after_contradiction": 1,
                 "immediate_repeat": 1, "recovery_latency": None, "text_model_calls": 0, "tokens": 0},
                {**CLEAN, "system": "D", "contradictions": 0, "actions_after_contradiction": None,
                 "immediate_repeat": None, "recovery_latency": None, "text_model_calls": 0, "tokens": 0},
            ],
        )

    def test_worst_case_row_comes_first_and_takes_each_columns_worst_episode(self):
        self.assertEqual(
            proof(self.run_dir)["rows"][0],
            {
                "system": "D", "set": "worst", "episodes": 3, "success": 0.0, "actions_per_success": 4,
                "contradicted": 2, "actions_after_contradiction": 1, "immediate_repeat": 1,
                "recovery_latency_mean": 5.0, "recovery_latency_worst": 5, "unrecovered": 1,
                "text_model_calls": 2, "tokens": 2400,
            },
        )

    def test_a_run_tree_gives_each_system_a_worst_row_before_the_set_rows(self):
        write_run(self.tmp / "matrix" / "D", "D", [CLEAN], LOGS, [])
        write_run(self.tmp / "matrix" / "B", "B", [CONTRADICTED], LOGS, CALLS)
        self.assertEqual(
            [(row["system"], row["set"]) for row in proof(self.tmp / "matrix")["rows"]],
            [("B", "worst"), ("D", "worst"), ("B", "HC"), ("D", "T1")],
        )

    def test_each_system_names_its_slowest_recovery_and_averages_all_its_episodes(self):
        result = proof(self.run_dir)
        self.assertEqual(
            {key: result[key] for key in ("worst_case", "aggregate")},
            {
                "worst_case": {"D": {"episode": DROPPED["id"], "recovery_latency": None}},
                "aggregate": {"D": {
                    "system": "D", "set": "all", "episodes": 3, "success": 1 / 3, "actions_per_success": 4.0,
                    "contradicted": 2, "actions_after_contradiction": 1.0, "immediate_repeat": 0.5,
                    "recovery_latency_mean": 5.0, "recovery_latency_worst": 5, "unrecovered": 1,
                    "text_model_calls": 2 / 3, "tokens": 800.0,
                }},
            },
        )

    def test_a_system_without_contradictions_has_no_worst_case_episode(self):
        write_run(self.tmp / "matrix" / "D", "D", [CLEAN], LOGS, [])
        write_run(self.tmp / "matrix" / "B", "B", [CONTRADICTED], LOGS, CALLS)
        self.assertEqual(
            proof(self.tmp / "matrix")["worst_case"],
            {"B": {"episode": CONTRADICTED["id"], "recovery_latency": 5}, "D": {"episode": None, "recovery_latency": None}},
        )

    def test_a_log_that_disagrees_with_the_action_count_is_refused(self):
        write_run(self.tmp / "short", "D", [{**CLEAN, "actions": 5}], LOGS, [])
        with self.assertRaisesRegex(ValueError, "t1-s1"):
            proof(self.tmp / "short")

    def test_a_manifest_whose_success_the_log_contradicts_is_refused(self):
        write_run(self.tmp / "lie", "D", [{**CLEAN, "success": False}], LOGS, [])
        with self.assertRaisesRegex(ValueError, "t1-s1.*success"):
            proof(self.tmp / "lie")

    def test_cli_writes_proof_json_and_prints_the_worst_case_row_first(self):
        result = subprocess.run([sys.executable, "-m", "breach.proof", str(self.run_dir)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(
            (result.stdout, json.loads((self.run_dir / "proof.json").read_text())),
            (TABLE, proof(self.run_dir)),
        )

    def test_cli_on_a_directory_without_logs_exits_nonzero_with_a_clear_message(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        result = subprocess.run([sys.executable, "-m", "breach.proof", str(empty)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(
            (result.returncode, result.stderr),
            (1, f"breach.proof: no run under {empty}: expected manifest.json and one <episode>.jsonl per episode\n"),
        )


class LaterEpisodeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = write_run(Path(tmp.name) / "run", "D", [ENDS_ON_IT, ELSEWHERE, RETURN], LATER_LOGS, [])

    def test_a_probe_reads_the_output_slot_and_leaves_the_inventory_alone(self):
        self.assertEqual(
            {e["id"]: e["success"] for e in proof(self.run_dir)["episodes"]},
            {ENDS_ON_IT["id"]: True, ELSEWHERE["id"]: True, RETURN["id"]: False},
        )

    def test_recovery_counts_on_into_the_next_episode_on_the_same_server(self):
        self.assertEqual(
            {e["id"]: e["recovery_latency"] for e in proof(self.run_dir)["episodes"]},
            {ENDS_ON_IT["id"]: 2, ELSEWHERE["id"]: None, RETURN["id"]: None},
        )


if __name__ == "__main__":
    unittest.main()
