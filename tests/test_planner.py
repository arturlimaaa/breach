import unittest

from breach.planner import plan
from breach.store import RuleStore
from breach.world import VANILLA, rules_from_ruleset


def certified_store():
    store = RuleStore()
    for rule in rules_from_ruleset(VANILLA, status="certified"):
        store.add(rule)
    return store


class PlannerTests(unittest.TestCase):
    def test_empty_store_yields_no_plan(self):
        self.assertIsNone(plan("wooden_pickaxe", 1, {}, RuleStore().usable("grid/vanilla"), lambda block: 1))

    def test_certified_store_plans_a_wooden_pickaxe_with_three_logs(self):
        steps = plan("wooden_pickaxe", 1, {}, certified_store().usable("grid/vanilla"), lambda block: 1)
        self.assertEqual(
            [(s.action, s.target) for s in steps],
            [
                ("mine", "log"), ("craft", "planks"), ("craft", "crafting_table"),
                ("mine", "log"), ("craft", "planks"), ("craft", "stick"),
                ("mine", "log"), ("craft", "planks"), ("craft", "wooden_pickaxe"),
            ],
        )

    def test_satisfied_preconditions_are_skipped(self):
        inventory = {"planks": 4, "crafting_table": 1, "wooden_pickaxe": 1, "cobblestone": 3}
        steps = plan("stone_pickaxe", 1, inventory, certified_store().usable("grid/vanilla"), lambda block: 1)
        self.assertEqual([(s.action, s.target) for s in steps], [("craft", "stick"), ("craft", "stone_pickaxe")])

    def test_hypotheses_are_not_planned_over(self):
        store = RuleStore()
        for rule in rules_from_ruleset(VANILLA, status="hypothesis"):
            store.add(rule)
        self.assertIsNone(plan("planks", 4, {"log": 1}, store.usable("grid/vanilla"), lambda block: 1))


if __name__ == "__main__":
    unittest.main()
