import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from breach.changes import Change, apply, enumerate_class, goal_for, load_ruleset, write_datapack, write_ruleset
from breach.planner import plan
from breach.world import VANILLA, Recipe, rules_from_ruleset


def change(change_id):
    return next(c for c in enumerate_class() if c.id == change_id)


def json_files(root):
    return {p.relative_to(root).as_posix(): json.loads(p.read_text()) for p in Path(root).rglob("*.json")}


class ChangeClassTests(unittest.TestCase):
    def test_vanilla_class_holds_three_changes_per_recipe_and_two_per_block(self):
        self.assertEqual(
            [c.id for c in enumerate_class()],
            [
                "planks-count-2", "planks-add-coal", "planks-swap-log-stick",
                "stick-count-2", "stick-add-coal", "stick-swap-planks-log",
                "crafting_table-count-2", "crafting_table-add-coal", "crafting_table-swap-planks-log",
                "torch-count-2", "torch-add-cobblestone", "torch-swap-coal-log",
                "wooden_pickaxe-count-2", "wooden_pickaxe-add-coal", "wooden_pickaxe-swap-planks-log",
                "stone_pickaxe-count-2", "stone_pickaxe-add-coal", "stone_pickaxe-swap-cobblestone-log",
                "furnace-count-2", "furnace-add-coal", "furnace-swap-cobblestone-log",
                "ladder-count-2", "ladder-add-coal", "ladder-swap-stick-log",
                "log-drop-planks", "log-drop-nothing",
                "stone-drop-stone", "stone-drop-nothing",
                "coal_ore-drop-cobblestone", "coal_ore-drop-nothing",
            ],
        )

    def test_every_change_round_trips_through_json(self):
        changes = enumerate_class()
        self.assertEqual([Change.parse(json.loads(json.dumps(c.to_dict()))) for c in changes], changes)

    def test_parse_rejects_a_value_that_does_not_fit_the_kind(self):
        with self.assertRaises(ValueError):
            Change.parse({"id": "stick-swap", "kind": "swap_ingredient", "recipe": "stick", "value": {"planks": 2}})

    def test_apply_rewrites_exactly_the_changed_rule(self):
        recipes, drops = VANILLA.recipes, VANILLA.drops
        self.assertEqual(
            [apply(change(i), VANILLA) for i in ("stick-count-2", "torch-add-cobblestone", "stick-swap-planks-log", "log-drop-planks")],
            [
                replace(VANILLA, recipes={**recipes, "stick": Recipe({"planks": 2}, 2, None)}),
                replace(VANILLA, recipes={**recipes, "torch": Recipe({"coal": 1, "stick": 1, "cobblestone": 1}, 4, None)}),
                replace(VANILLA, recipes={**recipes, "stick": Recipe({"log": 2}, 4, None)}),
                replace(VANILLA, drops={**drops, "log": {"planks": 1}}),
            ],
        )

    def test_apply_leaves_vanilla_untouched(self):
        before = copy.deepcopy(VANILLA)
        for c in enumerate_class():
            apply(c, VANILLA)
        self.assertEqual(VANILLA, before)

    def test_the_stick_count_goal_plans_through_the_changed_craft(self):
        stick_count = change("stick-count-2")
        rules = rules_from_ruleset(apply(stick_count, VANILLA), status="certified")
        steps = plan(goal_for(stick_count), 1, {}, rules, lambda block: 4)
        self.assertIn("craft:stick", [s.rule_id for s in steps])

    def test_a_log_that_drops_nothing_leaves_no_goal(self):
        self.assertIsNone(goal_for(change("log-drop-nothing")))

    def test_every_changed_ruleset_round_trips_through_json(self):
        changes = enumerate_class()
        with tempfile.TemporaryDirectory() as tmp:
            for c in changes:
                write_ruleset(c, Path(tmp) / c.id / "ruleset.json")
            loaded = [load_ruleset(Path(tmp) / c.id / "ruleset.json") for c in changes]
        self.assertEqual(loaded, [apply(c, VANILLA) for c in changes])

    def test_every_datapack_parses_as_pack_format_6_within_nine_ingredients(self):
        with tempfile.TemporaryDirectory() as tmp:
            for c in enumerate_class():
                write_datapack(c, Path(tmp) / c.id)
            formats = [json.loads(p.read_text())["pack"]["pack_format"] for p in Path(tmp).glob("*/pack.mcmeta")]
            overrides = json_files(tmp)
        over_nine = [name for name, data in overrides.items() if len(data.get("ingredients", ())) > 9]
        self.assertEqual((formats, len(overrides), over_nine), ([6] * 30, 30, []))

    def test_datapacks_override_the_oak_recipe_and_loot_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in ("planks-count-2", "log-drop-planks", "log-drop-nothing"):
                write_datapack(change(i), Path(tmp) / i)
            files = json_files(tmp)
        planks = {"type": "minecraft:item", "name": "minecraft:oak_planks", "functions": [{"function": "minecraft:set_count", "count": 1}]}
        self.assertEqual(
            files,
            {
                "planks-count-2/data/minecraft/recipes/oak_planks.json": {
                    "type": "minecraft:crafting_shapeless",
                    "ingredients": [{"item": "minecraft:oak_log"}],
                    "result": {"item": "minecraft:oak_planks", "count": 2},
                },
                "log-drop-planks/data/minecraft/loot_tables/blocks/oak_log.json": {
                    "type": "minecraft:block",
                    "pools": [{"rolls": 1, "entries": [planks]}],
                },
                "log-drop-nothing/data/minecraft/loot_tables/blocks/oak_log.json": {"type": "minecraft:block", "pools": []},
            },
        )


if __name__ == "__main__":
    unittest.main()
