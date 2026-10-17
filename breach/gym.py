"""The grid world as a NeMo Gym environment on its Gymnasium protocol: /reset builds the world a dataset row names, /step
plays the policy's `act` calls, and gymnasium_agent sums the step rewards into the rollout's reward.
https://docs.nvidia.com/nemo/gym/v0.7.0/environment-tutorials/resources-server-apis

A step pays 1 when the episode ends holding the goal, and 1 the first time a predicted change that departs from the
vanilla rules comes true: a revised rule whose probe or use matched. BreachGym needs nemo-gym, which needs Python
3.13.14 or later; the rest is the standard library. Its smoke test runs where nemo-gym is installed:
    <venv>/bin/python -m unittest tests.nemo_gym_smoke
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict
from importlib.util import find_spec
from typing import Any

from .changes import apply, enumerate_class
from .log import diff
from .world import VANILLA, Action, GridWorld, StepResult, Task, rules_from_ruleset

COUNTS = {"type": "object", "additionalProperties": {"type": "integer"}}
TOOL = {
    "type": "function",
    "name": "act",
    "description": "Take one action in the world. The result shows what it changed and what is in view.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["move", "look", "mine", "craft", "probe"]},
            "target": {"type": "string", "description": "move: east, west, north or south. craft and probe: the item to make."},
            "grid": {**COUNTS, "description": "probe: the items to place in the crafting grid."},
            "predicted": {**COUNTS, "description": "The inventory change you expect, negative consumed and positive produced; for a probe, the output slot."},
        },
        "required": ["action"],
        "additionalProperties": False,
    },
    "strict": False,
}


def row(change: str | None, goal: str, seed: int, budget: int = 350, inventory: dict[str, int] | None = None) -> dict[str, Any]:
    """A NeMo Gym dataset row: the policy's prompt and tool, and the fields /reset builds the world from."""
    return {
        "responses_create_params": {"input": [{"role": "user", "content": _prompt(goal, budget)}], "tools": [TOOL]},
        "change": change, "goal": goal, "seed": seed, "budget": budget, "inventory": inventory or {},
    }


class Episode:
    """One rollout of the world a row names, played one tool call at a time."""

    def __init__(self, metadata: Mapping[str, Any]):
        change = metadata["change"]
        ruleset = VANILLA if change is None else apply({c.id: c for c in enumerate_class()}[change], VANILLA)
        task = Task("gym", metadata["goal"], budget=metadata["budget"], inventory=dict(metadata["inventory"]))
        self.world = GridWorld(task, metadata["seed"], ruleset, server=f"grid/{change or 'vanilla'}")
        self.revised = False

    def observation(self) -> str:
        return json.dumps(asdict(self.world.observe()))

    def turn(self, calls: list[tuple[str, str]]) -> tuple[list[dict[str, Any]], float, bool, bool]:
        """One response's tool calls as (name, arguments): each call's result, the reward, terminated, truncated."""
        results, reward = [], 0.0
        for name, arguments in calls:
            result, paid = self.act(arguments) if name == "act" else ({"ok": False, "message": f"no tool named {name}"}, 0.0)
            results.append(result)
            reward += paid
        success = self.world.success
        # Holding the goal ends the episode, and so does a response without a call, as a final answer does for gymnasium_agent.
        return results, reward + float(success), success or not calls, self.world.done and not success

    def act(self, arguments: str) -> tuple[dict[str, Any], float]:
        """Run one `act` call: what the step showed, and 1 when it is the first revised prediction to come true."""
        try:
            action, predicted = _parse(arguments)
        except (ValueError, KeyError, TypeError) as exc:
            return {"ok": False, "message": f"bad arguments: {exc}"}, 0.0
        # What an unchanged server would show for the same step: this world copied under the vanilla rules.
        vanilla = deepcopy(self.world)
        vanilla.ruleset = VANILLA
        _, expected = _shown(vanilla, action)
        result, observed = _shown(self.world, action)
        # ponytail: one revision reward per episode, which is once per rule in the single-rule change class; key it by rule
        # if a world changes several.
        paid = result.ok and not self.revised and predicted == observed != expected
        self.revised |= paid
        return {
            "ok": result.ok, "message": result.message, "output": result.output, "observed": observed,
            "observation": asdict(result.observation),
        }, float(paid)


def _shown(world: GridWorld, action: Action) -> tuple[StepResult, dict[str, int]]:
    """Step `world`: the result, and what the step showed, the output slot for a probe and the inventory change otherwise."""
    before = world.observe().inventory
    result = world.step(action)
    return result, ((result.output or {}) if action.name == "probe" else diff(before, result.observation.inventory))


def _parse(arguments: str) -> tuple[Action, dict[str, int] | None]:
    """The action and predicted change in tool-call arguments a model wrote."""
    args = json.loads(arguments)
    name, target, grid, predicted = args["action"], args.get("target"), args.get("grid"), args.get("predicted")
    if not isinstance(name, str) or not isinstance(target, str | None):
        raise ValueError("action and target must be strings")
    for counts in (grid, predicted):
        if counts is not None and not (isinstance(counts, dict) and all(isinstance(n, int) for n in counts.values())):
            raise ValueError("grid and predicted must map item names to integers")
    return Action(name, target, grid), predicted


def _prompt(goal: str, budget: int) -> str:
    lines = []
    for rule in rules_from_ruleset(VANILLA):
        needs = rule.tool if rule.action == "mine" else rule.near
        lines.append(f"- {rule.action} {rule.target}: {json.dumps(rule.delta)}" + (f", needs a {needs} held" if needs else ""))
    rules = "\n".join(lines)
    return f"""Hold 1 {goal} within {budget} actions in a 2D grid version of Minecraft. Call act once per action.

move steps one block. look reports the nearest block along each heading. mine takes the block you stand on.
craft makes one batch of an item. probe places grid in the crafting grid, reports the output slot, and takes it all back.

The rules as known, each an inventory change, negative consumed and positive produced:
{rules}

This server may have changed one of them. Pass predicted with the change you expect. The first prediction that departs
from these rules and comes true earns 1, and ending with the {goal} earns 1."""


if find_spec("resources_servers") is not None:  # installed with nemo-gym; the core gate runs without it
    from nemo_gym.openai_utils import NeMoGymResponse
    from resources_servers.gymnasium import GymnasiumServer

    class BreachGym(GymnasiumServer):
        """Resources server for gymnasium_agent: /reset builds a row's world, /step plays a response's tool calls."""

        ray_enabled = False

        async def reset(self, metadata: dict, session_id: str | None = None) -> tuple[str, dict]:
            episode = Episode(metadata)
            self.session_state[session_id] = episode
            return episode.observation(), {}

        async def step(self, action: NeMoGymResponse, metadata: dict, session_id: str | None = None) -> tuple[None, float, bool, bool, dict]:
            calls = [item for item in action.output if item.type == "function_call"]
            results, reward, terminated, truncated = self.session_state[session_id].turn([(c.name, c.arguments) for c in calls])
            return None, reward, terminated, truncated, {"tool_outputs": [self.tool_output(c, r) for c, r in zip(calls, results)]}
