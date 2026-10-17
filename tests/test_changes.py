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

    def test_the_stick_count_goal_uses_the_changed_craft_before_its_last_step(self):
        stick_count = change("stick-count-2")
        rules = rules_from_ruleset(apply(stick_count, VANILLA), status="certified")
        steps = plan(goal_for(stick_count), 1, {}, rules, lambda block: 4)
        self.assertIn("craft:stick", [s.rule_id for s in steps[:-1]])

    def test_a_change_no_other_goal_uses_falls_back_to_its_own_output(self):
        self.assertEqual(goal_for(change("furnace-count-2")), "furnace")

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
        self.assertEqual((formats, len(overrides), over_nine), ([6] * 30, 61, []))

    def test_the_stick_count_pack_takes_any_wood_planks(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_datapack(change("stick-count-2"), Path(tmp))
            files = json_files(tmp)
        self.assertEqual(
            files,
            {
                "data/minecraft/recipes/stick.json": {
                    "type": "minecraft:crafting_shapeless",
                    "ingredients": [{"tag": "minecraft:planks"}] * 2,
                    "result": {"item": "minecraft:stick", "count": 2},
                },
            },
        )

    def test_a_log_drop_pack_writes_one_loot_table_per_overworld_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_datapack(change("log-drop-planks"), Path(tmp))
            files = json_files(tmp)
        planks = {"type": "minecraft:item", "name": "minecraft:oak_planks", "functions": [{"function": "minecraft:set_count", "count": 1}]}
        self.assertEqual(
            files,
            {
                f"data/minecraft/loot_tables/blocks/{wood}_log.json": {"type": "minecraft:block", "pools": [{"rolls": 1, "entries": [planks]}]}
                for wood in ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak")
            },
        )

    def test_a_planks_change_rewrites_every_overworld_planks_recipe_from_its_own_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_datapack(change("planks-count-2"), Path(tmp))
            files = json_files(tmp)
        self.assertEqual(
            files,
            {
                f"data/minecraft/recipes/{wood}_planks.json": {
                    "type": "minecraft:crafting_shapeless",
                    "ingredients": [{"tag": f"minecraft:{wood}_logs"}],
                    "result": {"item": f"minecraft:{wood}_planks", "count": 2},
                }
                for wood in ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak")
            },
        )

    def test_four_logs_in_a_square_also_disable_every_vanilla_wood_recipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_datapack(change("crafting_table-swap-planks-log"), Path(tmp))
            files = json_files(tmp)
        self.assertEqual(
            files,
            {
                "data/minecraft/recipes/crafting_table.json": {
                    "type": "minecraft:crafting_shapeless",
                    "ingredients": [{"tag": "minecraft:logs"}] * 4,
                    "result": {"item": "minecraft:crafting_table", "count": 1},
                },
                **{
                    f"data/minecraft/recipes/{wood}_wood.json": {
                        "type": "minecraft:crafting_shapeless",
                        "ingredients": [{"item": "minecraft:barrier"}] * 4,
                        "result": {"item": f"minecraft:{wood}_wood", "count": 3},
                    }
                    for wood in ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak")
                },
            },
        )

if __name__ == "__main__":
    unittest.main()
