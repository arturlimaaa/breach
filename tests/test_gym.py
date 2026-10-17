import json
import unittest

from breach.changes import apply, enumerate_class
from breach.gym import TOOL, Episode, row
from breach.world import VANILLA

STICK, STICK_2 = {"planks": -2, "stick": 4}, {"planks": -2, "stick": 2}


def episode(change, goal="stick", inventory=None, budget=350):
    return Episode(row(change, goal, seed=1, budget=budget, inventory=inventory))


def args(**fields):
    return json.dumps(fields)


class EpisodeTests(unittest.TestCase):
    def test_a_row_carries_the_prompt_and_the_act_tool_beside_the_world_reset_builds(self):
        r = row("stick-count-2", "wooden_pickaxe", seed=3)
        prompt = r["responses_create_params"]["input"][0]["content"]
        self.assertEqual(
            (r["responses_create_params"]["tools"], r["change"], r["goal"], r["seed"], r["budget"], r["inventory"],
             "Hold 1 wooden_pickaxe within 350 actions" in prompt),
            ([TOOL], "stick-count-2", "wooden_pickaxe", 3, 350, {}, True),
        )

    def test_reset_builds_the_world_the_row_names(self):
        ep = episode("stick-count-2", inventory={"planks": 2})
        change = next(c for c in enumerate_class() if c.id == "stick-count-2")
        obs = json.loads(ep.observation())
        self.assertEqual(
            (ep.world.server, ep.world.ruleset, obs["inventory"], obs["budget"]),
            ("grid/stick-count-2", apply(change, VANILLA), {"planks": 2}, 350),
        )

    def test_a_use_that_departs_from_the_vanilla_rule_and_comes_true_pays_once(self):
        ep = episode("stick-count-2", goal="ladder", inventory={"planks": 4})
        paid = [ep.act(args(action="craft", target="stick", predicted=STICK_2))[1] for _ in range(2)]
        self.assertEqual(paid, [1.0, 0.0])

    def test_a_probe_of_the_swapped_grid_that_comes_true_pays(self):
        ep = episode("stick-swap-planks-log", inventory={"log": 2})
        result, paid = ep.act(args(action="probe", target="stick", grid={"log": 2}, predicted={"stick": 4}))
        self.assertEqual((result["ok"], result["observed"], paid), (True, {"stick": 4}, 1.0))

    def test_a_vanilla_wrong_or_missing_prediction_pays_nothing(self):
        ep = episode("stick-count-2", goal="ladder", inventory={"planks": 6})
        calls = [
            args(action="craft", target="stick", predicted=STICK),
            args(action="craft", target="stick", predicted={"planks": -2, "stick": 3}),
            args(action="craft", target="stick"),
        ]
        self.assertEqual([ep.act(call)[1] for call in calls], [0.0, 0.0, 0.0])

    def test_a_true_prediction_on_an_unchanged_server_pays_nothing(self):
        ep = episode(None, inventory={"planks": 2})
        self.assertEqual(ep.act(args(action="craft", target="stick", predicted=STICK))[1], 0.0)

    def test_a_refused_action_pays_nothing_though_the_vanilla_rule_would_have_run(self):
        ep = episode("stick-add-coal", inventory={"planks": 2})
        result, paid = ep.act(args(action="craft", target="stick", predicted={}))
        self.assertEqual((result["ok"], result["observed"], paid), (False, {}, 0.0))

    def test_bad_arguments_get_an_error_and_take_no_action(self):
        ep = episode("stick-count-2", inventory={"planks": 2})
        bad = ["not json", args(target="stick"), args(action="probe", grid={"planks": "two"}), args(action="move", target=["east"])]
        self.assertEqual(([ep.act(call)[0]["ok"] for call in bad], ep.world.actions), ([False] * 4, 0))


class TurnTests(unittest.TestCase):
    def test_a_turn_that_reaches_the_goal_pays_it_beside_the_revision_and_terminates(self):
        ep = episode("stick-count-2", inventory={"planks": 2})
        results, reward, terminated, truncated = ep.turn([("act", args(action="craft", target="stick", predicted=STICK_2))])
        self.assertEqual((results[0]["observed"], reward, terminated, truncated), (STICK_2, 2.0, True, False))

    def test_a_turn_without_a_call_ends_the_episode(self):
        self.assertEqual(episode("stick-count-2").turn([]), ([], 0.0, True, False))

    def test_the_budget_running_out_truncates(self):
        ep = episode("stick-count-2", budget=1)
        self.assertEqual(ep.turn([("act", args(action="move", target="east"))])[1:], (0.0, False, True))

    def test_a_call_to_another_tool_gets_an_error(self):
        ep = episode("stick-count-2", inventory={"planks": 2})
        self.assertEqual(ep.turn([("mine_faster", "{}")]), ([{"ok": False, "message": "no tool named mine_faster"}], 0.0, False, False))


if __name__ == "__main__":
    unittest.main()
