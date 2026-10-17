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

    def test_a_mine_that_left_its_block_is_judged_on_ok_ness_alone(self):
        self.assertEqual([classify("mine", block, ok=False) for block in ("log", "leaves")], ["tolerant", "tolerant"])


if __name__ == "__main__":
    unittest.main()
