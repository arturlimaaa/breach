import unittest

from breach.rules import Rule


class RuleTests(unittest.TestCase):
    def test_round_trips_through_json_without_loss(self):
        rule = Rule.parse(
            {
                "rule_id": "craft:stick",
                "action": "craft",
                "target": "stick",
                "delta": {"planks": -2, "stick": 4},
                "tool": None,
                "near": "crafting_table",
                "cls": "exact",
                "status": "certified",
                "scope": "global",
                "source": "prior",
                "evidence": ["t1/3"],
                "revision_of": None,
            }
        )
        self.assertEqual(Rule.parse(rule.to_dict()), rule)

    def test_rejects_free_text_preconditions(self):
        with self.assertRaises(ValueError):
            Rule.parse(
                {
                    "rule_id": "craft:stick",
                    "action": "craft",
                    "target": "stick",
                    "delta": "inventory[planks] >= 2",
                }
            )

    def test_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            Rule.parse(
                {
                    "rule_id": "craft:stick",
                    "action": "craft",
                    "target": "stick",
                    "delta": {"planks": -2, "stick": 4},
                    "status": "maybe",
                }
            )


if __name__ == "__main__":
    unittest.main()
