import json
import unittest

from breach.baseline_a import EpisodeResultA, run_episode_a
from breach.baseline_b import immediate_repeat_rate
from breach.changes import apply, benchmark
from breach.log import TransitionLog
from breach.planner import plan
from breach.tasks import T1
from breach.world import VANILLA, GridWorld, Task, rules_from_ruleset
from tests.test_induce import scripted

T1_PLAN = [
    "mine log", "craft planks x4", "craft crafting_table x1",
    "mine log", "craft planks x4", "craft stick x4",
    "mine log", "craft planks x4", "craft wooden_pickaxe x1",
]
LADDER = Task("hs", "ladder")
PROMPT = """Plan a task in a 2D grid version of Minecraft: hold 1 wooden_pickaxe within 150 actions.

Options and the inventory change each one causes, negative consumed and positive produced:
- "craft planks x4": {"log": -1, "planks": 4}
- "craft stick x4": {"planks": -2, "stick": 4}
- "craft crafting_table x1": {"planks": -4, "crafting_table": 1}
- "craft torch x4": {"coal": -1, "stick": -1, "torch": 4}
- "craft wooden_pickaxe x1": {"planks": -3, "stick": -2, "wooden_pickaxe": 1}, needs a crafting_table held
- "craft stone_pickaxe x1": {"cobblestone": -3, "stick": -2, "stone_pickaxe": 1}, needs a crafting_table held
- "craft furnace x1": {"cobblestone": -8, "furnace": 1}, needs a crafting_table held
- "craft ladder x3": {"stick": -7, "ladder": 3}, needs a crafting_table held
- "mine log": {"log": 1}
- "mine stone": {"cobblestone": 1}, needs a wooden_pickaxe held
- "mine coal_ore": {"coal": 1}, needs a wooden_pickaxe held
- "move toward <block>": one step toward the nearest <block> seen before and now out of view
- "explore": one step along an outward square spiral
- "wait": no action
A craft needs its inputs held. A mine needs the block in view and first walks to the nearest one. Every craft, mine, and step costs one action.

Actions used: 0 of 150. Position: (0, 0).
Inventory: {}
In view: log at (-3, 0), log at (1, 2), log at (2, -1), stone at (4, 3)
Available now: ["mine log", "explore", "wait"]
Reply with only a JSON array of options to run in order."""


def benchmarked(change_id):
    """The benchmark's change `change_id` and the goal it is benchmarked on."""
    return next((c, g) for c, g in benchmark() if c.id == change_id)


def change_world(change_id, task):
    change, _ = benchmarked(change_id)
    return GridWorld(task, seed=1, ruleset=apply(change, VANILLA), server=f"grid/{change_id}")


def vanilla_replanner(world):
    """Fake Nemotron that knows only vanilla: every call answers the vanilla plan from the world's inventory."""
    calls = []
    rules = rules_from_ruleset(VANILLA, status="certified")

    def complete(messages, **kwargs):
        calls.append((messages, kwargs))
        steps = plan(world.task.goal, world.task.count, world.observe().inventory, rules, lambda block: 1)
        return json.dumps([f"craft {s.target} x{s.delta[s.target]}" if s.action == "craft" else f"mine {s.target}" for s in steps])

    return complete, calls


