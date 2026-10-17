import unittest

from breach.verify import classify


class ClassifyTests(unittest.TestCase):
    def test_crafts_and_deterministic_mines_are_exact_moves_tolerant_the_rest_ignored(self):
        expected = {
            ("craft", "stick"): "exact",
            ("craft", "furnace"): "exact",
            ("mine", "log"): "exact",
            ("mine", "stone"): "exact",
            ("mine", "coal_ore"): "exact",
            ("mine", "leaves"): "ignored",
            ("mine", None): "ignored",
            ("move", "east"): "tolerant",
            ("probe", "stick"): "ignored",
            ("place", "crafting_table"): "tolerant",
            ("look", None): "ignored",
        }
        self.assertEqual({key: classify(*key) for key in expected}, expected)

    def test_a_step_the_world_refused_before_acting_is_judged_on_ok_ness_alone(self):
        self.assertEqual([classify(action, "log", executed=False) for action in ("craft", "mine", "probe")], ["tolerant"] * 3)

    def test_a_mine_whose_block_stayed_is_judged_on_ok_ness_and_a_removed_block_that_yielded_nothing_stays_exact(self):
        outputs = ({"block_removed": False, "collected": {}}, {"block_removed": True, "collected": {}})
        self.assertEqual([classify("mine", "log", output=output) for output in outputs], ["tolerant", "exact"])


if __name__ == "__main__":
    unittest.main()
