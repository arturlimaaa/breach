import json
import re
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from itertools import takewhile
from pathlib import Path

from breach.baseline_a import run_episode_a
from breach.baseline_b import run_episode_b, vanilla_plan
from breach.evaluate import certified_vanilla, run_jobs
from breach.http_world import HttpWorld, parse
from breach.log import TransitionLog
from breach.loop import run_episode
from breach.proof import proof
from breach.tasks import H2, T1, T3
from breach.world import VANILLA, Action, GridWorld, Task
from tests.fake_adapter import observation, serve
from tests.test_baseline_a import T1_PLAN
from tests.test_induce import scripted

ROOT = Path(__file__).resolve().parents[1]
PLANKS = Task("p", "planks")
TOWARD, MINE, CRAFT_PLANKS = ("move", {"toward": "log"}, None), ("mine", "log", None), ("craft", "planks", {"log": 1})
PLACE_TABLE = ("place", "crafting_table", None)


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
    """Its look has no output, which is what a failed adapter look returns."""

    def _look(self, action):
        return self._result(True, "blocks in sight")


class Mirage(GridWorld):
    """Shows a log at (3, 0) that no path reaches, like a tree across water."""

    def observe(self):
        obs = super().observe()
        return replace(obs, visible=[*obs.visible, (3, 0, "log")])


