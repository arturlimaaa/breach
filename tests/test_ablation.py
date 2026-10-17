import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from breach.ablation import ablation
from breach.proof import proof
from tests.test_proof import ROOT, step, write_run

NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SUPER = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B"
STICK, STICK_2 = {"planks": -2, "stick": 4}, {"planks": -2, "stick": 2}

# Four sticks from four planks: the refuting craft makes two, the revision makes the other two.
HC = {
    "id": "stick-count-2-hc-s1", "task": "hc", "server": "grid/stick-count-2", "change": "stick-count-2", "seed": 1,
    "goal": "stick", "count": 4, "inventory": {"planks": 4}, "success": True, "actions": 2, "reason": "goal",
}
LOGS = {HC["id"]: [
    step("craft", "stick", "craft:stick", STICK, STICK_2, "mismatch"),
    step("craft", "stick", "craft:stick@grid/stick-count-2", STICK_2, STICK_2, "match", test=True),
]}
CALLS = [
    {"episode": HC["id"], "step": 1, "model": NANO, "purpose": "induce", "tokens_in": 1000, "tokens_out": 200, "latency_ms": 1500},
    {"episode": HC["id"], "step": 1, "model": NANO, "purpose": "induce", "tokens_in": 900, "tokens_out": 100, "latency_ms": 2500},
]
RATE_LIMITED = {
    "episode": HC["id"], "step": 1, "model": SUPER, "purpose": "induce", "tokens_in": 0, "tokens_out": 0, "latency_ms": 300,
    "error": "RuntimeError('HTTP 429')",
}


def recovered(run_dir):
    write_run(run_dir / "D" / "stick-count-2-s1", "D", [HC], LOGS, CALLS)
    proof(run_dir)
    return 0


def rate_limited(run_dir):
    """The first induction call fails, which ends the matrix before it writes a manifest or proof.json."""
    chain = run_dir / "D" / "stick-count-2-s1"
    chain.mkdir(parents=True)
    (chain / "model_calls.jsonl").write_text(json.dumps(RATE_LIMITED) + "\n")
    return 1


def fake_matrix(children, commands):
    """Runner that records each command and the model in its environment, then plays that model's child."""

    def run(argv, env):
        commands.append((argv[1:], env["BREACH_LLM_MODEL"]))
        return children[env["BREACH_LLM_MODEL"]](Path(argv[3]))

    return run


TABLE = """\
| model | success | recovery mean | recovery worst | model calls | tokens | mean latency ms | exit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B | 100% | 1 | 1 | 2 | 2200 | 2000 | 0 |
| nvidia/NVIDIA-Nemotron-3-Super-120B-A12B | - | - | - | 1 | 0 | 300 | 1 |
"""


class AblationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name) / "ablation"
        self.commands = []
        self.rows = ablation(self.out, [1, 2], [NANO, SUPER], run=fake_matrix({NANO: recovered, SUPER: rate_limited}, self.commands))

    def test_each_model_runs_d_with_the_text_model_and_its_id_in_the_child_environment(self):
        self.assertEqual(
            self.commands,
            [
                (["-m", "breach.matrix", str(self.out / "nvidia-NVIDIA-Nemotron-3-Nano-30B-A3B"), "--systems", "D", "--llm", "--seeds", "1", "2"], NANO),
                (["-m", "breach.matrix", str(self.out / "nvidia-NVIDIA-Nemotron-3-Super-120B-A12B"), "--systems", "D", "--llm", "--seeds", "1", "2"], SUPER),
            ],
        )

    def test_a_row_per_model_from_its_proof_and_model_calls_and_a_failed_run_keeps_only_its_cost(self):
        self.assertEqual(
            self.rows,
            [
                {
                    "model": NANO, "exit": 0, "success": 1.0, "recovery_latency_mean": 1.0, "recovery_latency_worst": 1,
                    "unrecovered": 0, "model_calls": 2, "tokens": 2200, "latency_ms_mean": 2000.0,
                },
                {
                    "model": SUPER, "exit": 1, "success": None, "recovery_latency_mean": None, "recovery_latency_worst": None,
                    "unrecovered": None, "model_calls": 1, "tokens": 0, "latency_ms_mean": 300.0,
                },
            ],
        )

    def test_writes_the_rows_as_ablation_json_and_the_table_as_ablation_md(self):
        self.assertEqual(
            (json.loads((self.out / "ablation.json").read_text()), (self.out / "ablation.md").read_text()),
            (self.rows, TABLE),
        )


class RealMatrixTests(unittest.TestCase):
    def test_the_matrix_cli_accepts_the_command_and_each_row_reads_its_own_run(self):
        def offline(argv, env):
            # A test must not call Nemotron, so the child runs the matrix without --llm.
            return subprocess.run([a for a in argv if a != "--llm"], env=env, cwd=ROOT, capture_output=True).returncode

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ablation"
            rows = ablation(out, [1], [NANO, SUPER], ["stick-count-2"], run=offline)
            runs = [json.loads((out / name / "proof.json").read_text())["aggregate"]["D"] for name in (
                "nvidia-NVIDIA-Nemotron-3-Nano-30B-A3B", "nvidia-NVIDIA-Nemotron-3-Super-120B-A12B")]
        self.assertEqual(
            [(r["model"], r["exit"], r["success"], r["unrecovered"]) for r in rows],
            [(NANO, 0, runs[0]["success"], runs[0]["unrecovered"]), (SUPER, 0, runs[1]["success"], runs[1]["unrecovered"])],
        )


if __name__ == "__main__":
    unittest.main()
