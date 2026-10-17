from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from .rules import TOOL_TIERS, Rule

Position = tuple[int, int]
DIRECTIONS: dict[str, Position] = {"east": (1, 0), "west": (-1, 0), "south": (0, 1), "north": (0, -1)}
RADIUS = 8


@dataclass(frozen=True)
class Recipe:
    inputs: dict[str, int]
    output: int
    station: str | None = "crafting_table"


@dataclass(frozen=True)
class Ruleset:
    recipes: dict[str, Recipe]
    drops: dict[str, dict[str, int]]
    tools: dict[str, str | None]


VANILLA = Ruleset(
    recipes={
        "planks": Recipe({"log": 1}, 4, None),
        "stick": Recipe({"planks": 2}, 4, None),
        "crafting_table": Recipe({"planks": 4}, 1, None),
        "torch": Recipe({"coal": 1, "stick": 1}, 4, None),
        "wooden_pickaxe": Recipe({"planks": 3, "stick": 2}, 1),
        "stone_pickaxe": Recipe({"cobblestone": 3, "stick": 2}, 1),
        "furnace": Recipe({"cobblestone": 8}, 1),
        "ladder": Recipe({"stick": 7}, 3),
    },
    drops={"log": {"log": 1}, "stone": {"cobblestone": 1}, "coal_ore": {"coal": 1}},
    tools={"log": None, "stone": "wooden_pickaxe", "coal_ore": "wooden_pickaxe"},
)


def rules_from_ruleset(ruleset: Ruleset, status: str = "hypothesis", scope: str = "global", source: str = "prior") -> list[Rule]:
    rules = []
    for item, recipe in ruleset.recipes.items():
        delta = {k: -v for k, v in recipe.inputs.items()}
        delta[item] = delta.get(item, 0) + recipe.output
        rules.append(Rule(f"craft:{item}", "craft", item, delta, None, recipe.station, "exact", status, scope, source))
    for block, drop in ruleset.drops.items():
        rules.append(Rule(f"mine:{block}", "mine", block, dict(drop), ruleset.tools.get(block), block, "exact", status, scope, source))
    return rules


@dataclass(frozen=True)
class Task:
    task_id: str
    goal: str
    count: int = 1
    budget: int = 150
    inventory: dict[str, int] = field(default_factory=dict)
    min_log_distance: int = 0


@dataclass(frozen=True)
class Action:
    name: str
    target: str | None = None
    grid: dict[str, int] | None = None


@dataclass(frozen=True)
class Observation:
    server: str
    position: Position
    inventory: dict[str, int]
    visible: list[tuple[int, int, str]]
    action_count: int
    budget: int
    done: bool
    success: bool


@dataclass(frozen=True)
class StepResult:
    ok: bool
    message: str
    output: dict[str, int] | None
    observation: Observation
    events: list[str] = field(default_factory=list)  # death, damage, despawn; the grid has no hazards


def layout(seed: int, min_log_distance: int = 0) -> dict[Position, str]:
    rng = random.Random(seed)
    blocks: dict[Position, str] = {}

    def place(block: str, count: int, lo: int, hi: int) -> None:
        while count:
            x, z = rng.randint(-hi, hi), rng.randint(-hi, hi)
            if lo <= abs(x) + abs(z) <= hi and (x, z) not in blocks and (x, z) != (0, 0):
                blocks[(x, z)] = block
                count -= 1

    place("log", 12, max(1, min_log_distance), max(RADIUS + 2, min_log_distance + 6))
    place("stone", 14, 2, 12)
    place("coal_ore", 4, 4, 14)
    return blocks


def held_tier(inventory: Counter) -> int:
    return max((tier for tool, tier in TOOL_TIERS.items() if tool and inventory[tool] > 0), default=0)


class GridWorld:
    """Deterministic 2D world with a Minecraft-shaped action space."""

    def __init__(self, task: Task, seed: int, ruleset: Ruleset = VANILLA, inventory: dict[str, int] | None = None, server: str = "grid/vanilla"):
        self.task = task
        self.ruleset = ruleset
        self.server = server
        self.blocks = layout(seed, task.min_log_distance)
        self.inventory = Counter(task.inventory if inventory is None else inventory)
        self.position: Position = (0, 0)
        self.actions = 0

    @property
    def success(self) -> bool:
        return self.inventory[self.task.goal] >= self.task.count

    @property
    def done(self) -> bool:
        return self.success or self.actions >= self.task.budget

    def observe(self) -> Observation:
        x0, z0 = self.position
        visible = sorted((x, z, b) for (x, z), b in self.blocks.items() if abs(x - x0) + abs(z - z0) <= RADIUS)
        return Observation(
            self.server, self.position, {k: v for k, v in self.inventory.items() if v > 0},
            visible, self.actions, self.task.budget, self.done, self.success,
        )

    def step(self, action: Action) -> StepResult:
        if self.done:
            return self._result(False, "episode is over")
        self.actions += 1
        handler = {"move": self._move, "mine": self._mine, "craft": self._craft, "probe": self._probe}.get(action.name)
        if handler is None:
            return self._result(False, f"unknown action {action.name}")
        return handler(action)

    def _result(self, ok: bool, message: str, output: dict[str, int] | None = None) -> StepResult:
        return StepResult(ok, message, output, self.observe())

    def _move(self, action: Action) -> StepResult:
        offset = DIRECTIONS.get(action.target or "")
        if offset is None:
            return self._result(False, "move needs a cardinal direction")
        self.position = (self.position[0] + offset[0], self.position[1] + offset[1])
        return self._result(True, f"moved {action.target}")

    def _mine(self, action: Action) -> StepResult:
        block = self.blocks.get(self.position)
        if block is None:
            return self._result(False, "nothing to mine here")
        needed = self.ruleset.tools.get(block)
        if TOOL_TIERS[needed] > held_tier(self.inventory):
            return self._result(False, f"{block} needs a {needed}")
        del self.blocks[self.position]
        self.inventory.update(self.ruleset.drops.get(block, {}))
        return self._result(True, f"mined {block}")

    def _craft(self, action: Action) -> StepResult:
        recipe = self.ruleset.recipes.get(action.target or "")
        if recipe is None:
            return self._result(False, f"no recipe for {action.target}")
        if recipe.station and self.inventory[recipe.station] < 1:
            return self._result(False, f"{action.target} needs a {recipe.station}")
        missing = {k: v - self.inventory[k] for k, v in recipe.inputs.items() if self.inventory[k] < v}
        if missing:
            return self._result(False, f"missing {missing}")
        self.inventory.subtract(recipe.inputs)
        self.inventory[action.target] += recipe.output
        return self._result(True, f"crafted {recipe.output} {action.target}")

    def _probe(self, action: Action) -> StepResult:
        """Place `grid` in the crafting grid, read the output slot, take everything back."""
        grid = action.grid or {}
        if any(self.inventory[k] < v for k, v in grid.items()):
            return self._result(True, "cannot place what is not held", {})
        for item, recipe in self.ruleset.recipes.items():
            if recipe.inputs == grid and not (recipe.station and self.inventory[recipe.station] < 1):
                return self._result(True, f"output slot shows {recipe.output} {item}", {item: recipe.output})
        return self._result(True, "output slot is empty", {})