class Bare(HttpWorld):
    """An adapter from before `executed`: its step replies carry no such field."""

    def __init__(self, reply):
        self.blocks, self.reply = {}, reply

    def _call(self, method, path, body=None):
        return self.reply


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

    def test_a_refused_step_reaches_the_core_as_not_executed_and_a_reply_without_the_field_as_executed(self):
        refused = HttpWorld(self.adapter(only({(5, 0): "log"})), T1).step(Action("mine", "log"))
        reply = {"ok": True, "message": "", "output": None, "events": [], "observation": observation(GridWorld(T1, seed=1).observe())}
        self.assertEqual((refused.ok, refused.executed, Bare(reply).step(Action("look")).executed), (False, False, True))

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
                            ("place", "crafting_table", "match"), ("craft", "wooden_pickaxe", "match")]),
        )

    def test_the_executor_sends_the_toward_target_the_block_to_mine_and_the_craft_grid(self):
        steps = []
        run_episode(HttpWorld(self.adapter(seed_1, steps.append), T1), certified_vanilla(), TransitionLog(), "t1")
        self.assertEqual(wire(steps), [
            TOWARD, MINE, CRAFT_PLANKS, ("craft", "crafting_table", {"planks": 4}), TOWARD, MINE, CRAFT_PLANKS,
            ("craft", "stick", {"planks": 2}), TOWARD, MINE, CRAFT_PLANKS, PLACE_TABLE, ("craft", "wooden_pickaxe", {"planks": 3, "stick": 2}),
        ])

    def test_a_failed_toward_move_then_a_refused_mine_ends_the_episode(self):
        log = TransitionLog()
        result = run_episode(HttpWorld(self.adapter(only({}, Mirage)), T1), certified_vanilla(), log, "t1")
        self.assertEqual(
            (result.reason, [(t.action, t.target, t.cls, t.verdict) for t in log]),
            ("no reachable log", [("move", "log", "tolerant", "mismatch"), ("mine", "log", "tolerant", "mismatch")]),
        )

    def test_the_fakes_heading_move_goes_along_the_heading_and_stops_short_of_a_block(self):
        steps = []
        world = HttpWorld(self.adapter(only({(3, 0): "stone"}), steps.append), T1)
        results = [world.step(Action("move", target)) for target in ("E8", "N2")]
        self.assertEqual(
            ([(r.ok, r.observation.position) for r in results], wire(steps)),
            ([(False, (2, 0)), (True, (2, -2))], [("move", {"heading": "E", "blocks": 8}, None), ("move", {"heading": "N", "blocks": 2}, None)]),
        )

    def test_a_look_with_no_output_leads_to_a_bounded_spiral_of_heading_moves(self):
        log = TransitionLog()
        result = run_episode(HttpWorld(self.adapter(only({}, Blind)), T1), certified_vanilla(), log, "t1")
        legs = ["E1", "S1", "W2", "N2", "E3", "S3", "W4", "N4"]
        self.assertEqual(
            (result.reason, [(t.action, t.target) for t in log]),
            ("no reachable log", [("look", None), *(("move", leg) for leg in legs)]),
        )

    def test_a_look_with_no_output_walks_the_spiral_until_a_log_is_in_view(self):
        log = TransitionLog()
        result = run_episode(HttpWorld(self.adapter(only({(9, 0): "log"}, Blind)), PLANKS), certified_vanilla(), log, "p")
        self.assertEqual(
            (result.reason, [(t.action, t.target) for t in log]),
            ("goal", [("look", None), ("move", "E1"), ("move", "log"), ("mine", "log"), ("craft", "planks")]),
        )

    def test_a_look_with_headings_explores_by_heading_moves_until_the_toward_move(self):
        log = TransitionLog()
        result = run_episode(HttpWorld(self.adapter(), H2), certified_vanilla(), log, "h2")
        explored = list(takewhile(lambda t: t.target != "log", log))
        moves = [t.target for t in explored if t.action == "move"]
        self.assertEqual(
            (result.reason, {t.action for t in explored}, sum(t.action == "look" for t in explored) > 1,
             [m for m in moves if not re.fullmatch(r"[NESW]{1,2}[1-8]", m)]),
            ("goal", {"look", "move"}, True, []),
        )

    def test_a_budget_spent_bringing_a_log_into_view_issues_no_toward_move(self):
        log = TransitionLog()
        world = HttpWorld(self.adapter(only({(9, 0): "log"}, Blind)), replace(PLANKS, budget=2))
        result = run_episode(world, certified_vanilla(), log, "p")
        self.assertEqual((result.reason, [(t.action, t.target) for t in log]), ("budget", [("look", None), ("move", "E1")]))

    def test_a_remembered_block_out_of_view_is_walked_back_into_view_so_t3_finishes_on_seeds_1_to_10(self):
        reasons = []
        for seed in range(1, 11):
            url = self.adapter(lambda task, seed=seed: GridWorld(task, seed=seed))
            reasons.append(run_episode(HttpWorld(url, T3), certified_vanilla(), TransitionLog(), "t3").reason)
        self.assertEqual(reasons, ["goal"] * 10)

    def test_b_sends_the_block_to_mine_and_the_craft_grid(self):
        steps = []
        run_episode_b(HttpWorld(self.adapter(seed_1, steps.append), T1), TransitionLog(), "t1", vanilla_plan)
        self.assertEqual([s for s in wire(steps) if s[0] != "move"], [
            MINE, CRAFT_PLANKS, ("craft", "stick", {"planks": 2}), MINE, CRAFT_PLANKS, ("craft", "crafting_table", {"planks": 4}),
            MINE, CRAFT_PLANKS, PLACE_TABLE, ("craft", "wooden_pickaxe", {"planks": 3, "stick": 2}),
        ])

    def test_a_sends_the_block_to_mine_and_the_craft_grid(self):
        steps = []
        complete, _ = scripted(json.dumps(T1_PLAN))
        run_episode_a(HttpWorld(self.adapter(seed_1, steps.append), T1), TransitionLog(), "t1", complete)
        self.assertEqual([s for s in wire(steps) if s[0] != "move"], [
            MINE, CRAFT_PLANKS, ("craft", "crafting_table", {"planks": 4}), MINE, CRAFT_PLANKS, ("craft", "stick", {"planks": 2}),
            MINE, CRAFT_PLANKS, PLACE_TABLE, ("craft", "wooden_pickaxe", {"planks": 3, "stick": 2}),
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
        # The adapter paths, so the live episode takes one move per mine: 13 actions where the grid takes 20.
        self.assertEqual(
            (entry, proven["system"], proven["contradictions"]),
            (grid_entry | {"id": "t1", "seed": None, "reset": "/clear", "actions": 13}, "D", 0),
        )

    def test_cli_replays_a_prior_log_without_writing_it_into_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second, url = Path(tmp) / "first", Path(tmp) / "second", self.adapter()
            live = [sys.executable, "-m", "breach.live", "--url", url, "--task", "T1"]
            subprocess.run([*live, str(first)], cwd=ROOT, check=True, capture_output=True)
            subprocess.run([*live, str(second), "--prior", str(first / "t1.jsonl")], cwd=ROOT, check=True, capture_output=True)
            lines = [len((run / "t1.jsonl").read_text().splitlines()) for run in (first, second)]
            [entry] = json.loads((second / "manifest.json").read_text())["episodes"]
        self.assertEqual(lines, [entry["actions"], entry["actions"]])


if __name__ == "__main__":
    unittest.main()
