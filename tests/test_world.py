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

    def test_stone_needs_a_pickaxe(self):
        world = GridWorld(T1, seed=7)
        world.position = next(p for p, b in world.blocks.items() if b == "stone")
        self.assertFalse(world.step(Action("mine")).ok)

    def test_visible_blocks_are_within_radius_at_spawn(self):
        obs = GridWorld(T1, seed=7).observe()
        self.assertTrue(obs.visible and all(abs(x) + abs(z) <= 8 for x, z, _ in obs.visible))


if __name__ == "__main__":
    unittest.main()
