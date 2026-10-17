import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from breach.changes import apply
from breach.evaluate import certified_vanilla
from breach.live import Pack, live
from breach.proof import proof
from breach.reload import hr_task
from breach.rules import Rule
from breach.tasks import T1
from breach.world import VANILLA, GridWorld
from tests.fake_adapter import serve
from tests.test_reload import STICK_COUNT, console

CHANGED = apply(STICK_COUNT, VANILLA)
LIVE = [sys.executable, "-m", "breach.live"]
ROOT = Path(__file__).resolve().parents[1]


class LiveWiringTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.worlds = []

    def adapter(self, ruleset=VANILLA, server="grid/vanilla"):
        def make(task):
            self.worlds.append(GridWorld(task, seed=1, ruleset=ruleset, server=server))
            return self.worlds[-1]

        httpd = serve(make)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_a_d_run_keeps_its_status_and_store_in_the_run_directory(self):
        run = live(self.tmp / "run", self.adapter(), T1, "D")
        status = json.loads((run / "status.json").read_text())
        store = {r["rule_id"]: r["status"] for r in json.loads((run / "store.json").read_text())}
        self.assertEqual((status["episode"], store["craft:stick"]), ("t1", "certified"))

    def test_store_starts_the_run_from_an_earlier_runs_rules(self):
        revision = Rule(
            "craft:stick@grid/stick-count-2", "craft", "stick", {"planks": -2, "stick": 2}, status="certified",
            scope="grid/stick-count-2", source="induced", revision_of="craft:stick",
        )
        certified_vanilla(self.tmp / "earlier.json").add(revision)
        run = self.tmp / "run"
        url = self.adapter(CHANGED, "grid/stick-count-2")
        subprocess.run([*LIVE, str(run), "--url", url, "--task", "T1", "--store", str(self.tmp / "earlier.json")], cwd=ROOT, check=True)
        [proven] = proof(run)["episodes"]
        kept = {r["rule_id"] for r in json.loads((run / "store.json").read_text())}
        self.assertEqual((proven["success"], proven["contradictions"], revision.rule_id in kept), (True, 0, True))

    def test_keep_pack_leaves_the_datapack_enabled_for_the_next_run_on_the_server(self):
        url = self.adapter()
        run, typed = console(self.tmp / "server", STICK_COUNT, self.worlds)
        live(self.tmp / "run", url, hr_task(STICK_COUNT), "D", Pack(STICK_COUNT, self.tmp / "server", run), keep_pack=True)
        self.assertEqual(
            ([argv[-1] for argv in typed], self.worlds[-1].ruleset),
            (["reload\r", 'datapack enable "file/stick-count-2"\r', "datapack list enabled\r"], CHANGED),
        )

    def test_llm_gives_d_the_real_inducer_logging_into_the_run_directory(self):
        # A closed local port: the inducer's first call fails at once, is logged, and stops the run.
        env = {**os.environ, "BREACH_LLM_BASE_URL": "http://127.0.0.1:9/v1", "BREACH_LLM_API_KEY": "test"}
        run, url = self.tmp / "run", self.adapter(CHANGED, "grid/stick-count-2")
        done = subprocess.run([*LIVE, str(run), "--url", url, "--task", "T1", "--llm"], cwd=ROOT, env=env, capture_output=True, text=True)
        calls = [json.loads(line) for line in (run / "model_calls.jsonl").read_text().splitlines()]
        self.assertEqual((done.returncode != 0, [(c["purpose"], "error" in c) for c in calls]), (True, [("induce", True)]))


if __name__ == "__main__":
    unittest.main()
