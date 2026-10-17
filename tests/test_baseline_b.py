import unittest
from collections import Counter
from dataclasses import replace
from itertools import pairwise

from breach.baseline_b import COOLDOWN, default_choose, immediate_repeat_rate, run_episode_b
from breach.log import Transition, TransitionLog
from breach.planner import plan
from breach.tasks import T1, T2
from breach.world import VANILLA, GridWorld, Recipe, Task, rules_from_ruleset


def vanilla_plan(state):
    """Fake Nemotron: the task goal as objective and the vanilla ingredient tree as targets."""
    targets = Counter()
    for step in plan(state["goal"], state["count"], {}, rules_from_ruleset(VANILLA, status="certified"), lambda block: 1):
        targets.update({item: n for item, n in step.delta.items() if n > 0})
    return {"objective": state["goal"], "targets": dict(targets)}


def changed(item, recipe):
    return replace(VANILLA, recipes={**VANILLA.recipes, item: recipe})


def stick_count_2_world():
    return GridWorld(T1, seed=1, ruleset=changed("stick", Recipe({"planks": 2}, 2, None)), server="grid/stick-count-2")


class BaselineBTests(unittest.TestCase):
    def test_completes_vanilla_t1_within_budget_with_one_planner_call(self):
        log = TransitionLog()
        result = run_episode_b(GridWorld(T1, seed=1), log, "t1", vanilla_plan)
        self.assertEqual(
            (result.success, len(log) == result.actions, log.contradictions(), result.planner_calls),
            (True, True, [], 1),
        )

    def test_keeps_choosing_through_a_stick_count_change(self):
        log = TransitionLog()
        result = run_episode_b(stick_count_2_world(), log, "hc", vanilla_plan)
        self.assertEqual((result.reason, {t.rule_id for t in log.contradictions()}), ("goal", {"bundled:craft:stick"}))

    def test_retries_a_lying_craft_after_each_cooldown_until_the_budget(self):
        ruleset = changed("stone_pickaxe", Recipe({"cobblestone": 3, "stick": 2, "coal": 1}, 1))
        log = TransitionLog()
        result = run_episode_b(GridWorld(T2, seed=1, ruleset=ruleset, server="grid/stone-pickaxe-add-coal"), log, "hc", vanilla_plan)
        attempts = [t.step for t in log if (t.action, t.target) == ("craft", "stone_pickaxe")]
        self.assertEqual(
            (result.reason, len(attempts) > 1, [b - a for a, b in pairwise(attempts) if b - a <= COOLDOWN]),
            ("budget", True, []),
        )

    def test_replans_after_three_consecutive_failures(self):
        task = replace(T1, budget=4, inventory={"log": 1, "planks": 4, "stick": 2, "crafting_table": 1})
        result = run_episode_b(GridWorld(task, seed=1, ruleset=replace(VANILLA, recipes={})), TransitionLog(), "x", vanilla_plan)
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
