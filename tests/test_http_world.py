import json
import re
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from breach.baseline_b import run_episode_b, vanilla_plan
from breach.evaluate import certified_vanilla, run_jobs
from breach.http_world import HttpWorld, parse
from breach.log import TransitionLog
from breach.loop import run_episode
from breach.proof import proof
from breach.tasks import H2, T1
from breach.world import VANILLA, Action, GridWorld
from tests.fake_adapter import serve

ROOT = Path(__file__).resolve().parents[1]


def seed_1(task):
    return GridWorld(task, seed=1)


def hashless(log):
    return [replace(t, obs_hash="") for t in log]


class HttpWorldTests(unittest.TestCase):
    def adapter(self, make_world=seed_1):
        httpd = serve(make_world)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_reset_then_observe_returns_the_grid_observation(self):
        self.assertEqual(HttpWorld(self.adapter(), T1).observe(), GridWorld(T1, seed=1).observe())

    def test_steps_return_the_grid_results(self):
        task = replace(T1, inventory={"planks": 2})
        actions = [
            Action("move", "east"), Action("probe", "stick", grid={"planks": 2}), Action("look"), Action("mine"),
            Action("place", "crafting_table"),
        ]
        http, grid = HttpWorld(self.adapter(), task), GridWorld(task, seed=1)
        self.assertEqual([http.step(a) for a in actions], [grid.step(a) for a in actions])

    def test_blocks_forget_a_mined_block_and_keep_one_out_of_view(self):
        def log_east_stone_west(task):
            world = GridWorld(task, seed=1)
            world.blocks = {(1, 0): "log", (-8, 0): "stone"}
            return world

        world = HttpWorld(self.adapter(log_east_stone_west), T1)
        world.step(Action("move", "east"))
        world.step(Action("mine"))
        self.assertEqual(world.blocks, {(-8, 0): "stone"})

    def test_a_column_shows_the_visible_block_nearest_the_bots_height(self):
        column = [(63, "grass_block"), (64, "log"), (66, "leaves")]
        data = {
            "server": "mc/test", "position": {"x": 0, "y": 64, "z": 0}, "inventory": {}, "action_count": 0, "budget": 1,
            "done": False, "success": False,
            "visible": [{"x": 1, "y": y, "z": 0, "block": b} for y, b in column] + [{"x": 2, "y": 61, "z": 0, "block": "stone"}],
        }
        self.assertEqual(sorted(parse(data).visible), [(1, 0, "log"), (2, 0, "stone")])

    def test_done_and_success_follow_the_observation(self):
        url = self.adapter()
        spent = HttpWorld(url, replace(T1, budget=1))
        spent.step(Action("move", "east"))
        held = HttpWorld(url, replace(T1, inventory={"wooden_pickaxe": 1}))
        self.assertEqual([(w.done, w.success, w.actions) for w in (spent, held)], [(True, False, 1), (True, True, 0)])

    def test_reset_keeps_the_commands_the_adapter_issued(self):
        world = HttpWorld(self.adapter(), replace(T1, inventory={"planks": 4}))
        self.assertEqual(world.reset_message, "/clear; /give @s planks 4")

    def test_server_is_the_adapters_label(self):
        url = self.adapter(lambda task: GridWorld(task, seed=1, server="grid/stick-count-2"))
        self.assertEqual(HttpWorld(url, T1).server, "grid/stick-count-2")

    def test_an_adapter_error_names_the_url_and_the_status(self):
        url = self.adapter() + "/nowhere"
        with self.assertRaisesRegex(RuntimeError, re.escape(f"POST {url}/reset: HTTP 404")):
            HttpWorld(url, T1)

    def test_the_executor_over_http_repeats_the_grid_episode(self):
        for task in (T1, H2):
            with self.subTest(task=task.task_id):
                grid_log, http_log = TransitionLog(), TransitionLog()
                grid = run_episode(GridWorld(task, seed=1), certified_vanilla(), grid_log, task.task_id)
                http = run_episode(HttpWorld(self.adapter(), task), certified_vanilla(), http_log, task.task_id)
                self.assertEqual((http.reason, http, hashless(http_log)), ("goal", grid, hashless(grid_log)))

    def test_b_over_http_repeats_the_grid_episode(self):
        grid_log, http_log = TransitionLog(), TransitionLog()
        grid = run_episode_b(GridWorld(T1, seed=1), grid_log, "t1", vanilla_plan)
        http = run_episode_b(HttpWorld(self.adapter(), T1), http_log, "t1", vanilla_plan)
        self.assertEqual((http.reason, http, hashless(http_log)), ("goal", grid, hashless(grid_log)))

    def test_cli_writes_run_jobs_manifest_entry_and_the_proof_accepts_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, grid = Path(tmp) / "run", Path(tmp) / "grid"
            cli = [sys.executable, "-m", "breach.live", str(run), "--url", self.adapter(), "--task", "T1"]
            subprocess.run(cli, cwd=ROOT, check=True, capture_output=True)
            run_jobs(run_episode, [(T1, 1, "grid/vanilla", VANILLA, None)], certified_vanilla, grid, name="D")
            [entry], [grid_entry] = (json.loads((d / "manifest.json").read_text())["episodes"] for d in (run, grid))
            [proven] = proof(run)["episodes"]
        self.assertEqual(
            (entry, proven["system"], proven["contradictions"]),
            (grid_entry | {"id": "t1", "seed": None, "reset": "/clear"}, "D", 0),
        )


if __name__ == "__main__":
    unittest.main()