class BaselineATests(unittest.TestCase):
    def test_finishes_vanilla_t1_from_one_correct_plan_logging_each_craft_by_its_bundled_rule(self):
        log = TransitionLog()
        complete, _ = scripted(json.dumps(T1_PLAN))
        result = run_episode_a(GridWorld(T1, seed=1), log, "t1", complete)
        crafts = [(t.target, t.cls, t.rule_id, t.test) for t in log if t.action == "craft"]
        targets = ["planks", "crafting_table", "planks", "stick", "planks", "wooden_pickaxe"]
        expected = [(target, "exact", f"bundled:craft:{target}", False) for target in targets]
        self.assertEqual((result, crafts, log.contradictions()), (EpisodeResultA(True, len(log), 1, "goal"), expected, []))

    def test_a_vanilla_replanner_repeats_the_changed_craft_and_calls_again(self):
        world = change_world("stick-count-2", LADDER)
        complete, _ = vanilla_replanner(world)
        log = TransitionLog()
        result = run_episode_a(world, log, "hs", complete)
        self.assertEqual(
            (result.success, {t.rule_id for t in log.contradictions()}, immediate_repeat_rate(log), result.model_calls),
            (True, {"bundled:craft:stick"}, 0.5, 3),
        )

    def test_each_failure_is_appended_to_one_conversation_and_asked_again(self):
        task = Task("x", "stone_pickaxe", budget=2, inventory={"cobblestone": 3, "stick": 2, "crafting_table": 1})
        replies = [
            json.dumps(["craft stone_pickaxe x1"]), json.dumps(["wait"]), json.dumps(["craft furnace x1"]),
            "Mine a log first.", json.dumps({"plan": ["wait"]}), json.dumps(["craft stone_pickaxe x1"]),
        ]
        complete, calls = scripted(*replies)
        result = run_episode_a(change_world("stone_pickaxe-add-coal", task), TransitionLog(), "x", complete)
        conversation = calls[-1][0]
        said = [m["content"] for m in conversation if m["role"] == "assistant"]
        heads = [m["content"].splitlines()[0] for m in conversation[2::2]]
        self.assertEqual(
            (result, [kwargs["step"] for _, kwargs in calls], said, heads),
            (
                EpisodeResultA(False, 2, 6, "budget"),
                [0, 1, 1, 1, 1, 1],
                replies[:5],
                [
                    "\"craft stone_pickaxe x1\" failed: missing {'coal': 1}.",
                    "The plan ran out before the goal.",
                    '"craft furnace x1" is not available now.',
                    "No plan in that reply: Expecting value: line 1 column 1 (char 0).",
                    "No plan in that reply: a plan is a JSON array of option strings.",
                ],
            ),
        )

    def test_calls_the_model_on_every_task_including_a_second_task_on_the_same_server(self):
        _, goal = benchmarked("stick-count-2")
        firsts = []
        for task in (Task("hc", goal), LADDER):
            world = change_world("stick-count-2", task)
            complete, calls = vanilla_replanner(world)
            result = run_episode_a(world, TransitionLog(), task.task_id, complete)
            firsts.append((result.model_calls >= 1, len(calls[0][0])))
        self.assertEqual(firsts, [(True, 1), (True, 1)])

    def test_stops_after_eight_calls_with_calls_exhausted(self):
        complete, calls = scripted(*[json.dumps(["craft wooden_pickaxe x1"])] * 8)
        result = run_episode_a(GridWorld(T1, seed=1), TransitionLog(), "t1", complete)
        self.assertEqual((result, len(calls)), (EpisodeResultA(False, 0, 8, "calls exhausted"), 8))

    def test_accepts_a_plan_inside_a_code_fence(self):
        complete, _ = scripted("```json\n" + json.dumps(T1_PLAN) + "\n```")
        result = run_episode_a(GridWorld(T1, seed=1), TransitionLog(), "t1", complete)
        self.assertEqual((result.success, result.model_calls), (True, 1))

    def test_prompt_carries_the_task_the_bundled_table_as_menu_keys_and_the_observation(self):
        world = GridWorld(T1, seed=1)
        world.blocks = {(1, 2): "log", (2, -1): "log", (-3, 0): "log", (4, 3): "stone"}
        complete, calls = scripted(json.dumps(T1_PLAN))
        run_episode_a(world, TransitionLog(), "t1", complete)
        self.assertEqual(calls, [([{"role": "user", "content": PROMPT}], {"episode": "t1", "step": 0, "purpose": "plan", "thinking": False})])


if __name__ == "__main__":
    unittest.main()
