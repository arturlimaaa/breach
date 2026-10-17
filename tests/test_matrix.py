import json
import os
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
            [sys.executable, "-m", "breach.matrix", str(cls.run_dir), "--changes", "stick-count-2", "--seeds", "1", "--systems", "A", "B", "C", "D"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        cls.proof = json.loads((cls.run_dir / "proof.json").read_text())
        cls.episodes = {(e["system"], e["task"]): e for e in cls.proof["episodes"]}

    def test_writes_one_manifest_per_system(self):
        self.assertEqual(
            [m.relative_to(self.run_dir).parts[0] for m in sorted(self.run_dir.rglob("manifest.json"))], ["A", "B", "C", "D"],
        )

    def test_every_system_has_a_worst_case(self):
        self.assertEqual(sorted(self.proof["worst_case"]), ["A", "B", "C", "D"])

    def test_c_meets_the_contradiction_again_on_hs_from_a_fresh_store(self):
        self.assertEqual((self.episodes["C", "hc"]["contradictions"] > 0, self.episodes["C", "hs"]["contradictions"] > 0), (True, True))

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
            [
                ["A", "worst"], ["B", "worst"], ["C", "worst"], ["D", "worst"],
                ["A", "HC"], ["A", "HS"], ["B", "HC"], ["C", "HC"], ["C", "HS"], ["D", "HC"], ["D", "HS"],
            ],
        )


class PerfectInducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.runs = Path(tmp.name)
        subprocess.run(
            [sys.executable, "-m", "breach.matrix", str(cls.runs / "perfect"), "--changes", "stick-count-2", "--seeds", "1",
             "--systems", "D", "--inducer", "perfect"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        cls.job_dir = cls.runs / "perfect" / "D" / "stick-count-2-s1"
        cls.episodes = {e["task"]: e for e in json.loads((cls.runs / "perfect" / "proof.json").read_text())["episodes"]}

    def test_d_recovers_in_hc_and_meets_no_contradiction_on_its_return(self):
        hc, hs = self.episodes["hc"], self.episodes["hs"]
        self.assertEqual((type(hc["recovery_latency"]), hs["contradictions"], hs["success"]), (int, 0, True))

    def test_the_job_keeps_its_rules_and_status_beside_its_manifest(self):
        store = {r["rule_id"]: r for r in json.loads((self.job_dir / "store.json").read_text())}
        status = json.loads((self.job_dir / "status.json").read_text())
        self.assertEqual(
            (status["episode"], store["craft:stick@grid/stick-count-2"]["delta"]),
            ("stick-count-2-hs-s1", {"planks": -2, "stick": 2}),
        )

    def test_runs_latest_links_to_the_newest_job(self):
        latest = self.runs / "latest"
        self.assertEqual((latest.is_symlink(), latest.resolve()), (True, self.job_dir.resolve()))


class NemotronWiringTests(unittest.TestCase):
    def test_llm_sends_ds_inducer_through_llm_complete_into_the_jobs_model_calls(self):
        # A closed local port: every call fails at once, and llm.complete still logs it.
        env = {**os.environ, "BREACH_LLM_BASE_URL": "http://127.0.0.1:9/v1", "BREACH_LLM_API_KEY": "test"}
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "llm"
            subprocess.run(
                [sys.executable, "-m", "breach.matrix", str(run), "--changes", "stick-count-2", "--seeds", "1", "--systems", "D", "--llm"],
                cwd=ROOT, env=env, capture_output=True, text=True, check=True,
            )
            calls = [json.loads(line) for line in (run / "D" / "stick-count-2-s1" / "model_calls.jsonl").read_text().splitlines()]
            counted = sum(e["text_model_calls"] for e in json.loads((run / "proof.json").read_text())["episodes"])
        self.assertEqual(({c["purpose"] for c in calls}, all("error" in c for c in calls), counted), ({"induce"}, True, len(calls)))


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
