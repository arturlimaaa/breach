import json
import unittest
from dataclasses import fields, replace
from pathlib import Path

from breach.induce import JSON_SCHEMA, induce
from breach.log import Transition
from breach.rules import Rule

SERVER = "grid/stick-count-2"
DEMOTED = Rule("craft:stick", "craft", "stick", {"planks": -2, "stick": 4}, status="demoted", scope=SERVER, source="prior")
COUNTEREXAMPLE = Transition(
    "hc", 7, SERVER, "0a1b2c3d4e5f", "craft", "stick", "craft:stick",
    {"planks": -2, "stick": 4}, {"planks": -2, "stick": 2}, "exact", "mismatch",
)


def revision(delta, **changes):
    """One rule object as a model would echo it: the demoted rule with a new delta."""
    return {**DEMOTED.to_dict(), **changes, "delta": delta}


# Nemotron Nano 30B's two replies in the first live HR (runs/live-hr-1, stick-count-2), verbatim: a call and its retry.
LIVE_HR = json.loads((Path(__file__).parent / "golden" / "live-hr-1-replies.json").read_text(encoding="utf-8"))


def scripted(*replies):
    """Fake `complete` that answers with `replies` in order and records (messages, kwargs) per call."""
    calls = []
    answers = iter(replies)

    def complete(messages, **kwargs):
        calls.append((messages, kwargs))
        return next(answers)

    return complete, calls


def hypothesis(n, delta):
    return Rule(
        f"craft:stick#{n}", "craft", "stick", delta,
        status="hypothesis", scope=SERVER, source="induced", revision_of="craft:stick",
    )


