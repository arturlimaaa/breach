import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from breach.baseline_a import run_episode_a, vanilla_replanner
from breach.changes import benchmark
from breach.evaluate import run_jobs
from breach.matrix import job
from breach.proof import proof, read_log
from breach.store import RuleStore

ROOT = Path(__file__).resolve().parents[1]


class MatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.run_dir = Path(tmp.name) / "matrix"
        cls.stdout = subprocess.run(
            [sys.executable, "-m", "breach.matrix", str(cls.run_dir), "--changes", "stick-count-2", "--seeds", "1", "--systems", "A", "B", "D"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        cls.proof = json.loads((cls.run_dir / "proof.json").read_text())
        cls.episodes = {(e["system"], e["task"]): e for e in cls.proof["episodes"]}

    def test_writes_one_manifest_per_system(self):
        self.assertEqual([m.relative_to(self.run_dir).parts[0] for m in sorted(self.run_dir.rglob("manifest.json"))], ["A", "B", "D"])

    def test_every_system_has_a_worst_case(self):
        self.assertEqual(sorted(self.proof["worst_case"]), ["A", "B", "D"])

    def test_a_calls_the_model_again_on_hs_where_d_calls_none(self):
        self.assertEqual(
            (self.episodes["A", "hs"]["text_model_calls"] > 0, self.episodes["D", "hs"]["text_model_calls"]),
            (True, 0),
        )

    def test_b_contradicts_on_the_bundled_stick_recipe(self):
        log = read_log(self.run_dir / "B" / f"{self.episodes['B', 'hc']['id']}.jsonl")
        self.assertIn("bundled:craft:stick", {t.rule_id for t in log.contradictions()})

    def test_d_stops_at_the_contradiction(self):
        hc = self.episodes["D", "hc"]
        self.assertEqual((hc["change"], hc["contradictions"], hc["actions_after_contradiction"]), ("stick-count-2", 1, 0))

    def test_d_returns_to_the_server_with_the_demotion_carried(self):
        hs = self.episodes["D", "hs"]
        self.assertEqual((hs["id"], hs["contradictions"], hs["reason"]), ("stick-count-2-hs-s1", 0, "no certified plan"))

    def test_table_leads_with_a_worst_row_per_system_and_shows_hs_as_a_row(self):
        cells = [[c.strip() for c in line.split("|")[1:3]] for line in self.stdout.splitlines()[2:]]
        self.assertEqual(
            cells,
            [["A", "worst"], ["B", "worst"], ["D", "worst"], ["A", "HC"], ["A", "HS"], ["B", "HC"], ["D", "HC"], ["D", "HS"]],
        )


class OfflineModelTests(unittest.TestCase):
    def test_each_offline_model_call_lands_in_model_calls_jsonl_and_the_proof_counts_it(self):
        change, goal = next((c, g) for c, g in benchmark() if c.id == "stick-count-2")
        calls = {}

        def system(world, store, log, episode):
            complete, calls[episode] = vanilla_replanner(world, {"BREACH_RUN_DIR": str(run)})
            return run_episode_a(world, log, episode, complete)

        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "A"
            run_jobs(system, [job("hc", change, goal, 1), job("hs", change, goal, 1)], RuleStore, run, name="A")
            counted = {e["id"]: e["text_model_calls"] for e in proof(run)["episodes"]}
        self.assertEqual((counted, min(counted.values()) > 0), ({episode: len(made) for episode, made in calls.items()}, True))


if __name__ == "__main__":
    unittest.main()
