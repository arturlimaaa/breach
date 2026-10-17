import unittest
from dataclasses import replace
from itertools import pairwise

from breach.baseline_b import COOLDOWN, default_choose, immediate_repeat_rate, menu, run_episode_b, vanilla_plan
from breach.certify import replay
from breach.log import Transition, TransitionLog
from breach.tasks import T1, T2
from breach.world import VANILLA, GridWorld, Observation, Recipe, Task, rules_from_ruleset
from tests.test_loop import GOLDEN, Hurt, Slippery


def changed(item, recipe):
    return replace(VANILLA, recipes={**VANILLA.recipes, item: recipe})


def stick_count_2_world(world=GridWorld):
    return world(T1, seed=1, ruleset=changed("stick", Recipe({"planks": 2}, 2, None)), server="grid/stick-count-2")


class BaselineBTests(unittest.TestCase):
    def test_completes_vanilla_t1_within_budget_with_one_planner_call(self):
        log = TransitionLog()
        result = run_episode_b(GridWorld(T1, seed=1), log, "t1", vanilla_plan)
        mined = {(t.target, t.cls) for t in log if t.action == "mine"}
        self.assertEqual(
            (result.success, len(log) == result.actions, log.contradictions(), result.planner_calls, mined),
            (True, True, [], 1, {("log", "exact")}),
        )

    def test_t1_seed_1_logs_the_golden_transitions(self):
        log = TransitionLog()
        run_episode_b(GridWorld(T1, seed=1), log, "t1", vanilla_plan)
        self.assertEqual(list(log), list(TransitionLog(GOLDEN / "b-t1-s1.jsonl")))

    def test_a_station_craft_needs_a_table_in_reach_and_a_held_table_can_be_placed(self):
        held = {"planks": 3, "stick": 2, "crafting_table": 1}
        offered = []
        for visible in ([], [(1, 1, "crafting_table")]):
            obs = Observation("grid/vanilla", (0, 0), held, visible, 0, 150, False, False)
            offered.append(sorted(key for key in menu(rules_from_ruleset(VANILLA), obs, {}) if key.startswith(("craft wooden", "place"))))
        self.assertEqual(offered, [["place crafting_table"], ["craft wooden_pickaxe x1"]])

    def test_placing_ranks_as_the_waiting_craft_furthest_along_and_a_placed_table_counts_as_held(self):
        held = {"planks": 3, "stick": 2, "cobblestone": 8, "crafting_table": 1, "wooden_pickaxe": 1}
        obs = Observation("grid/vanilla", (0, 0), held, [], 0, 300, False, False)
        _, tag = menu(rules_from_ruleset(VANILLA), obs, {})["place crafting_table"]
        state = {"inventory": {"planks": 7, "stick": 2}, "placed": ["crafting_table"], "objective": "furnace",
                 "targets": {"crafting_table": 1, "wooden_pickaxe": 1}}
        rules = {r.target: r for r in rules_from_ruleset(VANILLA)}
        options = {"craft crafting_table x1": ("craft", rules["crafting_table"]), "craft wooden_pickaxe x1": ("craft", rules["wooden_pickaxe"])}
        self.assertEqual((tag.target, default_choose(state, options)), ("furnace", "craft wooden_pickaxe x1"))

    def test_a_mine_that_left_its_block_is_logged_tolerant(self):
        log = TransitionLog()
        result = run_episode_b(Slippery(Task("p", "planks"), seed=1), log, "p", vanilla_plan)
        self.assertEqual(
            (result.success, [(t.cls, t.verdict) for t in log if t.action == "mine"][:1], log.contradictions()),
            (True, [("tolerant", "mismatch")], []),
        )

    def test_budget_exhausted_on_arrival_logs_no_phantom_step(self):
        full = TransitionLog()
        run_episode_b(GridWorld(T1, seed=1), full, "t1", vanilla_plan)
        arrival = next(t.step for t in full if t.action == "mine") - 1
        log = TransitionLog()
        result = run_episode_b(GridWorld(replace(T1, budget=arrival), seed=1), log, "t1", vanilla_plan)
        self.assertEqual((len(log), log.contradictions(), result.reason), (result.actions, [], "budget"))

    def test_an_event_quarantines_the_step_and_the_log_replays(self):
        log = TransitionLog()
        result = run_episode_b(stick_count_2_world(Hurt), log, "hq", vanilla_plan)
        self.assertEqual(
            (result.reason, log.contradictions(), {t.verdict for t in log if t.target == "stick"}, replay(log)),
            ("goal", [], {"quarantined"}, [t.verdict for t in log]),
        )

    def test_keeps_choosing_through_a_stick_count_change(self):
        log = TransitionLog()
        result = run_episode_b(stick_count_2_world(), log, "hc", vanilla_plan)
        self.assertEqual((result.reason, {t.rule_id for t in log.contradictions()}), ("goal", {"bundled:craft:stick"}))

    def test_retries_a_lying_craft_after_each_cooldown_until_the_budget(self):
        ruleset = changed("stone_pickaxe", Recipe({"cobblestone": 3, "stick": 2, "coal": 1}, 1))
        log = TransitionLog()
        result = run_episode_b(GridWorld(T2, seed=1, ruleset=ruleset, server="grid/stone-pickaxe-add-coal"), log, "hc", vanilla_plan)
        attempts = [t for t in log if (t.action, t.target) == ("craft", "stone_pickaxe")]
        gaps = [b.step - a.step for a, b in pairwise(attempts)]
        self.assertEqual(
            (result.reason, len(attempts) > 1, [g for g in gaps if g <= COOLDOWN], {t.ok for t in attempts}),
            ("budget", True, [], {False}),
        )

    def test_replans_after_three_consecutive_failures(self):
        task = replace(T1, budget=4, inventory={"log": 1, "planks": 4, "stick": 2})
        world = GridWorld(task, seed=1, ruleset=replace(VANILLA, recipes={}))
        world.blocks[(0, 0)] = "crafting_table"
        result = run_episode_b(world, TransitionLog(), "x", vanilla_plan)
        self.assertEqual(result.planner_calls, 2)

    def test_moves_toward_a_remembered_block_out_of_view(self):
        world = GridWorld(Task("p", "planks"), seed=1)
        world.blocks = {(-8, 0): "log"}
        chosen = []

        def explore_first(state, options):
            chosen.append("explore" if not chosen else default_choose(state, options))
            return chosen[-1]

        run_episode_b(world, TransitionLog(), "p", vanilla_plan, explore_first)
        self.assertEqual(chosen, ["explore", "move toward log", "mine log", "craft planks x4"])

    def test_does_not_repeat_every_count_mismatch_immediately(self):
        log = TransitionLog()
        run_episode_b(stick_count_2_world(), log, "hc", vanilla_plan)
        self.assertLess(immediate_repeat_rate(log), 1.0)

    def test_repeat_rate_of_a_log_without_mismatches_is_zero(self):
        log = TransitionLog()
        run_episode_b(GridWorld(T1, seed=1), log, "t1", vanilla_plan)
        self.assertEqual(immediate_repeat_rate(log), 0.0)

    def test_the_next_episode_is_not_a_repeat(self):
        log = TransitionLog()
        for episode in ("a", "b"):
            log.append(Transition(episode, 1, "grid/x", "h", "craft", "stick", "bundled:craft:stick", {"stick": 4}, {"stick": 2}, "exact", "mismatch"))
        self.assertEqual(immediate_repeat_rate(log), 0.0)


if __name__ == "__main__":
    unittest.main()
