import unittest
from dataclasses import replace

from breach.tasks import T1
from breach.world import VANILLA, Action, GridWorld, Recipe


class GridWorldTests(unittest.TestCase):
    def test_same_seed_loads_identically(self):
        self.assertEqual(GridWorld(T1, seed=7).blocks, GridWorld(T1, seed=7).blocks)
        self.assertNotEqual(GridWorld(T1, seed=7).blocks, GridWorld(T1, seed=8).blocks)

    def test_count_ruleset_changes_craft_output(self):
        recipes = dict(VANILLA.recipes)
        recipes["stick"] = Recipe({"planks": 2}, 2, None)
        world = GridWorld(T1, seed=7, ruleset=replace(VANILLA, recipes=recipes), inventory={"planks": 2})
        result = world.step(Action("craft", "stick"))
        self.assertEqual((result.ok, world.inventory["stick"]), (True, 2))

    def test_probe_reports_output_without_consuming(self):
        world = GridWorld(T1, seed=7, inventory={"planks": 2})
        result = world.step(Action("probe", "stick", grid={"planks": 2}))
        self.assertEqual((result.output, world.inventory["planks"]), ({"stick": 4}, 2))

    def test_probe_of_a_wrong_grid_shows_an_empty_slot(self):
        world = GridWorld(T1, seed=7, inventory={"planks": 2, "coal": 1})
        self.assertEqual(world.step(Action("probe", "stick", grid={"planks": 2, "coal": 1})).output, {})

    def test_probe_of_a_grid_not_held_fails_without_showing_a_slot(self):
        world = GridWorld(T1, seed=7, inventory={"planks": 1})
        result = world.step(Action("probe", "stick", grid={"planks": 2}))
        self.assertEqual((result.ok, result.output, dict(world.inventory)), (False, None, {"planks": 1}))

    def test_look_reports_the_nearest_block_per_heading_and_omits_empty_headings(self):
        world = GridWorld(T1, seed=7, inventory={"planks": 2})
        world.blocks = {(-2, 30): "log", (1, 40): "stone", (20, -21): "log"}
        result = world.step(Action("look"))
        self.assertEqual(
            (result.ok, result.output, dict(world.inventory), world.actions),
            (True, {"S": {"block": "log", "distance": 30}, "NE": {"block": "log", "distance": 21}}, {"planks": 2}, 1),
        )

    def test_a_look_for_a_block_type_reports_the_nearest_of_that_type_behind_other_blocks(self):
        world = GridWorld(T1, seed=7)
        world.blocks = {(-2, 30): "log", (1, 40): "stone", (20, -21): "log"}
        self.assertEqual(world.step(Action("look", "stone")).output, {"S": {"block": "stone", "distance": 40}})

    def test_only_a_step_the_world_refused_before_acting_is_not_executed(self):
        coal_sticks = replace(VANILLA, recipes={**VANILLA.recipes, "stick": Recipe({"planks": 2, "coal": 1}, 4, None)})
        pickaxe = {"planks": 3, "stick": 2}
        cases = [
            (GridWorld(T1, seed=7), Action("mine", "log")),
            (GridWorld(T1, seed=7), Action("place", "crafting_table")),
            (GridWorld(T1, seed=7, inventory={"planks": 1}), Action("craft", "stick", grid={"planks": 2})),
            (GridWorld(T1, seed=7, inventory={"planks": 1}), Action("probe", "stick", grid={"planks": 2})),
            (GridWorld(T1, seed=7, inventory=pickaxe), Action("craft", "wooden_pickaxe", grid=pickaxe)),
            (GridWorld(T1, seed=7, ruleset=coal_sticks, inventory={"planks": 2}), Action("craft", "stick", grid={"planks": 2})),
            (GridWorld(T1, seed=7, inventory={"planks": 2}), Action("craft", "stick", grid={"planks": 2})),
        ]
        outcomes = []
        for world, action in cases:
            world.blocks = {}
            result = world.step(action)
            outcomes.append((result.ok, result.executed))
        self.assertEqual(outcomes, [(False, False)] * 5 + [(False, True), (True, True)])

    def test_place_puts_a_held_block_on_the_bots_cell_then_on_a_free_neighbour(self):
        world = GridWorld(T1, seed=7, inventory={"crafting_table": 2})
        world.blocks = {(1, 0): "log"}
        placed = [world.step(Action("place", "crafting_table")).ok for _ in range(3)]
        self.assertEqual(
            (placed, world.blocks, world.inventory["crafting_table"]),
            ([True, True, False], {(1, 0): "log", (0, 0): "crafting_table", (-1, 0): "crafting_table"}, 0),
        )

    def test_a_3x3_craft_and_its_probe_need_a_table_block_within_one_cell_not_one_held(self):
        outcomes = []
        for table in (None, (2, 0), (1, 1)):
            world = GridWorld(T1, seed=7, inventory={"planks": 3, "stick": 2, "crafting_table": 1})
            world.blocks = {} if table is None else {table: "crafting_table"}
            shown = world.step(Action("probe", "wooden_pickaxe", grid={"planks": 3, "stick": 2})).output
            outcomes.append((shown, world.step(Action("craft", "wooden_pickaxe")).ok))
        self.assertEqual(outcomes, [(None, False), (None, False), ({"wooden_pickaxe": 1}, True)])

    def test_stone_needs_a_pickaxe(self):
        world = GridWorld(T1, seed=7)
        world.position = next(p for p, b in world.blocks.items() if b == "stone")
        self.assertFalse(world.step(Action("mine")).ok)

    def test_visible_blocks_are_within_radius_at_spawn(self):
        obs = GridWorld(T1, seed=7).observe()
        self.assertTrue(obs.visible and all(abs(x) + abs(z) <= 8 for x, z, _ in obs.visible))


if __name__ == "__main__":
    unittest.main()
