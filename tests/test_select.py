import unittest

from breach.rules import Rule
from breach.select import order_tests


def candidate(n, delta):
    return Rule(
        f"craft:stick#{n}", "craft", "stick", delta,
        status="hypothesis", scope="grid/x", source="induced", revision_of="craft:stick",
    )


class OrderTestsTests(unittest.TestCase):
    def test_the_candidate_whose_grid_is_held_is_probed_first(self):
        swapped = candidate(1, {"log": -2, "stick": 4})
        added = candidate(2, {"planks": -2, "coal": -1, "stick": 4})
        counted = candidate(3, {"planks": -2, "stick": 2})
        self.assertEqual(order_tests([swapped, added, counted], {"planks": 2}), [counted, added, swapped])

    def test_equal_costs_go_first_to_the_grid_that_differs_from_more_candidates(self):
        two = candidate(1, {"planks": -2, "stick": 2})
        three = candidate(2, {"planks": -2, "stick": 3})
        coal = candidate(3, {"planks": -2, "coal": -1, "stick": 4})
        self.assertEqual(order_tests([two, three, coal], {"planks": 2, "coal": 1}), [coal, two, three])


if __name__ == "__main__":
    unittest.main()