class InduceTests(unittest.TestCase):
    def test_keeps_valid_revisions_and_drops_a_free_text_precondition(self):
        complete, _ = scripted(json.dumps([
            revision({"planks": -2, "stick": 2}),
            revision("inventory[planks] >= 2"),
            revision({"planks": -2, "coal": -1, "stick": 4}),
        ]))
        self.assertEqual(
            induce(DEMOTED, COUNTEREXAMPLE, [COUNTEREXAMPLE], complete=complete),
            [hypothesis(1, {"planks": -2, "stick": 2}), hypothesis(2, {"planks": -2, "coal": -1, "stick": 4})],
        )

    def test_accepts_json_inside_a_code_fence(self):
        complete, _ = scripted("Candidates:\n```json\n" + json.dumps([revision({"planks": -2, "stick": 2})]) + "\n```")
        self.assertEqual(induce(DEMOTED, COUNTEREXAMPLE, [], complete=complete), [hypothesis(1, {"planks": -2, "stick": 2})])

    def test_drops_other_targets_unusable_fields_duplicates_and_anything_past_k(self):
        complete, _ = scripted(json.dumps([
            revision({"planks": -2, "stick": 2}),
            revision({"planks": -2, "stick": 2}),
            revision({"log": -1, "planks": 4}, target="planks"),
            revision({"planks": -2, "stick": 3}, near=["crafting_table"]),
            revision({"planks": -1, "stick": 2}),
            revision({"planks": -3, "stick": 4}),
        ]))
        self.assertEqual(
            induce(DEMOTED, COUNTEREXAMPLE, [], k=2, complete=complete),
            [hypothesis(1, {"planks": -2, "stick": 2}), hypothesis(2, {"planks": -1, "stick": 2})],
        )

    def test_a_reply_that_is_not_json_is_retried_once_with_the_parse_error(self):
        complete, calls = scripted("The stick recipe changed.", json.dumps([revision({"planks": -2, "stick": 2})]))
        result = induce(DEMOTED, COUNTEREXAMPLE, [], complete=complete)
        retry = calls[1][0]
        self.assertEqual(
            (result, [m["role"] for m in retry], retry[1]["content"], "not JSON" in retry[2]["content"]),
            ([hypothesis(1, {"planks": -2, "stick": 2})], ["user", "assistant", "user"], "The stick recipe changed.", True),
        )

    def test_gives_up_after_one_retry(self):
        complete, calls = scripted("not a rule", "still not a rule")
        self.assertEqual((induce(DEMOTED, COUNTEREXAMPLE, [], complete=complete), len(calls)), ([], 2))

    def test_prompt_states_the_observation_the_probe_and_the_items_but_not_moves(self):
        move = Transition("hc", 6, SERVER, "0a1b2c3d4e5f", "move", "east", None, {}, {}, "tolerant", "match")
        complete, calls = scripted(json.dumps([revision({"planks": -2, "stick": 2})]))
        induce(DEMOTED, COUNTEREXAMPLE, [move, COUNTEREXAMPLE], complete=complete)
        prompt = calls[0][0][0]["content"]
        needles = ('observed {"planks": -2, "stick": 2}', "A probe reports the output slot", "Items in play: planks, stick.", "move east")
        self.assertEqual([needle in prompt for needle in needles], [True, True, True, False])

    def test_attributes_the_call_to_the_counterexample_step(self):
        complete, calls = scripted(json.dumps([revision({"planks": -2, "stick": 2})]))
        induce(DEMOTED, COUNTEREXAMPLE, [], complete=complete)
        self.assertEqual(
            calls[0][1],
            {"schema": JSON_SCHEMA, "thinking": True, "episode": "hc", "step": 7, "purpose": "induce"},
        )

    def test_json_schema_requires_every_rule_field(self):
        self.assertEqual(set(JSON_SCHEMA["items"]["required"]), {f.name for f in fields(Rule)})

    def test_refuses_every_candidate_of_the_first_live_hr_call_and_its_retry(self):
        complete, calls = scripted(*LIVE_HR)
        result = induce(DEMOTED, COUNTEREXAMPLE, [], complete=complete)
        feedback = calls[1][0][-1]["content"]
        self.assertEqual((result, [f"item {n}:" in feedback for n in (1, 2, 3)]), ([], [True, True, True]))

    def test_a_craft_consumes_something_produces_its_target_and_names_no_block_but_a_station(self):
        complete, _ = scripted(json.dumps([
            revision({"stick": 2}),
            revision({"planks": -2}),
            revision({"planks": -2, "stick": 2}, near="planks"),
            revision({"planks": -2, "stick": 2}, near="crafting_table"),
            revision({"planks": -2, "stick": 3}, near="furnace"),
            revision({"planks": -1, "stick": 2}, tool="stone_pickaxe"),
        ]))
        self.assertEqual(
            induce(DEMOTED, COUNTEREXAMPLE, [], complete=complete),
            [
                replace(hypothesis(1, {"planks": -2, "stick": 2}), near="crafting_table"),
                replace(hypothesis(2, {"planks": -2, "stick": 3}), near="furnace"),
                replace(hypothesis(3, {"planks": -1, "stick": 2}), tool="stone_pickaxe"),
            ],
        )

    def test_prompt_states_the_change_class_and_every_item_of_the_world(self):
        complete, calls = scripted(json.dumps([revision({"planks": -2, "stick": 2})]))
        induce(DEMOTED, COUNTEREXAMPLE, [], complete=complete)
        prompt = calls[0][0][0]["content"]
        needles = (
            "a recipe's output count, one ingredient added to a recipe, one ingredient swapped for another, or a block's drop changed or removed",
            "Every item in this world: coal, cobblestone, crafting_table, furnace, ladder, log, planks, stick, stone, stone_pickaxe, torch, wooden_pickaxe.",
        )
        self.assertEqual([needle in prompt for needle in needles], [True, True])

    def test_prompt_states_what_a_craft_candidate_must_look_like(self):
        complete, calls = scripted(json.dumps([revision({"planks": -2, "stick": 2})]))
        induce(DEMOTED, COUNTEREXAMPLE, [], complete=complete)
        prompt = calls[0][0][0]["content"]
        needles = ("every item it consumes as a negative count and stick as a positive count", 'near is null, "crafting_table" or "furnace"')
        self.assertEqual([needle in prompt for needle in needles], [True, True])


if __name__ == "__main__":
    unittest.main()
