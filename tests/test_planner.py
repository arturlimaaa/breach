import unittest
from collections import Counter
from dataclasses import replace

from breach.planner import Step, plan
from breach.rules import Rule
from breach.store import RuleStore
from breach.world import VANILLA, Recipe, rules_from_ruleset


def certified_store():
    store = RuleStore()
    for rule in rules_from_ruleset(VANILLA, status="certified"):
        store.add(rule)
    return store


def rules_with(**recipes):
    return rules_from_ruleset(replace(VANILLA, recipes={**VANILLA.recipes, **recipes}), status="certified")


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

    def test_a_station_block_on_the_map_spares_making_a_table(self):
        rules, inventory = certified_store().usable("grid/vanilla"), {"planks": 3, "stick": 2}
        made = [[s.target for s in plan("wooden_pickaxe", 1, inventory, rules, lambda block: 1, stations)] for stations in ((), {"crafting_table"})]
        self.assertEqual(made, [["log", "planks", "crafting_table", "wooden_pickaxe"], ["wooden_pickaxe"]])

    def test_hypotheses_are_not_planned_over(self):
        store = RuleStore()
        for rule in rules_from_ruleset(VANILLA, status="hypothesis"):
            store.add(rule)
        self.assertIsNone(plan("planks", 4, {"log": 1}, store.usable("grid/vanilla"), lambda block: 1))

    def test_a_step_from_an_uncertified_rule_is_a_test(self):
        hypothesis = Rule("craft:stick#1", "craft", "stick", {"planks": -2, "stick": 2})
        self.assertEqual(
            plan("stick", 1, {"planks": 2}, [hypothesis], lambda block: 1),
            [Step("craft:stick#1", "craft", "stick", {"planks": -2, "stick": 2}, None, None, test=True)],
        )

    def test_a_tool_that_needs_itself_yields_no_plan(self):
        rules = rules_with(planks=Recipe({"log": 1, "coal": 1}, 4, None))
        self.assertIsNone(plan("wooden_pickaxe", 1, {}, rules, lambda block: 1))

    def test_an_input_spent_on_a_later_inputs_tool_is_made_again(self):
        held = Counter()
        for step in plan("ladder", 1, {}, rules_with(ladder=Recipe({"stick": 7, "coal": 1}, 3)), lambda block: 1):
            held.update(step.delta)
        self.assertEqual({item: n for item, n in held.items() if n < 0}, {})


if __name__ == "__main__":
    unittest.main()
