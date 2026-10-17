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
            ("look", None): "ignored",
        }
        self.assertEqual({key: classify(*key) for key in expected}, expected)


if __name__ == "__main__":
    unittest.main()
