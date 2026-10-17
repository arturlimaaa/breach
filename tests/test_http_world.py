import json
import re
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from breach.baseline_a import run_episode_a
from breach.baseline_b import run_episode_b, vanilla_plan
from breach.evaluate import certified_vanilla, run_jobs
from breach.http_world import HttpWorld, parse
from breach.log import TransitionLog
from breach.loop import run_episode
from breach.proof import proof
from breach.tasks import T1
from breach.world import VANILLA, Action, GridWorld, Task
from tests.fake_adapter import serve
from tests.test_baseline_a import T1_PLAN
from tests.test_induce import scripted

ROOT = Path(__file__).resolve().parents[1]
PLANKS = Task("p", "planks")
TOWARD, MINE, CRAFT_PLANKS = ("move", {"toward": "log"}, None), ("mine", "log", None), ("craft", "planks", {"log": 1})


def seed_1(task):
    return GridWorld(task, seed=1)


def only(blocks, world=GridWorld):
    """A seed-1 world holding just `blocks`."""

    def make(task):
        made = world(task, seed=1)
        made.blocks = dict(blocks)
        return made

    return make


class Blind(GridWorld):
    """Looks the way the Mineflayer adapter does: no headings, the observation is the whole answer."""

    def _look(self, action):
        return self._result(True, "blocks in sight")


class Mirage(GridWorld):
    """Shows a log at (3, 0) that no path reaches, like a tree across water."""

    def observe(self):
        obs = super().observe()
        return replace(obs, visible=[*obs.visible, (3, 0, "log")])


def hashless(log):
    return [replace(t, obs_hash="") for t in log]


def wire(steps):
    return [(s["action"], s["target"], s["grid"]) for s in steps]


class HttpWorldTests(unittest.TestCase):
    def adapter(self, make_world=seed_1, on_step=lambda body: None):
        httpd = serve(make_world, on_step)
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

    def test_the_fake_moves_toward_and_mines_by_name_in_one_action_each(self):
        world = HttpWorld(self.adapter(only({(3, 0): "log"})), T1)
        results = [world.step(Action(name, "log")) for name in ("move", "mine", "mine", "move")]
        self.assertEqual(
            [(r.ok, r.observation.position, r.observation.inventory, r.observation.action_count) for r in results],
            [(True, (2, 0), {}, 1), (True, (3, 0), {"log": 1}, 2), (False, (3, 0), {"log": 1}, 3), (False, (3, 0), {"log": 1}, 4)],
        )

    def test_the_executor_over_http_moves_once_per_mine(self):
        log = TransitionLog()
        result = run_episode(HttpWorld(self.adapter(), T1), certified_vanilla(), log, "t1")
        travel = [("move", "log", "match"), ("mine", "log", "match"), ("craft", "planks", "match")]
        self.assertEqual(
            (result.reason, len(log) == result.actions, [(t.action, t.target, t.verdict) for t in log]),
            ("goal", True, [*travel, ("craft", "crafting_table", "match"), *travel, ("craft", "stick", "match"), *travel,
                            ("craft", "wooden_pickaxe", "match")]),
        )

    def test_the_executor_sends_the_toward_target_the_block_to_mine_and_the_craft_grid(self):
        steps = []
        run_episode(HttpWorld(self.adapter(seed_1, steps.append), T1), certified_vanilla(), TransitionLog(), "t1")
        self.assertEqual(wire(steps), [
            TOWARD, MINE, CRAFT_PLANKS, ("craft", "crafting_table", {"planks": 4}), TOWARD, MINE, CRAFT_PLANKS,
            ("craft", "stick", {"planks": 2}), TOWARD, MINE, CRAFT_PLANKS, ("craft", "wooden_pickaxe", {"planks": 3, "stick": 2}),
        ])

    def test_a_failed_toward_move_is_logged_once_and_ends_the_episode(self):
        log = TransitionLog()
        result = run_episode(HttpWorld(self.adapter(only({}, Mirage)), T1), certified_vanilla(), log, "t1")
        self.assertEqual(
            (result.reason, [(t.action, t.target, t.cls, t.verdict) for t in log]),
            ("no reachable log", [("move", "log", "tolerant", "mismatch")]),
        )

    def test_a_look_that_shows_nothing_leads_to_a_bounded_spiral(self):
        log = TransitionLog()
        result = run_episode(HttpWorld(self.adapter(only({}, Blind)), T1), certified_vanilla(), log, "t1")
        legs = [("east", 1), ("south", 1), ("west", 2), ("north", 2), ("east", 3), ("south", 3), ("west", 4), ("north", 4)]
        self.assertEqual(
            (result.reason, [(t.action, t.target) for t in log]),
            ("no reachable log", [("look", None), *(("move", d) for d, n in legs for _ in range(n))]),
        )

    def test_a_look_that_shows_nothing_walks_the_spiral_until_a_log_is_in_view(self):
        log = TransitionLog()
        result = run_episode(HttpWorld(self.adapter(only({(9, 0): "log"}, Blind)), PLANKS), certified_vanilla(), log, "p")
        self.assertEqual(
            (result.reason, [(t.action, t.target) for t in log]),
            ("goal", [("look", None), ("move", "east"), ("move", "log"), ("mine", "log"), ("craft", "planks")]),
        )

    def test_a_budget_spent_bringing_a_log_into_view_issues_no_toward_move(self):
        log = TransitionLog()
        world = HttpWorld(self.adapter(only({(9, 0): "log"}, Blind)), replace(PLANKS, budget=2))
        result = run_episode(world, certified_vanilla(), log, "p")
        self.assertEqual((result.reason, [(t.action, t.target) for t in log]), ("budget", [("look", None), ("move", "east")]))

    def test_b_sends_the_block_to_mine_and_the_craft_grid(self):
        steps = []
        run_episode_b(HttpWorld(self.adapter(seed_1, steps.append), T1), TransitionLog(), "t1", vanilla_plan)
        self.assertEqual([s for s in wire(steps) if s[0] != "move"], [
            MINE, CRAFT_PLANKS, ("craft", "stick", {"planks": 2}), MINE, CRAFT_PLANKS, ("craft", "crafting_table", {"planks": 4}),
            MINE, CRAFT_PLANKS, ("craft", "wooden_pickaxe", {"planks": 3, "stick": 2}),
        ])

    def test_a_sends_the_block_to_mine_and_the_craft_grid(self):
        steps = []
        complete, _ = scripted(json.dumps(T1_PLAN))
        run_episode_a(HttpWorld(self.adapter(seed_1, steps.append), T1), TransitionLog(), "t1", complete)
        self.assertEqual([s for s in wire(steps) if s[0] != "move"], [
            MINE, CRAFT_PLANKS, ("craft", "crafting_table", {"planks": 4}), MINE, CRAFT_PLANKS, ("craft", "stick", {"planks": 2}),
            MINE, CRAFT_PLANKS, ("craft", "wooden_pickaxe", {"planks": 3, "stick": 2}),
        ])

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
        # The adapter paths, so the live episode takes one move per mine: 12 actions where the grid takes 19.
        self.assertEqual(
            (entry, proven["system"], proven["contradictions"]),
            (grid_entry | {"id": "t1", "seed": None, "reset": "/clear", "actions": 12}, "D", 0),
        )


if __name__ == "__main__":
    unittest.main()
