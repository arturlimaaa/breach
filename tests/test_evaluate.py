import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from functools import partial

from breach.changes import apply, benchmark
from breach.evaluate import certified_vanilla, run_jobs
from breach.log import Transition
from breach.loop import EpisodeResult, run_episode
from breach.matrix import job, perfect
from breach.proof import proof
from breach.store import RuleStore
from breach.tasks import H1, T1
from breach.world import VANILLA, Action

T1_JOB = (T1, 1, "grid/vanilla", VANILLA, None)
H1_JOB = (H1, 1, "grid/vanilla", VANILLA, None)
ROOT = Path(__file__).resolve().parents[1]


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_run_jobs_logs_one_line_per_action(self):
        run = run_jobs(run_episode, [T1_JOB], certified_vanilla, self.tmp / "run", name="D")
        [entry] = json.loads((run / "manifest.json").read_text())["episodes"]
        lines = (run / f"{entry['id']}.jsonl").read_text().splitlines()
        self.assertEqual((len(lines), entry["success"]), (entry["actions"], True))

    def test_carried_memory_lets_the_next_episode_certify_a_revision_from_both_episodes_evidence(self):
        change, goal = next((c, g) for c, g in benchmark() if c.id == "stick-count-2")
        run = self.tmp / "chain"
        system = partial(run_episode, induce=perfect(apply(change, VANILLA)))
        jobs = [job("hc", change, goal, 1), job("hs", change, goal, 1)]
        run_jobs(system, jobs, partial(certified_vanilla, run / "store.json"), run, carry_memory=True, name="D")
        store = {r["rule_id"]: r["status"] for r in json.loads((run / "store.json").read_text())}
        # proof() refuses a log whose length differs from its episode's actions, so the earlier log was read, not copied.
        self.assertEqual((store["craft:stick@grid/stick-count-2"], len(proof(run)["episodes"])), ("certified", 2))

    def test_proof_of_a_vanilla_t1_run_reports_full_success_and_no_contradictions(self):
        worst = proof(run_jobs(run_episode, [T1_JOB], certified_vanilla, self.tmp / "run", name="D"))["rows"][0]
        self.assertEqual((worst["set"], worst["success"], worst["contradicted"]), ("worst", 1.0, 0))

    def test_only_carried_memory_shares_a_store_and_the_earlier_logs_across_jobs(self):
        def shared(carry_memory):
            seen = []

            def system(world, store, log, episode):
                seen.append((store, len(log)))
                log.append(Transition(episode, 1, world.server, "0", "look", None, None, {}, {}, "ignored", "ignored"))
                return EpisodeResult(True, 0, "goal")

            run_jobs(system, [T1_JOB, H1_JOB], RuleStore, self.tmp / str(carry_memory), carry_memory=carry_memory, name="D")
            return seen[0][0] is seen[1][0], [prior for _, prior in seen]

        self.assertEqual((shared(True), shared(False)), ((True, [0, 1]), (False, [0, 0])))

    def test_the_manifest_records_the_worlds_outcome_not_the_systems_claim(self):
        def liar(world, store, log, episode):
            world.step(Action("move", "east"))
            return EpisodeResult(True, 0, "goal")

        run = run_jobs(liar, [T1_JOB], RuleStore, self.tmp / "run", name="D")
        [entry] = json.loads((run / "manifest.json").read_text())["episodes"]
        self.assertEqual(
            {k: entry[k] for k in ("goal", "count", "inventory", "success", "actions", "reason")},
            {"goal": "wooden_pickaxe", "count": 1, "inventory": {}, "success": False, "actions": 1, "reason": "goal"},
        )

    def test_a_repeated_job_is_refused_instead_of_sharing_a_log(self):
        with self.assertRaises(FileExistsError):
            run_jobs(run_episode, [T1_JOB, T1_JOB], certified_vanilla, self.tmp / "run", name="D")

    def test_cli_runs_d_on_training_then_holdout_for_each_seed(self):
        run = self.tmp / "run"
        subprocess.run([sys.executable, "-m", "breach.evaluate", str(run), "--seeds", "1", "2"], cwd=ROOT, check=True, capture_output=True)
        self.assertEqual(
            [(e["system"], e["task"], e["seed"]) for e in proof(run)["episodes"]],
            [("D", task, seed) for seed in (1, 2) for task in ("t1", "t2", "t3", "h1")],
        )


if __name__ == "__main__":
    unittest.main()
