import unittest
from dataclasses import replace

from breach.log import TransitionLog
from breach.loop import run_episode
from breach.store import RuleStore
from breach.tasks import H1, T1
from breach.world import VANILLA, GridWorld, Recipe, rules_from_ruleset


def certified_store():
    store = RuleStore()
    for rule in rules_from_ruleset(VANILLA, status="certified"):
        store.add(rule)
    return store


class LoopTests(unittest.TestCase):
    def test_empty_store_issues_zero_crafts(self):
        log = TransitionLog()
        result = run_episode(GridWorld(T1, seed=1), RuleStore(), log, "t1")
        self.assertEqual((result.success, [t for t in log if t.action == "craft"]), (False, []))

    def test_prior_store_reaches_a_wooden_pickaxe_within_budget(self):
        log = TransitionLog()
        result = run_episode(GridWorld(T1, seed=1), certified_store(), log, "t1")
        self.assertEqual((result.success, len(log) == result.actions, log.contradictions()), (True, True, []))

    def test_partial_inventory_skips_the_crafting_table(self):
        log = TransitionLog()
        result = run_episode(GridWorld(H1, seed=2), certified_store(), log, "h1")
        self.assertEqual(
            (result.success, [t.target for t in log if t.action == "craft"]),
            (True, ["stick", "planks", "wooden_pickaxe", "stone_pickaxe"]),
        )

    def test_count_change_aborts_at_the_craft_step(self):
        recipes = dict(VANILLA.recipes)
        recipes["stick"] = Recipe({"planks": 2}, 2, None)
        world = GridWorld(T1, seed=1, ruleset=replace(VANILLA, recipes=recipes), server="grid/stick-count-2")
        log = TransitionLog()
        result = run_episode(world, certified_store(), log, "hc")
        contradiction = log.contradictions()[0]
        after = [t for t in log if t.step > contradiction.step]
        self.assertEqual(
            (result.success, contradiction.target, contradiction.observed, after),
            (False, "stick", {"planks": -2, "stick": 2}, []),
        )


if __name__ == "__main__":
    unittest.main()
